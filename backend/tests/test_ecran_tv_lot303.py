"""Lot 303 — écran TV : code d'appairage conservé, conversations de RDV masquées, pastille de l'agent IA ;
« Réponses WA aux RDV » en lecture seule pour les médecins et le secrétariat médical."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes.ecran_tv import agent_ia, setup_ecran_tv_routes
from routes.planning_suivi_rdv import attach_planning_suivi_routes

SECRET = "secret-de-la-tele-0123456789"


def _run(c):
    return asyncio.get_event_loop().run_until_complete(c)


def il_y_a(h):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


def test_agent_ia_champ_signature_ou_liluvine():
    assert agent_ia({"direction": "inbound", "ai_generated": True}) == ""                  # un message reçu n'a pas d'agent
    assert agent_ia({"direction": "outbound", "body": "Bonjour"}) == ""                    # message humain : pas de pastille
    assert agent_ia({"direction": "outbound", "ai_generated": True, "agent_ia": "Awa"}) == "Awa"
    assert agent_ia({"direction": "outbound", "ai_generated": True, "body": "Ok\n\n— Robert (Comptable), assistant Liluvine 🤖"}) == "Robert"
    assert agent_ia({"direction": "outbound", "auto_reply": True, "body": "Réponse automatique"}) == "Liluvine"


def _tv():
    db = AsyncMongoMockClient()["test_tv_303"]
    _run(db.users.insert_one({"id": "cli-1", "company": "Clinique A"}))
    _run(db.whatsapp_messages.insert_many([
        # conversation ordinaire avec réponse de l'agent Awa
        {"id": "a1", "client_id": "cli-1", "direction": "inbound", "body": "Question facture", "phone_digits": "22670001111", "created_at": il_y_a(2)},
        {"id": "a2", "client_id": "cli-1", "direction": "outbound", "body": "Voici", "phone_digits": "22670001111", "created_at": il_y_a(1),
         "ai_generated": True, "agent_ia": "Awa"},
        # conversation d'un patient rappelé pour un RDV : doit disparaître (messages et non-lus)
        {"id": "r1", "client_id": "cli-1", "direction": "outbound", "body": "Rappel RDV", "phone_digits": "22670002222", "created_at": il_y_a(1)},
        {"id": "r2", "client_id": "cli-1", "direction": "inbound", "body": "Je viens", "phone_digits": "22670002222", "created_at": il_y_a(0.5), "read_by_us_at": None},
    ]))
    _run(db.planning_appointments.insert_one({"id": "p1", "patient_phone": "+226 70 00 22 22", "reminder_sent_at": il_y_a(1)}))

    async def admin(request: Request):
        return {"email": "admin@test"}

    api = APIRouter(prefix="/api")
    setup_ecran_tv_routes(db=db, api=api, get_current_admin=admin)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def test_code_conserve_rdv_masques_et_agent():
    c = _tv()
    d = c.post("/api/tv/appairage", json={"secret": SECRET}).json()
    r = c.post("/api/admin/tv/appairer", json={"code": d["code"], "nom": "Hall", "client_id": "cli-1"})
    assert r.json()["ecran"]["code"] == d["code"]                                          # 1. le code reste visible dans la liste
    assert c.get("/api/admin/tv/ecrans").json()["ecrans"][0]["code"] == d["code"]
    f = c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()
    assert [m["id"] for m in f["messages"]] == ["a1", "a2"]                                # 4. la conversation de RDV n'apparaît pas
    assert len(f["fils"]) == 1 and f["non_lus_total"] == 1      # seul le non-lu de la conversation ordinaire est compté
    assert f["messages"][1]["agent"] == "Awa" and f["messages"][0]["agent"] == ""          # 6. pastille de l'agent
    assert f["fils"][0]["agent"] == "Awa"


def _suivi():
    db = AsyncMongoMockClient()["test_suivi_303"]
    _run(db.planning_appointments.insert_many([
        {"id": "r1", "tenant_id": "soc-1", "medecin_id": "med-1", "medecin_email": "m1@x", "code_clinique": "CMCO", "patient": "KANE F",
         "medecin": "DR X", "patient_phone": "+226 70 00 11 22", "start_at": il_y_a(-1), "reminder_sent_at": il_y_a(1)},
        {"id": "r2", "tenant_id": "soc-1", "medecin_id": "med-2", "medecin_email": "m2@x", "code_clinique": "CMCO", "patient": "OUEDRAOGO A",
         "medecin": "DR Y", "patient_phone": "70002233", "start_at": il_y_a(-2), "reminder_sent_at": il_y_a(2)},
        {"id": "r3", "tenant_id": "soc-2", "medecin_id": "med-9", "code_clinique": "AUTRE", "patient": "AUTRE SOCIETE",
         "medecin": "DR Z", "patient_phone": "70009999", "start_at": il_y_a(-3), "reminder_sent_at": il_y_a(3)},
    ]))
    _run(db.whatsapp_messages.insert_many([
        {"id": "m1", "direction": "inbound", "body": "Merci", "phone_digits": "22670001122", "created_at": il_y_a(0.5)},
        {"id": "m9", "direction": "inbound", "body": "Secret", "phone_digits": "70009999", "created_at": il_y_a(0.5)},
    ]))
    profils = {
        "med1": {"id": "med-1", "email": "m1@x", "role": "client", "tracked_role": "Médecin", "client_id": "soc-1"},
        "sec": {"id": "sec-1", "email": "s@x", "role": "client", "tracked_role": "Secrétaire médicale", "client_id": "soc-1"},
        "compta": {"id": "c-1", "email": "c@x", "role": "client", "tracked_role": "Comptable", "client_id": "soc-1"},
    }

    async def utilisateur(request: Request):
        return profils[request.headers.get("x-profil", "compta")]

    async def visibles(user):
        return [user["client_id"]]

    api = APIRouter(prefix="/api")
    attach_planning_suivi_routes(api=api, db=db, get_current_user=utilisateur, is_admin_like=lambda u: u["role"] in ("admin", "superviseur"),
                                 resolve_visible_client_ids=visibles)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def test_reponses_rdv_lecture_seule_selon_le_role():
    c = _suivi()
    # Médecin : seulement SES patients ; secrétariat : tous ceux de la société ; jamais ceux d'une autre société
    med = c.get("/api/me/planning/suivi/fils", headers={"x-profil": "med1"}).json()["fils"]
    assert [f["patient"] for f in med] == ["KANE F"]
    sec = c.get("/api/me/planning/suivi/fils", headers={"x-profil": "sec"}).json()["fils"]
    assert {f["patient"] for f in sec} == {"KANE F", "OUEDRAOGO A"}
    # Fil d'un patient du périmètre : lisible ; fil d'un patient d'une autre société ou d'un autre médecin : 404
    ok = c.get("/api/me/planning/suivi/fil", headers={"x-profil": "med1"}, params={"telephone": "+226 70 00 11 22"})
    assert ok.status_code == 200 and any(m["texte"] == "Merci" for m in ok.json()["messages"])
    assert c.get("/api/me/planning/suivi/fil", headers={"x-profil": "sec"}, params={"telephone": "70009999"}).status_code == 404
    assert c.get("/api/me/planning/suivi/fil", headers={"x-profil": "med1"}, params={"telephone": "70002233"}).status_code == 404
    # Un autre rôle suivi (ex. comptable) n'y a pas accès
    assert c.get("/api/me/planning/suivi/fils", headers={"x-profil": "compta"}).status_code == 403


def test_contenu_hall_enregistre_et_relu():
    """Cocher « Hall » dans la liste des écrans doit être conservé (PUT puis relecture de la liste)."""
    c = _tv()
    d = c.post("/api/tv/appairage", json={"secret": SECRET}).json()
    ecran = c.post("/api/admin/tv/appairer", json={"code": d["code"], "nom": "Hall", "client_id": "cli-1"}).json()["ecran"]
    r = c.put(f"/api/admin/tv/ecrans/{ecran['id']}", json={"modules": {"messagerie": True, "support": True, "hall": True}})
    assert r.status_code == 200
    assert c.get("/api/admin/tv/ecrans").json()["ecrans"][0]["modules"] == {"messagerie": True, "support": True, "hall": True}


def test_photo_et_profession_du_medecin_dans_le_hall():
    from routes.ecran_tv import forme_hall, normaliser_portes
    petite = "data:image/jpeg;base64," + "A" * 100
    portes = normaliser_portes([
        {"medecin": "DR X", "porte": "201", "profession": "Cardiologue", "photo": petite},
        {"medecin": "DR Y", "porte": "202", "photo": "data:text/html;base64,AAAA"},                 # type refusé
        {"medecin": "DR Z", "porte": "203", "photo": "data:image/png;base64," + "A" * 70000},       # trop lourde
    ])
    par = {p["medecin"]: p for p in portes}
    assert par["DR X"]["profession"] == "Cardiologue" and par["DR X"]["photo"] == petite
    assert "photo" not in par["DR Y"] and "photo" not in par["DR Z"]
    maintenant = datetime.now(timezone.utc)
    docs = [{"medecin": "DR X", "start_at": maintenant.isoformat(), "is_rdv": 1}]
    sans = forme_hall(docs, {"dr x": "201"}, maintenant, fiches={"dr x": par["DR X"]}, avec_photos=False)["medecins"][0]
    avec = forme_hall(docs, {"dr x": "201"}, maintenant, fiches={"dr x": par["DR X"]}, avec_photos=True)["medecins"][0]
    assert sans["profession"] == "Cardiologue" and sans["a_photo"] and sans["photo"] == "" and avec["photo"] == petite
