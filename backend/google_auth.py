"""Connexion par compte Google — logique PURE (sans FastAPI), testée par tests/test_google.py.

Pour un développeur WinDev : on utilise le « flux à code » d'OpenID Connect, qui marche dans un navigateur ET dans l'application Android
(Google interdit la connexion dans une fenêtre intégrée : l'application ouvre donc le navigateur du téléphone).
  1. /auth/google/demarrer : le serveur envoie la personne chez Google, avec un « état » SIGNÉ (anti-falsification, valable 10 minutes) ;
  2. Google rappelle /auth/google/retour avec un code ; le serveur l'échange (avec le secret du client, qui reste sur le serveur) contre l'identité vérifiée ;
  3. le serveur donne au site un CODE À USAGE UNIQUE (2 minutes) ; le site l'échange contre la session (/auth/google/echange).
Sécurité (règle 21) : aucun compte n'est créé ni fusionné tout seul ; seul un compte DÉJÀ LIÉ (depuis son profil, connecté) peut ouvrir une session par Google.
Aucun secret n'est écrit ici : GOOGLE_CLIENT_ID et GOOGLE_CLIENT_SECRET viennent des variables d'environnement.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

URL_AUTORISATION = "https://accounts.google.com/o/oauth2/v2/auth"
URL_JETON = "https://oauth2.googleapis.com/token"
EMETTEURS = ("accounts.google.com", "https://accounts.google.com")
VALIDITE_ETAT_S = 600          # 10 minutes pour revenir de chez Google
VALIDITE_CODE_S = 120          # code à usage unique remis au site


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).decode().rstrip("=")


def _b64_inverse(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def signer_etat(cible: str, lier_user_id: str | None, secret: str, maintenant: float | None = None) -> str:
    """État signé (HMAC-SHA256) : cible « web » ou « app », compte à lier (ou None pour une connexion), échéance, nonce."""
    corps = {"c": "app" if cible == "app" else "web", "l": lier_user_id, "e": int((maintenant or time.time()) + VALIDITE_ETAT_S), "n": secrets.token_hex(8)}
    brut = _b64(json.dumps(corps, separators=(",", ":")).encode())
    return f"{brut}.{_b64(hmac.new(secret.encode(), brut.encode(), hashlib.sha256).digest())}"


def lire_etat(etat: str, secret: str, maintenant: float | None = None) -> dict | None:
    """Contrôle la signature ET l'échéance ; None si l'état est faux, modifié ou périmé."""
    try:
        brut, signature = str(etat).split(".", 1)
        attendue = _b64(hmac.new(secret.encode(), brut.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, attendue):
            return None
        corps = json.loads(_b64_inverse(brut))
        if int(corps.get("e", 0)) < (maintenant or time.time()):
            return None
        return corps
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def url_demarrage(client_id: str, redirect_uri: str, etat: str) -> str:
    """Adresse de Google où envoyer la personne (choix du compte à chaque fois : jamais de connexion silencieuse)."""
    return f"{URL_AUTORISATION}?" + urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
                                              "scope": "openid email profile", "state": etat, "prompt": "select_account", "access_type": "online"})


def identite_depuis_jeton(id_token: str, client_id: str, maintenant: float | None = None) -> dict | None:
    """Identité contenue dans l'id_token reçu DIRECTEMENT de Google (échange du code, en HTTPS, avec notre secret : la signature n'a pas à être revérifiée, OIDC §3.1.3.7).
    On contrôle quand même l'émetteur, le destinataire (notre client), l'échéance et que l'e-mail est VÉRIFIÉ par Google. Rend { sub, email, nom } ou None."""
    try:
        morceaux = str(id_token).split(".")
        corps = json.loads(_b64_inverse(morceaux[1]))
    except (ValueError, IndexError, json.JSONDecodeError):
        return None
    if corps.get("iss") not in EMETTEURS or corps.get("aud") != client_id:
        return None
    if int(corps.get("exp", 0)) < (maintenant or time.time()):
        return None
    sub = str(corps.get("sub") or "")
    email = str(corps.get("email") or "").strip().lower()
    verifie = corps.get("email_verified")
    if not sub or not email or verifie not in (True, "true"):
        return None
    return {"sub": sub, "email": email, "nom": str(corps.get("name") or "")[:80]}


def nouveau_code() -> tuple[str, str]:
    """Code à usage unique remis au site + son empreinte (seule l'empreinte est gardée en base)."""
    code = secrets.token_urlsafe(24)
    return code, empreinte_code(code)


def empreinte_code(code: str) -> str:
    return hashlib.sha256(str(code).encode()).hexdigest()
