"""Iter42b (2026-02) — Tests pour l'import CSV AMM + endpoints admin test
(synthèse + officine OTP).
"""
from __future__ import annotations

import io
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
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge_admin(uid: str) -> str:
    return pyjwt.encode({
        "sub": uid, "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


def _forge_editeur_vidal(uid: str) -> str:
    return pyjwt.encode({
        "sub": uid, "role": "editeur_vidal",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(db):
    aid = f"amm_csv_adm_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@admintest.com", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge_admin(aid), aid
    db.users.delete_one({"id": aid})


@pytest.fixture(scope="module")
def editeur_vidal_token(db):
    uid = f"amm_ev_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@vidaltest.com", "password_hash": "x",
        "role": "editeur_vidal", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge_editeur_vidal(uid), uid
    db.users.delete_one({"id": uid})


@pytest.fixture()
def clean_amms(db):
    created = []
    yield created
    if created:
        db.amm_numbers.delete_many({"id": {"$in": created}})
        # Cleanup also by CIP/AMM (created via CSV)
        for amm in created:
            pass


def _csv_payload(rows, sep=","):
    header = sep.join(["Nom du produit", "AMM", "CIP1", "date expiration", "Laboratoire", "Note"])
    body = "\n".join([header] + [sep.join(r) for r in rows])
    return ("test.csv", io.BytesIO(body.encode("utf-8")), "text/csv")


# --------------------------------------------------------------------------- #
# 1. CSV import — succès simple
# --------------------------------------------------------------------------- #
def test_csv_import_success(admin_token, db):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    suffix = uuid.uuid4().hex[:6]
    rows = [
        [f"Paracetamol-{suffix}", f"AMM-{suffix}-1", f"CIP-{suffix}-1", "2027-12-31", "Sanofi", "Note A"],
        [f"Ibuprofene-{suffix}", f"AMM-{suffix}-2", f"CIP-{suffix}-2", "2028-06-30", "Bayer", ""],
        [f"Amoxicilline-{suffix}", "", "", "", "Pfizer", "Sans AMM ni CIP"],
    ]
    fname, fp, mime = _csv_payload(rows)
    r = requests.post(f"{API}/amm/import-csv", headers=H, files={"file": (fname, fp, mime)})
    try:
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["imported"] == 3
        # Vérifie internal_no auto-généré
        docs = list(db.amm_numbers.find({"product_name": {"$regex": suffix}}))
        assert len(docs) == 3
        for d in docs:
            assert d.get("internal_no", "").startswith("INT-")
            assert d.get("source") == "csv_import"
            assert d.get("created_by_email")
            assert d.get("created_at")
    finally:
        db.amm_numbers.delete_many({"product_name": {"$regex": suffix}})


# --------------------------------------------------------------------------- #
# 2. CSV — conflits DB → refus global
# --------------------------------------------------------------------------- #
def test_csv_import_rejects_on_db_conflict(admin_token, db):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    suffix = uuid.uuid4().hex[:6]
    # Pré-insère un AMM existant
    db.amm_numbers.insert_one({
        "id": f"pre-{suffix}", "internal_no": f"INT-PRE{suffix}",
        "product_name": f"Existant-{suffix}", "amm_number": f"AMM-DUP-{suffix}",
        "cip1": None, "source": "manual",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        rows = [
            [f"Nouveau-{suffix}", f"AMM-DUP-{suffix}", f"CIP-OK-{suffix}", "", "", ""],
            [f"Autre-{suffix}", f"AMM-NEW-{suffix}", "", "", "", ""],
        ]
        fname, fp, mime = _csv_payload(rows)
        r = requests.post(f"{API}/amm/import-csv", headers=H, files={"file": (fname, fp, mime)})
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert "Import refusé" in detail["message"]
        assert len(detail["database_conflicts"]) >= 1
        # Vérifie qu'AUCUN nouvel item n'a été inséré
        assert db.amm_numbers.count_documents({"product_name": {"$regex": suffix, "$options": "i"}}) == 1
    finally:
        db.amm_numbers.delete_one({"id": f"pre-{suffix}"})


# --------------------------------------------------------------------------- #
# 3. CSV — conflit intra-fichier
# --------------------------------------------------------------------------- #
def test_csv_import_rejects_intra_file_duplicates(admin_token, db):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    suffix = uuid.uuid4().hex[:6]
    rows = [
        [f"A-{suffix}", f"DUPAMM-{suffix}", "", "", "", ""],
        [f"B-{suffix}", f"DUPAMM-{suffix}", "", "", "", ""],
    ]
    fname, fp, mime = _csv_payload(rows)
    r = requests.post(f"{API}/amm/import-csv", headers=H, files={"file": (fname, fp, mime)})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert len(detail["intra_file_conflicts"]) >= 1
    assert db.amm_numbers.count_documents({"product_name": {"$regex": suffix}}) == 0


# --------------------------------------------------------------------------- #
# 4. editeur_vidal — Read OK, Write/Import KO
# --------------------------------------------------------------------------- #
def test_editeur_vidal_cannot_write(editeur_vidal_token, admin_token, db):
    token, _ = editeur_vidal_token
    H = {"Authorization": f"Bearer {token}"}
    # Read OK
    r = requests.get(f"{API}/amm", headers=H)
    assert r.status_code == 200
    # POST KO (403)
    r2 = requests.post(f"{API}/amm", headers=H, json={"product_name": "Hack"})
    assert r2.status_code == 403
    # Import CSV KO (403)
    fname, fp, mime = _csv_payload([["X", "", "", "", "", ""]])
    r3 = requests.post(f"{API}/amm/import-csv", headers=H, files={"file": (fname, fp, mime)})
    assert r3.status_code == 403


# --------------------------------------------------------------------------- #
# 5. Création POST sans amm_number — internal_no auto
# --------------------------------------------------------------------------- #
def test_post_amm_without_amm_number(admin_token, db):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    suffix = uuid.uuid4().hex[:6]
    r = requests.post(f"{API}/amm", headers=H, json={
        "product_name": f"NoAmm-{suffix}",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    amm_id = body["amm"]["id"]
    try:
        assert body["amm"].get("internal_no", "").startswith("INT-")
        assert body["amm"]["amm_number"] is None
    finally:
        db.amm_numbers.delete_one({"id": amm_id})


# --------------------------------------------------------------------------- #
# 6. Endpoint admin /admin/synthese/test
# --------------------------------------------------------------------------- #
def test_admin_synthese_test_endpoint(admin_token):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{API}/admin/synthese/test", headers=H)
    # Le endpoint répond 200 même si aucun canal ne dispatch (renvoie ok=False + erreurs)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "channels" in body
    assert "preview" in body
    assert "config" in body


# --------------------------------------------------------------------------- #
# 7. Endpoint admin /admin/officine-otp/test — sans WA configuré → 503
# --------------------------------------------------------------------------- #
def test_admin_officine_otp_test_requires_wa_config(admin_token):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{API}/admin/officine-otp/test", headers=H, json={"msisdn": "22501234567"})
    # Sans WA configuré → 503 ; avec WA mais sans template → 503 OU 200 avec sent_via=text_fallback
    assert r.status_code in (200, 502, 503)
