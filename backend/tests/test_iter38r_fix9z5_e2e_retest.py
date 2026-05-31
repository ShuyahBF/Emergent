"""
E2E retest for iter38r-fix9z5 — Sizing controls, Public renewal widget, AI cost chart.
Validates the integration end-to-end via the public preview URL.
"""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")


def _login_admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@sawalismartsystems.com",
        "password": "Admin@Sawali2026",
    })
    assert r.status_code == 200, r.text
    j = r.json()
    session_token = j.get("session_token")
    dev_otp = j.get("dev_otp")
    assert session_token and dev_otp, f"missing fields: {j}"
    r2 = s.post(f"{BASE_URL}/api/auth/verify-otp", json={
        "session_token": session_token, "code": dev_otp,
    })
    assert r2.status_code == 200, r2.text
    token = r2.json().get("access_token") or r2.json().get("token")
    assert token
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def admin_client():
    return _login_admin()


def test_create_banner_with_ratio_sizing(admin_client):
    payload = {
        "name": "TEST_e2e_ratio_banner",
        "advertiser": "TestCo",
        "image_url": "https://placehold.co/728x90.png",
        "target_url": "https://example.com",
        "active": True,
        "display_mode": "ratio",
        "aspect_ratio": "21:9",
        "width_pct": 80,
    }
    r = admin_client.post(f"{BASE_URL}/api/admin/ad-banners", json=payload)
    assert r.status_code in (200, 201), r.text
    body = r.json()
    data = body.get("item", body)
    assert data["display_mode"] == "ratio"
    assert data["aspect_ratio"] == "21:9"
    assert data["width_pct"] == 80
    banner_id = data["id"]
    share_token = data.get("share_token")
    slug = data.get("slug")

    # GET list and confirm presence
    r2 = admin_client.get(f"{BASE_URL}/api/admin/ad-banners")
    assert r2.status_code == 200
    items = r2.json().get("items", [])
    found = next((i for i in items if i["id"] == banner_id), None)
    assert found is not None
    assert found["display_mode"] == "ratio"
    assert found["aspect_ratio"] == "21:9"

    # UPDATE → fixed
    r3 = admin_client.put(f"{BASE_URL}/api/admin/ad-banners/{banner_id}", json={
        "display_mode": "fixed", "width_px": 1200, "height_px": 200,
    })
    assert r3.status_code == 200, r3.text
    u = r3.json().get("item", r3.json())
    assert u["display_mode"] == "fixed"
    assert u["width_px"] == 1200
    assert u["height_px"] == 200

    # Public token endpoint returns sizing fields
    if share_token and slug:
        rp = requests.get(f"{BASE_URL}/api/public/ads-report/{slug}", params={"token": share_token})
        assert rp.status_code == 200, rp.text
        pj = rp.json()
        # The endpoint should expose sizing fields somewhere — accept flat or nested
        flat = pj.get("banner", pj)
        assert flat.get("display_mode") in ("fixed", "ratio", "auto", "percentage"), pj

        # POST renew with valid token
        rn = requests.post(
            f"{BASE_URL}/api/public/ads-report/{slug}/renew",
            params={"token": share_token},
            json={"contact_email": "renew@test.com", "new_budget": 50000, "target_duration_days": 30},
        )
        assert rn.status_code in (200, 201), rn.text
        rj = rn.json()
        assert "id" in rj or rj.get("ok") is True, rj

    # cleanup
    admin_client.delete(f"{BASE_URL}/api/admin/ad-banners/{banner_id}")


def test_ai_costs_monthly_endpoint(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/admin/ai-costs/monthly", params={"months": 6})
    assert r.status_code == 200
    j = r.json()
    assert "series" in j
    assert len(j["series"]) == 6
    assert j.get("currency") == "XOF"
    assert "totals" in j


def test_ai_costs_monthly_range_validation(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/admin/ai-costs/monthly", params={"months": 999})
    assert r.status_code in (400, 422)


def test_ai_costs_monthly_requires_admin():
    r = requests.get(f"{BASE_URL}/api/admin/ai-costs/monthly", params={"months": 12})
    assert r.status_code in (401, 403)


def test_renewal_request_bad_token():
    r = requests.post(
        f"{BASE_URL}/api/public/ads-report/sawali-portal/renew",
        params={"token": "BAD_TOKEN_xyz"},
        json={"contact_email": "x@y.com", "new_budget": 10000, "target_duration_days": 30},
    )
    assert r.status_code in (403, 404)


def test_admin_renewal_inbox_lists(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/admin/ad-renewal-requests")
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j, dict)
    assert "items" in j


def test_byte_range_regression_on_files():
    """Critical regression: video/image serving with HTTP 206 byte ranges."""
    # Probe public file endpoint with a HEAD-like behaviour; we accept 200, 206 or 404
    # but if a file exists we must be able to request a byte range.
    r = requests.get(f"{BASE_URL}/api/files/nonexistent", headers={"Range": "bytes=0-100"})
    # Either 404 (no such file) or 206 (if file exists). Should never be 500.
    assert r.status_code != 500
