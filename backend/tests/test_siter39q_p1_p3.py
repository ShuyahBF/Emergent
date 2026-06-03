"""S-iter39q / S-iter39p — P1 AdminSettings tabs (no backend impact) + P3 Media Library backend CRUD.

Covers:
- POST /api/admin/media-library multipart upload (small PNG) -> 200 + record
- GET  /api/public/media-library returns the uploaded item
- GET  /api/admin/media-library returns the item (admin list)
- PATCH /api/admin/media-library/{id} updates title + public flag
- DELETE /api/admin/media-library/{id} soft-deletes (then absent from listings)
"""
import io
import os
import struct
import zlib

import pytest
import requests


def _load_base_url() -> str:
    v = os.environ.get("REACT_APP_BACKEND_URL") or ""
    if not v:
        try:
            with open("/app/frontend/.env", "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        v = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except OSError:
            pass
    return v.rstrip("/")


BASE_URL = _load_base_url()
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


# ---- Tiny 1x1 PNG (deterministic, no Pillow dep) ----
def _tiny_png() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = b"\x00\xff\x00\x00"  # 1 scanline, 1 pixel RGB red + filter byte
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


@pytest.fixture(scope="module")
def admin_token():
    assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    if body.get("access_token"):
        return body["access_token"]
    assert body.get("needs_otp") and body.get("session_token") and body.get("dev_otp"), \
        f"unexpected login body: {body}"
    r2 = requests.post(f"{BASE_URL}/api/auth/verify-otp",
                       json={"session_token": body["session_token"], "code": body["dev_otp"]},
                       timeout=30)
    assert r2.status_code == 200, f"verify-otp failed: {r2.status_code} {r2.text}"
    tok = r2.json().get("access_token")
    assert tok, f"no access_token in {r2.json()}"
    return tok


@pytest.fixture(scope="module")
def headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def uploaded_media(headers):
    files = {"file": ("TEST_iter39q.png", _tiny_png(), "image/png")}
    data = {"title": "TEST_iter39q image", "description": "iter39q test", "public": "true"}
    r = requests.post(f"{BASE_URL}/api/admin/media-library",
                      headers=headers, files=files, data=data, timeout=60)
    assert r.status_code == 200, f"upload failed: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("id"), body
    assert body.get("kind") == "image", body
    assert body.get("title") == "TEST_iter39q image"
    assert body.get("public") is True
    assert body.get("url"), "url missing"
    assert "_id" not in body, "Mongo _id must not leak"
    yield body
    # Cleanup
    requests.delete(f"{BASE_URL}/api/admin/media-library/{body['id']}", headers=headers, timeout=30)


# ---- P3 — Media Library upload + listing ----
class TestMediaLibrary:
    def test_upload_returns_record(self, uploaded_media):
        assert uploaded_media["filename"] == "TEST_iter39q.png"
        assert uploaded_media["content_type"] in ("image/png",)
        assert uploaded_media["size"] > 0

    def test_public_listing_contains_item(self, uploaded_media):
        r = requests.get(f"{BASE_URL}/api/public/media-library", timeout=30)
        assert r.status_code == 200, r.text
        ids = [i.get("id") for i in r.json().get("items", [])]
        assert uploaded_media["id"] in ids, f"uploaded id missing from public list (count={len(ids)})"

    def test_admin_listing_contains_item(self, uploaded_media, headers):
        r = requests.get(f"{BASE_URL}/api/admin/media-library", headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        ids = [i.get("id") for i in r.json().get("items", [])]
        assert uploaded_media["id"] in ids

    def test_patch_updates_title_and_public(self, uploaded_media, headers):
        mid = uploaded_media["id"]
        r = requests.patch(f"{BASE_URL}/api/admin/media-library/{mid}",
                           headers={**headers, "Content-Type": "application/json"},
                           json={"title": "TEST_iter39q renamed", "public": False}, timeout=30)
        assert r.status_code == 200, r.text
        # Verify via admin listing
        r2 = requests.get(f"{BASE_URL}/api/admin/media-library", headers=headers, timeout=30)
        found = next((i for i in r2.json()["items"] if i.get("id") == mid), None)
        assert found, "media missing after patch"
        assert found["title"] == "TEST_iter39q renamed"
        assert found["public"] is False
        # Verify it disappeared from public listing
        rp = requests.get(f"{BASE_URL}/api/public/media-library", timeout=30)
        pub_ids = [i.get("id") for i in rp.json().get("items", [])]
        assert mid not in pub_ids, "non-public item still listed in /public"

    def test_delete_soft_removes(self, headers):
        # Create dedicated item to delete
        files = {"file": ("TEST_iter39q_del.png", _tiny_png(), "image/png")}
        data = {"title": "TEST_iter39q deletable", "public": "true"}
        r = requests.post(f"{BASE_URL}/api/admin/media-library",
                          headers=headers, files=files, data=data, timeout=60)
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        # Delete
        rd = requests.delete(f"{BASE_URL}/api/admin/media-library/{mid}", headers=headers, timeout=30)
        assert rd.status_code == 200, rd.text
        assert rd.json().get("ok") is True
        # Verify gone from both listings
        for url in (f"{BASE_URL}/api/public/media-library",
                    f"{BASE_URL}/api/admin/media-library"):
            h = headers if "/admin/" in url else {}
            rr = requests.get(url, headers=h, timeout=30)
            ids = [i.get("id") for i in rr.json().get("items", [])]
            assert mid not in ids, f"deleted item still in {url}"
        # Second delete must 404
        rd2 = requests.delete(f"{BASE_URL}/api/admin/media-library/{mid}", headers=headers, timeout=30)
        assert rd2.status_code == 404, rd2.text

    def test_upload_requires_auth(self):
        files = {"file": ("x.png", _tiny_png(), "image/png")}
        data = {"title": "no auth"}
        r = requests.post(f"{BASE_URL}/api/admin/media-library", files=files, data=data, timeout=30)
        assert r.status_code in (401, 403), r.status_code

    def test_upload_rejects_unsupported_mime(self, headers):
        files = {"file": ("evil.exe", b"MZ\x00\x00", "application/octet-stream")}
        data = {"title": "bad"}
        r = requests.post(f"{BASE_URL}/api/admin/media-library",
                          headers=headers, files=files, data=data, timeout=30)
        assert r.status_code == 400, r.text
