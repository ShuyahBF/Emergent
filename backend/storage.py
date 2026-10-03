"""Stockage des fichiers de SAWALI dans Cloudflare R2 (lot 53 : indépendance d'Emergent).

Avant le lot 53, les fichiers (pièces OCR, médias, pièces jointes WhatsApp,
images IA…) partaient dans le stockage objet d'Emergent
(integrations.emergentagent.com/objstore, clé EMERGENT_LLM_KEY). Ils vont
désormais dans un bucket Cloudflare R2 (API S3, boto3), avec la MÊME interface
publique qu'avant :

  init_storage()                            -> None              (non bloquant)
  storage_available() / astorage_available() -> bool             (aucun appel réseau)
  upload_bytes(path, data, content_type)    -> str (chemin de stockage, « sawali/... »)
  fetch_bytes(path)                         -> (bytes, content_type)
  save_upload_and_cache(...) / rehydrate_from_storage(...) et leurs versions « a... » asynchrones

CONVENTION DES CLÉS R2 = celle de l'outil « Migration vers Render »
(routes/migration_render.py, lots 44 à 47), pour que les fichiers déjà copiés
d'Emergent vers R2 soient retrouvés SANS retraitement :

  objet du stockage Emergent  « <chemin> »   -> clé R2 « <R2_FICHIERS_PREFIXE>/objets/<chemin> »
  fichier du disque UPLOAD_DIR « <rel> »     -> clé R2 « <R2_FICHIERS_PREFIXE>/uploads/<rel> »
  fichier du disque SNAPSHOTS_DIR « <rel> »  -> clé R2 « <R2_FICHIERS_PREFIXE>/snapshots/<rel> »

  <chemin> est le chemin de stockage enregistré en base (`storage_path`,
  `stored_objects.storage_path`…), sans « / » initial, normalement préfixé par
  APP_STORAGE_NAME (« sawali/ »). La migration garde la forme rencontrée en base
  (avec ou sans « sawali/ ») : en lecture, on essaie les deux formes.
  R2_FICHIERS_PREFIXE = le préfixe de la sauvegarde de migration retenue
  (« migration-AAAAMMJJ-HHMMSS », affiché dans l'écran Migration et dans
  manifest.json). Les nouveaux fichiers sont écrits au même endroit.
  R2_FICHIERS_PREFIXES_SECONDAIRES (facultatif, séparés par des virgules) :
  préfixes d'autres sauvegardes de migration, consultés en lecture seulement.

Configuration (variables d'environnement, lues à chaque appel) :
  R2_FICHIERS_BUCKET               bucket (obligatoire pour activer R2)
  R2_FICHIERS_PREFIXE              préfixe de la migration (voir ci-dessus)
  R2_FICHIERS_ACCOUNT_ID / R2_FICHIERS_ACCESS_KEY_ID / R2_FICHIERS_SECRET_ACCESS_KEY
                                   à défaut R2_SAUVEGARDES_*, puis R2_STOCKS_* (même compte Cloudflare)
  R2_FICHIERS_ENDPOINT             (facultatif) point d'accès S3 ; par défaut
                                   https://<compte>.r2.cloudflarestorage.com

REPLI DE MIGRATION (paresseux) : un objet absent de R2 alors qu'EMERGENT_LLM_KEY
est encore définie est lu chez Emergent puis recopié dans R2 (même clé que la
migration). Sans EMERGENT_LLM_KEY, aucun appel à Emergent : jamais de blocage.
Les fonctions « Emergent » historiques (_ensure_ready, _storage_key, STORAGE_URL,
_normalize_path, _try_init, _reset_storage_key) restent ici : l'outil de
migration les utilise pour lire le stockage Emergent.

Lot 26 — NE JAMAIS BLOQUER LE SERVEUR : les routes utilisent les versions
asynchrones (a...), qui exécutent le travail réseau dans un thread.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("storage")

APP_NAME = os.environ.get("APP_STORAGE_NAME", "sawali")

# Objets absents du stockage : chemin -> heure du dernier échec (cache négatif)
_missing: Dict[str, float] = {}
_MISSING_TTL = 600.0


# ===========================================================================
# 1) Cloudflare R2 (stockage principal)
# ===========================================================================
_r2_lock = threading.Lock()
_r2_client = None
_r2_signature: Optional[tuple] = None


def _env(*noms: str) -> str:
    for nom in noms:
        v = (os.environ.get(nom) or "").strip()
        if v:
            return v
    return ""


def config_r2() -> Optional[Dict[str, str]]:
    """Configuration R2 des fichiers, ou None si elle est incomplète (aucun appel réseau)."""
    bucket = _env("R2_FICHIERS_BUCKET")
    compte = _env("R2_FICHIERS_ACCOUNT_ID", "R2_SAUVEGARDES_ACCOUNT_ID", "R2_STOCKS_ACCOUNT_ID")
    cle = _env("R2_FICHIERS_ACCESS_KEY_ID", "R2_SAUVEGARDES_ACCESS_KEY_ID", "R2_STOCKS_ACCESS_KEY_ID")
    secret = _env("R2_FICHIERS_SECRET_ACCESS_KEY", "R2_SAUVEGARDES_SECRET_ACCESS_KEY",
                  "R2_STOCKS_SECRET_ACCESS_KEY")
    endpoint = _env("R2_FICHIERS_ENDPOINT") or (f"https://{compte}.r2.cloudflarestorage.com" if compte else "")
    if not (bucket and cle and secret and endpoint):
        return None
    return {"bucket": bucket, "cle": cle, "secret": secret, "endpoint": endpoint,
            "prefixe": _env("R2_FICHIERS_PREFIXE").strip("/")}


def _prefixes_lecture(cfg: Dict[str, str]) -> List[str]:
    secondaires = [p.strip().strip("/") for p in _env("R2_FICHIERS_PREFIXES_SECONDAIRES").split(",")]
    return list(dict.fromkeys([cfg["prefixe"]] + [p for p in secondaires if p]))


def _nouveau_client_r2(cfg: Dict[str, str]):
    """Client S3 pointé sur R2 (fonction séparée pour pouvoir la simuler en test)."""
    import boto3
    from botocore.config import Config
    config = Config(connect_timeout=10, read_timeout=60, retries={"max_attempts": 3, "mode": "standard"})
    return boto3.client("s3", endpoint_url=cfg["endpoint"], aws_access_key_id=cfg["cle"],
                        aws_secret_access_key=cfg["secret"], region_name="auto", config=config)


def _client(cfg: Dict[str, str]):
    """Client R2 partagé (thread-safe), recréé si la configuration change."""
    global _r2_client, _r2_signature
    signature = (cfg["endpoint"], cfg["cle"], cfg["secret"])
    with _r2_lock:
        if _r2_client is None or _r2_signature != signature:
            _r2_client = _nouveau_client_r2(cfg)
            _r2_signature = signature
        return _r2_client


def _joindre(*morceaux: str) -> str:
    return "/".join(m.strip("/") for m in morceaux if m and m.strip("/"))


def _normalize_path(path: str) -> str:
    """Retire les « / » initiaux et ajoute le préfixe APP_NAME s'il manque (comme avant)."""
    p = (path or "").lstrip("/")
    if not p.startswith(f"{APP_NAME}/"):
        p = f"{APP_NAME}/{p}"
    return p


def cle_r2_ecriture(path: str, normaliser: bool = True, cfg: Optional[Dict[str, str]] = None) -> str:
    """Clé R2 où l'objet est écrit : « <prefixe>/objets/<chemin> » (convention de la migration)."""
    cfg = cfg or config_r2() or {"prefixe": _env("R2_FICHIERS_PREFIXE").strip("/")}
    chemin = _normalize_path(path) if normaliser else (path or "").lstrip("/")
    return _joindre(cfg["prefixe"], "objets", chemin)


def cles_r2_lecture(path: str, cfg: Optional[Dict[str, str]] = None) -> List[str]:
    """Clés R2 essayées en lecture : chemin tel quel, puis avec / sans le préfixe APP_NAME,
    dans le préfixe principal puis dans les préfixes secondaires."""
    cfg = cfg or config_r2() or {"prefixe": _env("R2_FICHIERS_PREFIXE").strip("/")}
    brut = (path or "").lstrip("/")
    formes = [brut, _normalize_path(brut)]
    if brut.startswith(f"{APP_NAME}/"):
        formes.append(brut[len(APP_NAME) + 1:])
    prefixes = _prefixes_lecture(cfg) if "bucket" in cfg else [cfg["prefixe"]]
    return list(dict.fromkeys(_joindre(p, "objets", f) for p in prefixes for f in formes if f))


def cles_r2_local(local_path) -> List[str]:
    """Clés R2 d'un fichier du disque copié par la migration (« <prefixe>/uploads/<rel> »)."""
    cfg = config_r2()
    if not cfg:
        return []
    try:
        from chemins import SNAPSHOTS_DIR, UPLOAD_DIR
    except Exception:  # noqa: BLE001
        return []
    chemin = Path(local_path).resolve()
    cles: List[str] = []
    for dossier, sous in ((UPLOAD_DIR, "uploads"), (SNAPSHOTS_DIR, "snapshots")):
        try:
            rel = chemin.relative_to(Path(dossier).resolve()).as_posix()
        except ValueError:
            continue
        cles += [_joindre(p, sous, rel) for p in _prefixes_lecture(cfg)]
    return cles


def _code_erreur(exc: BaseException) -> str:
    reponse = getattr(exc, "response", None) or {}
    return str((reponse.get("Error") or {}).get("Code") or (reponse.get("ResponseMetadata") or {}).get(
        "HTTPStatusCode") or "")


def _r2_lire(cfg: Dict[str, str], cle: str) -> Optional[Tuple[bytes, str]]:
    """(octets, type) ou None si l'objet n'existe pas ; lève pour toute autre erreur."""
    try:
        rep = _client(cfg).get_object(Bucket=cfg["bucket"], Key=cle)
    except Exception as exc:  # noqa: BLE001
        if _code_erreur(exc) in ("NoSuchKey", "404", "NotFound"):
            return None
        raise
    corps = rep["Body"]
    try:
        donnees = corps.read()
    finally:
        try:
            corps.close()
        except Exception:  # noqa: BLE001
            pass
    return donnees, rep.get("ContentType") or "application/octet-stream"


def _r2_ecrire(cfg: Dict[str, str], cle: str, data: bytes, content_type: str) -> None:
    _client(cfg).put_object(Bucket=cfg["bucket"], Key=cle, Body=data,
                            ContentType=content_type or "application/octet-stream")


def storage_available() -> bool:
    """True si R2 est configuré. NE BLOQUE JAMAIS (aucun appel réseau)."""
    return config_r2() is not None


async def astorage_available() -> bool:
    return storage_available()


def init_storage() -> None:
    """Point d'entrée du démarrage : note la configuration dans le journal (aucun appel réseau)."""
    cfg = config_r2()
    if cfg:
        logger.info("[storage] R2 actif : bucket %s, préfixe « %s »", cfg["bucket"], cfg["prefixe"])
        if not cfg["prefixe"]:
            logger.warning("[storage] R2_FICHIERS_PREFIXE vide : les fichiers migrés d'Emergent "
                           "(« migration-AAAAMMJJ-HHMMSS/objets/... ») ne seront pas retrouvés")
    else:
        logger.warning("[storage] R2 non configuré (R2_FICHIERS_BUCKET + identifiants) : "
                       "fichiers sur le disque local seulement")


def upload_bytes(path: str, data: bytes, content_type: str = "application/octet-stream",
                 normaliser: bool = True) -> str:
    """Envoi synchrone vers R2 ; lève en cas d'échec. Renvoie le chemin de stockage
    (« sawali/... »), à enregistrer en base comme avant."""
    cfg = config_r2()
    if not cfg:
        raise RuntimeError("Stockage R2 non configuré (R2_FICHIERS_BUCKET et identifiants R2)")
    chemin = _normalize_path(path) if normaliser else (path or "").lstrip("/")
    _r2_ecrire(cfg, cle_r2_ecriture(chemin, normaliser=False, cfg=cfg), data, content_type)
    _missing.pop(chemin, None)
    return chemin


def fetch_bytes(path: str) -> Tuple[bytes, str]:
    """Lecture synchrone -> (octets, type). R2 d'abord ; si absent et EMERGENT_LLM_KEY
    définie, lecture chez Emergent puis copie dans R2 (migration paresseuse).
    Lève FileNotFoundError si l'objet n'existe nulle part."""
    cfg = config_r2()
    if cfg:
        for cle in cles_r2_lecture(path, cfg):
            trouve = _r2_lire(cfg, cle)
            if trouve is not None:
                return trouve
    if _emergent_cle():
        donnees, ct = _emergent_fetch(path)
        if cfg and donnees:
            try:
                # Même clé que l'outil de migration : la prochaine lecture vient de R2
                _r2_ecrire(cfg, cle_r2_ecriture(path, normaliser=False, cfg=cfg), donnees, ct)
                logger.info("[storage] %s recopié d'Emergent vers R2", path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[storage] recopie vers R2 impossible pour %s : %s", path, exc)
        return donnees, ct
    if not cfg:
        raise RuntimeError("Stockage R2 non configuré (R2_FICHIERS_BUCKET et identifiants R2)")
    raise FileNotFoundError(f"Objet absent du stockage : {path}")


def _restaurer_local_depuis_r2(local_path: Path) -> bool:
    """Fichier du disque copié par la migration (uploads/, snapshots/) -> réécrit sur le disque."""
    cfg = config_r2()
    if not cfg:
        return False
    for cle in cles_r2_local(local_path):
        trouve = _r2_lire(cfg, cle)
        if trouve is not None:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            _write_local_bytes(local_path, trouve[0])
            return True
    return False


def restaurer_fichier_local(local_path) -> bool:
    """Fichier absent du disque (redéploiement Render) : recherché dans la copie de migration
    (« <prefixe>/uploads/<rel> »). True si le fichier a été restauré. Ne lève jamais."""
    local_path = Path(local_path)
    cle_cache = f"local:{local_path}"
    dernier = _missing.get(cle_cache)
    if dernier and time.time() - dernier < _MISSING_TTL:
        return False
    try:
        if _restaurer_local_depuis_r2(local_path):
            _missing.pop(cle_cache, None)
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[storage] restauration de %s impossible : %s", local_path, exc)
    _noter_absent(cle_cache)
    return False


def _noter_absent(cle: str) -> None:
    _missing[cle] = time.time()
    if len(_missing) > 5000:   # borne la mémoire du cache négatif
        _missing.clear()


def save_upload_and_cache(*, upload_dir, filename: str, data: bytes,
                          content_type: str = "application/octet-stream", remote_prefix: str = "files"):
    """Envoie `data` dans R2 ET l'écrit dans le cache disque local.
    Renvoie (chemin_local: Path, chemin_stockage: Optional[str], erreur: Optional[str]) ;
    R2 non configuré : disque seulement, sans erreur (comme avant sans stockage)."""
    upload_dir = Path(upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    local_path = upload_dir / filename
    storage_path = None
    storage_error = None
    if storage_available():
        try:
            storage_path = upload_bytes(f"{remote_prefix}/{filename}", data, content_type)
        except Exception as exc:  # noqa: BLE001
            storage_error = str(exc)[:300]
    _write_local_bytes(local_path, data)
    return local_path, storage_path, storage_error


def rehydrate_from_storage(*, local_path, remote_path: str) -> bool:
    """Récupère `remote_path` (R2, ou Emergent en repli) et l'écrit dans `local_path`.
    À défaut, cherche le fichier du disque copié par la migration. True si réussi ; ne lève jamais."""
    local_path = Path(local_path)
    last_miss = _missing.get(remote_path)
    if last_miss and time.time() - last_miss < _MISSING_TTL:
        return False
    try:
        data, _ct = fetch_bytes(remote_path)
        if data:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            _write_local_bytes(local_path, data)
            _missing.pop(remote_path, None)
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        if _restaurer_local_depuis_r2(local_path):
            _missing.pop(remote_path, None)
            return True
    except Exception:  # noqa: BLE001
        pass
    _noter_absent(remote_path)
    return False


async def aupload_bytes(path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    return await asyncio.to_thread(upload_bytes, path, data, content_type)


async def afetch_bytes(path: str) -> Tuple[bytes, str]:
    return await asyncio.to_thread(fetch_bytes, path)


async def asave_upload_and_cache(**kwargs):
    return await asyncio.to_thread(lambda: save_upload_and_cache(**kwargs))


async def arehydrate_from_storage(**kwargs) -> bool:
    return await asyncio.to_thread(lambda: rehydrate_from_storage(**kwargs))


async def arestaurer_fichier_local(local_path) -> bool:
    return await asyncio.to_thread(restaurer_fichier_local, local_path)


def _write_local_bytes(local_path, data: bytes) -> None:
    """Écrit `data` dans `local_path` (descripteur bas niveau, usage interne)."""
    fd = os.open(str(local_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


# ===========================================================================
# 2) Stockage Emergent historique : LECTURE seulement (migration et repli)
# ===========================================================================
STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")

_storage_key: Optional[str] = None
_storage_key_attempts: int = 0
_storage_key_last_attempt_ts: float = 0.0
_init_lock = threading.Lock()


def _emergent_cle() -> str:
    """Clé Emergent si elle est encore définie (repli de migration), sinon ""."""
    return (os.environ.get("EMERGENT_LLM_KEY") or EMERGENT_KEY or "").strip()


def _ensure_ready() -> bool:
    """Clé de stockage Emergent disponible, en l'obtenant si besoin (BLOQUANT : thread seulement)."""
    return bool(_emergent_cle()) and (_storage_key is not None or _locked_init())


def _locked_init() -> bool:
    with _init_lock:
        return _try_init()


def _try_init() -> bool:
    """Obtient la clé de stockage Emergent ; 60 s d'attente entre deux échecs."""
    global _storage_key, _storage_key_attempts, _storage_key_last_attempt_ts
    if _storage_key:
        return True
    cle = _emergent_cle()
    if not cle:
        return False
    now = time.time()
    if _storage_key_attempts > 0 and (now - _storage_key_last_attempt_ts) < 60:
        return False
    _storage_key_last_attempt_ts = now
    _storage_key_attempts += 1
    try:
        r = httpx.post(f"{STORAGE_URL}/init", json={"emergent_key": cle}, timeout=15)
        r.raise_for_status()
        _storage_key = r.json().get("storage_key")
        if _storage_key:
            logger.info("[storage] Emergent (lecture) : init OK (essai %s)", _storage_key_attempts)
            _storage_key_attempts = 0
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[storage] Emergent (lecture) : init impossible (essai %s) : %s",
                       _storage_key_attempts, exc)
    return False


def _reset_storage_key() -> None:
    global _storage_key
    _storage_key = None


def _emergent_fetch(path: str) -> Tuple[bytes, str]:
    """Lecture d'un objet chez Emergent (repli de migration). Lève en cas d'échec."""
    if not _ensure_ready() or not _storage_key:
        raise RuntimeError("Stockage Emergent indisponible")
    full_path = _normalize_path(path)
    r = httpx.get(f"{STORAGE_URL}/objects/{full_path}", headers={"X-Storage-Key": _storage_key}, timeout=60)
    if r.status_code == 403:
        _reset_storage_key()
        if _try_init() and _storage_key:
            r = httpx.get(f"{STORAGE_URL}/objects/{full_path}", headers={"X-Storage-Key": _storage_key},
                          timeout=60)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "application/octet-stream")
