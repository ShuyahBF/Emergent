"""Lot 484 — CONNEXION RAPIDE de « Loois Mobile » : biométrie, compte Google, clé d'accès (passkey). Voir `connexion_rapide.py` pour les principes.

Routes (sous /api) — l'appareil est reconnu par son jeton (comme toutes les routes Android) :
   GET    /android/rapide/config               — ce qui est disponible (Google configuré ? domaine des clés d'accès ?)
   GET    /android/rapide/liste                — session : mes connexions rapides sur cet appareil
   POST   /android/rapide/biometrie/activer    — session : remet un secret aléatoire (une seule fois) au téléphone
   POST   /android/rapide/google/activer       — session : lie le compte Google (jeton d'identité vérifié)
   POST   /android/rapide/cle/options          — session : défi d'enregistrement d'une clé d'accès
   POST   /android/rapide/cle/activer          — session : enregistre la clé publique
   POST   /android/rapide/cle/options-connexion— appareil : défi de connexion
   POST   /android/rapide/connexion            — appareil : connexion rapide (méthode + preuve) → même réponse que /android/connexion
   DELETE /android/rapide/{id}                 — session : retirer une de mes connexions rapides
   GET    /admin/android-rapide                — administrateur : toutes les liaisons ; DELETE /admin/android-rapide/{id} : en révoquer une
   GET    /.well-known/assetlinks.json         — public : autorise l'application à utiliser les clés d'accès du domaine (Credential Manager)
SÛRETÉ : le mot de passe n'est jamais gardé ; l'utilisateur doit toujours exister chez le client (relu à chaque connexion rapide) ; 5 essais ratés par appareil
et par identifiant en 15 minutes ; le contrôle Google se fait AUPRÈS DE GOOGLE (jeton signé) et jamais sur la seule parole du téléphone.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from webauthn import (generate_authentication_options, generate_registration_options, options_to_json, verify_authentication_response,
                      verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement)

import android_loois as al
import connexion_rapide as cr
from routes.liluvine_partage import est_admin

logger = logging.getLogger("sawali.connexion_rapide")
TYPE_DEFI = "loois_cle_defi"
DUREE_DEFI_S = 180
RP_PAR_DEFAUT = "api.sawalismartsystems.com"          # le fichier assetlinks.json est servi par ce domaine (le serveur d'API)
TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"


class CorpsGoogle(BaseModel):
    id_token: str = Field(min_length=20, max_length=4000)


class CorpsCleActiver(BaseModel):
    challenge_id: str
    credential: Dict[str, Any]
    nom: str = Field(default="", max_length=60)


class CorpsCleOptions(BaseModel):
    login: str = Field(default="", max_length=40)


class CorpsConnexionRapide(BaseModel):
    methode: str
    login: str = Field(default="", max_length=40)              # biométrie et clé d'accès : identifiant mémorisé sur le téléphone ; Google : facultatif
    secret: str = Field(default="", max_length=200)
    id_token: str = Field(default="", max_length=4000)
    challenge_id: str = Field(default="", max_length=80)
    credential: Optional[Dict[str, Any]] = None


def _rp_id() -> str:
    return (os.environ.get("LOOIS_RP_ID") or RP_PAR_DEFAUT).strip().lower()


def attacher_connexion_rapide(*, db, api, get_current_user, appareil_dep, session_dep, journal: Callable, emettre: Callable, executer: Callable, interne: Callable) -> None:
    async def _client_google() -> str:
        s = await db.settings.find_one({"_id": "global"}) or {}
        return (os.environ.get("GOOGLE_CLIENT_ID") or s.get("google_client_id") or "").strip()

    async def _verifier_google(id_token: str) -> Dict[str, Any]:
        """Interroge Google (jeton signé par Google) : renvoie les informations vérifiées ou refuse. Appel déclenché par l'utilisateur lui-même (connexion), délai borné."""
        client_id = await _client_google()
        if not client_id:
            raise HTTPException(status_code=503, detail="La connexion par Google n'est pas configurée sur SAWALI (Paramètres → Connexion par compte Google).")
        try:
            async with httpx.AsyncClient(timeout=8.0) as http:
                r = await http.get(TOKENINFO, params={"id_token": id_token})
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=503, detail="Google ne répond pas : réessayez, ou utilisez votre mot de passe.")
        if r.status_code != 200:
            raise HTTPException(status_code=401, detail="Jeton Google refusé.")
        infos = r.json()
        ok, raison = cr.verifier_jeton_google(infos, client_id)
        if not ok:
            raise HTTPException(status_code=401, detail=raison)
        return infos

    async def _defi(objet: str, appareil_id: str, login: str, defi: bytes) -> str:
        maintenant = datetime.now(timezone.utc)
        await db.otps.delete_many({"type": TYPE_DEFI, "expires_at": {"$lt": maintenant.isoformat()}})
        ident = cr.nouvelle_liaison(appareil_id, "", "", login or "-", "defi")["id"]
        await db.otps.insert_one({"id": ident, "type": TYPE_DEFI, "objet": objet, "appareil": appareil_id, "login": (login or "").upper(), "used": False,
                                  "challenge": bytes_to_base64url(defi), "expires_at": (maintenant + timedelta(seconds=DUREE_DEFI_S)).isoformat()})
        return ident

    async def _consommer_defi(ident: str, objet: str, appareil_id: str) -> Dict[str, Any]:
        doc = await db.otps.find_one_and_update({"id": ident, "type": TYPE_DEFI, "objet": objet, "appareil": appareil_id, "used": False}, {"$set": {"used": True}})
        if not doc or doc.get("expires_at", "") < datetime.now(timezone.utc).isoformat():
            raise HTTPException(status_code=400, detail="Défi expiré ou invalide : recommencez.")
        return doc

    def _origines() -> List[str]:
        return [cr.origine_android(e) for e in cr.empreintes_apk(os.environ.get("LOOIS_APK_SHA256", ""))]

    async def _ajouter(liaison: Dict[str, Any]) -> None:
        """Une liaison par (appareil, identifiant, méthode) : l'ancienne est remplacée ; plafond global."""
        liaisons = await cr.lire(db)
        anciennes = [l["id"] for l in cr.trouver(liaisons, liaison["appareil"], liaison["methode"], liaison["login"])] if liaison["methode"] != "cle" else []
        if len(liaisons) - len(anciennes) >= cr.MAX_LIAISONS:
            raise HTTPException(status_code=507, detail="Trop de connexions rapides enregistrées : contactez l'administrateur.")
        await cr.retirer(db, anciennes)
        await cr.ecrire_liaison(db, liaison)

    # ------------------------------------------------------------------------------------------------------------------ configuration et liste
    @api.get("/android/rapide/config", tags=["Loois mobile (Android)"])
    async def config(appareil: Dict[str, Any] = Depends(appareil_dep)):
        cid = await _client_google()
        return {"biometrie": True, "google": bool(cid), "google_client_id": cid, "cle_acces": True, "rp_id": _rp_id()}

    @api.get("/android/rapide/liste", tags=["Loois mobile (Android)"])
    async def liste(s: Dict[str, Any] = Depends(session_dep)):
        liaisons = await cr.lire(db)
        mes = [cr.vue(l) for l in liaisons.values() if l.get("appareil") == s["appareil"]["id"] and l.get("login") == s["login"].upper()]
        return {"liaisons": sorted(mes, key=lambda v: v["cree_le"] or "", reverse=True)}

    # ------------------------------------------------------------------------------------------------------------------ activation (utilisateur déjà connecté par mot de passe)
    @api.post("/android/rapide/biometrie/activer", tags=["Loois mobile (Android)"])
    async def biometrie_activer(s: Dict[str, Any] = Depends(session_dep)):
        a = s["appareil"]
        secret = cr.nouveau_secret()
        liaison = cr.nouvelle_liaison(a["id"], a["client_code"], a["zone"], s["login"], "biometrie", empreinte=cr.empreinte(secret))
        await _ajouter(liaison)
        await journal(a, s["login"], "rapide_activer", "biométrie", "ok")
        return {"id": liaison["id"], "secret": secret}

    @api.post("/android/rapide/google/activer", tags=["Loois mobile (Android)"])
    async def google_activer(corps: CorpsGoogle, s: Dict[str, Any] = Depends(session_dep)):
        a = s["appareil"]
        infos = await _verifier_google(corps.id_token)
        liaisons = await cr.lire(db)
        autre = next((l for l in liaisons.values() if l.get("methode") == "google" and l.get("google_sub") == infos["sub"] and l.get("appareil") == a["id"]
                      and l.get("login") != s["login"].upper() and l.get("zone") == a["zone"]), None)
        if autre:
            raise HTTPException(status_code=409, detail="Ce compte Google est déjà lié à un autre identifiant de cette zone sur cet appareil.")
        liaison = cr.nouvelle_liaison(a["id"], a["client_code"], a["zone"], s["login"], "google", google_sub=infos["sub"], email_masque=cr.masquer_email(infos.get("email", "")))
        await _ajouter(liaison)
        await journal(a, s["login"], "rapide_activer", "google", "ok")
        return {"id": liaison["id"], "detail": liaison["email_masque"]}

    @api.post("/android/rapide/cle/options", tags=["Loois mobile (Android)"])
    async def cle_options(s: Dict[str, Any] = Depends(session_dep)):
        a = s["appareil"]
        existantes = cr.trouver(await cr.lire(db), a["id"], "cle", s["login"])
        options = generate_registration_options(
            rp_id=_rp_id(), rp_name="SAWALI — Loois mobile", user_id=f"{a['id']}:{s['login'].upper()}".encode(), user_name=s["login"], user_display_name=s["login"],
            authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(l["cred_id"])) for l in existantes])
        return {"challenge_id": await _defi("enregistrement", a["id"], s["login"], options.challenge), "options": json.loads(options_to_json(options))}

    @api.post("/android/rapide/cle/activer", tags=["Loois mobile (Android)"])
    async def cle_activer(corps: CorpsCleActiver, s: Dict[str, Any] = Depends(session_dep)):
        a = s["appareil"]
        doc = await _consommer_defi(corps.challenge_id, "enregistrement", a["id"])
        if doc.get("login") != s["login"].upper():
            raise HTTPException(status_code=400, detail="Défi d'un autre identifiant.")
        try:
            v = verify_registration_response(credential=corps.credential, expected_challenge=base64url_to_bytes(doc["challenge"]), expected_rp_id=_rp_id(),
                                             expected_origin=_origines(), require_user_verification=True)
        except Exception as exc:  # noqa: BLE001 — toute anomalie = refus, sans indice sur la cause
            logger.info("[rapide] enregistrement de clé refusé : %s", exc)
            raise HTTPException(status_code=400, detail="Enregistrement refusé : la clé d'accès n'a pas pu être vérifiée.")
        cred_id = bytes_to_base64url(v.credential_id)
        if any(l.get("cred_id") == cred_id for l in (await cr.lire(db)).values()):
            raise HTTPException(status_code=409, detail="Cette clé d'accès est déjà enregistrée.")
        nom = " ".join((corps.nom or "").split()) or "Clé d'accès du téléphone"
        liaison = cr.nouvelle_liaison(a["id"], a["client_code"], a["zone"], s["login"], "cle", cred_id=cred_id, public_key=bytes_to_base64url(v.credential_public_key),
                                      sign_count=v.sign_count, nom=nom)
        if len(cr.trouver(await cr.lire(db), a["id"], "cle", s["login"])) >= cr.MAX_PAR_APPAREIL_LOGIN:
            raise HTTPException(status_code=400, detail="3 clés d'accès au plus par identifiant : retirez-en une d'abord.")
        await _ajouter(liaison)
        await journal(a, s["login"], "rapide_activer", "clé d'accès", "ok")
        return {"id": liaison["id"], "detail": nom}

    @api.delete("/android/rapide/{ident}", tags=["Loois mobile (Android)"])
    async def retirer_liaison(ident: str, s: Dict[str, Any] = Depends(session_dep)):
        liaisons = await cr.lire(db)
        l = liaisons.get(ident)
        if not l or l.get("appareil") != s["appareil"]["id"] or l.get("login") != s["login"].upper():
            raise HTTPException(status_code=404, detail="Connexion rapide introuvable.")
        await cr.retirer(db, [ident])
        await journal(s["appareil"], s["login"], "rapide_retirer", l["methode"], "ok")
        return {"ok": True}

    # ------------------------------------------------------------------------------------------------------------------ connexion
    @api.post("/android/rapide/cle/options-connexion", tags=["Loois mobile (Android)"])
    async def cle_options_connexion(corps: CorpsCleOptions, a: Dict[str, Any] = Depends(appareil_dep)):
        liaisons = cr.trouver(await cr.lire(db), a["id"], "cle", corps.login)
        if not liaisons:
            raise HTTPException(status_code=404, detail="Aucune clé d'accès enregistrée sur cet appareil : connectez-vous avec votre mot de passe.")
        options = generate_authentication_options(rp_id=_rp_id(), user_verification=UserVerificationRequirement.REQUIRED,
                                                  allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(l["cred_id"])) for l in liaisons])
        return {"challenge_id": await _defi("connexion", a["id"], corps.login, options.challenge), "options": json.loads(options_to_json(options))}

    @api.post("/android/rapide/connexion", tags=["Loois mobile (Android)"])
    async def connexion_rapide(corps: CorpsConnexionRapide, a: Dict[str, Any] = Depends(appareil_dep)):
        if corps.methode not in cr.METHODES:
            raise HTTPException(status_code=422, detail="Méthode de connexion inconnue.")
        espace = al.espace_de_la_zone(a["zone"])
        if espace is None:
            raise HTTPException(status_code=422, detail="Cette zone n'est pas encore prise en charge par Loois mobile.")
        cle_e = al.cle_essais(a["id"], "rapide|" + (corps.login or "?").upper())
        if al.essais_restants(cle_e) <= 0:
            await journal(a, corps.login, "connexion_rapide", f"{corps.methode} : trop d'essais", "refuse")
            raise HTTPException(status_code=429, detail="Trop d'essais : réessayez dans 15 minutes ou utilisez votre mot de passe.")
        liaisons = await cr.lire(db)

        def refuser(detail: str):
            al.noter_echec(cle_e)
            return HTTPException(status_code=401, detail=detail)

        liaison: Optional[Dict[str, Any]] = None
        if corps.methode == "biometrie":
            if not corps.login or not corps.secret:
                raise HTTPException(status_code=422, detail="Identifiant et secret biométrique requis.")
            liaison = next((l for l in cr.trouver(liaisons, a["id"], "biometrie", corps.login) if cr.secret_correspond(corps.secret, l.get("empreinte", ""))), None)
            if liaison is None:
                await journal(a, corps.login, "connexion_rapide", "biométrie refusée", "refuse")
                raise refuser("Connexion biométrique refusée : reconnectez-vous avec votre mot de passe puis réactivez-la.")
        elif corps.methode == "google":
            infos = await _verifier_google(corps.id_token)
            candidats = [l for l in cr.trouver(liaisons, a["id"], "google", corps.login) if l.get("google_sub") == infos["sub"]]
            if len(candidats) != 1:
                await journal(a, corps.login, "connexion_rapide", "google : aucune liaison" if not candidats else "google : plusieurs identifiants", "refuse")
                raise refuser("Ce compte Google n'est lié à aucun identifiant sur cet appareil (ou à plusieurs : choisissez l'identifiant)." if candidats else
                              "Ce compte Google n'est lié à aucun identifiant sur cet appareil : connectez-vous avec votre mot de passe, puis liez-le dans Paramètres.")
            liaison = candidats[0]
        else:  # clé d'accès
            if not corps.credential or not corps.challenge_id:
                raise HTTPException(status_code=422, detail="Réponse de la clé d'accès manquante.")
            doc = await _consommer_defi(corps.challenge_id, "connexion", a["id"])
            ident = corps.credential.get("id")
            liaison = next((l for l in cr.trouver(liaisons, a["id"], "cle") if l.get("cred_id") == ident), None)
            if liaison is None:
                raise refuser("Clé d'accès inconnue ou retirée : connectez-vous avec votre mot de passe.")
            try:
                v = verify_authentication_response(credential=corps.credential, expected_challenge=base64url_to_bytes(doc["challenge"]), expected_rp_id=_rp_id(),
                                                   expected_origin=_origines(), credential_public_key=base64url_to_bytes(liaison["public_key"]),
                                                   credential_current_sign_count=int(liaison.get("sign_count") or 0), require_user_verification=True)
            except Exception as exc:  # noqa: BLE001
                logger.info("[rapide] connexion par clé d'accès refusée : %s", exc)
                await journal(a, liaison.get("login", ""), "connexion_rapide", "clé d'accès non vérifiée", "refuse")
                raise refuser("Clé d'accès non vérifiée : réessayez ou utilisez votre mot de passe.")
            liaison["sign_count"] = v.new_sign_count
        # L'utilisateur doit TOUJOURS exister chez le client (relu à chaque connexion rapide, sans mot de passe)
        login = liaison["login"]
        vue = await executer(a, al.sql_utilisateur_connu(espace, login), tolerant=True)
        lignes = vue.get("lignes") or []
        if not lignes:
            await journal(a, login, "connexion_rapide", f"{corps.methode} : utilisateur introuvable chez le client", "refuse")
            raise HTTPException(status_code=401, detail="Cet identifiant n'existe plus chez le client (ou le client ne répond pas) : connectez-vous avec votre mot de passe.")
        al.effacer_echecs(cle_e)
        autoriser = al.vrai(lignes[0][1]) if espace["autoriser"] and len(lignes[0]) > 1 else False
        liaison["dernier_usage"] = cr.maintenant_iso()
        await cr.ecrire_liaison(db, liaison)
        return await emettre(a, espace, str(lignes[0][0]).strip() or login, autoriser, f"rapide : {corps.methode}")

    # ------------------------------------------------------------------------------------------------------------------ administrateur
    @api.get("/admin/android-rapide", tags=["Loois mobile (Android)"])
    async def admin_liste(user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur.")
        liaisons = await cr.lire(db)
        google = await _client_google()
        return {"google_configure": bool(google), "rp_id": _rp_id(), "origines": _origines(),
                "liaisons": [{**cr.vue(l), "appareil": l.get("appareil"), "client": l.get("client")} for l in sorted(liaisons.values(), key=lambda x: x.get("cree_le") or "", reverse=True)]}

    @api.delete("/admin/android-rapide/{ident}", tags=["Loois mobile (Android)"])
    async def admin_revoquer(ident: str, user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur.")
        if ident not in await cr.lire(db):
            raise HTTPException(status_code=404, detail="Connexion rapide introuvable.")
        await cr.retirer(db, [ident])
        return {"ok": True}


def attacher_assetlinks(app) -> None:
    """Fichier public /.well-known/assetlinks.json (hors /api) : sans lui, Android refuse les clés d'accès du domaine."""
    @app.get("/.well-known/assetlinks.json", include_in_schema=False)
    async def assetlinks():
        return cr.assetlinks(cr.empreintes_apk(os.environ.get("LOOIS_APK_SHA256", "")))
