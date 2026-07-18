"""Iter79 supplemental — verify 3 successive duplicates increment suffix
(copie), (copie 2), (copie 3). Regression for the re.escape fix in
routes/production.py:494.
"""
import os
from pathlib import Path
import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path("/app/frontend/.env"))
BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE}/api"

FAB = ("fab-analytics@sawali-test.com", "Analytics@2026")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("needs_otp"):
        return data.get("access_token")
    otp = data.get("dev_otp")
    r2 = requests.post(f"{API}/auth/verify-otp",
                       json={"session_token": data["session_token"], "code": otp}, timeout=30)
    r2.raise_for_status()
    return r2.json().get("access_token")


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_three_successive_duplicates_increment_suffix():
    tok = _login(*FAB)
    h = _h(tok)
    r = requests.get(f"{API}/production/recipes", headers=h, timeout=30)
    assert r.status_code == 200
    items = r.json().get("items") or []
    assert items, "no seed recipes"
    src = next((x for x in items if x.get("dosage_number")), items[0])
    rid = src["id"]
    original = src["name"]

    created = []
    try:
        for expected_suffix in ["(copie)", "(copie 2)", "(copie 3)"]:
            rr = requests.post(f"{API}/production/recipes/{rid}/duplicate", headers=h, timeout=30)
            assert rr.status_code == 200, rr.text
            d = rr.json()
            created.append(d["id"])
            assert d["name"].endswith(expected_suffix), (
                f"expected suffix {expected_suffix!r}, got name={d['name']!r} (source={original})"
            )
    finally:
        for cid in created:
            try:
                requests.delete(f"{API}/production/recipes/{cid}", headers=h, timeout=15)
            except Exception:
                pass
