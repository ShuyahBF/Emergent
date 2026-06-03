"""S-iter47 — Admin toggle qdrant_image_auto_describe.

Verifies that PUT /api/admin/settings persists the boolean and GET returns it.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PWD = "Admin@Sawali2026"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PWD},
                      timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    if j.get("needs_otp"):
        otp = j.get("dev_otp")
        st = j.get("session_token")
        assert otp and st, f"dev_otp/session_token missing in login response: {j}"
        r = requests.post(f"{API}/auth/verify-otp",
                          json={"email": ADMIN_EMAIL, "session_token": st, "code": otp},
                          timeout=15)
        assert r.status_code == 200, r.text
        return r.json()["access_token"]
    return j["access_token"]


@pytest.fixture(scope="module")
def hdr(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def test_toggle_qdrant_image_auto_describe_false(hdr):
    # Set to false
    r = requests.put(f"{API}/admin/settings",
                     json={"qdrant_image_auto_describe": False},
                     headers=hdr, timeout=15)
    assert r.status_code == 200, r.text

    # Verify GET returns false
    r = requests.get(f"{API}/admin/settings", headers=hdr, timeout=15)
    assert r.status_code == 200
    assert r.json().get("qdrant_image_auto_describe") is False


def test_toggle_qdrant_image_auto_describe_true(hdr):
    # Set back to true
    r = requests.put(f"{API}/admin/settings",
                     json={"qdrant_image_auto_describe": True},
                     headers=hdr, timeout=15)
    assert r.status_code == 200, r.text

    r = requests.get(f"{API}/admin/settings", headers=hdr, timeout=15)
    assert r.status_code == 200
    assert r.json().get("qdrant_image_auto_describe") is True
