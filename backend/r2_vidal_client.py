"""Client Cloudflare R2 dédié au module VIDAL.

Portage de la décision prise côté `site-meetafrican` (voir
PORTAGE-SAWALI-VIDAL.md, section "Liluvine — requêtes produit par
WhatsApp") : les formules d'abonnement Liluvine VIDAL (essai, quotas,
formules jour/semaine/mois/trimestriel/annuel, numéros autorisés) sont
stockées en JSON sur R2, PAS dans MongoDB — demande explicite de
l'utilisateur, distincte du reste de sawali-portal qui utilise soit
MongoDB soit le stockage disque local (`UPLOAD_DIR`, `object_storage.py`).

Ce module N'EST utilisé QUE par `routes/liluvine_vidal_subscription.py`.
Il ne touche à aucune autre solution de stockage de l'application — c'est
un client S3-compatible autonome, séparé de `object_storage.py`, avec ses
propres identifiants (`R2_VIDAL_*`, distincts des `R2_*` génériques déjà
présents dans l'environnement pour un projet tiers sans rapport — voir
PORTAGE-SAWALI-VIDAL.md, "Bucket R2 dédié VIDAL").
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger("sawali.vidal.r2")

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    account_id = (os.environ.get("R2_VIDAL_ACCOUNT_ID") or "").strip()
    access_key = (os.environ.get("R2_VIDAL_ACCESS_KEY_ID") or "").strip()
    secret_key = (os.environ.get("R2_VIDAL_SECRET_ACCESS_KEY") or "").strip()
    if not account_id or not access_key or not secret_key:
        raise RuntimeError(
            "R2 VIDAL non configuré (R2_VIDAL_ACCOUNT_ID/ACCESS_KEY_ID/SECRET_ACCESS_KEY manquants)."
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
    return (os.environ.get("R2_VIDAL_BUCKET") or "vidal").strip()


def is_configured() -> bool:
    return bool(
        (os.environ.get("R2_VIDAL_ACCOUNT_ID") or "").strip()
        and (os.environ.get("R2_VIDAL_ACCESS_KEY_ID") or "").strip()
        and (os.environ.get("R2_VIDAL_SECRET_ACCESS_KEY") or "").strip()
    )


def get_json(key: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Lecture synchrone (boto3 est bloquant — appelé via `asyncio.to_thread`
    par les appelants, jamais directement dans une coroutine)."""
    try:
        obj = _get_client().get_object(Bucket=_bucket(), Key=key)
        raw = obj["Body"].read()
        return json.loads(raw.decode("utf-8"))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            return default if default is not None else {}
        logger.exception("[r2_vidal] get_json failed for key=%s", key)
        raise


def put_json(key: str, data: Dict[str, Any]) -> None:
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    _get_client().put_object(Bucket=_bucket(), Key=key, Body=body, ContentType="application/json")


def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Upload binaire générique (ex: PDF d'ordonnance anonymisé archivé pour
    le module Sécurisation — voir routes/vidal_ordonnance.py). Appelé via
    `asyncio.to_thread` par les appelants, jamais directement dans une
    coroutine (boto3 est bloquant)."""
    _get_client().put_object(Bucket=_bucket(), Key=key, Body=data, ContentType=content_type)


def list_keys(prefix: str) -> list[str]:
    keys: list[str] = []
    client = _get_client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=_bucket(), Prefix=prefix):
        for item in page.get("Contents", []):
            keys.append(item["Key"])
    return keys
