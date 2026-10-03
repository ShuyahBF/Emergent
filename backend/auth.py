"""Authentication: bcrypt password hashing, JWT tokens, OTP generation."""
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from db import db, serialize

JWT_SECRET = os.environ.get("JWT_SECRET", "fallback-insecure")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "12"))

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, role: str, sid: Optional[str] = None) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)).timestamp()),
    }
    # Lot 50 — identifiant de la session du compte (sessions_comptes.py : limite d'appareils,
    # fermeture depuis « Mon compte », contrôle serveur de l'inactivité).
    if sid:
        payload["sid"] = sid
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def create_session_token(user: dict, request=None, methode: Optional[str] = None) -> str:
    """Lot 50 — Connexion d'un compte : ouvre une session (au plus N appareils par compte,
    les plus anciennes sont fermées) puis émet le jeton qui porte son identifiant.
    Lot 55 — refusée si l'IP est bloquée pour ce compte ; connexion notée dans le journal des
    connexions (`methode` : code_email, code_whatsapp…)."""
    import connexions_ip
    import sessions_comptes
    await connexions_ip.refuser_si_bloquee(user, request, methode or "autre")
    ouverte = await sessions_comptes.ouvrir_session(user, request)
    await connexions_ip.noter(user, request, methode or "autre", connexions_ip.REUSSIE, sid=ouverte["sid"])
    return create_access_token(user["id"], user.get("role") or "client", sid=ouverte["sid"])


def decode_token(token: str) -> dict:
    return pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Token manquant")
    try:
        payload = decode_token(credentials.credentials)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expiré")
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if user is None:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    if user.get("account_status") != "active":
        raise HTTPException(status_code=403, detail="Compte désactivé")
    # Iter35h — demo expiration check. We auto-disable the account so the
    # user can't access anything beyond the expiry; a side-effect emits an
    # entry on `db.demo_expiry_events` for the admin to review.
    if user.get("role") == "demo" and user.get("demo_expires_at"):
        try:
            exp_str = str(user["demo_expires_at"]).replace("Z", "+00:00")
            exp_dt = datetime.fromisoformat(exp_str)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp_dt:
                already = await db.demo_expiry_events.find_one(
                    {"user_id": user["id"], "resolved": {"$ne": True}},
                    {"_id": 0, "id": 1},
                )
                if not already:
                    await db.demo_expiry_events.insert_one({
                        "id": str(uuid.uuid4()),
                        "user_id": user["id"],
                        "user_email": user.get("email"),
                        "user_full_name": user.get("full_name"),
                        "expired_at": exp_dt.isoformat(),
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                        "resolved": False,
                    })
                # Mark the account as expired (idempotent)
                await db.users.update_one(
                    {"id": user["id"]},
                    {"$set": {"account_status": "expired",
                              "updated_at": datetime.now(timezone.utc).isoformat()}},
                )
                raise HTTPException(
                    status_code=403,
                    detail="Compte de démonstration expiré. Contactez l'administrateur.",
                )
        except HTTPException:
            raise
        except Exception:
            pass
    # Lot 50 — maintenance de la plateforme, session du compte (limite d'appareils, inactivité),
    # abonnement du client (coupure après la grâce) : controle_acces.py.
    from controle_acces import controler_requete
    await controler_requete(user, payload, request)
    return user


async def get_current_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé à l'administrateur")
    return user


async def get_current_admin_or_moderator(user: dict = Depends(get_current_user)) -> dict:
    """Iter43-fix22 — Accès pour les rôles admin / moderator / superviseur."""
    # Lot 25 — Le formulaire Clients enregistre « moderateur » (orthographe
    # française) : on accepte les deux orthographes du rôle modérateur.
    if user.get("role") not in {"admin", "moderator", "moderateur", "superviseur"}:
        raise HTTPException(status_code=403, detail="Accès réservé aux modérateurs, superviseurs et administrateurs")
    return user


def est_super_admin(user: dict) -> bool:
    """Lot 50 — Super-admin SAWALI (SUPER_ADMIN_EMAIL), même règle que server._is_super_admin."""
    email = (user.get("email") or "").strip().lower()
    attendu = (os.environ.get("SUPER_ADMIN_EMAIL") or "admin@sawalismartsystems.com").strip().lower()
    return bool(email) and email == attendu


async def get_super_admin(user: dict = Depends(get_current_admin)) -> dict:
    """Lot 50 — Réservé au super-admin SAWALI : maintenance de la plateforme, abonnements et
    sessions de tous les clients (un Admin de client ne voit pas les autres clients)."""
    if not est_super_admin(user):
        raise HTTPException(status_code=403, detail="Réservé au super-administrateur SAWALI")
    return user
