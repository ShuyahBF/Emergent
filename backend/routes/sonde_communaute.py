# routes/sonde_communaute.py — Lot 485 : ESPACE COMMUN de la sonde réseau (téléphones identifiés par un compte Google, synthèse par lieu / connexion / opérateur).
#   POST   /sonde-reseau/participant/echange          le téléphone remet le code reçu après sa connexion Google (+ version du consentement accepté) → jeton d'appareil
#   GET    /sonde-reseau/participant/moi              (jeton) identité, consentement, nombre d'appareils
#   POST   /sonde-reseau/participant/deconnexion      (jeton) révoque le jeton de CET appareil
#   DELETE /sonde-reseau/participant                  (jeton) retrait de l'accord : la fiche du participant et tous ses jetons sont supprimés
#   POST   /sonde-reseau/communaute/envoi             (jeton) UNE mesure : additionnée dans sa cellule (jour × zone de 2 km × connexion × opérateur), jamais gardée seule
#   GET    /sonde-reseau/communaute                   administrateur : synthèse par zone, type de connexion, opérateur
#   GET    /sonde-reseau/communaute/participants      administrateur : participants (e-mail, consentement, appareils, mesures)
#   POST   /sonde-reseau/communaute/participants/{id}/bloquer, DELETE …/{id}   administrateur : bloquer / débloquer, supprimer
# La connexion Google elle-même passe par /auth/google/demarrer?cible=sonde puis /auth/google/retour (voir routes/google_connexion.py).
# Logique pure : backend/sonde_communaute.py. Stockage : deux fiches de `settings`, aucune nouvelle collection. Aucun compte SAWALI n'est créé.
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from fastapi import Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

import google_auth
import sonde_communaute as sc
from ip_client import ip_reelle

LIMITE_ECHANGES_IP = 30            # échanges de code par adresse IP et par heure (anti-essais)
_echanges_par_ip: Dict[str, List[float]] = {}


def _limite_ip(ip: str) -> bool:
    """Compte l'appel ; vrai si l'adresse a dépassé sa limite sur la dernière heure."""
    t = time.monotonic()
    recents = [x for x in _echanges_par_ip.get(ip, []) if t - x < 3600] + [t]
    _echanges_par_ip[ip] = recents[-(LIMITE_ECHANGES_IP + 1):]
    return len(recents) > LIMITE_ECHANGES_IP


# Modèles au NIVEAU DU MODULE (FastAPI ne retrouve pas ceux déclarés dans une fonction : 422)
class Echange(BaseModel):
    code: str = Field(min_length=10, max_length=100)
    consentement_version: int = Field(ge=0, le=1000)           # version du texte accepté sur le téléphone avant la connexion
    appareil: str = Field(min_length=16, max_length=64)        # identifiant ALÉATOIRE de l'installation (hexadécimal, rien de personnel)
    nom_appareil: str = Field("Téléphone", max_length=40)


class MesureCommunaute(BaseModel):
    """Une mesure du téléphone. Toutes les valeurs sont bornées. Le lieu est facultatif (partage désactivable) et recalé sur la grille de 2 km par le serveur."""
    type_connexion: Literal["wifi", "mobile"]
    operateur: Optional[str] = Field(None, max_length=40)
    zone_lat: Optional[float] = Field(None, ge=-90, le=90)
    zone_lon: Optional[float] = Field(None, ge=-180, le=180)
    essais: int = Field(..., ge=1, le=100)
    perdus: int = Field(..., ge=0, le=100)
    latence_moy_ms: Optional[float] = Field(None, ge=0, le=60000)
    https_ok: int = Field(0, ge=0, le=100)
    https_total: int = Field(0, ge=0, le=100)
    debit_desc_mbps: Optional[float] = Field(None, ge=0, le=100000)
    debit_mont_mbps: Optional[float] = Field(None, ge=0, le=100000)


class Blocage(BaseModel):
    bloque: bool


def setup_sonde_communaute_routes(*, db, api, get_current_user) -> None:
    def _admin(user: dict) -> None:
        if user.get("role") not in ("admin", "super_admin") and user.get("tracked_role") != "Administrateur":
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")

    async def _authentifier(autorisation: Optional[str]):
        """Jeton → (identifiant participant, identifiant appareil, fiche). 401 si le jeton est absent, faux ou révoqué ; 403 si le participant est bloqué."""
        jeton = sc.jeton_depuis_en_tete(autorisation)
        if not jeton:
            raise HTTPException(status_code=401, detail="Connexion requise")
        h = sc.empreinte_jeton(jeton)
        doc = await db.settings.find_one({"_id": sc.DOC_PARTICIPANTS}, {f"jetons.{h}": 1}) or {}
        lien = (doc.get("jetons") or {}).get(h)
        if not lien:
            raise HTTPException(status_code=401, detail="Connexion expirée ou révoquée : reconnectez-vous")
        fiche = ((await db.settings.find_one({"_id": sc.DOC_PARTICIPANTS}, {f"p.{lien['pid']}": 1}) or {}).get("p") or {}).get(lien["pid"])
        if not fiche:
            raise HTTPException(status_code=401, detail="Participant introuvable : reconnectez-vous")
        if fiche.get("bloque"):
            raise HTTPException(status_code=403, detail="Participation suspendue par l'administrateur")
        return lien["pid"], lien["aid"], fiche

    # ------------------------------------------------------------------------------------------------------------ côté téléphone
    @api.post("/sonde-reseau/participant/echange", tags=["Sonde réseau"])
    async def echange(data: Echange, request: Request):
        """Code à usage unique reçu après la connexion Google → jeton d'appareil. Le consentement DOIT être celui de la version en vigueur (sinon 422) :
        sans accord, pas de connexion."""
        if _limite_ip(ip_reelle(request)):
            raise HTTPException(status_code=429, detail="Trop d'essais depuis cette adresse")
        if data.consentement_version != sc.CONSENTEMENT_VERSION:
            raise HTTPException(status_code=422, detail=f"Consentement requis (version {sc.CONSENTEMENT_VERSION})")
        if not re.fullmatch(r"[0-9a-f]{16,64}", data.appareil):
            raise HTTPException(status_code=422, detail="Identifiant d'appareil invalide")
        ligne = await db.google_codes.find_one_and_delete({"empreinte": google_auth.empreinte_code(data.code), "sonde_pid": {"$exists": True}})
        if not ligne or ligne.get("expire", 0) < time.time():
            raise HTTPException(status_code=401, detail="Connexion Google expirée : recommencez")
        pid = ligne["sonde_pid"]
        fiche = ((await db.settings.find_one({"_id": sc.DOC_PARTICIPANTS}, {f"p.{pid}": 1}) or {}).get("p") or {}).get(pid)
        if not fiche:
            raise HTTPException(status_code=401, detail="Participant introuvable : recommencez")
        if fiche.get("bloque"):
            raise HTTPException(status_code=403, detail="Participation suspendue par l'administrateur")
        clair, h = sc.nouveau_jeton()
        maintenant = sc.maintenant_iso()
        appareils = dict(fiche.get("appareils") or {})
        retirer = []                                                # jetons de l'appareil remplacé et des appareils en trop (les plus anciens)
        if data.appareil in appareils and appareils[data.appareil].get("h"):
            retirer.append(appareils.pop(data.appareil)["h"])
        while len(appareils) >= sc.MAX_APPAREILS:
            plus_ancien = min(appareils, key=lambda a: appareils[a].get("le", ""))
            retirer.append(appareils.pop(plus_ancien).get("h", ""))
            await db.settings.update_one({"_id": sc.DOC_PARTICIPANTS}, {"$unset": {f"p.{pid}.appareils.{plus_ancien}": ""}})
        mise_a_jour = {"$set": {f"jetons.{h}": {"pid": pid, "aid": data.appareil},
                                f"p.{pid}.appareils.{data.appareil}": {"nom": re.sub(r"[^0-9A-Za-zÀ-ÿ _-]", "", data.nom_appareil)[:40] or "Téléphone", "le": maintenant, "h": h},
                                f"p.{pid}.consentement": {"version": data.consentement_version, "le": maintenant}}}
        if retirer:
            mise_a_jour["$unset"] = {f"jetons.{x}": "" for x in retirer if x}
        await db.settings.update_one({"_id": sc.DOC_PARTICIPANTS}, mise_a_jour)
        return {"jeton": clair, "email": fiche.get("email", ""), "nom": fiche.get("nom", ""), "consentement_version": sc.CONSENTEMENT_VERSION}

    @api.get("/sonde-reseau/participant/moi", tags=["Sonde réseau"])
    async def moi(authorization: Optional[str] = Header(None)):
        _, _, fiche = await _authentifier(authorization)
        return {"email": fiche.get("email", ""), "nom": fiche.get("nom", ""), "consentement": fiche.get("consentement"),
                "consentement_requis": sc.CONSENTEMENT_VERSION, "appareils": len(fiche.get("appareils") or {}), "mesures": fiche.get("mesures", 0)}

    @api.post("/sonde-reseau/participant/deconnexion", tags=["Sonde réseau"])
    async def deconnexion(authorization: Optional[str] = Header(None)):
        pid, aid, fiche = await _authentifier(authorization)
        h = sc.empreinte_jeton(sc.jeton_depuis_en_tete(authorization) or "")
        await db.settings.update_one({"_id": sc.DOC_PARTICIPANTS}, {"$unset": {f"jetons.{h}": "", f"p.{pid}.appareils.{aid}": ""}})
        return {"ok": True}

    async def _supprimer(pid: str) -> None:
        """Supprime la fiche du participant et TOUS ses jetons. Les cellules d'agrégation ne contiennent aucune identité : elles restent."""
        fiche = ((await db.settings.find_one({"_id": sc.DOC_PARTICIPANTS}, {f"p.{pid}": 1}) or {}).get("p") or {}).get(pid) or {}
        retirer = {f"jetons.{a['h']}": "" for a in (fiche.get("appareils") or {}).values() if a.get("h")}
        await db.settings.update_one({"_id": sc.DOC_PARTICIPANTS}, {"$unset": {f"p.{pid}": "", **retirer}})

    @api.delete("/sonde-reseau/participant", tags=["Sonde réseau"])
    async def retrait(authorization: Optional[str] = Header(None)):
        """Retrait de l'accord : la fiche du participant disparaît (e-mail, consentement, appareils, jetons)."""
        pid, _, _ = await _authentifier(authorization)
        await _supprimer(pid)
        return {"ok": True}

    @api.post("/sonde-reseau/communaute/envoi", tags=["Sonde réseau"])
    async def envoi(m: MesureCommunaute, authorization: Optional[str] = Header(None)):
        """Additionne UNE mesure dans sa cellule. Contrôles : jeton valide, consentement de la version en vigueur, cohérence, une mesure toutes les 50 s par appareil,
        400 par jour et par participant. Le lieu est recalé sur la grille de 2 km (jamais gardé plus fin)."""
        pid, aid, fiche = await _authentifier(authorization)
        if (fiche.get("consentement") or {}).get("version") != sc.CONSENTEMENT_VERSION:
            raise HTTPException(status_code=403, detail="Consentement à renouveler : reconnectez-vous")
        if m.perdus > m.essais or m.https_ok > m.https_total:
            raise HTTPException(status_code=422, detail="Mesure incohérente (plus de pertes que d'essais)")
        maintenant = datetime.now(timezone.utc); iso = maintenant.isoformat(); jour = iso[:10]
        derniere = ((fiche.get("appareils") or {}).get(aid) or {}).get("derniere")
        if derniere and (maintenant - datetime.fromisoformat(derniere)).total_seconds() < sc.DELAI_MIN_S:
            raise HTTPException(status_code=429, detail="Mesure trop rapprochée de la précédente")
        n_jour = fiche.get("n_jour", 0) if fiche.get("jour") == jour else 0
        if n_jour >= sc.MAX_PAR_JOUR:
            raise HTTPException(status_code=429, detail="Limite quotidienne atteinte")
        z = sc.zone(m.zone_lat, m.zone_lon)
        cle = sc.cle_cellule(jour, z[0] if z else None, m.type_connexion, m.operateur)
        champs = m.model_dump()
        inc = {f"cellules.{cle}.{k}": v for k, v in sc.increments(champs).items()}
        regle = {"$inc": inc, "$set": {f"cellules.{cle}.maj": iso}}
        if z:
            regle["$set"][f"zones.{z[0]}"] = {"lat": z[1], "lon": z[2]}
        # cellule déjà connue : simple addition ; nouvelle cellule : on vérifie la place (compteur « nb ») avant de la créer
        res = await db.settings.update_one({"_id": sc.DOC_COMMUNAUTE, f"cellules.{cle}": {"$exists": True}}, regle)
        if res.matched_count == 0:
            nb = (await db.settings.find_one({"_id": sc.DOC_COMMUNAUTE}, {"nb": 1}) or {}).get("nb", 0)
            if nb >= sc.MAX_CELLULES:
                cellules = (await db.settings.find_one({"_id": sc.DOC_COMMUNAUTE}, {"cellules": 1}) or {}).get("cellules") or {}
                vieilles = sc.cles_a_purger(cellules, maintenant)
                if vieilles:
                    await db.settings.update_one({"_id": sc.DOC_COMMUNAUTE}, {"$unset": {f"cellules.{c}": "" for c in vieilles}, "$inc": {"nb": -len(vieilles)}})
                else:
                    raise HTTPException(status_code=503, detail="Espace commun plein : réessayez plus tard")
            regle["$inc"]["nb"] = 1
            await db.settings.update_one({"_id": sc.DOC_COMMUNAUTE}, regle, upsert=True)
        # compteurs du participant (une écriture)
        await db.settings.update_one({"_id": sc.DOC_PARTICIPANTS}, {
            "$inc": {f"p.{pid}.mesures": 1}, "$set": {f"p.{pid}.derniere": iso, f"p.{pid}.jour": jour, f"p.{pid}.n_jour": n_jour + 1,
                                                      f"p.{pid}.appareils.{aid}.derniere": iso}})
        return {"ok": True, "zone": z[0] if z else None}

    # ------------------------------------------------------------------------------------------------------------ côté administrateur
    @api.get("/sonde-reseau/communaute", tags=["Admin — Santé"])
    async def synthese(jours: int = Query(7, ge=1, le=120), type_connexion: str = Query("", alias="type"), operateur: str = "", user: dict = Depends(get_current_user)):
        _admin(user)
        doc = await db.settings.find_one({"_id": sc.DOC_COMMUNAUTE}, {"_id": 0}) or {}
        participants = ((await db.settings.find_one({"_id": sc.DOC_PARTICIPANTS}, {"p": 1}) or {}).get("p") or {})
        rep = sc.synthese(doc.get("cellules") or {}, jours, type_connexion, operateur, doc.get("zones") or {})
        rep["participants"] = len(participants)
        rep["pas_zone_km"] = 2
        return rep

    @api.get("/sonde-reseau/communaute/participants", tags=["Admin — Santé"])
    async def participants(user: dict = Depends(get_current_user)):
        _admin(user)
        p = ((await db.settings.find_one({"_id": sc.DOC_PARTICIPANTS}, {"p": 1}) or {}).get("p") or {})
        lignes = [{"id": pid, "email": f.get("email", ""), "nom": f.get("nom", ""), "cree_le": f.get("cree_le"), "consentement": f.get("consentement"),
                   "appareils": len(f.get("appareils") or {}), "mesures": f.get("mesures", 0), "derniere": f.get("derniere"), "bloque": bool(f.get("bloque"))}
                  for pid, f in p.items()]
        return {"participants": sorted(lignes, key=lambda x: x["derniere"] or "", reverse=True)}

    @api.post("/sonde-reseau/communaute/participants/{pid}/bloquer", tags=["Admin — Santé"])
    async def bloquer(pid: str, data: Blocage, user: dict = Depends(get_current_user)):
        _admin(user)
        if not re.fullmatch(r"[0-9a-f]{20}", pid):
            raise HTTPException(status_code=422, detail="Identifiant invalide")
        res = await db.settings.update_one({"_id": sc.DOC_PARTICIPANTS, f"p.{pid}": {"$exists": True}}, {"$set": {f"p.{pid}.bloque": data.bloque}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Participant introuvable")
        return {"ok": True, "bloque": data.bloque}

    @api.delete("/sonde-reseau/communaute/participants/{pid}", tags=["Admin — Santé"])
    async def supprimer_participant(pid: str, user: dict = Depends(get_current_user)):
        _admin(user)
        if not re.fullmatch(r"[0-9a-f]{20}", pid):
            raise HTTPException(status_code=422, detail="Identifiant invalide")
        await _supprimer(pid)
        return {"ok": True}
