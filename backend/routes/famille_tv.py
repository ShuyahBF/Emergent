"""Lot 418 — Télé des familles : projeter des vidéos sur un téléviseur depuis l'application Personnel de maison.

Règles du propriétaire (15/11/2026) :
  - SEUL LE DÉTENTEUR DE L'APPAREIL lance sa projection sur la télé : les ordres passent par l'identité de l'appareil (en-têtes X-Famille-Compte /
    X-Famille-Jeton) ; l'administrateur de SAWALI et les autres membres de la famille ne peuvent pas piloter la télé d'un appareil ;
  - ABONNEMENT NÉCESSAIRE, et prix selon le nombre d'APPAREILS du foyer et de POSTES TV (téléviseurs) : chaque formule (créée dans Paramètres → « Formules des
    plateformes », plateforme « Personnel de maison », fonction « Télé ») porte deux limites : « appareils » (le titulaire compris) et « postes_tv ».

Pour un développeur WinDev (le « foyer » sans nouveau fichier) :
  - le TITULAIRE est celui qui paie la formule (même circuit que les autres formules : PawaPay / PI-SPI, parrainage, cumul des durées) ;
  - les appareils COUVERTS sont les proches ayant un lien VÉRIFIÉ avec le titulaire (« Ma famille »), dans l'ordre de création des liens, jusqu'à
    « appareils − 1 » ; le calcul est refait à chaque demande, rien n'est stocké en plus ;
  - les postes TV de la formule sont partagés par le titulaire et ses appareils couverts ;
  - une télé est appairée par le détenteur avec le CODE affiché par la page /tv de la télé (comme pour les écrans TV de l'administration) ;
    l'écran enregistré porte « proprietaire_compte » : la télécommande de l'administrateur ne le voit pas et ne le commande pas.
Les vidéos proposées sont celles de la Bibliothèque de médias que l'administrateur a marquées « Visible dans Personnel de maison ».
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, Header, HTTPException
from pydantic import BaseModel

from routes.ecran_tv import VALIDITE_CODE_MIN, modules_valides
from routes.formules_plateformes import AchatIn, AcheterIn, Utilisateur
from routes.tv_video import ACTIONS, DELTA_MAX_S, EN_LIGNE_S, PREFIXE

logger = logging.getLogger("sawali.famille_tv")

PLATEFORME = "personnelmaison"
FONCTION = "tv_video"


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def meilleur_abonnement(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Abonnement « télé » actif du membre qui couvre le plus d'appareils (à égalité : le plus long). Limites par défaut : 1 appareil, 1 poste TV."""
    maintenant = _maintenant().isoformat()
    candidats = []
    for a in (m.get("abonnements") or {}).values():
        if FONCTION in (a.get("fonctions") or []) and (a.get("expire_le") or "") > maintenant:
            lim = a.get("limites") or {}
            candidats.append({"nom": a.get("nom") or "Formule", "expire_le": a["expire_le"], "appareils": max(1, int(lim.get("appareils") or 1)),
                              "postes_tv": max(1, int(lim.get("postes_tv") or 1))})
    return max(candidats, key=lambda c: (c["appareils"], c["expire_le"])) if candidats else None


def setup_famille_tv_routes(*, db, api, outils, authentifier):
    async def _compte(x_famille_compte: Optional[str] = Header(None), x_famille_jeton: Optional[str] = Header(None)) -> dict:
        compte = await authentifier(db, x_famille_compte, x_famille_jeton)
        if not compte:
            raise HTTPException(status_code=401, detail="Compte famille non reconnu.")
        return compte

    def _utilisateur(compte: dict) -> Utilisateur:
        return Utilisateur(id=str(compte["_id"]), nom=str(compte.get("nom") or "")[:120])

    async def _liens_verifies(compte_id: str) -> List[str]:
        """Comptes liés (lien VÉRIFIÉ) à ce compte, dans l'ordre de création des liens."""
        liens = await db.famille_liens.find({"comptes": compte_id, "statut": "verifie"}).sort("cree_le", 1).to_list(200)
        return [next(c for c in l["comptes"] if c != compte_id) for l in liens]

    async def _abonnement_de(compte_id: str) -> Optional[Dict[str, Any]]:
        m = await db.membres_plateformes.find_one({"plateforme": PLATEFORME, "utilisateur_id": compte_id}, {"_id": 0})
        return meilleur_abonnement(m) if m else None

    async def _groupe(titulaire_id: str, appareils: int) -> List[str]:
        """Le titulaire + ses appareils couverts (les « appareils − 1 » premiers liens vérifiés)."""
        return [titulaire_id] + (await _liens_verifies(titulaire_id))[:max(0, appareils - 1)]

    async def couverture(compte_id: str) -> Optional[Dict[str, Any]]:
        """Comment ce compte a droit à la télé : abonnement propre (« titulaire ») ou couvert par l'abonnement d'un proche (« couvert »)."""
        propre = await _abonnement_de(compte_id)
        if propre:
            return {"role": "titulaire", "titulaire_id": compte_id, **propre}
        for autre in await _liens_verifies(compte_id):
            abo = await _abonnement_de(autre)
            if abo and compte_id in (await _groupe(autre, abo["appareils"])):
                return {"role": "couvert", "titulaire_id": autre, **abo}
        return None

    async def _exiger(compte: dict) -> Dict[str, Any]:
        """Couverture active, sinon 402 « abonnement requis » avec le nom et le prix de la formule la moins chère."""
        c = await couverture(str(compte["_id"]))
        if c:
            return c
        m = await outils.membre(PLATEFORME, _utilisateur(compte))
        await outils.exiger_abonnement(PLATEFORME, m, FONCTION, "La projection sur télé")
        raise HTTPException(status_code=402, detail={"code": "abonnement_requis", "message": "La projection sur télé est réservée aux abonnés.", "formule": None})

    async def _ecrans() -> List[Dict[str, Any]]:
        g = await db.settings.find_one({"_id": "global"}, {"tv_ecrans": 1}) or {}
        return g.get("tv_ecrans") or []

    async def _mon_ecran(compte_id: str, ecran_id: str) -> Dict[str, Any]:
        """Écran appairé par CE compte ; les écrans des autres (et ceux de l'administration) sont refusés."""
        e = next((x for x in await _ecrans() if x.get("id") == ecran_id), None)
        if not e:
            raise HTTPException(status_code=404, detail="Télé introuvable")
        if e.get("proprietaire_compte") != compte_id:
            raise HTTPException(status_code=403, detail="Seul le détenteur de l'appareil qui a appairé cette télé peut lancer une projection.")
        return e

    async def _postes_utilises(groupe: List[str]) -> int:
        return sum(1 for e in await _ecrans() if e.get("proprietaire_compte") in groupe)

    async def _doc(ecran_id: str) -> Dict[str, Any]:
        d = await db.settings.find_one({"_id": PREFIXE + ecran_id}) or {"_id": PREFIXE + ecran_id}
        d.setdefault("seq", 0); d.setdefault("commande", None); d.setdefault("etat", None)
        return d

    def _en_ligne(d: Dict[str, Any], ecran: Dict[str, Any]) -> bool:
        limite = (_maintenant() - timedelta(seconds=EN_LIGNE_S)).isoformat()
        return any(v and v >= limite for v in (d.get("vu"), (d.get("etat") or {}).get("maj"), ecran.get("vu_le")))

    # ------------------------------------------------------------------ abonnement
    @api.get("/famille/tv/abonnement", tags=["Ma famille — Télé"])
    async def abonnement(compte: dict = Depends(_compte)):
        """Mon droit à la télé, les appareils et postes TV utilisés, et les formules proposées (prix selon appareils et postes TV)."""
        cid = str(compte["_id"])
        cat = await outils.catalogue_coeur(PLATEFORME, _utilisateur(compte))
        formules = [f for f in cat["formules"] if FONCTION in (f.get("fonctions") or [])]
        c = await couverture(cid)
        sortie: Dict[str, Any] = {"actif": bool(c), "formules": formules}
        if c:
            groupe = await _groupe(c["titulaire_id"], c["appareils"])
            noms = {str(x["_id"]): x.get("nom", "?") async for x in db.famille_comptes.find({"_id": {"$in": groupe}}, {"nom": 1})}
            expire = datetime.fromisoformat(c["expire_le"])
            sortie.update({"role": c["role"], "formule": c["nom"], "expire_le": c["expire_le"], "jours_restants": max(0, (expire - _maintenant()).days),
                           "limites": {"appareils": c["appareils"], "postes_tv": c["postes_tv"]}, "titulaire": noms.get(c["titulaire_id"], "?"),
                           "appareils_couverts": [noms.get(g, "?") for g in groupe], "postes_utilises": await _postes_utilises(groupe)})
        return sortie

    @api.post("/famille/tv/acheter", tags=["Ma famille — Télé"])
    async def acheter(donnees: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        """Page de paiement (PawaPay) d'une formule « télé » : seules les formules qui débloquent la télé sont achetables ici."""
        fid = str(donnees.get("formule_id") or "")
        f = await db.formules_plateformes.find_one({"id": fid, "plateforme": PLATEFORME, "actif": True}, {"_id": 0})
        if not f or FONCTION not in (f.get("fonctions") or []):
            raise HTTPException(status_code=422, detail="Formule inconnue")
        retour = str(donnees.get("retour") or "")[:400]
        return await outils.acheter_coeur(PLATEFORME, AcheterIn(utilisateur=_utilisateur(compte), formule_id=fid, retour=retour))

    @api.post("/famille/tv/achat", tags=["Ma famille — Télé"])
    async def achat(donnees: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        return await outils.achat_coeur(PLATEFORME, AchatIn(utilisateur=_utilisateur(compte), deposit_id=str(donnees.get("deposit_id") or "")))

    # ------------------------------------------------------------------ mes télés
    @api.get("/famille/tv/ecrans", tags=["Ma famille — Télé"])
    async def mes_ecrans(compte: dict = Depends(_compte)):
        cid = str(compte["_id"])
        sortie = []
        for e in await _ecrans():
            if e.get("proprietaire_compte") != cid:
                continue
            d = await _doc(e["id"])
            sortie.append({"id": e["id"], "nom": e.get("nom") or "Télé", "en_ligne": _en_ligne(d, e), "etat": d.get("etat")})
        return {"ecrans": sortie}

    @api.post("/famille/tv/appairer", tags=["Ma famille — Télé"])
    async def appairer(donnees: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        """Associe la télé qui affiche ce code (page /tv) à CET appareil. Abonnement actif et poste TV disponible exigés."""
        cid = str(compte["_id"])
        c = await _exiger(compte)
        groupe = await _groupe(c["titulaire_id"], c["appareils"])
        if await _postes_utilises(groupe) >= c["postes_tv"]:
            raise HTTPException(status_code=409, detail=f"Limite atteinte : votre formule « {c['nom']} » permet {c['postes_tv']} téléviseur(s). "
                                                        "Retirez une télé ou choisissez une formule avec plus de postes TV.")
        code = str(donnees.get("code") or "").strip().upper().replace(" ", "").replace("-", "")
        nom = str(donnees.get("nom") or "").strip()[:60] or "Télévision"
        g = await db.settings.find_one({"_id": "global"}, {"tv_appairages": 1}) or {}
        limite = (_maintenant() - timedelta(minutes=VALIDITE_CODE_MIN)).isoformat()
        appairage = next((a for a in g.get("tv_appairages") or [] if a.get("code") == code and a.get("cree_le", "") >= limite), None)
        if not appairage:
            raise HTTPException(status_code=404, detail="Code inconnu ou expiré : relancez la page /tv sur la télé pour obtenir un nouveau code.")
        ecran = {"id": uuid.uuid4().hex, "nom": nom, "code": code, "client_id": "", "client_nom": "", "modules": modules_valides({"video": True}),
                 "rdv_portee": "tous", "rdv_clair": False, "rdv_medecin": "", "empreinte": appairage["empreinte"], "cree_le": _maintenant().isoformat(),
                 "cree_par": "famille:" + cid, "vu_le": None, "proprietaire_compte": cid, "proprietaire_nom": str(compte.get("nom") or "")[:80]}
        await db.settings.update_one({"_id": "global"}, {"$push": {"tv_ecrans": ecran}, "$pull": {"tv_appairages": {"id": appairage["id"]}}})
        return {"ok": True, "ecran": {"id": ecran["id"], "nom": nom}}

    @api.delete("/famille/tv/ecrans/{ecran_id}", tags=["Ma famille — Télé"])
    async def retirer(ecran_id: str, compte: dict = Depends(_compte)):
        await _mon_ecran(str(compte["_id"]), ecran_id)
        await db.settings.update_one({"_id": "global"}, {"$pull": {"tv_ecrans": {"id": ecran_id}}})
        await db.settings.delete_one({"_id": PREFIXE + ecran_id})
        return {"ok": True}

    # ------------------------------------------------------------------ vidéos et télécommande
    @api.get("/famille/tv/videos", tags=["Ma famille — Télé"])
    async def videos(compte: dict = Depends(_compte)):
        """Vidéos proposées aux familles (marquées « Visible dans Personnel de maison » par l'administrateur)."""
        cur = db.media_library.find({"kind": "video", "pour_familles": True, "is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "title": 1, "description": 1, "size": 1}).sort("created_at", -1).limit(100)
        return {"videos": await cur.to_list(length=100)}

    @api.post("/famille/tv/commande", tags=["Ma famille — Télé"])
    async def commande(corps: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        """Ordre à MA télé : lire (vidéo), pause, reprendre, avancer / reculer (delta), position, stop. Détenteur de l'appareil et abonnement actif exigés."""
        cid = str(compte["_id"])
        ecran = await _mon_ecran(cid, str(corps.get("ecran_id") or ""))
        await _exiger(compte)
        action = str(corps.get("action") or "")
        if action not in ACTIONS:
            raise HTTPException(status_code=422, detail="Action inconnue")
        ordre: Dict[str, Any] = {"action": action, "par": "famille:" + cid, "le": _maintenant().isoformat()}
        if action == "lire":
            m = await db.media_library.find_one({"id": str(corps.get("video_id") or ""), "kind": "video", "pour_familles": True, "is_deleted": {"$ne": True}}, {"_id": 0})
            if not m or not m.get("storage_path"):
                raise HTTPException(status_code=404, detail="Vidéo introuvable")
            ordre.update({"video_id": m["id"], "titre": m.get("title") or m.get("filename") or "Vidéo"})
        elif action in ("avancer", "reculer"):
            ordre["delta"] = max(1, min(int(corps.get("delta") or 10), DELTA_MAX_S))
        elif action == "position":
            ordre["position"] = max(0.0, float(corps.get("position") or 0))
        from pymongo import ReturnDocument
        r = await db.settings.find_one_and_update({"_id": PREFIXE + ecran["id"]}, {"$inc": {"seq": 1}, "$set": {"commande": ordre}}, upsert=True, return_document=ReturnDocument.AFTER)
        return {"ok": True, "seq": (r or {}).get("seq", 1)}

    @api.get("/famille/tv/etat/{ecran_id}", tags=["Ma famille — Télé"])
    async def etat(ecran_id: str, compte: dict = Depends(_compte)):
        ecran = await _mon_ecran(str(compte["_id"]), ecran_id)
        d = await _doc(ecran_id)
        return {"seq": d["seq"], "etat": d.get("etat"), "en_ligne": _en_ligne(d, ecran)}
