"""Lot 23 — Base de connaissance Liluvine par public : « tous », « clients »,
« prospects ». Un prospect WhatsApp ne reçoit que « tous » + « prospects »
(et pas la recherche sémantique Qdrant) ; les clients et le chat interne ne
reçoivent jamais les entrées réservées aux prospects.
Lancer : cd backend && python -m pytest tests/test_liluvine_kb_audience_lot23.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

pytest.importorskip("mongomock_motor")
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def kb(monkeypatch):
    from routes import liluvine_kb
    liluvine_kb.invalidate_kb_cache()
    db = AsyncMongoMockClient()["sawali_kb_lot23"]
    loop = asyncio.new_event_loop()
    loop.run_until_complete(db.liluvine_knowledge.insert_many([
        {"id": "a", "title": "Horaires", "content": "Ouvert de 8h à 18h", "enabled": True},            # ancienne entrée (sans audience)
        {"id": "b", "title": "Procédure interne", "content": "Code coffre 1234", "enabled": True, "audience": "clients"},
        {"id": "c", "title": "Offre découverte", "content": "Essai gratuit 30 jours", "enabled": True, "audience": "prospects"},
        {"id": "d", "title": "Tarifs publics", "content": "À partir de 25 000 FCFA", "enabled": True, "audience": "all"},
    ]))
    # La recherche sémantique Qdrant ne doit jamais être appelée pour un prospect.
    calls = []

    async def fake_rag(db, query, max_chars):
        calls.append(query)
        return "[RAG interne]"
    import types
    monkeypatch.setitem(sys.modules, "routes.qdrant_rag", types.SimpleNamespace(build_rag_context=fake_rag))
    yield liluvine_kb, db, loop, calls
    liluvine_kb.invalidate_kb_cache()
    loop.close()


def test_prospects_get_only_all_and_prospect_entries(kb):
    mod, db, loop, calls = kb
    ctx = loop.run_until_complete(mod.build_kb_context(db, query="prix ?", audience="prospects"))
    assert "Essai gratuit" in ctx and "Tarifs publics" in ctx and "Ouvert de 8h" in ctx
    assert "Code coffre" not in ctx and "[RAG interne]" not in ctx and calls == []


def test_clients_never_get_prospect_entries(kb):
    mod, db, loop, calls = kb
    ctx = loop.run_until_complete(mod.build_kb_context(db, query="prix ?"))  # défaut = clients
    assert "Code coffre" in ctx and "Tarifs publics" in ctx and "Ouvert de 8h" in ctx
    assert "Essai gratuit" not in ctx
    assert ctx.startswith("[RAG interne]") and calls == ["prix ?"]
    # Le cache est distinct par public : pas de fuite d'un contexte à l'autre.
    ctx_p = loop.run_until_complete(mod.build_kb_context(db, audience="prospects"))
    assert "Code coffre" not in ctx_p


def test_payload_validates_audience():
    from pydantic import ValidationError
    from routes.liluvine_kb import KbEntryCreate, KbEntryUpdate
    assert KbEntryCreate(title="t", content="c", audience="prospects").audience == "prospects"
    assert KbEntryUpdate(audience="clients").audience == "clients"
    with pytest.raises(ValidationError):
        KbEntryCreate(title="t", content="c", audience="tout-le-monde")
