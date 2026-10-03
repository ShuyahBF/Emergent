"""Sauvegarde de MIGRATION du site SAWALI vers MongoDB Atlas + Cloudflare R2.

Objectif : quitter l'hébergement Emergent sans rien perdre. Un bouton dans
AdminSettings (section « Migration vers Render ») lance, en arrière-plan :

  1. BASE DE DONNÉES — copie de TOUTES les collections (y compris « Produit »,
     « AAcheté »...) vers une base MongoDB Atlas cible, avec leurs index.
     Les types BSON (ObjectId, dates, binaires) sont conservés tels quels.
     En parallèle, chaque collection est archivée dans R2 en JSON étendu
     (EJSON canonique, une ligne par document, compressé .jsonl.gz).
  2. FICHIERS — copie vers R2 :
       - des objets du stockage Emergent (Object Storage) : chemins trouvés dans
         `stored_objects`, `files.storage_path`, et toute référence
         « /api/files/... » ou « storage_path » rencontrée dans la base
         (hors collections de journaux) ; une référence « /api/files/<id> »
         désigne un document de la collection `files` et est traduite en son
         `storage_path` ; « /api/files/ai/... » désigne un fichier du disque ;
       - des fichiers du disque local (UPLOAD_DIR, snapshots).
  3. SECRETS — les variables d'environnement du serveur (JWT_SECRET, clés
     Stripe, R2, Gemini...) sont regroupées dans un fichier CHIFFRÉ
     (AES-256-GCM, clé dérivée du mot de passe saisi, PBKDF2 200 000 tours),
     déposé dans R2 et téléchargeable. Les secrets rangés dans la base
     (settings global) voyagent déjà avec la copie de la base.
  4. RAPPORT — manifeste (manifest.json dans R2) : nombre de documents
     source / cible par collection, fichiers copiés / en échec, empreintes
     SHA-256. La progression est suivie dans la collection `migration_jobs`.

Les identifiants de la cible (URI Atlas, clés R2, mot de passe) ne sont
JAMAIS enregistrés en clair : ils restent en mémoire le temps de la tâche.
Sur demande, ils peuvent être mémorisés dans un COFFRE chiffré (même
chiffrement que les secrets) et restitués en saisissant son mot de passe.
La sauvegarde peut être relancée autant de fois que nécessaire (mode
« fusion » par défaut, ou « remplacer » pour la bascule finale).

Robustesse (v2) :
  - la tâche publie un « signe de vie » (champ `battement`) à chaque lot et la
    collection en cours avec son avancement : l'écran montre qu'elle avance ;
  - si le serveur redémarre (déploiement, mise en veille...), la tâche meurt
    avec lui : sans signe de vie depuis SILENCE_MAX secondes, la sauvegarde est
    marquée INTERROMPUE et une nouvelle peut être lancée ;
  - REPRISE : une sauvegarde interrompue peut être reprise ; les collections
    déjà copiées (et contrôlées) sont sautées, les fichiers déjà présents dans
    R2 aussi, et le même préfixe R2 est réutilisé ;
  - délais maximum sur Atlas et R2 : un appel réseau bloqué lève une erreur au
    lieu de figer la sauvegarde indéfiniment ;
  - la conversion JSON / compression est faite hors de la boucle principale
    pour ne pas ralentir le site pendant la copie.

Échecs de fichiers (lot 46) :
  - un objet introuvable (404) est « absent à la source » : compté à part
    (`fichiers_absents`), il n'empêche pas le statut « Terminée » ;
  - trop de requêtes (429), erreur serveur (5xx), délai dépassé ou coupure
    réseau : jusqu'à ESSAIS_MAX essais avec une attente croissante ;
  - chaque échec garde son code HTTP, sa cause et son origine (manifeste,
    suivi, collection `migration_echecs`), exportables en CSV ;
  - « Réessayer les échecs » relance uniquement l'étape Fichiers (reprise :
    les objets déjà présents dans R2 sont sautés, la base n'est pas recopiée).

Gros fichiers (lot 47) :
  - un objet Emergent est lu EN FLUX (morceaux de 1 Mo) vers un fichier
    temporaire, puis envoyé à R2 par boto3 (envoi en plusieurs parties) :
    rien n'est chargé entièrement en mémoire ; le SHA-256 est calculé au fil
    de l'eau. Les fichiers locaux sont envoyés directement depuis le disque ;
  - pendant l'étape Fichiers, une tâche publie un signe de vie toutes les
    BATTEMENT_FICHIER s (fichier en cours, taille, octets reçus / envoyés) :
    un long fichier ne fait plus déclarer la sauvegarde « Interrompue » ;
  - durée maximale par fichier (DUREE_MAX_FICHIER, tous essais compris) et
    délai de lecture (DELAI_LECTURE sans aucun octet reçu) : au-delà, échec
    « délai dépassé » et passage au fichier suivant ;
  - le veilleur ne déclare pas interrompue une sauvegarde dont la tâche tourne
    encore dans ce processus ;
  - les fichiers locaux (rapides) passent avant les objets Emergent.

Sauvegardes programmées et rétention (lot 47, routes/migration_programmation.py) :
  - sauvegarde automatique tous les N jours à heure fixe (mode fusion), avec des
    identifiants R2/Atlas conservés chiffrés par une clé du serveur ;
  - purge des anciennes sauvegardes dans R2 (jours de rétention + les K dernières
    réussies toujours gardées) et rapport envoyé à l'admin par Liluvine.
"""
from __future__ import annotations

import asyncio
import base64
import csv
import gzip
import hashlib
import io
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

import httpx
from bson import json_util
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from pymongo import ReplaceOne

from auth import get_current_admin
from db import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/migration", tags=["Migration vers Render"])

# Collections jamais copiées (suivi de la migration elle-même)
# (et réglage des sauvegardes programmées : le nouveau site ne doit pas hériter de la programmation)
# Lot 50 : ni l'état de la maintenance de la plateforme (le nouveau site ne démarre pas « en
# maintenance »), ni les sessions des comptes (chacun se reconnecte sur le nouveau site).
EXCLUES = {"migration_jobs", "migration_coffre", "migration_echecs", "migration_programmation",
           "maintenance_plateforme", "sessions_comptes"}
LOT = 500  # documents écrits par lot dans la base cible
JOURNAL_MAX = 300  # lignes de journal conservées dans le suivi
SILENCE_MAX = 180  # secondes sans signe de vie avant de déclarer la sauvegarde interrompue
BATTEMENT_MIN = 5  # secondes minimum entre deux mises à jour de l'avancement
# Silence toléré pour une tâche encore vivante dans ce processus (au-delà, on la croit bloquée)
SILENCE_MAX_TACHE_VIVANTE = 1800

# Références fortes vers les tâches en arrière-plan : sans elles, Python peut
# supprimer une tâche en cours d'exécution (asyncio ne garde qu'une référence faible).
_TACHES: set = set()
# Tâche de chaque sauvegarde lancée par CE processus (le veilleur ne déclare pas
# interrompue une sauvegarde dont la tâche tourne encore ici). Un serveur à plusieurs
# processus ne voit pas les tâches des autres : pour elles, seul le signe de vie compte.
_TACHES_PAR_JOB: Dict[str, asyncio.Task] = {}


class ArretDemande(BaseException):
    """Levée quand l'administrateur a demandé l'arrêt de la sauvegarde.
    Hérite de BaseException pour traverser les « except Exception » de la copie fichier par fichier."""

# Variables d'environnement du serveur à sauvegarder (chiffrées).
# Liste issue de l'inventaire du code ; les absentes sont simplement ignorées.
ENV_A_SAUVER = [
    "MONGO_URL", "DB_NAME", "CORS_ORIGINS",
    "JWT_SECRET", "JWT_ALGORITHM", "JWT_EXPIRE_HOURS", "LINK_JWT_SECRET", "WA_PLANNING_RECAP_SECRET",
    "EMERGENT_LLM_KEY", "APP_STORAGE_NAME", "UPLOAD_DIR",
    "PUBLIC_BASE_URL", "REACT_APP_BACKEND_URL", "PUBLIC_APP_URL", "SAWALI_PUBLIC_BASE_URL",
    "PUBLIC_BACKEND_URL", "BACKEND_PUBLIC_URL",
    "ADMIN_INIT_EMAIL", "ADMIN_INIT_PASSWORD", "ADMIN_INIT_NAME", "SUPER_ADMIN_EMAIL",
    "APP_VERSION", "DEPLOY_ID", "CAPTCHA_BYPASS_HOSTS",
    "STRIPE_API_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
    "GOOGLE_GEMINI_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY",
    "QDRANT_URL", "QDRANT_API_KEY",
    "R2_STOCKS_ACCOUNT_ID", "R2_STOCKS_ACCESS_KEY_ID", "R2_STOCKS_SECRET_ACCESS_KEY", "R2_STOCKS_BUCKET",
    "R2_VIDAL_ACCOUNT_ID", "R2_VIDAL_ACCESS_KEY_ID", "R2_VIDAL_SECRET_ACCESS_KEY", "R2_VIDAL_BUCKET",
    "WEBHOOK_CRON_SECRET",
    # Lot 49 : dossiers portables, sauvegarde quotidienne chiffrée vers R2
    "SNAPSHOTS_DIR", "EXPORTS_DIR", "MEMORY_DIR", "DOCS_DIR", "UPLOAD_AI_DIR", "SAUVEGARDE_AUTO_PHRASE",
    "R2_SAUVEGARDES_ACCOUNT_ID", "R2_SAUVEGARDES_ACCESS_KEY_ID", "R2_SAUVEGARDES_SECRET_ACCESS_KEY",
    "R2_SAUVEGARDES_BUCKET", "R2_SAUVEGARDES_PREFIXE",
    # Lot 53 : indépendance d'Emergent (clés IA directes, fichiers dans R2)
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "R2_FICHIERS_ACCOUNT_ID", "R2_FICHIERS_ACCESS_KEY_ID",
    "R2_FICHIERS_SECRET_ACCESS_KEY", "R2_FICHIERS_BUCKET", "R2_FICHIERS_PREFIXE", "R2_FICHIERS_PREFIXES_SECONDAIRES",
]

# Références à des fichiers du stockage Emergent trouvées dans les documents.
# Tout ce qui suit « /api/files/ » jusqu'à un espace, un guillemet, un chevron, une
# parenthèse fermante ou une barre oblique inverse : les accents sont conservés, et
# dans le JSON sérialisé un guillemet échappé (\") s'arrête sur la barre oblique inverse.
RE_API_FILES = re.compile(r'/api/files/([^\s"\'<>\\)]+)')
RE_STORAGE_PATH = re.compile(r'"storage_path"\s*:\s*"([^"]+)"')

# Préfixe des objets de l'application dans le stockage Emergent (même valeur que storage.APP_NAME)
PREFIXE_STOCKAGE = os.environ.get("APP_STORAGE_NAME", "sawali")

# Collections de JOURNAUX : copiées comme les autres, mais on n'y cherche pas de
# références de fichiers (URL anciennes, tronquées ou déjà servies autrement).
SANS_REFERENCES = {
    "api_traces", "error_registry", "activity_events", "document_logs", "wa_webhook_logs",
    "meta_webhook_events", "access_logs", "catalog_events", "ai_usage_events", "llm_usage_log",
    "voice_notifications_log", "payroll_webhook_log", "demo_expiry_events", "webhook_events_stripe",
    "planning_digest_events", "incidents_webhook_log", "liluvine_wa_autoreply_log", "vidal_sync_log",
    "vidal_api_calls_log", "impersonation_journal", "stock_sync_journal", "secret_change_audit",
    "officine_audit_log", "officines_audit", "vault_audit", "vidal_prescription_audit",
    "wa_reply_router_audit", "suggestion_override_audit", "linkedin_posts_audit", "twitter_posts_audit",
    "tiktok_posts_audit", "instagram_posts_audit", "facebook_posts_audit",
}
# Même traitement pour toute collection dont le nom se termine ainsi (journaux ajoutés plus tard)
SUFFIXES_JOURNAUX = ("_log", "_logs", "_traces", "_audit", "_journal")

# Nouvelles tentatives de lecture d'un objet Emergent (429, 5xx, délai dépassé, coupure réseau)
ESSAIS_MAX = 3
ATTENTES_ESSAIS = (2.0, 6.0)  # secondes d'attente avant le 2e puis le 3e essai
CAUSE_ABSENT = "absent à la source"
ECHECS_SUIVI_MAX = 500  # vraies erreurs détaillées dans le suivi (écran)
ABSENTS_SUIVI_MAX = 200  # absents à la source détaillés dans le suivi (écran)
ECHECS_STOCKES_MAX = 20_000  # échecs conservés par sauvegarde dans `migration_echecs` (export CSV)

# Copie des fichiers en flux (lot 47)
DUREE_MAX_FICHIER = 900  # secondes au maximum par fichier Emergent (15 min, tous essais compris)
DELAI_LECTURE = 60  # secondes au maximum sans recevoir aucun octet (délai de lecture httpx)
DELAI_CONNEXION = 30  # secondes au maximum pour se connecter au stockage Emergent
MORCEAU = 1024 * 1024  # taille des morceaux lus puis écrits dans le fichier temporaire (1 Mo)
BATTEMENT_FICHIER = 20  # secondes entre deux signes de vie pendant l'étape Fichiers
GROS_FICHIER = 20 * 1024 * 1024  # au-delà (ou taille inconnue) : ligne de journal avant la copie
JOURNAL_TOUS_LES = 25  # une ligne « n/total fichiers traités » tous les N fichiers

# Option « Copier les médias (vidéos et sons) » : décochée, ces fichiers ne sont pas copiés.
# Décision par l'extension, AVANT toute lecture ; sans extension reconnue, le type MIME annoncé
# par le stockage Emergent (en-tête, avant le contenu) peut encore l'exclure.
EXTENSIONS_MEDIAS = frozenset({
    "mp4", "mov", "m4v", "avi", "mkv", "webm", "3gp", "3g2", "mpeg", "mpg", "wmv", "flv", "ogv", "ts",
    "mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "flac", "amr", "wma", "weba", "aiff", "aif", "mid", "midi",
})
CAUSE_MEDIA = "média ignoré (option)"

# Dossiers locaux copiés vers R2 (les chemins par défaut sont ceux d'Emergent)
# Lot 49 : mêmes dossiers que le reste du serveur (backend/chemins.py)
from chemins import UPLOAD_DIR as DOSSIER_UPLOADS, SNAPSHOTS_DIR as DOSSIER_SNAPSHOTS  # noqa: E402


# ---------------------------------------------------------------------------
# Petits outils
# ---------------------------------------------------------------------------
def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hote(uri: str) -> str:
    """Hôte d'une URI MongoDB, sans identifiants (pour l'affichage)."""
    try:
        return urlparse(uri).hostname or "?"
    except Exception:  # noqa: BLE001
        return "?"


def _client_cible(uri: str):
    """Client de la base cible (fonction séparée pour pouvoir la simuler en test)."""
    from motor.motor_asyncio import AsyncIOMotorClient
    # socketTimeoutMS : un appel réseau sans réponse pendant 2 min lève une erreur (au lieu de bloquer)
    return AsyncIOMotorClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=20000, socketTimeoutMS=120000)


def _client_r2(account_id: str, access_key: str, secret_key: str):
    """Client S3 pointé sur Cloudflare R2."""
    import boto3
    from botocore.config import Config
    # Délais maximum + nouvelles tentatives automatiques en cas d'erreur réseau passagère
    config = Config(connect_timeout=20, read_timeout=120, retries={"max_attempts": 5, "mode": "standard"})
    return boto3.client("s3", endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
                        aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name="auto",
                        config=config)


@contextmanager
def _flux_objet_emergent(chemin: str):
    """Ouvre un objet du stockage Emergent EN FLUX -> (morceaux, type MIME, taille ou None).
    Même requête que storage.fetch_bytes, mais sans charger tout le contenu en mémoire.
    Délai de connexion DELAI_CONNEXION, puis DELAI_LECTURE au maximum sans aucun octet reçu.
    Clé de stockage expirée (403) : une nouvelle clé est demandée et la requête refaite une fois.
    Lève httpx.HTTPStatusError (404, 429, 5xx...), httpx.TimeoutException, httpx.TransportError,
    ou RuntimeError si le stockage Emergent n'est pas initialisé (fonction simulée en test)."""
    import storage as stockage_emergent
    if not stockage_emergent._ensure_ready() or not stockage_emergent._storage_key:
        raise RuntimeError("Emergent storage non disponible")
    url = f"{stockage_emergent.STORAGE_URL}/objects/{stockage_emergent._normalize_path(chemin)}"
    delais = httpx.Timeout(DELAI_LECTURE, connect=DELAI_CONNEXION)
    for tentative in (1, 2):
        with httpx.stream("GET", url, headers={"X-Storage-Key": stockage_emergent._storage_key},
                          timeout=delais) as reponse:
            if reponse.status_code == 403 and tentative == 1:
                # Clé de stockage expirée : nouvelle clé puis nouvel essai
                stockage_emergent._reset_storage_key()
                if stockage_emergent._try_init() and stockage_emergent._storage_key:
                    continue
            reponse.raise_for_status()
            longueur = reponse.headers.get("Content-Length") or ""
            yield (reponse.iter_bytes(MORCEAU), reponse.headers.get("Content-Type", "application/octet-stream"),
                   int(longueur) if longueur.isdigit() else None)
            return


class DureeDepassee(Exception):
    """Durée maximale par fichier (DUREE_MAX_FICHIER) dépassée pendant la lecture."""


class MediaIgnore(Exception):
    """Objet annoncé vidéo/son (type MIME) alors que l'option « Copier les médias » est décochée."""


def _est_media(chemin: str) -> bool:
    """Vrai si l'extension du fichier est celle d'une vidéo ou d'un son (EXTENSIONS_MEDIAS)."""
    nom = chemin.rsplit("/", 1)[-1].lower()
    return "." in nom and nom.rsplit(".", 1)[1] in EXTENSIONS_MEDIAS


def _en_mo(octets: Optional[int]) -> str:
    """Octets -> texte en Mo (journal)."""
    return f"{(octets or 0) / 1048576:.1f} Mo"


def _telecharger(chemin: str, sortie, etat: Dict[str, Any], echeance: float, arret: threading.Event,
                 annoncer=None, ignorer_medias: bool = False) -> tuple:
    """Lit un objet Emergent en flux et l'écrit dans `sortie` (fichier temporaire, vidé d'abord).
    -> (type MIME, octets reçus, SHA-256). Exécuté dans un fil séparé.
    `etat` reçoit la taille annoncée et les octets reçus (publiés par le signe de vie périodique) ;
    `annoncer(taille)` est appelé dès que la taille est connue (ligne de journal des gros fichiers).
    S'arrête entre deux morceaux si l'échéance (time.monotonic) est dépassée ou l'arrêt demandé.
    ignorer_medias : un type MIME vidéo/son lève MediaIgnore AVANT de lire le contenu."""
    sortie.seek(0)
    sortie.truncate()
    empreinte, recus = hashlib.sha256(), 0
    etat.update(taille=None, recus=0, envoyes=0, phase="lecture")
    with _flux_objet_emergent(chemin) as (morceaux, type_mime, taille):
        if ignorer_medias and (type_mime or "").split(";")[0].strip().lower().startswith(("video/", "audio/")):
            raise MediaIgnore(type_mime)
        etat["taille"] = taille
        if annoncer is not None:
            annoncer(taille)
        for morceau in morceaux:
            sortie.write(morceau)
            empreinte.update(morceau)
            recus += len(morceau)
            etat["recus"] = recus
            if arret.is_set():
                raise ArretDemande()
            if time.monotonic() > echeance:
                raise DureeDepassee(f"durée maximale de {DUREE_MAX_FICHIER // 60} min dépassée "
                                    f"({_en_mo(recus)} reçus sur {_en_mo(taille) if taille else '?'})")
    return type_mime, recus, empreinte.hexdigest()


def _sha256_fichier(fichier: Path) -> tuple:
    """SHA-256 et taille d'un fichier du disque, lus par morceaux (jamais tout en mémoire)."""
    empreinte, taille = hashlib.sha256(), 0
    with open(fichier, "rb") as f:
        for morceau in iter(lambda: f.read(MORCEAU), b""):
            empreinte.update(morceau)
            taille += len(morceau)
    return empreinte.hexdigest(), taille


def _sans_references(nom: str) -> bool:
    """Vrai pour une collection de journaux : on n'y cherche pas de références de fichiers."""
    return nom in SANS_REFERENCES or nom.endswith(SUFFIXES_JOURNAUX)


def _classer_erreur(exc: BaseException) -> tuple:
    """Exception de lecture/écriture -> (code HTTP ou None, cause lisible, nouvelle tentative utile ?).
    storage.fetch_bytes lève httpx.HTTPStatusError (raise_for_status), httpx.TimeoutException,
    httpx.TransportError, ou RuntimeError si le stockage Emergent n'est pas initialisé."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404:
            return code, CAUSE_ABSENT, False
        if code == 429:
            return code, "trop de requêtes", True
        if code >= 500:
            return code, "erreur du serveur source", True
        if code in (401, 403):
            return code, "accès refusé", False
        return code, "erreur HTTP", False
    if isinstance(exc, (httpx.TimeoutException, DureeDepassee)):
        return None, "délai dépassé", True
    if isinstance(exc, httpx.TransportError):
        return None, "erreur réseau", True
    if isinstance(exc, RuntimeError) and "non disponible" in str(exc):
        return None, "stockage Emergent indisponible", False
    return None, "autre erreur", False


class EchecLecture(Exception):
    """Lecture d'un objet Emergent impossible après les essais autorisés."""

    def __init__(self, exc: BaseException, code: Optional[int], cause: str, essais: int):
        super().__init__(str(exc))
        self.code, self.cause, self.essais = code, cause, essais


async def _lire_avec_essais(chemin: str, sortie, etat: Dict[str, Any], arret: threading.Event,
                            annoncer=None, ignorer_medias: bool = False) -> tuple:
    """Lit un objet Emergent en flux dans `sortie` -> (type MIME, octets, SHA-256, nombre d'essais).
    Jusqu'à ESSAIS_MAX essais, avec une attente croissante, pour les erreurs passagères
    (429, 5xx, délai dépassé, réseau) ; un 404 ou un refus d'accès échoue tout de suite.
    Tous les essais tiennent dans DUREE_MAX_FICHIER : une fois cette durée écoulée, plus d'essai
    (échec « délai dépassé », qui pourra être repris par « Réessayer les échecs »)."""
    echeance = time.monotonic() + DUREE_MAX_FICHIER
    essai = 0
    while True:
        essai += 1
        try:
            type_mime, octets, sha = await asyncio.to_thread(_telecharger, chemin, sortie, etat, echeance, arret,
                                                             annoncer, ignorer_medias)
            return type_mime, octets, sha, essai
        except MediaIgnore:
            raise
        except Exception as exc:  # noqa: BLE001
            code, cause, reessayable = _classer_erreur(exc)
            attente = ATTENTES_ESSAIS[min(essai - 1, len(ATTENTES_ESSAIS) - 1)]
            if not reessayable or essai >= ESSAIS_MAX or isinstance(exc, DureeDepassee) \
                    or time.monotonic() + attente >= echeance:
                raise EchecLecture(exc, code, cause, essai) from exc
            await asyncio.sleep(attente)


def _chiffrer(donnees: bytes, mot_de_passe: str) -> Dict[str, Any]:
    """Chiffrement AES-256-GCM avec clé dérivée du mot de passe (PBKDF2-SHA256, 200 000 tours)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    sel, nonce = os.urandom(16), os.urandom(12)
    cle = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sel, iterations=200_000).derive(mot_de_passe.encode())
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"format": "sawali-migration-secrets/v1", "algo": "AES-256-GCM", "kdf": "PBKDF2-SHA256",
            "iterations": 200_000, "sel": b64(sel), "nonce": b64(nonce),
            "donnees": b64(AESGCM(cle).encrypt(nonce, donnees, None))}


def _dechiffrer(enveloppe: Dict[str, Any], mot_de_passe: str) -> bytes:
    """Inverse de _chiffrer. Lève une exception si le mot de passe est faux (contrôle d'intégrité GCM)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    d = lambda k: base64.b64decode(enveloppe[k])  # noqa: E731
    cle = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=d("sel"),
                     iterations=int(enveloppe["iterations"])).derive(mot_de_passe.encode())
    return AESGCM(cle).decrypt(d("nonce"), d("donnees"), None)


# ---------------------------------------------------------------------------
# Coffre des identifiants de migration (chiffré par mot de passe)
# ---------------------------------------------------------------------------
# Un seul document, dans une collection exclue de la copie. Le serveur ne stocke
# que le contenu CHIFFRÉ ; le mot de passe n'est jamais enregistré.
COFFRE_ID = "identifiants"
COFFRE_ESSAIS_MAX = 5  # mots de passe faux tolérés avant blocage temporaire
COFFRE_BLOCAGE_S = 900  # durée du blocage (15 min)
CHAMPS_COFFRE = ("mongo_uri", "mongo_db", "r2_account_id", "r2_access_key_id", "r2_secret_access_key", "r2_bucket")


class CoffreEnregistrer(BaseModel):
    mot_de_passe: str = Field(..., min_length=12, max_length=200)
    mongo_uri: str = ""
    mongo_db: str = ""
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""


class CoffreOuvrir(BaseModel):
    mot_de_passe: str = Field(..., min_length=1, max_length=200)


@router.get("/coffre")
async def etat_coffre(_: dict = Depends(get_current_admin)):
    """Indique seulement si des identifiants sont mémorisés (jamais leur contenu)."""
    doc = await db.migration_coffre.find_one({"_id": COFFRE_ID}, {"cree_le": 1, "par": 1, "champs": 1})
    if not doc:
        return {"existe": False}
    return {"existe": True, "cree_le": doc.get("cree_le"), "par": doc.get("par"), "champs": doc.get("champs", [])}


@router.put("/coffre")
async def enregistrer_coffre(corps: CoffreEnregistrer, admin: dict = Depends(get_current_admin)):
    """Chiffre (AES-256-GCM, PBKDF2 200 000 tours) et mémorise les identifiants saisis. Remplace l'ancien coffre."""
    valeurs = {k: getattr(corps, k) for k in CHAMPS_COFFRE if getattr(corps, k)}
    if not valeurs:
        raise HTTPException(400, "Aucun identifiant à mémoriser")
    enveloppe = await asyncio.to_thread(_chiffrer, json.dumps(valeurs).encode(), corps.mot_de_passe)
    await db.migration_coffre.replace_one(
        {"_id": COFFRE_ID},
        {"_id": COFFRE_ID, "enveloppe": enveloppe, "cree_le": _maintenant(), "par": admin.get("email", ""),
         "champs": sorted(valeurs), "echecs": 0, "bloque_jusqua": None},
        upsert=True)
    return {"ok": True, "champs": sorted(valeurs)}


@router.post("/coffre/ouvrir")
async def ouvrir_coffre(corps: CoffreOuvrir, _: dict = Depends(get_current_admin)):
    """Restitue les identifiants si le mot de passe est bon. Blocage 15 min après 5 échecs."""
    doc = await db.migration_coffre.find_one({"_id": COFFRE_ID})
    if not doc:
        raise HTTPException(404, "Aucun identifiant mémorisé")
    if doc.get("bloque_jusqua") and _age_secondes(doc["bloque_jusqua"]) < 0:
        raise HTTPException(429, "Trop d'essais : coffre bloqué pendant 15 minutes")
    try:
        valeurs = json.loads(await asyncio.to_thread(_dechiffrer, doc["enveloppe"], corps.mot_de_passe))
    except Exception:  # noqa: BLE001 — mot de passe faux (échec du contrôle d'intégrité)
        echecs = int(doc.get("echecs") or 0) + 1
        bloque = None
        if echecs >= COFFRE_ESSAIS_MAX:
            bloque = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + COFFRE_BLOCAGE_S,
                                            timezone.utc).isoformat()
            echecs = 0
        await db.migration_coffre.update_one({"_id": COFFRE_ID}, {"$set": {"echecs": echecs, "bloque_jusqua": bloque}})
        raise HTTPException(400, "Mot de passe incorrect")
    await db.migration_coffre.update_one({"_id": COFFRE_ID}, {"$set": {"echecs": 0, "bloque_jusqua": None}})
    return {k: valeurs.get(k, "") for k in CHAMPS_COFFRE}


@router.delete("/coffre")
async def oublier_coffre(_: dict = Depends(get_current_admin)):
    """Efface définitivement les identifiants mémorisés."""
    await db.migration_coffre.delete_one({"_id": COFFRE_ID})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Inventaire (lecture seule)
# ---------------------------------------------------------------------------
def _taille_dossier(dossier: Path) -> Dict[str, int]:
    n, taille = 0, 0
    if dossier.exists():
        for f in dossier.rglob("*"):
            if f.is_file():
                n += 1
                taille += f.stat().st_size
    return {"fichiers": n, "octets": taille}


@router.get("/inventaire")
async def inventaire(_: dict = Depends(get_current_admin)):
    """Ce que contient le site : collections et nombre de documents, fichiers, variables présentes."""
    noms = sorted(n for n in await db.list_collection_names() if not n.startswith("system.") and n not in EXCLUES)
    collections = []
    for nom in noms:
        collections.append({"nom": nom, "documents": await db[nom].estimated_document_count()})
    return {
        "collections": collections,
        "total_documents": sum(c["documents"] for c in collections),
        "fichiers": {
            "stored_objects": await db.stored_objects.count_documents({}),
            "files_avec_storage_path": await db.files.count_documents({"storage_path": {"$nin": [None, ""]}}),
            "uploads_local": _taille_dossier(DOSSIER_UPLOADS),
            "snapshots_local": _taille_dossier(DOSSIER_SNAPSHOTS),
        },
        # Noms seulement : jamais les valeurs
        "variables": [{"nom": n, "definie": bool(os.environ.get(n))} for n in ENV_A_SAUVER],
    }


# ---------------------------------------------------------------------------
# Lancement et suivi
# ---------------------------------------------------------------------------
class Cible(BaseModel):
    # Obligatoire seulement si la base est copiée (« Réessayer les échecs » ne copie que les fichiers)
    mongo_uri: str = Field("", max_length=2000, description="URI MongoDB Atlas de la nouvelle base")
    mongo_db: str = Field("sawali", min_length=1, max_length=60)
    remplacer: bool = False  # True : vide chaque collection cible avant copie (bascule finale)
    r2_account_id: str = Field(..., min_length=4)
    r2_access_key_id: str = Field(..., min_length=4)
    r2_secret_access_key: str = Field(..., min_length=4)
    r2_bucket: str = Field(..., min_length=3, max_length=63)
    copier_base: bool = True
    copier_fichiers: bool = True
    sauver_secrets: bool = True
    # Lot 47 : décoché, les vidéos et sons ne sont pas copiés (repris tel quel en reprise)
    copier_medias: bool = True
    mot_de_passe_secrets: Optional[str] = Field(None, max_length=200)
    # Identifiant d'une sauvegarde INTERROMPUE ou en ÉCHEC à reprendre (sinon : nouvelle sauvegarde)
    reprendre: Optional[str] = Field(None, max_length=40)


def _age_secondes(horodatage: Optional[str]) -> float:
    """Secondes écoulées depuis un horodatage ISO (très grand si absent ou illisible)."""
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(horodatage)).total_seconds()
    except Exception:  # noqa: BLE001
        return float("inf")


def _tache_vivante(job_id: str) -> bool:
    """Vrai si la tâche de cette sauvegarde tourne encore dans CE processus."""
    tache = _TACHES_PAR_JOB.get(job_id)
    return tache is not None and not tache.done()


async def _marquer_orphelines() -> None:
    """Sauvegardes « EN_COURS » dont la tâche est perdue -> INTERROMPUE (serveur redémarré...).
      - tâche encore vivante dans ce processus : jamais déclarée interrompue, sauf silence anormal
        de plus de SILENCE_MAX_TACHE_VIVANTE s (tâche sans doute bloquée) ;
      - tâche lancée ici mais terminée sans statut final : interrompue tout de suite ;
      - tâche inconnue ici (serveur redémarré, ou autre processus) : interrompue après SILENCE_MAX s
        sans signe de vie (le signe de vie périodique de l'étape Fichiers la protège)."""
    async for j in db.migration_jobs.find({"statut": "EN_COURS"}, {"_id": 0, "id": 1, "battement": 1, "debut": 1}):
        silence = _age_secondes(j.get("battement") or j.get("debut"))
        if _tache_vivante(j["id"]):
            if silence <= SILENCE_MAX_TACHE_VIVANTE:
                continue
            ligne = f"{_maintenant()[11:19]} INTERROMPUE : tâche bloquée, aucun signe de vie depuis {int(silence)} s"
        elif j["id"] in _TACHES_PAR_JOB:
            ligne = f"{_maintenant()[11:19]} INTERROMPUE : la tâche s'est arrêtée sans statut final"
        elif silence > SILENCE_MAX:
            ligne = f"{_maintenant()[11:19]} INTERROMPUE : plus de signe de vie depuis {SILENCE_MAX} s (serveur redémarré ?)"
        else:
            continue
        await db.migration_jobs.update_one(
            {"id": j["id"], "statut": "EN_COURS"},
            {"$set": {"statut": "INTERROMPUE", "etape": "Interrompue", "fin": _maintenant()},
             "$push": {"journal": {"$each": [ligne], "$slice": -JOURNAL_MAX}}})


@router.post("/lancer", status_code=202)
async def lancer(cible: Cible, admin: dict = Depends(get_current_admin)):
    return await _demarrer(cible, admin.get("email", ""))


async def _demarrer(cible: Cible, lance_par: str, programmee: bool = False) -> Dict[str, Any]:
    """Contrôle la demande, vérifie les connexions puis lance la sauvegarde en arrière-plan.
    Commun au bouton « Lancer » et aux sauvegardes programmées (routes/migration_programmation.py).
    Lève HTTPException (400, 404, 409) quand la sauvegarde ne peut pas démarrer.
    programmee=True : sauvegarde déclenchée par la programmation (rapport Liluvine et purge ensuite)."""
    await _marquer_orphelines()
    if await db.migration_jobs.find_one({"statut": "EN_COURS"}):
        raise HTTPException(409, "Une sauvegarde de migration est déjà en cours")
    # Reprise : on repart de la sauvegarde indiquée (mêmes collections déjà faites, même préfixe R2)
    precedente = None
    if cible.reprendre:
        precedente = await db.migration_jobs.find_one({"id": cible.reprendre}, {"_id": 0, "secrets_chiffres": 0})
        if not precedente:
            raise HTTPException(404, "Sauvegarde à reprendre introuvable")
        if precedente.get("statut") not in ("INTERROMPUE", "ECHEC", "TERMINEE_AVEC_ERREURS"):
            raise HTTPException(400, "Seule une sauvegarde interrompue, en échec ou avec anomalies peut être reprise")
        if cible.remplacer:
            raise HTTPException(400, "La reprise se fait en mode fusion : décochez « Remplacer »")
        # Le choix « Copier les médias » de la sauvegarde reprise est conservé tel quel
        medias_precedent = (precedente.get("options") or {}).get("medias")
        if medias_precedent is not None:
            cible = cible.model_copy(update={"copier_medias": bool(medias_precedent)})
    if cible.sauver_secrets and len(cible.mot_de_passe_secrets or "") < 12:
        raise HTTPException(400, "Mot de passe des secrets : 12 caractères minimum")
    if not (cible.copier_base or cible.copier_fichiers or cible.sauver_secrets):
        raise HTTPException(400, "Choisissez au moins un élément à sauvegarder")
    if cible.copier_base and len(cible.mongo_uri or "") < 10:
        raise HTTPException(400, "URI MongoDB Atlas manquante")

    # Vérification des connexions AVANT de lancer quoi que ce soit (Atlas seulement si la base est copiée)
    client = None
    if cible.copier_base:
        try:
            client = _client_cible(cible.mongo_uri)
            await client.admin.command("ping")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Connexion à MongoDB Atlas impossible : {str(exc)[:200]}")
    r2 = _client_r2(cible.r2_account_id, cible.r2_access_key_id, cible.r2_secret_access_key)
    try:
        await asyncio.to_thread(r2.head_bucket, Bucket=cible.r2_bucket)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Accès au bucket R2 « {cible.r2_bucket} » impossible : {str(exc)[:200]}")

    job_id = secrets.token_urlsafe(10)
    prefixe = (precedente["cible"]["prefixe"] if precedente
               else f"migration-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}")
    # Collections déjà copiées et contrôlées lors de la sauvegarde reprise (même base cible uniquement)
    deja_faites = []
    if precedente and precedente["cible"].get("mongo_hote") == _hote(cible.mongo_uri) \
            and precedente["cible"].get("mongo_db") == cible.mongo_db:
        deja_faites = [r for r in precedente.get("resultats_collections", []) if r.get("ok")]
    # Hôte Atlas affiché : celui de la sauvegarde reprise quand la base n'est pas recopiée
    mongo_hote = (_hote(cible.mongo_uri) if cible.mongo_uri
                  else (precedente or {}).get("cible", {}).get("mongo_hote", "—"))
    job = {
        "id": job_id, "statut": "EN_COURS", "etape": "Démarrage", "debut": _maintenant(), "fin": None,
        "lance_par": lance_par,
        # Lot 47 : sauvegarde programmée ? (le rapport Liluvine est envoyé une fois terminée)
        "programmee": programmee, "rapport": None,
        # Octets envoyés à R2 : archives de la base et fichiers (taille indiquée dans le rapport)
        "octets_archives": 0, "octets_fichiers": 0,
        # Description de la cible SANS identifiants
        "cible": {"mongo_hote": mongo_hote, "mongo_db": cible.mongo_db, "remplacer": cible.remplacer,
                  "r2_bucket": cible.r2_bucket, "prefixe": prefixe},
        "options": {"base": cible.copier_base, "fichiers": cible.copier_fichiers, "secrets": cible.sauver_secrets,
                    "medias": cible.copier_medias},
        "collections_total": 0, "collections_faites": 0, "documents_copies": 0,
        "resultats_collections": [], "fichiers_total": 0, "fichiers_copies": 0, "fichiers_echecs": 0,
        # Lot 46 : absents à la source (404) comptés à part ; échecs regroupés par cause
        "fichiers_absents": 0, "echecs_par_cause": {}, "absents_fichiers": [],
        # Lot 47 : vidéos et sons non copiés (option décochée), jamais comptés comme erreurs
        "fichiers_medias_ignores": 0,
        "echecs_fichiers": [], "secrets": None, "secrets_chiffres": None, "journal": [],
        # Suivi en direct : signe de vie + collection en cours ; reprise éventuelle
        "battement": _maintenant(), "en_cours": None, "arret_demande": False,
        "reprise_de": precedente["id"] if precedente else None,
    }
    if deja_faites:
        job["resultats_collections"] = deja_faites
        job["collections_faites"] = len(deja_faites)
        job["journal"] = [f"{_maintenant()[11:19]} Reprise de {precedente['id']} : "
                          f"{len(deja_faites)} collection(s) déjà copiée(s) seront sautées"]
    await db.migration_jobs.insert_one(dict(job))
    tache = asyncio.create_task(_executer(job_id, cible, client, r2, prefixe, {r["nom"] for r in deja_faites},
                                          bool(precedente)))
    _TACHES.add(tache)  # référence forte tant que la tâche tourne
    tache.add_done_callback(_TACHES.discard)
    _TACHES_PAR_JOB[job_id] = tache
    return {"id": job_id, "prefixe": prefixe}


@router.post("/jobs/{job_id}/reessayer-echecs", status_code=202)
async def reessayer_echecs(job_id: str, cible: Cible, admin: dict = Depends(get_current_admin)):
    """« Réessayer les échecs » : reprise de l'étape Fichiers SEULEMENT (ni base, ni secrets).
    Les objets déjà présents dans R2 sont sautés ; seuls les manquants sont relus et copiés.
    Seuls les identifiants R2 sont nécessaires."""
    cible = cible.model_copy(update={"reprendre": job_id, "copier_base": False, "copier_fichiers": True,
                                     "sauver_secrets": False, "remplacer": False})
    return await lancer(cible, admin)


@router.post("/jobs/{job_id}/arreter")
async def arreter_job(job_id: str, _: dict = Depends(get_current_admin)):
    """Demande l'arrêt d'une sauvegarde en cours (prise en compte au lot suivant)."""
    job = await db.migration_jobs.find_one({"id": job_id}, {"_id": 0, "statut": 1, "battement": 1, "debut": 1})
    if not job:
        raise HTTPException(404, "Sauvegarde introuvable")
    if job["statut"] != "EN_COURS":
        return {"ok": True, "statut": job["statut"]}
    if not _tache_vivante(job_id) and _age_secondes(job.get("battement") or job.get("debut")) > SILENCE_MAX:
        # Tâche déjà morte : on la déclare interrompue tout de suite
        await _marquer_orphelines()
        return {"ok": True, "statut": "INTERROMPUE"}
    await db.migration_jobs.update_one({"id": job_id}, {"$set": {"arret_demande": True}})
    return {"ok": True, "statut": "ARRET_DEMANDE"}


@router.get("/jobs")
async def lister_jobs(_: dict = Depends(get_current_admin)):
    await _marquer_orphelines()
    return await db.migration_jobs.find({}, {"_id": 0, "secrets_chiffres": 0, "journal": 0,
                                               "resultats_collections": 0, "echecs_fichiers": 0,
                                               "absents_fichiers": 0}
                                        ).sort("debut", -1).to_list(20)


@router.get("/jobs/{job_id}")
async def lire_job(job_id: str, _: dict = Depends(get_current_admin)):
    await _marquer_orphelines()
    job = await db.migration_jobs.find_one({"id": job_id}, {"_id": 0, "secrets_chiffres": 0})
    if not job:
        raise HTTPException(404, "Sauvegarde introuvable")
    return job


@router.get("/jobs/{job_id}/secrets")
async def telecharger_secrets(job_id: str, _: dict = Depends(get_current_admin)):
    """Fichier des secrets CHIFFRÉ (inutilisable sans le mot de passe saisi au lancement)."""
    job = await db.migration_jobs.find_one({"id": job_id}, {"_id": 0, "secrets_chiffres": 1})
    if not job or not job.get("secrets_chiffres"):
        raise HTTPException(404, "Aucun fichier de secrets pour cette sauvegarde")
    return Response(content=json.dumps(job["secrets_chiffres"], indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="sawali-secrets-{job_id}.enc.json"'})


# Colonnes de l'export CSV des échecs de fichiers
COLONNES_CSV = ("type", "source", "origine", "cause", "code_http", "essais", "erreur", "cle_r2")


@router.get("/jobs/{job_id}/echecs.csv")
async def exporter_echecs(job_id: str, _: dict = Depends(get_current_admin)):
    """Échecs de fichiers d'une sauvegarde en CSV (UTF-8 avec BOM pour Excel, séparateur « ; »).
    Vraies erreurs d'abord, puis absents à la source. Lu depuis la base : aucun identifiant R2 requis.
    Les sauvegardes antérieures au lot 46 n'ont que la liste du suivi (500 premiers échecs)."""
    job = await db.migration_jobs.find_one({"id": job_id}, {"_id": 0, "echecs_fichiers": 1, "cible": 1})
    if not job:
        raise HTTPException(404, "Sauvegarde introuvable")
    lignes = await db.migration_echecs.find({"job_id": job_id}, {"_id": 0}).sort(
        [("absent", 1), ("cause", 1), ("source", 1)]).to_list(ECHECS_STOCKES_MAX)
    if not lignes:
        lignes = job.get("echecs_fichiers") or []
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(COLONNES_CSV)
    for e in lignes:
        ecrivain.writerow([
            "absent à la source" if e.get("absent") else "erreur",
            e.get("source", ""), e.get("origine", ""), e.get("cause", ""),
            e.get("code") if e.get("code") is not None else "", e.get("essais", ""),
            (e.get("erreur") or "").replace("\r", " ").replace("\n", " "), e.get("cle", ""),
        ])
    nom = f"sawali-migration-echecs-{(job.get('cible') or {}).get('prefixe') or job_id}.csv"
    return Response(content=("\ufeff" + sortie.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nom}"'})


# ---------------------------------------------------------------------------
# Exécution en arrière-plan
# ---------------------------------------------------------------------------
async def _maj(job_id: str, ligne: Optional[str] = None, **champs) -> None:
    """Met à jour le suivi (et ajoute une ligne horodatée au journal)."""
    maj: Dict[str, Any] = {"$set": champs} if champs else {}
    if ligne:
        logger.info("[migration] %s", ligne)
        maj["$push"] = {"journal": {"$each": [f"{_maintenant()[11:19]} {ligne}"], "$slice": -JOURNAL_MAX}}
    if maj:
        await db.migration_jobs.update_one({"id": job_id}, maj)


async def _battement(job_id: str, en_cours: Optional[Dict[str, Any]] = None, force: bool = False,
                    _dernier: Dict[str, float] = {}) -> None:  # noqa: B006 (mémoire volontaire entre appels)
    """Publie le signe de vie (au plus toutes les BATTEMENT_MIN s) et vérifie la demande d'arrêt."""
    maintenant = asyncio.get_running_loop().time()
    if not force and maintenant - _dernier.get(job_id, 0) < BATTEMENT_MIN:
        return
    _dernier[job_id] = maintenant
    champs: Dict[str, Any] = {"battement": _maintenant()}
    if en_cours is not None:
        champs["en_cours"] = en_cours
    job = await db.migration_jobs.find_one_and_update({"id": job_id}, {"$set": champs},
                                                      projection={"_id": 0, "arret_demande": 1})
    if job and job.get("arret_demande"):
        raise ArretDemande()


async def _executer(job_id: str, cible: Cible, client, r2, prefixe: str,
                    deja_faites: Optional[set] = None, reprise: bool = False) -> None:
    # Références de fichiers trouvées dans la base : {(genre, valeur): collection d'origine}
    references: Dict[tuple, str] = {}
    manifeste: Dict[str, Any] = {"prefixe": prefixe, "debut": _maintenant(), "collections": [], "fichiers": []}
    erreurs = 0
    try:
        if cible.copier_base:
            erreurs += await _copier_base(job_id, cible, client, r2, prefixe, references, manifeste,
                                          deja_faites or set())
        elif cible.copier_fichiers:
            # Fichiers seuls (ex. « Réessayer les échecs ») : on relit la base sans la copier,
            # uniquement pour retrouver les références de fichiers
            await _maj(job_id, "Base non recopiée : relecture des références de fichiers", etape="Références")
            noms = sorted(n for n in await db.list_collection_names()
                          if not n.startswith("system.") and n not in EXCLUES and not _sans_references(n))
            for nom in noms:
                await _relire_references(job_id, nom, references)
        if cible.copier_fichiers:
            erreurs += await _copier_fichiers(job_id, cible, r2, prefixe, references, manifeste, reprise)
        if cible.sauver_secrets:
            await _sauver_secrets(job_id, cible, r2, prefixe)
        manifeste["fin"] = _maintenant()
        await asyncio.to_thread(r2.put_object, Bucket=cible.r2_bucket, Key=f"{prefixe}/manifest.json",
                                Body=json.dumps(manifeste, ensure_ascii=False, indent=1).encode(),
                                ContentType="application/json")
        statut = "TERMINEE" if erreurs == 0 else "TERMINEE_AVEC_ERREURS"
        await _maj(job_id, f"Terminé ({erreurs} anomalie(s)). Manifeste : {prefixe}/manifest.json",
                   statut=statut, etape="Terminé", fin=_maintenant(), en_cours=None, battement=_maintenant())
    except ArretDemande:
        await _maj(job_id, "Arrêtée à la demande de l'administrateur (reprise possible)",
                   statut="INTERROMPUE", etape="Interrompue", fin=_maintenant(), en_cours=None)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[migration] échec")
        await _maj(job_id, f"ÉCHEC : {str(exc)[:300]}", statut="ECHEC", etape="Échec", fin=_maintenant(),
                   en_cours=None)
    finally:
        try:
            if client is not None:
                client.close()
        except Exception:  # noqa: BLE001
            pass


def _serialiser_lot(docs: List[dict], extraire: bool = True) -> tuple:
    """Lot de documents -> (octets EJSON, une ligne par document ; références de fichiers trouvées).
    Références : ensemble de couples ("api", ce qui suit /api/files/) ou ("stockage", valeur de storage_path).
    extraire=False pour les collections de journaux (aucune référence relevée).
    Exécuté dans un fil séparé pour ne pas bloquer le site pendant la copie."""
    morceaux, refs = [], set()
    for doc in docs:
        ligne = json_util.dumps(doc, json_options=json_util.CANONICAL_JSON_OPTIONS, ensure_ascii=False)
        morceaux.append(ligne + "\n")
        if not extraire:
            continue
        # Références à des fichiers (pour l'étape Fichiers)
        if "/api/files/" in ligne:
            refs.update(("api", r) for r in RE_API_FILES.findall(ligne))
        if "storage_path" in ligne:
            refs.update(("stockage", r) for r in RE_STORAGE_PATH.findall(ligne))
    return "".join(morceaux).encode("utf-8"), refs


def _ajouter_references(references: Dict[tuple, str], refs: set, nom: str) -> None:
    """Ajoute les références d'un lot en retenant la première collection où chacune a été vue."""
    for r in refs:
        references.setdefault(r, nom)


async def _relire_references(job_id: str, nom: str, references: Dict[tuple, str]) -> None:
    """Relit une collection SANS la copier, seulement pour relever ses références de fichiers."""
    if _sans_references(nom):
        return
    lot_refs: List[dict] = []
    async for doc in db[nom].find({}, batch_size=LOT):
        lot_refs.append(doc)
        if len(lot_refs) >= LOT:
            _ajouter_references(references, (await asyncio.to_thread(_serialiser_lot, lot_refs))[1], nom)
            lot_refs = []
            await _battement(job_id, {"collection": nom, "copies": 0, "total": 0, "saut": True})
    if lot_refs:
        _ajouter_references(references, (await asyncio.to_thread(_serialiser_lot, lot_refs))[1], nom)


async def _copier_base(job_id, cible, client, r2, prefixe, references, manifeste, deja_faites=frozenset()) -> int:
    """Copie chaque collection vers Atlas (+ archive EJSON dans R2). Renvoie le nombre d'anomalies."""
    tdb = client[cible.mongo_db]
    noms = sorted(n for n in await db.list_collection_names() if not n.startswith("system.") and n not in EXCLUES)
    # Total estimé des documents (instantané, sans parcourir les collections) -> jauge de progression globale
    documents_total = 0
    for nom in noms:
        documents_total += await db[nom].estimated_document_count()
    await _maj(job_id, f"Base : {len(noms)} collections à copier ({documents_total} documents)",
               etape="Base de données", collections_total=len(noms), documents_total=documents_total)
    anomalies, total_docs = 0, 0
    for nom in noms:
        src, dst = db[nom], tdb[nom]
        if nom in deja_faites:
            # Reprise : collection déjà copiée et contrôlée. On relit seulement ses références de fichiers
            # (sans les copier à nouveau) pour que l'étape Fichiers reste complète.
            await _relire_references(job_id, nom, references)
            await _maj(job_id, f"  = {nom} : déjà copiée (reprise)")
            continue
        n_source = await src.count_documents({})
        await _battement(job_id, {"collection": nom, "copies": 0, "total": n_source}, force=True)
        if cible.remplacer:
            await dst.drop()
        # Archive EJSON compressée, écrite dans un fichier temporaire puis envoyée à R2
        empreinte = hashlib.sha256()
        copies = 0
        with tempfile.TemporaryFile() as tmp:
            with gzip.GzipFile(fileobj=tmp, mode="wb") as gz:

                async def ecrire_lot(docs: List[dict]) -> None:
                    """Archive (hors boucle principale) puis écrit le lot dans Atlas ; publie l'avancement."""
                    nonlocal copies
                    donnees, refs = await asyncio.to_thread(_serialiser_lot, docs, not _sans_references(nom))
                    await asyncio.to_thread(gz.write, donnees)
                    empreinte.update(donnees)
                    _ajouter_references(references, refs, nom)
                    await dst.bulk_write([ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs],
                                         ordered=False)
                    copies += len(docs)
                    await _battement(job_id, {"collection": nom, "copies": copies, "total": n_source})

                lot: List[dict] = []
                async for doc in src.find({}, batch_size=LOT):
                    lot.append(doc)
                    if len(lot) >= LOT:
                        await ecrire_lot(lot)
                        lot = []
                if lot:
                    await ecrire_lot(lot)
            taille = tmp.tell()
            tmp.seek(0)
            await asyncio.to_thread(r2.upload_fileobj, tmp, cible.r2_bucket, f"{prefixe}/mongo/{nom}.jsonl.gz",
                                    ExtraArgs={"ContentType": "application/gzip"})
        # Index (hors _id)
        index_copies = 0
        for nom_index, info in (await src.index_information()).items():
            if nom_index == "_id_":
                continue
            options = {k: v for k, v in info.items()
                       if k in ("unique", "sparse", "expireAfterSeconds", "partialFilterExpression",
                                "collation", "weights", "default_language", "language_override")}
            try:
                await dst.create_index(info["key"], name=nom_index, **options)
                index_copies += 1
            except Exception as exc:  # noqa: BLE001
                await _maj(job_id, f"  index {nom}.{nom_index} non recréé : {str(exc)[:120]}")
        n_cible = await dst.count_documents({})
        # En mode fusion la cible peut contenir plus de documents (données déjà présentes)
        ok = n_cible == n_source if cible.remplacer else n_cible >= n_source
        anomalies += 0 if ok else 1
        total_docs += copies
        resultat = {"nom": nom, "source": n_source, "cible": n_cible, "ok": ok, "index": index_copies,
                    "archive_octets": taille, "sha256": empreinte.hexdigest()}
        manifeste["collections"].append(resultat)
        await db.migration_jobs.update_one({"id": job_id}, {"$push": {"resultats_collections": resultat},
                                                            "$inc": {"collections_faites": 1, "documents_copies": copies,
                                                                     "octets_archives": taille}})
        await _maj(job_id, f"  {'✓' if ok else '✗'} {nom} : {n_source} → {n_cible}")
    await _maj(job_id, f"Base terminée : {total_docs} documents copiés, {anomalies} anomalie(s)")
    return anomalies


def _normaliser_chemin(brut: Any) -> str:
    """Référence brute -> chemin propre : sans paramètres d'URL (?…, #…), décodé (%20 -> espace),
    sans « / » initial ni ponctuation de fin de phrase."""
    if not brut or not isinstance(brut, str):
        return ""
    c = brut.strip().split("?", 1)[0].split("#", 1)[0]
    c = unquote(c).strip().rstrip(".,;:!")
    return c.lstrip("/")


def _cle_canonique(chemin: str) -> str:
    """Forme comparable d'un chemin (storage.fetch_bytes ajoute le préfixe s'il manque) : sert au dédoublonnage."""
    return chemin if chemin.startswith(f"{PREFIXE_STOCKAGE}/") else f"{PREFIXE_STOCKAGE}/{chemin}"


def _traduire_reference(ref: str, fichiers: Dict[str, Optional[str]]) -> tuple:
    """Ce qui suit « /api/files/ » -> (chemin de stockage ou None, motif).
      - « sawali/... » : chemin du stockage objet (route proxy), gardé tel quel ;
      - « ai/... »     : fichier du disque (routes/ai_media.py), déjà copié avec les fichiers locaux ;
      - sinon          : IDENTIFIANT de la collection `files` (route serve_file, ex. <uuid>.pdf),
                         traduit en son `storage_path` (id = premier segment, sans extension).
    `fichiers` : {id: storage_path ou None si le fichier n'est que sur le disque}."""
    chemin = _normaliser_chemin(ref)
    if not chemin:
        return None, "vide"
    if chemin.startswith(f"{PREFIXE_STOCKAGE}/"):
        return chemin, "chemin"
    if chemin.startswith("ai/"):
        return None, "disque"
    segment = chemin.split("/", 1)[0]
    for ident in (segment.split(".", 1)[0], segment):
        if ident in fichiers:
            sp = _normaliser_chemin(fichiers[ident])
            return (sp, "traduit") if sp else (None, "disque")
    return None, "inconnu"


async def _chemins_emergent(references: Dict[tuple, str]) -> tuple:
    """Tous les chemins d'objets du stockage Emergent connus -> ({chemin: origine}, compteurs des ignorés).
    Sources : registre `stored_objects`, `files.storage_path`, puis les références relevées dans la base
    (« /api/files/... » traduites, « storage_path » gardées). Dédoublonnage sur la forme canonique."""
    chemins: Dict[str, str] = {}
    vus: set = set()
    ignores = {"disque": 0, "inconnu": 0}

    def ajouter(brut: Any, origine: str) -> None:
        c = _normaliser_chemin(brut)
        if c and _cle_canonique(c) not in vus:
            vus.add(_cle_canonique(c))
            chemins[c] = origine

    async for o in db.stored_objects.find({}, {"_id": 0, "storage_path": 1, "path": 1}):
        ajouter(o.get("storage_path") or o.get("path"), "stored_objects")
    # Identifiants des documents `files` (pour traduire /api/files/<id>) + leurs chemins de stockage
    fichiers: Dict[str, Optional[str]] = {}
    async for f in db.files.find({}, {"_id": 0, "id": 1, "storage_path": 1}):
        if f.get("id"):
            fichiers[str(f["id"])] = f.get("storage_path") or None
        if f.get("storage_path"):
            ajouter(f["storage_path"], "files.storage_path")
    for (genre, valeur), collection in sorted(references.items()):
        if genre == "stockage":
            ajouter(valeur, f"{collection} (storage_path)")
            continue
        chemin, motif = _traduire_reference(valeur, fichiers)
        if chemin:
            ajouter(chemin, f"{collection} (/api/files)")
        elif motif in ignores:
            ignores[motif] += 1
    return chemins, ignores


def _existe_dans_r2(r2, bucket: str, cle: str) -> bool:
    """Vrai si l'objet est déjà présent dans R2 (utilisé en reprise pour ne pas tout recopier)."""
    try:
        r2.head_object(Bucket=bucket, Key=cle)
        return True
    except Exception:  # noqa: BLE001
        return False


def _code_r2(exc: BaseException) -> Optional[int]:
    """Code HTTP renvoyé par R2 (botocore.ClientError le porte dans exc.response), sinon None."""
    reponse = getattr(exc, "response", None)
    return reponse.get("ResponseMetadata", {}).get("HTTPStatusCode") if isinstance(reponse, dict) else None


async def _copier_fichiers(job_id, cible, r2, prefixe, references, manifeste, reprise: bool = False) -> int:
    """Copie des fichiers locaux puis des objets Emergent vers R2, EN FLUX (jamais tout en mémoire).
    Renvoie le nombre de VRAIES erreurs (les absents à la source et les médias ignorés ne comptent pas)."""
    chemins, ignores = await _chemins_emergent(references)
    locaux: List[tuple] = []
    for dossier, sous in ((DOSSIER_UPLOADS, "uploads"), (DOSSIER_SNAPSHOTS, "snapshots")):
        if dossier.exists():
            locaux += [(f, f"{sous}/{f.relative_to(dossier).as_posix()}") for f in dossier.rglob("*") if f.is_file()]
    total = len(chemins) + len(locaux)
    ignorer_medias = not cible.copier_medias
    await _maj(job_id, f"Fichiers : {len(locaux)} fichier(s) locaux + {len(chemins)} objet(s) Emergent "
                       f"(références ignorées : {ignores['disque']} fichier(s) disque, "
                       f"{ignores['inconnu']} identifiant(s) inconnu(s))",
               etape="Fichiers", fichiers_total=total, references_ignorees=ignores)
    await _maj(job_id, "Médias (vidéos et sons) : " + ("ignorés (option décochée)" if ignorer_medias else "copiés"))
    echecs, absents, medias, faits, stockes = 0, 0, 0, 0, 0

    # Fichier en cours, lu par le signe de vie périodique. Les fils de lecture (octets reçus)
    # et d'envoi boto3 (octets envoyés) le mettent à jour pendant la copie.
    etat: Dict[str, Any] = {"fichier": None, "taille": None, "recus": 0, "envoyes": 0, "phase": None}
    # Arrêt demandé (vu par le signe de vie périodique) : transmis aux fils de lecture
    arret = threading.Event()
    boucle = asyncio.get_running_loop()

    def en_cours() -> Dict[str, Any]:
        """Avancement publié dans le suivi (champ `en_cours`)."""
        return {"fichier": (etat["fichier"] or "")[-80:], "faits": faits, "total": total, "taille": etat["taille"],
                "recus": etat["recus"], "envoyes": etat["envoyes"], "phase": etat["phase"]}

    async def veiller() -> None:
        """Signe de vie toutes les BATTEMENT_FICHIER s, même au milieu d'un long fichier."""
        while True:
            await asyncio.sleep(BATTEMENT_FICHIER)
            try:
                await _battement(job_id, en_cours(), force=True)
            except ArretDemande:
                arret.set()
                return
            except Exception as exc:  # noqa: BLE001 — une base momentanément injoignable n'arrête pas la copie
                logger.warning("[migration] signe de vie non publié : %s", exc)

    def debut_fichier(source: str) -> None:
        etat.update(fichier=source, taille=None, recus=0, envoyes=0, phase="lecture")

    def compter_envoi(octets: int) -> None:
        """Rappel de boto3 (depuis ses fils d'envoi) : octets envoyés à R2."""
        etat["phase"] = "envoi"
        etat["envoyes"] = (etat["envoyes"] or 0) + octets

    def annonceur(numero: int, source: str):
        """Ligne de journal « Fichier n/total » dès que la taille d'un objet Emergent est connue,
        s'il est gros ou de taille inconnue. Appelée depuis le fil de lecture."""
        def annoncer(taille: Optional[int]) -> None:
            if taille is None or taille > GROS_FICHIER:
                texte = _en_mo(taille) if taille is not None else "taille inconnue"
                asyncio.run_coroutine_threadsafe(_maj(job_id, f"Fichier {numero}/{total} : {source} ({texte})"),
                                                 boucle)
        return annoncer

    async def noter(ok: bool, source: str, cle: str, octets: int = 0, sha: str = "", erreur: str = "",
                    code: Optional[int] = None, cause: str = "", origine: str = "", essais: int = 1):
        """Enregistre le résultat d'un fichier : manifeste, compteurs, détail des échecs (suivi + base).
        Un média ignoré (option) est compté à part et n'apparaît ni dans les échecs ni dans leur export."""
        nonlocal echecs, absents, medias, faits, stockes
        faits += 1
        absent = not ok and cause == CAUSE_ABSENT
        media = not ok and cause == CAUSE_MEDIA
        manifeste["fichiers"].append({"source": source, "cle": cle, "ok": ok, "octets": octets, "sha256": sha,
                                      "erreur": erreur, "code": code, "cause": cause, "origine": origine,
                                      "essais": essais})
        compteur = ("fichiers_copies" if ok else "fichiers_medias_ignores" if media
                    else "fichiers_absents" if absent else "fichiers_echecs")
        champs: Dict[str, Any] = {"$inc": {compteur: 1}}
        if ok and octets:
            champs["$inc"]["octets_fichiers"] = octets
        if media:
            medias += 1
        elif not ok:
            # Regroupement par cause (et code HTTP) pour l'écran
            groupe = f"{cause} (HTTP {code})" if code else cause
            champs["$inc"][f"echecs_par_cause.{groupe}"] = 1
            detail = {"source": source, "erreur": erreur[:200], "code": code, "cause": cause, "origine": origine}
            if absent:
                absents += 1
                if absents <= ABSENTS_SUIVI_MAX:
                    champs["$push"] = {"absents_fichiers": detail}
            else:
                echecs += 1
                if echecs <= ECHECS_SUIVI_MAX:
                    champs["$push"] = {"echecs_fichiers": detail}
            # Tous les échecs (jusqu'à ECHECS_STOCKES_MAX) sont gardés pour l'export CSV
            if stockes < ECHECS_STOCKES_MAX:
                stockes += 1
                await db.migration_echecs.insert_one({**detail, "job_id": job_id, "cle": cle, "absent": absent,
                                                      "erreur": erreur[:1000], "essais": essais,
                                                      "date": _maintenant()})
        await db.migration_jobs.update_one({"id": job_id}, champs)
        await _battement(job_id, {**en_cours(), "fichier": source[-80:]})
        if faits % JOURNAL_TOUS_LES == 0:
            await _maj(job_id, f"  {faits}/{total} fichiers traités")

    async def a_sauter(source: str, cle: str, origine: str) -> bool:
        """Fichier à ne pas copier : arrêt demandé (lève ArretDemande), média ignoré par option,
        ou, en reprise, fichier déjà copié lors de la sauvegarde précédente (compté comme copié)."""
        if arret.is_set():
            raise ArretDemande()
        if ignorer_medias and _est_media(source):
            await noter(False, source, cle, cause=CAUSE_MEDIA, origine=origine)
            return True
        if reprise and await asyncio.to_thread(_existe_dans_r2, r2, cible.r2_bucket, cle):
            await noter(True, source, cle, erreur="déjà présent (reprise)", origine=origine)
            return True
        return False

    veille = asyncio.create_task(veiller())
    try:
        # 1) Fichiers locaux (rapides) : SHA-256 lu par morceaux, envoi direct depuis le disque
        for fichier, relatif in locaux:
            cle = f"{prefixe}/{relatif}"
            origine = f"disque ({relatif.split('/', 1)[0]})"
            if await a_sauter(str(fichier), cle, origine):
                continue
            debut_fichier(str(fichier))
            try:
                etat["taille"] = fichier.stat().st_size
                if etat["taille"] > GROS_FICHIER:
                    await _maj(job_id, f"Fichier {faits + 1}/{total} : {relatif} ({_en_mo(etat['taille'])})")
                sha, octets = await asyncio.to_thread(_sha256_fichier, fichier)
            except Exception as exc:  # noqa: BLE001
                await noter(False, str(fichier), cle, erreur=str(exc), cause="lecture disque", origine=origine)
                continue
            etat["phase"] = "envoi"
            try:
                await asyncio.to_thread(r2.upload_file, str(fichier), cible.r2_bucket, cle, Callback=compter_envoi)
                await noter(True, str(fichier), cle, octets, sha, origine=origine)
            except Exception as exc:  # noqa: BLE001
                await noter(False, str(fichier), cle, erreur=str(exc), code=_code_r2(exc), cause="écriture R2",
                            origine=origine)

        # 2) Objets Emergent : lecture en flux vers un fichier temporaire (supprimé ensuite),
        #    avec nouvelles tentatives et durée maximale, puis envoi à R2 (plusieurs parties si gros)
        for chemin, origine in chemins.items():
            cle = f"{prefixe}/objets/{chemin}"
            if await a_sauter(chemin, cle, origine):
                continue
            debut_fichier(chemin)
            with tempfile.TemporaryFile() as tmp:
                try:
                    type_mime, octets, sha, essais = await _lire_avec_essais(
                        chemin, tmp, etat, arret, annonceur(faits + 1, chemin), ignorer_medias)
                except MediaIgnore as exc:
                    # Sans extension reconnue, mais annoncé vidéo/son par le stockage : rien n'a été téléchargé
                    await noter(False, chemin, cle, erreur=f"type {exc}", cause=CAUSE_MEDIA, origine=origine)
                    continue
                except EchecLecture as exc:
                    await noter(False, chemin, cle, erreur=str(exc), code=exc.code, cause=exc.cause, origine=origine,
                                essais=exc.essais)
                    continue
                etat["phase"] = "envoi"
                tmp.seek(0)
                try:
                    await asyncio.to_thread(r2.upload_fileobj, tmp, cible.r2_bucket, cle,
                                            ExtraArgs={"ContentType": type_mime or "application/octet-stream"},
                                            Callback=compter_envoi)
                    await noter(True, chemin, cle, octets, sha, origine=origine, essais=essais)
                except Exception as exc:  # noqa: BLE001
                    await noter(False, chemin, cle, erreur=str(exc), code=_code_r2(exc), cause="écriture R2",
                                origine=origine, essais=essais)
    finally:
        veille.cancel()
        try:
            await veille
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    if ignorer_medias:
        await _maj(job_id, f"Médias : ignorés ({medias})")
    await _maj(job_id, f"Fichiers terminés : {faits - echecs - absents - medias} copié(s), {absents} absent(s) "
                       f"à la source (ignorés), {medias} média(s) ignoré(s) (option), {echecs} vraie(s) erreur(s)")
    return echecs


async def _sauver_secrets(job_id, cible, r2, prefixe) -> None:
    """Variables d'environnement du serveur -> fichier chiffré (R2 + téléchargement)."""
    valeurs = {n: os.environ[n] for n in ENV_A_SAUVER if os.environ.get(n)}
    enveloppe = _chiffrer(json.dumps(valeurs, ensure_ascii=False).encode(), cible.mot_de_passe_secrets)
    enveloppe.update({"cree_le": _maintenant(), "cles": sorted(valeurs)})  # noms en clair, valeurs chiffrées
    await asyncio.to_thread(r2.put_object, Bucket=cible.r2_bucket, Key=f"{prefixe}/secrets/env-secrets.enc.json",
                            Body=json.dumps(enveloppe, indent=1).encode(), ContentType="application/json")
    await _maj(job_id, f"Secrets : {len(valeurs)} variable(s) chiffrée(s) → {prefixe}/secrets/env-secrets.enc.json",
               secrets={"nombre": len(valeurs), "cles": sorted(valeurs)}, secrets_chiffres=enveloppe)
