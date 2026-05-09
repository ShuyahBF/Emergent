"""Iter24 SAWALI backend tests — 4 final feedback points:

(A) Contact `unique_code` (YYYY-CODE-NNNN) generation, immutability, backfill
(B) `anon_company` flag — exposed in /admin/rgpd-preview + persisted via PUT
    /admin/clients/{id}/features + masking applied for non-privileged users
(C) `wa_sound_alerts` toggle — persisted + reflected in /me/features for tracked
    users (privileged users always see True)
(D) WhatsApp inbound webhook auto-fill of contact.name when blank or phone-only
"""
from __future__ import annotations

import os
import re
import time
import uuid
import asyncio
import bcrypt
import pytest
import requests
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "sawali_db")


# ---------- helpers ----------
def _login_with_otp(email: str, password: str) -> dict:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    data = r.json()
    code = data.get("dev_otp")
    assert code, f"dev_otp missing for {email}: {data}"
    v = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": data["session_token"], "code": code},
        timeout=15,
    )
    v.raise_for_status()
    return {"access_token": v.json()["access_token"], "user": v.json().get("user")}


@pytest.fixture(scope="session")
def admin_session():
    return _login_with_otp(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="session")
def admin_headers(admin_session):
    return {"Authorization": f"Bearer {admin_session['access_token']}"}


@pytest.fixture(scope="session")
def admin_user(admin_session):
    return admin_session["user"]


@pytest.fixture(scope="session")
def db(event_loop):
    client = AsyncIOMotorClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="session")
def tracked_user(admin_headers, admin_user, db, event_loop):
    """Provision a tracked-user (role=client) bridged via /admin/tracked-users + set-password.
    Also patch its bridged users row with `client_id` (in addition to the
    `parent_client_id` set by set-password) because /me/features and
    /me/contacts use the legacy `client_id` field to resolve the parent.
    """
    test_email = f"tracker_iter24_{uuid.uuid4().hex[:6]}@test.com"
    test_pwd = "Test1234!"
    create_payload = {
        "name": "Iter24 Tracker",
        "email": test_email,
        "role": "Consultation",
        "client_id": admin_user["id"],
        "status": "active",
    }
    cr = requests.post(f"{API}/admin/tracked-users", json=create_payload, headers=admin_headers, timeout=15)
    if not cr.ok:
        pytest.skip(f"Could not create tracked user: {cr.status_code} {cr.text}")
    tu_id = cr.json().get("id")
    sp = requests.post(
        f"{API}/admin/tracked-users/{tu_id}/set-password",
        json={"password": test_pwd},
        headers=admin_headers,
        timeout=15,
    )
    if not sp.ok:
        pytest.skip(f"set-password failed: {sp.status_code} {sp.text}")
    bridged_user_id = sp.json().get("user_id")

    # PATCH: set client_id on bridged users row so /me/features and /me/contacts
    # resolve to admin's parent client. (See critical_code_review_comments.)
    async def _patch():
        await db.users.update_one(
            {"id": bridged_user_id},
            {"$set": {"client_id": admin_user["id"]}},
        )
    event_loop.run_until_complete(_patch())

    yield {"id": tu_id, "user_id": bridged_user_id, "email": test_email, "password": test_pwd, "client_id": admin_user["id"]}
    requests.delete(f"{API}/admin/tracked-users/{tu_id}", headers=admin_headers, timeout=10)


@pytest.fixture(scope="session")
def tracked_headers(tracked_user):
    s = _login_with_otp(tracked_user["email"], tracked_user["password"])
    return {"Authorization": f"Bearer {s['access_token']}"}


# ============================================================
# (A) Contact unique_code
# ============================================================
class TestContactUniqueCode:
    """Unique code generation, sequencing, immutability, backfill."""

    def test_create_returns_unique_code_format(self, admin_headers):
        payload = {"name": f"TEST_iter24_{uuid.uuid4().hex[:6]}", "tags": ["test"], "shared": False}
        r = requests.post(f"{API}/me/contacts", json=payload, headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        c = r.json()
        uc = c.get("unique_code")
        assert uc, f"unique_code missing: {c}"
        # format YYYY-CODE-NNNN
        assert re.fullmatch(r"\d{4}-[A-Z0-9_]+-\d{4}", uc), f"bad format: {uc}"
        year = datetime.now(timezone.utc).year
        assert uc.startswith(f"{year}-"), uc
        # cleanup
        requests.delete(f"{API}/me/contacts/{c['id']}", headers=admin_headers, timeout=10)

    def test_sequential_increment(self, admin_headers):
        codes = []
        ids = []
        for i in range(2):
            p = {"name": f"TEST_iter24_seq_{i}_{uuid.uuid4().hex[:4]}", "tags": ["test"]}
            r = requests.post(f"{API}/me/contacts", json=p, headers=admin_headers, timeout=15)
            assert r.status_code == 200, r.text
            c = r.json()
            codes.append(c["unique_code"])
            ids.append(c["id"])
        # parse counters
        seq1 = int(codes[0].rsplit("-", 1)[-1])
        seq2 = int(codes[1].rsplit("-", 1)[-1])
        assert seq2 == seq1 + 1, f"non-incrementing: {codes}"
        # same client prefix
        assert codes[0].rsplit("-", 1)[0] == codes[1].rsplit("-", 1)[0]
        for cid in ids:
            requests.delete(f"{API}/me/contacts/{cid}", headers=admin_headers, timeout=10)

    def test_unique_code_immutable_via_put(self, admin_headers):
        p = {"name": f"TEST_iter24_imm_{uuid.uuid4().hex[:4]}", "tags": ["test"]}
        r = requests.post(f"{API}/me/contacts", json=p, headers=admin_headers, timeout=15)
        assert r.status_code == 200
        c = r.json()
        cid, original_uc = c["id"], c["unique_code"]
        # try to overwrite via PUT
        upd = requests.put(
            f"{API}/me/contacts/{cid}",
            json={"unique_code": "9999-HACK-9999", "name": c["name"]},
            headers=admin_headers,
            timeout=15,
        )
        assert upd.status_code == 200, upd.text
        # GET back
        lst = requests.get(f"{API}/me/contacts", headers=admin_headers, timeout=15).json()
        match = next((x for x in lst if x["id"] == cid), None)
        assert match, "contact disappeared after PUT"
        assert match["unique_code"] == original_uc, f"unique_code mutated: {match['unique_code']} != {original_uc}"
        requests.delete(f"{API}/me/contacts/{cid}", headers=admin_headers, timeout=10)

    def test_backfill_no_empty_unique_codes(self, admin_headers):
        lst = requests.get(f"{API}/me/contacts", headers=admin_headers, timeout=15).json()
        assert isinstance(lst, list)
        missing = [c for c in lst if not c.get("unique_code")]
        assert missing == [], f"contacts missing unique_code: {[c.get('id') for c in missing]}"


# ============================================================
# (B) anon_company flag
# ============================================================
class TestAnonCompany:
    def test_rgpd_preview_includes_anon_company(self, admin_headers, admin_user):
        r = requests.get(f"{API}/admin/rgpd-preview/{admin_user['id']}", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        flags = r.json().get("flags") or {}
        assert "anon_company" in flags, f"anon_company missing from flags: {flags}"

    def test_features_persists_anon_company(self, admin_headers, admin_user):
        # set true
        r1 = requests.put(
            f"{API}/admin/clients/{admin_user['id']}/features",
            json={"anon_company": True},
            headers=admin_headers,
            timeout=15,
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()["features"]["anon_company"] is True
        # GET
        g = requests.get(f"{API}/admin/clients/{admin_user['id']}/features", headers=admin_headers, timeout=15)
        assert g.json()["features"]["anon_company"] is True
        # reset
        requests.put(
            f"{API}/admin/clients/{admin_user['id']}/features",
            json={"anon_company": False},
            headers=admin_headers,
            timeout=15,
        )

    def test_anon_company_masks_for_tracked_user(self, admin_headers, admin_user, tracked_headers):
        # 1. create a contact w/ a known company name as admin
        cname = f"TEST_iter24_co_{uuid.uuid4().hex[:4]}"
        cp = {"name": cname, "company": "Jean Dupont SARL", "tags": ["test"], "shared": True}
        cr = requests.post(f"{API}/me/contacts", json=cp, headers=admin_headers, timeout=15)
        assert cr.status_code == 200
        cid = cr.json()["id"]
        try:
            # 2. enable anon_company
            requests.put(
                f"{API}/admin/clients/{admin_user['id']}/features",
                json={"anon_company": True},
                headers=admin_headers,
                timeout=15,
            )
            # 3. tracked user lists contacts
            tlst = requests.get(f"{API}/me/contacts", headers=tracked_headers, timeout=15).json()
            match = next((x for x in tlst if x["id"] == cid), None)
            assert match, f"shared contact not visible to tracked user: ids={[x.get('id') for x in tlst]}"
            assert match.get("company") != "Jean Dupont SARL", "company NOT masked"
            assert "*" in (match.get("company") or ""), f"expected mask in company, got {match.get('company')}"
            # 4. admin sees raw
            alst = requests.get(f"{API}/me/contacts", headers=admin_headers, timeout=15).json()
            am = next((x for x in alst if x["id"] == cid), None)
            assert am and am.get("company") == "Jean Dupont SARL", f"admin saw masked: {am}"
        finally:
            requests.put(
                f"{API}/admin/clients/{admin_user['id']}/features",
                json={"anon_company": False},
                headers=admin_headers,
                timeout=15,
            )
            requests.delete(f"{API}/me/contacts/{cid}", headers=admin_headers, timeout=10)


# ============================================================
# (C) wa_sound_alerts toggle
# ============================================================
class TestWaSoundAlerts:
    def test_toggle_persists_and_tracked_user_sees_false(self, admin_headers, admin_user, tracked_headers):
        # set false
        r = requests.put(
            f"{API}/admin/clients/{admin_user['id']}/features",
            json={"wa_sound_alerts": False},
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["features"]["wa_sound_alerts"] is False
        try:
            # tracked user features should reflect false
            tf = requests.get(f"{API}/me/features", headers=tracked_headers, timeout=15)
            assert tf.status_code == 200, tf.text
            feats = tf.json()["features"]
            assert feats.get("wa_sound_alerts") is False, f"tracked user sees: {feats.get('wa_sound_alerts')}"
            # admin features always True
            af = requests.get(f"{API}/me/features", headers=admin_headers, timeout=15).json()
            assert af["features"]["wa_sound_alerts"] is True, "admin should always see True"
        finally:
            requests.put(
                f"{API}/admin/clients/{admin_user['id']}/features",
                json={"wa_sound_alerts": True},
                headers=admin_headers,
                timeout=15,
            )


# ============================================================
# (D) WhatsApp webhook auto-fill of contact.name
# ============================================================
class TestWhatsAppAutoFill:
    @staticmethod
    def _post_webhook(wa_id: str, profile_name: str):
        body = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [{"wa_id": wa_id, "profile": {"name": profile_name}}],
                                "messages": [
                                    {
                                        "from": wa_id,
                                        "id": f"wamid.iter24.{uuid.uuid4().hex[:8]}",
                                        "timestamp": str(int(time.time())),
                                        "type": "text",
                                        "text": {"body": "hello iter24"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        return requests.post(f"{API}/whatsapp/webhook", json=body, timeout=15)

    def test_autofill_when_name_is_phone(self, admin_headers):
        # unique digits
        wa_id = "22501020" + str(int(time.time()))[-3:]
        # create contact whose name == phone
        cp = {"name": wa_id, "whatsapp": wa_id, "tags": ["test"]}
        cr = requests.post(f"{API}/me/contacts", json=cp, headers=admin_headers, timeout=15)
        assert cr.status_code == 200
        cid = cr.json()["id"]
        try:
            # webhook
            wr = self._post_webhook(wa_id, "Auto Synced Name")
            assert wr.status_code in (200, 204), wr.text
            time.sleep(1.0)
            lst = requests.get(f"{API}/me/contacts", headers=admin_headers, timeout=15).json()
            match = next((x for x in lst if x["id"] == cid), None)
            assert match
            assert match["name"] == "Auto Synced Name", f"name not updated: {match['name']}"
            assert match.get("wa_profile_name") == "Auto Synced Name"
        finally:
            requests.delete(f"{API}/me/contacts/{cid}", headers=admin_headers, timeout=10)

    def test_no_overwrite_when_real_name(self, admin_headers):
        wa_id = "22502020" + str(int(time.time()))[-3:]
        cp = {"name": "Existing Real", "whatsapp": wa_id, "tags": ["test"]}
        cr = requests.post(f"{API}/me/contacts", json=cp, headers=admin_headers, timeout=15)
        assert cr.status_code == 200
        cid = cr.json()["id"]
        try:
            wr = self._post_webhook(wa_id, "Webhook Should Not Win")
            assert wr.status_code in (200, 204)
            time.sleep(1.0)
            lst = requests.get(f"{API}/me/contacts", headers=admin_headers, timeout=15).json()
            match = next((x for x in lst if x["id"] == cid), None)
            assert match
            assert match["name"] == "Existing Real", f"real name overwritten: {match['name']}"
            # but wa_profile_name should be set
            assert match.get("wa_profile_name") == "Webhook Should Not Win"
        finally:
            requests.delete(f"{API}/me/contacts/{cid}", headers=admin_headers, timeout=10)
