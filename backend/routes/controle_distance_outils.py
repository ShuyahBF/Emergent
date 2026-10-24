"""Lot 135 — Contrôle à distance : outils PURS (sans base ni réseau) des extensions demandées le 12/10/2026.

Pour un développeur WinDev : ce fichier regroupe les « procédures globales » du contrôle à distance, testées seules
(tests/test_controle_distance_lot135.py). Les routes qui les utilisent sont dans routes/controle_distance.py.

Contenu :
  - numéro de prise en main « CD-AAAA-NNNNN » (compteur annuel) ;
  - délais mesurés d'une session (accord, connexion, durée) et résumé lisible pour le journal d'activités ;
  - chiffrement des identifiants Windows mémorisés par poste (Fernet dérivé de JWT_SECRET, étiquette propre) ;
  - lien signé et de courte durée pour relire la vidéo d'une session dans le navigateur (balise <video>) ;
  - réglages de la rubrique (valeurs par défaut et bornes) ;
  - lot 281 : durée de la session — fin automatique à 4 h, mais JAMAIS en plein transfert de fichier, et prolongation à la demande.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

# ---------------------------------------------------------------------------------------------------------------------
# Numérotation des prises en main
# ---------------------------------------------------------------------------------------------------------------------
PREFIXE_NUMERO = "CD"


def numero_session(annee: int, sequence: int) -> str:
    """« CD-2026-00042 » : préfixe, année, compteur annuel sur 5 chiffres (au-delà, le nombre s'allonge)."""
    return f"{PREFIXE_NUMERO}-{int(annee)}-{max(1, int(sequence)):05d}"


def compteur_annuel(annee: int) -> str:
    """Identifiant du compteur (collection `counters`) : un compteur par année."""
    return f"controle_distance_{int(annee)}"


# ---------------------------------------------------------------------------------------------------------------------
# Délais mesurés (item 8 : temps de connexion rapportés après chaque session)
# ---------------------------------------------------------------------------------------------------------------------
def _date(v: Any) -> Optional[datetime]:
    """Date ISO → datetime ; None si absente ou illisible."""
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def ecart_s(debut: Any, fin: Any) -> Optional[int]:
    """Secondes entre deux dates ISO (jamais négatif) ; None si l'une manque."""
    d, f = _date(debut), _date(fin)
    if not d or not f:
        return None
    return max(0, int(round((f - d).total_seconds())))


def delais_session(session: Dict[str, Any], fin_iso: Optional[str] = None) -> Dict[str, Optional[int]]:
    """Délais d'une session : accord de l'utilisateur, ouverture des connexions, durée de la prise en main."""
    fin = fin_iso or session.get("fin_le")
    return {
        "delai_accord_s": ecart_s(session.get("cree_le"), session.get("accepte_le")),
        "delai_connexion_s": ecart_s(session.get("accepte_le"), session.get("debut_le")),
        "duree_s": ecart_s(session.get("debut_le") or session.get("accepte_le") or session.get("cree_le"), fin),
    }


# Mesures envoyées par la visionneuse à la fin de la session : nom → (minimum, maximum) acceptés
BORNES_MESURES = {
    "premiere_image_ms": (0, 600_000),
    "ips_moyen": (0, 120),
    "latence_moy_ms": (0, 120_000),
    "latence_max_ms": (0, 120_000),
    "debit_moy_ko": (0, 1_000_000),
    "octets_recus": (0, 1 << 42),
    "duree_affichee_s": (0, 86_400),
}
MOTEURS_CAPTURE = ("dxgi", "gdi")


def nettoyer_mesures(brut: Dict[str, Any]) -> Dict[str, Any]:
    """Garde seulement les mesures connues, bornées (une valeur absurde est ignorée, jamais enregistrée)."""
    propre: Dict[str, Any] = {}
    for nom, (mini, maxi) in BORNES_MESURES.items():
        v = brut.get(nom)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if mini <= v <= maxi:
            propre[nom] = round(float(v), 1) if isinstance(v, float) else int(v)
    capture = str(brut.get("capture") or "").lower()
    if capture in MOTEURS_CAPTURE:
        propre["capture"] = capture
    echelle = brut.get("echelle")
    if isinstance(echelle, int) and echelle in (25, 50, 75, 100):
        propre["echelle"] = echelle
    return propre


def duree_lisible(s: Optional[int]) -> str:
    """« 45 s », « 12 min », « 1 h 05 »."""
    if s is None:
        return "—"
    if s < 60:
        return f"{s} s"
    m = round(s / 60)
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d}"


def resume_mesures(session: Dict[str, Any]) -> str:
    """Une ligne pour le journal d'activités : « CD-2026-00042 · accord 8 s · connexion 2 s · durée 12 min · … »."""
    d = delais_session(session)
    m = session.get("mesures") or {}
    morceaux = [session.get("numero") or "Prise en main",
                f"accord {duree_lisible(d['delai_accord_s'])}",
                f"connexion {duree_lisible(d['delai_connexion_s'])}",
                f"durée {duree_lisible(d['duree_s'])}"]
    if m.get("premiere_image_ms") is not None:
        morceaux.append(f"1re image {m['premiere_image_ms'] / 1000:.1f} s".replace(".", ","))
    if m.get("latence_moy_ms") is not None:
        morceaux.append(f"latence {int(m['latence_moy_ms'])} ms")
    if m.get("ips_moyen") is not None:
        morceaux.append(f"{m['ips_moyen']} img/s".replace(".", ","))
    if m.get("capture"):
        morceaux.append(f"capture {m['capture'].upper()}")
    return " · ".join(morceaux)


# ---------------------------------------------------------------------------------------------------------------------
# Identifiants Windows mémorisés (item 7) — jamais renvoyés au navigateur
# ---------------------------------------------------------------------------------------------------------------------
MAX_UTILISATEUR = 120
MAX_MOT_DE_PASSE = 256


def _fernet() -> Fernet:
    """Clé stable dérivée de JWT_SECRET avec une étiquette propre à cet usage (aucune variable d'environnement de plus)."""
    secret = os.environ.get("JWT_SECRET") or "fallback-insecure-jwt"
    empreinte = hashlib.sha256(f"sawali-controle-distance-identifiants::{secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(empreinte))


def chiffrer(clair: Optional[str]) -> Optional[str]:
    """Texte chiffré (Fernet), ou None pour une valeur vide."""
    if not clair:
        return None
    return _fernet().encrypt(clair.encode("utf-8")).decode("ascii")


def dechiffrer(chiffre: Optional[str]) -> Optional[str]:
    """Texte clair, ou None si absent ou illisible (JWT_SECRET modifié : à saisir de nouveau)."""
    if not chiffre:
        return None
    try:
        return _fernet().decrypt(chiffre.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return None


def identifiants_publics(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ce que la page peut voir : utilisateur, domaine, dates — JAMAIS le mot de passe (ni chiffré)."""
    doc = doc or {}
    return {
        "enregistre": bool(doc.get("mdp_chiffre")),
        "utilisateur": doc.get("utilisateur") or "",
        "domaine": doc.get("domaine") or "",
        "saisie_auto": bool(doc.get("saisie_auto", True)),
        "maj_le": doc.get("maj_le"),
        "maj_par": doc.get("maj_par"),
    }


def trame_identifiants(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Message envoyé AU POSTE seulement (par le serveur) pour saisir l'identifiant à l'écran de connexion."""
    mdp = dechiffrer(doc.get("mdp_chiffre"))
    if not mdp:
        return None
    utilisateur = doc.get("utilisateur") or ""
    if doc.get("domaine") and utilisateur and "\\" not in utilisateur and "@" not in utilisateur:
        utilisateur = f"{doc['domaine']}\\{utilisateur}"
    return {"type": "saisir_identifiants", "utilisateur": utilisateur, "mot_de_passe": mdp}


# ---------------------------------------------------------------------------------------------------------------------
# Vidéo de la session (item 4) : lien signé de courte durée (la balise <video> n'envoie pas l'en-tête Authorization)
# ---------------------------------------------------------------------------------------------------------------------
DUREE_LIEN_VIDEO_S = 15 * 60
TAILLE_MAX_PARTIE_VIDEO = 25 * 1024 * 1024     # une partie (≈ 30 s d'enregistrement) pèse bien moins


def _cle_video() -> bytes:
    secret = os.environ.get("JWT_SECRET") or "fallback-insecure-jwt"
    return hashlib.sha256(f"sawali-controle-distance-video::{secret}".encode()).digest()


def signer_video(sid: str, expire: int) -> str:
    """Signature HMAC-SHA256 (session + date d'expiration)."""
    return hmac.new(_cle_video(), f"{sid}|{int(expire)}".encode(), hashlib.sha256).hexdigest()


def lien_video(sid: str, maintenant: Optional[float] = None) -> Dict[str, Any]:
    """Paramètres du lien de lecture : expiration + signature."""
    expire = int((maintenant if maintenant is not None else time.time()) + DUREE_LIEN_VIDEO_S)
    return {"exp": expire, "sig": signer_video(sid, expire)}


def lien_video_valide(sid: str, exp: Any, sig: Any, maintenant: Optional[float] = None) -> bool:
    """Vrai si la signature est bonne et le lien pas encore expiré."""
    try:
        expire = int(exp)
    except (TypeError, ValueError):
        return False
    if expire < (maintenant if maintenant is not None else time.time()):
        return False
    return hmac.compare_digest(signer_video(sid, expire), str(sig or ""))


def chemin_partie_video(sid: str, index: int) -> str:
    """Chemin de stockage d'une partie de la vidéo (les parties se lisent bout à bout, dans l'ordre)."""
    return f"controle_distance/videos/{sid}/{int(index):06d}.webm"


# ---------------------------------------------------------------------------------------------------------------------
# Réglages de la rubrique
# ---------------------------------------------------------------------------------------------------------------------
REGLAGES_DEFAUT = {
    "enregistrement_video": True,     # vidéo de chaque session dans le journal
    "video_ips": 5,                   # images par seconde de la vidéo (1 à 15)
    "conservation_jours": 90,         # durée de conservation affichée (purge à prévoir)
    "ticket_automatique": True,       # ticket du client ouvert à chaque prise en main
}


def reglages_valides(brut: Dict[str, Any]) -> Dict[str, Any]:
    """Réglages complétés par les valeurs par défaut et bornés."""
    r = dict(REGLAGES_DEFAUT)
    for cle in ("enregistrement_video", "ticket_automatique"):
        if isinstance(brut.get(cle), bool):
            r[cle] = brut[cle]
    if isinstance(brut.get("video_ips"), int) and not isinstance(brut.get("video_ips"), bool):
        r["video_ips"] = min(15, max(1, brut["video_ips"]))
    if isinstance(brut.get("conservation_jours"), int) and not isinstance(brut.get("conservation_jours"), bool):
        r["conservation_jours"] = min(3650, max(1, brut["conservation_jours"]))
    return r


# ---------------------------------------------------------------------------------------------------------------------
# Lot 281 — durée d'une session : 4 h, prolongeable, jamais coupée en plein transfert de fichier
# ---------------------------------------------------------------------------------------------------------------------
DUREE_MAX_S = 4 * 3600             # durée normale d'une session
DUREE_PROLONGATION_S = 2 * 3600    # chaque « Prolonger » ajoute 2 heures
DUREE_ABSOLUE_S = 12 * 3600        # plafond de sécurité : jamais plus de 12 h au total
FENETRE_TRANSFERT_S = 90           # un transfert est « en cours » si une trame de fichier est passée il y a moins de 90 s


def plafond_session(debut: datetime) -> datetime:
    """Heure au-delà de laquelle la session est fermée quoi qu'il arrive (début + 12 h)."""
    return debut + timedelta(seconds=DUREE_ABSOLUE_S)


def session_expiree(debut: datetime, maintenant: datetime, limite_fin: datetime, dernier_fichier: Optional[datetime]) -> bool:
    """Vrai si la session doit être fermée : la limite est dépassée ET aucun fichier n'est en cours de transfert
    (ou le plafond de 12 h est dépassé)."""
    if maintenant <= limite_fin:
        return False
    if maintenant > plafond_session(debut):
        return True
    return not (dernier_fichier is not None and (maintenant - dernier_fichier).total_seconds() <= FENETRE_TRANSFERT_S)


def prolonger_limite(debut: datetime, maintenant: datetime, limite_fin: datetime) -> datetime:
    """Nouvelle limite après « Prolonger » : 2 h de plus que la limite actuelle (ou que maintenant si elle est dépassée),
    sans dépasser le plafond de 12 h."""
    return min(max(limite_fin, maintenant) + timedelta(seconds=DUREE_PROLONGATION_S), plafond_session(debut))


def motif_deconnexion(role: str, code: Any = None) -> str:
    """Motif inscrit au journal quand un bout se déconnecte : « déconnexion du poste (code 1006) ». Le code de fermeture du
    WebSocket aide à comprendre une coupure (1006 = liaison coupée sans fermeture propre ; 1001 = page fermée ; 1000 = normale)."""
    base = f"déconnexion du {role}"
    return f"{base} (code {code})" if isinstance(code, int) and code else base
