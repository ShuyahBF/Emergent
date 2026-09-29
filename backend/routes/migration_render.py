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
         « /api/files/... » ou « storage_path » rencontrée dans la base ;
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
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import json
import logging
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

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
EXCLUES = {"migration_jobs", "migration_coffre"}
LOT = 500  # documents écrits par lot dans la base cible
JOURNAL_MAX = 300  # lignes de journal conservées dans le suivi
SILENCE_MAX = 180  # secondes sans signe de vie avant de déclarer la sauvegarde interrompue
BATTEMENT_MIN = 5  # secondes minimum entre deux mises à jour de l'avancement

# Références fortes vers les tâches en arrière-plan : sans elles, Python peut
# supprimer une tâche en cours d'exécution (asyncio ne garde qu'une référence faible).
_TACHES: set = set()


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
]

# Références à des fichiers du stockage Emergent trouvées dans les documents
RE_API_FILES = re.compile(r"/api/files/([A-Za-z0-9_\-./%~]+)")
RE_STORAGE_PATH = re.compile(r'"storage_path"\s*:\s*"([^"]+)"')

# Dossiers locaux copiés vers R2 (les chemins par défaut sont ceux d'Emergent)
_RACINE = Path(os.environ.get("APP_ROOT") or Path(__file__).resolve().parents[2])  # /app sur Emergent
DOSSIER_UPLOADS = Path(os.environ.get("UPLOAD_DIR") or _RACINE / "backend" / "uploads")
DOSSIER_SNAPSHOTS = _RACINE / "backend" / "snapshots"


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


def _lire_objet_emergent(chemin: str):
    """Lit un objet du stockage Emergent -> (octets, type MIME). Lève une exception si absent."""
    import storage as stockage_emergent
    return stockage_emergent.fetch_bytes(chemin)


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
    mongo_uri: str = Field(..., min_length=10, description="URI MongoDB Atlas de la nouvelle base")
    mongo_db: str = Field("sawali", min_length=1, max_length=60)
    remplacer: bool = False  # True : vide chaque collection cible avant copie (bascule finale)
    r2_account_id: str = Field(..., min_length=4)
    r2_access_key_id: str = Field(..., min_length=4)
    r2_secret_access_key: str = Field(..., min_length=4)
    r2_bucket: str = Field(..., min_length=3, max_length=63)
    copier_base: bool = True
    copier_fichiers: bool = True
    sauver_secrets: bool = True
    mot_de_passe_secrets: Optional[str] = Field(None, max_length=200)
    # Identifiant d'une sauvegarde INTERROMPUE ou en ÉCHEC à reprendre (sinon : nouvelle sauvegarde)
    reprendre: Optional[str] = Field(None, max_length=40)


def _age_secondes(horodatage: Optional[str]) -> float:
    """Secondes écoulées depuis un horodatage ISO (très grand si absent ou illisible)."""
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(horodatage)).total_seconds()
    except Exception:  # noqa: BLE001
        return float("inf")


async def _marquer_orphelines() -> None:
    """Sauvegardes « EN_COURS » sans signe de vie récent -> INTERROMPUE (serveur redémarré, tâche perdue)."""
    async for j in db.migration_jobs.find({"statut": "EN_COURS"}, {"_id": 0, "id": 1, "battement": 1, "debut": 1}):
        if _age_secondes(j.get("battement") or j.get("debut")) > SILENCE_MAX:
            ligne = f"{_maintenant()[11:19]} INTERROMPUE : plus de signe de vie depuis {SILENCE_MAX} s (serveur redémarré ?)"
            await db.migration_jobs.update_one(
                {"id": j["id"], "statut": "EN_COURS"},
                {"$set": {"statut": "INTERROMPUE", "etape": "Interrompue", "fin": _maintenant()},
                 "$push": {"journal": {"$each": [ligne], "$slice": -JOURNAL_MAX}}})


@router.post("/lancer", status_code=202)
async def lancer(cible: Cible, admin: dict = Depends(get_current_admin)):
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
    if cible.sauver_secrets and len(cible.mot_de_passe_secrets or "") < 12:
        raise HTTPException(400, "Mot de passe des secrets : 12 caractères minimum")
    if not (cible.copier_base or cible.copier_fichiers or cible.sauver_secrets):
        raise HTTPException(400, "Choisissez au moins un élément à sauvegarder")

    # Vérification des connexions AVANT de lancer quoi que ce soit
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
    job = {
        "id": job_id, "statut": "EN_COURS", "etape": "Démarrage", "debut": _maintenant(), "fin": None,
        "lance_par": admin.get("email", ""),
        # Description de la cible SANS identifiants
        "cible": {"mongo_hote": _hote(cible.mongo_uri), "mongo_db": cible.mongo_db, "remplacer": cible.remplacer,
                  "r2_bucket": cible.r2_bucket, "prefixe": prefixe},
        "options": {"base": cible.copier_base, "fichiers": cible.copier_fichiers, "secrets": cible.sauver_secrets},
        "collections_total": 0, "collections_faites": 0, "documents_copies": 0,
        "resultats_collections": [], "fichiers_total": 0, "fichiers_copies": 0, "fichiers_echecs": 0,
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
    return {"id": job_id, "prefixe": prefixe}


@router.post("/jobs/{job_id}/arreter")
async def arreter_job(job_id: str, _: dict = Depends(get_current_admin)):
    """Demande l'arrêt d'une sauvegarde en cours (prise en compte au lot suivant)."""
    job = await db.migration_jobs.find_one({"id": job_id}, {"_id": 0, "statut": 1, "battement": 1, "debut": 1})
    if not job:
        raise HTTPException(404, "Sauvegarde introuvable")
    if job["statut"] != "EN_COURS":
        return {"ok": True, "statut": job["statut"]}
    if _age_secondes(job.get("battement") or job.get("debut")) > SILENCE_MAX:
        # Tâche déjà morte : on la déclare interrompue tout de suite
        await _marquer_orphelines()
        return {"ok": True, "statut": "INTERROMPUE"}
    await db.migration_jobs.update_one({"id": job_id}, {"$set": {"arret_demande": True}})
    return {"ok": True, "statut": "ARRET_DEMANDE"}


@router.get("/jobs")
async def lister_jobs(_: dict = Depends(get_current_admin)):
    await _marquer_orphelines()
    return await db.migration_jobs.find({}, {"_id": 0, "secrets_chiffres": 0, "journal": 0,
                                               "resultats_collections": 0, "echecs_fichiers": 0}
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
    references: set = set()
    manifeste: Dict[str, Any] = {"prefixe": prefixe, "debut": _maintenant(), "collections": [], "fichiers": []}
    erreurs = 0
    try:
        if cible.copier_base:
            erreurs += await _copier_base(job_id, cible, client, r2, prefixe, references, manifeste,
                                          deja_faites or set())
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
            client.close()
        except Exception:  # noqa: BLE001
            pass


def _serialiser_lot(docs: List[dict]) -> tuple:
    """Lot de documents -> (octets EJSON, une ligne par document ; références de fichiers trouvées).
    Exécuté dans un fil séparé pour ne pas bloquer le site pendant la copie."""
    morceaux, refs = [], set()
    for doc in docs:
        ligne = json_util.dumps(doc, json_options=json_util.CANONICAL_JSON_OPTIONS, ensure_ascii=False)
        morceaux.append(ligne + "\n")
        # Références à des fichiers (pour l'étape Fichiers)
        if "/api/files/" in ligne:
            refs.update(RE_API_FILES.findall(ligne))
        if "storage_path" in ligne:
            refs.update(RE_STORAGE_PATH.findall(ligne))
    return "".join(morceaux).encode("utf-8"), refs


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
            lot_refs: List[dict] = []
            async for doc in src.find({}, batch_size=LOT):
                lot_refs.append(doc)
                if len(lot_refs) >= LOT:
                    references.update((await asyncio.to_thread(_serialiser_lot, lot_refs))[1])
                    lot_refs = []
                    await _battement(job_id, {"collection": nom, "copies": 0, "total": 0, "saut": True})
            if lot_refs:
                references.update((await asyncio.to_thread(_serialiser_lot, lot_refs))[1])
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
                    donnees, refs = await asyncio.to_thread(_serialiser_lot, docs)
                    await asyncio.to_thread(gz.write, donnees)
                    empreinte.update(donnees)
                    references.update(refs)
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
                                                            "$inc": {"collections_faites": 1, "documents_copies": copies}})
        await _maj(job_id, f"  {'✓' if ok else '✗'} {nom} : {n_source} → {n_cible}")
    await _maj(job_id, f"Base terminée : {total_docs} documents copiés, {anomalies} anomalie(s)")
    return anomalies


async def _chemins_emergent(references: set) -> List[str]:
    """Tous les chemins d'objets du stockage Emergent connus (registre + références trouvées)."""
    chemins = set()
    async for o in db.stored_objects.find({}, {"_id": 0, "storage_path": 1, "path": 1}):
        chemins.add(o.get("storage_path") or o.get("path"))
    async for f in db.files.find({"storage_path": {"$nin": [None, ""]}}, {"_id": 0, "storage_path": 1}):
        chemins.add(f["storage_path"])
    chemins.update(references)
    # Normalisation : pas de « / » initial, pas de paramètres d'URL
    propres = set()
    for c in chemins:
        if c and isinstance(c, str):
            propres.add(c.split("?")[0].split("#")[0].lstrip("/"))
    return sorted(propres)


def _existe_dans_r2(r2, bucket: str, cle: str) -> bool:
    """Vrai si l'objet est déjà présent dans R2 (utilisé en reprise pour ne pas tout recopier)."""
    try:
        r2.head_object(Bucket=bucket, Key=cle)
        return True
    except Exception:  # noqa: BLE001
        return False


async def _copier_fichiers(job_id, cible, r2, prefixe, references, manifeste, reprise: bool = False) -> int:
    """Copie des objets Emergent et des fichiers locaux vers R2. Renvoie le nombre d'échecs."""
    chemins = await _chemins_emergent(references)
    locaux: List[tuple] = []
    for dossier, sous in ((DOSSIER_UPLOADS, "uploads"), (DOSSIER_SNAPSHOTS, "snapshots")):
        if dossier.exists():
            locaux += [(f, f"{sous}/{f.relative_to(dossier).as_posix()}") for f in dossier.rglob("*") if f.is_file()]
    total = len(chemins) + len(locaux)
    await _maj(job_id, f"Fichiers : {len(chemins)} objet(s) Emergent + {len(locaux)} fichier(s) locaux",
               etape="Fichiers", fichiers_total=total)
    echecs, faits = 0, 0

    async def noter(ok: bool, source: str, cle: str, octets: int = 0, sha: str = "", erreur: str = ""):
        nonlocal echecs, faits
        faits += 1
        manifeste["fichiers"].append({"source": source, "cle": cle, "ok": ok, "octets": octets, "sha256": sha,
                                      "erreur": erreur})
        champs = {"$inc": {"fichiers_copies" if ok else "fichiers_echecs": 1}}
        if not ok:
            echecs += 1
            if echecs <= 500:
                champs["$push"] = {"echecs_fichiers": {"source": source, "erreur": erreur[:200]}}
        await db.migration_jobs.update_one({"id": job_id}, champs)
        await _battement(job_id, {"fichier": source[-80:], "faits": faits, "total": total})
        if faits % 100 == 0:
            await _maj(job_id, f"  {faits}/{total} fichiers traités")

    async def deja_dans_r2(source: str, cle: str) -> bool:
        """En reprise : fichier déjà copié lors de la sauvegarde précédente -> compté comme copié."""
        if reprise and await asyncio.to_thread(_existe_dans_r2, r2, cible.r2_bucket, cle):
            await noter(True, source, cle, erreur="déjà présent (reprise)")
            return True
        return False

    for chemin in chemins:
        cle = f"{prefixe}/objets/{chemin}"
        if await deja_dans_r2(chemin, cle):
            continue
        try:
            donnees, type_mime = await asyncio.to_thread(_lire_objet_emergent, chemin)
            await asyncio.to_thread(r2.put_object, Bucket=cible.r2_bucket, Key=cle, Body=donnees,
                                    ContentType=type_mime or "application/octet-stream")
            await noter(True, chemin, cle, len(donnees), hashlib.sha256(donnees).hexdigest())
        except Exception as exc:  # noqa: BLE001
            await noter(False, chemin, cle, erreur=str(exc))
    for fichier, relatif in locaux:
        cle = f"{prefixe}/{relatif}"
        if await deja_dans_r2(str(fichier), cle):
            continue
        try:
            donnees = await asyncio.to_thread(fichier.read_bytes)
            await asyncio.to_thread(r2.put_object, Bucket=cible.r2_bucket, Key=cle, Body=donnees)
            await noter(True, str(fichier), cle, len(donnees), hashlib.sha256(donnees).hexdigest())
        except Exception as exc:  # noqa: BLE001
            await noter(False, str(fichier), cle, erreur=str(exc))
    await _maj(job_id, f"Fichiers terminés : {faits - echecs} copié(s), {echecs} échec(s)")
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
