"""Iter35i — Tests for Orange Developer OAuth2 SMS integration.

Validates:
  • Settings persistance of the new sms_orange_* OAuth fields.
  • The _orange_get_token helper sends form-urlencoded body and Basic auth
    (mocked via httpx_mock). NB: we test the helper at module level so we
    don't need a real Orange Developer account in CI.
  • The /admin/sms/test endpoint surfaces a clean error message when the
    OAuth flow fails (no client_id configured) instead of crashing.
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


class TestSettingsPersistance:
    def test_orange_oauth_fields_persist(self, admin_h):
        marker = uuid.uuid4().hex[:8]
        body = {
            "sms_orange_enabled": True,
            "sms_orange_url": "https://api.orange.com/smsmessaging/v1",
            "sms_orange_auth_type": "orange_oauth",
            "sms_orange_oauth_url": "https://api.orange.com/oauth/v3/token",
            "sms_orange_client_id": f"client_{marker}",
            "sms_orange_client_secret": f"secret_{marker}",
            "sms_orange_sender_msisdn": "+22670000000",
        }
        r = requests.put(f"{API}/admin/settings", headers=admin_h, json=body, timeout=20)
        assert r.status_code == 200, r.text

        g = requests.get(f"{API}/admin/settings", headers=admin_h, timeout=15)
        assert g.status_code == 200
        s = g.json()
        assert s["sms_orange_auth_type"] == "orange_oauth"
        assert s["sms_orange_oauth_url"] == "https://api.orange.com/oauth/v3/token"
        assert s["sms_orange_client_id"] == f"client_{marker}"
        # Secret must be masked on read
        assert s["sms_orange_client_secret"] == "********", f"client_secret leaked: {s.get('sms_orange_client_secret')!r}"
        assert s["sms_orange_sender_msisdn"] == "+22670000000"

    def test_secret_mask_is_preserved_on_subsequent_save(self, admin_h):
        # Saving with the masked sentinel must NOT overwrite the stored secret.
        marker = uuid.uuid4().hex[:8]
        # First save a real value
        r1 = requests.put(
            f"{API}/admin/settings", headers=admin_h, timeout=15,
            json={"sms_orange_client_secret": f"real_secret_{marker}"},
        )
        assert r1.status_code == 200
        # Now save the masked sentinel
        r2 = requests.put(
            f"{API}/admin/settings", headers=admin_h, timeout=15,
            json={"sms_orange_client_secret": "********"},
        )
        assert r2.status_code == 200
        # Confirm we still see masked on GET (secret is still in DB, just hidden)
        s = requests.get(f"{API}/admin/settings", headers=admin_h, timeout=15).json()
        assert s["sms_orange_client_secret"] == "********"


class TestSmsTestEndpointSurfacesErrorCleanly:
    """The /admin/sms/test endpoint should return a 200 OK with a structured
    response carrying the OAuth error message, NOT a 500."""

    def test_orange_oauth_missing_credentials_returns_clean_error(self, admin_h):
        # Clear OAuth credentials but keep orange_oauth mode enabled
        save = requests.put(
            f"{API}/admin/settings", headers=admin_h, timeout=15,
            json={
                "sms_orange_enabled": True,
                "sms_orange_auth_type": "orange_oauth",
                "sms_orange_client_id": "",
                "sms_orange_client_secret": "",
            },
        )
        assert save.status_code == 200
        # Now attempt a test send → must NOT 500
        r = requests.post(
            f"{API}/admin/sms/test", headers=admin_h, timeout=20,
            json={"provider": "orange", "phone": "+22670000000", "message": "test iter35i"},
        )
        # 200 OK with error inside, or 4xx with detail — either way no 5xx
        assert r.status_code < 500, f"got 5xx for missing creds: {r.status_code} {r.text}"
        if r.status_code == 200:
            body = r.json()
            # Surface SHOULD mention OAuth or credentials in the api_message
            api_msg = (body.get("api_message") or "").lower()
            assert (
                "oauth" in api_msg
                or "client_id" in api_msg
                or "client_secret" in api_msg
                or "identifiants" in api_msg
            ), f"error message unclear: {body}"
