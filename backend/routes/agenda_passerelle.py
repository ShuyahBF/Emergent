# agenda_passerelle.py — Lot 403 : SAWALI = PASSERELLE « Agenda Google » pour les autres plateformes (auRor, Concentration, Personnel Maison…).
#
# Principe (pour un développeur WinDev) :
#   - Chaque UTILISATEUR d'une plateforme lie SON compte Google à SAWALI (une seule fois, par la page d'autorisation de Google).
#     SAWALI garde, par utilisateur, un « jeton d'actualisation » CHIFFRÉ (Fernet dérivé de JWT_SECRET) ; la plateforme ne voit JAMAIS de jeton Google.
#   - Les plateformes parlent à SAWALI par des appels SIGNÉS, comme pour les paiements SMS :
#       * plateforme serveur (auRor, Personnel Maison…) : en-têtes X-Emetteur / X-Timestamp / X-Signature (HMAC-SHA256 du corps avec la clé de l'émetteur)
#         + « utilisateur » dans le corps (identifiant de l'utilisateur DANS la plateforme) ;
#       * application sans serveur (Concentration, Personnel de maison) : en-têtes X-Appareil / X-Cle-Appareil, que l'application GÉNÈRE ELLE-MÊME au premier usage
#         (aucun réglage à saisir) ; l'appareil est enregistré à sa première « demande d'accès » (avec le compte Google déclaré et le nom de l'appareil) et ne peut RIEN
#         faire d'autre tant que l'administrateur n'a pas accepté la demande. Ancien mode toujours accepté : X-Source / X-Cle (téléphones source de « Transactions SMS »).
#     L'utilisateur est donc toujours identifié par (plateforme, identifiant) : une requête ne peut JAMAIS atteindre l'agenda d'un autre utilisateur.
#   - Confidentialité : l'administrateur de SAWALI ne peut pas lire les agendas des utilisateurs ; il voit seulement le NOMBRE de liaisons par plateforme.
#
#   POST /api/webhook/agenda/lier       {utilisateur, retour?}        -> {url}            à ouvrir dans le navigateur (consentement Google)
#   GET  /api/agenda/retour?code&state                                 (retour de Google : enregistre la liaison, page de confirmation)
#   POST /api/webhook/agenda/demander   {utilisateur, gmail, nom?}    -> {etat}           demande d'accès : l'administrateur de SAWALI l'accepte ou la refuse
#   POST /api/webhook/agenda/etat       {utilisateur}                  -> {lie, email, demande, gmail, approbation_requise}
#   POST /api/webhook/agenda/analyser   {texte, maintenant?}           -> proposition de RDV (jour, heure, titre) ; ne crée RIEN
#   POST /api/webhook/agenda/evenements {du?, au?, limite?}            -> événements de l'agenda principal
#   POST /api/webhook/agenda/creer      {titre, debut, fin?, lieu?, description?, rappel_minutes?}   (après CONFIRMATION de l'utilisateur)
#   POST /api/webhook/agenda/supprimer  {id}
#   POST /api/webhook/agenda/delier     {}                              -> retire la liaison (et révoque l'accès chez Google)
#   GET  /api/admin/agenda-passerelle/etat                              (administrateur : adresse de retour, nombre de liaisons, demandes d'accès)
#   POST /api/admin/agenda-passerelle/demandes/{id}  {decision: accepte|refuse}      PUT /api/admin/agenda-passerelle/approbation {actif}
#
# RESPONSABILISER LES UTILISATEURS : avec l'« approbation » active (défaut), un utilisateur doit d'abord DEMANDER l'accès en indiquant son compte Google ;
# l'administrateur accepte ou refuse ; seulement ensuite le bouton « Lier » fonctionne, et seul CE compte Google est accepté au retour de Google
# (un autre compte est refusé et son accès révoqué aussitôt). Cela décide aussi QUI occupe les places du plafond d'utilisateurs de Google.
#
# Stockage : documents de la collection `settings` (aucune nouvelle collection) : « agenda-utilisateurs:<clé> » (liaison) et « agenda-etat:<nonce> » (consentement en cours, 15 min).
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from agenda_parseur import FUSEAU_DEFAUT, analyser
from routes.contrats_plateformes import signature_valide

PREFIXE_LIAISON = "agenda-utilisateurs:"
PREFIXE_ETAT = "agenda-etat:"
ADRESSE_RETOUR_DEFAUT = "https://api.sawalismartsystems.com/api/agenda/retour"
PREFIXE_APPAREIL = "agenda-appareil:"     # { cle_hash, cree_le } : appareil qui s'est enregistré lui-même (clé générée par l'application)
MAX_APPAREILS = 3000                       # plafond : jamais de croissance illimitée par des demandes en rafale
ID_CONFIG = "agenda-config"          # { approbation: bool (défaut True), demandes: [ {id, plateforme, utilisateur, nom, gmail, etat, cree_le, decide_le} ] }
MAX_DEMANDES = 500
VALIDITE_CONSENTEMENT_MIN = 15
# Autorisations demandées : l'identité (e-mail) et les ÉVÉNEMENTS de l'agenda (pas le calendrier complet). À déclarer dans Google Auth Platform → Accès aux données.
SCOPES = os.environ.get("AGENDA_GOOGLE_SCOPES") or "openid email https://www.googleapis.com/auth/calendar.events"
URL_AUTORISATION = "https://accounts.google.com/o/oauth2/v2/auth"
URL_JETON = "https://oauth2.googleapis.com/token"
URL_REVOCATION = "https://oauth2.googleapis.com/revoke"
URL_INFOS = "https://openidconnect.googleapis.com/v1/userinfo"
API_AGENDA = "https://www.googleapis.com/calendar/v3"
# Adresses de retour acceptées après la liaison (jamais d'adresse libre : pas de redirection ouverte)
RETOURS_AUTORISES = ("https://", "auror://", "concentration://", "personnelmaison://")

_JETONS: Dict[str, Tuple[str, datetime]] = {}      # cache en mémoire : clé de liaison -> (jeton d'accès, expiration)


def _client() -> httpx.AsyncClient:
    """Client HTTP (remplacé par un faux dans les tests)."""
    return httpx.AsyncClient(timeout=20)


def _fernet() -> Fernet:
    secret = os.environ.get("JWT_SECRET") or "fallback-insecure-jwt"
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"sawali-agenda-utilisateurs::{secret}".encode()).digest()))


def chiffrer(clair: str) -> str:
    return _fernet().encrypt(clair.encode()).decode()


def dechiffrer(chiffre: str) -> Optional[str]:
    try:
        return _fernet().decrypt(chiffre.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def cle_liaison(plateforme: str, utilisateur: str) -> str:
    """Identité d'une liaison : (plateforme, utilisateur) condensés ; deux utilisateurs différents n'ont jamais la même clé."""
    return hashlib.sha256(f"{plateforme}|{utilisateur}".encode()).hexdigest()[:24]


def hacher_cle(cle: str) -> str:
    return hashlib.sha256((cle or "").encode()).hexdigest()


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def setup_agenda_passerelle_routes(db, api, get_current_user, public_base_url_fn=None):
    """Branche les routes sur l'application (même convention que Transactions SMS)."""

    def _base(request: Request) -> str:
        base = ""
        if public_base_url_fn:
            try:
                base = public_base_url_fn(request) or ""
            except TypeError:
                base = public_base_url_fn() or ""
        return (base or os.environ.get("PUBLIC_BASE_URL") or str(request.base_url)).rstrip("/")

    def _adresse_retour(request: Request) -> str:
        """Adresse de retour de Google : FIXE (jamais déduite de la page ou de l'application qui fait la demande). Google compare cette adresse, caractère par caractère, à celle
        déclarée dans « Clients → URI de redirection autorisés » : si elle changeait selon le site d'origine (sawalismartsystems.com, api.sawalismartsystems.com…), Google répondrait
        « redirect_uri_mismatch ». Réglable par la variable d'environnement AGENDA_ADRESSE_RETOUR ; l'écran des Paramètres affiche exactement cette valeur."""
        return (os.environ.get("AGENDA_ADRESSE_RETOUR") or ADRESSE_RETOUR_DEFAUT).strip()

    async def _identifiants_google() -> Tuple[str, str]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        if not s.get("google_client_id") or not s.get("google_client_secret"):
            raise HTTPException(status_code=503, detail="Google non configuré dans SAWALI (Client ID et Secret)")
        return s["google_client_id"], s["google_client_secret"]

    # ------------------------------------------------------------------ identification de l'appelant
    async def _appelant(request: Request, enregistrer: bool = False) -> Tuple[str, str, Dict[str, Any]]:
        """(plateforme, utilisateur, corps JSON). Trois modes ; sinon 401.
        `enregistrer` (seulement pour la demande d'accès) : un appareil inconnu qui présente une clé suffisamment longue est ENREGISTRÉ (clé gardée sous forme d'empreinte)."""
        brut = await request.body()
        try:
            corps = json.loads(brut.decode("utf-8") or "{}") if brut else {}
        except ValueError:
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        corps = corps if isinstance(corps, dict) else {}
        code = (request.headers.get("X-Emetteur") or "").strip().lower()
        if code:
            emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0})
            if not emetteur or not emetteur.get("actif", True) or not signature_valide(
                    emetteur.get("secret") or "", request.headers.get("X-Timestamp") or "", brut, request.headers.get("X-Signature") or "", maintenant()):
                raise HTTPException(status_code=401, detail="Plateforme inconnue ou signature refusée")
            utilisateur = str(corps.get("utilisateur") or "").strip()[:120]
            if not utilisateur:
                raise HTTPException(status_code=422, detail="« utilisateur » obligatoire")
            return code, utilisateur, corps
        appareil = (request.headers.get("X-Appareil") or "").strip()
        if appareil:
            cle = request.headers.get("X-Cle-Appareil") or ""
            if not re.fullmatch(r"[A-Za-z0-9]{16,64}", appareil) or len(cle) < 24:
                raise HTTPException(status_code=401, detail="Appareil refusé")
            doc = await db.settings.find_one({"_id": PREFIXE_APPAREIL + appareil})
            if doc:
                if not hmac.compare_digest(doc.get("cle_hash") or "", hacher_cle(cle)):
                    raise HTTPException(status_code=401, detail="Appareil refusé : clé différente")
            elif enregistrer:
                if await db.settings.count_documents({"_id": {"$regex": "^" + PREFIXE_APPAREIL}}) >= MAX_APPAREILS:
                    raise HTTPException(status_code=503, detail="Trop d'appareils enregistrés : réessayez plus tard")
                await db.settings.replace_one({"_id": PREFIXE_APPAREIL + appareil}, {"_id": PREFIXE_APPAREIL + appareil, "cle_hash": hacher_cle(cle), "cree_le": maintenant().isoformat()}, upsert=True)
            return "appareil", appareil, corps          # appareil inconnu et sans demande : aucune liaison ni demande n'existe pour lui (« etat » répond « non lié »)
        ident = (request.headers.get("X-Source") or "").strip()
        if ident:
            cfg = await db.settings.find_one({"_id": "transactions-sms:config"}) or {}
            source = next((s for s in (cfg.get("sources") or []) if s.get("id") == ident), None)
            if not source or not hmac.compare_digest(source.get("cle_hash") or "", hacher_cle(request.headers.get("X-Cle") or "")):
                raise HTTPException(status_code=401, detail="Téléphone inconnu ou clé refusée")
            return "appareil", ident, corps
        raise HTTPException(status_code=401, detail="Authentification requise (X-Emetteur + signature, ou X-Appareil + X-Cle-Appareil, ou X-Source + X-Cle)")

    # ------------------------------------------------------------------ demandes d'accès (approbation par l'administrateur)
    async def _config() -> Dict[str, Any]:
        doc = await db.settings.find_one({"_id": ID_CONFIG}) or {}
        return {"approbation": doc.get("approbation") is not False, "demandes": doc.get("demandes") or []}

    async def _ecrire_config(cfg: Dict[str, Any]) -> None:
        await db.settings.replace_one({"_id": ID_CONFIG}, {"_id": ID_CONFIG, **cfg}, upsert=True)

    def _id_demande(plateforme: str, utilisateur: str) -> str:
        return cle_liaison(plateforme, utilisateur)

    def _trouver(cfg: Dict[str, Any], plateforme: str, utilisateur: str) -> Optional[Dict[str, Any]]:
        return next((d for d in cfg["demandes"] if d["id"] == _id_demande(plateforme, utilisateur)), None)

    # ------------------------------------------------------------------ jetons Google
    async def _jeton_acces(cle: str) -> str:
        """Jeton d'accès de CET utilisateur (actualisé si besoin). 409 si la liaison n'existe pas ou a été retirée chez Google."""
        en_cache = _JETONS.get(cle)
        if en_cache and en_cache[1] > maintenant() + timedelta(seconds=60):
            return en_cache[0]
        doc = await db.settings.find_one({"_id": PREFIXE_LIAISON + cle})
        refresh = dechiffrer((doc or {}).get("refresh_chiffre") or "") if doc else None
        if not refresh:
            raise HTTPException(status_code=409, detail="Agenda non lié : reliez votre compte Google")
        client_id, secret = await _identifiants_google()
        async with _client() as http:
            r = await http.post(URL_JETON, data={"client_id": client_id, "client_secret": secret, "refresh_token": refresh, "grant_type": "refresh_token"})
        jeton = r.json() if r.content else {}
        if r.status_code != 200 or "access_token" not in jeton:
            if jeton.get("error") == "invalid_grant":          # l'utilisateur a retiré l'accès chez Google : la liaison n'est plus valable
                await db.settings.delete_one({"_id": PREFIXE_LIAISON + cle})
                _JETONS.pop(cle, None)
                raise HTTPException(status_code=409, detail="Liaison expirée ou retirée chez Google : reliez votre agenda")
            raise HTTPException(status_code=502, detail="Google a refusé l'actualisation de l'accès")
        _JETONS[cle] = (jeton["access_token"], maintenant() + timedelta(seconds=int(jeton.get("expires_in") or 3000)))
        return jeton["access_token"]

    async def _api(cle: str, methode: str, chemin: str, **kw) -> httpx.Response:
        jeton = await _jeton_acces(cle)
        async with _client() as http:
            r = await http.request(methode, f"{API_AGENDA}{chemin}", headers={"Authorization": f"Bearer {jeton}"}, **kw)
        if r.status_code == 401:
            _JETONS.pop(cle, None)
        if r.status_code >= 400 and r.status_code != 404 and r.status_code != 410:
            raise HTTPException(status_code=502, detail="Google Agenda a refusé la demande")
        return r

    # ------------------------------------------------------------------ liaison
    @api.post("/webhook/agenda/lier", tags=["Agenda — passerelle"])
    async def lier(request: Request):
        plateforme, utilisateur, corps = await _appelant(request)
        client_id, _ = await _identifiants_google()
        cfg = await _config()
        demande = _trouver(cfg, plateforme, utilisateur)
        if cfg["approbation"] and not (demande and demande["etat"] == "accepte"):
            raise HTTPException(status_code=403, detail="Demandez d'abord l'accès avec votre compte Google : l'administrateur doit l'accepter" if not demande else
                                ("Votre demande d'accès est en attente de l'administrateur" if demande["etat"] == "attente" else "Votre demande d'accès a été refusée"))
        nonce = secrets.token_urlsafe(24)
        retour = str(corps.get("retour") or "").strip()[:300]
        if retour and not retour.startswith(RETOURS_AUTORISES):
            retour = ""
        await db.settings.replace_one({"_id": PREFIXE_ETAT + nonce}, {
            "_id": PREFIXE_ETAT + nonce, "plateforme": plateforme, "utilisateur": utilisateur, "retour": retour,
            "expire": (maintenant() + timedelta(minutes=VALIDITE_CONSENTEMENT_MIN)).isoformat()}, upsert=True)
        url = URL_AUTORISATION + "?" + urlencode({
            "client_id": client_id, "redirect_uri": _adresse_retour(request), "response_type": "code", "scope": SCOPES,
            "access_type": "offline", "prompt": "consent select_account", "state": nonce,
            **({"login_hint": demande["gmail"]} if demande else {})})
        return {"url": url, "expire_minutes": VALIDITE_CONSENTEMENT_MIN}

    def _page(titre: str, message: str, retour: str = "", ok: bool = True) -> HTMLResponse:
        lien = f'<p><a href="{html.escape(retour)}">Retourner à l\'application</a></p>' if retour else "<p>Vous pouvez fermer cette page et revenir à l'application.</p>"
        couleur = "#047857" if ok else "#b91c1c"
        return HTMLResponse(f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                            f'<title>{html.escape(titre)}</title><body style="font-family:system-ui;max-width:28rem;margin:3rem auto;padding:0 1rem">'
                            f'<h1 style="color:{couleur};font-size:1.4rem">{html.escape(titre)}</h1><p>{html.escape(message)}</p>{lien}</body>', status_code=200 if ok else 400)

    @api.get("/agenda/retour", tags=["Agenda — passerelle"])
    async def retour_google(request: Request, code: str = "", state: str = "", error: str = ""):
        """Retour de Google après le consentement : le « state » (usage unique, 15 min) dit à QUEL utilisateur appartient la liaison."""
        etat = await db.settings.find_one({"_id": PREFIXE_ETAT + state}) if state else None
        if etat:
            await db.settings.delete_one({"_id": PREFIXE_ETAT + state})       # usage unique
        if not etat or etat.get("expire", "") < maintenant().isoformat():
            return _page("Lien expiré", "Cette demande de liaison a expiré ou a déjà servi. Recommencez depuis l'application.", ok=False)
        retour = etat.get("retour") or ""
        if error or not code:
            return _page("Liaison refusée", "L'accès à votre agenda n'a pas été accordé.", retour, ok=False)
        client_id, secret = await _identifiants_google()
        async with _client() as http:
            r = await http.post(URL_JETON, data={"code": code, "client_id": client_id, "client_secret": secret, "redirect_uri": _adresse_retour(request), "grant_type": "authorization_code"})
            jeton = r.json() if r.content else {}
            if "refresh_token" not in jeton:
                return _page("Liaison impossible", "Google n'a pas fourni l'autorisation permanente. Retirez l'accès de SAWALI sur myaccount.google.com/permissions puis recommencez.", retour, ok=False)
            infos = await http.get(URL_INFOS, headers={"Authorization": f"Bearer {jeton['access_token']}"})
        email = (infos.json() if infos.status_code == 200 else {}).get("email") or ""
        cfg = await _config()
        demande = _trouver(cfg, etat["plateforme"], etat["utilisateur"])
        if cfg["approbation"] and not (demande and demande["etat"] == "accepte" and demande["gmail"].lower() == email.lower()):
            try:                                                           # mauvais compte : l'accès est révoqué aussitôt, rien n'est gardé
                async with _client() as http:
                    await http.post(URL_REVOCATION, data={"token": jeton["refresh_token"]})
            except Exception:  # noqa: BLE001
                pass
            return _page("Compte non autorisé", f"Le compte Google « {email or 'inconnu'} » n'est pas celui accepté pour vous ({(demande or {}).get('gmail') or 'aucune demande acceptée'}). "
                         "Recommencez avec le bon compte.", retour, ok=False)
        cle = cle_liaison(etat["plateforme"], etat["utilisateur"])
        await db.settings.replace_one({"_id": PREFIXE_LIAISON + cle}, {
            "_id": PREFIXE_LIAISON + cle, "plateforme": etat["plateforme"], "utilisateur": etat["utilisateur"], "email": email,
            "refresh_chiffre": chiffrer(jeton["refresh_token"]), "lie_le": maintenant().isoformat()}, upsert=True)
        _JETONS.pop(cle, None)
        if retour:
            return RedirectResponse(url=retour + ("&" if "?" in retour else "?") + "agenda=ok")
        return _page("Agenda lié", f"Votre agenda Google{(' (' + email + ')') if email else ''} est lié. Vos rendez-vous sont visibles uniquement par vous.", retour)

    @api.post("/webhook/agenda/etat", tags=["Agenda — passerelle"])
    async def etat_liaison(request: Request):
        plateforme, utilisateur, _ = await _appelant(request)
        doc = await db.settings.find_one({"_id": PREFIXE_LIAISON + cle_liaison(plateforme, utilisateur)})
        cfg = await _config()
        demande = _trouver(cfg, plateforme, utilisateur)
        return {"lie": bool(doc), "email": (doc or {}).get("email") or "", "lie_le": (doc or {}).get("lie_le"),
                "approbation_requise": cfg["approbation"], "demande": (demande or {}).get("etat") or "", "gmail": (demande or {}).get("gmail") or ""}

    @api.post("/webhook/agenda/demander", tags=["Agenda — passerelle"])
    async def demander(request: Request):
        """L'utilisateur indique SON compte Google ; l'administrateur de SAWALI accepte ou refuse. Une nouvelle demande remplace la précédente (et repasse « en attente »)."""
        plateforme, utilisateur, corps = await _appelant(request, enregistrer=True)
        gmail = str(corps.get("gmail") or "").strip().lower()[:120]
        if not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", gmail):
            raise HTTPException(status_code=422, detail="Adresse e-mail du compte Google invalide")
        cfg = await _config()
        d = _trouver(cfg, plateforme, utilisateur)
        if d and d["etat"] == "accepte" and d["gmail"] == gmail:
            return {"etat": "accepte", "gmail": gmail}
        nouvelle = {"id": _id_demande(plateforme, utilisateur), "plateforme": plateforme, "utilisateur": utilisateur, "nom": str(corps.get("nom") or "")[:80],
                    "gmail": gmail, "etat": "attente", "cree_le": maintenant().isoformat(), "decide_le": None}
        cfg["demandes"] = [x for x in cfg["demandes"] if x["id"] != nouvelle["id"]] + [nouvelle]
        cfg["demandes"] = cfg["demandes"][-MAX_DEMANDES:]
        await _ecrire_config(cfg)
        return {"etat": "attente", "gmail": gmail}

    @api.post("/webhook/agenda/delier", tags=["Agenda — passerelle"])
    async def delier(request: Request):
        plateforme, utilisateur, _ = await _appelant(request)
        cle = cle_liaison(plateforme, utilisateur)
        doc = await db.settings.find_one({"_id": PREFIXE_LIAISON + cle})
        if doc:
            refresh = dechiffrer(doc.get("refresh_chiffre") or "")
            if refresh:
                try:
                    async with _client() as http:
                        await http.post(URL_REVOCATION, data={"token": refresh})
                except Exception:  # noqa: BLE001 — la liaison est retirée de SAWALI même si Google est injoignable
                    pass
            await db.settings.delete_one({"_id": PREFIXE_LIAISON + cle})
        _JETONS.pop(cle, None)
        return {"ok": True, "lie": False}

    # ------------------------------------------------------------------ note vocale -> proposition
    @api.post("/webhook/agenda/analyser", tags=["Agenda — passerelle"])
    async def analyser_note(request: Request):
        """Texte dicté -> proposition (jour, heure, titre). NE CRÉE RIEN : l'utilisateur confirme, puis l'application appelle « creer »."""
        _, _, corps = await _appelant(request)
        texte = str(corps.get("texte") or "").strip()[:500]
        if not texte:
            raise HTTPException(status_code=422, detail="« texte » obligatoire")
        quand = maintenant()
        if corps.get("maintenant"):
            try:
                quand = datetime.fromisoformat(str(corps["maintenant"]).replace("Z", "+00:00"))
            except ValueError:
                pass
        return analyser(texte, quand, str(corps.get("fuseau") or FUSEAU_DEFAUT))

    # ------------------------------------------------------------------ agenda
    def _evenement_public(e: Dict[str, Any]) -> Dict[str, Any]:
        debut, fin = e.get("start") or {}, e.get("end") or {}
        return {"id": e.get("id"), "titre": e.get("summary") or "(sans titre)", "debut": debut.get("dateTime") or debut.get("date"),
                "fin": fin.get("dateTime") or fin.get("date"), "toute_la_journee": "date" in debut, "lieu": e.get("location") or "", "lien": e.get("htmlLink") or ""}

    @api.post("/webhook/agenda/evenements", tags=["Agenda — passerelle"])
    async def evenements(request: Request):
        plateforme, utilisateur, corps = await _appelant(request)
        cle = cle_liaison(plateforme, utilisateur)
        debut = str(corps.get("du") or "") or maintenant().date().isoformat()
        fin = str(corps.get("au") or "") or (maintenant() + timedelta(days=14)).date().isoformat()

        def _iso(v: str, fin_de_jour: bool) -> str:
            try:
                d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(status_code=422, detail="Dates attendues au format AAAA-MM-JJ")
            if len(v) <= 10:
                d = d.replace(tzinfo=timezone.utc) + (timedelta(days=1) if fin_de_jour else timedelta())
            return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        limite = max(1, min(int(corps.get("limite") or 50), 250))
        r = await _api(cle, "GET", "/calendars/primary/events", params={"timeMin": _iso(debut, False), "timeMax": _iso(fin, True), "singleEvents": "true", "orderBy": "startTime", "maxResults": limite})
        return {"evenements": [_evenement_public(e) for e in (r.json().get("items") or [])]}

    @api.post("/webhook/agenda/creer", tags=["Agenda — passerelle"])
    async def creer(request: Request):
        plateforme, utilisateur, corps = await _appelant(request)
        cle = cle_liaison(plateforme, utilisateur)
        titre = str(corps.get("titre") or "").strip()[:200]
        if not titre:
            raise HTTPException(status_code=422, detail="« titre » obligatoire")
        try:
            debut = datetime.fromisoformat(str(corps.get("debut") or "").replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="« debut » attendu au format ISO avec fuseau, ex. 2026-11-21T08:15:00+00:00")
        if debut.tzinfo is None:
            raise HTTPException(status_code=422, detail="« debut » doit porter un fuseau horaire")
        try:
            fin = datetime.fromisoformat(str(corps["fin"]).replace("Z", "+00:00")) if corps.get("fin") else debut + timedelta(hours=1)
        except ValueError:
            raise HTTPException(status_code=422, detail="« fin » invalide")
        if fin <= debut:
            raise HTTPException(status_code=422, detail="« fin » doit suivre « debut »")
        fuseau = str(corps.get("fuseau") or FUSEAU_DEFAUT)
        corps_google: Dict[str, Any] = {"summary": titre, "start": {"dateTime": debut.isoformat(), "timeZone": fuseau}, "end": {"dateTime": fin.isoformat(), "timeZone": fuseau}}
        if corps.get("lieu"):
            corps_google["location"] = str(corps["lieu"])[:200]
        if corps.get("description"):
            corps_google["description"] = str(corps["description"])[:1000]
        if corps.get("rappel_minutes") is not None:
            corps_google["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": max(0, min(int(corps["rappel_minutes"]), 40320))}]}
        r = await _api(cle, "POST", "/calendars/primary/events", json=corps_google)
        return {"ok": True, "evenement": _evenement_public(r.json())}

    @api.post("/webhook/agenda/supprimer", tags=["Agenda — passerelle"])
    async def supprimer(request: Request):
        plateforme, utilisateur, corps = await _appelant(request)
        ident = str(corps.get("id") or "").strip()
        if not ident:
            raise HTTPException(status_code=422, detail="« id » obligatoire")
        await _api(cle_liaison(plateforme, utilisateur), "DELETE", f"/calendars/primary/events/{ident}")
        return {"ok": True}

    # ------------------------------------------------------------------ administrateur : aucun contenu d'agenda ; les demandes d'accès (compte Google indiqué par l'utilisateur) à accepter ou refuser
    def _admin(user: dict) -> None:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    @api.get("/admin/agenda-passerelle/etat", tags=["Agenda — passerelle"])
    async def etat_admin(request: Request, user: dict = Depends(get_current_user)):
        _admin(user)
        par: Dict[str, int] = {}
        async for d in db.settings.find({"_id": {"$regex": "^" + PREFIXE_LIAISON}}, {"plateforme": 1}):
            par[d.get("plateforme") or "?"] = par.get(d.get("plateforme") or "?", 0) + 1
        s_ = await db.settings.find_one({"_id": "global"}) or {}
        cfg = await _config()
        return {"adresse_retour": _adresse_retour(request), "autorisations": SCOPES.split(), "google_configure": bool(s_.get("google_client_id") and s_.get("google_client_secret")),
                "liaisons_par_plateforme": par, "total": sum(par.values()), "approbation": cfg["approbation"],
                "demandes": sorted(({k: d.get(k) for k in ("id", "plateforme", "utilisateur", "nom", "gmail", "etat", "cree_le", "decide_le")} for d in cfg["demandes"]),
                                   key=lambda d: d["cree_le"] or "", reverse=True)}

    @api.post("/admin/agenda-passerelle/demandes/{ident}", tags=["Agenda — passerelle"])
    async def decider(ident: str, request: Request, user: dict = Depends(get_current_user)):
        _admin(user)
        corps = await request.json()
        decision = str((corps or {}).get("decision") or "")
        if decision not in ("accepte", "refuse"):
            raise HTTPException(status_code=422, detail="decision : accepte ou refuse")
        cfg = await _config()
        d = next((x for x in cfg["demandes"] if x["id"] == ident), None)
        if not d:
            raise HTTPException(status_code=404, detail="Demande introuvable")
        d["etat"], d["decide_le"] = decision, maintenant().isoformat()
        await _ecrire_config(cfg)
        return {"id": ident, "etat": decision}

    @api.put("/admin/agenda-passerelle/approbation", tags=["Agenda — passerelle"])
    async def regler_approbation(request: Request, user: dict = Depends(get_current_user)):
        _admin(user)
        corps = await request.json()
        cfg = await _config()
        cfg["approbation"] = bool((corps or {}).get("actif"))
        await _ecrire_config(cfg)
        return {"approbation": cfg["approbation"]}
