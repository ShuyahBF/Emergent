"""Iter23 SAWALI backend tests — Forms enhancements (Lot B-2).

Coverage:
 (A) POST /me/forms/{form_id}/upload — multipart file
     - 200 on small file → returns {ok, file_id, filename, size, content_type, public_url}
     - 413 on > 1 Mo
     - 400 on empty file
     - 404 on unknown form
     - public_url is reachable via /api/files/{id}.{ext}
 (B) PUT /me/forms/{id} — FormField with type=table & columns=[{key,label,type}]
 (C) PUT /me/forms/{id} — FormField with type=file & accept='.pdf,image/*'
 (D) PUT /me/forms/{id} — FormField with type=signature
 (E) GET /me/forms/{id} — pages.fields preserve columns + accept after roundtrip
"""
from __future__ import annotations

import io
import os
import uuid
from typing import Optional

import pytest
import requests


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login_with_otp(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    data = r.json()
    code = data.get("dev_otp")
    assert code, f"dev_otp missing for {email}: {data}"
    v = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": data["session_token"], "code": code},
        timeout=15,
    )
    v.raise_for_status()
    return v.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers() -> dict:
    tok = _login_with_otp(ADMIN_EMAIL, ADMIN_PASSWORD)
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="session")
def form_id(admin_headers) -> str:
    """Create a fresh form for the test session and return its id.
    Cleaned up at the end."""
    payload = {"title": f"TEST_iter23_{uuid.uuid4().hex[:6]}", "description": "iter23 fixture"}
    r = requests.post(f"{API}/me/forms", headers=admin_headers, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    yield fid
    # cleanup
    requests.delete(f"{API}/me/forms/{fid}", headers=admin_headers, timeout=15)


# ============================================================
# (A) /me/forms/{form_id}/upload — multipart file
# ============================================================
class TestFormUpload:
    def test_upload_small_file_ok(self, admin_headers, form_id):
        small = b"hello world" * 10  # ~110 bytes
        files = {"file": ("hello.txt", io.BytesIO(small), "text/plain")}
        r = requests.post(
            f"{API}/me/forms/{form_id}/upload",
            headers=admin_headers,
            files=files,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # response shape
        for k in ("ok", "file_id", "filename", "size", "content_type", "public_url"):
            assert k in body, f"missing {k} in response: {body}"
        assert body["ok"] is True
        assert body["filename"] == "hello.txt"
        assert body["size"] == len(small)
        assert "text" in (body["content_type"] or "")
        assert body["public_url"].startswith("http")
        assert f"/api/files/{body['file_id']}" in body["public_url"]
        # public_url must be reachable (returns the bytes)
        rr = requests.get(body["public_url"], timeout=15)
        assert rr.status_code == 200, rr.text
        assert rr.content == small

    def test_upload_too_large_413(self, admin_headers, form_id):
        # > 1 Mo (1024*1024)
        big = b"x" * (1024 * 1024 + 10)
        files = {"file": ("big.bin", io.BytesIO(big), "application/octet-stream")}
        r = requests.post(
            f"{API}/me/forms/{form_id}/upload",
            headers=admin_headers,
            files=files,
            timeout=30,
        )
        assert r.status_code == 413, f"expected 413 got {r.status_code} {r.text}"
        assert "Mo" in r.text or "volumin" in r.text.lower()

    def test_upload_empty_400(self, admin_headers, form_id):
        files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
        r = requests.post(
            f"{API}/me/forms/{form_id}/upload",
            headers=admin_headers,
            files=files,
            timeout=15,
        )
        assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text}"

    def test_upload_unknown_form_404(self, admin_headers):
        files = {"file": ("hello.txt", io.BytesIO(b"abc"), "text/plain")}
        r = requests.post(
            f"{API}/me/forms/{uuid.uuid4().hex}/upload",
            headers=admin_headers,
            files=files,
            timeout=15,
        )
        assert r.status_code == 404, f"expected 404 got {r.status_code} {r.text}"


# ============================================================
# (B)(C)(D)(E) FormField type=table|file|signature roundtrip via PUT /me/forms/{id}
# ============================================================
class TestFormFieldsTypes:
    def _build_pages(self, fields):
        return [{"id": uuid.uuid4().hex, "title": "Page 1", "fields": fields}]

    def test_put_with_table_columns_roundtrip(self, admin_headers, form_id):
        f_table = {
            "id": "f_table_1",
            "type": "table",
            "label": "Articles",
            "required": False,
            "col_start": 1,
            "col_span": 12,
            "row": 0,
            "columns": [
                {"key": "name", "label": "Nom", "type": "text"},
                {"key": "qty", "label": "Quantité", "type": "number"},
                {"key": "due", "label": "Échéance", "type": "date"},
            ],
        }
        r = requests.put(
            f"{API}/me/forms/{form_id}",
            headers=admin_headers,
            json={"pages": self._build_pages([f_table])},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        # GET to verify persistence
        g = requests.get(f"{API}/me/forms/{form_id}", headers=admin_headers, timeout=15)
        assert g.status_code == 200
        page0 = g.json()["pages"][0]
        fld = page0["fields"][0]
        assert fld["type"] == "table"
        assert isinstance(fld.get("columns"), list)
        assert len(fld["columns"]) == 3
        assert fld["columns"][1]["key"] == "qty"
        assert fld["columns"][1]["type"] == "number"

    def test_put_with_file_accept_roundtrip(self, admin_headers, form_id):
        f_file = {
            "id": "f_file_1",
            "type": "file",
            "label": "Pièce jointe",
            "required": False,
            "col_start": 1,
            "col_span": 6,
            "row": 1,
            "accept": ".pdf,image/*",
        }
        r = requests.put(
            f"{API}/me/forms/{form_id}",
            headers=admin_headers,
            json={"pages": self._build_pages([f_file])},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        g = requests.get(f"{API}/me/forms/{form_id}", headers=admin_headers, timeout=15)
        page0 = g.json()["pages"][0]
        fld = page0["fields"][0]
        assert fld["type"] == "file"
        assert fld.get("accept") == ".pdf,image/*"

    def test_put_with_signature_roundtrip(self, admin_headers, form_id):
        f_sig = {
            "id": "f_sig_1",
            "type": "signature",
            "label": "Signature",
            "required": True,
            "col_start": 1,
            "col_span": 12,
            "row": 2,
        }
        r = requests.put(
            f"{API}/me/forms/{form_id}",
            headers=admin_headers,
            json={"pages": self._build_pages([f_sig])},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        g = requests.get(f"{API}/me/forms/{form_id}", headers=admin_headers, timeout=15)
        fld = g.json()["pages"][0]["fields"][0]
        assert fld["type"] == "signature"
        assert fld["required"] is True

    def test_put_combo_three_types(self, admin_headers, form_id):
        """Final test: persist all three new types together."""
        fields = [
            {
                "id": "f_combo_table",
                "type": "table",
                "label": "Lignes",
                "col_start": 1, "col_span": 12, "row": 0,
                "columns": [{"key": "x", "label": "X", "type": "text"}],
            },
            {
                "id": "f_combo_file",
                "type": "file",
                "label": "Doc",
                "col_start": 1, "col_span": 6, "row": 1,
                "accept": ".pdf",
            },
            {
                "id": "f_combo_sig",
                "type": "signature",
                "label": "Sig",
                "col_start": 7, "col_span": 6, "row": 1,
            },
        ]
        r = requests.put(
            f"{API}/me/forms/{form_id}",
            headers=admin_headers,
            json={"pages": [{"id": "p1", "title": "P1", "fields": fields}]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        g = requests.get(f"{API}/me/forms/{form_id}", headers=admin_headers, timeout=15)
        all_fields = g.json()["pages"][0]["fields"]
        types = [f["type"] for f in all_fields]
        assert "table" in types and "file" in types and "signature" in types
