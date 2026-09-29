"""Lot 27 — Facturation du portefeuille « Formulaires & Sondages WhatsApp » par client.

Tarifs et prompt par client (page SMART Communications), bilan de période
(chiffres, analyse IA, lignes de facture, PDF, lien public) et facture créée
dans la Caisse avec le vrai crochet de routes/cashier.py.
Tests autonomes : MongoDB simulé (mongomock-motor), IA simulée.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.portfolio_billing as pb  # noqa: E402

# num2words (somme en lettres des factures) n'est pas indispensable au test
try:
    import num2words  # noqa: F401
except ImportError:
    import types
    _m = types.ModuleType("num2words")
    _m.num2words = lambda n, **k: str(n)
    sys.modules["num2words"] = _m

D1, D2 = "2026-09-01", "2026-09-30"


def test_pure_helpers():
    assert pb.period_months("2026-09-01", "2026-09-30") == 1
    assert pb.period_months("2026-07-01", "2026-09-30") == 3
    assert pb.period_months("2026-09-10", "2026-09-12") == 1
    m = {"forms": {"active": 2, "submissions": 30}, "surveys": {"active": 1, "messages_sent": 100, "responses": 40}}
    s = {"monthly_fee": 25000, "per_active_form": 0, "per_active_survey": 5000, "per_wa_message": 50,
         "per_survey_response": 100, "per_form_submission": 0, "per_ai_report": 10000, "tva_pct": 18}
    lines = pb.billing_lines(s, m, months=1, with_ai=True)
    assert [(ln["key"], ln["quantity"], ln["total_ht"]) for ln in lines] == [
        ("monthly_fee", 1, 25000), ("per_active_survey", 1, 5000), ("per_wa_message", 100, 5000),
        ("per_survey_response", 40, 4000), ("per_ai_report", 1, 10000)]
    t = pb.totals_of(lines)
    assert t == {"total_ht": 49000, "total_tva": 8820, "total_ttc": 57820}
    assert not any(ln["key"] == "per_ai_report" for ln in pb.billing_lines(s, m, months=1, with_ai=False))
    assert pb._latin("Très bien 👍 → ok") == "Très bien  -> ok"


@pytest.fixture()
def env():
    import asyncio
    db = mongomock_motor.AsyncMongoMockClient()["sawali_pb"]
    admin = {"id": "u-admin", "role": "admin", "email": "admin@sawalismartsystems.com", "full_name": "Admin", "company": "SAWALI"}
    prompts = []

    async def get_admin():
        return admin

    async def fake_llm(system, user_text):
        prompts.append((system, user_text))
        return "## Chiffres clés\n- 2 réponses sur 3 envois (**66,7 %**)\n## Recommandations\n- Relancer les non-répondants", 1200

    tracked = []

    async def track(db_, **kw):
        tracked.append(kw)
        return {"allowed": True}

    # Vrai crochet de la Caisse (routes/cashier.py)
    from routes.cashier import make_router

    async def cur_user():
        return admin
    router, _ = make_router(db=db, get_current_user=cur_user, get_current_admin=cur_user, get_current_supervisor=cur_user)
    app = FastAPI()
    api = APIRouter(prefix="/api")
    pb.attach_portfolio_billing_routes(api=api, db=db, get_current_admin=get_admin, uuid_fn=lambda: uuid.uuid4().hex,
                                       public_base_url=lambda r: "https://sawali.test",
                                       create_invoice_for_client=router.create_invoice_for_client,
                                       llm_send=fake_llm, track_ai_usage=track)
    app.include_router(api)
    loop = asyncio.new_event_loop()

    async def seed():
        await db.users.insert_many([dict(admin), {"id": "u-phl", "role": "client", "company": "PHL", "full_name": "PHL Admin",
                                                  "phone": "+22670000000", "email": "phl@x.bf"}])
        await db.forms.insert_many([{"id": "f1", "client_id": "u-phl", "title": "Fiche de visite", "number": "FORM-PHL-0001"},
                                    {"id": "f2", "client_id": "u-phl", "title": "Inutilisé", "number": "FORM-PHL-0002"},
                                    {"id": "f3", "client_id": "u-autre", "title": "Autre client"}])
        await db.form_submissions.insert_many([
            {"form_id": "f1", "created_at": "2026-09-05T10:00:00+00:00"},
            {"form_id": "f1", "created_at": "2026-09-20T10:00:00+00:00"},
            {"form_id": "f1", "created_at": "2026-08-20T10:00:00+00:00"},          # hors période
            {"form_id": "f3", "created_at": "2026-09-05T10:00:00+00:00"}])         # autre client
        q = [{"id": "q1", "type": "nps", "label": "Reco", "required": True, "options": []},
             {"id": "q2", "type": "text", "label": "Avis", "required": False, "options": []}]
        await db.wa_surveys.insert_one({"id": "s1", "client_id": "u-phl", "title": "Satisfaction", "questions": q})
        await db.wa_survey_campaigns.insert_many([
            {"survey_id": "s1", "sent_ok": 3, "created_at": "2026-09-10T08:00:00+00:00"},
            {"survey_id": "s1", "sent_ok": 5, "created_at": "2026-08-10T08:00:00+00:00"}])   # hors période
        await db.wa_survey_invites.insert_many([
            {"id": "i1", "survey_id": "s1", "contact_id": "c1", "name": "Awa", "status": "sent",
             "last_sent_at": "2026-09-10T08:00:00+00:00", "answered_at": "2026-09-10T09:00:00+00:00"},
            {"id": "i2", "survey_id": "s1", "contact_id": "c2", "name": "Brice", "status": "sent",
             "last_sent_at": "2026-09-10T08:00:00+00:00", "answered_at": "2026-09-11T08:00:00+00:00"},
            {"id": "i3", "survey_id": "s1", "contact_id": "c3", "name": "Chantal", "status": "sent",
             "last_sent_at": "2026-09-10T08:00:00+00:00", "answered_at": None}])
        await db.wa_survey_responses.insert_many([
            {"survey_id": "s1", "invite_id": "i1", "answers": {"q1": 10, "q2": "Très bien"}, "created_at": "2026-09-10T09:00:00+00:00"},
            {"survey_id": "s1", "invite_id": "i2", "answers": {"q1": 6}, "created_at": "2026-09-11T08:00:00+00:00"}])
    loop.run_until_complete(seed())
    yield {"db": db, "client": TestClient(app), "prompts": prompts, "tracked": tracked, "loop": loop}
    loop.close()


def test_settings_report_invoice(env):
    c = env["client"]
    g = c.get("/api/admin/clients/u-phl/portfolio-billing").json()
    assert g["settings"]["tva_pct"] == 18 and g["default_prompt"] and len(g["tariffs"]) == 7
    assert c.get("/api/admin/clients/inconnu/portfolio-billing").status_code == 404
    r = c.put("/api/admin/clients/u-phl/portfolio-billing", json={
        "monthly_fee": 25000, "per_active_form": 2000, "per_wa_message": 50, "per_survey_response": 100,
        "per_ai_report": 10000, "tva_pct": 18, "ai_prompt": "Analyse pour le pharmacien. Sois bref.", "due_days": 10})
    assert r.status_code == 200 and r.json()["settings"]["ai_prompt"].startswith("Analyse pour")

    rep = c.post("/api/admin/clients/u-phl/portfolio-reports", json={"date_from": D1, "date_to": D2, "with_ai": True})
    assert rep.status_code == 200, rep.text
    rep = rep.json()
    m = rep["metrics"]
    assert (m["forms"]["total"], m["forms"]["active"], m["forms"]["submissions"]) == (2, 1, 2)
    assert (m["surveys"]["active"], m["surveys"]["messages_sent"], m["surveys"]["responses"]) == (1, 3, 2)
    assert m["surveys"]["items"][0]["nps"] == 0 and m["surveys"]["response_rate"] == 66.7
    assert [x["name"] for x in m["contributors"]] == ["Awa", "Brice"]
    # Prompt du client utilisé ; aucune donnée de téléphone envoyée à l'IA
    system, user_text = env["prompts"][0]
    assert system.startswith("Analyse pour le pharmacien") and "Très bien" in user_text and "+226" not in user_text
    assert env["tracked"][0]["resource"] == "chat"
    assert rep["analysis"].startswith("## Chiffres clés")
    assert [(ln["key"], ln["quantity"]) for ln in rep["lines"]] == [
        ("monthly_fee", 1), ("per_active_form", 1), ("per_wa_message", 3), ("per_survey_response", 2), ("per_ai_report", 1)]
    assert rep["total_ht"] == 25000 + 2000 + 150 + 200 + 10000 and rep["total_ttc"] == round(rep["total_ht"] * 1.18, 2)

    # PDF (admin) et lien public pour le client
    pdf = c.get(f"/api/admin/portfolio-reports/{rep['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and len(pdf.content) > 2000
    assert c.get(f"/api/public/portfolio-report/{rep['token']}").content[:4] == b"%PDF"
    assert c.get("/api/public/portfolio-report/faux").status_code == 404

    # Facture dans la Caisse : émise par SAWALI au client PHL
    inv = c.post(f"/api/admin/portfolio-reports/{rep['id']}/invoice", json={"kind": "invoice"})
    assert inv.status_code == 200, inv.text
    inv = inv.json()["invoice"]
    assert inv["number"].startswith("F-") and inv["net_to_pay"] == rep["total_ttc"]
    doc = env["loop"].run_until_complete(env["db"].invoices.find_one({"id": inv["id"]}))
    assert doc["business_client_snapshot"]["name"] == "PHL" and doc["tenant_id"] == "u-admin" and len(doc["items"]) == 5
    assert "du 01/09/2026 au 30/09/2026" in doc["items"][0]["label"] and doc["source"] == "portfolio_report"
    bc = env["loop"].run_until_complete(env["db"].business_clients.find_one({"linked_user_id": "u-phl"}))
    assert bc and bc["tenant_id"] == "u-admin"
    # Déjà facturé : refus ; une 2e facture réutilise la même fiche client
    assert c.post(f"/api/admin/portfolio-reports/{rep['id']}/invoice", json={"kind": "invoice"}).status_code == 409
    assert c.post(f"/api/admin/portfolio-reports/{rep['id']}/invoice", json={"kind": "proforma"}).json()["invoice"]["number"].startswith("FP-")
    assert env["loop"].run_until_complete(env["db"].business_clients.count_documents({"linked_user_id": "u-phl"})) == 1

    lst = c.get("/api/admin/clients/u-phl/portfolio-reports").json()["items"]
    assert lst[0]["invoice_number"] == inv["number"] and "metrics" not in lst[0]


def test_report_without_ai_and_errors(env):
    c = env["client"]
    r = c.post("/api/admin/clients/u-phl/portfolio-reports", json={"date_from": D1, "date_to": D2, "with_ai": False}).json()
    assert r["analysis"] is None and r["lines"] == [] and r["total_ttc"] == 0      # aucun tarif réglé
    assert c.post(f"/api/admin/portfolio-reports/{r['id']}/invoice", json={}).status_code == 400
    assert c.post("/api/admin/clients/u-phl/portfolio-reports", json={"date_from": D2, "date_to": D1}).status_code == 400


def test_shared_form_counts_only_client_submissions(env):
    db, loop = env["db"], env["loop"]

    async def seed():
        await db.forms.insert_one({"id": "fs", "client_id": "u-admin", "title": "Formulaire SAWALI partagé", "access_client_ids": ["u-phl"]})
        await db.form_submissions.insert_many([
            {"form_id": "fs", "client_id": "u-phl", "created_at": "2026-09-12T10:00:00+00:00"},
            {"form_id": "fs", "client_id": "u-autre", "created_at": "2026-09-12T10:00:00+00:00"}])
    loop.run_until_complete(seed())
    r = env["client"].post("/api/admin/clients/u-phl/portfolio-reports", json={"date_from": D1, "date_to": D2, "with_ai": False}).json()
    f = r["metrics"]["forms"]
    assert (f["total"], f["active"], f["submissions"]) == (3, 2, 3)


def test_supervisor_chooses_vat_per_invoice(env):
    c, db, loop = env["client"], env["db"], env["loop"]
    c.put("/api/admin/clients/u-phl/portfolio-billing", json={"monthly_fee": 10000, "tva_pct": 18})
    r1 = c.post("/api/admin/clients/u-phl/portfolio-reports", json={"date_from": D1, "date_to": D2, "with_ai": False}).json()
    r2 = c.post("/api/admin/clients/u-phl/portfolio-reports", json={"date_from": "2026-08-01", "date_to": "2026-08-31", "with_ai": False}).json()
    todo = c.get("/api/admin/portfolio-reports?status=to_invoice").json()["items"]
    assert {x["id"] for x in todo} == {r1["id"], r2["id"]} and "analysis" not in todo[0]
    # Sans TVA : total = HT
    a = c.post(f"/api/admin/portfolio-reports/{r1['id']}/invoice", json={"kind": "invoice", "apply_tva": False}).json()
    assert a["apply_tva"] is False and a["invoice"]["net_to_pay"] == 10000 and a["invoice"]["total_tva"] == 0
    # Avec TVA : 18 %
    b = c.post(f"/api/admin/portfolio-reports/{r2['id']}/invoice", json={"kind": "invoice", "apply_tva": True}).json()
    assert b["invoice"]["net_to_pay"] == 11800
    rep = loop.run_until_complete(db.portfolio_reports.find_one({"id": r1["id"]}))
    assert rep["invoiced_with_tva"] is False and rep["invoiced_amount"] == 10000
    assert c.get("/api/admin/portfolio-reports?status=to_invoice").json()["items"] == []
    assert len(c.get("/api/admin/portfolio-reports?status=invoiced").json()["items"]) == 2


def test_lot41_formulaires_liluvine_auto_et_force(env):
    """Lot 41 — commandes « !formulaire » de la période : badge AUTO / FORCÉ dans le bilan,
    ligne FORCÉ facturée au tarif de la commande, ligne AUTO à 0 FCFA pour mémoire."""
    c = env["client"]
    env["loop"].run_until_complete(env["db"].liluvine_formulaires.insert_many([
        {"id": "l1", "compte_id": "u-phl", "statut": "publie", "reference": "FORM-PHL-0003 · FORM_226_1",
         "publie_le": "2026-09-12T10:00:00+00:00", "mode_realisation": "force", "prix_xof": 2000, "force_par": "admin"},
        {"id": "l2", "compte_id": "u-phl", "statut": "publie", "reference": "FORM-PHL-0004 · FORM_226_2",
         "publie_le": "2026-09-13T10:00:00+00:00", "prix_xof": 2000},                  # ancien : pas de mode → auto
        {"id": "l3", "compte_id": "u-phl", "statut": "en_attente_paiement", "prix_xof": 2000},
        {"id": "l4", "compte_id": "u-phl", "statut": "publie", "mode_realisation": "force", "prix_xof": 2000,
         "publie_le": "2026-08-01T10:00:00+00:00"}]))                                   # hors période
    rep = c.post("/api/admin/clients/u-phl/portfolio-reports", json={"date_from": D1, "date_to": D2, "with_ai": False}).json()
    lil = rep["metrics"]["liluvine"]
    assert (lil["auto"], lil["force"]) == (1, 1) and [x["mode"] for x in lil["items"]] == ["force", "auto"]
    lignes = {ln["key"]: ln for ln in rep["lines"]}
    assert "[FORCÉ]" in lignes["liluvine_force"]["label"] and lignes["liluvine_force"]["total_ht"] == 2000
    assert "[AUTO]" in lignes["liluvine_auto"]["label"] and lignes["liluvine_auto"]["total_ht"] == 0
    assert rep["total_ht"] == 2000
    pdf = c.get(f"/api/admin/portfolio-reports/{rep['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    inv = c.post(f"/api/admin/portfolio-reports/{rep['id']}/invoice", json={"kind": "invoice"}).json()["invoice"]
    doc = env["loop"].run_until_complete(env["db"].invoices.find_one({"id": inv["id"]}))
    assert any("[FORCÉ]" in it["label"] for it in doc["items"]) and any("[AUTO]" in it["label"] for it in doc["items"])
