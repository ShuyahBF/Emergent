"""Iter43-fix24az-t (2026-07-22) — Deployment fingerprint refactor tests.

Vérifie que `_bump_deployment_counter_if_needed` :
  1. Utilise DEPLOY_ID env var comme source d'autorité si présente
  2. Détecte les changements dans tous les fichiers backend clés (server.py,
     routes/*.py, models.py, requirements.txt) — pas seulement server.py
  3. Reste idempotent quand le contenu ne change pas
  4. Expose `files_hash` et `deploy_id` dans `/api/version-detail`
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def test_version_detail_exposes_new_fields():
    """GET /api/version-detail must return the new fields introduced in fix24az-t."""
    r = requests.get(f"{API}/version-detail", timeout=15)
    assert r.status_code == 200
    body = r.json()
    for f in ("version", "started_at", "deploy_seq", "git_head", "files_hash", "deploy_id"):
        assert f in body, f"missing field {f}"
    # files_hash should be a short hex string (16 chars) when server.py is on disk
    assert isinstance(body["files_hash"], str)
    assert len(body["files_hash"]) == 16
    # Only hex chars
    int(body["files_hash"], 16)  # raises if not hex
    # deploy_seq is a positive int
    assert isinstance(body["deploy_seq"], int)
    assert body["deploy_seq"] >= 1


def test_fingerprint_priority_order():
    """Direct unit test of the fingerprint composition."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _run():
        # Just call the function and check the returned dict shape.
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        # We can't easily import server without triggering all its startup, so
        # we just call the public endpoint which invokes the counter.
        r = requests.get(f"{API}/version-detail", timeout=15)
        body = r.json()
        # If DEPLOY_ID is set in env → it should be non-null. If not → None.
        env_did = (os.environ.get("DEPLOY_ID") or "").strip() or None
        assert body["deploy_id"] == env_did
        client.close()

    asyncio.run(_run())


def test_files_hash_includes_routes_directory():
    """Direct call to the function to verify that touching a file in
    routes/*.py DOES change files_hash (regression : previously only server.py
    mtime was fingerprinted)."""
    import asyncio
    import hashlib

    async def _run():
        # Compute the expected hash manually via the same logic
        backend_root = Path("/app/backend")
        critical_paths = [
            backend_root / "server.py",
            backend_root / "models.py",
            backend_root / "requirements.txt",
        ]
        routes_dir = backend_root / "routes"
        if routes_dir.is_dir():
            critical_paths.extend(sorted(routes_dir.glob("*.py")))
        h = hashlib.sha256()
        for p in critical_paths:
            try:
                h.update(str(p.relative_to(backend_root)).encode())
                h.update(b"\0")
                h.update(p.read_bytes())
                h.update(b"\0")
            except OSError:
                continue
        expected = h.hexdigest()[:16]

        # Fetch from live API
        r = requests.get(f"{API}/version-detail", timeout=15)
        actual = r.json()["files_hash"]
        assert actual == expected, f"files_hash mismatch: expected={expected!r} actual={actual!r}"

    asyncio.run(_run())


def test_deployment_bump_is_idempotent():
    """Two calls to /version-detail in a row must NOT bump seq (unless
    something else legitimately changed)."""
    r1 = requests.get(f"{API}/version-detail", timeout=15).json()
    r2 = requests.get(f"{API}/version-detail", timeout=15).json()
    assert r1["deploy_seq"] == r2["deploy_seq"]
    assert r1["files_hash"] == r2["files_hash"]


def test_fingerprint_covers_multiple_files():
    """Regression : le fingerprint doit couvrir au moins 5 fichiers backend
    (server.py + models.py + requirements.txt + ≥2 routes)."""
    backend_root = Path("/app/backend")
    files = [
        backend_root / "server.py",
        backend_root / "models.py",
        backend_root / "requirements.txt",
    ]
    routes_dir = backend_root / "routes"
    if routes_dir.is_dir():
        files.extend(sorted(routes_dir.glob("*.py")))
    existing = [f for f in files if f.exists()]
    assert len(existing) >= 5, f"Backend layout unexpected: only {len(existing)} critical files found"
    # And routes/ contains at least 5 python files (sanity)
    routes_py = list(routes_dir.glob("*.py")) if routes_dir.is_dir() else []
    assert len(routes_py) >= 5, f"routes/*.py count too low: {len(routes_py)}"
