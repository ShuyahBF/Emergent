"""Iter43-fix21 — Tests pour : logos persistants en DB, rôles configurables,
groupes de garde, et action en lot d'affectation.
"""
import io
import os
import uuid
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001") + "/api"


def _admin_token() -> str:
    r1 = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@sawalismartsystems.com", "password": "Admin@Sawali2026"},
        timeout=10,
    )
    d1 = r1.json()
    if not d1.get("needs_otp"):
        return d1["access_token"]
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": d1["session_token"], "code": d1["dev_otp"]},
        timeout=10,
    )
    return r2.json()["access_token"]


def _create_officine(token: str, name: str | None = None) -> str:
    """Helper : crée une officine en bypassant le portal flow (admin POST)."""
    suffix = uuid.uuid4().hex[:10]
    name = name or f"Officine_test_{suffix}"
    r = requests.post(
        f"{API}/officines-portal/register",
        json={
            "name": name,
            "intitule": name,
            "email": f"test_{suffix}@example.com",
            "phone": f"+22670{suffix[:6].translate(str.maketrans('abcdef', '012345'))}",
            "address": "Rue 1", "city": "Ouagadougou", "country": "BF",
            "contact_name": "Test",
            "numero_ordre": suffix[:8].upper(),
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body.get("officine_id") or body["officine"]["id"]


class TestOfficineRoles:
    def test_roles_default_includes_laboratoire(self):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/officines-registry/roles",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert "Laboratoire" in d["roles"], d
        assert "default_roles" in d
        assert "Laboratoire" in d["default_roles"]

    def test_update_roles_cycle(self):
        tok = _admin_token()
        hdr = {"Authorization": f"Bearer {tok}"}
        # 1. Read current
        r0 = requests.get(f"{API}/admin/officines-registry/roles", headers=hdr, timeout=10).json()
        original = list(r0["roles"])
        # 2. Add a custom role
        custom = "TestRole_" + uuid.uuid4().hex[:6]
        new_list = original + [custom]
        r = requests.put(f"{API}/admin/officines-registry/roles",
                         json={"roles": new_list}, headers=hdr, timeout=10)
        assert r.status_code == 200, r.text
        assert custom in r.json()["roles"]
        # 3. Restore original
        r = requests.put(f"{API}/admin/officines-registry/roles",
                         json={"roles": original}, headers=hdr, timeout=10)
        assert r.status_code == 200

    def test_cannot_remove_role_in_use(self):
        tok = _admin_token()
        hdr = {"Authorization": f"Bearer {tok}"}
        oid = _create_officine(tok)
        # Affecte rôle "Laboratoire"
        requests.put(f"{API}/admin/officines-registry/{oid}",
                     json={"role": "Laboratoire"}, headers=hdr, timeout=10)
        # Tenter de supprimer "Laboratoire" de la liste → 409
        roles = requests.get(f"{API}/admin/officines-registry/roles", headers=hdr, timeout=10).json()["roles"]
        filtered = [r for r in roles if r != "Laboratoire"]
        r = requests.put(f"{API}/admin/officines-registry/roles",
                         json={"roles": filtered}, headers=hdr, timeout=10)
        assert r.status_code == 409, r.text


class TestGardeGroups:
    def test_garde_groups_endpoint(self):
        tok = _admin_token()
        hdr = {"Authorization": f"Bearer {tok}"}
        r = requests.get(f"{API}/admin/officines-registry/garde-groups", headers=hdr, timeout=10)
        assert r.status_code == 200
        d = r.json()
        # Toujours au moins les 5 premiers visibles
        assert len(d["groups"]) >= 5
        assert d["next_suggested"] >= 1


class TestBulkAssign:
    def test_bulk_assign_role_and_groupe(self):
        tok = _admin_token()
        hdr = {"Authorization": f"Bearer {tok}"}
        oid1 = _create_officine(tok)
        oid2 = _create_officine(tok)
        r = requests.post(
            f"{API}/admin/officines-registry/bulk-assign",
            json={"officine_ids": [oid1, oid2], "role": "Laboratoire", "groupe_garde": 3},
            headers=hdr, timeout=10,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"]
        assert d["modified"] >= 2

    def test_bulk_assign_rejects_unknown_role(self):
        tok = _admin_token()
        hdr = {"Authorization": f"Bearer {tok}"}
        oid = _create_officine(tok)
        r = requests.post(
            f"{API}/admin/officines-registry/bulk-assign",
            json={"officine_ids": [oid], "role": "RoleInexistant999"},
            headers=hdr, timeout=10,
        )
        assert r.status_code == 400, r.text

    def test_bulk_assign_requires_at_least_one_field(self):
        tok = _admin_token()
        hdr = {"Authorization": f"Bearer {tok}"}
        oid = _create_officine(tok)
        r = requests.post(
            f"{API}/admin/officines-registry/bulk-assign",
            json={"officine_ids": [oid]},
            headers=hdr, timeout=10,
        )
        assert r.status_code == 400


class TestLogoPersistence:
    def test_logos_health_endpoint(self):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/officines-registry/logos/health",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 200
        d = r.json()
        for k in ("ok_in_db", "ok_on_disk_only", "broken_count", "broken", "advice"):
            assert k in d

    def test_upload_logo_persists_in_db(self):
        """Iter43-fix21 — Le logo doit être stocké en base64 dans MongoDB."""
        tok = _admin_token()
        hdr = {"Authorization": f"Bearer {tok}"}
        oid = _create_officine(tok)
        # Mini PNG (1x1 transparent)
        png_bytes = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c63000100000005000100" "0d0a2db40000000049454e44ae426082"
        )
        files = {"file": ("test.png", io.BytesIO(png_bytes), "image/png")}
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/upload-logo",
            files=files,
            headers=hdr,
            timeout=15,
        )
        assert r.status_code == 200, r.text
        # Vérifier que get_officine_logo renvoie un PNG
        r2 = requests.get(f"{API}/officines-registry/{oid}/logo", timeout=10)
        assert r2.status_code == 200
        assert r2.headers.get("content-type") == "image/png"
        assert r2.content == png_bytes  # Round-trip parfait

    def test_upload_logo_rejects_too_big(self):
        tok = _admin_token()
        hdr = {"Authorization": f"Bearer {tok}"}
        oid = _create_officine(tok)
        big = b"\x00" * (3 * 1024 * 1024)  # 3 Mo > limite 2 Mo
        files = {"file": ("big.png", io.BytesIO(big), "image/png")}
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/upload-logo",
            files=files, headers=hdr, timeout=15,
        )
        assert r.status_code == 413, r.text
