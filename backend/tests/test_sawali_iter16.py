"""SAWALI — Iteration 16 backend tests: Unified CRM Timeline per client.

Endpoint: GET /api/admin/clients/{id}/timeline
Coverage:
 - Auth: 401 (no token), 403 (non-admin), 200 (admin).
 - Body shape: {client, events, counts, total}.
 - All 5 source collections surface events (appointment, intervention, whatsapp,
   form, document). Seeds 1 of each directly in pymongo for a fresh test client.
 - Events sorted by ts DESC (string ISO sort).
 - ?types=whatsapp filter → only whatsapp events; counts computed AFTER filter.
 - ?types=appointment,intervention filter.
 - ?limit=5 caps results.
 - Default limit is 200 (smoke: request without limit returns <=200).
 - 404 'Client introuvable' on unknown id.
"""
from __future__ import annotations

import os
import uuid
import datetime as dt
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"

_sync_mongo = MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_mongo[os.environ["DB_NAME"]]


# ---------- helpers -------------------------------------------------------
def _login(email: str, password: str):
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    r = sess.post(f"{BASE}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    d = r.json()
    if d.get("needs_otp"):
        assert d.get("dev_otp"), f"dev_otp expected, got {d}"
        r2 = sess.post(
            f"{BASE}/api/auth/verify-otp",
            json={"session_token": d["session_token"], "code": d["dev_otp"]},
        )
        assert r2.status_code == 200, r2.text
        return r2.json()["access_token"], r2.json()["user"]
    return d["access_token"], d["user"]


def _h(tok: str):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso(ts: dt.datetime) -> str:
    return ts.replace(microsecond=0).isoformat()


# ---------- fixtures ------------------------------------------------------
@pytest.fixture(scope="module")
def admin():
    tok, u = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert u["role"] == "admin"
    return tok, u


@pytest.fixture(scope="module")
def admin_h(admin):
    return _h(admin[0])


@pytest.fixture(scope="module")
def test_client(admin_h):
    """Create a fresh test client for timeline tests."""
    email = f"test_iter16_tl_{uuid.uuid4().hex[:6]}@example.org"
    pwd = "IterSixteen!2026"
    r = requests.post(
        f"{BASE}/api/admin/clients",
        headers=admin_h,
        json={
            "email": email,
            "full_name": "Iter16 Timeline Client",
            "company": "Iter16 Co",
            "password": pwd,
            "role": "client",
            "client_code": f"IT16{uuid.uuid4().hex[:3].upper()}",
        },
    )
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    tok, _ = _login(email, pwd)
    yield {"id": uid, "email": email, "token": tok}
    # Cleanup client and any leftover seed docs
    _sync_db.appointments.delete_many({"client_id": uid})
    _sync_db.interventions.delete_many({"client_id": uid})
    _sync_db.whatsapp_messages.delete_many({"client_id": uid})
    _sync_db.form_submissions.delete_many({"client_id": uid})
    _sync_db.documents.delete_many(
        {"$or": [{"client_id": uid}, {"owner_id": uid}, {"uploaded_by": uid}]}
    )
    requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)


@pytest.fixture(scope="module")
def seeded_events(test_client):
    """Seed 1 doc in each of the 5 source collections for the test client.

    Uses ascending ts so we can assert DESC ordering: document (latest) >
    form > whatsapp > intervention > appointment (earliest).
    Returns dict of ids keyed by type plus expected order.
    """
    uid = test_client["id"]
    now = dt.datetime.utcnow()
    # Spread 1h apart so sort is deterministic
    ts_appt = _iso(now - dt.timedelta(hours=5))
    ts_int = _iso(now - dt.timedelta(hours=4))
    ts_wa = _iso(now - dt.timedelta(hours=3))
    ts_form = _iso(now - dt.timedelta(hours=2))
    ts_doc = _iso(now - dt.timedelta(hours=1))

    ids = {
        "appointment": f"appt-iter16-{uuid.uuid4().hex[:6]}",
        "intervention": f"int-iter16-{uuid.uuid4().hex[:6]}",
        "whatsapp": f"wa-iter16-{uuid.uuid4().hex[:6]}",
        "form": f"sub-iter16-{uuid.uuid4().hex[:6]}",
        "document": f"doc-iter16-{uuid.uuid4().hex[:6]}",
        "form_def": f"form-iter16-{uuid.uuid4().hex[:6]}",
    }

    _sync_db.appointments.insert_one({
        "id": ids["appointment"],
        "client_id": uid,
        "subject": "RDV Iter16 test",
        "status": "planned",
        "scheduled_at": ts_appt,
        "duration_minutes": 45,
        "created_at": ts_appt,
    })
    _sync_db.interventions.insert_one({
        "id": ids["intervention"],
        "client_id": uid,
        "intervention_number": "INT-ITER16-001",
        "subject": "Support onsite",
        "title": "Support onsite",
        "type": "maintenance",
        "status": "completed",
        "intervention_date": ts_int,
        "created_at": ts_int,
    })
    _sync_db.whatsapp_messages.insert_one({
        "id": ids["whatsapp"],
        "client_id": uid,
        "to": "+33600000000",
        "template_name": "welcome_msg_iter16",
        "ok": True,
        "status": "sent",
        "recipient_label": "Iter16 Client",
        "automation_event": False,
        "bulk": False,
        "created_at": ts_wa,
    })
    # Seed a form definition so the resolver produces a nice title
    _sync_db.forms.insert_one({
        "id": ids["form_def"],
        "number": "F-ITER16",
        "title": "Iter16 Feedback",
        "created_at": ts_form,
    })
    _sync_db.form_submissions.insert_one({
        "id": ids["form"],
        "form_id": ids["form_def"],
        "client_id": uid,
        "user_label": "Iter16 Client",
        "anonymous": False,
        "respondent_email": test_client["email"],
        "created_at": ts_form,
    })
    _sync_db.documents.insert_one({
        "id": ids["document"],
        "client_id": uid,
        "name": "Iter16_doc.pdf",
        "category": "contract",
        "size": 123456,
        "uploaded_by_label": "Admin Iter16",
        "created_at": ts_doc,
    })

    yield {
        "ids": ids,
        "ts": {
            "appointment": ts_appt,
            "intervention": ts_int,
            "whatsapp": ts_wa,
            "form": ts_form,
            "document": ts_doc,
        },
    }

    # Explicit cleanup (also done by test_client teardown but be defensive)
    _sync_db.appointments.delete_one({"id": ids["appointment"]})
    _sync_db.interventions.delete_one({"id": ids["intervention"]})
    _sync_db.whatsapp_messages.delete_one({"id": ids["whatsapp"]})
    _sync_db.form_submissions.delete_one({"id": ids["form"]})
    _sync_db.forms.delete_one({"id": ids["form_def"]})
    _sync_db.documents.delete_one({"id": ids["document"]})


# ---------- tests ---------------------------------------------------------
class TestTimelineAuth:
    def test_401_no_token(self, test_client):
        r = requests.get(f"{BASE}/api/admin/clients/{test_client['id']}/timeline")
        assert r.status_code in (401, 403), r.text

    def test_403_non_admin(self, test_client):
        # test_client user token is a plain client
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/timeline",
            headers=_h(test_client["token"]),
        )
        assert r.status_code == 403, r.text

    def test_404_unknown_client(self, admin_h):
        r = requests.get(
            f"{BASE}/api/admin/clients/does-not-exist-xyz/timeline",
            headers=admin_h,
        )
        assert r.status_code == 404, r.text
        assert "introuvable" in (r.json().get("detail") or "").lower()


class TestTimelineShape:
    def test_body_shape_and_client_fields(self, admin_h, test_client, seeded_events):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/timeline",
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Top-level keys
        assert set(body.keys()) >= {"client", "events", "counts", "total"}
        # Client block
        c = body["client"]
        for k in [
            "id", "full_name", "company", "email", "phone",
            "client_code", "country", "city", "account_status", "created_at",
        ]:
            assert k in c, f"missing client.{k}"
        assert c["id"] == test_client["id"]
        assert c["full_name"] == "Iter16 Timeline Client"
        assert c["company"] == "Iter16 Co"
        # counts block: 5 known buckets
        assert set(body["counts"].keys()) >= {
            "appointment", "intervention", "whatsapp", "form", "document"
        }
        # total matches len(events)
        assert body["total"] == len(body["events"])

    def test_all_5_sources_present(self, admin_h, test_client, seeded_events):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/timeline",
            headers=admin_h,
        )
        assert r.status_code == 200
        body = r.json()
        types_found = {e["type"] for e in body["events"]}
        assert {"appointment", "intervention", "whatsapp", "form", "document"} <= types_found, (
            f"missing source types, got {types_found}"
        )
        # counts reflect at least 1 of each
        for t in ["appointment", "intervention", "whatsapp", "form", "document"]:
            assert body["counts"][t] >= 1, f"counts.{t} should be >=1"

    def test_event_content_includes_source_fields(self, admin_h, test_client, seeded_events):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/timeline",
            headers=admin_h,
        )
        body = r.json()
        by_type = {}
        for e in body["events"]:
            by_type.setdefault(e["type"], []).append(e)

        # Intervention title contains intervention_number
        ints = [e for e in by_type.get("intervention", []) if e["id"] == seeded_events["ids"]["intervention"]]
        assert ints, "seeded intervention not found in timeline"
        assert "INT-ITER16-001" in ints[0]["title"], ints[0]["title"]

        # WhatsApp title includes template_name
        was = [e for e in by_type.get("whatsapp", []) if e["id"] == seeded_events["ids"]["whatsapp"]]
        assert was, "seeded whatsapp not found"
        assert "welcome_msg_iter16" in was[0]["title"], was[0]["title"]
        assert was[0]["status"] == "ok"  # ok=True → status 'ok'

        # Appointment title = subject
        appts = [e for e in by_type.get("appointment", []) if e["id"] == seeded_events["ids"]["appointment"]]
        assert appts and "RDV Iter16 test" in appts[0]["title"]

        # Form title resolved via forms collection
        forms = [e for e in by_type.get("form", []) if e["id"] == seeded_events["ids"]["form"]]
        assert forms, "seeded form submission not found"
        assert "F-ITER16" in forms[0]["title"] or "Iter16 Feedback" in forms[0]["title"]

        # Document title = name
        docs = [e for e in by_type.get("document", []) if e["id"] == seeded_events["ids"]["document"]]
        assert docs, "seeded document not found"
        assert docs[0]["title"] == "Iter16_doc.pdf"

    def test_events_sorted_desc_by_ts(self, admin_h, test_client, seeded_events):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/timeline",
            headers=admin_h,
        )
        events = r.json()["events"]
        ts_list = [e.get("ts") or "" for e in events]
        assert ts_list == sorted(ts_list, reverse=True), "events not sorted DESC by ts"
        # Our seeded document was the most recent → first event should be our doc
        # (or another real doc with later ts; as long as first ts >= our doc ts)
        assert events[0]["ts"] >= seeded_events["ts"]["document"]


class TestTimelineFilters:
    def test_types_whatsapp_only(self, admin_h, test_client, seeded_events):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/timeline",
            headers=admin_h,
            params={"types": "whatsapp"},
        )
        assert r.status_code == 200
        body = r.json()
        assert all(e["type"] == "whatsapp" for e in body["events"]), (
            [e["type"] for e in body["events"]]
        )
        # counts computed AFTER filter
        assert body["counts"]["whatsapp"] == len(body["events"])
        assert body["counts"]["appointment"] == 0
        assert body["counts"]["intervention"] == 0
        assert body["counts"]["form"] == 0
        assert body["counts"]["document"] == 0

    def test_types_appt_and_intervention(self, admin_h, test_client, seeded_events):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/timeline",
            headers=admin_h,
            params={"types": "appointment,intervention"},
        )
        assert r.status_code == 200
        body = r.json()
        types = {e["type"] for e in body["events"]}
        assert types <= {"appointment", "intervention"}, types
        assert body["counts"]["whatsapp"] == 0
        assert body["counts"]["form"] == 0
        assert body["counts"]["document"] == 0


class TestTimelineLimit:
    def test_limit_caps_results(self, admin_h, test_client, seeded_events):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/timeline",
            headers=admin_h,
            params={"limit": 3},
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["events"]) <= 3
        assert body["total"] == len(body["events"])

    def test_default_limit_smoke(self, admin_h, test_client, seeded_events):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/timeline",
            headers=admin_h,
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["events"]) <= 200
