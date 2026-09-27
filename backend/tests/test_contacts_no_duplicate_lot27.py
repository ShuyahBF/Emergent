"""Lot 27 — plus de doublon recréé à chaque conversation WhatsApp.

Un contact importé sans « + » (« 22661256822 ») ou avec des espaces n'était pas
retrouvé par l'ajout automatique de Liluvine (qui cherchait seulement
« +22661256822 ») : un doublon « auto-liluvine » était recréé à chaque message,
même après dédoublonnage. Le numéro est maintenant reconnu sur ses 8 derniers
chiffres, comme dans le reste du webhook. Test autonome : MongoDB simulé.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter  # noqa: E402

import routes.liluvine_reactions as lr  # noqa: E402


async def _nobody():
    return {}


async def _scope(u):
    return []


def _helpers(db):
    return lr.attach_liluvine_reactions_routes(api=APIRouter(), db=db, get_current_user=_nobody, get_current_admin=_nobody,
                                               _is_super_admin=lambda u: False, _resolve_visible_client_ids=_scope)


def test_existing_contact_in_any_format_is_recognised():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_dup"]

    async def scenario():
        await db.settings.insert_one({"_id": "global", "liluvine_reactions_config": {"auto_add_new_contacts": True}})
        await db.directory_contacts.insert_many([
            {"id": "k1", "client_id": "t1", "name": "Catline K.", "phone": "22661256822", "whatsapp": "22661256822"},
            {"id": "k2", "client_id": "t1", "name": "NANA Faouzi", "whatsapp": "+226 75 59 73 40"},
        ])
        h = _helpers(db)
        add = h["auto_add_new_contact_if_enabled"]
        r1 = await add("22661256822", "Catline K.", "t1")      # enregistré sans « + »
        r2 = await add("22675597340", "Faouzi", "t1")          # enregistré avec des espaces
        r3 = await add("22670522075", "SANNA Azize", "t1")     # vraiment nouveau
        r4 = await add("22670522075", "SANNA Azize", "t1")     # 2e message : pas de doublon
        n = await db.directory_contacts.count_documents({})
        return r1, r2, r3, r4, n
    r1, r2, r3, r4, n = asyncio.run(scenario())
    assert r1 is None and r2 is None and r4 is None
    assert r3 and r3["id"]
    assert n == 3


def test_suffix_regex():
    import re
    rx = lr._phone_suffix_regex("+226 61 25 68 22")
    assert all(re.search(rx, v) for v in ("22661256822", "+22661256822", "61 25 68 22", "61.25.68.22"))
    assert not re.search(rx, "22661256823") and lr._phone_suffix_regex("123") is None
