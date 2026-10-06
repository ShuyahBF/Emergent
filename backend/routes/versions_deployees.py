# versions_deployees.py — Lot 65 : versions déployées de chaque solution et postes où elles tournent.
#
# Deux sources :
#
# 1. LOGICIELS DE BUREAU (Loois.exe, LooisSyncService…) : chaque programme envoie toutes les
#    5 minutes un « signal de présence » :
#      POST /api/presence-logiciel
#      corps : {"application": "Loois", "version": "1.2610.610.44", "deploye_le": "<ISO>",
#               "machine": "POSTE-ACCUEIL", "utilisateur": "secretariat", "site": "Clinique X",
#               "systeme": "Windows 10.0.19045", "demarre_le": "<ISO>"}
#      en-tête facultatif : X-Cle-Loois = LOOIS_SUPPORT_CLE (variable d'environnement Render)
#    La clé est FACULTATIVE (le service Windows tourne sous le compte Système, qui n'a pas la clé
#    enregistrée par l'utilisateur) : un signal sans clé est accepté mais marqué « non vérifié ».
#    Une seule fiche par (application, machine, composant) : la collection ne grossit pas avec le
#    temps ; au-delà de MAX_POSTES fiches, un poste INCONNU est refusé (protection contre l'abus).
#    « En ligne » = signal reçu depuis moins de EN_LIGNE_MINUTES minutes.
#
# 2. PLATEFORMES WEB (Ster, adLyn, beAuthentik, ALBARKA…) : la version arrive avec leurs
#    statistiques internes (champs facultatifs « version » et « deploye_le » de la réponse, voir
#    stats_plateformes.py). SAWALI lui-même : backend/lot.py + compteur de déploiements.
#
#   GET /api/admin/versions-deployees  (administrateur) → {sawali, plateformes, logiciels}
from __future__ import annotations

import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request  # au niveau du module : l'annotation de la route doit être résolue (from __future__)

EN_LIGNE_MINUTES = 12          # 2 signaux manqués (toutes les 5 min) → hors ligne
MAX_POSTES = 2000              # plafond de fiches (protection contre l'envoi massif de faux postes)
_CHAMPS = {                    # champ → longueur maximale conservée
    "application": 40, "composant": 40, "version": 40, "deploye_le": 40, "machine": 80,
    "utilisateur": 80, "site": 120, "systeme": 120, "demarre_le": 40,
}
_NOM_APPLICATION = re.compile(r"^[A-Za-z0-9 ._\-]{2,40}$")


def _maintenant() -> datetime:
    """Date et heure actuelles (UTC)."""
    return datetime.now(timezone.utc)


def nettoyer_presence(corps: Any) -> Dict[str, str]:
    """Logique pure (testée) : garde seulement les champs connus, en texte court.

    Lève ValueError si l'application, la version ou la machine manquent."""
    if not isinstance(corps, dict):
        raise ValueError("corps JSON attendu")
    propre: Dict[str, str] = {}
    for champ, longueur in _CHAMPS.items():
        valeur = corps.get(champ)
        if valeur is None or isinstance(valeur, (dict, list)):
            continue
        texte = str(valeur).strip()[:longueur]
        if texte:
            propre[champ] = texte
    for obligatoire in ("application", "version", "machine"):
        if not propre.get(obligatoire):
            raise ValueError(f"champ « {obligatoire} » manquant")
    if not _NOM_APPLICATION.match(propre["application"]):
        raise ValueError("nom d'application invalide")
    propre.setdefault("composant", propre["application"])
    return propre


def cle_valide(cle_recue: Optional[str]) -> bool:
    """Vrai si la clé reçue est LOOIS_SUPPORT_CLE (comparaison à temps constant)."""
    attendue = (os.environ.get("LOOIS_SUPPORT_CLE") or "").strip()
    recue = (cle_recue or "").strip()
    return bool(attendue and recue) and hmac.compare_digest(attendue, recue)


def regrouper_logiciels(fiches: List[Dict[str, Any]], maintenant: datetime) -> List[Dict[str, Any]]:
    """Logique pure (testée) : une entrée par application, avec ses postes (en ligne d'abord),
    la version la plus récente vue et le nombre de postes à jour."""
    limite = maintenant - timedelta(minutes=EN_LIGNE_MINUTES)
    par_application: Dict[str, Dict[str, Any]] = {}
    for f in fiches:
        try:
            vu = datetime.fromisoformat(f.get("vu_le") or "")
        except ValueError:
            continue
        poste = {k: f.get(k) for k in ("machine", "composant", "version", "deploye_le", "utilisateur",
                                       "site", "systeme", "demarre_le", "vu_le", "premiere_fois", "verifie")}
        poste["en_ligne"] = vu >= limite
        app = par_application.setdefault(f["application"], {"application": f["application"], "postes": []})
        app["postes"].append(poste)
    sortie = []
    for app in par_application.values():
        postes = app["postes"]
        # Version la plus récente = comparaison numérique 1.2610.610.44 (repli : texte)
        derniere = max((p["version"] for p in postes if p.get("version")), key=_cle_version, default="")
        for p in postes:
            p["a_jour"] = p.get("version") == derniere
        postes.sort(key=lambda p: (not p["en_ligne"], (p.get("machine") or "").lower(), p.get("composant") or ""))
        sortie.append({
            "application": app["application"],
            "derniere_version": derniere,
            "deploye_le": next((p.get("deploye_le") for p in postes if p.get("version") == derniere and p.get("deploye_le")), None),
            "postes": postes,
            "en_ligne": sum(1 for p in postes if p["en_ligne"]),
            "a_jour": sum(1 for p in postes if p["a_jour"]),
        })
    sortie.sort(key=lambda a: a["application"].lower())
    return sortie


def _cle_version(version: str):
    """Clé de tri d'un numéro de version : (1, 2610, 610, 44) ; texte non numérique en dernier recours."""
    try:
        return (1, tuple(int(x) for x in version.split(".")))
    except ValueError:
        return (0, (version,))


def setup_versions_deployees_routes(*, db, api, get_current_user, lire_version=None) -> None:
    """Branche les routes du lot 65 (appelée depuis server_parts/p20).

    lire_version : la fonction de /api/version (p01), pour la version de SAWALI lui-même."""
    from fastapi import Depends, HTTPException

    @api.post("/presence-logiciel", tags=["Versions déployées"])
    async def presence_logiciel(request: Request):
        """Signal de présence d'un logiciel de bureau (Loois…) : version + machine. Jamais de secret renvoyé."""
        try:
            fiche = nettoyer_presence(await request.json())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception:  # noqa: BLE001 — corps illisible
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        cle = {"application": fiche["application"], "machine": fiche["machine"], "composant": fiche["composant"]}
        existe = await db.presences_logiciels.find_one(cle, {"_id": 1})
        if not existe and await db.presences_logiciels.count_documents({}) >= MAX_POSTES:
            raise HTTPException(status_code=429, detail="trop de postes enregistrés")
        maintenant = _maintenant().isoformat()
        await db.presences_logiciels.update_one(cle, {
            "$set": {**fiche, "vu_le": maintenant, "verifie": cle_valide(request.headers.get("X-Cle-Loois")),
                     "adresse_ip": (request.client.host if request.client else None)},
            "$setOnInsert": {"premiere_fois": maintenant},
        }, upsert=True)
        return {"ok": True}

    @api.get("/admin/versions-deployees", tags=["Versions déployées"])
    async def versions_deployees(user: dict = Depends(get_current_user)):
        """Versions de SAWALI, des plateformes web et des logiciels de bureau (avec leurs postes)."""
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        # SAWALI : même calcul que /api/version (lot.py + compteur de déploiements)
        sawali = None
        try:
            if lire_version is not None:
                sawali = await lire_version()
        except Exception:  # noqa: BLE001
            pass
        # Plateformes web : dernière réponse de statistiques réussie (version facultative)
        plateformes = []
        async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "code": 1, "nom": 1, "actif": 1}).sort("nom", 1):
            derniere = await db.plateformes_stats.find_one(
                {"code": e.get("code"), "resultat.ok": True}, {"_id": 0, "resultat": 1}, sort=[("recu_le", -1)])
            res = (derniere or {}).get("resultat") or {}
            plateformes.append({"code": e.get("code"), "nom": e.get("nom") or e.get("code"),
                                "actif": bool(e.get("actif", True)), "version": res.get("version"),
                                "deploye_le": res.get("deploye_le"), "recu_le": res.get("recu_le")})
        fiches = [f async for f in db.presences_logiciels.find({}, {"_id": 0, "adresse_ip": 0})]
        return {"sawali": sawali, "plateformes": plateformes,
                "logiciels": regrouper_logiciels(fiches, _maintenant()),
                "en_ligne_minutes": EN_LIGNE_MINUTES}
