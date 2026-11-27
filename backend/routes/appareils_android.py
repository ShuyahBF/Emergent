# routes/appareils_android.py — Lot 468 : registre des appareils Android de « Loois mobile ». Logique et stockage : backend/appareils_android.py.
#
# Côté APPAREIL (pas de compte SAWALI : l'appareil s'identifie par son JETON, en-tête « Authorization: Bearer <jeton> ») :
#   POST /api/android/appareil/enregistrer   premier lancement : crée la fiche en état « interdit » et rend le jeton (une seule fois)
#   POST /api/android/appareil/statut        à chaque ouverture : note l'IP vue par le serveur, rend l'état, la zone, la base, le client, l'utilisateur
# Côté ADMINISTRATEUR (Paramètres → « 📱 Appareils Android ») :
#   GET    /api/admin/android-appareils                      liste (zones connues comprises), jamais de jeton ni d'empreinte
#   PUT    /api/admin/android-appareils/{id}                 modifie : état, utilisateur, zone, base, client, notes
#   POST   /api/admin/android-appareils/{id}/reinitialiser   efface le jeton : l'appareil pourra se ré-enregistrer (réinstallation, téléphone réinitialisé)
#   DELETE /api/admin/android-appareils/{id}                 supprime la fiche
# Sécurité : jeton aléatoire de 256 bits (seule son empreinte est gardée) ; appareil déjà connu = jamais de second jeton sans réinitialisation par l'administrateur ;
# limites par adresse IP (enregistrements, statuts, jetons faux) ; message neutre quand le jeton est faux.
from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

from fastapi import Body, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

import appareils_android as aa
import serveurs_locaux as sl
from ip_client import ip_reelle
from routes.liluvine_partage import est_admin

_limites: Dict[str, Deque[float]] = defaultdict(deque)
LIMITE_ENREGISTRER = (10, 3600)      # 10 enregistrements par heure et par adresse IP
LIMITE_STATUT = (240, 3600)          # 240 statuts par heure (une ouverture de l'application toutes les 15 s, largement assez)
LIMITE_JETON_FAUX = (20, 900)        # 20 jetons faux par 15 minutes


def _depassee(nature: str, ip: str, limite: tuple, ajouter: bool = True) -> bool:
    """Vrai si l'adresse a dépassé sa limite pour cette nature d'appel (fenêtre glissante, en mémoire du serveur)."""
    maxi, duree = limite
    file = _limites[f"{nature}|{ip}"]
    maintenant = time.monotonic()
    while file and maintenant - file[0] > duree:
        file.popleft()
    if len(file) >= maxi:
        return True
    if ajouter:
        file.append(maintenant)
    return False


class DemandeEnregistrement(BaseModel):
    """Corps du premier lancement de l'APK : identifiant Android, modèle, version de l'application."""
    android_id: str = Field(min_length=8, max_length=80)
    modele: str = Field(default="", max_length=80)
    version_app: str = Field(default="", max_length=30)


class DemandeStatut(BaseModel):
    version_app: str = Field(default="", max_length=30)


def setup_appareils_android_routes(*, db, api, get_current_user) -> None:
    async def _admin(user: dict = Depends(get_current_user)) -> dict:
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return user

    def _jeton(autorisation: Optional[str]) -> str:
        return (autorisation or "").removeprefix("Bearer ").strip()

    async def _acces_local(fiche: Dict[str, Any]) -> Dict[str, Any]:
        """Lot 480 : de quoi travailler SANS Internet — adresses des passerelles locales du client (remontées par Loois) et TICKET LOCAL de l'appareil (72 h, vérifiable hors ligne). Rien pour un appareil interdit."""
        vide = {"serveurs_locaux": [], "ticket_local": "", "ticket_local_h": sl.TICKET_TTL_H}
        if fiche.get("etat") != "autorise" or not fiche.get("client_code"):
            return vide
        try:
            urls = sl.urls_locales(await sl.lire_client(db, fiche["client_code"]))
            secret = await sl.secret_client(db, fiche["client_code"])
            if not urls or not secret:
                return {**vide, "serveurs_locaux": urls}
            return {"serveurs_locaux": urls, "ticket_local": sl.creer_ticket(secret, fiche["id"], fiche["client_code"], fiche.get("zone", ""), fiche.get("base", "")), "ticket_local_h": sl.TICKET_TTL_H}
        except Exception:  # noqa: BLE001
            return vide                                   # jamais d'échec du statut à cause du mode hors ligne

    # ------------------------------------------------------------------------------------------------------------------ côté appareil
    @api.post("/android/appareil/enregistrer", tags=["Loois mobile (appareils Android)"])
    async def enregistrer(corps: DemandeEnregistrement, request: Request):
        ip = ip_reelle(request)
        if _depassee("enreg", ip, LIMITE_ENREGISTRER):
            raise HTTPException(status_code=429, detail="Trop de tentatives, réessayez plus tard.")
        existant = await aa.trouver_par_android_id(db, corps.android_id)
        if existant is not None:
            if existant.get("jeton_hash"):                       # déjà enregistré : jamais de second jeton sans réinitialisation par l'administrateur
                raise HTTPException(status_code=409, detail="Appareil déjà enregistré. Demandez à l'administrateur de réinitialiser son jeton.")
            jeton = secrets.token_urlsafe(32)      # jeton réinitialisé par l'administrateur : on en émet un nouveau pour la MÊME fiche
            await aa.modifier(db, existant["id"], {"jeton_hash": aa.hash_secret(jeton), "modele": aa.nettoyer(corps.modele, 80), "version_app": aa.nettoyer(corps.version_app, 30)})
            await aa.noter_connexion(db, existant["id"], ip, corps.version_app, "reenregistre")
            return {"appareil_id": existant["id"], "jeton": jeton, **aa.reponse_statut(existant)}
        if len(await aa.lire_tous(db)) >= aa.MAX_APPAREILS:
            raise HTTPException(status_code=507, detail="Nombre maximal d'appareils atteint : contactez l'administrateur.")
        fiche, jeton = aa.nouvelle_fiche(corps.android_id, corps.modele, corps.version_app, ip)
        await aa.creer(db, fiche)
        await aa.noter_connexion(db, fiche["id"], ip, corps.version_app, "enregistre")
        return {"appareil_id": fiche["id"], "jeton": jeton, **aa.reponse_statut(fiche)}

    @api.post("/android/appareil/statut", tags=["Loois mobile (appareils Android)"])
    async def statut(request: Request, corps: DemandeStatut = Body(default_factory=DemandeStatut), authorization: Optional[str] = Header(default=None)):
        ip = ip_reelle(request)
        if _depassee("statut", ip, LIMITE_STATUT) or _depassee("faux", ip, LIMITE_JETON_FAUX, ajouter=False):
            raise HTTPException(status_code=429, detail="Trop de demandes, réessayez plus tard.")
        fiche = await aa.trouver_par_jeton(db, _jeton(authorization))
        if fiche is None:
            _depassee("faux", ip, LIMITE_JETON_FAUX)             # compte un jeton faux
            raise HTTPException(status_code=401, detail="Appareil non reconnu : enregistrez-le de nouveau.")
        await aa.noter_connexion(db, fiche["id"], ip, corps.version_app, "autorise" if fiche.get("etat") == "autorise" else "interdit")
        return {**aa.reponse_statut(fiche), **(await _acces_local(fiche))}

    # ------------------------------------------------------------------------------------------------------------------ côté administrateur
    @api.get("/admin/android-appareils", tags=["Loois mobile (appareils Android)"])
    async def liste(_: dict = Depends(_admin)):
        fiches = sorted((aa.vue_admin(f) for f in (await aa.lire_tous(db)).values()), key=lambda f: f.get("derniere_connexion") or f.get("cree_le") or "", reverse=True)
        return {"appareils": fiches, "zones": aa.ZONES, "maximum": aa.MAX_APPAREILS}

    @api.put("/admin/android-appareils/{appareil_id}", tags=["Loois mobile (appareils Android)"])
    async def modifier(appareil_id: str, donnees: Dict[str, Any] = Body(...), _: dict = Depends(_admin)):
        if await aa.lire_un(db, appareil_id) is None:
            raise HTTPException(status_code=404, detail="Appareil introuvable")
        champs, erreur = aa.valider_modifications(donnees)
        if erreur:
            raise HTTPException(status_code=422, detail=erreur)
        if champs:
            await aa.modifier(db, appareil_id, champs)
        return aa.vue_admin(await aa.lire_un(db, appareil_id))

    @api.post("/admin/android-appareils/{appareil_id}/reinitialiser", tags=["Loois mobile (appareils Android)"])
    async def reinitialiser(appareil_id: str, _: dict = Depends(_admin)):
        if await aa.lire_un(db, appareil_id) is None:
            raise HTTPException(status_code=404, detail="Appareil introuvable")
        await aa.modifier(db, appareil_id, {"jeton_hash": ""})   # l'ancien jeton ne marche plus ; l'appareil pourra se ré-enregistrer
        return aa.vue_admin(await aa.lire_un(db, appareil_id))

    @api.delete("/admin/android-appareils/{appareil_id}", tags=["Loois mobile (appareils Android)"])
    async def supprimer(appareil_id: str, _: dict = Depends(_admin)):
        if not await aa.supprimer(db, appareil_id):
            raise HTTPException(status_code=404, detail="Appareil introuvable")
        return {"ok": True}
