"""Lot 21 — Auto-réponse WhatsApp Liluvine : prompt dédié aux prospects
(expéditeurs non contractuels), consignes « Mode WhatsApp » modifiables,
aucune donnée CRM transmise à un prospect, et compte plateforme exempté des
contrôles de contrat.

Tests autonomes : MongoDB simulé (mongomock-motor), IA et envois WhatsApp
simulés — aucun serveur, aucune clé, aucun réseau.
Lancer : cd backend && python -m pytest tests/test_liluvine_wa_prospects_lot21.py -q
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("mongomock_motor")
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Numéros de test
UNKNOWN = "22670000001"       # numéro absent du carnet et des comptes
CLIENT_CONTACT = "22670000002"  # contact normal d'une pharmacie cliente
TAGGED = "22670000003"        # contact étiqueté « prospect » chez la pharmacie


class _FakeChat:
    """Remplace LlmChat : mémorise le prompt système reçu, répond un texte fixe."""
    last_system = None

    def __init__(self, api_key=None, session_id=None, system_message=""):
        _FakeChat.last_system = system_message

    def with_model(self, *_a):
        return self

    async def send_message(self, _msg):
        return "Bonjour, merci pour votre message."


def _stub(monkeypatch, name, **attrs):
    """Installe un faux module `name` (avec ses attributs) dans sys.modules."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, name, mod)
    return mod


@pytest.fixture()
def env(monkeypatch):
    # --- Dépendances externes simulées ---------------------------------
    monkeypatch.setenv("EMERGENT_LLM_KEY", "test-key")
    _stub(monkeypatch, "server")  # pas de LILUVINE_REACTIONS_HELPERS
    _stub(monkeypatch, "emergentintegrations")
    _stub(monkeypatch, "emergentintegrations.llm")
    _stub(monkeypatch, "emergentintegrations.llm.chat", LlmChat=_FakeChat, UserMessage=lambda text: text)

    async def _kb(db, max_chars=0, query="", audience="clients"):
        # Lot 23 — le public demandé est inscrit dans le contexte, pour le vérifier.
        return f"BASE_DE_CONNAISSANCE[{audience}]"

    async def _biz(db, phone_digits="", query=""):
        return "DONNEES_METIER_ACL"

    async def _noop(*a, **k):
        return None

    async def _no_agents(db):
        return []

    _stub(monkeypatch, "routes.liluvine_kb", build_kb_context=_kb)
    _stub(monkeypatch, "routes.liluvine_business_rag", build_business_rag_context=_biz)
    _stub(monkeypatch, "routes.liluvine_escalation", ESCALATE_PROMPT_HINT="",
          strip_escalation_marker=lambda r: (r, None), notify_admin=_noop)
    _stub(monkeypatch, "routes.liluvine_agents", get_agents=_no_agents,
          match_agent_for_message=lambda a, t: None, build_signature=lambda a: "")
    _stub(monkeypatch, "routes.llm_health", record_llm_outcome=_noop)
    _stub(monkeypatch, "routes.ai_quotas", track_ai_usage=_noop)

    from routes import liluvine_pro
    from routes import liluvine_wa_autoreply as autoreply

    # Contexte CRM du tenant : marqueur reconnaissable
    async def _ctx(db, user, text):
        return "DONNEES_CRM_DU_TENANT"
    monkeypatch.setattr(liluvine_pro, "_fetch_context_snippets", _ctx)

    db = AsyncMongoMockClient()["sawali_test_lot21"]
    loop = asyncio.new_event_loop()
    loop.run_until_complete(db.users.insert_many([
        # Compte SAWALI (tenant principal) : superviseur SANS numéro de contrat
        {"id": "sawali", "role": "superviseur", "company": "SAWALI", "features": {"ai_liluvine_pro": True},
         "liluvine_pro_system_prompt": "PROMPT_DU_COMPTE_SAWALI"},
        # Pharmacie cliente sous contrat valable (paiement récent)
        {"id": "pharma", "role": "pharmacien", "company": "Pharmacie Test", "features": {"ai_liluvine_pro": True},
         "contract_number": "C-001", "last_payment_at": _today(),
         "liluvine_pro_system_prompt": "PROMPT_DE_LA_PHARMACIE"},
        # Pharmacie cliente SANS contrat
        {"id": "pharma-sans", "role": "pharmacien", "company": "Sans Contrat", "features": {"ai_liluvine_pro": True}},
    ]))
    loop.run_until_complete(db.directory_contacts.insert_many([
        {"id": "c-client", "client_id": "pharma", "name": "Client fidèle", "phone": f"+{CLIENT_CONTACT}"},
        {"id": "c-tag", "client_id": "pharma-sans", "name": "Curieux", "phone": f"+{TAGGED}", "tags": ["Prospect"]},
    ]))

    sent: list = []

    async def wa_send_text(to, text, reply_to_message_id=None):
        sent.append({"to": to, "text": text})
        return {"ok": True, "message_id": "wamid.out"}

    def run(phone, tenant, contact=None, text="Bonjour, quels sont vos services ?", **settings):
        """Simule un message WhatsApp entrant et renvoie le résultat de l'auto-réponse."""
        _FakeChat.last_system = None
        base = {
            "liluvine_wa_autoreply_enabled": True,
            "liluvine_wa_autoreply_cooldown_seconds": 0,
        }
        base.update(settings)
        inbound = {"from": f"+{phone}", "phone_digits": phone, "body": text,
                   "wa_message_id": f"wamid.in.{phone}", "client_id": tenant, "message_type": "text"}
        return loop.run_until_complete(autoreply.autoreply_to_inbound(
            db, inbound_doc=inbound, contact=contact, settings_doc=base, wa_send_text=wa_send_text,
        ))

    yield types.SimpleNamespace(run=run, sent=sent, db=db, loop=loop, liluvine_pro=liluvine_pro)
    loop.close()


def _today():
    from datetime import date
    return date.today().isoformat()


def test_unknown_sender_gets_default_prospect_prompt_without_crm_data(env):
    res = env.run(UNKNOWN, "sawali")
    # Compte SAWALI sans contrat : la réponse part quand même (compte plateforme exempté).
    assert res["ok"] is True and res["prospect"] is True
    system = _FakeChat.last_system
    assert system.startswith(env.liluvine_pro.DEFAULT_WA_PROSPECT_SYSTEM_PROMPT)
    assert "PROMPT_DU_COMPTE_SAWALI" not in system
    # Aucune donnée du CRM, seulement la base de connaissance.
    assert "DONNEES_CRM_DU_TENANT" not in system and "DONNEES_METIER_ACL" not in system
    assert "BASE_DE_CONNAISSANCE" in system
    # Lot 23 — base de connaissance « prospects » (entrées « tous » + « prospects »)
    assert "BASE_DE_CONNAISSANCE[prospects]" in system
    # Consignes « Mode WhatsApp » d'origine
    assert env.liluvine_pro.DEFAULT_WA_MODE_INSTRUCTIONS in system
    # Traçabilité : message assistant marqué « prospect »
    msg = env.loop.run_until_complete(env.db.liluvine_pro_messages.find_one({"role": "assistant"}))
    assert msg["prospect"] is True and msg["context_injected"] is False


def test_custom_prospect_prompt_and_mode_instructions(env):
    res = env.run(UNKNOWN, "sawali",
                  liluvine_wa_prospect_system_prompt="  MON_PROMPT_PROSPECT  ",
                  liluvine_wa_mode_instructions="MES_CONSIGNES_WA")
    assert res["ok"] is True
    system = _FakeChat.last_system
    assert system.startswith("MON_PROMPT_PROSPECT")
    assert "[IMPORTANT — Mode auto-réponse WhatsApp]\nMES_CONSIGNES_WA" in system
    assert env.liluvine_pro.DEFAULT_WA_MODE_INSTRUCTIONS not in system


def test_prospect_replies_can_be_disabled(env):
    res = env.run(UNKNOWN, "sawali", liluvine_wa_prospect_enabled=False)
    assert res == {"ok": False, "reason": "prospect_replies_disabled"}
    assert env.sent == [] and _FakeChat.last_system is None


def test_known_client_keeps_tenant_prompt_and_crm_context(env):
    res = env.run(CLIENT_CONTACT, "pharma", contact={"id": "c-client", "client_id": "pharma", "name": "Client fidèle"},
                  liluvine_wa_prospect_system_prompt="MON_PROMPT_PROSPECT",
                  liluvine_wa_mode_instructions="MES_CONSIGNES_WA")
    assert res["ok"] is True and res["prospect"] is False
    system = _FakeChat.last_system
    assert system.startswith("PROMPT_DE_LA_PHARMACIE") and "MON_PROMPT_PROSPECT" not in system
    assert "DONNEES_CRM_DU_TENANT" in system and "DONNEES_METIER_ACL" in system
    assert "BASE_DE_CONNAISSANCE[clients]" in system  # Lot 23 — pas les entrées réservées aux prospects
    # Les consignes « Mode WhatsApp » s'appliquent aussi aux clients.
    assert "MES_CONSIGNES_WA" in system


def test_tagged_prospect_of_client_without_contract_is_still_gated(env):
    # Le contrôle de contrat reste actif pour un tenant client, même pour un prospect.
    res = env.run(TAGGED, "pharma-sans", contact={"id": "c-tag", "client_id": "pharma-sans", "name": "Curieux"})
    assert res["ok"] is False and res["reason"].startswith("contract_invalid")
    assert _FakeChat.last_system is None


def test_client_tenant_without_contract_still_blocked_for_clients(env):
    env.loop.run_until_complete(env.db.directory_contacts.insert_one(
        {"id": "c-x", "client_id": "pharma-sans", "name": "Client X", "phone": "+22670000009"}))
    res = env.run("22670000009", "pharma-sans", contact={"id": "c-x", "client_id": "pharma-sans", "name": "Client X"})
    assert res["ok"] is False and res["reason"].startswith("contract_invalid")


def test_is_prospect_sender_rules(env):
    from routes.liluvine_wa_autoreply import _is_prospect_sender, _is_platform_tenant
    run = env.loop.run_until_complete
    assert run(_is_prospect_sender(env.db, None)) is True
    assert run(_is_prospect_sender(env.db, {"id": "c-tag"})) is True          # étiquette relue en base
    assert run(_is_prospect_sender(env.db, {"id": "c-client"})) is False
    assert run(_is_prospect_sender(env.db, {"id": "x", "tags": ["vip"]})) is False
    assert _is_platform_tenant({"role": "superviseur"}) and _is_platform_tenant({"role": "admin"})
    assert not _is_platform_tenant({"role": "pharmacien"})


def test_admin_payload_accepts_lot21_fields(env):
    payload = env.liluvine_pro.AutoreplyConfigPayload(
        prospect_enabled=False, prospect_system_prompt="P", mode_instructions="M")
    assert payload.prospect_enabled is False and payload.mode_instructions == "M"
