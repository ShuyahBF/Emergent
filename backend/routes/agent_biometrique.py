"""Lot 370 — Connexion par l'AGENT BIOMÉTRIQUE LOOIS (lecteur d'empreintes d'un poste partagé).

POURQUOI EN PLUS DES PASSKEYS (lot 369)
   Les passkeys reposent sur Windows Hello, lié au COMPTE WINDOWS : sur un poste partagé (accueil, laboratoire) où tout le monde
   utilise le même compte Windows, l'empreinte de l'un peut déverrouiller la passkey d'un autre. L'agent biométrique Loois
   (programme LooisBioAgent du dépôt Loois) reconnaît, lui, LA PERSONNE parmi toutes celles enrôlées dans Loois (1 parmi N).

COMMENT ÇA MARCHE (rien de l'empreinte ne circule)
   1. La page de connexion demande un DÉFI à usage unique à SAWALI (POST /auth/agent-bio/defi).
   2. Elle le remet à l'agent du poste (http://127.0.0.1:47821/v1/identifier) ; l'agent fait poser le doigt, reconnaît la personne
      et répond par une ATTESTATION SIGNÉE (ECDSA P-256) : « telle personne, pour tel site, en réponse à tel défi, jusqu'à telle heure ».
   3. La page envoie l'attestation à SAWALI (POST /auth/agent-bio/connexion) qui vérifie : signature avec la clé publique de
      l'agent (enregistrée par l'administrateur), défi connu et non utilisé, site = adresse de la page, durée, puis retrouve le
      compte lié à cette personne et ouvre la session comme une connexion normale.

ROUTES (sous /api)
   GET    /auth/agent-bio/config          — public : la connexion par agent est-elle activée ?
   POST   /auth/agent-bio/defi            — public : défi à usage unique (2 min)
   POST   /auth/agent-bio/connexion       — public : attestation → mêmes contrôles qu'une connexion → jeton
   GET    /admin/agent-bio                — administrateur : état, agents enregistrés, comptes liés
   PUT    /admin/agent-bio/config         — administrateur : activer / désactiver
   POST   /admin/agent-bio/agents         — administrateur : enregistrer la clé publique d'un agent (poste)
   DELETE /admin/agent-bio/agents/{id}    — administrateur : retirer un agent
   PUT    /admin/agent-bio/user/{user_id} — administrateur : lier un compte à une personne enrôlée dans Loois
   POST   /admin/agent-bio/lier           — administrateur : idem, le compte étant désigné par son e-mail
   DELETE /admin/agent-bio/user/{user_id} — administrateur : délier

DÉCISIONS
   - Désactivée par défaut : le déploiement ne change RIEN tant que l'administrateur ne l'active pas. Mot de passe toujours possible.
   - AUCUNE nouvelle collection (cluster MongoDB plein) : clés publiques des agents dans `settings` (`agent_bio_agents`), lien
     compte ↔ personne dans la fiche `users` (`agent_bio`), défis dans `otps` (type « agent_bio_challenge », usage unique, 2 min).
   - Seule une attestation signée par un agent ENREGISTRÉ est acceptée (un faux agent, ou une page qui invente un nom, est refusé).
   - Mêmes refus que les autres connexions : compte inactif, maintenance, client suspendu ou archivé, IP bloquée ; chaque refus
     est journalisé (méthode « empreinte », Historique des connexions).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

import connexions_ip  # journal des connexions (méthode « empreinte »), IP bloquée
from ip_client import ip_reelle
from models import AuthTokenResponse
from routes.auth import refuser_si_compte_inactif

logger = logging.getLogger("sawali.agent_bio")

TYPE_DEFI = "agent_bio_challenge"      # type des documents de la collection `otps` qui portent un défi
DUREE_DEFI_S = 120                     # un défi vaut 2 minutes, une seule fois
MAX_AGENTS = 20                        # agents (postes) enregistrés au plus
LIMITE_DEMANDES = 30                   # demandes publiques par adresse IP et par minute
FENETRE_LIMITE_S = 60
TOLERANCE_HORLOGE_S = 30               # écart d'horloge toléré entre le poste et le serveur
_PERSONNE_VALIDE = re.compile(r"^[^\s<>\"'\\]{1,64}$")


class AgentConnexion(BaseModel):
    """Corps de /auth/agent-bio/connexion : le défi reçu de SAWALI et l'attestation renvoyée par l'agent."""
    challenge_id: str
    attestation: str = Field(max_length=4000)


class AgentConfig(BaseModel):
    enabled: bool


class AgentEnregistrement(BaseModel):
    """Corps de POST /admin/agent-bio/agents : nom lisible du poste et clé publique copiée depuis les Réglages de l'agent."""
    nom: str = Field(min_length=1, max_length=60)
    cle_publique: str = Field(min_length=20, max_length=2000)


class LienParEmail(BaseModel):
    """Corps de POST /admin/agent-bio/lier : compte désigné par son e-mail + nom de la personne enrôlée."""
    email: str = Field(min_length=3, max_length=200)
    personne: str = Field(min_length=1, max_length=64)


class LienPersonne(BaseModel):
    """Nom de la personne TEL QU'ENRÔLÉ dans Loois (login des empreintes)."""
    personne: str = Field(min_length=1, max_length=64)


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _b64u(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


# ---------------------------------------------------------------- logique pure (testée)

def cle_publique_depuis_texte(texte: str) -> tuple[bytes, str]:
    """Clé publique collée par l'administrateur (Base64 du format SubjectPublicKeyInfo) → (octets DER, identifiant d'agent).
    Refuse tout ce qui n'est pas une clé ECDSA P-256. L'identifiant = 16 premiers caractères hexadécimaux du SHA-256 de la clé :
    c'est celui que l'agent affiche et inscrit dans ses attestations."""
    try:
        brut = base64.b64decode(re.sub(r"\s+", "", texte), validate=True)
        cle = serialization.load_der_public_key(brut)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="Clé publique illisible : copiez-la de nouveau depuis les Réglages de l'agent") from exc
    if not isinstance(cle, ec.EllipticCurvePublicKey) or cle.curve.name != "secp256r1":
        raise HTTPException(status_code=422, detail="Clé publique non acceptée (ECDSA P-256 attendue)")
    return brut, hashlib.sha256(brut).hexdigest()[:16]


def lire_attestation_sans_verifier(jeton: str) -> Optional[dict]:
    """Contenu d'une attestation SANS vérifier la signature : sert uniquement à savoir quel agent l'a émise (pour choisir sa clé)."""
    try:
        charge, _ = jeton.split(".")
        contenu = json.loads(_b64u(charge))
        return contenu if isinstance(contenu, dict) else None
    except Exception:  # noqa: BLE001
        return None


def verifier_signature(jeton: str, cle_der: bytes) -> Optional[dict]:
    """Contenu de l'attestation si la signature ECDSA P-256 / SHA-256 est bonne, sinon None.
    La signature de l'agent (.NET) est au format brut r‖s (64 octets), reconvertie en DER pour la bibliothèque."""
    try:
        charge_b64, signature_b64 = jeton.split(".")
        charge, signature = _b64u(charge_b64), _b64u(signature_b64)
        if len(signature) != 64:
            return None
        cle = serialization.load_der_public_key(cle_der)
        cle.verify(encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")), charge, ec.ECDSA(hashes.SHA256()))
        contenu = json.loads(charge)
        return contenu if isinstance(contenu, dict) else None
    except (InvalidSignature, ValueError, TypeError):
        return None
    except Exception:  # noqa: BLE001
        return None


def valider_attestation(att: dict, site: str, defi: str, maintenant_s: float) -> str:
    """Contrôles faits en plus de la signature. Renvoie « » si tout va bien, sinon la raison du refus."""
    if att.get("v") != 1:
        return "Version d'attestation inconnue"
    if str(att.get("site", "")).lower() != site.lower():
        return "Attestation émise pour un autre site"
    if att.get("defi") != defi:
        return "Défi différent : attestation rejouée ou d'une autre demande"
    try:
        emis, expire = float(att["emis"]), float(att["expire"])
    except (KeyError, TypeError, ValueError):
        return "Dates absentes"
    if maintenant_s > expire:
        return "Attestation expirée"
    if emis > maintenant_s + TOLERANCE_HORLOGE_S:
        return "Attestation datée du futur (horloges désaccordées)"
    if not isinstance(att.get("personne"), str) or not att["personne"].strip():
        return "Personne absente"
    return ""


def origine_page(entete_origine: str) -> str:
    """Adresse exacte de la page (https://hôte[:port]) ; HTTPS exigé sauf localhost. C'est la valeur que l'agent a inscrite comme « site »."""
    p = urlparse((entete_origine or "").strip().rstrip("/"))
    if p.scheme not in ("https", "http") or not p.hostname:
        raise HTTPException(status_code=400, detail="Adresse de la page absente ou invalide")
    if p.scheme == "http" and p.hostname.lower() not in ("localhost", "127.0.0.1"):
        raise HTTPException(status_code=400, detail="La connexion par l'agent exige une page en HTTPS")
    return f"{p.scheme}://{p.netloc}".lower()


def cle_personne(personne: str) -> str:
    """Forme comparable du nom d'une personne (sans tenir compte de la casse ni des espaces autour)."""
    return personne.strip().lower()


def attach_agent_bio_routes(api: APIRouter | FastAPI, *, db, helpers: Dict[str, Any]) -> None:
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
    demandes: Dict[str, List[float]] = {}

    def limiter(request: Request) -> None:
        """Refuse (429) au-delà de LIMITE_DEMANDES par minute pour une même adresse IP (les routes publiques écrivent en base)."""
        ip = ip_reelle(request) or "?"
        maintenant = time.monotonic()
        recentes = [t for t in demandes.get(ip, []) if maintenant - t < FENETRE_LIMITE_S]
        if len(recentes) >= LIMITE_DEMANDES:
            demandes[ip] = recentes
            raise HTTPException(status_code=429, detail="Trop de tentatives : patientez une minute")
        recentes.append(maintenant)
        demandes[ip] = recentes
        if len(demandes) > 5000:
            for cle in [k for k, v in demandes.items() if not v or maintenant - v[-1] >= FENETRE_LIMITE_S]:
                demandes.pop(cle, None)

    async def reglages() -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}, {"agent_bio_enabled": 1, "agent_bio_agents": 1}) or {}
        return {"enabled": bool(s.get("agent_bio_enabled")), "agents": s.get("agent_bio_agents") or []}

    async def exiger_active() -> Dict[str, Any]:
        r = await reglages()
        if not r["enabled"]:
            raise HTTPException(status_code=403, detail="La connexion par l'agent biométrique n'est pas activée")
        return r

    async def assurer_index() -> None:
        """Index sur la personne liée : la connexion retrouve le compte sans parcourir `users` (règle 7)."""
        if not etat["index"]:
            await db.users.create_index("agent_bio.cle", sparse=True, name="ix_users_agent_bio_cle")
            etat["index"] = True

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

    @api.get("/auth/agent-bio/config", tags=["Agent biométrique"])
    async def agent_config():
        """La page de connexion n'affiche le bouton « Empreinte (lecteur du poste) » que si c'est activé ET qu'un agent est enregistré."""
        r = await reglages()
        return {"enabled": r["enabled"] and len(r["agents"]) > 0}

    @api.post("/auth/agent-bio/defi", tags=["Agent biométrique"])
    async def agent_defi(request: Request):
        limiter(request)
        await exiger_active()
        origine_page(request.headers.get("origin", ""))
        maintenant = _maintenant()
        await db.otps.delete_many({"type": TYPE_DEFI, "expires_at": {"$lt": _iso(maintenant)}})
        defi = secrets.token_urlsafe(24)                    # 32 caractères sûrs, acceptés tels quels par l'agent (16 à 128)
        identifiant = nouvel_id()
        await db.otps.insert_one({"id": identifiant, "type": TYPE_DEFI, "used": False, "challenge": defi,
                                  "created_at": _iso(maintenant), "expires_at": _iso(maintenant + timedelta(seconds=DUREE_DEFI_S))})
        return {"challenge_id": identifiant, "defi": defi, "expire_dans": DUREE_DEFI_S}

    @api.post("/auth/agent-bio/connexion", response_model=AuthTokenResponse, tags=["Agent biométrique"])
    async def agent_connexion(payload: AgentConnexion, request: Request):
        limiter(request)
        r = await exiger_active()
        site = origine_page(request.headers.get("origin", ""))
        # Défi : usage unique, atomique ; consommé même si la suite échoue (une attestation ne se retente pas)
        doc = await db.otps.find_one_and_update({"id": payload.challenge_id, "type": TYPE_DEFI, "used": False}, {"$set": {"used": True}})
        if not doc or doc.get("expires_at", "") < _iso(_maintenant()):
            raise HTTPException(status_code=400, detail="Défi expiré ou invalide : recommencez")
        refus = HTTPException(status_code=401, detail="Empreinte non vérifiée : réessayez ou utilisez votre mot de passe")
        entete = lire_attestation_sans_verifier(payload.attestation)
        agent = next((a for a in r["agents"] if entete and a.get("id") == entete.get("agent")), None)
        if not agent:
            logger.info("[agent_bio] agent inconnu")
            raise refus
        att = verifier_signature(payload.attestation, base64.b64decode(agent["cle_publique"]))
        if att is None or valider_attestation(att, site, doc["challenge"], time.time()):
            logger.info("[agent_bio] attestation refusée : %s", "signature" if att is None else valider_attestation(att, site, doc["challenge"], time.time()))
            raise refus
        await assurer_index()
        user = await db.users.find_one({"agent_bio.cle": cle_personne(att["personne"])})
        if not user:
            raise HTTPException(status_code=401, detail="Cette personne n'est liée à aucun compte SAWALI : connectez-vous avec votre mot de passe")
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
        await db.users.update_one({"id": user["id"]}, {"$set": {"last_login": maintenant, "agent_bio.dernier_usage": maintenant, "agent_bio.agent": agent["id"]}})
        user.pop("password_hash", None)
        user.pop("_id", None)
        jeton = await create_session_token(user, request, methode=connexions_ip.EMPREINTE)
        if emit_login_event is not None:
            try:
                asyncio.create_task(emit_login_event(user, request))
            except Exception:  # noqa: BLE001
                pass
        return AuthTokenResponse(access_token=jeton, user=await profil_public(user))

    # ---------------------------------------------------------------- administrateur

    def exiger_admin(user: dict) -> None:
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    @api.get("/admin/agent-bio", tags=["Agent biométrique"])
    async def admin_agent_bio(user: dict = Depends(get_current_user)):
        """État, agents enregistrés (jamais leur clé complète) et comptes liés à une personne enrôlée."""
        exiger_admin(user)
        r = await reglages()
        comptes: List[dict] = []
        async for u in db.users.find({"agent_bio.cle": {"$exists": True}}, {"_id": 0, "id": 1, "email": 1, "full_name": 1, "role": 1, "agent_bio": 1}).limit(1000):
            comptes.append({"user_id": u["id"], "email": u.get("email"), "nom": u.get("full_name"), "role": u.get("role"),
                            "personne": u["agent_bio"].get("personne"), "dernier_usage": u["agent_bio"].get("dernier_usage")})
        return {"enabled": r["enabled"], "max_agents": MAX_AGENTS,
                "agents": [{"id": a["id"], "nom": a.get("nom"), "cree_le": a.get("cree_le")} for a in r["agents"]], "comptes": comptes}

    @api.put("/admin/agent-bio/config", tags=["Agent biométrique"])
    async def admin_agent_config(payload: AgentConfig, user: dict = Depends(get_current_user)):
        exiger_admin(user)
        await db.settings.update_one({"_id": "global"}, {"$set": {"agent_bio_enabled": payload.enabled}}, upsert=True)
        logger.info("[agent_bio] réglage : activée=%s par %s", payload.enabled, user.get("id"))
        return {"ok": True, "enabled": payload.enabled}

    @api.post("/admin/agent-bio/agents", tags=["Agent biométrique"])
    async def admin_agent_ajouter(payload: AgentEnregistrement, user: dict = Depends(get_current_user)):
        exiger_admin(user)
        der, identifiant = cle_publique_depuis_texte(payload.cle_publique)
        entree = {"id": identifiant, "nom": re.sub(r"\s+", " ", payload.nom).strip(), "cle_publique": base64.b64encode(der).decode(), "cree_le": _iso(_maintenant())}
        # Un seul enregistrement par clé, et au plus MAX_AGENTS : vérifié dans la requête elle-même
        res = await db.settings.update_one(
            {"_id": "global", "agent_bio_agents.id": {"$ne": identifiant}, f"agent_bio_agents.{MAX_AGENTS - 1}": {"$exists": False}},
            {"$push": {"agent_bio_agents": entree}})
        if res.modified_count == 0:
            if not await db.settings.find_one({"_id": "global"}, {"_id": 1}):
                await db.settings.insert_one({"_id": "global", "agent_bio_agents": [entree]})
            else:
                existants = (await reglages())["agents"]
                if any(a.get("id") == identifiant for a in existants):
                    raise HTTPException(status_code=409, detail="Cet agent est déjà enregistré")
                raise HTTPException(status_code=400, detail=f"{MAX_AGENTS} agents au plus : retirez-en un d'abord")
        logger.info("[agent_bio] agent %s enregistré par %s", identifiant, user.get("id"))
        return {"ok": True, "id": identifiant}

    @api.delete("/admin/agent-bio/agents/{identifiant}", tags=["Agent biométrique"])
    async def admin_agent_retirer(identifiant: str, user: dict = Depends(get_current_user)):
        exiger_admin(user)
        res = await db.settings.update_one({"_id": "global"}, {"$pull": {"agent_bio_agents": {"id": identifiant}}})
        if res.modified_count == 0:
            raise HTTPException(status_code=404, detail="Agent introuvable")
        return {"ok": True}

    async def lier(user_id: str, personne_brute: str, par: dict) -> dict:
        """Lie un compte à une personne enrôlée dans Loois. Une personne ne peut être liée qu'à UN compte."""
        personne = re.sub(r"\s+", " ", personne_brute).strip()
        if not _PERSONNE_VALIDE.match(personne.replace(" ", "")):
            raise HTTPException(status_code=422, detail="Nom de personne invalide")
        cle = cle_personne(personne)
        await assurer_index()
        autre = await db.users.find_one({"agent_bio.cle": cle, "id": {"$ne": user_id}}, {"_id": 0, "email": 1})
        if autre:
            raise HTTPException(status_code=409, detail=f"Cette personne est déjà liée au compte {autre.get('email')}")
        res = await db.users.update_one({"id": user_id}, {"$set": {"agent_bio": {"personne": personne, "cle": cle}}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Compte introuvable")
        logger.info("[agent_bio] compte %s lié à la personne « %s » par %s", user_id, personne, par.get("id"))
        return {"ok": True, "personne": personne}

    @api.put("/admin/agent-bio/user/{user_id}", tags=["Agent biométrique"])
    async def admin_lier(user_id: str, payload: LienPersonne, user: dict = Depends(get_current_user)):
        exiger_admin(user)
        return await lier(user_id, payload.personne, user)

    @api.post("/admin/agent-bio/lier", tags=["Agent biométrique"])
    async def admin_lier_par_email(payload: LienParEmail, user: dict = Depends(get_current_user)):
        """Même chose, en désignant le compte par son adresse e-mail (plus simple à l'écran que l'identifiant interne)."""
        exiger_admin(user)
        courriel = payload.email.strip().lower()
        cible = await db.users.find_one({"email": courriel}, {"_id": 0, "id": 1}) or await db.users.find_one({"email": {"$regex": f"^{re.escape(courriel)}$", "$options": "i"}}, {"_id": 0, "id": 1})
        if not cible:
            raise HTTPException(status_code=404, detail="Aucun compte avec cette adresse e-mail")
        return await lier(cible["id"], payload.personne, user)

    @api.delete("/admin/agent-bio/user/{user_id}", tags=["Agent biométrique"])
    async def admin_delier(user_id: str, user: dict = Depends(get_current_user)):
        exiger_admin(user)
        res = await db.users.update_one({"id": user_id, "agent_bio": {"$exists": True}}, {"$unset": {"agent_bio": ""}})
        if res.modified_count == 0:
            raise HTTPException(status_code=404, detail="Ce compte n'est lié à aucune personne")
        return {"ok": True}


__all__ = ["attach_agent_bio_routes", "cle_publique_depuis_texte", "verifier_signature", "valider_attestation", "origine_page", "cle_personne"]
