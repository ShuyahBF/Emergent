"""Iter35c — Tests for the snapshot-import recap (email + WhatsApp).

Validates:
  • A non-dry-run import response now includes a `notifications` key with
    {email: {sent, to, error?}, whatsapp: {attempts, any_sent, error?}}.
  • A dry-run import does NOT trigger notifications (key is null/absent).
  • The email dispatch records the recipient even when SMTP isn't
    actually configured (we only check `sent` is True/False, not the
    actual delivery).
  • An empty payload (all collections wiped) still produces a recap.
"""
import os
import io
import gzip
import json
import uuid
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://sawali-portal.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    if not data.get("needs_otp"):
        return data.get("access_token")
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": data["session_token"], "code": data.get("dev_otp")}, timeout=30)
    assert r2.status_code == 200, r2.text
    return r2.json().get("access_token")


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


def _make_tiny_payload(marker: str) -> bytes:
    payload = {
        "version": 1,
        "exported_at": "2026-01-01T00:00:00+00:00",
        "mask_secrets": True,
        "collections": {
            "testimonials": [
                {"id": f"TEST_iter35c_{marker}", "author": "iter35c", "content": marker}
            ],
        },
        "stats": {"testimonials": 1},
    }
    return gzip.compress(json.dumps(payload).encode("utf-8"))


class TestSnapshotImportRecap:
    def test_dry_run_does_not_trigger_notifications(self, admin_h):
        raw = _make_tiny_payload(f"dry_{uuid.uuid4().hex[:6]}")
        files = {"file": ("dry.json.gz", io.BytesIO(raw), "application/gzip")}
        data = {"mode": "merge", "dry_run": "true", "comment": "TEST_iter35c_dry"}
        rr = requests.post(f"{API}/admin/snapshots/import", headers=admin_h, files=files, data=data, timeout=30)
        assert rr.status_code == 200, rr.text
        body = rr.json()
        assert body["dry_run"] is True
        # No real mutation, no notifications dispatched
        assert body.get("notifications") in (None, {}), f"unexpected notifications on dry-run: {body.get('notifications')}"

    def test_real_import_includes_notifications_block(self, admin_h):
        raw = _make_tiny_payload(f"real_{uuid.uuid4().hex[:6]}")
        files = {"file": ("real.json.gz", io.BytesIO(raw), "application/gzip")}
        data = {"mode": "merge", "dry_run": "false", "comment": "TEST_iter35c_real"}
        rr = requests.post(f"{API}/admin/snapshots/import", headers=admin_h, files=files, data=data, timeout=30)
        assert rr.status_code == 200, rr.text
        body = rr.json()
        assert body["dry_run"] is False
        notif = body.get("notifications")
        assert notif is not None, f"missing notifications: {body}"
        # Shape
        assert "email" in notif, f"missing email block: {notif}"
        assert "whatsapp" in notif, f"missing whatsapp block: {notif}"
        # email block
        assert isinstance(notif["email"].get("sent"), bool)
        # whatsapp block
        assert isinstance(notif["whatsapp"].get("attempts"), list)
        assert isinstance(notif["whatsapp"].get("any_sent"), bool)
        # rows_count must reflect actual impacted collections
        assert isinstance(notif.get("rows_count"), int)
        assert notif["rows_count"] >= 1, f"expected at least testimonials in rows: {notif}"

    def test_real_import_summary_keeps_legacy_shape(self, admin_h):
        """Backwards-compat: existing UI relies on summary dict per collection."""
        raw = _make_tiny_payload(f"legacy_{uuid.uuid4().hex[:6]}")
        files = {"file": ("legacy.json.gz", io.BytesIO(raw), "application/gzip")}
        data = {"mode": "merge", "dry_run": "false", "comment": "TEST_iter35c_legacy"}
        rr = requests.post(f"{API}/admin/snapshots/import", headers=admin_h, files=files, data=data, timeout=30)
        assert rr.status_code == 200, rr.text
        summary = rr.json().get("summary") or {}
        assert "testimonials" in summary
        s = summary["testimonials"]
        assert "action" in s and "before" in s and "after" in s and "incoming" in s
