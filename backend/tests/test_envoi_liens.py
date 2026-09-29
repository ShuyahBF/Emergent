"""Lot 35 — Envoi du lien d'un sondage par SMS à un groupe de contacts.

Même moteur que l'envoi WhatsApp (lot 27) : une invitation et un lien personnel
(/s/<jeton>) par contact, envoi en tâche de fond, relance des non-répondants.
Par SMS : pas de modèle Meta ni de fenêtre de 24 h, module SMS du client requis,
quota SMS, trace dans l'historique des SMS. Envois simulés, MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_envoi_liens.py -q
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.wa_surveys as ws  # noqa: E402


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setattr(ws, "SEND_PAUSE_SECONDS", 0)
    db = mongomock_motor.AsyncMongoMockClient()["sawali_liens"]
    etat = {"sms_autorise": True, "wa_appels": [], "sms": [], "quota_sms": [], "quota_wa": []}
    user = {"id": "u-phl", "role": "client", "company": "PHL", "full_name": "PHL Admin"}

    async def get_user():
        return user

    async def visible(u):
        return [u["id"]]

    async def wa_enabled(u):
        etat["wa_appels"].append("wa_enabled")
        return False                       # WhatsApp NON activé : l'envoi SMS ne doit pas en dépendre

    async def sms_enabled(u):
        return etat["sms_autorise"]

    async def sms_send(numero, texte):
        etat["sms"].append((numero, texte))
        if numero.endswith("99"):
            return {"ok": False, "status": "error", "api_message": "Numéro refusé par l'opérateur", "provider": "orange"}
        return {"ok": True, "status": "sent", "api_message": "OK", "provider": "orange"}

    async def quota_sms(u, n):
        etat["quota_sms"].append(n)

    async def quota_wa(u, n):
        etat["quota_wa"].append(n)

    def build_ctx(kind, doc, phone, label):
        return {"full_name": doc.get("full_name") or label or "", "company": doc.get("company") or ""}

    api = APIRouter(prefix="/api")
    h = ws.attach_wa_survey_routes(
        api=api, db=db, get_current_user=get_user, uuid_fn=lambda: uuid.uuid4().hex,
        can_send_wa=lambda u: True, is_admin_like=lambda u: False, resolve_visible_client_ids=visible,
        wa_enabled_for=wa_enabled, enforce_demo_quota=quota_wa, wa_send_template=None, wa_send_text=None,
        wa_window_open=lambda iso: False, build_recipient_ctx=build_ctx, build_components=None,
        public_base_url=lambda req: "https://sawali.test",
        sms_enabled_for=sms_enabled, sms_send=sms_send, enforce_sms_quota=quota_sms)
    app = FastAPI()
    app.include_router(api)
    loop = asyncio.new_event_loop()
    run = loop.run_until_complete
    run(db.directory_contacts.insert_many([
        {"id": "c1", "client_id": "u-phl", "name": "Awa", "phone": "+226 70 00 00 01"},
        {"id": "c2", "client_id": "u-phl", "name": "Brice", "whatsapp": "22670000002"},
        {"id": "c3", "client_id": "u-phl", "name": "Refusé", "phone": "22670000099"},
    ]))
    run(db.contact_groups.insert_one({"id": "g1", "client_id": "u-phl", "name": "Clients fidèles",
                                      "contact_ids": ["c1", "c2", "c3"]}))
    yield {"client": TestClient(app), "db": db, "run": run, "h": h, "etat": etat}
    loop.close()


def _executer(env, sid):
    """Rejoue la campagne lancée en arrière-plan par la route."""
    camps = env["run"](env["db"].wa_survey_campaigns.find({"survey_id": sid, "status": "running"}).to_list(10))
    for c in camps:
        env["run"](env["h"]["run_campaign"](c["id"]))


def _sondage(env):
    r = env["client"].post("/api/me/wa-surveys", json={"title": "Satisfaction", "questions": [
        {"type": "yesno", "label": "Satisfait ?"}]})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_envoi_par_sms_a_un_groupe(env):
    c, etat = env["client"], env["etat"]
    sid = _sondage(env)
    # Destinataires : le groupe (même calcul que pour WhatsApp)
    p = c.post("/api/me/wa-surveys/recipients/preview", json={"group_ids": ["g1"], "survey_id": sid}).json()
    ids = [i["id"] for i in p["items"]]
    assert sorted(ids) == ["c1", "c2", "c3"]
    r = c.post(f"/api/me/wa-surveys/{sid}/send", json={
        "contact_ids": ids, "channel": "sms",
        "text_message": "Bonjour {{name}}, votre avis sur « {{sondage}} » : {{lien}}"})
    assert r.status_code == 200, r.text
    camp = r.json()["campaign"]
    assert camp["mode"] == "sms" and camp["template_name"] is None and camp["total"] == 3
    assert etat["quota_sms"] == [3] and etat["quota_wa"] == [] and etat["wa_appels"] == []
    _executer(env, sid)
    # Un SMS par contact, avec SON lien personnel
    invites = {i["contact_id"]: i for i in env["run"](env["db"].wa_survey_invites.find({"survey_id": sid}).to_list(10))}
    textes = dict(etat["sms"])
    assert textes["+226 70 00 00 01"] == f"Bonjour Awa, votre avis sur « Satisfaction » : https://sawali.test/s/{invites['c1']['token']}"
    assert textes["22670000002"].endswith(f"/s/{invites['c2']['token']}")
    assert invites["c1"]["status"] == "sent" and invites["c1"]["channel"] == "sms"
    assert invites["c3"]["status"] == "failed" and invites["c3"]["error"] == "Numéro refusé par l'opérateur"
    fin = env["run"](env["db"].wa_survey_campaigns.find_one({"id": camp["id"]}))
    assert (fin["status"], fin["sent_ok"], fin["sent_ko"]) == ("done", 2, 1)
    # Trace dans l'historique des SMS, rien dans les messages WhatsApp
    traces = env["run"](env["db"].sms_messages.find({"survey_id": sid}).to_list(10))
    assert len(traces) == 3 and all(t["bulk"] for t in traces)
    assert env["run"](env["db"].whatsapp_messages.count_documents({})) == 0


def test_message_par_defaut_et_relance(env):
    c, etat = env["client"], env["etat"]
    sid = _sondage(env)
    # Sans texte : message par défaut ; lien ajouté même s'il manque dans le texte
    c.post(f"/api/me/wa-surveys/{sid}/send", json={"contact_ids": ["c1"], "channel": "sms"})
    _executer(env, sid)
    assert etat["sms"][-1][1].startswith("Bonjour Awa, merci de repondre a notre sondage « Satisfaction » : https://")
    c.post(f"/api/me/wa-surveys/{sid}/send", json={"contact_ids": ["c2"], "channel": "sms", "text_message": "Merci !"})
    _executer(env, sid)
    assert etat["sms"][-1][1].startswith("Merci ! https://sawali.test/s/")
    # Relance par SMS des non-répondants : même lien personnel
    avant = len(etat["sms"])
    r = c.post(f"/api/me/wa-surveys/{sid}/send", json={"reminder": True, "channel": "sms"})
    assert r.status_code == 200 and r.json()["campaign"]["kind"] == "reminder"
    _executer(env, sid)
    assert len(etat["sms"]) == avant + 2


def test_refus_sms(env):
    c, etat = env["client"], env["etat"]
    sid = _sondage(env)
    etat["sms_autorise"] = False
    r = c.post(f"/api/me/wa-surveys/{sid}/send", json={"contact_ids": ["c1"], "channel": "sms"})
    assert r.status_code == 403 and r.json()["detail"] == "SMS non autorisé pour votre compte"
    etat["sms_autorise"] = True
    r = c.post(f"/api/me/wa-surveys/{sid}/send", json={"contact_ids": ["c1"], "channel": "sms", "text_message": "x" * 801})
    assert r.status_code == 400
    # WhatsApp reste soumis à son propre contrôle (non activé ici)
    r = c.post(f"/api/me/wa-surveys/{sid}/send", json={"contact_ids": ["c1"], "mode": "text"})
    assert r.status_code == 403 and "WhatsApp" in r.json()["detail"]
    assert etat["sms"] == []
