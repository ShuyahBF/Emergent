# securite_postes.py — Lot 373 : SÉCURITÉ DES POSTES CLIENTS (alertes envoyées par le service Windows Loois).
#
# Demande du propriétaire (11/11/2026) : des tiers non agréés installent des outils sur les postes des clients qui font tourner
# Aizenta, Biolog ou eKol ; leurs communications perturbent celles des postes avec les serveurs HFSQL (ports…) et des clés USB
# infectées sont branchées. Loois (agent « AgentSecurite » du service Windows, voir le dépôt Loois, docs/SECURITE_POSTES.md)
# OBSERVE chaque poste et ALERTE SAWALI ; le propriétaire SEUL approuve ou ignore.
#
# Deux côtés :
#   POSTE (service Loois)  : POST /api/securite-poste/evenements
#       en-têtes : X-Loois-Cle (clé client Loois ou clé commune), X-Loois-Ecole, X-Loois-Poste, X-Loois-Agent: service
#       corps    : {"poste", "site", "version", "evenements": [{"type", "gravite", "detail", "cle"}]}
#       réponse  : {"ok": true, "approuves": {"logiciels": [...], "chemins": [...], "usb": [...]}} — les éléments approuvés par le
#                  propriétaire, que Loois ajoute à la référence du poste (Loois envoie aussi un corps vide toutes les 10 minutes
#                  pour recevoir les approbations).
#   ADMINISTRATEUR (écran Plateformes → Loois → Synchro → « 🛡️ Sécurité des postes ») :
#       GET  /api/admin/securite-postes            → postes, alertes (les nouvelles d'abord), compteurs
#       POST /api/admin/securite-postes/decision   {machine, cle, decision: approuver | ignorer | reouvrir}
#       GET  /api/admin/securite-postes/export.csv → toutes les alertes (CSV)
#
# AUCUNE nouvelle collection (règle du propriétaire : cluster MongoDB plein) : tout est gardé dans la fiche de la machine de la
# collection existante `inventaires_postes` (une fiche par machine), sous le champ « securite » :
#   {"site", "client", "version", "derniere_synchro", "evenements": [...], "approuves": {"logiciels", "chemins", "usb"}}
# Chaque alerte : {"cle", "type", "gravite", "detail", "vu_le", "statut": nouvelle | approuvee | ignoree, "decide_le", "decide_par"}.
# Une alerte (même clé) n'est jamais enregistrée deux fois. Plafonds : 100 alertes par envoi, 200 par poste (les plus anciennes
# DÉJÀ TRAITÉES partent d'abord), 500 éléments approuvés par liste.
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response

# type d'alerte → gravité par défaut (celle envoyée par le poste est gardée si elle est valable)
TYPES: Dict[str, str] = {
    "reference_creee": "info",
    "logiciel_nouveau": "moyenne",
    "programme_inconnu_reseau": "moyenne",
    "usb_nouveau": "moyenne",
    "port_hfsql_occupe": "haute",
    "usb_politique_modifiee": "haute",
}
LIBELLES_TYPES: Dict[str, str] = {
    "reference_creee": "Référence du poste créée",
    "logiciel_nouveau": "Nouveau logiciel installé",
    "programme_inconnu_reseau": "Programme inconnu qui communique",
    "usb_nouveau": "Nouvelle clé USB",
    "port_hfsql_occupe": "Port HFSQL occupé",
    "usb_politique_modifiee": "Blocage USB modifié",
}
GRAVITES = ("info", "moyenne", "haute")
STATUTS = ("nouvelle", "approuvee", "ignoree")
DECISIONS = ("approuver", "ignorer", "reouvrir")
MAX_PAR_ENVOI = 100
MAX_PAR_POSTE = 200
MAX_APPROUVES = 500
MAX_POSTES = 2000


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


# ====================================================================================================
# Logique pure (testée sans base)
# ====================================================================================================

def nettoyer_envoi(corps: Any) -> Tuple[str, str, str, List[Dict[str, str]]]:
    """Corps envoyé par le poste → (poste, site, version, alertes valables). Lève ValueError si le poste est absent."""
    if not isinstance(corps, dict):
        raise ValueError("corps JSON attendu")
    poste = str(corps.get("poste") or "").strip()[:80]
    if not poste:
        raise ValueError("poste attendu")
    site = str(corps.get("site") or "").strip()[:120]
    version = str(corps.get("version") or "").strip()[:40]
    brutes = corps.get("evenements")
    alertes: List[Dict[str, str]] = []
    for e in (brutes if isinstance(brutes, list) else [])[:MAX_PAR_ENVOI]:
        if not isinstance(e, dict):
            continue
        type_ = str(e.get("type") or "")
        cle = str(e.get("cle") or "").strip()[:300]
        if type_ not in TYPES or not cle:
            continue                                         # type inconnu ou sans clé : ignoré
        gravite = str(e.get("gravite") or "")
        alertes.append({"cle": cle, "type": type_, "gravite": gravite if gravite in GRAVITES else TYPES[type_],
                        "detail": str(e.get("detail") or "").strip()[:400]})
    return poste, site, version, alertes


def fusionner_alertes(existantes: List[Dict[str, Any]], nouvelles: List[Dict[str, str]], maintenant: str) -> List[Dict[str, Any]]:
    """Ajoute les alertes dont la clé est nouvelle (statut « nouvelle ») ; plafonne à MAX_PAR_POSTE en retirant d'abord les plus
    anciennes alertes déjà traitées, puis, à défaut, les plus anciennes."""
    liste = [dict(a) for a in existantes]
    connues = {a.get("cle") for a in liste}
    for a in nouvelles:
        if a["cle"] in connues:
            continue
        connues.add(a["cle"])
        liste.append({**a, "vu_le": maintenant, "statut": "nouvelle", "decide_le": None, "decide_par": None})
    while len(liste) > MAX_PAR_POSTE:
        traitees = [i for i, a in enumerate(liste) if a.get("statut") != "nouvelle"]
        del liste[traitees[0] if traitees else 0]
    return liste


def valeur_approuvable(alerte: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """(liste, valeur) à ajouter aux approbations pour cette alerte, ou None si elle n'est pas approuvable.
    La clé de l'alerte contient déjà la valeur normalisée par Loois : « logiciel|nom », « reseau|chemin », « port|4900|chemin »,
    « usb|identifiant »."""
    cle = str(alerte.get("cle") or "")
    type_ = alerte.get("type")
    if type_ == "logiciel_nouveau" and cle.startswith("logiciel|"):
        return "logiciels", cle.split("|", 1)[1]
    if type_ == "programme_inconnu_reseau" and cle.startswith("reseau|"):
        return "chemins", cle.split("|", 1)[1]
    if type_ == "port_hfsql_occupe" and cle.startswith("port|") and cle.count("|") >= 2:
        return "chemins", cle.split("|", 2)[2]
    if type_ == "usb_nouveau" and cle.startswith("usb|"):
        return "usb", cle.split("|", 1)[1]
    return None


def appliquer_decision(securite: Dict[str, Any], cle: str, decision: str, par: str, maintenant: str) -> Dict[str, Any]:
    """Applique la décision du propriétaire sur l'alerte `cle` de la fiche `securite` (modifiée sur place).
    approuver : alerte approuvable seulement ; l'élément rejoint `approuves` (envoyé au poste à son prochain signal).
    ignorer   : l'alerte est classée sans approbation.
    reouvrir  : seulement pour une alerte ignorée (une approbation est déjà partie sur le poste : non révocable à distance).
    Lève ValueError avec un message lisible si la décision est impossible."""
    if decision not in DECISIONS:
        raise ValueError("décision inconnue")
    alerte = next((a for a in securite.get("evenements", []) if a.get("cle") == cle), None)
    if alerte is None:
        raise ValueError("alerte introuvable")
    if decision == "approuver":
        valeur = valeur_approuvable(alerte)
        if valeur is None:
            raise ValueError("cette alerte ne s'approuve pas : classez-la avec « Ignorer »")
        liste, element = valeur
        approuves = securite.setdefault("approuves", {"logiciels": [], "chemins": [], "usb": []})
        cible = approuves.setdefault(liste, [])
        if element.lower() not in {x.lower() for x in cible} and len(cible) < MAX_APPROUVES:
            cible.append(element)
        alerte["statut"] = "approuvee"
    elif decision == "ignorer":
        alerte["statut"] = "ignoree"
    else:
        if alerte.get("statut") != "ignoree":
            raise ValueError("seule une alerte ignorée peut être rouverte")
        alerte["statut"] = "nouvelle"
    alerte["decide_le"] = maintenant if decision != "reouvrir" else None
    alerte["decide_par"] = par if decision != "reouvrir" else None
    return alerte


def resume_poste(machine: str, securite: Dict[str, Any]) -> Dict[str, Any]:
    """Ligne d'un poste dans l'écran : compteurs et alertes (les nouvelles d'abord, puis les plus récentes)."""
    alertes = list(securite.get("evenements") or [])
    nouvelles = [a for a in alertes if a.get("statut") == "nouvelle"]
    ordre_gravite = {"haute": 0, "moyenne": 1, "info": 2}
    alertes.sort(key=lambda a: (a.get("statut") != "nouvelle", ordre_gravite.get(a.get("gravite"), 3), _inverse(a.get("vu_le"))))
    gravite_max = min((a.get("gravite") for a in nouvelles), key=lambda g: ordre_gravite.get(g, 3), default=None)
    approuves = securite.get("approuves") or {}
    return {
        "machine": machine, "site": securite.get("site") or "", "client": securite.get("client") or "",
        "version": securite.get("version") or "", "derniere_synchro": securite.get("derniere_synchro"),
        "nouvelles": len(nouvelles), "gravite_max": gravite_max, "alertes": alertes,
        "approuves": {k: len(approuves.get(k) or []) for k in ("logiciels", "chemins", "usb")},
    }


def _inverse(texte: Optional[str]) -> str:
    """Clé de tri décroissante sur une date ISO (les plus récentes d'abord) sans dépendre du type."""
    return "".join(chr(0x10FFFF - ord(c)) for c in (texte or ""))


def tableau_csv(postes: List[Dict[str, Any]]) -> str:
    """Toutes les alertes de tous les postes, en CSV (séparateur « ; », ouverture directe dans Excel)."""
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";")
    w.writerow(["Poste", "Site", "Client", "Date", "Gravité", "Type", "Détail", "Statut", "Décidé le", "Décidé par"])
    for p in postes:
        for a in p["alertes"]:
            w.writerow([p["machine"], p["site"], p["client"], a.get("vu_le") or "", a.get("gravite") or "",
                        LIBELLES_TYPES.get(a.get("type"), a.get("type")), a.get("detail") or "", a.get("statut") or "",
                        a.get("decide_le") or "", a.get("decide_par") or ""])
    return "﻿" + sortie.getvalue()


# ====================================================================================================
# Routes
# ====================================================================================================

def setup_securite_postes_routes(*, db, api, get_current_user) -> None:
    """Branche les routes du lot 373 (appelée depuis server_parts/p20)."""

    def admin(user: dict) -> None:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    @api.post("/securite-poste/evenements", tags=["Sécurité des postes"])
    async def recevoir(request: Request):
        """Alertes envoyées par le service Loois d'un poste ; répond avec les éléments approuvés par le propriétaire."""
        from routes import loois_cles_clients as cles   # import tardif (évite une boucle d'imports)
        entete_cle = request.headers.get("X-Loois-Cle") or request.headers.get("X-Cle-Loois")
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001 — corps illisible
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        try:
            poste, site, version, alertes = nettoyer_envoi(corps)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        # Seul un poste muni d'une clé client (ou de la clé commune) peut écrire : jamais d'alerte anonyme
        identite = await cles.identifier_cle(db, entete_cle, machine=poste)
        if not identite:
            raise HTTPException(status_code=401, detail="clé Loois invalide")
        cle_machine = poste.upper()
        fiche = await db.inventaires_postes.find_one({"machine_cle": cle_machine}, {"_id": 0, "securite": 1}) or {}
        if not fiche and await db.inventaires_postes.count_documents({}) >= MAX_POSTES:
            raise HTTPException(status_code=429, detail="trop de postes enregistrés")
        securite = fiche.get("securite") or {}
        maintenant = _maintenant()
        securite["evenements"] = fusionner_alertes(securite.get("evenements") or [], alertes, maintenant)
        securite.setdefault("approuves", {"logiciels": [], "chemins": [], "usb": []})
        securite.update({"site": site or securite.get("site") or "", "version": version, "derniere_synchro": maintenant,
                         "client": cles.libelle_identite(identite) or securite.get("client") or ""})
        await db.inventaires_postes.update_one({"machine_cle": cle_machine}, {"$set": {
            "machine": poste, "machine_cle": cle_machine, "securite": securite}}, upsert=True)
        a = securite["approuves"]
        return {"ok": True, "approuves": {k: list(a.get(k) or []) for k in ("logiciels", "chemins", "usb")}}

    async def charger_postes() -> List[Dict[str, Any]]:
        curseur = db.inventaires_postes.find({"securite": {"$exists": True}}, {"_id": 0, "machine": 1, "securite": 1})
        postes = [resume_poste(f.get("machine") or "?", f["securite"]) async for f in curseur.limit(MAX_POSTES)]
        # Postes avec des alertes nouvelles d'abord (les plus graves en tête), puis par nom
        ordre = {"haute": 0, "moyenne": 1, "info": 2, None: 3}
        postes.sort(key=lambda p: (p["nouvelles"] == 0, ordre.get(p["gravite_max"], 3), p["machine"].lower()))
        return postes

    @api.get("/admin/securite-postes", tags=["Sécurité des postes"])
    async def liste(user: dict = Depends(get_current_user)):
        admin(user)
        postes = await charger_postes()
        return {"postes": postes, "nouvelles": sum(p["nouvelles"] for p in postes), "libelles_types": LIBELLES_TYPES}

    @api.post("/admin/securite-postes/decision", tags=["Sécurité des postes"])
    async def decider(request: Request, user: dict = Depends(get_current_user)):
        admin(user)
        try:
            corps = await request.json()
            machine = str(corps.get("machine") or "").strip()[:80]
            cle = str(corps.get("cle") or "").strip()[:300]
            decision = str(corps.get("decision") or "")
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        fiche = await db.inventaires_postes.find_one({"machine_cle": machine.upper()}, {"_id": 0, "securite": 1})
        if not fiche or not fiche.get("securite"):
            raise HTTPException(status_code=404, detail="Poste inconnu")
        securite = fiche["securite"]
        try:
            alerte = appliquer_decision(securite, cle, decision, user.get("full_name") or user.get("email") or user.get("id") or "admin", _maintenant())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        await db.inventaires_postes.update_one({"machine_cle": machine.upper()}, {"$set": {"securite": securite}})
        return {"ok": True, "alerte": alerte}

    @api.get("/admin/securite-postes/export.csv", tags=["Sécurité des postes"])
    async def exporter(user: dict = Depends(get_current_user)):
        admin(user)
        return Response(content=tableau_csv(await charger_postes()), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'inline; filename="securite_postes.csv"'})
