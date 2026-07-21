"""Iter43-fix24az-s (2026-07-22) — Regression tests for `_build_garde_reply`.

BUG : Après implémentation du groupe d'appui (Iter43-fix24az-r), la réponse
WhatsApp `!garde` arrivait VIDE côté client. Root cause : chaque officine
d'appui était wrappée dans `_..._` italique WhatsApp, mais les noms
d'officines contiennent des `_` (`Off_07968122`) → pattern d'italique cassé
→ WhatsApp rend le message vide.

FIX : Préfixer chaque officine d'appui avec `↳ ` (au lieu de wrap italique).
Le titre de section reste en italique (safe, aucun `_` dans le libellé).

Ces tests appellent directement `_build_garde_reply(db)` via motor +
asyncio.run, seedant `garde_planning`, `officines` et `settings` de façon
isolée (nettoyés à la fin).
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jwt as pyjwt  # noqa: F401  (kept for parity w/ other tests)
import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _current_year_week():
    """Return (year, week) that `_build_garde_reply` will look up.

    We compute the ISO year/week from the same helper the code uses, but as
    a fallback we simply use `datetime.now(timezone.utc).date().isocalendar()`
    — that matches both `saturday_noon` and `monday_midnight` modes' week
    number in most cases, and _build_garde_reply uses the resolver which
    looks up `garde_planning` by (year, week) — matching seed year+week is
    what matters.
    """
    async def _run():
        from routes.garde_planning import _current_garde_period
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        try:
            p = await _current_garde_period(db, now=datetime.now(timezone.utc))
            return int(p["year"]), int(p["week"])
        finally:
            client.close()
    return asyncio.run(_run())


def _build_reply_isolated(seed_planning, seed_officines, seed_settings=None):
    """Run `_build_garde_reply(db)` on a fresh motor client, seeding the given
    docs and cleaning them up right after. Returns the reply string."""
    async def _run():
        from routes.liluvine_wa_autoreply import _build_garde_reply
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        seeded_office_ids = []
        seeded_planning_key = None
        try:
            # Seed planning
            if seed_planning:
                await db.garde_planning.delete_one(
                    {"year": seed_planning["year"], "week_number": seed_planning["week_number"]}
                )
                await db.garde_planning.insert_one(dict(seed_planning))
                seeded_planning_key = (seed_planning["year"], seed_planning["week_number"])

            # Seed officines
            for o in seed_officines:
                await db.officines.insert_one(dict(o))
                seeded_office_ids.append(o["id"])

            # Settings (optional — leave existing settings.global untouched)
            reply = await _build_garde_reply(db)
            return reply
        finally:
            # Cleanup
            for oid in seeded_office_ids:
                await db.officines.delete_one({"id": oid})
            if seeded_planning_key:
                await db.garde_planning.delete_one(
                    {"year": seeded_planning_key[0], "week_number": seeded_planning_key[1]}
                )
            client.close()
    return asyncio.run(_run())


def _make_officine(name: str, groupe: int, city: str = "Ouaga") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "intitule": name,
        "phone": "+22670000000",
        "whatsapp": "+22670000000",
        "address": "Rue Test",
        "city": city,
        "location_hint": "Centre",
        "latitude": 12.36,
        "longitude": -1.53,
        "contact_name": "Test",
        "email": "t@example.com",
        "groupe_garde": groupe,
        "status": "active",
    }


# ---------------------------------------------------------------------------
# Fixtures — seed current week planning with assist_group
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def year_week():
    return _current_year_week()


# =============================================================================
# TEST 1 — Reply non-vide quand assist_group défini
# =============================================================================
def test_reply_nonempty_when_assist_group_defined(year_week):
    year, week = year_week
    planning = {
        "year": year,
        "week_number": week,
        "groupe_garde": 91,
        "assist_group": 92,
    }
    officines = [
        _make_officine("Pharmacie Off_07968122", 91),
        _make_officine("Pharmacie Off_00f61f18", 91),
        _make_officine("Pharmacie Off_8059c1ee", 92),
        _make_officine("Pharmacie Off_deadbeef", 92),
    ]
    reply = _build_reply_isolated(planning, officines)
    assert isinstance(reply, str)
    assert len(reply) > 0, "reply must be non-empty"
    print(f"[test1] reply length = {len(reply)}")


# =============================================================================
# TEST 2 — Aucune ligne contenant `Off_` n'est wrappée `_..._` italique
# =============================================================================
def test_no_italic_wrap_on_lines_containing_underscore(year_week):
    year, week = year_week
    planning = {"year": year, "week_number": week, "groupe_garde": 91, "assist_group": 92}
    officines = [
        _make_officine("Pharmacie Off_07968122", 91),
        _make_officine("Pharmacie Off_8059c1ee", 92),
    ]
    reply = _build_reply_isolated(planning, officines)
    for line in reply.split("\n"):
        stripped = line.strip()
        if "Off_" in stripped:
            # Must NOT be wrapped in italic
            starts_italic = stripped.startswith("_")
            ends_italic = stripped.endswith("_")
            assert not (starts_italic and ends_italic), (
                f"Line contains 'Off_' AND is wrapped in `_..._` italic — WhatsApp render will break: {stripped!r}"
            )


# =============================================================================
# TEST 3 — Le préfixe `↳ ` et le titre italique de section sont présents
# =============================================================================
def test_assist_group_prefix_and_italic_title(year_week):
    year, week = year_week
    planning = {"year": year, "week_number": week, "groupe_garde": 91, "assist_group": 92}
    officines = [
        _make_officine("Pharmacie Off_07968122", 91),
        _make_officine("Pharmacie Off_8059c1ee", 92),
        _make_officine("Pharmacie Off_deadbeef", 92),
    ]
    reply = _build_reply_isolated(planning, officines)
    # Titre italique (safe car pas de `_` dans le libellé)
    assert "🤝 _Groupe d'appui G92 — 2 officine(s) :_" in reply, (
        f"Missing italic assist group title. Reply:\n{reply}"
    )
    # Chaque officine du groupe d'appui préfixée par ↳
    assert "↳ • *Pharmacie Off_8059c1ee*" in reply or re.search(
        r"↳\s+•\s+\*Pharmacie Off_8059c1ee\*", reply
    ), f"Missing `↳ ` prefix on assist officine. Reply:\n{reply}"
    assert "↳ • *Pharmacie Off_deadbeef*" in reply or re.search(
        r"↳\s+•\s+\*Pharmacie Off_deadbeef\*", reply
    ), f"Missing `↳ ` prefix on second assist officine. Reply:\n{reply}"


# =============================================================================
# TEST 4 — Pas de section "Groupe d'appui" quand assist_group est None
# =============================================================================
def test_no_assist_section_when_assist_group_none(year_week):
    year, week = year_week
    planning = {"year": year, "week_number": week, "groupe_garde": 93}  # no assist_group
    officines = [
        _make_officine("Pharmacie Off_07968122", 93),
        _make_officine("Pharmacie Off_00f61f18", 93),
    ]
    reply = _build_reply_isolated(planning, officines)
    assert len(reply) > 0
    assert "Groupe d'appui" not in reply, f"Should not contain assist section. Reply:\n{reply}"
    assert "↳" not in reply, "No ↳ prefix should be present when no assist group"
    # Officines standards toujours présentes
    assert "Pharmacie Off_07968122" in reply


# =============================================================================
# TEST 5 — Reply reste < 4096 chars avec 10+ officines dans chaque groupe
# =============================================================================
def test_reply_under_4096_with_many_officines(year_week):
    year, week = year_week
    planning = {"year": year, "week_number": week, "groupe_garde": 94, "assist_group": 95}
    officines = []
    for i in range(12):
        officines.append(_make_officine(f"Pharmacie Off_std_{i:04d}", 94))
    for i in range(12):
        officines.append(_make_officine(f"Pharmacie Off_asst_{i:04d}", 95))
    reply = _build_reply_isolated(planning, officines)
    assert len(reply) > 0
    assert len(reply) < 4096, f"Reply length {len(reply)} exceeds 4096 char WA limit"


# =============================================================================
# TEST 6 — Public endpoint returns assist_group / assist_officines / assist_count
# =============================================================================
def test_public_garde_current_returns_assist_fields():
    r = requests.get(f"{API}/public/officines/garde/current", timeout=15)
    assert r.status_code == 200, f"Public endpoint failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    assert "assist_group" in data, f"Missing key `assist_group` in response: {list(data.keys())}"
    assert "assist_officines" in data
    assert "assist_count" in data
    assert isinstance(data["assist_officines"], list)
    assert isinstance(data["assist_count"], int)
