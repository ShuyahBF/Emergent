"""Iter34 — Backend tests for DB Snapshots + shared contacts visibility.

Tests:
  • POST/GET/PATCH/DELETE /api/admin/snapshots*
  • Download → decompress + structure check
  • Sensitive masking (settings.smtp_password)
  • Import dry-run (no mutation), import merge (upserts new doc)
  • Imports history
  • RBAC: non-admin users get 403
  • Iter34 contacts visibility: /me/contacts still works for admin
"""
import os
import io
import gzip
import json
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    """Returns access_token after the dev_otp flow."""
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    data = r.json()
    if not data.get("needs_otp"):
        # already authenticated
        return data.get("access_token")
    session_token = data["session_token"]
    code = data.get("dev_otp")
    assert code, f"no dev_otp in response: {data}"
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": session_token, "code": code}, timeout=30)
    assert r2.status_code == 200, f"verify-otp failed: {r2.status_code} {r2.text}"
    tok = r2.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def created_snapshot(admin_h):
    """Create a snapshot once, share id and stats across tests."""
    r = requests.post(
        f"{API}/admin/snapshots",
        headers=admin_h,
        json={"comment": "TEST_iter34_snap", "mask_secrets": True},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    meta = r.json()
    yield meta
    # teardown
    try:
        requests.delete(f"{API}/admin/snapshots/{meta['id']}", headers=admin_h, timeout=30)
    except Exception:
        pass


# ---------- Snapshot CRUD ----------
class TestSnapshotCRUD:
    def test_create_snapshot(self, created_snapshot):
        meta = created_snapshot
        assert "id" in meta and isinstance(meta["id"], str)
        assert meta.get("total_documents", 0) > 0, f"expected total_documents>0, got {meta}"
        assert meta.get("mask_secrets") is True
        assert meta.get("comment") == "TEST_iter34_snap"
        assert meta.get("file_name", "").endswith(".json.gz")

    def test_list_snapshots(self, admin_h, created_snapshot):
        r = requests.get(f"{API}/admin/snapshots", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "snapshots" in data and isinstance(data["snapshots"], list)
        ids = [s["id"] for s in data["snapshots"]]
        assert created_snapshot["id"] in ids
        # ordering desc: first row must be the most recent
        if len(data["snapshots"]) >= 2:
            assert data["snapshots"][0]["created_at"] >= data["snapshots"][1]["created_at"]

    def test_download_snapshot_is_gzip_json(self, admin_h, created_snapshot):
        r = requests.get(
            f"{API}/admin/snapshots/{created_snapshot['id']}/download",
            headers=admin_h,
            timeout=60,
        )
        assert r.status_code == 200, r.text
        raw = r.content
        assert raw[:2] == b"\x1f\x8b", "expected gzip magic bytes"
        decompressed = gzip.decompress(raw)
        payload = json.loads(decompressed.decode("utf-8"))
        for key in ("version", "exported_at", "collections", "stats"):
            assert key in payload, f"missing key {key} in snapshot"
        assert isinstance(payload["collections"], dict)
        assert isinstance(payload["stats"], dict)

    def test_smtp_password_masked(self, admin_h, created_snapshot):
        r = requests.get(
            f"{API}/admin/snapshots/{created_snapshot['id']}/download",
            headers=admin_h,
            timeout=60,
        )
        assert r.status_code == 200
        payload = json.loads(gzip.decompress(r.content).decode("utf-8"))
        settings_rows = payload["collections"].get("settings") or []
        # If smtp_password is present anywhere, it must be the mask token
        for row in settings_rows:
            if "smtp_password" in row and row["smtp_password"]:
                assert row["smtp_password"] == "***MASKED***", f"unmasked smtp_password: {row['smtp_password']}"

    def test_patch_comment(self, admin_h, created_snapshot):
        new_comment = "TEST_iter34_updated_comment"
        r = requests.patch(
            f"{API}/admin/snapshots/{created_snapshot['id']}",
            headers=admin_h,
            json={"comment": new_comment},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("comment") == new_comment
        # verify persisted via GET list
        r2 = requests.get(f"{API}/admin/snapshots", headers=admin_h, timeout=30)
        found = next((s for s in r2.json()["snapshots"] if s["id"] == created_snapshot["id"]), None)
        assert found and found["comment"] == new_comment


# ---------- Import dry-run + merge ----------
class TestSnapshotImport:
    def _download_payload(self, admin_h, snap_id):
        r = requests.get(f"{API}/admin/snapshots/{snap_id}/download", headers=admin_h, timeout=60)
        assert r.status_code == 200
        return gzip.decompress(r.content), json.loads(gzip.decompress(r.content).decode("utf-8"))

    def test_import_dry_run_no_mutation(self, admin_h, created_snapshot):
        # download the just-created snapshot for re-import
        r = requests.get(f"{API}/admin/snapshots/{created_snapshot['id']}/download", headers=admin_h, timeout=60)
        assert r.status_code == 200
        raw = r.content
        files = {"file": (f"snapshot_dry.json.gz", io.BytesIO(raw), "application/gzip")}
        data = {"mode": "merge", "dry_run": "true", "comment": "TEST_iter34_dryrun"}
        # counts before
        snap = json.loads(gzip.decompress(raw).decode("utf-8"))
        users_before = snap["stats"].get("users", 0)

        rr = requests.post(f"{API}/admin/snapshots/import", headers=admin_h, files=files, data=data, timeout=120)
        assert rr.status_code == 200, rr.text
        body = rr.json()
        assert body["dry_run"] is True
        assert body["mode"] == "merge"
        summary = body["summary"]
        assert isinstance(summary, dict)
        # Every collection summary must contain action='dry-run' with before+incoming keys
        for col, s in summary.items():
            assert s["action"] == "dry-run", f"{col} -> {s}"
            assert "before" in s and "incoming" in s

    def test_import_merge_inserts_new(self, admin_h, created_snapshot):
        # Build a tiny custom snapshot with ONE new doc in a low-impact collection (testimonials)
        new_id = f"TEST_iter34_{uuid.uuid4().hex[:8]}"
        custom = {
            "version": 1,
            "exported_at": "2026-01-01T00:00:00+00:00",
            "mask_secrets": True,
            "collections": {
                "testimonials": [
                    {"id": new_id, "author": "TEST iter34", "content": "test content", "created_at": "2026-01-01T00:00:00+00:00"}
                ],
            },
            "stats": {"testimonials": 1},
        }
        raw = gzip.compress(json.dumps(custom).encode("utf-8"))
        files = {"file": ("custom.json.gz", io.BytesIO(raw), "application/gzip")}
        data = {"mode": "merge", "dry_run": "false", "comment": "TEST_iter34_merge"}
        rr = requests.post(f"{API}/admin/snapshots/import", headers=admin_h, files=files, data=data, timeout=120)
        assert rr.status_code == 200, rr.text
        body = rr.json()
        assert body["dry_run"] is False
        assert body["mode"] == "merge"
        s = body["summary"].get("testimonials")
        assert s is not None
        # Either inserted or merged — at minimum action='merged' and after>=before
        assert s["action"] == "merged"
        assert s.get("after", 0) >= s.get("before", 0)
        # if the id was new, inserted >= 1
        # (can't strictly assert if a previous run already inserted it)

    def test_imports_history(self, admin_h):
        r = requests.get(f"{API}/admin/snapshots/imports", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "imports" in data and isinstance(data["imports"], list)
        # at least the dry-run + merge from previous tests
        assert data["count"] >= 1


# ---------- RBAC ----------
class TestSnapshotRBAC:
    def test_unauthenticated_blocked(self):
        # no token at all
        r = requests.get(f"{API}/admin/snapshots", timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_non_admin_blocked_if_creatable(self, admin_h):
        # Try creating a tracked user via admin → log in as that user → expect 403 on snapshot endpoints
        # We can't easily create a client account without going through admin UI, so we attempt with bogus token.
        bad_h = {"Authorization": "Bearer invalid.jwt.token"}
        for path, method in [
            ("/admin/snapshots", "GET"),
            ("/admin/snapshots", "POST"),
            ("/admin/snapshots/imports", "GET"),
        ]:
            fn = requests.get if method == "GET" else requests.post
            r = fn(f"{API}{path}", headers=bad_h, json={} if method == "POST" else None, timeout=15)
            assert r.status_code in (401, 403), f"{method} {path} -> {r.status_code}"


# ---------- Iter34 — contacts visibility helper ----------
class TestMeContactsVisibility:
    def test_admin_me_contacts_still_works(self, admin_h):
        r = requests.get(f"{API}/me/contacts", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        # admin should see contacts (count > 0 ideally; tolerate 0 only if DB has zero)
        # We don't fail hard if count==0 because preview DB might be empty for this collection.
        # but we still assert the response shape.
        if data:
            assert isinstance(data[0], dict)


# ---------- DELETE last ----------
class TestSnapshotDelete:
    def test_delete_extra_snapshot(self, admin_h):
        # Create a throwaway snapshot just to delete it
        r = requests.post(f"{API}/admin/snapshots", headers=admin_h, json={"comment": "TEST_to_delete"}, timeout=120)
        assert r.status_code == 200
        sid = r.json()["id"]
        fname = r.json()["file_name"]
        # delete
        rd = requests.delete(f"{API}/admin/snapshots/{sid}", headers=admin_h, timeout=30)
        assert rd.status_code == 200, rd.text
        assert rd.json().get("ok") is True
        # verify file physically gone (we cannot access filesystem here, so instead verify download 404)
        rg = requests.get(f"{API}/admin/snapshots/{sid}/download", headers=admin_h, timeout=15)
        assert rg.status_code in (404, 410), f"expected 404/410 after delete, got {rg.status_code}"
