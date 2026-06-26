"""Iter71 — Validation des 3 bugs P0 + régressions :
  Bug #1: Synthèse Liluvine — KPIs réels (pas '0' partout)
  Bug #2: LinkedIn callback défensif (HTML 400, jamais 500)
  Bug #3: Facebook redirect_uri éditable (PUT/GET admin)
  Régression: Facebook callback défensif + endpoints admin Linkedin/Facebook intacts
"""
import os
import time
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


# ---------- Auth fixture ----------
@pytest.fixture(scope="module")
def admin_token() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    session_token = data.get("session_token")
    otp = data.get("dev_otp")
    assert session_token and otp, f"missing session_token/dev_otp: {data}"
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": session_token, "code": otp}, timeout=30)
    assert r2.status_code == 200, f"otp verify failed: {r2.status_code} {r2.text[:300]}"
    token = r2.json().get("access_token")
    assert token, f"missing access_token: {r2.json()}"
    return token


@pytest.fixture(scope="module")
def H(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------- Bug #1 — Liluvine synthèse KPIs ----------
class TestSyntheseKpis:
    def test_synthese_test_returns_kpis_with_real_counts(self, H):
        r = requests.post(f"{API}/admin/synthese/test", headers=H, timeout=120)
        assert r.status_code == 200, f"unexpected status: {r.status_code} {r.text[:300]}"
        body = r.json()
        assert "kpis" in body, f"missing kpis in response: keys={list(body.keys())}"
        kpis = body["kpis"]
        assert isinstance(kpis, dict), f"kpis not a dict: {type(kpis)}"
        counts = kpis.get("counts")
        assert isinstance(counts, dict), f"counts missing/invalid: {counts}"

        # Required keys present
        for key in ("new_contacts", "new_tickets", "wa_sent", "bird_sms_sent", "invoices", "payments"):
            assert key in counts, f"missing counts.{key} — got {list(counts.keys())}"

        # At least one of the documented populated KPIs should be > 0
        # PREVIEW DB seed: directory_contacts=119, whatsapp_messages=408, invoices=657, payment_transactions=49
        nonzero = {k: v for k, v in counts.items() if isinstance(v, int) and v > 0}
        assert nonzero, (
            f"ALL KPIs still report 0 — bug not fixed. counts={counts}. "
            "Expected real values from PREVIEW DB (contacts, wa, invoices etc.)."
        )
        print(f"[synthese] non-zero KPIs: {nonzero}")

        # Preview field should also contain numbers (not all zero in render)
        preview = body.get("preview") or ""
        assert isinstance(preview, str)
        # The preview is the LLM/prompt rendering — must contain at least one nonzero digit-string
        # We tolerate the case where LLM is offline (preview may be empty), but kpis.counts is the real assertion.


# ---------- Bug #2 — LinkedIn callback défensif ----------
class TestLinkedinCallback:
    def test_callback_no_params_returns_400_html(self):
        r = requests.get(f"{API}/linkedin/oauth/callback", timeout=20, allow_redirects=False)
        assert r.status_code == 400, f"expected 400, got {r.status_code} body={r.text[:300]}"
        ct = r.headers.get("content-type", "")
        assert "text/html" in ct, f"expected HTML, got {ct}"
        text = r.text.lower()
        assert "internal server error" not in text, "leaked 500 page"
        assert "traceback" not in text, "leaked stack trace"
        assert ("code" in text and "state" in text) or "requis" in text, f"no friendly msg: {r.text[:300]}"

    def test_callback_bogus_state_returns_400_html(self):
        r = requests.get(
            f"{API}/linkedin/oauth/callback",
            params={"code": "x", "state": "bogus_state_does_not_exist"},
            timeout=20,
            allow_redirects=False,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code} body={r.text[:300]}"
        assert "text/html" in r.headers.get("content-type", "")
        text = r.text.lower()
        assert "state invalide" in text or "invalide" in text, f"missing 'State invalide': {r.text[:300]}"
        assert "internal server error" not in text
        assert "traceback" not in text

    def test_callback_with_error_param_returns_400(self):
        r = requests.get(
            f"{API}/linkedin/oauth/callback",
            params={"error": "access_denied", "error_description": "user_refused"},
            timeout=20,
            allow_redirects=False,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}"
        assert "access_denied" in r.text.lower() or "refus" in r.text.lower()


# ---------- Bug #3 — Facebook redirect_uri éditable ----------
class TestFacebookRedirectUri:
    CUSTOM_URI = "https://test.example.com/api/facebook/oauth/callback"

    def test_put_custom_redirect_uri_then_preview_returns_override(self, H):
        # PUT custom
        r = requests.put(f"{API}/admin/facebook/config", headers=H, json={"redirect_uri": self.CUSTOM_URI}, timeout=20)
        assert r.status_code == 200, f"PUT failed: {r.status_code} {r.text[:300]}"

        # GET preview — should reflect override
        r2 = requests.get(f"{API}/admin/facebook/oauth/preview-redirect-uri", headers=H, timeout=20)
        assert r2.status_code == 200, f"GET preview failed: {r2.status_code} {r2.text[:300]}"
        data = r2.json()
        assert data.get("redirect_uri") == self.CUSTOM_URI, f"redirect_uri not honored: {data}"
        assert data.get("explicit_override") == self.CUSTOM_URI, f"explicit_override missing: {data}"

        # GET /admin/facebook/config should also show the value
        r3 = requests.get(f"{API}/admin/facebook/config", headers=H, timeout=20)
        assert r3.status_code == 200
        assert r3.json().get("redirect_uri") == self.CUSTOM_URI

    def test_put_empty_redirect_uri_clears_override(self, H):
        # First set
        requests.put(f"{API}/admin/facebook/config", headers=H, json={"redirect_uri": self.CUSTOM_URI}, timeout=20)
        # Then clear
        r = requests.put(f"{API}/admin/facebook/config", headers=H, json={"redirect_uri": ""}, timeout=20)
        assert r.status_code == 200, f"PUT clear failed: {r.status_code} {r.text[:300]}"

        # Preview must now return computed URL (from x-forwarded-host), not the override
        r2 = requests.get(f"{API}/admin/facebook/oauth/preview-redirect-uri", headers=H, timeout=20)
        assert r2.status_code == 200
        data = r2.json()
        assert data.get("explicit_override") in ("", None), f"override not cleared: {data}"
        ru = data.get("redirect_uri", "")
        # Should be the computed URL based on the request host (not test.example.com)
        assert "test.example.com" not in ru, f"override leaked into computed: {ru}"
        assert "/api/facebook/oauth/callback" in ru, f"computed uri malformed: {ru}"
        assert ru.startswith("http"), f"computed uri not absolute: {ru}"


# ---------- Régression — Facebook callback défensif ----------
class TestFacebookCallbackDefensive:
    def test_callback_no_params_returns_400_html(self):
        r = requests.get(f"{API}/facebook/oauth/callback", timeout=20, allow_redirects=False)
        assert r.status_code == 400, f"expected 400, got {r.status_code} body={r.text[:300]}"
        assert "text/html" in r.headers.get("content-type", "")
        text = r.text.lower()
        assert "code/state requis" in text or ("code" in text and "state" in text), (
            f"missing 'code/state requis' msg: {r.text[:300]}"
        )
        assert "internal server error" not in text
        assert "traceback" not in text


# ---------- Régression — endpoints admin Linkedin/Facebook intacts ----------
class TestAdminEndpointsIntact:
    def test_admin_linkedin_config(self, H):
        r = requests.get(f"{API}/admin/linkedin/config", headers=H, timeout=20)
        assert r.status_code == 200, f"linkedin config: {r.status_code} {r.text[:300]}"
        assert isinstance(r.json(), dict)

    def test_admin_facebook_config(self, H):
        r = requests.get(f"{API}/admin/facebook/config", headers=H, timeout=20)
        assert r.status_code == 200, f"facebook config: {r.status_code} {r.text[:300]}"
        assert isinstance(r.json(), dict)

    def test_linkedin_status(self, H):
        r = requests.get(f"{API}/linkedin/status", headers=H, timeout=20)
        assert r.status_code == 200, f"linkedin status: {r.status_code} {r.text[:300]}"
        assert isinstance(r.json(), dict)
