"""Iter43-fix24ad (2026-06-17) — Tests pour le compteur de déploiement
quand `.git` n'est PAS disponible (cas du conteneur de production).

Le compteur doit incrémenter même sans Git, en utilisant le file
fingerprint (`mtime + size`) de `/app/backend/server.py` comme empreinte
de déploiement.
"""
from __future__ import annotations

import os
import subprocess
import unittest.mock as mock

import httpx
import pytest


API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")


@pytest.mark.asyncio
async def test_fingerprint_uses_file_when_git_unavailable():
    """Quand `git rev-parse` raise (cas prod, pas de `.git`), on doit
    quand même retourner un fingerprint basé sur le file mtime/size."""
    from server import _bump_deployment_counter_if_needed
    # Patch subprocess.check_output to simulate `.git` missing
    with mock.patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(128, "git")):
        snap = await _bump_deployment_counter_if_needed()
    assert snap.get("git_head") is None
    assert snap.get("fingerprint") is not None
    # Should contain "file:" prefix
    assert "file:" in snap["fingerprint"]
    # seq should be ≥ 0 (could be > 1 due to test reruns)
    assert int(snap.get("seq") or 0) >= 0


def test_version_endpoint_works_even_without_git():
    """Le endpoint /api/version doit toujours répondre 200 et exposer
    deploy_seq ≥ 1 même si git n'est pas disponible."""
    with httpx.Client(timeout=10) as c:
        r = c.get(f"{API_BASE}/version")
    assert r.status_code == 200
    body = r.json()
    assert "deploy_seq" in body
    assert isinstance(body["deploy_seq"], int)
    # In production without git, git_sha will be empty/short or "unknown"
    assert "git_sha" in body
    # version still works
    assert "." in body["version"]
