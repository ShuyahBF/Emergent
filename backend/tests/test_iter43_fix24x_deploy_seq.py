"""Iter43-fix24x (2026-06-16) — Tests for the deployment sequence counter.

The `/api/version` endpoint must return a sequence number that increments
every time the git HEAD commit changes (i.e. a deploy). When called multiple
times with the same commit hash, the sequence must NOT increment.
"""
from __future__ import annotations

import os

import httpx
import pytest


API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")


def test_version_endpoint_returns_deploy_seq():
    """The /api/version endpoint exposes `deploy_seq` and a version string
    in the form `<major>.<seq>` (e.g. `1.3`)."""
    with httpx.Client(timeout=10) as c:
        r = c.get(f"{API_BASE}/version")
    assert r.status_code == 200
    body = r.json()
    assert "version" in body
    assert "deploy_seq" in body
    assert isinstance(body["deploy_seq"], int)
    # Version must be in format `X.Y` where Y == deploy_seq
    parts = body["version"].split(".")
    assert len(parts) == 2
    assert int(parts[1]) == body["deploy_seq"]


def test_version_endpoint_idempotent_same_commit():
    """Two consecutive calls on the same commit return the same deploy_seq.
    Bump should only happen when git HEAD changes."""
    with httpx.Client(timeout=10) as c:
        r1 = c.get(f"{API_BASE}/version")
        r2 = c.get(f"{API_BASE}/version")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["deploy_seq"] == r2.json()["deploy_seq"]


def test_version_endpoint_no_longer_v10():
    """Regression test — `v1.0` was the stale display before fix24x.
    After at least one deploy detection, the seq must be ≥ 1."""
    with httpx.Client(timeout=10) as c:
        r = c.get(f"{API_BASE}/version")
    body = r.json()
    assert body["deploy_seq"] >= 1, f"deploy_seq should be ≥ 1, got {body}"
    assert body["version"] != "1.0", f"Version should no longer be the stale '1.0' default, got {body['version']}"


def test_version_endpoint_exposes_git_sha():
    with httpx.Client(timeout=10) as c:
        r = c.get(f"{API_BASE}/version")
    body = r.json()
    assert "git_sha" in body
    # Should be a 7-char short hash (when git is available)
    sha = body["git_sha"]
    assert isinstance(sha, str)
    # Either 7 chars (valid hash) or "unknown" (fallback)
    assert len(sha) == 7 or sha == "unknown"
