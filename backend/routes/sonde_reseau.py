# routes/sonde_reseau.py — Lot 470 : SONDE RÉSEAU (Paramètres → « 📶 Sonde réseau — débit et stabilité de la connexion »). Administrateur SEUL.
#   POST   /sonde-reseau/mesures    reçoit UNE mesure faite par la page (navigateur du poste branché à la box, ou téléphone)
#   GET    /sonde-reseau/mesures    mesures d'une période (+ statistiques et liste des postes)
#   GET    /sonde-reseau/rapport    rapport HTML autonome à partager (fichier à télécharger)
#   DELETE /sonde-reseau/mesures    efface toutes les mesures (nouveau départ)
#   POST   /sonde-reseau/envoi      (lot 471) même chose que POST /mesures, mais authentifiée par la CLÉ DE LA SONDE (en-tête X-Cle-Sonde = variable
#                                   d'environnement SONDE_RESEAU_CLE, saisie par le propriétaire dans Render) : le PC laissé allumé et l'application Android
#                                   n'ont ainsi besoin d'AUCUNE session administrateur (qui expire au bout de 12 h ou par inactivité).
#   GET    /sonde-reseau/cle-etat   dit à l'administrateur si la clé est configurée sur le serveur (jamais sa valeur)
# Logique pure, statistiques et rapport : voir backend/sonde_reseau.py. Stockage : une fiche de `settings`, aucune nouvelle collection.
from __future__ import annotations

import hmac
import os
import time
from typing import Dict, List, Literal, Optional

from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import sonde_reseau as sr
from ip_client import ip_reelle

# Limite d'envois par adresse IP pour la route à clé : 120 mesures par heure (une sonde en envoie 4 par heure) ; fenêtre glissante gardée EN MÉMOIRE
LIMITE_ENVOIS_IP = 120
FENETRE_S = 3600
_envois_par_ip: Dict[str, List[float]] = {}


def _limite_ip_atteinte(ip: str, maintenant: Optional[float] = None) -> bool:
    """Compte l'appel et dit si l'adresse a dépassé sa limite sur la dernière heure (les clés fausses comptent aussi : pas d'essais à l'infini)."""
    t = time.monotonic() if maintenant is None else maintenant
    recents = [x for x in _envois_par_ip.get(ip, []) if t - x < FENETRE_S]
    recents.append(t)
    _envois_par_ip[ip] = recents[-(LIMITE_ENVOIS_IP + 1):]
    return len(recents) > LIMITE_ENVOIS_IP


class MesureEntrante(BaseModel):
    """Une mesure envoyée par la page. Toutes les valeurs sont bornées : une page détournée ne peut pas remplir la fiche de n'importe quoi.
    Les débits et la vidéo sont facultatifs (mesurés seulement une fois par heure)."""
    poste: str = Field(..., min_length=1, max_length=60)
    type: Literal["pc", "mobile"] = "pc"
    essais: int = Field(..., ge=1, le=100)                     # requêtes de latence envoyées
    perdus: int = Field(..., ge=0, le=100)                     # requêtes sans réponse dans le délai
    latence_moy_ms: Optional[float] = Field(None, ge=0, le=60000)
    latence_min_ms: Optional[float] = Field(None, ge=0, le=60000)
    latence_max_ms: Optional[float] = Field(None, ge=0, le=60000)
    https_ok: int = Field(0, ge=0, le=100)
    https_total: int = Field(0, ge=0, le=100)
    debit_desc_mbps: Optional[float] = Field(None, ge=0, le=100000)
    debit_mont_mbps: Optional[float] = Field(None, ge=0, le=100000)
    video_demarrage_ms: Optional[float] = Field(None, ge=0, le=600000)
    video_saccades: Optional[int] = Field(None, ge=0, le=1000)
    connexion: Optional[str] = Field(None, max_length=20)      # type de réseau annoncé par le navigateur (4g, wifi…), indicatif
    # Lot 471 — champs de l'application Android : vrai « ping » système (méthode), et débit le plus bas sur une fenêtre d'une seconde pendant un test SOUTENU
    # (c'est lui qui dit si une vidéo SD ≈ 1,5 Mb/s ou HD ≈ 5 Mb/s saccaderait) ; la page web ne les envoie pas.
    methode: Literal["navigateur", "ping"] = "navigateur"
    debit_desc_min_mbps: Optional[float] = Field(None, ge=0, le=100000)
    debit_mont_min_mbps: Optional[float] = Field(None, ge=0, le=100000)


def setup_sonde_reseau_routes(*, db, api, get_current_user) -> None:
    def _admin(user: dict) -> None:
        if user.get("role") not in ("admin", "super_admin") and user.get("tracked_role") != "Administrateur":
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")

    async def _toutes() -> List[dict]:
        doc = await db.settings.find_one({"_id": sr.DOC_ID}, {"_id": 0, "mesures": 1}) or {}
        return list(doc.get("mesures") or [])

    async def _enregistrer(m: MesureEntrante) -> dict:
        """Contrôles communs (cohérence, anti-abus par poste) puis ajout atomique dans la fiche : utilisée par la route administrateur ET la route à clé."""
        if m.perdus > m.essais or m.https_ok > m.https_total:
            raise HTTPException(status_code=422, detail="Mesure incohérente (plus de pertes que d'essais)")
        poste = sr.nom_poste(m.poste)
        maintenant = sr.maintenant_iso()
        # Anti-abus : un même poste n'envoie pas plus d'une mesure toutes les 50 s (la page en envoie une toutes les 15 minutes).
        dernier = ((await db.settings.find_one({"_id": sr.DOC_ID}, {"_id": 0, "dernier_par_poste": 1}) or {}).get("dernier_par_poste") or {}).get(poste)
        if dernier and (sr.datetime.fromisoformat(maintenant) - sr.datetime.fromisoformat(dernier)).total_seconds() < sr.DELAI_MIN_S:
            raise HTTPException(status_code=429, detail="Mesure trop rapprochée de la précédente")
        fiche = {**m.model_dump(), "poste": poste, "le": maintenant}
        # Ajout atomique, tableau plafonné : les plus anciennes mesures disparaissent seules.
        await db.settings.update_one(
            {"_id": sr.DOC_ID},
            {"$push": {"mesures": {"$each": [fiche], "$slice": -sr.MAX_MESURES}}, "$set": {f"dernier_par_poste.{poste}": maintenant}},
            upsert=True)
        return {"ok": True, "le": maintenant}

    @api.post("/sonde-reseau/mesures", tags=["Admin — Santé"])
    async def ajouter_mesure(m: MesureEntrante, user: dict = Depends(get_current_user)):
        _admin(user)
        return await _enregistrer(m)

    @api.post("/sonde-reseau/envoi", tags=["Sonde réseau"])
    async def envoi_par_cle(m: MesureEntrante, request: Request, x_cle_sonde: Optional[str] = Header(None)):
        """Envoi d'une mesure par la clé de la sonde (page ouverte sans surveillance, application Android). Jamais acceptée par défaut :
        sans SONDE_RESEAU_CLE sur le serveur la route répond 503 ; clé absente ou fausse = 401 ; l'adresse IP est limitée."""
        cle = os.environ.get("SONDE_RESEAU_CLE", "")
        if _limite_ip_atteinte(ip_reelle(request)):
            raise HTTPException(status_code=429, detail="Trop d'envois depuis cette adresse")
        if not cle:
            raise HTTPException(status_code=503, detail="Clé de la sonde non configurée sur le serveur (variable SONDE_RESEAU_CLE)")
        if not x_cle_sonde or not hmac.compare_digest(x_cle_sonde.encode("utf-8"), cle.encode("utf-8")):    # comparaison à temps constant
            raise HTTPException(status_code=401, detail="Clé de la sonde incorrecte")
        return await _enregistrer(m)

    @api.get("/sonde-reseau/cle-etat", tags=["Admin — Santé"])
    async def cle_etat(user: dict = Depends(get_current_user)):
        _admin(user)
        return {"configuree": bool(os.environ.get("SONDE_RESEAU_CLE")), "variable": "SONDE_RESEAU_CLE", "route": "/api/sonde-reseau/envoi"}

    @api.get("/sonde-reseau/mesures", tags=["Admin — Santé"])
    async def lire_mesures(jours: int = Query(7, ge=1, le=60), poste: str = "", limite: int = Query(300, ge=1, le=1000),
                           user: dict = Depends(get_current_user)):
        _admin(user)
        toutes = await _toutes()
        retenues = sr.filtrer(toutes, jours, poste or None)
        return {"jours": jours, "poste": poste or None, "postes": sorted({m.get("poste") for m in toutes if m.get("poste")}),
                "resume": sr.resume(retenues), "total_en_base": len(toutes),
                "mesures": [{**m, "perte_pct": sr.pct_perte(m)} for m in retenues[-limite:]]}

    @api.get("/sonde-reseau/rapport", tags=["Admin — Santé"])
    async def rapport(jours: int = Query(7, ge=1, le=60), poste: str = "", user: dict = Depends(get_current_user)):
        _admin(user)
        retenues = sr.filtrer(await _toutes(), jours, poste or None)
        corps = sr.rapport_html(retenues, jours, poste or None)
        nom = f"rapport-sonde-reseau-{sr.maintenant_iso()[:10].replace('-', '')}.html"
        return HTMLResponse(corps, headers={"Content-Disposition": f'attachment; filename="{nom}"'})

    @api.delete("/sonde-reseau/mesures", tags=["Admin — Santé"])
    async def effacer(user: dict = Depends(get_current_user)):
        _admin(user)
        await db.settings.update_one({"_id": sr.DOC_ID}, {"$set": {"mesures": [], "dernier_par_poste": {}}}, upsert=True)
        return {"ok": True}
