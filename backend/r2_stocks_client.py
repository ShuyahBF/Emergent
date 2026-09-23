"""Client Cloudflare R2 dédié au module "Gestion Stocks" (Pharmacien suivi).

Portage du même choix déjà fait pour VIDAL (voir r2_vidal_client.py) : un
bucket R2 séparé, avec ses propres identifiants (`R2_STOCKS_*`), plutôt que
de réutiliser `object_storage.py` (stockage propriétaire Emergent) ou le
bucket VIDAL. Ce module N'EST utilisé QUE par `routes/gestion_stocks.py`.

Convention de clés : `{client_code}/{sous_dossier}/{nom_fichier}`, par
exemple `PMT/Inventaires/inventaire_2026-09.xlsx` — `client_code` est le
code court du tenant (voir `models.py::UserPublic.client_code`), permettant
un cloisonnement strict par client au sein d'un même bucket.
"""
from __future__ import annotations

import logging
import os
from typing import List

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger("sawali.gestion_stocks.r2")

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    account_id = (os.environ.get("R2_STOCKS_ACCOUNT_ID") or "").strip()
    access_key = (os.environ.get("R2_STOCKS_ACCESS_KEY_ID") or "").strip()
    secret_key = (os.environ.get("R2_STOCKS_SECRET_ACCESS_KEY") or "").strip()
    if not account_id or not access_key or not secret_key:
        raise RuntimeError(
            "R2 Gestion Stocks non configuré (R2_STOCKS_ACCOUNT_ID/ACCESS_KEY_ID/SECRET_ACCESS_KEY manquants)."
        )
    _client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=BotoConfig(signature_version="s3v4"),
    )
    return _client


def _bucket() -> str:
    return (os.environ.get("R2_STOCKS_BUCKET") or "gestion-stocks").strip()


def is_configured() -> bool:
    return bool(
        (os.environ.get("R2_STOCKS_ACCOUNT_ID") or "").strip()
        and (os.environ.get("R2_STOCKS_ACCESS_KEY_ID") or "").strip()
        and (os.environ.get("R2_STOCKS_SECRET_ACCESS_KEY") or "").strip()
    )


def list_objects(prefix: str) -> List[dict]:
    """Liste les objets sous `prefix` (non récursif au-delà — utilisé pour
    lister le contenu d'un seul sous-dossier). Appelé via `asyncio.to_thread`
    par les appelants (boto3 est bloquant)."""
    client = _get_client()
    objects: List[dict] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=_bucket(), Prefix=prefix):
        for item in page.get("Contents", []):
            if item["Key"].endswith("/"):
                continue  # marqueur de dossier vide, pas un vrai fichier
            objects.append({
                "key": item["Key"],
                "size": item["Size"],
                "last_modified": item["LastModified"].isoformat(),
            })
    return objects


def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    _get_client().put_object(Bucket=_bucket(), Key=key, Body=data, ContentType=content_type)


def get_presigned_url(key: str, expires_in: int = 300) -> str:
    """URL de lecture temporaire (GET), pour que le navigateur du pharmacien
    ouvre/télécharge le fichier directement depuis R2 sans passer par le
    backend. `expires_in` en secondes (défaut 5 min)."""
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=expires_in,
    )


def delete_object(key: str) -> None:
    try:
        _get_client().delete_object(Bucket=_bucket(), Key=key)
    except ClientError:
        logger.exception("[r2_stocks] delete_object failed for key=%s", key)
        raise
