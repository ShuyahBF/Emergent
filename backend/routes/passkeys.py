"""Lot 369 — Connexion par empreinte digitale (« passkeys » / WebAuthn).

POURQUOI WEBAUTHN ET PAS UN LECTEUR LU PAR LE SITE
   Un site web ne peut pas lire un lecteur d'empreintes USB, et envoyer des empreintes à un serveur sur Internet
   serait un risque sérieux pour la confidentialité. Le standard des navigateurs, WebAuthn, fait autrement :
   l'empreinte est vérifiée LOCALEMENT (Windows Hello avec un lecteur dont le pilote « WBF » est installé, le
   téléphone Android ou iPhone, ou une clé de sécurité à empreinte) ; le serveur ne reçoit JAMAIS l'empreinte,
   seulement une signature cryptographique qu'il vérifie avec la CLÉ PUBLIQUE enregistrée au préalable.

CE QUE FAIT CE MODULE (sous /api)
   GET    /auth/passkeys/config                   — public : la connexion par empreinte est-elle activée ?
   POST   /auth/passkeys/login/options            — public : défi à signer (aucun compte nommé : passkey « découvrable »)
   POST   /auth/passkeys/login/verify             — public : signature → mêmes contrôles qu'une connexion → jeton
   POST   /auth/passkeys/register/options         — connecté : défi d'enregistrement d'une nouvelle passkey
   POST   /auth/passkeys/register/verify          — connecté : enregistre la clé publique (8 passkeys au plus par compte)
   GET    /auth/passkeys                          — connecté : mes passkeys
   DELETE /auth/passkeys/{id}                     — connecté : retirer une de mes passkeys
   GET    /admin/passkeys                         — administrateur : état, domaine, comptes qui en ont
   PUT    /admin/passkeys/config                  — administrateur : activer / désactiver, domaine (RP ID)
   DELETE /admin/passkeys/user/{user_id}          — administrateur : révoquer toutes les passkeys d'un compte

DÉCISIONS
   - Activée par l'administrateur (réglage `passkeys_enabled` de `settings`, désactivé par défaut) : le déploiement ne
     change RIEN tant qu'elle ne l'a pas activée. Le mot de passe reste toujours possible (secours).
   - AUCUNE nouvelle collection (cluster MongoDB plein, règle 9) : les clés publiques sont dans le champ `passkeys`
     de la fiche du compte (`users`), les défis éphémères dans `otps` (type « passkey_challenge », usage unique, 3 min).
   - Passkey = « quelque chose que l'on possède » ET « que l'on est » (vérification utilisateur exigée) : elle remplace
     le mot de passe ET le code e-mail. Aucun reCAPTCHA (une signature ne peut pas être fabriquée par un robot).
   - Mêmes refus que les autres connexions : compte inactif, maintenance, client suspendu ou archivé, IP bloquée ; chaque
     tentative est journalisée (méthode « empreinte », Historique des connexions).
   - Domaine (RP ID) : réglage `passkeys_rp_id`, sinon variable WEBAUTHN_RP_ID, sinon « sawalismartsystems.com » pour ce
     domaine et ses sous-domaines, sinon le nom d'hôte du site. Une passkey ne marche que sur son domaine d'enregistrement.
   - Limite connue : Windows Hello est lié au COMPTE WINDOWS ; sur un poste partagé par un seul compte Windows, l'empreinte
     d'une personne peut déverrouiller la passkey d'une autre. Pour ces postes : clé de sécurité à empreinte par personne
     ou téléphone de chacun.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

import connexions_ip  # journal des connexions (méthode « empreinte »), IP bloquée
from ip_client import ip_reelle
from models import AuthTokenResponse
from routes.auth import refuser_si_compte_inactif

logger = logging.getLogger("sawali.passkeys")

TYPE_DEFI = "passkey_challenge"        # type des documents de la collection `otps` qui portent un défi
DUREE_DEFI_S = 180                     # un défi vaut 3 minutes, une seule fois
MAX_PAR_COMPTE = 8                     # passkeys au plus par compte
LIMITE_DEMANDES = 30                   # demandes de connexion (défi + vérification) par adresse IP et par minute : pas de remplissage de la base par un robot
FENETRE_LIMITE_S = 60
NOM_PLATEFORME = "SAWALI"
RP_PAR_DEFAUT = "sawalismartsystems.com"
_RP_VALIDE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


class PasskeyEnregistrement(BaseModel):
    """Corps de /auth/passkeys/register/verify : le défi, la réponse du navigateur et un nom lisible."""
    challenge_id: str
    credential: Dict[str, Any]
    nom: str = Field(default="", max_length=60)


class PasskeyConnexion(BaseModel):
    """Corps de /auth/passkeys/login/verify : le défi et la réponse signée du navigateur."""
    challenge_id: str
    credential: Dict[str, Any]


class PasskeyConfig(BaseModel):
    """Corps de PUT /admin/passkeys/config."""
    enabled: bool
    rp_id: Optional[str] = Field(default=None, max_length=120)


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _vue(p: dict) -> dict:
    """Une passkey telle qu'affichée : jamais la clé publique ni le compteur."""
    return {"id": p.get("id"), "nom": p.get("nom") or "Passkey", "cree_le": p.get("cree_le"),
            "dernier_usage": p.get("dernier_usage"), "transports": p.get("transports") or []}


def origine_et_domaine(entete_origine: str, rp_reglage: Optional[str]) -> Tuple[str, str]:
    """Origine de la page (adresse exacte du site) et domaine WebAuthn (RP ID), validés.
    Logique pure, testée : HTTPS exigé (sauf localhost), le domaine doit couvrir l'hôte de la page."""
    origine = (entete_origine or "").strip().rstrip("/")
    p = urlparse(origine)
    if p.scheme not in ("https", "http") or not p.hostname:
        raise HTTPException(status_code=400, detail="Adresse de la page absente ou invalide")
    hote = p.hostname.lower()
    if p.scheme == "http" and hote not in ("localhost", "127.0.0.1"):
        raise HTTPException(status_code=400, detail="La connexion par empreinte exige une page en HTTPS")
    rp = (rp_reglage or os.environ.get("WEBAUTHN_RP_ID") or "").strip().lower()
    if not rp:
        rp = RP_PAR_DEFAUT if hote == RP_PAR_DEFAUT or hote.endswith("." + RP_PAR_DEFAUT) else hote
    if not (hote == rp or hote.endswith("." + rp)):
        raise HTTPException(status_code=400, detail="Cette adresse ne correspond pas au domaine réglé pour les passkeys")
    return f"{p.scheme}://{p.netloc}", rp


def attach_passkey_routes(api: APIRouter | FastAPI, *, db, helpers: Dict[str, Any]) -> None:
    """Branche les routes. `helpers` : get_current_user, create_session_token, _to_user_public, _uuid ; facultatifs :
    refuser_si_maintenance, refuser_si_cycle_vie, emit_login_event."""
    get_current_user = helpers["get_current_user"]
    create_session_token = helpers["create_session_token"]
    to_public = helpers["_to_user_public"]
    nouvel_id = helpers["_uuid"]
    refuser_si_maintenance = helpers.get("refuser_si_maintenance")
    refuser_si_cycle_vie = helpers.get("refuser_si_cycle_vie")
    emit_login_event = helpers.get("emit_login_event")
    etat = {"index": False}
    demandes: Dict[str, List[float]] = {}   # adresse IP -> instants des demandes de la dernière minute (mémoire du serveur)

    def limiter(request: Request) -> None:
        """Refuse (429) au-delà de LIMITE_DEMANDES par minute pour une même adresse IP. Les routes publiques créent un défi en base :
        sans cette limite, un robot pourrait la remplir. Mémoire du serveur seulement (se vide au redémarrage, suffisant ici)."""
        ip = ip_reelle(request) or "?"
        maintenant = time.monotonic()
        recentes = [t for t in demandes.get(ip, []) if maintenant - t < FENETRE_LIMITE_S]
        if len(recentes) >= LIMITE_DEMANDES:
            demandes[ip] = recentes
            raise HTTPException(status_code=429, detail="Trop de tentatives : patientez une minute")
        recentes.append(maintenant)
        demandes[ip] = recentes
        if len(demandes) > 5000:                                   # ménage : on oublie les adresses sans demande récente
            for cle in [k for k, v in demandes.items() if not v or maintenant - v[-1] >= FENETRE_LIMITE_S]:
                demandes.pop(cle, None)

    async def reglages() -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}, {"passkeys_enabled": 1, "passkeys_rp_id": 1}) or {}
        return {"enabled": bool(s.get("passkeys_enabled")), "rp_id": (s.get("passkeys_rp_id") or "").strip() or None}

    async def exiger_active() -> Dict[str, Any]:
        r = await reglages()
        if not r["enabled"]:
            raise HTTPException(status_code=403, detail="La connexion par empreinte n'est pas activée")
        return r

    async def assurer_index() -> None:
        """Index sur l'identifiant de passkey : la connexion retrouve le compte sans parcourir `users` (règle 7)."""
        if not etat["index"]:
            await db.users.create_index("passkeys.id", sparse=True, name="ix_users_passkeys_id")
            etat["index"] = True

    async def creer_defi(objet: str, user_id: Optional[str], defi: bytes) -> str:
        """Garde le défi (usage unique, 3 min) dans `otps` ; les défis expirés sont nettoyés au passage."""
        maintenant = _maintenant()
        await db.otps.delete_many({"type": TYPE_DEFI, "expires_at": {"$lt": _iso(maintenant)}})
        identifiant = nouvel_id()
        await db.otps.insert_one({
            "id": identifiant, "type": TYPE_DEFI, "objet": objet, "user_id": user_id, "used": False,
            "challenge": bytes_to_base64url(defi), "created_at": _iso(maintenant),
            "expires_at": _iso(maintenant + timedelta(seconds=DUREE_DEFI_S)),
        })
        return identifiant

    async def consommer_defi(identifiant: str, objet: str, user_id: Optional[str] = None) -> bytes:
        """Marque le défi utilisé (une seule fois, de façon atomique) et le renvoie ; refuse un défi inconnu, expiré ou d'un autre compte."""
        doc = await db.otps.find_one_and_update({"id": identifiant, "type": TYPE_DEFI, "objet": objet, "used": False}, {"$set": {"used": True}})
        if (not doc or doc.get("expires_at", "") < _iso(_maintenant())
                or (user_id is not None and doc.get("user_id") != user_id)):
            raise HTTPException(status_code=400, detail="Défi expiré ou invalide : recommencez")
        return base64url_to_bytes(doc["challenge"])

    async def profil_public(user: dict) -> dict:
        """Profil public du compte ; un utilisateur suivi hérite du `business_type` de son client parent (comme /auth/me)."""
        pub = to_public(user)
        suivi = bool(user.get("tracked_user_id") or user.get("tracked_role"))
        parent_id = user.get("parent_client_id") or user.get("client_id")
        if suivi and parent_id and parent_id != user.get("id"):
            parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "business_type": 1})
            pub["business_type"] = (parent or {}).get("business_type") or ""
        return pub

    # ---------------------------------------------------------------- public

    @api.get("/auth/passkeys/config", tags=["Passkeys"])
    async def passkeys_config():
        """La page de connexion n'affiche le bouton « Se connecter avec mon empreinte » que si c'est activé."""
        return {"enabled": (await reglages())["enabled"]}

    @api.post("/auth/passkeys/login/options", tags=["Passkeys"])
    async def passkeys_login_options(request: Request):
        limiter(request)
        r = await exiger_active()
        _, rp = origine_et_domaine(request.headers.get("origin", ""), r["rp_id"])
        options = generate_authentication_options(rp_id=rp, user_verification=UserVerificationRequirement.REQUIRED)
        return {"challenge_id": await creer_defi("connexion", None, options.challenge), "options": json.loads(options_to_json(options))}

    @api.post("/auth/passkeys/login/verify", response_model=AuthTokenResponse, tags=["Passkeys"])
    async def passkeys_login_verify(payload: PasskeyConnexion, request: Request):
        limiter(request)
        r = await exiger_active()
        origine, rp = origine_et_domaine(request.headers.get("origin", ""), r["rp_id"])
        defi = await consommer_defi(payload.challenge_id, "connexion")
        identifiant = payload.credential.get("id")
        if not isinstance(identifiant, str) or not identifiant:
            raise HTTPException(status_code=400, detail="Réponse du navigateur invalide")
        await assurer_index()
        user = await db.users.find_one({"passkeys.id": identifiant})
        if not user:
            raise HTTPException(status_code=401, detail="Passkey inconnue ou retirée : connectez-vous avec votre mot de passe")
        entree = next(p for p in user["passkeys"] if p.get("id") == identifiant)
        try:
            verifiee = verify_authentication_response(
                credential=payload.credential, expected_challenge=defi, expected_rp_id=rp, expected_origin=origine,
                credential_public_key=base64url_to_bytes(entree["public_key"]),
                credential_current_sign_count=int(entree.get("sign_count") or 0), require_user_verification=True)
            handle = (payload.credential.get("response") or {}).get("userHandle")
            if handle and base64url_to_bytes(handle) != str(user["id"]).encode():
                raise ValueError("identifiant de compte incohérent")
        except Exception as exc:  # noqa: BLE001 — toute anomalie de signature = refus, jamais d'indice sur la cause
            logger.info("[passkeys] connexion refusée : %s", exc)
            await connexions_ip.noter(user, request, connexions_ip.EMPREINTE, connexions_ip.REFUSEE, "Empreinte non vérifiée")
            raise HTTPException(status_code=401, detail="Empreinte non vérifiée : réessayez ou utilisez votre mot de passe")
        try:
            refuser_si_compte_inactif(user)
            if refuser_si_maintenance is not None:
                await refuser_si_maintenance(user)
            if refuser_si_cycle_vie is not None:
                await refuser_si_cycle_vie(user)
        except HTTPException as exc:
            await connexions_ip.noter(user, request, connexions_ip.EMPREINTE, connexions_ip.REFUSEE, str(exc.detail)[:200])
            raise
        maintenant = _iso(_maintenant())
        await db.users.update_one({"id": user["id"], "passkeys.id": identifiant}, {"$set": {
            "passkeys.$.sign_count": verifiee.new_sign_count, "passkeys.$.dernier_usage": maintenant, "last_login": maintenant}})
        user.pop("password_hash", None)
        user.pop("_id", None)
        jeton = await create_session_token(user, request, methode=connexions_ip.EMPREINTE)   # IP bloquée refusée et journal notés ici
        if emit_login_event is not None:
            try:
                asyncio.create_task(emit_login_event(user, request))
            except Exception:  # noqa: BLE001
                pass
        return AuthTokenResponse(access_token=jeton, user=await profil_public(user))

    # ---------------------------------------------------------------- compte connecté

    @api.get("/auth/passkeys", tags=["Passkeys"])
    async def mes_passkeys(user: dict = Depends(get_current_user)):
        fiche = await db.users.find_one({"id": user["id"]}, {"_id": 0, "passkeys": 1}) or {}
        return {"enabled": (await reglages())["enabled"], "max": MAX_PAR_COMPTE, "passkeys": [_vue(p) for p in fiche.get("passkeys") or []]}

    @api.post("/auth/passkeys/register/options", tags=["Passkeys"])
    async def passkeys_register_options(request: Request, user: dict = Depends(get_current_user)):
        r = await exiger_active()
        _, rp = origine_et_domaine(request.headers.get("origin", ""), r["rp_id"])
        fiche = await db.users.find_one({"id": user["id"]}, {"_id": 0, "passkeys": 1}) or {}
        existantes = fiche.get("passkeys") or []
        if len(existantes) >= MAX_PAR_COMPTE:
            raise HTTPException(status_code=400, detail=f"{MAX_PAR_COMPTE} passkeys au plus par compte : retirez-en une d'abord")
        options = generate_registration_options(
            rp_id=rp, rp_name=NOM_PLATEFORME, user_id=str(user["id"]).encode(), user_name=user["email"],
            user_display_name=user.get("full_name") or user["email"],
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(p["id"])) for p in existantes])
        return {"challenge_id": await creer_defi("enregistrement", user["id"], options.challenge), "options": json.loads(options_to_json(options))}

    @api.post("/auth/passkeys/register/verify", tags=["Passkeys"])
    async def passkeys_register_verify(payload: PasskeyEnregistrement, request: Request, user: dict = Depends(get_current_user)):
        r = await exiger_active()
        origine, rp = origine_et_domaine(request.headers.get("origin", ""), r["rp_id"])
        defi = await consommer_defi(payload.challenge_id, "enregistrement", user["id"])
        try:
            verifiee = verify_registration_response(
                credential=payload.credential, expected_challenge=defi, expected_rp_id=rp, expected_origin=origine, require_user_verification=True)
        except Exception as exc:  # noqa: BLE001
            logger.info("[passkeys] enregistrement refusé : %s", exc)
            raise HTTPException(status_code=400, detail="Enregistrement refusé : l'empreinte n'a pas pu être vérifiée")
        identifiant = bytes_to_base64url(verifiee.credential_id)
        if await db.users.find_one({"passkeys.id": identifiant}, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=409, detail="Cette passkey est déjà enregistrée")
        transports = (payload.credential.get("response") or {}).get("transports")
        nom = re.sub(r"\s+", " ", payload.nom or "").strip() or "Ma passkey"
        entree = {"id": identifiant, "public_key": bytes_to_base64url(verifiee.credential_public_key), "sign_count": verifiee.sign_count,
                  "nom": nom, "transports": [t for t in transports if isinstance(t, str)][:6] if isinstance(transports, list) else [],
                  "cree_le": _iso(_maintenant()), "dernier_usage": None}
        # Limite vérifiée dans la requête elle-même : deux enregistrements simultanés ne dépassent jamais 8
        res = await db.users.update_one({"id": user["id"], f"passkeys.{MAX_PAR_COMPTE - 1}": {"$exists": False}}, {"$push": {"passkeys": entree}})
        if res.modified_count == 0:
            raise HTTPException(status_code=400, detail=f"{MAX_PAR_COMPTE} passkeys au plus par compte")
        logger.info("[passkeys] passkey enregistrée pour %s", user["id"])
        fiche = await db.users.find_one({"id": user["id"]}, {"_id": 0, "passkeys": 1}) or {}
        return {"ok": True, "passkeys": [_vue(p) for p in fiche.get("passkeys") or []]}

    @api.delete("/auth/passkeys/{identifiant}", tags=["Passkeys"])
    async def retirer_passkey(identifiant: str, user: dict = Depends(get_current_user)):
        res = await db.users.update_one({"id": user["id"]}, {"$pull": {"passkeys": {"id": identifiant}}})
        if res.modified_count == 0:
            raise HTTPException(status_code=404, detail="Passkey introuvable")
        return {"ok": True}

    # ---------------------------------------------------------------- administrateur

    def exiger_admin(user: dict) -> None:
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    @api.get("/admin/passkeys", tags=["Passkeys"])
    async def admin_passkeys(request: Request, user: dict = Depends(get_current_user)):
        """État, domaine et comptes qui ont des passkeys (jamais leurs clés)."""
        exiger_admin(user)
        r = await reglages()
        try:
            _, domaine = origine_et_domaine(request.headers.get("origin", ""), r["rp_id"])
        except HTTPException:
            domaine = r["rp_id"] or RP_PAR_DEFAUT
        comptes: List[dict] = []
        async for u in db.users.find({"passkeys.0": {"$exists": True}}, {"_id": 0, "id": 1, "email": 1, "full_name": 1, "role": 1, "passkeys": 1}).limit(500):
            usages = [p.get("dernier_usage") for p in u["passkeys"] if p.get("dernier_usage")]
            comptes.append({"user_id": u["id"], "email": u.get("email"), "nom": u.get("full_name"), "role": u.get("role"),
                            "nb": len(u["passkeys"]), "dernier_usage": max(usages) if usages else None,
                            "passkeys": [_vue(p) for p in u["passkeys"]]})
        return {"enabled": r["enabled"], "rp_id_reglage": r["rp_id"], "rp_id_effectif": domaine, "max_par_compte": MAX_PAR_COMPTE, "comptes": comptes}

    @api.put("/admin/passkeys/config", tags=["Passkeys"])
    async def admin_passkeys_config(payload: PasskeyConfig, user: dict = Depends(get_current_user)):
        exiger_admin(user)
        rp = (payload.rp_id or "").strip().lower()
        if rp and not _RP_VALIDE.match(rp):
            raise HTTPException(status_code=422, detail="Domaine invalide (exemple : sawalismartsystems.com)")
        await db.settings.update_one({"_id": "global"}, {"$set": {"passkeys_enabled": payload.enabled, "passkeys_rp_id": rp or None}}, upsert=True)
        logger.info("[passkeys] réglage : activée=%s domaine=%s par %s", payload.enabled, rp or "(automatique)", user.get("id"))
        return {"ok": True, "enabled": payload.enabled, "rp_id": rp or None}

    @api.delete("/admin/passkeys/user/{user_id}", tags=["Passkeys"])
    async def admin_revoquer(user_id: str, user: dict = Depends(get_current_user)):
        """Révoque TOUTES les passkeys d'un compte (téléphone perdu, départ d'une personne)."""
        exiger_admin(user)
        res = await db.users.update_one({"id": user_id, "passkeys.0": {"$exists": True}}, {"$set": {"passkeys": []}})
        if res.modified_count == 0:
            raise HTTPException(status_code=404, detail="Ce compte n'a aucune passkey")
        logger.info("[passkeys] passkeys du compte %s révoquées par %s", user_id, user.get("id"))
        return {"ok": True}


__all__ = ["attach_passkey_routes", "origine_et_domaine"]
