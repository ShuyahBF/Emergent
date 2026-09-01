"""Iter108 backend tests — S164 (browser notifications flag), S158 (recurring
billing reminders), S159 (auto-suspend / auto-reactivate).
"""
import os
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _today():
    return datetime.now(timezone.utc).date()


def _iso(days_ago: int) -> str:
    return (_today() - timedelta(days=days_ago)).isoformat()


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(session):
    r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        pytest.fail(f"admin login failed {r.status_code}: {r.text[:300]}")
    data = r.json()
    otp = data.get("dev_otp")
    st = data.get("session_token")
    assert st, "session_token missing"
    assert otp, f"dev_otp missing in login response: {data}"
    r2 = session.post(f"{API}/auth/verify-otp", json={"session_token": st, "code": otp})
    if r2.status_code != 200:
        pytest.fail(f"verify-otp failed {r2.status_code}: {r2.text[:300]}")
    token = r2.json().get("access_token")
    assert token
    return token


@pytest.fixture(scope="module")
def admin(session, admin_token):
    session.headers.update({"Authorization": f"Bearer {admin_token}"})
    return session


# --------------------------------------------------------------------------
# S164 — public ui-flags
# --------------------------------------------------------------------------
class TestS164UiFlags:
    def test_ui_flags_exposes_browser_notifications_enabled(self, session):
        r = requests.get(f"{API}/public/ui-flags")
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "browser_notifications_enabled" in data
        assert isinstance(data["browser_notifications_enabled"], bool)
        assert data["browser_notifications_enabled"] is True, "default should be True"

    def test_toggle_flag_off_then_restore(self, admin):
        # Turn OFF
        r = admin.put(f"{API}/admin/settings", json={"browser_notifications_enabled": False})
        assert r.status_code == 200, r.text[:300]
        flags = requests.get(f"{API}/public/ui-flags").json()
        assert flags["browser_notifications_enabled"] is False
        # Restore
        r = admin.put(f"{API}/admin/settings", json={"browser_notifications_enabled": True})
        assert r.status_code == 200, r.text[:300]
        flags = requests.get(f"{API}/public/ui-flags").json()
        assert flags["browser_notifications_enabled"] is True


# --------------------------------------------------------------------------
# S158 — recurring billing reminders
# --------------------------------------------------------------------------
class TestS158BillingReminders:
    client_id = None
    email = "test_s158_billing@sawali-test.com"

    def test_01_create_client_monthly_billing(self, admin):
        # cleanup previous run
        lst = admin.get(f"{API}/admin/clients").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        for it in items:
            if it.get("email") == self.email:
                admin.delete(f"{API}/admin/clients/{it['id']}")
        payload = {
            "email": self.email,
            "full_name": "TEST_S158 Billing",
            "password": "Test@2026",
            "role": "client",
            "company": "TEST_S158_CO",
            "contract_billing_period": "monthly",
            "last_payment_at": _iso(28),
        }
        r = admin.post(f"{API}/admin/clients", json=payload)
        assert r.status_code in (200, 201), r.text[:500]
        body = r.json()
        cid = body.get("id") or (body.get("user") or {}).get("id")
        assert cid, body
        TestS158BillingReminders.client_id = cid
        # GET to verify persistence of the new field
        lst = admin.get(f"{API}/admin/clients").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        me = next((x for x in items if x.get("id") == cid), None)
        assert me is not None, "created client not returned by GET /admin/clients"
        assert me.get("contract_billing_period") == "monthly", me

    def test_02_run_billing_reminders(self, admin):
        assert TestS158BillingReminders.client_id, "client not created"
        r = admin.post(f"{API}/admin/billing-reminders/run", json={})
        assert r.status_code == 200, r.text[:500]
        data = r.json()
        assert "scanned" in data and "dispatched" in data, data
        # Iter109 — S158 must expose a `details` list.
        assert "details" in data, f"missing `details` key: {data}"
        assert isinstance(data["details"], list), data
        assert isinstance(data["scanned"], int)
        assert data["scanned"] >= 1, f"expected our test client to be scanned: {data}"
        assert data["dispatched"] >= 1, f"expected >=1 dispatched: {data}"

    def test_03_idempotent_second_run(self, admin):
        r = admin.post(f"{API}/admin/billing-reminders/run", json={})
        assert r.status_code == 200
        data = r.json()
        assert data["dispatched"] == 0, f"second run should dedupe: {data}"

    def test_04_update_billing_period_persists(self, admin):
        cid = TestS158BillingReminders.client_id
        r = admin.put(f"{API}/admin/clients/{cid}", json={"contract_billing_period": "quarterly"})
        assert r.status_code == 200, r.text[:400]
        lst = admin.get(f"{API}/admin/clients").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        me = next((x for x in items if x.get("id") == cid), None)
        assert me.get("contract_billing_period") == "quarterly", me

    def test_99_cleanup(self, admin):
        cid = TestS158BillingReminders.client_id
        if cid:
            r = admin.delete(f"{API}/admin/clients/{cid}")
            assert r.status_code in (200, 204, 404), r.text[:200]


# --------------------------------------------------------------------------
# S159 — auto-suspend + auto-reactivate
# --------------------------------------------------------------------------
class TestS159AutoSuspend:
    client_id = None
    email = "test_s159_suspend@sawali-test.com"
    password = "Test@2026"

    def test_01_create_client_with_auto_suspend(self, admin):
        lst = admin.get(f"{API}/admin/clients").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        for it in items:
            if it.get("email") == self.email:
                admin.delete(f"{API}/admin/clients/{it['id']}")
        payload = {
            "email": self.email,
            "full_name": "TEST_S159 Suspend",
            "password": self.password,
            "role": "client",
            "company": "TEST_S159_CO",
            "auto_suspend_after_overdue_days": 1,
            "contract_signed_at": _iso(30),
        }
        r = admin.post(f"{API}/admin/clients", json=payload)
        assert r.status_code in (200, 201), r.text[:500]
        body = r.json()
        cid = body.get("id") or (body.get("user") or {}).get("id")
        assert cid, body
        TestS159AutoSuspend.client_id = cid
        lst = admin.get(f"{API}/admin/clients").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        me = next((x for x in items if x.get("id") == cid), None)
        assert me is not None
        assert me.get("auto_suspend_after_overdue_days") == 1, me
        assert (me.get("account_status") or "active") == "active"

    def test_02_login_works_before_suspension(self):
        r = requests.post(f"{API}/auth/login", json={"email": self.email, "password": self.password})
        assert r.status_code == 200, f"pre-suspension login should work: {r.status_code} {r.text[:300]}"

    def test_03_run_overdue_suspends(self, admin):
        r = admin.post(f"{API}/admin/contract-overdue/run", json={})
        assert r.status_code == 200, r.text[:500]
        data = r.json()
        assert "suspended" in data, data
        assert "suspended_details" in data, data
        assert isinstance(data["suspended_details"], list)
        emails = [d.get("email") for d in data["suspended_details"]]
        assert self.email in emails, f"test client not in suspended_details: {data}"
        # Verify persisted status
        lst = admin.get(f"{API}/admin/clients").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        me = next((x for x in items if x.get("id") == TestS159AutoSuspend.client_id), None)
        assert me.get("account_status") == "suspended", me

    def test_04_login_blocked_403(self):
        r = requests.post(f"{API}/auth/login", json={"email": self.email, "password": self.password})
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:300]}"
        assert "Compte suspendu" in r.json().get("detail", ""), r.text[:300]

    def test_05_payment_reactivates(self, admin):
        cid = TestS159AutoSuspend.client_id
        r = admin.post(f"{API}/admin/clients/{cid}/payments", json={
            "payment_date": _today().isoformat(),
            "amount_paid": 50000,
            "send_confirmation": False,
            "invoice_ref": "TEST_S159_INV",
        })
        assert r.status_code in (200, 201), r.text[:500]
        lst = admin.get(f"{API}/admin/clients").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        me = next((x for x in items if x.get("id") == cid), None)
        assert me.get("account_status") == "active", f"auto-reactivation failed: {me}"

    def test_06_login_works_after_reactivation(self):
        r = requests.post(f"{API}/auth/login", json={"email": self.email, "password": self.password})
        assert r.status_code == 200, f"post-reactivation login failed: {r.status_code} {r.text[:300]}"

    def test_99_cleanup(self, admin):
        cid = TestS159AutoSuspend.client_id
        if cid:
            r = admin.delete(f"{API}/admin/clients/{cid}")
            assert r.status_code in (200, 204, 404), r.text[:200]


# --------------------------------------------------------------------------
# Iter109 — S159 auto-suspend gate independence from the ALERT threshold
# --------------------------------------------------------------------------
class TestS159SuspendGateIndependence:
    client_id = None
    email = "test_s159_gate@sawali-test.com"
    password = "Test@2026"

    def test_01_create_client_high_alert_low_suspend(self, admin):
        lst = admin.get(f"{API}/admin/clients").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        for it in items:
            if it.get("email") == self.email:
                admin.delete(f"{API}/admin/clients/{it['id']}")
        payload = {
            "email": self.email,
            "full_name": "TEST_S159 Gate",
            "password": self.password,
            "role": "client",
            "company": "TEST_S159_GATE_CO",
            "auto_suspend_after_overdue_days": 1,
            "contract_overdue_days": 99,
            "contract_signed_at": _iso(5),
        }
        r = admin.post(f"{API}/admin/clients", json=payload)
        assert r.status_code in (200, 201), r.text[:500]
        body = r.json()
        cid = body.get("id") or (body.get("user") or {}).get("id")
        assert cid, body
        TestS159SuspendGateIndependence.client_id = cid
        lst = admin.get(f"{API}/admin/clients").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        me = next((x for x in items if x.get("id") == cid), None)
        assert me is not None
        assert me.get("contract_overdue_days") == 99, me
        assert me.get("auto_suspend_after_overdue_days") == 1, me

    def test_02_run_overdue_suspends_despite_high_alert_threshold(self, admin):
        r = admin.post(f"{API}/admin/contract-overdue/run", json={})
        assert r.status_code == 200, r.text[:500]
        data = r.json()
        emails = [d.get("email") for d in (data.get("suspended_details") or [])]
        assert self.email in emails, (
            f"auto-suspend gated behind alert threshold: {data}"
        )
        lst = admin.get(f"{API}/admin/clients").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        me = next((x for x in items if x.get("id") == TestS159SuspendGateIndependence.client_id), None)
        assert me.get("account_status") == "suspended", me

    def test_99_cleanup(self, admin):
        cid = TestS159SuspendGateIndependence.client_id
        if cid:
            r = admin.delete(f"{API}/admin/clients/{cid}")
            assert r.status_code in (200, 204, 404), r.text[:200]


# --------------------------------------------------------------------------
# Iter107 — RDV participants + reminder_minutes, GCal manual sync
# --------------------------------------------------------------------------
class TestIter107Appointments:
    appt_id = None

    def test_01_create_appointment_with_participants(self, admin):
        # Pick the next weekday at 10:00 UTC to stay inside business hours.
        d = _today() + timedelta(days=3)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        when = datetime(d.year, d.month, d.day, 10, 0, tzinfo=timezone.utc).isoformat()
        payload = {
            "subject": "TEST_ITER107 RDV participants",
            "message": "test",
            "scheduled_at": when,
            "duration_min": 45,
            "participants": [
                {"name": "TEST Participant A", "phone": "+22670000001"},
                {"name": "TEST Participant B", "phone": "+22670000002"},
            ],
            "reminder_minutes": 60,
        }
        r = admin.post(f"{API}/me/appointments", json=payload)
        assert r.status_code in (200, 201), r.text[:500]
        body = r.json()
        aid = body.get("id") or (body.get("appointment") or {}).get("id")
        assert aid, body
        TestIter107Appointments.appt_id = aid

    def test_02_appointment_fields_persist(self, admin):
        r = admin.get(f"{API}/me/appointments")
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        me = next((x for x in items if x.get("id") == TestIter107Appointments.appt_id), None)
        assert me is not None, "created appointment not returned"
        assert me.get("reminder_minutes") == 60, me
        parts = me.get("participants") or []
        assert len(parts) == 2, f"participants not persisted: {me}"
        assert parts[0].get("phone") == "+22670000001", parts

    def test_03_gcal_sync_endpoint_requires_auth(self):
        r = requests.post(f"{API}/me/appointments/gcal-sync", json={})
        assert r.status_code in (401, 403), (
            f"SECURITY: /me/appointments/gcal-sync reachable without auth -> {r.status_code} {r.text[:200]}"
        )

    def test_04_gcal_sync_authenticated(self, admin):
        r = admin.post(f"{API}/me/appointments/gcal-sync", json={})
        assert r.status_code in (200, 400, 424, 503), r.text[:300]

    def test_05_participants_as_plain_strings_frontend_contract(self, admin):
        """Appointments.jsx sends `participants` as a list of phone STRINGS.
        The backend model declares List[Dict[str, Any]] — verify what happens."""
        d = _today() + timedelta(days=4)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        when = datetime(d.year, d.month, d.day, 11, 0, tzinfo=timezone.utc).isoformat()
        r = admin.post(f"{API}/me/appointments", json={
            "subject": "TEST_ITER107 RDV strings",
            "message": "test",
            "scheduled_at": when,
            "duration_min": 30,
            "participants": ["+22670000001", "+22670000002"],
            "reminder_minutes": 60,
        })
        assert r.status_code in (200, 201), (
            f"FRONTEND CONTRACT MISMATCH: participants as strings rejected -> "
            f"{r.status_code} {r.text[:400]}"
        )
        body = r.json()
        aid = body.get("id") or (body.get("appointment") or {}).get("id")
        if aid:
            TestIter107Appointments.appt_id_2 = aid


# --------------------------------------------------------------------------
# Regression — core admin endpoints reachable
# --------------------------------------------------------------------------
class TestRegression:
    def test_admin_me(self, admin):
        r = admin.get(f"{API}/auth/me")
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("email") == ADMIN_EMAIL

    def test_admin_clients_list(self, admin):
        r = admin.get(f"{API}/admin/clients")
        assert r.status_code == 200, r.text[:300]

    def test_endpoints_require_auth(self):
        for ep in ("/admin/billing-reminders/run", "/admin/contract-overdue/run"):
            r = requests.post(f"{API}{ep}", json={})
            assert r.status_code in (401, 403), f"{ep} unauthenticated -> {r.status_code}"
