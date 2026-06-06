"""Iter40 (2026-02) — Form categories (P1-8)."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge(uid: str, role: str = "admin") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def admin_token(db):
    aid = f"fc_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "company": f"FormCatCo {aid}", "client_code": f"FCC{aid[-4:].upper()}",
        "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(aid, "admin"), aid
    db.users.delete_one({"id": aid})
    db.form_categories.delete_many({"client_id": aid})
    db.forms.delete_many({"client_id": aid})


def test_first_category_is_default(admin_token):
    token, _ = admin_token
    r = requests.post(f"{API}/me/form-categories", json={"name": "Client"},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 201, r.text
    assert r.json()["is_default"] is True


def test_max_6_categories(admin_token):
    token, _ = admin_token
    for i in range(6):
        r = requests.post(f"{API}/me/form-categories", json={"name": f"Cat{i}"},
                          headers={"Authorization": f"Bearer {token}"}, timeout=10)
        assert r.status_code == 201, f"create {i}: {r.text}"
    # 7th rejected
    r = requests.post(f"{API}/me/form-categories", json={"name": "Cat7"},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 409
    assert "maximum" in r.json()["detail"].lower()


def test_duplicate_name_rejected(admin_token):
    token, _ = admin_token
    requests.post(f"{API}/me/form-categories", json={"name": "Maintenances"},
                  headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r = requests.post(f"{API}/me/form-categories", json={"name": "  maintenances  "},  # case-insensitive
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 409


def test_set_default_exclusive(admin_token):
    token, _ = admin_token
    rA = requests.post(f"{API}/me/form-categories", json={"name": "A", "is_default": True},
                       headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    rB = requests.post(f"{API}/me/form-categories", json={"name": "B"},
                       headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    requests.post(f"{API}/me/form-categories/{rB['id']}/set-default",
                  headers={"Authorization": f"Bearer {token}"}, timeout=10)
    cats = requests.get(f"{API}/me/form-categories",
                        headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    defaults = [c for c in cats if c["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == rB["id"]


def test_delete_promotes_next_default(admin_token):
    token, _ = admin_token
    rA = requests.post(f"{API}/me/form-categories", json={"name": "A"},
                       headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    rB = requests.post(f"{API}/me/form-categories", json={"name": "B"},
                       headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    # A is default. Delete it.
    r = requests.delete(f"{API}/me/form-categories/{rA['id']}",
                        headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    cats = requests.get(f"{API}/me/form-categories",
                        headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    assert len(cats) == 1
    assert cats[0]["id"] == rB["id"]
    assert cats[0]["is_default"] is True


def test_delete_detaches_forms(admin_token, db):
    token, aid = admin_token
    cat = requests.post(f"{API}/me/form-categories", json={"name": "ToDelete"},
                        headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    # Create a form with that category
    form = requests.post(f"{API}/me/forms",
                        json={"title": f"Form-{uuid.uuid4().hex[:6]}", "category_id": cat["id"]},
                        headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    assert form.get("category_id") == cat["id"]
    requests.delete(f"{API}/me/form-categories/{cat['id']}",
                    headers={"Authorization": f"Bearer {token}"}, timeout=10)
    # Form should remain but its category_id is now None
    refreshed = db.forms.find_one({"id": form["id"]})
    assert refreshed is not None
    assert refreshed.get("category_id") in (None, "")


def test_update_category(admin_token):
    token, _ = admin_token
    cat = requests.post(f"{API}/me/form-categories", json={"name": "Old"},
                        headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    r = requests.put(f"{API}/me/form-categories/{cat['id']}",
                     json={"name": "New", "color": "#ff0000"},
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "New"
    assert body["color"] == "#ff0000"


def test_form_create_with_category(admin_token):
    """Forms can be created with a category_id and it's persisted in the doc."""
    token, _ = admin_token
    cat = requests.post(f"{API}/me/form-categories", json={"name": "Suivi Logiciel"},
                        headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    r = requests.post(f"{API}/me/forms",
                     json={"title": f"Bug-{uuid.uuid4().hex[:6]}", "description": "Suivi panne",
                           "category_id": cat["id"]},
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, r.text
    form = r.json()
    assert form["category_id"] == cat["id"]


def test_form_update_changes_category(admin_token):
    token, _ = admin_token
    catA = requests.post(f"{API}/me/form-categories", json={"name": "A"},
                         headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    catB = requests.post(f"{API}/me/form-categories", json={"name": "B"},
                         headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    form = requests.post(f"{API}/me/forms", json={"title": f"F-{uuid.uuid4().hex[:6]}", "category_id": catA["id"]},
                         headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    r = requests.put(f"{API}/me/forms/{form['id']}", json={"category_id": catB["id"]},
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["category_id"] == catB["id"]
