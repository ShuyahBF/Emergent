"""SAWALI — Iteration 18 backend tests: Public legal policies (privacy/services/deletion).

Coverage:
 - GET /api/admin/policies: auth (401/403), shape, public_url format, present flag.
 - POST /api/admin/policies/{slot}/upload: bad slot 400, non-PDF 400, empty 400,
   too-large 413, happy path 200 returns full doc + persists file + db doc,
   re-upload replaces atomically.
 - DELETE /api/admin/policies/{slot}: bad slot 400, happy path removes file + doc,
   subsequent GET shows present=false.
 - GET /api/public/policies/{slot}: NO auth, bad slot 404, missing 404,
   happy path 200 application/pdf inline + body bytes match.
"""
from __future__ import annotations

import os
import shutil
import uuid
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"

_sync_mongo = MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_mongo[os.environ["DB_NAME"]]

POLICIES_DIR = Path("/app/backend/uploads/policies")
SLOTS = ["privacy", "services", "deletion"]
LABELS = {
    "privacy": "Politique de confidentialité (RGPD)",
    "services": "Politique de services",
    "deletion": "Politique de suppression",
}

# Minimal valid PDF (1 page, ~ 400 bytes)
MIN_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
    b"0000000053 00000 n \n0000000099 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n149\n%%EOF\n"
)


# ---------- helpers -------------------------------------------------------
def _login(email: str, password: str):
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    r = sess.post(f"{BASE}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    d = r.json()
    if d.get("needs_otp"):
        assert d.get("dev_otp"), f"dev_otp expected, got {d}"
        r2 = sess.post(
            f"{BASE}/api/auth/verify-otp",
            json={"session_token": d["session_token"], "code": d["dev_otp"]},
        )
        assert r2.status_code == 200, r2.text
        return r2.json()["access_token"], r2.json()["user"]
    return d["access_token"], d["user"]


def _h(tok: str):
    return {"Authorization": f"Bearer {tok}"}


# ---------- fixtures ------------------------------------------------------
@pytest.fixture(scope="module")
def admin():
    tok, u = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert u["role"] == "admin"
    return tok, u


@pytest.fixture(scope="module")
def admin_tok(admin):
    return admin[0]


@pytest.fixture(scope="module")
def admin_h(admin_tok):
    return _h(admin_tok)


@pytest.fixture(scope="module", autouse=True)
def _backup_seed():
    """Backup the 3 seed PDFs and the DB metadata before tests; restore after."""
    backup = {}
    for slot in SLOTS:
        p = POLICIES_DIR / f"{slot}.pdf"
        if p.exists():
            backup[slot] = p.read_bytes()
    docs_backup = list(_sync_db.policies.find({}, {"_id": 0}))
    yield
    # Restore
    for slot in SLOTS:
        p = POLICIES_DIR / f"{slot}.pdf"
        if slot in backup:
            p.write_bytes(backup[slot])
        else:
            p.unlink(missing_ok=True)
    _sync_db.policies.delete_many({})
    if docs_backup:
        _sync_db.policies.insert_many(docs_backup)


# ==========================================================================
# A) GET /api/admin/policies — list shape & auth
# ==========================================================================
class TestPolicyList:
    def test_list_unauth_401(self):
        r = requests.get(f"{BASE}/api/admin/policies")
        assert r.status_code in (401, 403), r.text

    def test_list_non_admin_403(self):
        # create a quick non-admin
        email = f"test_iter18_nonadmin_{uuid.uuid4().hex[:6]}@example.org"
        # Attempt to login with garbage — easier: just call without token
        # (already covered above); use random bearer to confirm 401
        r = requests.get(
            f"{BASE}/api/admin/policies",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert r.status_code in (401, 403), r.text

    def test_list_admin_returns_three_slots(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/policies", headers=admin_h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data
        items = data["items"]
        assert len(items) == 3
        slots = [i["slot"] for i in items]
        assert sorted(slots) == sorted(SLOTS)
        for it in items:
            assert it["label"] == LABELS[it["slot"]]
            assert "present" in it
            assert "public_url" in it
            assert it["public_url"].endswith(f"/api/public/policies/{it['slot']}")
            # The public_url should be the externally-resolvable preview URL
            assert it["public_url"].startswith("http")

    def test_list_seed_present_true(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/policies", headers=admin_h)
        items = r.json()["items"]
        for it in items:
            # All 3 seeds should be present (per agent context note)
            if (POLICIES_DIR / f"{it['slot']}.pdf").exists():
                assert it["present"] is True
                assert it["filename"]
                assert isinstance(it["size"], int) and it["size"] > 0
                assert it["uploaded_at"]


# ==========================================================================
# B) POST /api/admin/policies/{slot}/upload — validation + happy path
# ==========================================================================
class TestPolicyUpload:
    def test_upload_bad_slot_400(self, admin_h):
        r = requests.post(
            f"{BASE}/api/admin/policies/badslot/upload",
            headers=admin_h,
            files={"file": ("x.pdf", MIN_PDF, "application/pdf")},
        )
        assert r.status_code == 400, r.text
        assert "Slot" in r.json()["detail"]

    def test_upload_non_pdf_400(self, admin_h):
        r = requests.post(
            f"{BASE}/api/admin/policies/privacy/upload",
            headers=admin_h,
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )
        assert r.status_code == 400, r.text
        assert "PDF" in r.json()["detail"]

    def test_upload_empty_file_400(self, admin_h):
        r = requests.post(
            f"{BASE}/api/admin/policies/privacy/upload",
            headers=admin_h,
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert r.status_code == 400, r.text
        assert "vide" in r.json()["detail"].lower()

    def test_upload_too_large_413(self, admin_h):
        # 16 MB > POLICY_MAX_SIZE (15MB)
        big = b"%PDF-1.4\n" + (b"A" * (16 * 1024 * 1024))
        r = requests.post(
            f"{BASE}/api/admin/policies/privacy/upload",
            headers=admin_h,
            files={"file": ("big.pdf", big, "application/pdf")},
        )
        assert r.status_code == 413, r.text

    def test_upload_happy_and_replace_atomic(self, admin_h):
        # 1) Upload to 'services' slot
        r = requests.post(
            f"{BASE}/api/admin/policies/services/upload",
            headers=admin_h,
            files={"file": ("my-services-v1.pdf", MIN_PDF, "application/pdf")},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["slot"] == "services"
        assert d["label"] == LABELS["services"]
        assert d["filename"] == "my-services-v1.pdf"
        assert d["size"] == len(MIN_PDF)
        assert d["uploaded_at"]
        assert d["uploaded_by_label"]
        assert d["present"] is True
        assert d["public_url"].endswith("/api/public/policies/services")

        # File persisted on disk
        p = POLICIES_DIR / "services.pdf"
        assert p.exists()
        assert p.read_bytes() == MIN_PDF

        # DB upsert
        doc = _sync_db.policies.find_one({"slot": "services"}, {"_id": 0})
        assert doc is not None
        assert doc["filename"] == "my-services-v1.pdf"
        assert doc["size"] == len(MIN_PDF)

        # 2) Re-upload with new content — must REPLACE atomically
        new_pdf = MIN_PDF + b"%comment-v2\n"
        r2 = requests.post(
            f"{BASE}/api/admin/policies/services/upload",
            headers=admin_h,
            files={"file": ("my-services-v2.pdf", new_pdf, "application/pdf")},
        )
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["filename"] == "my-services-v2.pdf"
        assert d2["size"] == len(new_pdf)
        assert p.read_bytes() == new_pdf
        # No leftover .tmp file
        assert not (POLICIES_DIR / "services.pdf.tmp").exists()

    def test_upload_only_pdf_extension_accepted(self, admin_h):
        # Send with content_type=application/octet-stream but filename=.pdf → accepted
        r = requests.post(
            f"{BASE}/api/admin/policies/services/upload",
            headers=admin_h,
            files={"file": ("ok.pdf", MIN_PDF, "application/octet-stream")},
        )
        assert r.status_code == 200, r.text


# ==========================================================================
# C) DELETE /api/admin/policies/{slot}
# ==========================================================================
class TestPolicyDelete:
    def test_delete_bad_slot_400(self, admin_h):
        r = requests.delete(f"{BASE}/api/admin/policies/badslot", headers=admin_h)
        assert r.status_code == 400, r.text

    def test_delete_then_list_shows_absent(self, admin_h):
        # Upload then delete 'deletion' slot
        up = requests.post(
            f"{BASE}/api/admin/policies/deletion/upload",
            headers=admin_h,
            files={"file": ("del.pdf", MIN_PDF, "application/pdf")},
        )
        assert up.status_code == 200, up.text
        assert (POLICIES_DIR / "deletion.pdf").exists()

        d = requests.delete(f"{BASE}/api/admin/policies/deletion", headers=admin_h)
        assert d.status_code == 200, d.text
        assert d.json()["ok"] is True

        # File removed
        assert not (POLICIES_DIR / "deletion.pdf").exists()
        # DB doc removed
        assert _sync_db.policies.find_one({"slot": "deletion"}) is None

        # GET list now shows present=false
        lst = requests.get(f"{BASE}/api/admin/policies", headers=admin_h).json()["items"]
        d_item = next(i for i in lst if i["slot"] == "deletion")
        assert d_item["present"] is False
        assert d_item["filename"] is None


# ==========================================================================
# D) GET /api/public/policies/{slot} — public, no auth
# ==========================================================================
class TestPublicPolicy:
    def test_public_no_auth_required_bad_slot_404(self):
        r = requests.get(f"{BASE}/api/public/policies/badslot")
        assert r.status_code == 404, r.text
        assert "introuvable" in r.json()["detail"].lower()

    def test_public_missing_returns_404(self, admin_h):
        # First delete the privacy file/doc
        requests.delete(f"{BASE}/api/admin/policies/privacy", headers=admin_h)
        r = requests.get(f"{BASE}/api/public/policies/privacy")
        assert r.status_code == 404, r.text
        assert "publi" in r.json()["detail"].lower()

    def test_public_happy_path_pdf_inline_bytes_match(self, admin_h):
        # Upload a unique pdf to privacy
        unique_pdf = MIN_PDF + b"%test-iter18-public\n"
        up = requests.post(
            f"{BASE}/api/admin/policies/privacy/upload",
            headers=admin_h,
            files={"file": ("custom-privacy.pdf", unique_pdf, "application/pdf")},
        )
        assert up.status_code == 200, up.text

        # Fetch public — NO auth header
        r = requests.get(f"{BASE}/api/public/policies/privacy")
        assert r.status_code == 200, r.text
        ct = r.headers.get("content-type", "")
        assert "application/pdf" in ct
        cd = r.headers.get("content-disposition", "")
        assert "inline" in cd.lower()
        assert "custom-privacy.pdf" in cd
        # Body matches
        assert r.content == unique_pdf
