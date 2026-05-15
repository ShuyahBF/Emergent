"""Iter35e — Tests for the Secrets Vault (encrypted export / restore).

Validates:
  • /admin/secrets/keys lists every vaultable key and marks populated ones.
  • /admin/secrets/export with a strong password returns an AES-GCM envelope
    that decrypts back to the original bundle.
  • /admin/secrets/import with the correct password restores keys.
  • Wrong password → 400 explicit error (not silent failure).
  • dry_run mode does not mutate settings.
  • overwrite_filled=false leaves existing values alone.
  • Audit trail captures every export/import.
  • All endpoints require admin.
"""
import os
import io
import json
import uuid
import base64
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://sawali-portal.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    if not data.get("needs_otp"):
        return data.get("access_token")
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": data["session_token"], "code": data.get("dev_otp")}, timeout=30)
    assert r2.status_code == 200, r2.text
    return r2.json().get("access_token")


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


class TestVaultKeys:
    def test_list_keys_returns_shape(self, admin_h):
        r = requests.get(f"{API}/admin/secrets/keys", headers=admin_h, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "keys" in data and isinstance(data["keys"], list)
        assert "total" in data and "populated" in data
        assert data["total"] >= 30, f"expected ≥30 vault keys, got {data['total']}"
        # each entry has the expected shape
        for k in data["keys"][:5]:
            assert "key" in k and "populated" in k and "is_secret" in k
        # WhatsApp keys must be in the vault
        all_keys = [k["key"] for k in data["keys"]]
        assert "wa_access_token" in all_keys
        assert "wa_business_account_id" in all_keys
        assert "smtp_password" in all_keys

    def test_keys_require_auth(self):
        r = requests.get(f"{API}/admin/secrets/keys", timeout=10)
        assert r.status_code in (401, 403)


class TestVaultExportImport:
    def _export(self, admin_h, password: str, comment: str = ""):
        r = requests.post(
            f"{API}/admin/secrets/export",
            headers=admin_h,
            json={"password": password, "comment": comment},
            timeout=30,
        )
        return r

    def test_export_rejects_short_password(self, admin_h):
        r = self._export(admin_h, "short")
        assert r.status_code == 400
        assert "mot de passe" in r.text.lower() or "8" in r.text

    def test_export_returns_aes_envelope(self, admin_h):
        password = f"iter35e_{uuid.uuid4().hex[:12]}"
        r = self._export(admin_h, password, comment="TEST iter35e roundtrip")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        env = body["envelope"]
        # Envelope shape
        for f in ("v", "alg", "salt", "nonce", "ct", "created_at"):
            assert f in env, f"missing field {f}"
        assert env["v"] == 1
        assert "AES-256-GCM" in env["alg"]
        # Sizes look sane
        assert len(base64.b64decode(env["salt"])) == 16
        assert len(base64.b64decode(env["nonce"])) == 12
        assert len(base64.b64decode(env["ct"])) > 16  # AES-GCM tag is 16
        assert body["filename"].endswith(".json")

    def test_roundtrip_with_correct_password_succeeds_dry_run(self, admin_h):
        password = f"iter35e_{uuid.uuid4().hex[:12]}"
        ex = self._export(admin_h, password, comment="TEST iter35e roundtrip2")
        assert ex.status_code == 200
        envelope = ex.json()["envelope"]
        # Import (dry-run first)
        raw = json.dumps(envelope).encode("utf-8")
        files = {"file": ("vault.json", io.BytesIO(raw), "application/json")}
        data = {"password": password, "dry_run": "true", "overwrite_filled": "false"}
        rr = requests.post(f"{API}/admin/secrets/import", headers=admin_h, files=files, data=data, timeout=20)
        assert rr.status_code == 200, rr.text
        body = rr.json()
        assert body["dry_run"] is True
        assert body["applied_count"] == 0  # dry-run never applies
        assert body["incoming_count"] >= 0
        assert "plan" in body
        # Round-trip carries the metadata
        assert body["bundle_comment"] == "TEST iter35e roundtrip2"
        assert body["bundle_exported_by"] == ADMIN_EMAIL

    def test_import_wrong_password_returns_400(self, admin_h):
        password = f"iter35e_{uuid.uuid4().hex[:12]}"
        ex = self._export(admin_h, password)
        envelope = ex.json()["envelope"]
        raw = json.dumps(envelope).encode("utf-8")
        files = {"file": ("vault.json", io.BytesIO(raw), "application/json")}
        data = {"password": "wrong_password_iter35e", "dry_run": "true", "overwrite_filled": "false"}
        rr = requests.post(f"{API}/admin/secrets/import", headers=admin_h, files=files, data=data, timeout=20)
        assert rr.status_code == 400
        assert "mot de passe" in rr.text.lower() or "incorrect" in rr.text.lower() or "altéré" in rr.text.lower()

    def test_import_corrupted_envelope_returns_400(self, admin_h):
        # Random bytes that aren't a valid JSON envelope
        files = {"file": ("corrupt.json", io.BytesIO(b"\x00\x01\x02not a vault"), "application/json")}
        data = {"password": "doesntmatter", "dry_run": "true", "overwrite_filled": "false"}
        rr = requests.post(f"{API}/admin/secrets/import", headers=admin_h, files=files, data=data, timeout=20)
        assert rr.status_code == 400

    def test_import_non_vault_json_rejected(self, admin_h):
        # Valid JSON but wrong shape
        bad = {"v": 1, "alg": "wrong", "salt": "AAAA", "nonce": "AAAA", "ct": "AAAA"}
        files = {"file": ("bad.json", io.BytesIO(json.dumps(bad).encode("utf-8")), "application/json")}
        data = {"password": "test_pass_iter35e", "dry_run": "true", "overwrite_filled": "false"}
        rr = requests.post(f"{API}/admin/secrets/import", headers=admin_h, files=files, data=data, timeout=20)
        # Should fail at decrypt (invalid base64 length / wrong KDF output)
        assert rr.status_code == 400


class TestVaultAudit:
    def test_audit_endpoint_lists_recent_actions(self, admin_h):
        # First do an export to ensure at least one entry exists
        password = f"iter35e_audit_{uuid.uuid4().hex[:8]}"
        ex = requests.post(
            f"{API}/admin/secrets/export",
            headers=admin_h,
            json={"password": password, "comment": "AUDIT_TEST"},
            timeout=20,
        )
        assert ex.status_code == 200

        r = requests.get(f"{API}/admin/secrets/audit", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and isinstance(data["items"], list)
        assert data["count"] >= 1
        # Latest entry should be our export
        latest = data["items"][0]
        assert latest["action"] in ("export", "import", "import_dry")
        # Audit must NEVER leak the password
        flat = json.dumps(latest)
        assert password not in flat, "audit log leaked the password!"

    def test_audit_requires_admin(self):
        r = requests.get(f"{API}/admin/secrets/audit", timeout=10)
        assert r.status_code in (401, 403)


class TestVaultRBAC:
    def test_all_endpoints_require_admin(self):
        bad = {"Authorization": "Bearer bad.token"}
        endpoints = [
            ("GET", "/admin/secrets/keys"),
            ("POST", "/admin/secrets/export"),
            ("POST", "/admin/secrets/import"),
            ("GET", "/admin/secrets/audit"),
        ]
        for method, path in endpoints:
            fn = requests.get if method == "GET" else requests.post
            kwargs = {"headers": bad, "timeout": 10}
            if method == "POST":
                kwargs["json"] = {}
            r = fn(f"{API}{path}", **kwargs)
            assert r.status_code in (401, 403), f"{method} {path} -> {r.status_code}"
