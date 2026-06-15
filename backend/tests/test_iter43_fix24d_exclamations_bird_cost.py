"""Iter43-fix24d (2026-06) — Tests pour la table `liluvine_exclamations`.

Vérifie :
- L'endpoint `/api/admin/liluvine-pro/wa-requests` lit `liluvine_exclamations`
- Une exclamation insérée dans la table est correctement listée
- Le filtre `only_unknown` ne retourne que les commandes non-supportées
- Le grouping par phone agrège correctement les exclamations
"""
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


def _insert_exclamation(db, *, command: str, phone: str = "+22670111222", text: str = None, known: bool = True):
    text = text or f"!{command} test args"
    digits = "".join(ch for ch in phone if ch.isdigit())
    doc = {
        "id": uuid.uuid4().hex,
        "channel": "whatsapp",
        "direction": "inbound",
        "from": phone,
        "phone_digits": digits,
        "body": text,
        "command": command.lower(),
        "command_args": text[len(f"!{command}"):].strip(),
        "from_profile_name": "Pytest Bot",
        "contact_id": None,
        "contact_name": "Pytest Contact",
        "client_id": None,
        "wa_message_id": f"wamid.PYT_{uuid.uuid4().hex[:10]}",
        "inbound_doc_id": uuid.uuid4().hex,
        "is_known_command": known,
        "handled": False,
        "reply": None,
        "created_at": "2026-06-15T19:30:00+00:00",
    }
    db.liluvine_exclamations.insert_one(doc)
    return doc


class TestExclamationsEndpoint:
    def test_empty_by_default(self, auth_headers, db):
        # Cleanup
        db.liluvine_exclamations.delete_many({"from_profile_name": "Pytest Bot"})
        with httpx.Client(timeout=10) as client:
            r = client.get(
                f"{API_BASE}/admin/liluvine-pro/wa-requests?search=PytestBot&limit=10",
                headers=auth_headers,
            )
            assert r.status_code == 200
            data = r.json()
            # Doit être vide pour notre marker
            assert data["count"] == 0
            assert data["items"] == []

    def test_known_command_listed(self, auth_headers, db):
        db.liluvine_exclamations.delete_many({"from_profile_name": "Pytest Bot"})
        _insert_exclamation(db, command="garde", known=True)
        _insert_exclamation(db, command="meteo", phone="+22670111222", text="!Meteo Ouaga", known=True)
        with httpx.Client(timeout=10) as client:
            r = client.get(
                f"{API_BASE}/admin/liluvine-pro/wa-requests?search=Pytest+Bot&limit=50&group_by_phone=true",
                headers=auth_headers,
            )
            assert r.status_code == 200
            data = r.json()
            assert data["grouped"] is True
            assert data["count"] >= 1
            # Le grouping par phone doit donner 1 entrée pour notre numéro
            ours = [it for it in data["items"] if it.get("profile_name") == "Pytest Bot"]
            assert len(ours) == 1
            assert ours[0]["request_count"] >= 2
            # Stats commands
            assert "garde" in ours[0]["commands"]
            assert "meteo" in ours[0]["commands"]
            # 0 unknown
            assert ours[0]["unknown_count"] == 0

    def test_only_unknown_filter(self, auth_headers, db):
        db.liluvine_exclamations.delete_many({"from_profile_name": "Pytest Bot"})
        _insert_exclamation(db, command="aizenta", known=False)
        _insert_exclamation(db, command="garde", known=True)
        with httpx.Client(timeout=10) as client:
            # Sans filtre : 2 messages
            r_all = client.get(
                f"{API_BASE}/admin/liluvine-pro/wa-requests?group_by_phone=false&search=Pytest&limit=50",
                headers=auth_headers,
            )
            items_all = r_all.json()["items"]
            assert len([i for i in items_all if i.get("from_profile_name") == "Pytest Bot"]) == 2
            # Avec only_unknown=true : seulement !aizenta
            r_unknown = client.get(
                f"{API_BASE}/admin/liluvine-pro/wa-requests?group_by_phone=false&only_unknown=true&search=Pytest&limit=50",
                headers=auth_headers,
            )
            items_un = r_unknown.json()["items"]
            ours_un = [i for i in items_un if i.get("from_profile_name") == "Pytest Bot"]
            assert len(ours_un) == 1
            assert ours_un[0]["command"] == "aizenta"
            assert ours_un[0]["is_known_command"] is False

    def test_cleanup(self, db):
        # Final cleanup
        n = db.liluvine_exclamations.delete_many({"from_profile_name": "Pytest Bot"}).deleted_count
        assert n >= 0


class TestBirdCostEndpoints:
    def test_admin_cost_summary(self, auth_headers):
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{API_BASE}/admin/bird/cost-summary", headers=auth_headers)
            assert r.status_code == 200
            data = r.json()
            for k in ("unit_cost", "currency", "today", "yesterday", "last_7_days", "last_30_days", "total"):
                assert k in data, f"Missing key: {k}"
            assert data["currency"] in ("XOF", "EUR", "USD")
            assert data["unit_cost"] > 0
            for window in ("today", "yesterday", "last_7_days", "last_30_days", "total"):
                assert "count" in data[window]
                assert "cost" in data[window]

    def test_me_inbox_bird_cost_today(self, auth_headers):
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{API_BASE}/me/inbox/bird-cost-today", headers=auth_headers)
            assert r.status_code == 200
            data = r.json()
            assert "enabled" in data
            if data["enabled"]:
                assert "count" in data
                assert "cost" in data
                assert "currency" in data
