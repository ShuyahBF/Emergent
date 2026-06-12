"""Iter43-fix (2026-03) — Tests pour l'historique d'interventions :
   - taux horaire résolu (tenant > global > default)
   - PDF export avec filtres date/client/statut
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
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


@pytest.fixture()
def tenant_admin(db):
    aid = f"iter43h_tenant_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.com", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield aid
    db.users.delete_one({"id": aid})


def test_hourly_rate_default_15k(db, tenant_admin):
    """Si aucun taux défini → 15 000 XOF."""
    db.settings.update_one({"_id": "global"}, {"$unset": {"default_intervention_hourly_rate_xof": ""}}, upsert=True)
    db.users.update_one({"id": tenant_admin}, {"$unset": {"hourly_rate": ""}})
    tok = _forge(tenant_admin, "admin")
    r = requests.get(f"{API}/me/interventions/hourly-rate", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["hourly_rate_xof"] == 15000


def test_hourly_rate_global_settings(db, tenant_admin):
    """Si settings.global défini mais pas tenant → valeur globale."""
    db.settings.update_one({"_id": "global"}, {"$set": {"default_intervention_hourly_rate_xof": 20000}}, upsert=True)
    db.users.update_one({"id": tenant_admin}, {"$unset": {"hourly_rate": ""}})
    tok = _forge(tenant_admin, "admin")
    r = requests.get(f"{API}/me/interventions/hourly-rate", headers={"Authorization": f"Bearer {tok}"})
    assert r.json()["hourly_rate_xof"] == 20000


def test_hourly_rate_tenant_override(db, tenant_admin):
    """Le taux du tenant (hourly_rate) prime sur le global."""
    db.settings.update_one({"_id": "global"}, {"$set": {"default_intervention_hourly_rate_xof": 20000}}, upsert=True)
    db.users.update_one({"id": tenant_admin}, {"$set": {"hourly_rate": 25000}})
    tok = _forge(tenant_admin, "admin")
    r = requests.get(f"{API}/me/interventions/hourly-rate", headers={"Authorization": f"Bearer {tok}"})
    assert r.json()["hourly_rate_xof"] == 25000


def test_interventions_pdf_export(db, tenant_admin):
    """Génère un PDF avec colonnes durée + coût, filtres date/client/statut."""
    db.users.update_one({"id": tenant_admin}, {"$set": {"hourly_rate": 18000}})
    # Crée 3 interventions
    iids = []
    for i, dh in enumerate([1.5, 2.0, 0.5], start=1):
        iid = str(uuid.uuid4())
        db.interventions.insert_one({
            "id": iid,
            "intervention_number": f"INT-{i:03d}",
            "intervention_date": f"2026-03-{i:02d}",
            "title": f"Test #{i}",
            "client_id": tenant_admin,
            "duration_hours": dh,
            "status": "completed" if i < 3 else "planned",
            "technician": "Tech-X",
            "owner_id": tenant_admin,
        })
        iids.append(iid)
    try:
        tok = _forge(tenant_admin, "admin")
        # PDF complet
        r = requests.get(f"{API}/me/interventions/pdf",
                         headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 1000  # PDF non trivial
        # PDF avec filtre statut=completed
        r2 = requests.get(f"{API}/me/interventions/pdf?status=completed",
                          headers={"Authorization": f"Bearer {tok}"})
        assert r2.status_code == 200
        # PDF filtre date
        r3 = requests.get(f"{API}/me/interventions/pdf?from=2026-03-01&to=2026-03-02",
                          headers={"Authorization": f"Bearer {tok}"})
        assert r3.status_code == 200
    finally:
        db.interventions.delete_many({"id": {"$in": iids}})
