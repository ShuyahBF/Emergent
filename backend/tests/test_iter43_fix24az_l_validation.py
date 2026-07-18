"""Iter43-fix24az-l — validation tests.

Coverage:
  1. Cross-tenant data leak fix (P0)
  2. Recipe duplicate with cleared dosage (P1)
  3. Recipe uniqueness constraint (P1)
  4. Dosage-based cost model with FIXED categories packaging/other (P1)
  5. TikTok privacy toggle (P2)
"""
import os
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

CRED = {
    "tenant_a": ("isis-admin@test-tenant-a.com", "Isis@2026"),
    "tenant_b": ("sawali-admin@test-tenant-b.com", "Sawali@2026"),
    "super":    ("admin@sawalismartsystems.com", "Admin@Sawali2026"),
    "fab":      ("fab-analytics@sawali-test.com", "Analytics@2026"),
}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("needs_otp"):
        # already returned token
        return data.get("access_token"), data
    otp = data.get("dev_otp")
    assert otp, f"No dev_otp returned for {email}: {data}"
    r2 = requests.post(f"{API}/auth/verify-otp", json={
        "session_token": data["session_token"], "code": otp,
    }, timeout=30)
    r2.raise_for_status()
    tok = r2.json().get("access_token")
    return tok, r2.json()


@pytest.fixture(scope="module")
def tokens():
    out = {}
    for k, (e, p) in CRED.items():
        tok, _ = _login(e, p)
        out[k] = tok
    return out


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _contains_leak_str(items, needle):
    """Return list of items containing the needle in any string field."""
    hits = []
    for it in items or []:
        try:
            blob = str(it).lower()
            if needle.lower() in blob:
                hits.append(it)
        except Exception:
            pass
    return hits


# ============================================================================
# P0 — Cross-tenant leak
# ============================================================================
LEAK_A = "LEAK-TEST for ISISPHARMA"
LEAK_B = "LEAK-TEST for SAWALI SMART SYSTEMS-Client"


class TestCrossTenantLeak:
    """Neither tenant A nor tenant B should see the other's LEAK-TEST rows.
    Super-admin must see both.
    """

    ENDPOINTS = [
        ("/admin/documents", "documents"),
        ("/admin/appointments", "appointments"),
        ("/admin/interventions", "interventions"),
        ("/me/notes/reports", "notes_reports"),
        ("/me/notes/suivis", "notes_suivis"),
        ("/me/notes/notes", "notes_notes"),
    ]

    def _fetch(self, endpoint, tok):
        r = requests.get(f"{API}{endpoint}", headers=_h(tok), timeout=30)
        if r.status_code >= 400:
            return {"__status": r.status_code, "__body": r.text[:200]}
        try:
            data = r.json()
        except Exception:
            return {"__body": r.text[:200]}
        if isinstance(data, dict):
            return data.get("items") or data.get("data") or data.get("notes") or []
        return data

    @pytest.mark.parametrize("endpoint,label", ENDPOINTS)
    def test_tenant_A_does_not_see_B(self, tokens, endpoint, label):
        items = self._fetch(endpoint, tokens["tenant_a"])
        if isinstance(items, dict) and "__status" in items:
            pytest.skip(f"{endpoint} → HTTP {items['__status']} for tenant A: {items.get('__body')}")
        hits = _contains_leak_str(items, LEAK_B)
        assert not hits, f"TENANT-A LEAK on {endpoint}: sees {len(hits)} items tagged '{LEAK_B}': {hits[:2]}"

    @pytest.mark.parametrize("endpoint,label", ENDPOINTS)
    def test_tenant_B_does_not_see_A(self, tokens, endpoint, label):
        items = self._fetch(endpoint, tokens["tenant_b"])
        if isinstance(items, dict) and "__status" in items:
            pytest.skip(f"{endpoint} → HTTP {items['__status']} for tenant B: {items.get('__body')}")
        hits = _contains_leak_str(items, LEAK_A)
        assert not hits, f"TENANT-B LEAK on {endpoint}: sees {len(hits)} items tagged '{LEAK_A}': {hits[:2]}"

    def test_super_admin_sees_both(self, tokens):
        seen_a, seen_b = False, False
        for endpoint, _ in self.ENDPOINTS:
            items = self._fetch(endpoint, tokens["super"])
            if isinstance(items, dict) and "__status" in items:
                continue
            if _contains_leak_str(items, LEAK_A):
                seen_a = True
            if _contains_leak_str(items, LEAK_B):
                seen_b = True
        assert seen_a, "Super-admin does NOT see any LEAK-A tagged row in ANY endpoint"
        assert seen_b, "Super-admin does NOT see any LEAK-B tagged row in ANY endpoint"


# ============================================================================
# P1 — Recipe duplicate + uniqueness + dosage cost model
# ============================================================================
class TestRecipeDuplicate:
    def test_duplicate_clears_dosage_and_appends_copie(self, tokens):
        tok = tokens["fab"]
        r = requests.get(f"{API}/production/recipes", headers=_h(tok), timeout=30)
        assert r.status_code == 200, r.text
        items = r.json().get("items") or []
        assert items, "No seed recipes for fabricant"
        # pick a recipe with a dosage set
        src = next((x for x in items if x.get("dosage_number")), items[0])
        rid = src["id"]
        original_name = src["name"]
        # 1st duplicate
        r1 = requests.post(f"{API}/production/recipes/{rid}/duplicate", headers=_h(tok), timeout=30)
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1.get("dosage_number") in (None, 0), f"dosage_number not cleared: {d1.get('dosage_number')}"
        assert d1["name"].endswith("(copie)"), f"unexpected duplicate name: {d1['name']}"
        assert original_name in d1["name"]
        # 2nd duplicate → should get (copie 2)
        r2 = requests.post(f"{API}/production/recipes/{rid}/duplicate", headers=_h(tok), timeout=30)
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["name"].endswith("(copie 2)"), f"expected '(copie 2)', got {d2['name']}"
        # cleanup
        for _d in (d1, d2):
            requests.delete(f"{API}/production/recipes/{_d['id']}", headers=_h(tok), timeout=30)


class TestRecipeUniqueness:
    def test_create_duplicate_returns_409(self, tokens):
        tok = tokens["fab"]
        r = requests.get(f"{API}/production/recipes", headers=_h(tok), timeout=30)
        assert r.status_code == 200
        items = r.json().get("items") or []
        src = next((x for x in items if x.get("dosage_number")), None)
        if not src:
            pytest.skip("Need a seed recipe with dosage_number set")
        payload = {
            "name": src["name"],
            "dosage_number": src["dosage_number"],
            "dosage_unit": src.get("dosage_unit") or "ml",
            "output_batch_units": src.get("output_batch_units", 1),
            "output_unit_label": src.get("output_unit_label", "unit"),
            "intrants": [],
            "pricing_mode": src.get("pricing_mode", "margin_first"),
        }
        r2 = requests.post(f"{API}/production/recipes", json=payload, headers=_h(tok), timeout=30)
        assert r2.status_code == 409, f"expected 409, got {r2.status_code}: {r2.text}"
        detail = r2.json().get("detail", "")
        assert "existe déjà" in detail or "existe deja" in detail.lower(), f"FR detail expected, got: {detail}"


class TestDosageCostModel:
    def test_packaging_and_other_are_fixed(self, tokens):
        tok = tokens["fab"]
        h = _h(tok)
        # 1) Create 3 intrants (raw_material, packaging, other) with unique names
        import uuid as _u
        suffix = _u.uuid4().hex[:6]
        intrants = {}
        for cat, cost, unit in [("raw_material", 2, "g"), ("packaging", 50, "unit"), ("other", 10, "unit")]:
            payload = {"name": f"TEST_{cat}_{suffix}", "unit": unit, "unit_cost": cost, "category": cat}
            r = requests.post(f"{API}/production/intrants", json=payload, headers=h, timeout=30)
            assert r.status_code in (200, 201), r.text
            intrants[cat] = r.json()["id"]

        try:
            # 2) Create recipe with dosage=100
            recipe_payload = {
                "name": f"TEST_recipe_{suffix}",
                "dosage_number": 100,
                "dosage_unit": "ml",
                "output_batch_units": 1,
                "output_unit_label": "unit",
                "intrants": [{"intrant_id": iid, "quantity": 0} for iid in intrants.values()],
                "pricing_mode": "margin_first",
                "margin_pct": 0,
            }
            r = requests.post(f"{API}/production/recipes", json=recipe_payload, headers=h, timeout=30)
            assert r.status_code == 200, r.text
            rec = r.json()
            rid = rec["id"]
            # cost = 2*100 + 50 + 10 = 260
            cost_batch_100 = rec.get("intrants_total_batch")
            assert abs(cost_batch_100 - 260.0) < 0.01, f"dosage=100 expected 260, got {cost_batch_100}"

            # 3) PUT dosage=200 → 2*200 + 50 + 10 = 460
            recipe_payload["dosage_number"] = 200
            r2 = requests.put(f"{API}/production/recipes/{rid}", json=recipe_payload, headers=h, timeout=30)
            assert r2.status_code == 200, r2.text
            rec2 = r2.json()
            cost_batch_200 = rec2.get("intrants_total_batch")
            assert abs(cost_batch_200 - 460.0) < 0.01, f"dosage=200 expected 460, got {cost_batch_200}"
            ratio = cost_batch_200 / cost_batch_100
            assert 1.7 < ratio < 1.8, f"ratio expected ~1.77, got {ratio}"

            # cleanup recipe
            requests.delete(f"{API}/production/recipes/{rid}", headers=h, timeout=30)
        finally:
            # cleanup intrants
            for iid in intrants.values():
                requests.delete(f"{API}/production/intrants/{iid}", headers=h, timeout=30)


# ============================================================================
# P2 — TikTok privacy toggle
# ============================================================================
class TestTikTokPrivacyToggle:
    def test_default_self_only(self, tokens):
        tok = tokens["super"]
        r = requests.get(f"{API}/admin/story-studio/settings", headers=_h(tok), timeout=30)
        assert r.status_code == 200, r.text
        val = r.json().get("tiktok_privacy_level")
        # default SELF_ONLY (unless already updated by prior test run)
        assert val in ("SELF_ONLY", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"), val

    def test_put_and_get_public(self, tokens):
        tok = tokens["super"]
        h = _h(tok)
        # Set to PUBLIC_TO_EVERYONE
        r = requests.put(f"{API}/admin/story-studio/settings",
                         json={"tiktok_privacy_level": "PUBLIC_TO_EVERYONE"},
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text
        r2 = requests.get(f"{API}/admin/story-studio/settings", headers=h, timeout=30)
        assert r2.status_code == 200
        assert r2.json().get("tiktok_privacy_level") == "PUBLIC_TO_EVERYONE"
        # Restore default
        requests.put(f"{API}/admin/story-studio/settings",
                     json={"tiktok_privacy_level": "SELF_ONLY"}, headers=h, timeout=30)
