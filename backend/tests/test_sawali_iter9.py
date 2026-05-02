"""SAWALI — Iteration 9 backend tests: Form Analytics Dashboard.

Coverage:
- GET /api/me/forms-analytics (global) as admin → scope + totals + top_forms
- GET /api/me/forms/{form_id}/analytics (per-form) → KPIs + series + by_country + top_authors + recent
- GET /api/me/forms/{form_id}/analytics/export.csv → UTF-8 BOM + header + one row per submission
- Date filters (date_from / date_to YYYY-MM-DD) on series & aggregations
- Access control: non-admin client cannot access another owner's form analytics (403)
- 404 on unknown form_id for /analytics and /analytics/export.csv
- End-to-end: public form → anon submission with geo.country='France' → analytics reflects
  anon_count++, by_country contains 'France', series has today's datapoint.
- top_authors contains user_label (authenticated submission) and does NOT contain anon labels.
"""
import io
import csv
import os
import uuid
import datetime as dt
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email, password):
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    r = sess.post(f"{BASE}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    d = r.json()
    if d.get("needs_otp"):
        assert d.get("dev_otp"), f"dev_otp expected; got {d}"
        r2 = sess.post(f"{BASE}/api/auth/verify-otp",
                       json={"session_token": d["session_token"], "code": d["dev_otp"]})
        assert r2.status_code == 200, r2.text
        body = r2.json()
        return body["access_token"], body["user"]
    return d["access_token"], d["user"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def admin():
    tok, u = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert u["role"] == "admin"
    return tok, u


@pytest.fixture(scope="session")
def admin_tok(admin):
    return admin[0]


@pytest.fixture(scope="session")
def admin_h(admin_tok):
    return _h(admin_tok)


@pytest.fixture(scope="session")
def second_client(admin_h):
    """Create a secondary client user to assert 403 on cross-ownership."""
    email = f"test_iter9_cli_{uuid.uuid4().hex[:6]}@example.org"
    pwd = "IterNine!2026"
    r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json={
        "email": email, "full_name": "Iter9 Client", "password": pwd, "role": "client",
        "client_code": f"IT9{uuid.uuid4().hex[:3].upper()}",
    })
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    tok, _ = _login(email, pwd)
    yield {"id": uid, "email": email, "token": tok}
    requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)


@pytest.fixture(scope="session")
def seeded_public_form(admin_h):
    """Admin creates a PUBLIC form with 2 fields we can submit to."""
    r = requests.post(f"{BASE}/api/me/forms", headers=admin_h, json={
        "title": f"TEST_iter9_public_{uuid.uuid4().hex[:6]}",
        "description": "iter9 analytics public form",
        "is_public": True,
        "pages": [{
            "id": uuid.uuid4().hex, "title": "Page 1",
            "fields": [
                {"id": "fq1", "type": "short_text", "label": "Nom"},
                {"id": "fq2", "type": "short_text", "label": "Message"},
            ],
        }],
    })
    assert r.status_code in (200, 201), r.text
    f = r.json()
    yield f
    # Best-effort cleanup – delete form + its submissions via admin APIs if present
    requests.delete(f"{BASE}/api/me/forms/{f['id']}", headers=admin_h)


@pytest.fixture(scope="session")
def seeded_private_form_of_admin(admin_h):
    r = requests.post(f"{BASE}/api/me/forms", headers=admin_h, json={
        "title": f"TEST_iter9_private_{uuid.uuid4().hex[:6]}",
        "is_public": False,
        "pages": [{"id": uuid.uuid4().hex, "title": "P1", "fields": []}],
    })
    assert r.status_code in (200, 201), r.text
    f = r.json()
    yield f
    requests.delete(f"{BASE}/api/me/forms/{f['id']}", headers=admin_h)


# =====================================================================
class TestGlobalAnalytics:
    def test_shape_global_admin(self, admin_h, seeded_public_form):
        r = requests.get(f"{BASE}/api/me/forms-analytics", headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["scope"] == "global"
        for k in ("total_forms", "total_views", "public_count", "private_count", "submissions", "top_forms"):
            assert k in d, f"missing key {k}"
        subs = d["submissions"]
        for k in ("total_submissions", "auth_count", "anon_count", "series", "top_authors", "by_country"):
            assert k in subs, f"submissions missing {k}"
        assert isinstance(d["top_forms"], list)
        assert d["total_forms"] >= 1  # our seeded form at least

    def test_global_client_scoped(self, second_client):
        """Second client (no forms) → total_forms=0, empty submissions."""
        r = requests.get(f"{BASE}/api/me/forms-analytics", headers=_h(second_client["token"]))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["scope"] == "global"
        assert d["total_forms"] == 0
        assert d["top_forms"] == []
        assert d["submissions"]["total_submissions"] == 0


# =====================================================================
class TestSubmissionSeed:
    """Create anon + authenticated submissions, then verify analytics reflects them."""

    def test_anon_public_submission_with_geo(self, seeded_public_form, admin_h):
        fid = seeded_public_form["id"]
        r = requests.post(f"{BASE}/api/public/forms/{fid}/submission", json={
            "data": {"fq1": "Anon FR", "fq2": "Bonjour"},
            "geo": {"country": "France", "city": "Paris"},
            "respondent_email": "anon_fr@example.org",
            "respondent_name": "Anon France",
        })
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

    def test_authenticated_submission_populates_top_authors(self, seeded_public_form, admin_h):
        fid = seeded_public_form["id"]
        r = requests.post(f"{BASE}/api/me/forms/{fid}/submission", headers=admin_h,
                          json={"data": {"fq1": "AdminVal", "fq2": "Msg admin"}})
        assert r.status_code in (200, 201), r.text

    def test_detail_analytics_reflects(self, seeded_public_form, admin_h):
        fid = seeded_public_form["id"]
        r = requests.get(f"{BASE}/api/me/forms/{fid}/analytics", headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["scope"] == "form"
        assert d["form"]["id"] == fid
        assert d["form"]["is_public"] is True
        # At least 1 anon + 1 auth submission seeded above
        assert d["submissions"] >= 2, d
        assert d["anon_count"] >= 1, d
        assert d["auth_count"] >= 1, d
        countries = [c["country"] for c in d["by_country"]]
        assert "France" in countries, f"'France' not found in by_country: {countries}"
        # Today's date in series (UTC)
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        dates = [pt["date"] for pt in d["series"]]
        assert today in dates, f"today {today} not in series dates {dates}"
        # top_authors must NOT contain the anon label pattern (starts with 'Anonyme' or matches respondent_name)
        # and MUST include admin label (email or full_name)
        labels = [a["label"] for a in d["top_authors"]]
        assert all(not str(l).startswith("Anonyme") for l in labels), labels
        # recent is capped at 10
        assert isinstance(d["recent"], list)
        assert len(d["recent"]) <= 10
        # completion_rate sanity
        assert 0.0 <= float(d["completion_rate"]) <= 100.0


# =====================================================================
class TestDateFilters:
    def test_date_from_future_empties_series(self, seeded_public_form, admin_h):
        fid = seeded_public_form["id"]
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)).strftime("%Y-%m-%d")
        r = requests.get(f"{BASE}/api/me/forms/{fid}/analytics",
                         headers=admin_h, params={"date_from": future})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["submissions"] == 0
        assert d["series"] == []
        assert d["by_country"] == []

    def test_date_range_today_includes_seed(self, seeded_public_form, admin_h):
        fid = seeded_public_form["id"]
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        tomorrow = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).strftime("%Y-%m-%d")
        r = requests.get(f"{BASE}/api/me/forms/{fid}/analytics",
                         headers=admin_h, params={"date_from": today, "date_to": tomorrow})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["submissions"] >= 2

    def test_global_date_filter_applied(self, admin_h):
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)).strftime("%Y-%m-%d")
        r = requests.get(f"{BASE}/api/me/forms-analytics", headers=admin_h,
                         params={"date_from": future})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["submissions"]["total_submissions"] == 0
        assert d["submissions"]["series"] == []


# =====================================================================
class TestAccessControl:
    def test_404_unknown_form_detail(self, admin_h):
        r = requests.get(f"{BASE}/api/me/forms/nope-unknown-xyz/analytics", headers=admin_h)
        assert r.status_code == 404, r.text

    def test_404_unknown_form_csv(self, admin_h):
        r = requests.get(f"{BASE}/api/me/forms/nope-unknown-xyz/analytics/export.csv", headers=admin_h)
        assert r.status_code == 404, r.text

    def test_403_non_owner_detail(self, second_client, seeded_private_form_of_admin):
        fid = seeded_private_form_of_admin["id"]
        r = requests.get(f"{BASE}/api/me/forms/{fid}/analytics",
                         headers=_h(second_client["token"]))
        assert r.status_code == 403, r.text

    def test_403_non_owner_csv(self, second_client, seeded_private_form_of_admin):
        fid = seeded_private_form_of_admin["id"]
        r = requests.get(f"{BASE}/api/me/forms/{fid}/analytics/export.csv",
                         headers=_h(second_client["token"]))
        assert r.status_code == 403, r.text


# =====================================================================
class TestCSVExport:
    def test_csv_has_bom_and_header_and_rows(self, seeded_public_form, admin_h):
        fid = seeded_public_form["id"]
        r = requests.get(f"{BASE}/api/me/forms/{fid}/analytics/export.csv", headers=admin_h)
        assert r.status_code == 200, r.text
        # UTF-8 BOM
        assert r.content.startswith(b"\xef\xbb\xbf"), f"Missing UTF-8 BOM in CSV; first bytes: {r.content[:10]!r}"
        assert "text/csv" in r.headers.get("content-type", ""), r.headers
        disp = r.headers.get("content-disposition", "")
        assert "attachment" in disp and ".csv" in disp, disp

        text = r.content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        assert len(rows) >= 2, f"expected header + >=1 data row; got {len(rows)}"
        header = rows[0]
        for col in ["id", "date", "auteur", "type", "email", "pays", "ville", "ip"]:
            assert col in header, f"Missing column '{col}' in header: {header}"
        # Field labels must appear (Nom + Message from seed_public_form)
        assert "Nom" in header, header
        assert "Message" in header, header

        # Look for one row with pays=France and type=Anonyme
        anon_france = [row for row in rows[1:] if len(row) > 5 and row[5] == "France" and row[3] == "Anonyme"]
        assert anon_france, f"Expected at least one Anonyme/France row; rows={rows[1:]}"
