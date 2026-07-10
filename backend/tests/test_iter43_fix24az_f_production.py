"""Iter43-fix24az-f (2026-02-26) — Production module smoke tests.

Covers:
  - Access control: only admin/superviseur of a business_type=fabricant tenant.
  - CRUD intrants + recipes + settings.
  - Real-time cost/margin/price computation.
  - PDF exports return application/pdf.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

API_URL = os.environ.get("REACT_APP_BACKEND_URL") or "https://sawali-portal.preview.emergentagent.com"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    d = r.json()
    if not d.get("needs_otp"):
        return d["access_token"]
    r = requests.post(f"{API_URL}/api/auth/verify-otp", json={"session_token": d["session_token"], "code": d["dev_otp"]}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@sawalismartsystems.com", "Admin@Sawali2026")


@pytest.fixture(scope="module")
def fabricant_tenant(admin_token):
    """Create a fresh tenant with business_type=fabricant + login. Return the token."""
    email = f"fab-{uuid.uuid4().hex[:6]}@sawali-test.com"
    pw = "Fab@2026!Test"
    payload = {
        "email": email, "password": pw, "full_name": "Fabricant Test",
        "company": "Labo Test", "role": "admin", "business_type": "fabricant",
    }
    r = requests.post(f"{API_URL}/api/admin/clients",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      json=payload, timeout=15)
    assert r.status_code in (200, 201), f"Create tenant failed: {r.status_code} {r.text}"
    tok = _login(email, pw)
    yield {"token": tok, "email": email}
    # Cleanup done via delete by admin later if needed (best effort)


def test_non_fabricant_gets_403(admin_token):
    r = requests.get(f"{API_URL}/api/production/intrants",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 403
    assert "Fabricant" in r.text


def test_intrant_crud(fabricant_tenant):
    tok = fabricant_tenant["token"]
    H = {"Authorization": f"Bearer {tok}"}
    # Empty list initially
    r = requests.get(f"{API_URL}/api/production/intrants", headers=H, timeout=10)
    assert r.status_code == 200
    assert r.json()["count"] == 0
    # Create ICARIDINE
    r = requests.post(f"{API_URL}/api/production/intrants", headers=H, json={
        "name": "ICARIDINE", "unit": "ml", "unit_cost": 12.5, "category": "raw_material",
    }, timeout=10)
    assert r.status_code == 200, r.text
    iid = r.json()["id"]
    # Update
    r = requests.put(f"{API_URL}/api/production/intrants/{iid}", headers=H, json={
        "name": "ICARIDINE 20%", "unit": "ml", "unit_cost": 15.0, "category": "raw_material",
    }, timeout=10)
    assert r.status_code == 200
    # List
    r = requests.get(f"{API_URL}/api/production/intrants", headers=H, timeout=10)
    assert r.json()["count"] == 1
    assert r.json()["items"][0]["unit_cost"] == 15.0
    # Invalid category
    r = requests.post(f"{API_URL}/api/production/intrants", headers=H, json={
        "name": "X", "unit": "ml", "unit_cost": 1, "category": "bogus",
    }, timeout=10)
    assert r.status_code == 400


def test_recipe_computation(fabricant_tenant):
    tok = fabricant_tenant["token"]
    H = {"Authorization": f"Bearer {tok}"}
    # Create 3 intrants
    ids = {}
    for name, cost in [("ALCOOL", 3), ("GLYCERINE", 5), ("FLACON 50ML", 25)]:
        r = requests.post(f"{API_URL}/api/production/intrants", headers=H, json={
            "name": name, "unit": "ml" if "FLACON" not in name else "unit",
            "unit_cost": cost, "category": "raw_material" if "FLACON" not in name else "packaging",
        }, timeout=10)
        assert r.status_code == 200
        ids[name] = r.json()["id"]
    # Create a recipe : batch of 10 flacons of 50ml
    # 10 flacons × 50 ml = 500 ml/batch, so:
    #   ALCOOL 400 ml × 3 = 1200
    #   GLYCERINE 100 ml × 5 = 500
    #   FLACON 50ML × 10 = 250
    # Total batch = 1950 CFA ; par unité = 195 CFA
    payload = {
        "name": "SPRAY TEST", "variant_label": "50 ml",
        "output_batch_units": 10, "output_unit_label": "flacon",
        "intrants": [
            {"intrant_id": ids["ALCOOL"], "quantity": 400},
            {"intrant_id": ids["GLYCERINE"], "quantity": 100},
            {"intrant_id": ids["FLACON 50ML"], "quantity": 10},
        ],
        "pricing_mode": "margin_first", "margin_pct": 42,
    }
    r = requests.post(f"{API_URL}/api/production/recipes", headers=H, json=payload, timeout=10)
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["intrants_total_batch"] == 1950.0, rec
    assert rec["cost_price"] == 195.0, rec
    assert rec["margin_pct"] == 42.0
    assert rec["public_price"] == round(195 * 1.42, 2)
    # Switch pricing to price_first
    payload["pricing_mode"] = "price_first"
    payload["public_price"] = 300
    r = requests.put(f"{API_URL}/api/production/recipes/{rec['id']}", headers=H, json=payload, timeout=10)
    assert r.status_code == 200
    rec2 = r.json()
    assert rec2["cost_price"] == 195.0
    assert rec2["public_price"] == 300.0
    # Margin = (300/195 - 1) * 100 = 53.85%
    assert abs(rec2["margin_pct"] - 53.85) < 0.02
    # Attempt to delete an intrant used by recipe → 409
    r = requests.delete(f"{API_URL}/api/production/intrants/{ids['ALCOOL']}", headers=H, timeout=10)
    assert r.status_code == 409


def test_settings_default_margin(fabricant_tenant):
    tok = fabricant_tenant["token"]
    H = {"Authorization": f"Bearer {tok}"}
    r = requests.get(f"{API_URL}/api/production/settings", headers=H, timeout=10)
    assert r.status_code == 200
    assert r.json()["production_default_margin_pct"] > 0
    # Set to 35
    r = requests.put(f"{API_URL}/api/production/settings", headers=H, json={"production_default_margin_pct": 35}, timeout=10)
    assert r.status_code == 200
    r = requests.get(f"{API_URL}/api/production/settings", headers=H, timeout=10)
    assert r.json()["production_default_margin_pct"] == 35.0


def test_pdf_export(fabricant_tenant):
    tok = fabricant_tenant["token"]
    H = {"Authorization": f"Bearer {tok}"}
    # Global export
    r = requests.get(f"{API_URL}/api/production/export/recipes.pdf", headers=H, timeout=15)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:4] == b"%PDF"
    # Per-recipe export : we need a recipe id — fetch and pick first
    r = requests.get(f"{API_URL}/api/production/recipes", headers=H, timeout=10)
    items = r.json().get("items", [])
    assert items, "no recipes in tenant"
    rid = items[0]["id"]
    r = requests.get(f"{API_URL}/api/production/export/recipe/{rid}.pdf", headers=H, timeout=15)
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"


def test_user_me_exposes_business_type(fabricant_tenant):
    tok = fabricant_tenant["token"]
    r = requests.get(f"{API_URL}/api/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 200
    assert r.json().get("business_type") == "fabricant"


def test_analytics_payload_shape(fabricant_tenant):
    """Analyses tab (frontend) requires:
      * list_recipes returns items[].intrants[] with category_snapshot / quantity /
        unit_cost_snapshot fields so the PieChart can aggregate costs by category.
      * summary.{avg_cost_price, avg_public_price, avg_margin_pct} for the KPI cards.
      * items[].created_at so the LineChart can order by creation date.
    """
    tok = fabricant_tenant["token"]
    H = {"Authorization": f"Bearer {tok}"}
    # Seed 2 intrants in different categories
    i_raw = requests.post(f"{API_URL}/api/production/intrants", headers=H, json={
        "name": "MAT-A", "unit": "ml", "unit_cost": 4.0, "category": "raw_material",
    }, timeout=10).json()["id"]
    i_lab = requests.post(f"{API_URL}/api/production/intrants", headers=H, json={
        "name": "LABOR-A", "unit": "h", "unit_cost": 1000.0, "category": "labor",
    }, timeout=10).json()["id"]
    # Create 2 recipes
    for name, margin in [("REC-1", 40), ("REC-2", 55)]:
        r = requests.post(f"{API_URL}/api/production/recipes", headers=H, json={
            "name": name, "output_batch_units": 5, "output_unit_label": "unit",
            "pricing_mode": "margin_first", "margin_pct": margin,
            "intrants": [
                {"intrant_id": i_raw, "quantity": 100},
                {"intrant_id": i_lab, "quantity": 2},
            ],
        }, timeout=10)
        assert r.status_code == 200, r.text

    resp = requests.get(f"{API_URL}/api/production/recipes", headers=H, timeout=10).json()
    items = resp.get("items", [])
    summary = resp.get("summary") or {}
    assert len(items) >= 2, items
    # Summary keys the Analyses KPI cards depend on
    for k in ("total_recipes", "avg_cost_price", "avg_public_price", "avg_margin_pct"):
        assert k in summary, f"summary missing {k}: {summary}"
    for it in items:
        assert "created_at" in it, "created_at required for LineChart ordering"
        assert "intrants_total_batch" in it, "needed for cumulative-cost KPI"
        assert isinstance(it.get("intrants"), list) and it["intrants"], it
        for ing in it["intrants"]:
            for req_field in ("category_snapshot", "quantity", "unit_cost_snapshot"):
                assert req_field in ing, f"missing {req_field} in recipe intrant: {ing}"


def test_dosage_based_cost_model(fabricant_tenant):
    """Iter43-fix24az-h — New cost model :
      * Recipe has `dosage_number` + `dosage_unit` (e.g. 50 + "ml").
      * Each intrant's cost = intrant.unit_cost × dosage_number
        (all intrants share the same multiplier).
      * unit_cost supports up to 4 decimals.
      * variant_label is auto-derived from dosage_number + dosage_unit.
    """
    tok = fabricant_tenant["token"]
    H = {"Authorization": f"Bearer {tok}"}
    # 3 intrants — one with fractional unit_cost (4-decimal precision).
    ids = {}
    for name, cost, cat in [
        ("ICARIDINE", 3.5000, "raw_material"),   # 3.5 CFA/ml
        ("ALCOOL",    0.0250, "raw_material"),   # 0.025 CFA/ml — 4-decimal precision
        ("Eau",       0.0004, "water"),          # 0.0004 CFA/ml — tiny but non-zero
    ]:
        r = requests.post(f"{API_URL}/api/production/intrants", headers=H, json={
            "name": name, "unit": "ml", "unit_cost": cost, "category": cat,
        }, timeout=10)
        assert r.status_code == 200, r.text
        ids[name] = r.json()["id"]
    # Create a 50 ml recipe.
    r = requests.post(f"{API_URL}/api/production/recipes", headers=H, json={
        "name": "SPRAY DOSAGE",
        "dosage_number": 50,          # <-- 50 ml
        "dosage_unit": "ml",
        "output_batch_units": 1,      # 1 unit per batch, so cost_price == cost_batch
        "pricing_mode": "margin_first", "margin_pct": 40,
        # Intrants shipped without any quantity — new model.
        "intrants": [{"intrant_id": ids["ICARIDINE"]},
                     {"intrant_id": ids["ALCOOL"]},
                     {"intrant_id": ids["Eau"]}],
    }, timeout=10)
    assert r.status_code == 200, r.text
    rec = r.json()
    # sum(unit_cost) = 3.5 + 0.025 + 0.0004 = 3.5254
    # cost_batch = 3.5254 × 50 = 176.27
    expected_batch = round((3.5000 + 0.0250 + 0.0004) * 50, 4)
    assert abs(rec["intrants_total_batch"] - expected_batch) < 0.001, rec
    assert abs(rec["cost_price"] - expected_batch) < 0.001
    # public_price = cost_price × 1.40
    assert abs(rec["public_price"] - round(expected_batch * 1.40, 2)) < 0.02
    # variant_label auto-derived
    assert rec.get("variant_label") == "50 ml", rec.get("variant_label")
    assert rec.get("dosage_number") == 50.0
    assert rec.get("dosage_unit") == "ml"

    # Update to 100 ml → all intrant costs double.
    r = requests.put(f"{API_URL}/api/production/recipes/{rec['id']}", headers=H, json={
        "name": "SPRAY DOSAGE",
        "dosage_number": 100,
        "dosage_unit": "ml",
        "output_batch_units": 1,
        "pricing_mode": "margin_first", "margin_pct": 40,
        "intrants": [{"intrant_id": ids["ICARIDINE"]},
                     {"intrant_id": ids["ALCOOL"]},
                     {"intrant_id": ids["Eau"]}],
    }, timeout=10)
    assert r.status_code == 200, r.text
    rec2 = r.json()
    expected_100 = round((3.5000 + 0.0250 + 0.0004) * 100, 4)
    assert abs(rec2["intrants_total_batch"] - expected_100) < 0.001, rec2
    assert rec2.get("variant_label") == "100 ml"

    # Legacy recipe (no dosage_number) still works via qty × unit_cost.
    r = requests.post(f"{API_URL}/api/production/recipes", headers=H, json={
        "name": "LEGACY RECIPE",
        "output_batch_units": 1,
        "pricing_mode": "margin_first", "margin_pct": 40,
        # No dosage_number → legacy branch kicks in.
        "intrants": [{"intrant_id": ids["ICARIDINE"], "quantity": 25}],
    }, timeout=10)
    assert r.status_code == 200
    legacy_rec = r.json()
    # cost = 25 × 3.5 = 87.5
    assert abs(legacy_rec["intrants_total_batch"] - 87.5) < 0.01, legacy_rec
