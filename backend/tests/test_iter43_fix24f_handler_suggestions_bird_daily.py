"""Iter43-fix24f (2026-06) — Tests pour la page admin Handler Suggestions + Bird Cost Daily Series."""
import os
import uuid

import httpx
import pytest
from pymongo import MongoClient

API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "sawali_db")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sawalismartsystems.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@Sawali2026")


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_token():
    with httpx.Client(timeout=15) as client:
        r1 = client.post(
            f"{API_BASE}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        data1 = r1.json()
        if not data1.get("needs_otp"):
            return data1.get("access_token") or data1.get("token")
        sess = data1["session_token"]
        otp = data1.get("dev_otp")
        r2 = client.post(
            f"{API_BASE}/auth/verify-otp",
            json={"session_token": sess, "code": otp},
        )
        return r2.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


class TestHandlerSuggestions:
    def _insert(self, db, *, command, applied=False, notes=None):
        sid = uuid.uuid4().hex
        db.liluvine_handler_suggestions.insert_one({
            "id": sid,
            "command": command,
            "samples_count": 2,
            "generated_code": f"async def _build_{command}_reply(db, args):\n    return 'pytest'",
            "model": "claude-sonnet-4-5-20250929",
            "generated_by": "pytest@sawali.com",
            "generated_at": "2026-06-15T20:00:00+00:00",
            "applied": applied,
            "notes": notes,
        })
        return sid

    def test_list_empty(self, auth_headers, db):
        # cleanup
        db.liluvine_handler_suggestions.delete_many({"generated_by": "pytest@sawali.com"})
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{API_BASE}/admin/liluvine-pro/handler-suggestions", headers=auth_headers)
            assert r.status_code == 200
            data = r.json()
            # Vérifier qu'il n'y a pas de pytest dans la liste
            assert all(it.get("generated_by") != "pytest@sawali.com" for it in data.get("items", []))

    def test_create_and_list(self, auth_headers, db):
        db.liluvine_handler_suggestions.delete_many({"generated_by": "pytest@sawali.com"})
        sid1 = self._insert(db, command="aizenta")
        sid2 = self._insert(db, command="meteo", applied=True)
        with httpx.Client(timeout=10) as client:
            # All
            r = client.get(f"{API_BASE}/admin/liluvine-pro/handler-suggestions?limit=100", headers=auth_headers)
            data = r.json()
            ours = [it for it in data["items"] if it.get("generated_by") == "pytest@sawali.com"]
            assert len(ours) == 2
            # Filter by command
            r2 = client.get(f"{API_BASE}/admin/liluvine-pro/handler-suggestions?command=aizenta", headers=auth_headers)
            data2 = r2.json()
            ours2 = [it for it in data2["items"] if it.get("generated_by") == "pytest@sawali.com"]
            assert len(ours2) == 1
            assert ours2[0]["command"] == "aizenta"
            # Filter applied
            r3 = client.get(f"{API_BASE}/admin/liluvine-pro/handler-suggestions?applied=true", headers=auth_headers)
            data3 = r3.json()
            ours3 = [it for it in data3["items"] if it.get("generated_by") == "pytest@sawali.com"]
            assert len(ours3) == 1
            assert ours3[0]["command"] == "meteo"

    def test_patch_applied_and_notes(self, auth_headers, db):
        db.liluvine_handler_suggestions.delete_many({"generated_by": "pytest@sawali.com"})
        sid = self._insert(db, command="aizenta")
        with httpx.Client(timeout=10) as client:
            r = client.patch(
                f"{API_BASE}/admin/liluvine-pro/handler-suggestions/{sid}",
                headers=auth_headers,
                json={"applied": True, "notes": "Appliqué en prod"},
            )
            assert r.status_code == 200
            doc = db.liluvine_handler_suggestions.find_one({"id": sid})
            assert doc["applied"] is True
            assert doc["notes"] == "Appliqué en prod"
            assert doc.get("applied_at") is not None
            # Toggle off
            r2 = client.patch(
                f"{API_BASE}/admin/liluvine-pro/handler-suggestions/{sid}",
                headers=auth_headers,
                json={"applied": False},
            )
            assert r2.status_code == 200
            doc2 = db.liluvine_handler_suggestions.find_one({"id": sid})
            assert doc2["applied"] is False

    def test_delete(self, auth_headers, db):
        sid = self._insert(db, command="totodel")
        with httpx.Client(timeout=10) as client:
            r = client.delete(
                f"{API_BASE}/admin/liluvine-pro/handler-suggestions/{sid}",
                headers=auth_headers,
            )
            assert r.status_code == 200
            assert db.liluvine_handler_suggestions.find_one({"id": sid}) is None
            # 404 second time
            r2 = client.delete(
                f"{API_BASE}/admin/liluvine-pro/handler-suggestions/{sid}",
                headers=auth_headers,
            )
            assert r2.status_code == 404

    def test_patch_no_field_400(self, auth_headers, db):
        sid = self._insert(db, command="empty")
        with httpx.Client(timeout=10) as client:
            r = client.patch(
                f"{API_BASE}/admin/liluvine-pro/handler-suggestions/{sid}",
                headers=auth_headers,
                json={},
            )
            assert r.status_code == 400

    def test_cleanup(self, db):
        db.liluvine_handler_suggestions.delete_many({"generated_by": "pytest@sawali.com"})


class TestBirdCostDailySeries:
    def test_series_default_30(self, auth_headers):
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{API_BASE}/admin/bird/cost-daily-series", headers=auth_headers)
            assert r.status_code == 200
            data = r.json()
            assert data["days"] == 30
            assert len(data["series"]) == 30
            assert data["currency"] in ("XOF", "EUR", "USD")
            assert data["unit_cost"] > 0
            for entry in data["series"]:
                assert "date" in entry
                assert "count" in entry
                assert "cost" in entry
                assert len(entry["date"]) == 10  # YYYY-MM-DD

    def test_series_7_days(self, auth_headers):
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{API_BASE}/admin/bird/cost-daily-series?days=7", headers=auth_headers)
            assert r.status_code == 200
            data = r.json()
            assert data["days"] == 7
            assert len(data["series"]) == 7

    def test_series_invalid_days(self, auth_headers):
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{API_BASE}/admin/bird/cost-daily-series?days=0", headers=auth_headers)
            assert r.status_code == 422  # FastAPI validation error
            r2 = client.get(f"{API_BASE}/admin/bird/cost-daily-series?days=500", headers=auth_headers)
            assert r2.status_code == 422
