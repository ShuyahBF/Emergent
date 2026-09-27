"""Lot 27 — modèles WhatsApp avec bouton « Flux » (FLOW).

- à l'envoi : Meta exige, pour chaque bouton FLOW, un composant bouton portant
  un flow_token ; le portail ne l'envoyait pas (erreur Meta, message non
  envoyé). Le composant est maintenant ajouté d'après la définition du modèle ;
- à la réception : la réponse du formulaire (message « nfm_reply ») était
  perdue ; elle est affichée dans la conversation, enregistrée et déclenche
  l'événement d'automation « whatsapp.flow_completed ».
Tests autonomes : MongoDB simulé (mongomock-motor), Meta simulé, aucun envoi réel.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import types
from pathlib import Path

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test")
os.environ.setdefault("JWT_SECRET", "test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.whatsapp_helpers as wh  # noqa: E402

# Définition du modèle telle que Meta la renvoie (cas réel : suivilogiciels_fr)
TPL_DEF = {
    "name": "suivilogiciels_fr", "language": "fr", "status": "APPROVED",
    "components": [
        {"type": "BODY", "text": "Bonjour {{1}}, suivez votre logiciel."},
        {"type": "BUTTONS", "buttons": [
            {"type": "FLOW", "text": "Commencer le Suivi", "flow_id": "123", "flow_action": "navigate"},
        ]},
    ],
}


def test_flow_component_added_when_missing():
    comps = [{"type": "body", "parameters": [{"type": "text", "text": "Awa"}]}]
    out, added = wh._wa_add_flow_button_components(comps, TPL_DEF, lambda: "tok-1")
    assert added == [(0, "tok-1")]
    assert out[0] == comps[0]
    assert out[1] == {"type": "button", "sub_type": "flow", "index": "0",
                      "parameters": [{"type": "action", "action": {"flow_token": "tok-1"}}]}
    # Sans composant du tout (modèle sans variable) : ajouté aussi
    out2, added2 = wh._wa_add_flow_button_components(None, TPL_DEF, lambda: "tok-2")
    assert len(out2) == 1 and out2[0]["sub_type"] == "flow" and added2 == [(0, "tok-2")]


def test_flow_component_kept_or_replaced():
    good = [{"type": "button", "sub_type": "flow", "index": "0",
             "parameters": [{"type": "action", "action": {"flow_token": "deja"}}]}]
    out, added = wh._wa_add_flow_button_components(good, TPL_DEF, lambda: "x")
    assert out is good and added == []                     # déjà correct : inchangé
    wrong = [{"type": "button", "sub_type": "quick_reply", "index": "0", "parameters": []}]
    out, added = wh._wa_add_flow_button_components(wrong, TPL_DEF, lambda: "t")
    assert len(out) == 1 and out[0]["sub_type"] == "flow" and added == [(0, "t")]


def test_no_change_without_flow_button():
    tpl = {"components": [{"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Oui"},
                                                          {"type": "URL", "text": "Site"}]}]}
    comps = [{"type": "body", "parameters": []}]
    assert wh._wa_add_flow_button_components(comps, tpl, lambda: "x") == (comps, [])
    assert wh._wa_add_flow_button_components(comps, None, lambda: "x") == (comps, [])
    # Bouton FLOW en 2e position : index « 1 »
    tpl2 = {"components": [{"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Oui"},
                                                           {"type": "FLOW", "text": "Go"}]}]}
    out, added = wh._wa_add_flow_button_components(None, tpl2, lambda: "k")
    assert added == [(1, "k")] and out[0]["index"] == "1"


def test_parse_flow_reply():
    inter = {"type": "nfm_reply", "nfm_reply": {
        "name": "flow", "body": "Sent",
        "response_json": json.dumps({"flow_token": "sawali-abc", "screen_0_Nom_0": "Awa",
                                     "logiciels": ["Sage", "Odoo"], "satisfaction": "4"}),
    }}
    r = wh._wa_parse_flow_reply(inter)
    assert r["flow_token"] == "sawali-abc"
    assert r["fields"] == {"screen_0_Nom_0": "Awa", "logiciels": ["Sage", "Odoo"], "satisfaction": "4"}
    assert r["summary"].splitlines() == ["📋 Formulaire WhatsApp complété", "• Nom : Awa",
                                         "• logiciels : Sage, Odoo", "• satisfaction : 4"]
    assert wh._wa_parse_flow_reply({"type": "button_reply", "button_reply": {"id": "x"}}) is None
    assert wh._wa_parse_flow_reply(None) is None
    # JSON illisible : gardé tel quel
    r2 = wh._wa_parse_flow_reply({"type": "nfm_reply", "nfm_reply": {"response_json": "pas du json"}})
    assert r2["fields"] == {"reponse": "pas du json"} and r2["flow_token"] == ""


class _Resp:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data
        self.text = json.dumps(data)

    def json(self):
        return self._data


def _fake_meta(calls, template_status=200):
    """Client httpx simulé : liste des modèles (GET) et envoi du message (POST)."""
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None):
            calls.append(("GET", url, params))
            if template_status != 200:
                return _Resp(template_status, {"error": {"message": "refus"}})
            return _Resp(200, {"data": [TPL_DEF]})

        async def post(self, url, json=None, headers=None):
            calls.append(("POST", url, json))
            return _Resp(200, {"messages": [{"id": "wamid.1"}]})
    return _Client


def _helpers(db):
    return wh.attach_whatsapp_helpers(
        db=db, wa_graph_version="v21.0", wa_media_max_bytes=10_000_000,
        upload_dir=Path("/tmp"), uuid_fn=lambda: "u1", now_fn=lambda: "2026-09-26T10:00:00+00:00")


def test_send_template_adds_flow_button_and_records_token(monkeypatch):
    calls = []
    monkeypatch.setattr(wh.httpx, "AsyncClient", _fake_meta(calls))
    db = mongomock_motor.AsyncMongoMockClient()["sawali_flow"]

    async def scenario():
        await db.settings.insert_one({"_id": "global", "wa_access_token": "T", "wa_phone_number_id": "P",
                                      "wa_business_account_id": "W"})
        h = _helpers(db)
        res1 = await h["_wa_send_template"]("+226 70 00 00 00", "suivilogiciels_fr", "fr",
                                            [{"type": "body", "parameters": [{"type": "text", "text": "Awa"}]}])
        # 2e envoi : la définition du modèle est mémorisée (pas de nouvelle lecture)
        res2 = await h["_wa_send_template"]("22670000001", "suivilogiciels_fr", "fr", None)
        rows = await db.whatsapp_flow_sends.find({}, {"_id": 0}).to_list(10)
        return res1, res2, rows
    res1, res2, rows = asyncio.run(scenario())
    assert res1["ok"] and res2["ok"]
    gets = [c for c in calls if c[0] == "GET"]
    posts = [c for c in calls if c[0] == "POST"]
    assert len(gets) == 1 and "/W/message_templates" in gets[0][1] and gets[0][2]["name"] == "suivilogiciels_fr"
    sent = posts[0][2]["template"]["components"]
    assert sent[1] == {"type": "button", "sub_type": "flow", "index": "0",
                       "parameters": [{"type": "action", "action": {"flow_token": "sawali-u1"}}]}
    assert posts[1][2]["template"]["components"][0]["sub_type"] == "flow"
    assert [r["to"] for r in rows] == ["22670000000", "22670000001"]
    assert rows[0]["flow_token"] == "sawali-u1" and rows[0]["template"] == "suivilogiciels_fr"


def test_send_template_still_works_when_meta_listing_fails(monkeypatch):
    """Modèle illisible chez Meta : l'envoi part quand même, sans rien ajouter."""
    calls = []
    monkeypatch.setattr(wh.httpx, "AsyncClient", _fake_meta(calls, template_status=403))
    db = mongomock_motor.AsyncMongoMockClient()["sawali_flow2"]

    async def scenario():
        await db.settings.insert_one({"_id": "global", "wa_access_token": "T", "wa_phone_number_id": "P",
                                      "wa_business_account_id": "W"})
        return await _helpers(db)["_wa_send_template"]("22670000000", "autre_modele", "fr",
                                                       [{"type": "body", "parameters": [{"type": "text", "text": "a"}]}])
    res = asyncio.run(scenario())
    posts = [c for c in calls if c[0] == "POST"]
    assert res["ok"] and posts[0][2]["template"]["components"] == [
        {"type": "body", "parameters": [{"type": "text", "text": "a"}]}]


def test_server_webhook_and_event_wiring():
    """Le webhook lit la réponse du formulaire et émet « whatsapp.flow_completed »."""
    from _source_serveur import source_serveur  # lot 28 : server.py découpé en server_parts/
    src = source_serveur()
    assert "flow_reply = _wa_parse_flow_reply(interactive)" in src
    assert src.count('"whatsapp.flow_completed"') >= 3      # événement émis, supporté, listé
    assert "db.whatsapp_flow_responses.insert_one" in src


@pytest.fixture(scope="module")
def server_mod():
    """server.py importé dans une boucle (il crée des tâches à l'import)."""
    pytest.importorskip("apscheduler")
    if "num2words" not in sys.modules:
        try:
            import num2words  # noqa: F401
        except ImportError:
            _m = types.ModuleType("num2words")
            _m.num2words = lambda *a, **k: ""
            sys.modules["num2words"] = _m
    loop = asyncio.new_event_loop()

    async def _imp():
        import server
        return server
    mod = loop.run_until_complete(_imp())
    yield mod, loop
    loop.close()


def test_webhook_stores_flow_reply(server_mod, monkeypatch):
    server, loop = server_mod
    db = mongomock_motor.AsyncMongoMockClient()["sawali_flow_wh"]
    monkeypatch.setattr(server, "db", db)
    emitted = []

    async def fake_emit(event, target):
        emitted.append((event, target))
    monkeypatch.setattr(server, "_emit_event", fake_emit)
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "P"},
        "contacts": [{"profile": {"name": "Awa"}, "wa_id": "22670000000"}],
        "messages": [{"from": "22670000000", "id": "wamid.in1", "timestamp": "1790000000",
                      "type": "interactive", "interactive": {"type": "nfm_reply", "nfm_reply": {
                          "name": "flow", "body": "Sent",
                          "response_json": json.dumps({"flow_token": "sawali-u1", "satisfaction": "4"})}}}],
    }}]}]}

    async def scenario():
        await db.whatsapp_flow_sends.insert_one({"flow_token": "sawali-u1", "template": "suivilogiciels_fr",
                                                 "to": "22670000000"})
        from starlette.requests import Request
        body = json.dumps(payload).encode()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        req = Request({"type": "http", "method": "POST", "path": "/api/whatsapp/webhook",
                       "headers": [], "query_string": b""}, receive)
        await server.whatsapp_webhook_incoming(req)
        await asyncio.sleep(0.05)                          # tâches d'événements lancées
        msgs = await db.whatsapp_messages.find({}, {"_id": 0}).to_list(10)
        resp = await db.whatsapp_flow_responses.find({}, {"_id": 0}).to_list(10)
        return msgs, resp
    msgs, resp = loop.run_until_complete(scenario())
    assert msgs and msgs[0]["body"].startswith("📋 Formulaire WhatsApp complété")
    assert "• satisfaction : 4" in msgs[0]["body"]
    assert resp[0]["template"] == "suivilogiciels_fr" and resp[0]["fields"] == {"satisfaction": "4"}
    ev = [e for e in emitted if e[0] == "whatsapp.flow_completed"]
    assert ev and ev[0][1]["extra_ctx"]["wa_flow_summary"] == "• satisfaction : 4"
    assert ev[0][1]["extra_ctx"]["wa_flow_template"] == "suivilogiciels_fr"
