"""Lot 42 — Plages horaires d'envoi, envois programmés, envoi du lien d'un formulaire,
lien de sondage « plus disponible » pour un sondage de la plateforme.
Tests autonomes : MongoDB simulé (mongomock-motor), envois WhatsApp simulés."""
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

import routes.envois_formulaires as ef  # noqa: E402
import routes.plages_envoi as pe  # noqa: E402
import routes.wa_surveys as ws  # noqa: E402
from routes.fonctions_clients import attach_fonctions_clients_routes  # noqa: E402

UTC = timezone.utc
CFG = pe.normaliser({"actif": True, "fuseau": "Africa/Ouagadougou", "jours": [0, 1, 2, 3, 4],
                     "plages": [{"de": "15:00", "a": "19:00"}, {"de": "08:00", "a": "12:00"}]})


# ---- Fonctions pures ----------------------------------------------------------------
def test_normaliser():
    assert [p["de"] for p in CFG["plages"]] == ["08:00", "15:00"]           # triées
    with pytest.raises(ValueError, match="chevauchent"):
        pe.normaliser({"actif": True, "jours": [0], "plages": [{"de": "08:00", "a": "12:00"}, {"de": "11:00", "a": "13:00"}]})
    with pytest.raises(ValueError, match="fin doit suivre"):
        pe.normaliser({"actif": True, "jours": [0], "plages": [{"de": "12:00", "a": "08:00"}]})
    with pytest.raises(ValueError, match="HH:MM"):
        pe.normaliser({"actif": True, "jours": [0], "plages": [{"de": "8h", "a": "12:00"}]})
    with pytest.raises(ValueError, match="au moins un jour"):
        pe.normaliser({"actif": True, "jours": [], "plages": [{"de": "08:00", "a": "12:00"}]})
    with pytest.raises(ValueError, match="Fuseau"):
        pe.normaliser({"fuseau": "Mars/Olympus"})
    assert pe.normaliser(None)["actif"] is False


def test_prochaine_ouverture():
    lundi_10h = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)                     # Ouagadougou = UTC+0
    assert pe.dans_plage(CFG, lundi_10h) and pe.prochaine_ouverture(CFG, lundi_10h) is None
    assert pe.prochaine_ouverture(CFG, datetime(2026, 9, 28, 12, 0, tzinfo=UTC)) == datetime(2026, 9, 28, 15, 0, tzinfo=UTC)
    # Après la dernière plage : le lendemain à l'ouverture
    assert pe.prochaine_ouverture(CFG, datetime(2026, 9, 28, 19, 30, tzinfo=UTC)) == datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
    # Vendredi soir : lundi (samedi et dimanche interdits)
    assert pe.prochaine_ouverture(CFG, datetime(2026, 10, 2, 20, 0, tzinfo=UTC)) == datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    # Plages désactivées : toujours permis
    assert pe.prochaine_ouverture({**CFG, "actif": False}, datetime(2026, 10, 3, 3, 0, tzinfo=UTC)) is None
    assert pe.instant_programme("2026-10-01T09:30", CFG) == datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
    assert pe.instant_programme("", CFG) is None
    assert "Lun" in pe.resume_texte(CFG) and "08:00–12:00" in pe.resume_texte(CFG)


# ---- Environnement commun ----------------------------------------------------------------
@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setattr(ws, "SEND_PAUSE_SECONDS", 0)
    monkeypatch.setattr(ef, "SEND_PAUSE_SECONDS", 0)
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot42"]
    sent = []
    users = {
        "u-phl": {"id": "u-phl", "role": "client", "company": "PHL", "full_name": "PHL Admin",
                  "features": {"forms_surveys": False}},
        "plateforme": {"id": "plateforme", "role": "client", "company": "SAWALI", "email": "admin@sawalismartsystems.com"},
        "u-admin": {"id": "u-admin", "role": "admin", "full_name": "Admin", "client_id": "plateforme"},
    }
    current = {"user": users["u-phl"]}
    etat = {"attente": None}                          # prochaine ouverture simulée (None = dans la plage)

    async def get_user():
        return current["user"]

    async def visible(user):
        return [user["id"]]

    async def oui(*a, **k):
        return True

    async def rien(*a, **k):
        return None

    async def send_template(to, name, lang, components):
        sent.append(("template", to, name, components))
        return {"ok": True, "status": 200, "message_id": f"wamid.{len(sent)}"}

    async def send_text(to, text):
        sent.append(("text", to, text))
        return {"ok": True, "status": 200, "message_id": f"wamid.{len(sent)}"}

    def build_ctx(kind, doc, phone, label):
        return {"full_name": doc.get("full_name") or label or ""}

    def build_components(variables, ctx, header_text=None, button_specs=None):
        return [{"type": "body", "parameters": [{"type": "text", "text": ef.remplir(v, ctx)} for v in variables]}]

    async def attente():
        return etat["attente"]

    async def programme(texte):
        from fastapi import HTTPException
        try:
            return pe.instant_programme(texte, CFG)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    plages = {"attente": attente, "programme": programme}
    fc = attach_fonctions_clients_routes(api=APIRouter(), db=db, get_current_user=get_user,
                                         get_admin_or_supervisor=get_user,
                                         normalize_features=lambda f: f or {}, now=lambda: "")
    app = FastAPI()
    api = APIRouter(prefix="/api")
    h = ws.attach_wa_survey_routes(
        api=api, db=db, get_current_user=get_user, uuid_fn=lambda: uuid.uuid4().hex,
        can_send_wa=lambda u: True, is_admin_like=lambda u: u.get("role") in ("admin", "superviseur"),
        resolve_visible_client_ids=visible, wa_enabled_for=oui, enforce_demo_quota=rien,
        wa_send_template=send_template, wa_send_text=send_text, wa_window_open=lambda iso: False,
        build_recipient_ctx=build_ctx, build_components=build_components,
        public_base_url=lambda req: "https://sawali.test",
        owner_enabled=lambda cid: fc["fonction_active_pour_compte"](cid, "forms_surveys"), plages=plages)
    f = ef.attach_envois_formulaires_routes(
        api=api, db=db, get_current_user=get_user, uuid_fn=lambda: uuid.uuid4().hex, can_send_wa=lambda u: True,
        is_admin_like=lambda u: u.get("role") in ("admin", "superviseur"), wa_enabled_for=oui,
        enforce_demo_quota=rien, wa_send_template=send_template, wa_send_text=send_text,
        build_recipient_ctx=build_ctx, build_components=build_components,
        public_base_url=lambda req: "https://sawali.test", resolve_contacts=h["resolve_contacts"],
        open_window_digits=h["open_window_digits"], plages=plages)
    app.include_router(api)
    loop = asyncio.new_event_loop()
    run = loop.run_until_complete

    async def seed():
        for u in users.values():
            await db.users.insert_one(dict(u))
        await db.directory_contacts.insert_many([
            {"id": "c1", "client_id": "u-phl", "name": "Awa", "company": "PHL", "whatsapp": "22670000001"},
            {"id": "c2", "client_id": "u-phl", "name": "Brice", "company": "PHL", "whatsapp": "22670000002"},
        ])
        await db.forms.insert_one({"id": "f1", "client_id": "u-phl", "title": "Inscription", "number": "FORM-PHL-0001",
                                   "is_public": True})
        await db.forms.insert_one({"id": "f2", "client_id": "u-phl", "title": "Privé", "is_public": False})
    run(seed())
    yield {"db": db, "c": TestClient(app), "sent": sent, "run": run, "h": h, "f": f, "etat": etat,
           "current": current, "users": users, "fc": fc}
    loop.close()


def _sondage(env):
    r = env["c"].post("/api/me/wa-surveys", json={"title": "Suivi", "questions": [{"type": "yesno", "label": "Satisfait ?"}]})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _camp(env, sid):
    return env["run"](env["db"].wa_survey_campaigns.find_one({"survey_id": sid}, {"_id": 0}))


# ---- Sondages : plage horaire, reprise, programmation, annulation -------------------------
def test_sondage_attend_la_plage_puis_reprend(env):
    sid = _sondage(env)
    env["etat"]["attente"] = datetime.now(UTC) + timedelta(hours=10)          # hors plage
    r = env["c"].post(f"/api/me/wa-surveys/{sid}/send", json={"contact_ids": ["c1", "c2"], "mode": "template",
                                                               "template_name": "sondage_fr", "variables": ["{{lien}}"]})
    assert r.status_code == 200, r.text
    env["run"](env["h"]["run_campaign"](r.json()["campaign"]["id"]))
    c = _camp(env, sid)
    assert c["status"] == "waiting" and c["done"] == 0 and env["sent"] == []
    # Pas encore l'heure : le planificateur ne fait rien
    assert env["run"](env["h"]["lancer_echus"]()) == 0
    # La plage s'ouvre : reprise automatique
    env["etat"]["attente"] = None
    env["run"](env["db"].wa_survey_campaigns.update_one({"id": c["id"]}, {"$set": {"reprise_a": "2000-01-01T00:00:00+00:00"}}))
    assert env["run"](env["h"]["lancer_echus"]()) == 1
    env["run"](asyncio.gather(*env["h"]["running"].values()))         # tâche lancée par le planificateur
    c = _camp(env, sid)
    assert c["status"] == "done" and c["sent_ok"] == 2 and len(env["sent"]) == 2


def test_sondage_programme_et_annulation(env):
    sid = _sondage(env)
    demain = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    r = env["c"].post(f"/api/me/wa-surveys/{sid}/send", json={"contact_ids": ["c1"], "mode": "template",
                                                               "template_name": "t", "variables": ["{{lien}}"],
                                                               "programme_le": demain})
    assert r.status_code == 200 and r.json()["campaign"]["status"] == "scheduled"
    assert env["run"](env["h"]["lancer_echus"]()) == 0 and env["sent"] == []
    cid = r.json()["campaign"]["id"]
    assert env["c"].delete(f"/api/me/wa-surveys/{sid}/campaigns/{cid}").status_code == 200
    assert _camp(env, sid)["status"] == "cancelled"
    inv = env["run"](env["db"].wa_survey_invites.find_one({"survey_id": sid}))
    assert inv["status"] == "skipped" and inv["pending_campaign_id"] is None
    assert env["c"].delete(f"/api/me/wa-surveys/{sid}/campaigns/{cid}").status_code == 409
    # Date illisible : refusée
    bad = env["c"].post(f"/api/me/wa-surveys/{sid}/send", json={"contact_ids": ["c1"], "mode": "text",
                                                                 "programme_le": "demain matin"})
    assert bad.status_code == 400 and "invalide" in bad.json()["detail"]


# ---- Lien public d'un sondage de la plateforme ----------------------------------------------
def test_lien_sondage_plateforme_reste_disponible(env):
    env["current"]["user"] = env["users"]["u-admin"]            # sondage créé par l'Admin (compte plateforme)
    sid = _sondage(env)
    s = env["run"](env["db"].wa_surveys.find_one({"id": sid}))
    assert s["client_id"] == "plateforme"
    env["run"](env["db"].wa_survey_invites.insert_one({"id": "i1", "token": "tok1", "survey_id": sid, "name": "Awa"}))
    assert env["c"].get("/api/public/surveys/tok1").status_code == 200
    # Même sondage rattaché à PHL (fonction désactivée) : toujours actif car créé par l'Admin
    env["run"](env["db"].wa_surveys.update_one({"id": sid}, {"$set": {"client_id": "u-phl"}}))
    assert env["c"].get("/api/public/surveys/tok1").status_code == 200
    # Sondage créé par PHL, fonction désactivée : lien inactif (règle du lot 34 conservée)
    env["run"](env["db"].wa_surveys.update_one({"id": sid}, {"$set": {"created_by_id": "u-phl"}}))
    r = env["c"].get("/api/public/surveys/tok1")
    assert r.status_code == 404 and "plus disponible" in r.json()["detail"]
    # Compte plateforme : fonction toujours considérée active (formulaires publics aussi)
    assert env["run"](env["fc"]["fonction_active_pour_compte"]("plateforme", "forms_surveys"))
    assert not env["run"](env["fc"]["fonction_active_pour_compte"]("u-phl", "forms_surveys"))


# ---- Envoi du lien d'un formulaire -------------------------------------------------------------
def test_envoi_formulaire(env):
    c = env["c"]
    assert c.post("/api/me/forms/f2/envois", json={"contact_ids": ["c1"], "mode": "text"}).status_code == 400   # non public
    bad = c.post("/api/me/forms/f1/envois", json={"contact_ids": ["c1"], "mode": "template", "template_name": "t",
                                                  "variables": ["{{name}}"]})
    assert bad.status_code == 400 and "{{lien}}" in bad.json()["detail"]
    r = c.post("/api/me/forms/f1/envois", json={"contact_ids": ["c1", "c2"], "mode": "template", "template_name": "t",
                                                "variables": ["{{name}}", "{{lien}}", "{{formulaire}}"]})
    assert r.status_code == 200, r.text
    eid = r.json()["envoi"]["id"]
    env["run"](env["f"]["executer"](eid))
    params = env["sent"][0][3][0]["parameters"]
    assert params[1]["text"] == "https://sawali.test/f/f1" and params[2]["text"] == "Inscription"
    lst = c.get("/api/me/forms/f1/envois").json()["items"]
    assert lst[0]["status"] == "done" and lst[0]["sent_ok"] == 2 and lst[0]["echecs"] == []
    assert env["run"](env["db"].whatsapp_messages.count_documents({"form_id": "f1"})) == 2


def test_envoi_formulaire_hors_plage_et_reprise(env):
    env["etat"]["attente"] = datetime.now(UTC) + timedelta(hours=3)
    r = env["c"].post("/api/me/forms/f1/envois", json={"contact_ids": ["c1", "c2"], "mode": "template",
                                                       "template_name": "t", "variables": ["{{lien}}"]})
    eid = r.json()["envoi"]["id"]
    env["run"](env["f"]["executer"](eid))
    e = env["run"](env["db"].form_envois.find_one({"id": eid}))
    assert e["status"] == "waiting" and e["done"] == 0
    env["etat"]["attente"] = None
    env["run"](env["db"].form_envois.update_one({"id": eid}, {"$set": {"reprise_a": "2000-01-01T00:00:00+00:00"}}))
    assert env["run"](env["f"]["lancer_echus"]()) == 1
    env["run"](asyncio.gather(*env["f"]["en_cours"].values()))         # tâche lancée par le planificateur
    e = env["run"](env["db"].form_envois.find_one({"id": eid}))
    assert e["status"] == "done" and e["sent_ok"] == 2
    # Programmé puis annulé
    demain = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    r = env["c"].post("/api/me/forms/f1/envois", json={"contact_ids": ["c1"], "mode": "template", "template_name": "t",
                                                       "variables": ["{{lien}}"], "programme_le": demain})
    assert r.json()["envoi"]["status"] == "scheduled"
    assert env["c"].delete(f"/api/me/forms/f1/envois/{r.json()['envoi']['id']}").status_code == 200
