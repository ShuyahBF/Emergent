"""SAWALI — Iteration 8 backend tests.

Coverage:
- GET /api/me/notes/{kind} with author= filter (case-insensitive owner_email)
- GET /api/me/notes/{kind} with q= filter (regex on title/content_html/numero/tags)
- GET /api/me/notes/{kind}?author=X&q=Y combined
- GET /api/me/notes/{kind}/authors → distinct authors sorted by count desc
- /admin/db filters: status__regex, exact match, sort_dir=1
"""
import os
import uuid
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
        assert d.get("dev_otp"), f"dev_otp expected for {email}; got {d}"
        r2 = sess.post(f"{BASE}/api/auth/verify-otp",
                       json={"session_token": d["session_token"], "code": d["dev_otp"]})
        assert r2.status_code == 200, r2.text
        body = r2.json()
        return body["access_token"], body["user"]
    return d["access_token"], d["user"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def admin_tok():
    tok, u = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert u["role"] == "admin"
    return tok


@pytest.fixture(scope="session")
def admin_h(admin_tok):
    return _h(admin_tok)


@pytest.fixture(scope="session")
def seed_reports(admin_h):
    """Seed two reports with distinguishing title/tags content."""
    created = []
    marker = uuid.uuid4().hex[:6]
    for title, tags in [
        (f"TEST_iter8_alpha_{marker}", ["iter8alpha", "shared"]),
        (f"TEST_iter8_beta_{marker}", ["iter8beta", "shared"]),
    ]:
        r = requests.post(
            f"{BASE}/api/me/notes/reports",
            json={"title": title, "content_html": f"<p>body {title}</p>", "tags": tags, "images": []},
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        created.append(r.json())
    yield {"marker": marker, "items": created}
    for it in created:
        try:
            requests.delete(f"{BASE}/api/me/notes/reports/{it['id']}", headers=admin_h)
        except Exception:
            pass


# ---------- /me/notes/{kind} filters ----------
class TestMeNotesFilters:
    def test_author_filter_returns_only_matching(self, admin_h, seed_reports):
        r = requests.get(
            f"{BASE}/api/me/notes/reports",
            params={"author": ADMIN_EMAIL},
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list)
        assert len(items) >= 2  # our 2 seeded
        for it in items:
            assert (it.get("owner_email") or "").lower() == ADMIN_EMAIL.lower(), it

    def test_author_filter_no_match(self, admin_h):
        r = requests.get(
            f"{BASE}/api/me/notes/reports",
            params={"author": f"nobody_{uuid.uuid4().hex[:6]}@nope.test"},
            headers=admin_h,
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_q_search_in_title(self, admin_h, seed_reports):
        marker = seed_reports["marker"]
        r = requests.get(
            f"{BASE}/api/me/notes/reports",
            params={"q": f"alpha_{marker}"},
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        items = r.json()
        assert len(items) == 1
        assert "alpha" in items[0]["title"]

    def test_q_search_in_tags(self, admin_h, seed_reports):
        r = requests.get(
            f"{BASE}/api/me/notes/reports",
            params={"q": "iter8beta"},
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        items = r.json()
        assert len(items) == 1
        assert "beta" in items[0]["title"]

    def test_q_search_in_content(self, admin_h, seed_reports):
        marker = seed_reports["marker"]
        r = requests.get(
            f"{BASE}/api/me/notes/reports",
            params={"q": f"body TEST_iter8_alpha_{marker}"},
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        items = r.json()
        assert len(items) == 1

    def test_author_and_q_combined(self, admin_h, seed_reports):
        marker = seed_reports["marker"]
        r = requests.get(
            f"{BASE}/api/me/notes/reports",
            params={"author": ADMIN_EMAIL, "q": f"beta_{marker}"},
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        items = r.json()
        assert len(items) == 1
        assert items[0]["owner_email"].lower() == ADMIN_EMAIL.lower()
        assert "beta" in items[0]["title"]


# ---------- /me/notes/{kind}/authors ----------
class TestMeNotesAuthors:
    def test_reports_authors(self, admin_h, seed_reports):
        r = requests.get(f"{BASE}/api/me/notes/reports/authors", headers=admin_h)
        assert r.status_code == 200, r.text
        authors = r.json()
        assert isinstance(authors, list)
        emails = [a["email"] for a in authors]
        assert ADMIN_EMAIL in emails
        # check sorted by count desc
        counts = [a["count"] for a in authors]
        assert counts == sorted(counts, reverse=True), counts
        # check shape
        for a in authors:
            assert "email" in a and "count" in a
            assert isinstance(a["count"], int)

    def test_suivis_authors(self, admin_h):
        r = requests.get(f"{BASE}/api/me/notes/suivis/authors", headers=admin_h)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)


# ---------- /admin/db/{collection} extra coverage ----------
class TestAdminDbFilters:
    def test_status_regex_filter(self, admin_h):
        # regex on numeric status field — server coerces; this validates the regex
        # branch. Use a string-typed field 'method' to assert regex semantics.
        r = requests.get(
            f"{BASE}/api/admin/db/api_traces",
            params={"method__regex": "GET", "limit": 20},
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        for it in d["items"]:
            assert "GET" in (it.get("method") or "").upper()

    def test_exact_match(self, admin_h):
        r = requests.get(
            f"{BASE}/api/admin/db/users",
            params={"email": ADMIN_EMAIL, "limit": 5},
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total_matched"] >= 1
        for it in d["items"]:
            assert it.get("email") == ADMIN_EMAIL

    def test_sort_dir_ascending(self, admin_h):
        r = requests.get(
            f"{BASE}/api/admin/db/api_traces",
            params={"sort_by": "created_at", "sort_dir": 1, "limit": 5},
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        if len(items) >= 2:
            ts = [it.get("created_at") for it in items if it.get("created_at")]
            assert ts == sorted(ts), "sort_dir=1 should be ascending"
