"""Lot 292 — suivi des conversations de rappels de RDV : comptes, fils par patient, fil complet, droits."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes.planning_suivi_rdv import attach_planning_suivi_routes, derniers8, variantes_numero


def _run(c):
    return asyncio.get_event_loop().run_until_complete(c)


def il_y_a(h):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


def test_cle_et_variantes_de_numero():
    assert derniers8("+226 70 00 11 22") == derniers8("70001122") == "70001122"
    assert derniers8("123") == ""
    assert set(variantes_numero("+226 70 00 11 22")) == {"22670001122", "70001122"}


def _client():
    db = AsyncMongoMockClient()["test_suivi_292"]
    _run(db.planning_appointments.insert_many([
        {"id": "r1", "code_clinique": "CMCO", "patient": "KANE F", "medecin": "DR X", "patient_phone": "+226 70 00 11 22",
         "start_at": il_y_a(-1), "reminder_sent_at": il_y_a(1), "reminder_status": "sent", "report_reponse_at": il_y_a(0.5)},
        {"id": "r2", "code_clinique": "CMCO", "patient": "OUEDRAOGO A", "medecin": "DR Y", "patient_phone": "70002233",
         "start_at": il_y_a(-2), "reminder_sent_at": il_y_a(2), "reminder_status": "sent"},
        {"id": "r3", "code_clinique": "CMC", "patient": "AUTRE", "medecin": "DR Z", "patient_phone": "70009999",
         "start_at": il_y_a(-3), "reminder_sent_at": il_y_a(3), "reminder_status": "sent"},
        {"id": "r4", "code_clinique": "CMCO", "patient": "SANS RAPPEL", "patient_phone": "70004444", "start_at": il_y_a(-4)},
    ]))
    _run(db.whatsapp_messages.insert_many([
        {"id": "m1", "direction": "outbound", "body": "Rappel RDV", "phone_digits": "22670001122", "created_at": il_y_a(1)},
        {"id": "m2", "direction": "inbound", "body": "Je veux reporter mon rendez-vous", "phone_digits": "22670001122", "created_at": il_y_a(0.7)},
        {"id": "m3", "direction": "outbound", "body": "📞 Appelez l'accueil", "phone_digits": "22670001122", "created_at": il_y_a(0.5), "auto_reply": True},
        {"id": "m4", "direction": "inbound", "body": "Merci", "phone_digits": "70002233", "created_at": il_y_a(1.5)},
    ]))

    async def utilisateur(request: Request):
        return {"id": "u", "role": request.headers.get("x-role", "admin")}

    api = APIRouter(prefix="/api")
    attach_planning_suivi_routes(api=api, db=db, get_current_user=utilisateur, is_admin_like=lambda u: u["role"] in ("admin", "superviseur"))
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def test_comptes_fils_et_fil_complet():
    c = _client()
    comptes = c.get("/api/admin/planning/suivi/comptes").json()["comptes"]
    assert {x["code"]: x["rappels"] for x in comptes} == {"CMCO": 2, "CMC": 1}      # le RDV sans rappel n'est pas compté
    fils = c.get("/api/admin/planning/suivi/fils", params={"code": "cmco", "jours": 7}).json()["fils"]
    assert [f["patient"] for f in fils] == ["KANE F", "OUEDRAOGO A"] or [f["patient"] for f in fils] == ["OUEDRAOGO A", "KANE F"]
    kane = next(f for f in fils if f["patient"] == "KANE F")
    assert kane["nb_messages"] == 3 and kane["a_repondu"] and kane["demande_report"] and kane["reponse_auto_le"]
    # Le patient dont le numéro est stocké sans indicatif est rapproché quand même ; « Merci » n'est pas une demande de report
    ouedr = next(f for f in fils if f["patient"] == "OUEDRAOGO A")
    assert ouedr["a_repondu"] and not ouedr["demande_report"]
    assert "AUTRE" not in str(fils)                                                    # l'autre compte n'apparaît pas
    tous = c.get("/api/admin/planning/suivi/fils", params={"jours": 7}).json()["fils"]
    assert len(tous) == 3
    fil = c.get("/api/admin/planning/suivi/fil", params={"telephone": "+226 70 00 11 22"}).json()["messages"]
    assert [m["sens"] for m in fil] == ["sortant", "entrant", "sortant"] and fil[2]["liluvine"] is True


def test_rappel_non_journalise_ajoute_au_fil_et_droits():
    c = _client()
    fil = c.get("/api/admin/planning/suivi/fil", params={"telephone": "70009999"}).json()["messages"]
    assert len(fil) == 1 and fil[0]["texte"].startswith("🔔 Rappel de RDV envoyé")       # ce patient n'a aucun message journalisé
    assert c.get("/api/admin/planning/suivi/comptes", headers={"x-role": "client"}).status_code == 403
    assert c.get("/api/admin/planning/suivi/fil", params={"telephone": "12"}).status_code == 400
