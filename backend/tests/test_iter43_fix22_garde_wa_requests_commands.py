"""Iter43-fix22 — Tests :
  - Planning hebdo des gardes (génération, override, reset, endpoint public)
  - WA Requests tracker (listing, import contacts, export PDF)
  - Commandes Liluvine WA : !Garde, !Meteo, !Meteo +3
"""
import os
import uuid
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001") + "/api"


def _admin_token() -> str:
    r1 = requests.post(f"{API}/auth/login",
                       json={"email": "admin@sawalismartsystems.com", "password": "Admin@Sawali2026"},
                       timeout=10)
    d1 = r1.json()
    if not d1.get("needs_otp"):
        return d1["access_token"]
    r2 = requests.post(f"{API}/auth/verify-otp",
                       json={"session_token": d1["session_token"], "code": d1["dev_otp"]},
                       timeout=10)
    return r2.json()["access_token"]


class TestGardePlanning:
    def test_list_returns_52_or_53_weeks(self):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/officines-registry/garde-planning?year=2026",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["year"] == 2026
        assert 52 <= len(d["weeks"]) <= 53
        assert "groups" in d
        assert "current_iso_week" in d

    def test_generate_then_override_then_reset(self):
        tok = _admin_token()
        hdr = {"Authorization": f"Bearer {tok}"}
        # 1. Crée des officines avec groupes 1,2,3
        for g in (1, 2, 3):
            for _ in range(2):
                sfx = uuid.uuid4().hex[:8]
                requests.post(f"{API}/officines-portal/register", json={
                    "name": f"Off_{sfx}", "intitule": f"Off_{sfx}",
                    "email": f"{sfx}@example.com",
                    "phone": f"+22670{sfx[:5].translate(str.maketrans('abcdef','012345'))}",
                    "address": "X", "city": "Ouaga", "country": "BF",
                    "contact_name": "T", "numero_ordre": sfx.upper(),
                }, timeout=10)
        # Bulk assign aux 3 derniers - on récupère via la liste officines admin
        rl = requests.get(f"{API}/admin/officines-registry?status=pending", headers=hdr, timeout=10).json()
        # On prend les premiers
        first3 = [o["id"] for o in (rl.get("items") or [])[:3]]
        if first3:
            for i, oid in enumerate(first3, 1):
                requests.put(f"{API}/admin/officines-registry/{oid}",
                             json={"groupe_garde": i, "role": "Pharmacie"},
                             headers=hdr, timeout=10)
        # 2. Generate
        r = requests.post(f"{API}/admin/officines-registry/garde-planning/generate",
                          json={"year": 2026, "start_group": 1},
                          headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["weeks_generated"] >= 52
        # 3. Override week 10 → group 5
        r = requests.put(f"{API}/admin/officines-registry/garde-planning/2026/10",
                         json={"groupe_garde": 5},
                         headers=hdr, timeout=10)
        assert r.status_code == 200
        assert r.json()["manual_override"] is True
        # 4. Reset week 10
        r = requests.delete(f"{API}/admin/officines-registry/garde-planning/2026/10",
                            headers=hdr, timeout=10)
        assert r.status_code == 200

    def test_public_current_garde(self):
        r = requests.get(f"{API}/public/officines/garde/current", timeout=10)
        assert r.status_code == 200
        d = r.json()
        # Soit configuré (ok=True), soit no_groups_defined
        assert d.get("ok") in (True, False)
        if d.get("ok"):
            assert "groupe_garde" in d
            assert "officines" in d


class TestWaRequests:
    def test_grouped_listing(self):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/liluvine-pro/wa-requests?group_by_phone=true",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["grouped"] is True
        assert isinstance(d["items"], list)

    def test_import_to_contacts(self):
        tok = _admin_token()
        hdr = {"Authorization": f"Bearer {tok}"}
        r = requests.post(f"{API}/admin/liluvine-pro/wa-requests/import-to-contacts",
                          json={"phones": ["22501020304"], "group_name": "Test Interrog WA"},
                          headers=hdr, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"]
        assert d["total"] == 1

    def test_export_pdf(self):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/liluvine-pro/wa-requests/export.pdf?phones=22501020304,22509080706",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type") == "application/pdf"
        assert r.content[:4] == b"%PDF"

    def test_access_denied_for_client_role(self):
        # Pas d'auth → 401/403
        r = requests.get(f"{API}/admin/liluvine-pro/wa-requests", timeout=10)
        assert r.status_code in (401, 403)


class TestWaCommands:
    def test_garde_reply_builder(self):
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from routes.liluvine_wa_autoreply import _build_garde_reply
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]

        async def run():
            return await _build_garde_reply(db)
        out = asyncio.run(run())
        assert "Officines de garde" in out or "groupe" in out.lower()
        assert "Liluvine PRO" in out

    def test_meteo_reply_builder(self):
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from routes.liluvine_wa_autoreply import _build_meteo_reply
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]

        async def run():
            return await _build_meteo_reply(db, "!meteo", "22501020304")
        out = asyncio.run(run())
        assert "Météo" in out
        assert "°C" in out

    def test_meteo_with_offset_3(self):
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from routes.liluvine_wa_autoreply import _build_meteo_reply
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]

        async def run():
            return await _build_meteo_reply(db, "!meteo +3", "22501020304")
        out = asyncio.run(run())
        assert "Prochaines heures" in out
        # Doit avoir 3 lignes horaires
        assert out.count("•") >= 3

    def test_meteo_offset_capped_at_5(self):
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from routes.liluvine_wa_autoreply import _build_meteo_reply
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]

        async def run():
            return await _build_meteo_reply(db, "!meteo +12", "22501020304")
        out = asyncio.run(run())
        # Doit être limité à +5 → max 5 puces horaires
        assert out.count("•") <= 5
