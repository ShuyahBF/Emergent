"""Lot 27 — Sondages WhatsApp.

Parcours complet : création, destinataires (tous les contacts d'un client,
groupes, échantillon), envoi (modèle Meta / message libre selon la fenêtre de
24 h) avec un lien personnel, réponse sur la page publique, résultats (taux,
statistiques par question, NPS), relance des non-répondants, export CSV.
Tests autonomes : MongoDB simulé (mongomock-motor), envois WhatsApp simulés.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.wa_surveys as ws  # noqa: E402

QUESTIONS = [
    {"type": "single", "label": "Logiciel utilisé", "options": ["Sage", "Odoo", "Autre"]},
    {"type": "multi", "label": "Modules", "options": ["Stock", "Paie", "Caisse"], "required": False},
    {"type": "yesno", "label": "Satisfait ?"},
    {"type": "rating", "label": "Note du support"},
    {"type": "nps", "label": "Nous recommanderiez-vous ?"},
    {"type": "text", "label": "Suggestions", "required": False},
]


def test_normalize_and_validate():
    qs = ws.normalize_questions(QUESTIONS, lambda: uuid.uuid4().hex[:8])
    assert [q["type"] for q in qs] == ["single", "multi", "yesno", "rating", "nps", "text"]
    with pytest.raises(ValueError, match="au moins 2 choix"):
        ws.normalize_questions([{"type": "single", "label": "x", "options": ["a"]}], lambda: "i")
    with pytest.raises(ValueError, match="intitulé"):
        ws.normalize_questions([{"type": "text", "label": " "}], lambda: "i")
    ok = {qs[0]["id"]: "Odoo", qs[1]["id"]: ["Caisse", "Stock"], qs[2]["id"]: "oui",
          qs[3]["id"]: "4", qs[4]["id"]: 9}
    clean = ws.validate_answers(qs, ok)
    assert clean[qs[1]["id"]] == ["Stock", "Caisse"] and clean[qs[3]["id"]] == 4
    with pytest.raises(ValueError, match="question 1"):
        ws.validate_answers(qs, {**ok, qs[0]["id"]: None})
    with pytest.raises(ValueError, match="entre 0 et 10"):
        ws.validate_answers(qs, {**ok, qs[4]["id"]: 11})


def test_stats_nps():
    qs = ws.normalize_questions([{"type": "nps", "label": "Reco"}, {"type": "rating", "label": "Note"}], lambda: uuid.uuid4().hex[:6])
    rs = [{"answers": {qs[0]["id"]: v, qs[1]["id"]: n}} for v, n in [(10, 5), (9, 4), (7, 3), (3, 1)]]
    st = ws.compute_question_stats(qs, rs)
    assert st[0]["promoters"] == 2 and st[0]["detractors"] == 1 and st[0]["nps"] == 25
    assert st[1]["average"] == 3.25


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setattr(ws, "SEND_PAUSE_SECONDS", 0)
    db = mongomock_motor.AsyncMongoMockClient()["sawali_surveys"]
    sent = []
    users = {
        "u-phl": {"id": "u-phl", "role": "client", "company": "PHL", "full_name": "PHL Admin"},
        "u-other": {"id": "u-other", "role": "client", "company": "Autre SA", "full_name": "Autre"},
    }
    current = {"user": users["u-phl"]}

    async def get_user():
        return current["user"]

    async def visible(user):
        return [user["id"]]

    async def wa_enabled(user):
        return True

    async def quota(user, n):
        return None

    async def send_template(to, name, lang, components):
        sent.append(("template", to, name, components))
        return {"ok": True, "status": 200, "message_id": f"wamid.{len(sent)}", "error": None}

    async def send_text(to, text):
        sent.append(("text", to, text))
        return {"ok": True, "status": 200, "message_id": f"wamid.{len(sent)}", "error": None}

    def build_ctx(kind, doc, phone, label):
        return {"full_name": doc.get("full_name") or label or "", "company": doc.get("company") or ""}

    def build_components(variables, ctx, header_text=None, button_specs=None):
        import re
        return [{"type": "body", "parameters": [
            {"type": "text", "text": re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: ctx.get(m.group(1), ""), v)} for v in variables]}]

    app = FastAPI()
    api = APIRouter(prefix="/api")
    h = ws.attach_wa_survey_routes(
        api=api, db=db, get_current_user=get_user, uuid_fn=lambda: uuid.uuid4().hex,
        can_send_wa=lambda u: True, is_admin_like=lambda u: False, resolve_visible_client_ids=visible,
        wa_enabled_for=wa_enabled, enforce_demo_quota=quota, wa_send_template=send_template,
        wa_send_text=send_text,
        wa_window_open=lambda iso: bool(iso) and datetime.fromisoformat(iso) > datetime.now(timezone.utc) - timedelta(hours=24),
        build_recipient_ctx=build_ctx, build_components=build_components,
        public_base_url=lambda req: "https://sawali.test")
    app.include_router(api)
    loop = asyncio.new_event_loop()

    def run(coro):
        return loop.run_until_complete(coro)

    async def seed():
        for u in users.values():
            await db.users.insert_one(dict(u))
        now = datetime.now(timezone.utc)
        await db.directory_contacts.insert_many([
            {"id": "c1", "client_id": "u-phl", "name": "Awa", "company": "PHL", "whatsapp": "+226 70 00 00 01"},
            {"id": "c2", "client_id": "u-phl", "name": "Brice", "company": "PHL", "whatsapp": "22670000002"},
            {"id": "c3", "client_id": "u-phl", "name": "Doublon Awa", "company": "PHL", "whatsapp": "22670000001"},
            {"id": "c4", "client_id": "u-phl", "name": "Sans numéro", "company": "PHL"},
            {"id": "c5", "client_id": "u-other", "name": "Hors périmètre", "company": "PHL", "whatsapp": "22670000009"},
        ])
        # Brice a écrit il y a 1 h : message libre possible
        await db.whatsapp_messages.insert_one({"direction": "inbound", "phone_digits": "22670000002",
                                               "created_at": (now - timedelta(hours=1)).isoformat()})
    run(seed())

    class _TC(TestClient):
        pass
    client = TestClient(app)
    yield {"db": db, "client": client, "sent": sent, "run": run, "h": h, "current": current, "users": users, "loop": loop}
    loop.close()


def _wait(env, sid):
    """Exécute l'envoi en arrière-plan (la tâche est lancée par la route)."""
    async def go():
        for t in list(env["h"]["running"].values()):
            await t
    # La tâche a été créée sur la boucle du client de test : on rejoue la campagne ici
    camps = env["run"](env["db"].wa_survey_campaigns.find({"survey_id": sid, "status": "running"}).to_list(10))
    for c in camps:
        env["run"](env["h"]["run_campaign"](c["id"]))


def test_full_flow(env):
    c = env["client"]
    r = c.post("/api/me/wa-surveys", json={"title": "Suivi logiciels", "questions": QUESTIONS,
                                           "thank_you": "Merci !"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    qs = r.json()["questions"]

    # Destinataires : tous les contacts du client PHL (hors périmètre exclu, doublon de numéro fusionné)
    p = c.post("/api/me/wa-surveys/recipients/preview", json={"client_ids": ["u-phl"], "survey_id": sid}).json()
    assert sorted(i["id"] for i in p["items"]) == ["c1", "c2"]
    assert p["window_open_count"] == 1 and p["items"][0]["phone"].count("•") == 3
    # Échantillon
    p1 = c.post("/api/me/wa-surveys/recipients/preview", json={"client_ids": ["u-phl"], "sample_size": 1}).json()
    assert len(p1["items"]) == 1 and p1["sampled"]

    # Modèle sans {{lien}} : refusé (le destinataire ne recevrait pas le lien)
    bad = c.post(f"/api/me/wa-surveys/{sid}/send", json={"contact_ids": ["c1"], "mode": "auto",
                                                         "template_name": "sondage_fr", "variables": ["{{name}}"]})
    assert bad.status_code == 400 and "{{lien}}" in bad.json()["detail"]

    r = c.post(f"/api/me/wa-surveys/{sid}/send", json={
        "contact_ids": ["c1", "c2"], "mode": "auto", "template_name": "sondage_fr",
        "variables": ["{{name}}", "{{lien}}"], "text_message": "Bonjour {{name}}, répondez ici : {{lien}}"})
    assert r.status_code == 200, r.text
    _wait(env, sid)
    kinds = sorted((s[0], s[1]) for s in env["sent"])
    # Awa (fenêtre fermée) -> modèle ; Brice (a écrit il y a 1 h) -> message libre
    assert kinds == [("template", "+226 70 00 00 01"), ("text", "22670000002")]
    tpl = [s for s in env["sent"] if s[0] == "template"][0]
    link = tpl[3][0]["parameters"][1]["text"]
    assert link.startswith("https://sawali.test/s/")
    token = link.rsplit("/", 1)[1]
    assert "Bonjour Brice" in [s for s in env["sent"] if s[0] == "text"][0][2]
    assert env["run"](env["db"].whatsapp_messages.count_documents({"survey_id": sid})) == 2
    assert env["run"](env["db"].wa_surveys.find_one({"id": sid}))["status"] == "active"

    # Page publique : ouverture puis réponse
    g = c.get(f"/api/public/surveys/{token}").json()
    assert g["title"] == "Suivi logiciels" and g["respondent"] == "Awa" and not g["already_answered"]
    miss = c.post(f"/api/public/surveys/{token}", json={"answers": {}})
    assert miss.status_code == 400 and "question 1" in miss.json()["detail"]
    ans = {qs[0]["id"]: "Odoo", qs[2]["id"]: "oui", qs[3]["id"]: 5, qs[4]["id"]: 10, qs[5]["id"]: "Très bien"}
    assert c.post(f"/api/public/surveys/{token}", json={"answers": ans}).json()["thank_you"] == "Merci !"
    # Correction de la réponse : une seule réponse gardée
    ans[qs[3]["id"]] = 4
    c.post(f"/api/public/surveys/{token}", json={"answers": ans})
    assert env["run"](env["db"].wa_survey_responses.count_documents({"survey_id": sid})) == 1

    res = c.get(f"/api/me/wa-surveys/{sid}/results").json()
    t = res["totals"]
    assert (t["invited"], t["sent"], t["opened"], t["answered"], t["response_rate"]) == (2, 2, 1, 1, 50.0)
    by = {q["type"]: q for q in res["questions"]}
    assert [o["count"] for o in by["single"]["options"]] == [0, 1, 0]
    assert by["rating"]["average"] == 4 and by["nps"]["nps"] == 100
    assert by["text"]["answers"][0]["name"] == "Awa"
    assert res["by_company"][0] == {"company": "PHL", "invited": 2, "sent": 2, "answered": 1, "rate": 50.0}

    # Relance : seulement Brice (pas encore répondu), même lien
    env["sent"].clear()
    rr = c.post(f"/api/me/wa-surveys/{sid}/send", json={"reminder": True, "mode": "text"})
    assert rr.status_code == 200 and rr.json()["campaign"]["total"] == 1
    _wait(env, sid)
    assert len(env["sent"]) == 1 and env["sent"][0][1] == "22670000002"
    inv = env["run"](env["db"].wa_survey_invites.find_one({"contact_id": "c2"}))
    assert inv["sent_count"] == 2
    # Déjà invités : exclus de la prochaine sélection
    p2 = c.post("/api/me/wa-surveys/recipients/preview", json={"client_ids": ["u-phl"], "survey_id": sid}).json()
    assert p2["items"] == [] and p2["excluded_invited"] == 2

    # Période : aujourd'hui -> la réponse compte ; hier seulement -> rien
    today = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    assert c.get(f"/api/me/wa-surveys/{sid}/results?date_from={today}").json()["totals"]["answered"] == 1
    old = c.get(f"/api/me/wa-surveys/{sid}/results?date_to={yesterday}").json()["totals"]
    assert (old["invited"], old["answered"]) == (0, 0)
    assert ws.in_period("2026-09-10T10:00:00", "2026-09-01", "2026-09-30") and not ws.in_period(None, "2026-09-01", None)

    csv = c.get(f"/api/me/wa-surveys/{sid}/export.csv")
    assert csv.status_code == 200 and "Awa;PHL" in csv.text and "Odoo" in csv.text

    lst = c.get("/api/me/wa-surveys").json()["items"][0]
    assert lst["stats"]["answered"] == 1 and lst["stats"]["response_rate"] == 50.0

    # Clôture : plus de réponse acceptée
    s = c.get(f"/api/me/wa-surveys/{sid}").json()
    c.put(f"/api/me/wa-surveys/{sid}", json={**{k: s[k] for k in ("title", "questions")}, "status": "closed"})
    assert c.post(f"/api/public/surveys/{token}", json={"answers": ans}).status_code == 409
    assert c.get(f"/api/public/surveys/{token}").json()["closed"] is True

    # Autre client : le sondage lui est invisible
    env["current"]["user"] = env["users"]["u-other"]
    assert c.get(f"/api/me/wa-surveys/{sid}").status_code == 404
    assert c.get("/api/me/wa-surveys").json()["items"] == []


def test_text_mode_skips_closed_window(env):
    c = env["client"]
    sid = c.post("/api/me/wa-surveys", json={"title": "S", "questions": QUESTIONS[:1]}).json()["id"]
    c.post(f"/api/me/wa-surveys/{sid}/send", json={"contact_ids": ["c1", "c2"], "mode": "text"})
    _wait(env, sid)
    assert [s[1] for s in env["sent"]] == ["22670000002"]
    inv = env["run"](env["db"].wa_survey_invites.find_one({"contact_id": "c1"}))
    assert inv["status"] == "skipped" and "24 h" in inv["error"]
    assert c.get("/api/public/surveys/inconnu").status_code == 404


def test_rank_contributors_pure():
    base = "2026-09-20T10:00:00+00:00"
    inv = [
        {"id": "1", "contact_id": "a", "name": "Awa", "survey_id": "s1", "status": "sent", "last_sent_at": base, "answered_at": "2026-09-20T12:00:00+00:00"},
        {"id": "2", "contact_id": "a", "name": "Awa", "survey_id": "s2", "status": "sent", "last_sent_at": base, "answered_at": "2026-09-20T11:00:00+00:00"},
        {"id": "3", "contact_id": "b", "name": "Brice", "survey_id": "s1", "status": "sent", "last_sent_at": base, "answered_at": "2026-09-21T10:00:00+00:00"},
        {"id": "4", "contact_id": "b", "name": "Brice", "survey_id": "s2", "status": "sent", "last_sent_at": base, "answered_at": None},
        {"id": "5", "contact_id": "c", "name": "Chantal", "survey_id": "s1", "status": "sent", "last_sent_at": base, "answered_at": None},
    ]
    rows = ws.rank_contributors(inv)
    assert [(r["name"], r["answered"], r["response_rate"]) for r in rows] == [("Awa", 2, 100.0), ("Brice", 1, 50.0)]
    assert rows[0]["avg_delay_hours"] == 1.5 and rows[0]["surveys"] == 2 and rows[0]["rank"] == 1


def test_contributors_route(env):
    c = env["client"]
    sid = c.post("/api/me/wa-surveys", json={"title": "S", "questions": QUESTIONS[:1]}).json()["id"]
    c.post(f"/api/me/wa-surveys/{sid}/send", json={"contact_ids": ["c1", "c2"], "mode": "text"})
    _wait(env, sid)
    tok = env["run"](env["db"].wa_survey_invites.find_one({"contact_id": "c2"}))["token"]
    q0 = c.get(f"/api/public/surveys/{tok}").json()["questions"][0]["id"]
    assert c.post(f"/api/public/surveys/{tok}", json={"answers": {q0: "Sage"}}).status_code == 200
    r = c.get("/api/me/wa-surveys-contributors").json()
    assert [x["name"] for x in r["items"]] == ["Brice"] and r["items"][0]["phone"].count("•") == 3
    assert r["tenants"][0]["answered"] == 1 and r["tenants"][0]["name"] == "PHL"
    # Autre client : rien de ce client
    env["current"]["user"] = env["users"]["u-other"]
    assert c.get("/api/me/wa-surveys-contributors").json()["items"] == []


def test_admin_creates_survey_for_client(env):
    c = env["client"]
    env["h"]  # admin-like simulé : on bascule le test sur un is_admin_like vrai via un 2e attachement
    import uuid as _u
    from fastapi import APIRouter, FastAPI
    app = FastAPI(); api = APIRouter(prefix="/api")
    admin = {"id": "u-admin", "role": "admin"}

    async def gu():
        return admin
    ws.attach_wa_survey_routes(api=api, db=env["db"], get_current_user=gu, uuid_fn=lambda: _u.uuid4().hex,
        can_send_wa=lambda u: True, is_admin_like=lambda u: True, resolve_visible_client_ids=None, wa_enabled_for=None,
        enforce_demo_quota=None, wa_send_template=None, wa_send_text=None, wa_window_open=lambda i: False,
        build_recipient_ctx=None, build_components=None, public_base_url=lambda r: "")
    app.include_router(api)
    from fastapi.testclient import TestClient
    a = TestClient(app)
    s = a.post("/api/me/wa-surveys", json={"title": "Pour PHL", "questions": QUESTIONS[:1], "client_id": "u-phl"}).json()
    assert s["client_id"] == "u-phl"
    assert a.post("/api/me/wa-surveys", json={"title": "X", "client_id": "inconnu"}).status_code == 400
    assert a.get("/api/me/wa-surveys").json()["items"][0]["client_name"] == "PHL"
    # Le client PHL voit le sondage créé pour lui
    assert c.get(f"/api/me/wa-surveys/{s['id']}").status_code == 200
