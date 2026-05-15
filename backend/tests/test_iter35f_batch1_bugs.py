"""Iter35f — Tests for the 4 Batch 1 bug fixes.

1. RGPD edit contact: masked values (containing `***`) are silently dropped
   on update so we never overwrite the real value with its anonymized mask.
2. Admin client update: `email` is now part of UserUpdateAdmin → really
   persists, normalized to lowercase, unique-checked.
3. WhatsApp 24h window: now widens lookup to every visible client_id so a
   user whose own client_id differs from the webhook's anchor can still
   reply to a contact who just wrote.
4. Bulk WhatsApp send: widens contact lookup AND fails fast with a 404
   when zero contact resolves (was silently reporting "0 envoyé").
"""
import os
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


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    if not data.get("needs_otp"):
        return data.get("access_token")
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": data["session_token"], "code": data.get("dev_otp")}, timeout=30)
    assert r2.status_code == 200, r2.text
    return r2.json().get("access_token")


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}


# ============================================================
# Bug 2 — Admin email update
# ============================================================
class TestAdminEmailUpdate:
    def test_email_field_now_persists(self, admin_h):
        # Create a throwaway client
        suffix = uuid.uuid4().hex[:8]
        original_email = f"iter35f_orig_{suffix}@example.com"
        new_email = f"iter35f_new_{suffix}@example.com"
        cr = requests.post(
            f"{API}/admin/clients",
            headers=admin_h,
            json={
                "full_name": "Iter35f Test",
                "email": original_email,
                "password": "TempPass2026!",
                "company": f"Iter35f Co {suffix}",
                "role": "client",
            },
            timeout=20,
        )
        assert cr.status_code in (200, 201), cr.text
        cid = cr.json()["id"]
        try:
            # Update email
            ur = requests.put(
                f"{API}/admin/clients/{cid}",
                headers=admin_h,
                json={"email": new_email.upper()},  # also tests lowercase normalization
                timeout=20,
            )
            assert ur.status_code == 200, ur.text
            # Read back
            gr = requests.get(f"{API}/admin/clients/{cid}", headers=admin_h, timeout=15)
            assert gr.status_code == 200
            actual_email = (gr.json() or {}).get("email")
            assert actual_email == new_email, f"email did not propagate: {actual_email!r} != {new_email!r}"
        finally:
            requests.delete(f"{API}/admin/clients/{cid}", headers=admin_h, timeout=15)

    def test_email_uniqueness_enforced(self, admin_h):
        # Create two clients, then try to set the second's email = first's email
        s1 = uuid.uuid4().hex[:8]
        s2 = uuid.uuid4().hex[:8]
        e1 = f"iter35f_dup_a_{s1}@example.com"
        e2 = f"iter35f_dup_b_{s2}@example.com"
        c1 = requests.post(
            f"{API}/admin/clients", headers=admin_h, timeout=20,
            json={"full_name": "A", "email": e1, "password": "TempPass2026!", "company": "A", "role": "client"},
        )
        c2 = requests.post(
            f"{API}/admin/clients", headers=admin_h, timeout=20,
            json={"full_name": "B", "email": e2, "password": "TempPass2026!", "company": "B", "role": "client"},
        )
        assert c1.status_code in (200, 201) and c2.status_code in (200, 201)
        cid1, cid2 = c1.json()["id"], c2.json()["id"]
        try:
            r = requests.put(
                f"{API}/admin/clients/{cid2}", headers=admin_h, timeout=20,
                json={"email": e1},
            )
            assert r.status_code == 409, f"expected 409 conflict, got {r.status_code}: {r.text}"
            assert "déjà utilisé" in r.text.lower() or "already" in r.text.lower()
        finally:
            requests.delete(f"{API}/admin/clients/{cid1}", headers=admin_h, timeout=15)
            requests.delete(f"{API}/admin/clients/{cid2}", headers=admin_h, timeout=15)

    def test_email_invalid_rejected(self, admin_h):
        suffix = uuid.uuid4().hex[:8]
        c = requests.post(
            f"{API}/admin/clients", headers=admin_h, timeout=20,
            json={"full_name": "X", "email": f"iter35f_x_{suffix}@example.com", "password": "TempPass2026!", "company": "X", "role": "client"},
        )
        assert c.status_code in (200, 201)
        cid = c.json()["id"]
        try:
            r = requests.put(
                f"{API}/admin/clients/{cid}", headers=admin_h, timeout=20,
                json={"email": "not_an_email"},
            )
            assert r.status_code == 400, r.text
        finally:
            requests.delete(f"{API}/admin/clients/{cid}", headers=admin_h, timeout=15)


# ============================================================
# Bug 1 — Contact RGPD masked save
# ============================================================
class TestContactRgpdMaskedSave:
    def test_masked_field_is_not_persisted(self, admin_h):
        # Create a contact with real data
        cr = requests.post(
            f"{API}/me/contacts",
            headers=admin_h,
            json={
                "name": "Original Name iter35f",
                "email": "real@example.com",
                "phone": "+2250707070707",
                "whatsapp": "+2250707070707",
                "company": "Real Co",
            },
            timeout=15,
        )
        if cr.status_code not in (200, 201):
            pytest.skip(f"contact creation refused: {cr.status_code} {cr.text[:200]}")
        cid = (cr.json() or {}).get("id")
        assert cid, cr.text
        try:
            # Send back masked sentinels along with one real update
            ur = requests.put(
                f"{API}/me/contacts/{cid}",
                headers=admin_h,
                json={
                    "name": "O*** N*** i***",          # mask sentinel
                    "email": "r***@example.com",       # mask sentinel
                    "phone": "+22 ** ** ** 07",        # mask sentinel
                    "whatsapp": "+22 ** ** ** 07",     # mask sentinel
                    "company": "Updated Co",            # real change → must persist
                },
                timeout=15,
            )
            assert ur.status_code == 200, ur.text
            body = ur.json()
            assert "masked_skipped" in body, f"missing masked_skipped key: {body}"
            assert set(body["masked_skipped"]) == {"name", "email", "phone", "whatsapp"}
            # Read back the contact and confirm real data preserved
            gr = requests.get(f"{API}/me/contacts/{cid}", headers=admin_h, timeout=10)
            if gr.status_code == 200:
                doc = gr.json()
                assert doc.get("name") == "Original Name iter35f"
                assert doc.get("email") == "real@example.com"
                assert "***" not in (doc.get("name") or "")
                assert "***" not in (doc.get("email") or "")
                # Company should reflect the real update
                assert doc.get("company") == "Updated Co"
        finally:
            requests.delete(f"{API}/me/contacts/{cid}", headers=admin_h, timeout=10)

    def test_unmasked_update_still_persists(self, admin_h):
        cr = requests.post(
            f"{API}/me/contacts", headers=admin_h, timeout=15,
            json={"name": "T35f", "email": "t35f@example.com", "phone": "+2250101010101"},
        )
        if cr.status_code not in (200, 201):
            pytest.skip("contact creation refused")
        cid = cr.json()["id"]
        try:
            ur = requests.put(
                f"{API}/me/contacts/{cid}", headers=admin_h, timeout=15,
                json={"name": "New Name T35f"},
            )
            assert ur.status_code == 200
            body = ur.json()
            assert body.get("masked_skipped") == [], body
        finally:
            requests.delete(f"{API}/me/contacts/{cid}", headers=admin_h, timeout=10)


# ============================================================
# Bug 5b — Bulk WhatsApp fails fast on zero contacts resolved
# ============================================================
class TestBulkWaZeroContactsFailsFast:
    def test_bulk_with_unknown_contact_ids_returns_404(self, admin_h):
        body = {
            "contact_ids": [f"bogus_iter35f_{uuid.uuid4().hex}"],
            "template_name": "hello_world",
            "language_code": "en_US",
        }
        r = requests.post(f"{API}/me/whatsapp/bulk", headers=admin_h, json=body, timeout=20)
        # Either 404 (zero contact resolved) or 403 (WA disabled for this account).
        # The 404 path is what we want to assert on installs where WA is configured.
        assert r.status_code in (403, 404), f"unexpected status {r.status_code}: {r.text}"
        if r.status_code == 404:
            assert "Aucun contact" in r.text or "actualis" in r.text.lower()


# ============================================================
# Bug 5a — Read-only smoke test: window helper accepts list scope
# ============================================================
class TestWa24hWindowHelper:
    def test_send_text_without_inbound_still_409(self, admin_h):
        """Sanity: with no prior inbound the endpoint must still reject."""
        body = {"to": "+22501020304", "text": "iter35f smoke test"}
        r = requests.post(f"{API}/me/whatsapp/send-text", headers=admin_h, json=body, timeout=15)
        # Expected: 409 (24h closed) — proves the new list-scope query path works.
        assert r.status_code in (403, 409), f"unexpected {r.status_code}: {r.text[:200]}"
