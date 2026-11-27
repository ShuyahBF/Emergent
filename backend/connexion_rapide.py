# connexion_rapide.py — CONNEXION RAPIDE de « Loois Mobile » (lot 484) : logique pure + stockage, sans accès réseau (testable).
#
# Demande du propriétaire (27/11/2026) : en plus de l'identifiant et du mot de passe de la zone, l'utilisateur peut se connecter par
#   1. BIOMÉTRIE (empreinte / visage du téléphone) ; 2. COMPTE GOOGLE ; 3. CLÉ D'ACCÈS (passkey WebAuthn).
# Principe commun : l'utilisateur s'est d'abord connecté avec son mot de passe, puis « active » une méthode. SAWALI garde une LIAISON
# (appareil + zone + identifiant) ; la connexion rapide ne CRÉE JAMAIS de compte et ne remplace JAMAIS le contrôle de l'identifiant chez le
# client : à chaque connexion rapide, SAWALI relit l'utilisateur dans la base HFSQL du client (il doit toujours exister).
#   - biométrie : le téléphone garde un SECRET ALÉATOIRE dans le Keystore Android, déverrouillable seulement par l'empreinte ou le visage ;
#     SAWALI ne garde que l'EMPREINTE SHA-256 de ce secret. Le mot de passe n'est JAMAIS gardé sur le téléphone ni chez SAWALI.
#   - Google : SAWALI vérifie le jeton d'identité Google et garde l'identifiant Google (« sub ») de la liaison ; un compte Google = une liaison par appareil.
#   - clé d'accès : clé publique WebAuthn (jamais de clé privée côté serveur), vérification utilisateur exigée.
# Stockage : UNE fiche de `settings` (`_id = "android_rapide"`), aucune nouvelle collection (cluster MongoDB plein).
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ID_FICHE = "android_rapide"
METHODES = ("biometrie", "google", "cle")
MAX_LIAISONS = 600                         # au plus, tous appareils confondus
MAX_PAR_APPAREIL_LOGIN = 3                 # une par méthode
PACKAGE_ANDROID = "bf.sawali.loois.mobile"
# Empreinte SHA-256 du certificat de signature ShuyahStore (information PUBLIQUE, visible dans tout APK signé) : sert à l'origine WebAuthn Android
# et au fichier « assetlinks.json ». Autres empreintes possibles : variable LOOIS_APK_SHA256 (séparées par des virgules).
EMPREINTE_APK_DEFAUT = "A9:0A:62:E8:F5:0C:6B:AE:BE:81:BD:8D:FF:C4:A6:EF:DA:82:4F:84:E7:AA:E0:80:1C:BF:B1:23:AD:AF:C4:9C"
ISSUERS_GOOGLE = ("accounts.google.com", "https://accounts.google.com")


def maintenant_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------------------------------------------------------- biométrie
def nouveau_secret() -> str:
    """Secret aléatoire de 256 bits remis une seule fois au téléphone."""
    return secrets.token_urlsafe(32)


def empreinte(secret: str) -> str:
    return hashlib.sha256((secret or "").encode("utf-8")).hexdigest()


def secret_correspond(secret: str, empreinte_gardee: str) -> bool:
    """Comparaison en temps constant (aucun indice par la durée de la réponse)."""
    return bool(secret) and bool(empreinte_gardee) and hmac.compare_digest(empreinte(secret), empreinte_gardee)


# ---------------------------------------------------------------------------------------------------------------------------- Google
def masquer_email(email: str) -> str:
    """« awa.badini@gmail.com » → « a***@gmail.com » (affichage seulement)."""
    nom, _, domaine = (email or "").partition("@")
    return f"{nom[:1]}***@{domaine}" if nom and domaine else ""


def verifier_jeton_google(infos: Dict[str, Any], client_id: str, maintenant_ts: Optional[float] = None) -> Tuple[bool, str]:
    """Contrôle les informations renvoyées par Google pour un jeton d'identité : bon destinataire (notre client Google), bon émetteur, non expiré, e-mail vérifié.
    Renvoie (ok, raison_du_refus)."""
    if not client_id:
        return False, "La connexion par Google n'est pas configurée sur SAWALI."
    if str(infos.get("aud", "")) != client_id:
        return False, "Jeton Google destiné à une autre application."
    if str(infos.get("iss", "")) not in ISSUERS_GOOGLE:
        return False, "Émetteur du jeton Google inconnu."
    try:
        if float(infos.get("exp", 0)) < (maintenant_ts if maintenant_ts is not None else datetime.now(timezone.utc).timestamp()):
            return False, "Jeton Google expiré : recommencez."
    except (TypeError, ValueError):
        return False, "Jeton Google illisible."
    if not infos.get("sub"):
        return False, "Jeton Google sans identifiant."
    if str(infos.get("email_verified", "")).lower() not in ("true", "1"):
        return False, "Adresse Google non vérifiée."
    return True, ""


# ---------------------------------------------------------------------------------------------------------------------------- clé d'accès (WebAuthn sur Android)
def empreintes_apk(brut: str = "") -> List[str]:
    """Empreintes SHA-256 autorisées (format « AA:BB:… »), la nôtre toujours incluse."""
    liste = [EMPREINTE_APK_DEFAUT] + [x.strip().upper() for x in (brut or "").split(",") if x.strip()]
    vues: List[str] = []
    for e in liste:
        e = e.upper()
        if len(e.replace(":", "")) == 64 and e not in vues:
            vues.append(e)
    return vues


def origine_android(empreinte_hex: str) -> str:
    """Origine WebAuthn d'une application Android : « android:apk-key-hash:<SHA-256 du certificat, base64url sans remplissage> »."""
    octets = bytes.fromhex(empreinte_hex.replace(":", ""))
    return "android:apk-key-hash:" + base64.urlsafe_b64encode(octets).decode().rstrip("=")


def assetlinks(empreintes: List[str]) -> List[Dict[str, Any]]:
    """Contenu de /.well-known/assetlinks.json : autorise l'application à utiliser les clés d'accès du domaine de SAWALI."""
    return [{"relation": ["delegate_permission/common.get_login_creds", "delegate_permission/common.handle_all_urls"], "target": {"namespace": "android_app", "package_name": PACKAGE_ANDROID, "sha256_cert_fingerprints": empreintes}}]


# ---------------------------------------------------------------------------------------------------------------------------- liaisons
def nouvelle_liaison(appareil_id: str, client: str, zone: str, login: str, methode: str, **champs: Any) -> Dict[str, Any]:
    return {"id": secrets.token_hex(8), "appareil": appareil_id, "client": client, "zone": zone, "login": login.upper(), "methode": methode,
            "cree_le": maintenant_iso(), "dernier_usage": None, **champs}


def trouver(liaisons: Dict[str, Any], appareil_id: str, methode: str, login: str = "") -> List[Dict[str, Any]]:
    """Liaisons d'un appareil pour une méthode (et un identifiant si donné), de la plus récente à la plus ancienne."""
    sel = [l for l in liaisons.values() if l.get("appareil") == appareil_id and l.get("methode") == methode and (not login or l.get("login") == login.upper())]
    return sorted(sel, key=lambda l: l.get("cree_le") or "", reverse=True)


def vue(l: Dict[str, Any]) -> Dict[str, Any]:
    """Une liaison telle qu'affichée : jamais l'empreinte du secret, ni la clé publique."""
    return {"id": l["id"], "methode": l["methode"], "zone": l.get("zone", ""), "login": l.get("login", ""), "cree_le": l.get("cree_le"),
            "dernier_usage": l.get("dernier_usage"), "detail": l.get("email_masque") or l.get("nom") or ""}


async def lire(db) -> Dict[str, Any]:
    fiche = await db.settings.find_one({"_id": ID_FICHE}) or {}
    return fiche.get("liaisons") or {}


async def ecrire_liaison(db, liaison: Dict[str, Any]) -> None:
    await db.settings.update_one({"_id": ID_FICHE}, {"$set": {f"liaisons.{liaison['id']}": liaison}}, upsert=True)


async def retirer(db, ids: List[str]) -> None:
    if ids:
        await db.settings.update_one({"_id": ID_FICHE}, {"$unset": {f"liaisons.{i}": "" for i in ids}})
