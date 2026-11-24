"""Connexion par compte Google (SAWALI) : démarrer, retour de Google, échange du code, liaison / déliaison depuis « Mon compte », état pour l'administrateur.

Déroulé et règles de sécurité : voir backend/google_auth.py (flux « à code » serveur → Google → serveur, état signé, code à usage unique).
Spécificités SAWALI :
  - l'identifiant client et le SECRET du client sont ceux DÉJÀ saisis pour Google Agenda dans les Paramètres (`google_client_id`, `google_client_secret`),
    ou les variables d'environnement GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET ; seule l'adresse de retour de cette connexion est à déclarer en plus chez Google ;
  - AUCUN compte n'est créé ni rapproché par e-mail : seul un compte DÉJÀ LIÉ (depuis « Mon compte », connecté) ouvre une session par Google ;
  - Google remplace le mot de passe, PAS le code de vérification : après l'échange, le code à 6 chiffres (e-mail) est envoyé comme pour un mot de passe
    et la session s'ouvre par POST /auth/verify-otp (contrôles du compte, maintenance, cycle de vie et IP bloquée inclus).
"""
from __future__ import annotations

import json
import logging
import os
import time
from html import escape
from typing import Any, Dict
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

import auth as auth_module
import connexions_ip
import google_auth

logger = logging.getLogger("sawali.google")
SCHEMA_APP = "sawali"            # réservé à une application Android (non utilisé : site seul pour l'instant)


# Modèles au NIVEAU DU MODULE : FastAPI ne retrouve pas les modèles déclarés dans une fonction (annotations différées)
class DemandeLiaison(BaseModel):
    cible: str = Field("web", max_length=3)

class Echange(BaseModel):
    code: str = Field(min_length=10, max_length=100)

class Deliaison(BaseModel):
    mot_de_passe: str = Field(min_length=1, max_length=128)


async def echanger_code(code: str, adresse_retour: str, cid: str, secret: str) -> dict | None:
    """Échange le code contre l'identité (appel externe, seulement ici). Rend { sub, email, nom } ou None. Remplacé par un faux dans les tests."""
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            rep = await http.post(google_auth.URL_JETON, data={"code": code, "client_id": cid, "client_secret": secret,
                                                               "redirect_uri": adresse_retour, "grant_type": "authorization_code"})
        return google_auth.identite_depuis_jeton(rep.json().get("id_token", ""), cid) if rep.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


def attach_google_routes(api: APIRouter | FastAPI, *, db, helpers: Dict[str, Any]) -> None:
    """`helpers` : get_current_user, verify_password, emettre_otp (async : envoie le code de vérification et rend la réponse de /auth/login),
    controles_connexion (async : statut du compte, maintenance, cycle de vie, IP bloquée)."""
    get_current_user = helpers["get_current_user"]
    verify_password = helpers["verify_password"]
    emettre_otp = helpers["emettre_otp"]
    controles_connexion = helpers["controles_connexion"]

    async def _client() -> tuple[str, str]:
        """(identifiant client, secret) : variables d'environnement d'abord, sinon réglages de Google Agenda."""
        s = await db.settings.find_one({"_id": "global"}) or {}
        return (os.environ.get("GOOGLE_CLIENT_ID") or s.get("google_client_id") or "",
                os.environ.get("GOOGLE_CLIENT_SECRET") or s.get("google_client_secret") or "")

    async def _configure() -> bool:
        cid, secret = await _client()
        return bool(cid and secret)

    def _adresse_retour(request: Request) -> str:
        """Adresse de retour déclarée chez Google (GOOGLE_REDIRECT_URI, sinon déduite de la requête, en https hors poste local)."""
        if os.environ.get("GOOGLE_REDIRECT_URI"):
            return os.environ["GOOGLE_REDIRECT_URI"]
        base = str(request.base_url).rstrip("/")
        if base.startswith("http://") and not base.startswith("http://localhost"):
            base = "https://" + base[len("http://"):]
        return f"{base}/api/auth/google/retour"

    def _site(request: Request) -> str:
        """Adresse du site web où renvoyer la personne : GOOGLE_RETOUR_SITE, sinon l'adresse de l'API sans le « api. » du début."""
        if os.environ.get("GOOGLE_RETOUR_SITE"):
            return os.environ["GOOGLE_RETOUR_SITE"].rstrip("/")
        base = str(request.base_url).rstrip("/")
        return base.replace("://api.", "://", 1)

    def _vers_site(request: Request, cible: str, **params):
        params = {k: v for k, v in params.items() if v}
        if cible == "app":
            lien = f"{SCHEMA_APP}://google?{urlencode(params)}"
            return HTMLResponse(f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>SAWALI</title>"
                                f"<body style='font-family:sans-serif;text-align:center;padding:2rem'><p>Retour dans l'application SAWALI…</p>"
                                f"<p><a href=\"{escape(lien)}\" style='display:inline-block;padding:1rem 2rem;background:#0a3d8f;color:#fff;border-radius:2rem;text-decoration:none'>Retourner dans l'application</a></p>"
                                f"<script>location.href={json.dumps(lien)}</script></body>")
        return RedirectResponse(f"{_site(request)}/connexion-google?{urlencode(params)}", status_code=302)

    @api.get("/auth/google/config", tags=["Google"])
    async def google_config():
        """Le site n'affiche le bouton Google que si le serveur est configuré."""
        return {"disponible": await _configure()}

    @api.get("/auth/google/demarrer", tags=["Google"])
    async def google_demarrer(request: Request, cible: str = "web"):
        if not await _configure():
            raise HTTPException(status_code=503, detail="La connexion par Google n'est pas encore activée")
        cid, _ = await _client()
        etat = google_auth.signer_etat(cible, None, auth_module.JWT_SECRET)
        return RedirectResponse(google_auth.url_demarrage(cid, _adresse_retour(request), etat), status_code=302)

    @api.post("/auth/google/lier-url", tags=["Google"])
    async def google_lier_url(data: DemandeLiaison, request: Request, user: dict = Depends(get_current_user)):
        """Adresse de Google pour LIER le compte connecté (l'identité du compte est dans l'état signé)."""
        if not await _configure():
            raise HTTPException(status_code=503, detail="La connexion par Google n'est pas encore activée")
        cid, _ = await _client()
        etat = google_auth.signer_etat(data.cible, user["id"], auth_module.JWT_SECRET)
        return {"url": google_auth.url_demarrage(cid, _adresse_retour(request), etat)}

    @api.get("/auth/google/retour", tags=["Google"])
    async def google_retour(request: Request, code: str = "", state: str = "", error: str = ""):
        etat = google_auth.lire_etat(state, auth_module.JWT_SECRET)
        if not etat:
            return _vers_site(request, "web", erreur="etat")
        cible = etat.get("c", "web")
        if error or not code or not await _configure():
            return _vers_site(request, cible, erreur="refuse")
        cid, secret = await _client()
        identite = await echanger_code(code, _adresse_retour(request), cid, secret)
        if not identite:
            return _vers_site(request, cible, erreur="google")
        existant = await db.users.find_one({"google.sub": identite["sub"]}, {"_id": 0, "id": 1, "account_status": 1})
        if etat.get("l"):                                                       # liaison du compte connecté
            if existant and existant["id"] != etat["l"]:
                return _vers_site(request, cible, erreur="deja_lie")
            await db.users.update_one({"id": etat["l"]}, {"$set": {"google": {"sub": identite["sub"], "email": identite["email"],
                                                                              "lie_le": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}})
            return _vers_site(request, cible, lie="1")
        if not existant:                                                        # connexion : seulement un compte déjà lié
            return _vers_site(request, cible, erreur="aucun_compte")
        clair, empreinte = google_auth.nouveau_code()
        await db.google_codes.insert_one({"empreinte": empreinte, "user_id": existant["id"], "expire": time.time() + google_auth.VALIDITE_CODE_S})
        return _vers_site(request, cible, code=clair)

    @api.post("/auth/google/echange", tags=["Google"])
    async def google_echange(data: Echange, request: Request):
        """Le site remet le code à usage unique (reçu de Google). Le code est consommé tout de suite (une seule utilisation) ;
        la réponse est celle de /auth/login : un code de vérification est envoyé, la session s'ouvre par /auth/verify-otp."""
        ligne = await db.google_codes.find_one_and_delete({"empreinte": google_auth.empreinte_code(data.code)})
        if not ligne or ligne.get("expire", 0) < time.time():
            raise HTTPException(status_code=401, detail="Connexion Google expirée : recommencez")
        user = await db.users.find_one({"id": ligne["user_id"]})
        if not user:
            raise HTTPException(status_code=401, detail="Compte indisponible")
        await controles_connexion(user, request, "google")
        return await emettre_otp(user)

    @api.get("/auth/google/etat", tags=["Google"])
    async def google_etat(user: dict = Depends(get_current_user)):
        fiche = await db.users.find_one({"id": user["id"]}, {"_id": 0, "google": 1}) or {}
        g = fiche.get("google") or {}
        return {"disponible": await _configure(), "lie": bool(g.get("sub")), "email": g.get("email", ""), "lie_le": g.get("lie_le", "")}

    @api.post("/auth/google/delier", tags=["Google"])
    async def google_delier(data: Deliaison, user: dict = Depends(get_current_user)):
        """Retire la liaison : le mot de passe est redemandé (on prouve qu'on est le titulaire)."""
        import asyncio
        fiche = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 1}) or {}
        if not await asyncio.to_thread(verify_password, data.mot_de_passe, fiche.get("password_hash") or ""):
            raise HTTPException(status_code=400, detail="Mot de passe incorrect")
        await db.users.update_one({"id": user["id"]}, {"$unset": {"google": ""}})
        return {"ok": True}

    @api.get("/admin/google-connexion", tags=["Google"])
    async def google_admin(request: Request, user: dict = Depends(get_current_user)):
        """Paramètres (administrateur) : le client Google est-il configuré, adresse de retour à déclarer chez Google, nombre de comptes liés."""
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return {"configure": await _configure(), "adresse_retour": _adresse_retour(request), "site": _site(request),
                "comptes_lies": await db.users.count_documents({"google.sub": {"$type": "string"}})}


__all__ = ["attach_google_routes"]
