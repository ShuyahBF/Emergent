"""Lot 289 — écrans TV : appairage par code, flux messagerie + support, masquage des numéros, révocation."""
import asyncio

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes.ecran_tv import forme_message, forme_ticket, masquer_numero, nouveau_code, setup_ecran_tv_routes

SECRET = "secret-de-la-tele-0123456789"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_numero_masque_et_nom_prefere():
    assert masquer_numero("22670001122") == "•••• 1122"
    assert masquer_numero("12") == "Contact"
    m = forme_message({"id": "1", "direction": "inbound", "body": "Bonjour", "phone_digits": "22670001122", "created_at": "2026-10-24T10:00:00+00:00"})
    assert m["nom"] == "•••• 1122" and m["sens"] == "entrant" and "70001122" not in str(m)
    assert forme_message({"direction": "outbound", "body": "", "message_type": "image", "contact_name": "Dr Kane"})["texte"] == "📷 Image"
    assert forme_ticket({"id": "t", "number": "TKT-1", "motif": "Imprimante", "status": "open"})["numero"] == "TKT-1"


def test_code_lisible_sans_caracteres_ambigus():
    for _ in range(50):
        c = nouveau_code()
        assert len(c) == 6 and not set(c) & set("ILO01")


def _app():
    base = AsyncMongoMockClient()["test_tv_289"]
    _run(base.users.insert_one({"id": "cli-1", "company": "Clinique A"}))
    _run(base.whatsapp_messages.insert_many([
        {"id": "m1", "client_id": "cli-1", "direction": "inbound", "body": "Bonjour", "phone_digits": "22670001122", "created_at": "2026-10-24T10:00:00+00:00"},
        {"id": "m2", "client_id": "cli-1", "direction": "outbound", "body": "Réponse", "contact_name": "Fatimata", "created_at": "2026-10-24T10:01:00+00:00"},
        {"id": "m3", "client_id": "autre", "direction": "inbound", "body": "Secret d'un autre client", "created_at": "2026-10-24T10:02:00+00:00"},
    ]))
    _run(base.support_tickets.insert_many([
        {"id": "t1", "client_id": "cli-1", "number": "TKT-1", "motif": "Imprimante", "status": "open", "opened_at": "2026-10-24T09:00:00+00:00"},
        {"id": "t2", "client_id": "cli-1", "number": "TKT-2", "motif": "Réglé", "status": "closed", "opened_at": "2026-10-24T08:00:00+00:00"},
    ]))

    async def admin(request: Request):
        if request.headers.get("x-admin") != "1":
            raise HTTPException(status_code=403, detail="admin requis")
        return {"email": "admin@test"}

    api = APIRouter(prefix="/api")
    setup_ecran_tv_routes(db=base, api=api, get_current_admin=admin)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), base


def test_appairage_flux_et_revocation():
    c, _ = _app()
    adm = {"x-admin": "1"}
    # La télé demande un code ; avant l'accord elle est « en attente » et le flux lui est refusé
    d = c.post("/api/tv/appairage", json={"secret": SECRET}).json()
    assert c.get(f"/api/tv/appairage/{d['appairage_id']}", headers={"x-tv-secret": SECRET}).json()["etat"] == "attente"
    assert c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).status_code == 401
    # L'administrateur saisit le code (avec un tiret et en minuscules : toléré) ; client inconnu refusé, code inconnu refusé
    assert c.post("/api/admin/tv/appairer", headers=adm, json={"code": d["code"], "nom": "Hall", "client_id": "nope"}).status_code == 404
    assert c.post("/api/admin/tv/appairer", headers=adm, json={"code": "ZZZZZZ", "nom": "Hall", "client_id": "cli-1"}).status_code == 404
    assert c.post("/api/admin/tv/appairer", headers={}, json={"code": d["code"], "nom": "Hall", "client_id": "cli-1"}).status_code == 403
    r = c.post("/api/admin/tv/appairer", headers=adm, json={"code": d["code"].lower(), "nom": "Hall", "client_id": "cli-1"})
    assert r.status_code == 200 and "empreinte" not in r.json()["ecran"]
    ecran_id = r.json()["ecran"]["id"]
    assert c.get(f"/api/tv/appairage/{d['appairage_id']}", headers={"x-tv-secret": SECRET}).json()["etat"] == "ok"
    # Le flux ne contient que les messages et tickets OUVERTS de CE client, sans numéro complet
    f = c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()
    assert [m["id"] for m in f["messages"]] == ["m1", "m2"]
    assert f["messages"][0]["nom"] == "•••• 1122" and f["messages"][1]["nom"] == "Fatimata"
    assert [t["numero"] for t in f["support"]] == ["TKT-1"]
    assert "70001122" not in str(f) and "autre client" not in str(f)
    # Un secret quelconque est refusé ; décocher « support » le retire du flux
    assert c.get("/api/tv/flux", headers={"x-tv-secret": "autre-secret-0123456789"}).status_code == 401
    assert c.put(f"/api/admin/tv/ecrans/{ecran_id}", headers=adm, json={"modules": {"messagerie": True, "support": False}}).status_code == 200
    f2 = c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()
    assert "support" not in f2 and "messages" in f2
    # La liste admin ne révèle jamais l'empreinte ; la révocation refuse aussitôt la télé
    liste = c.get("/api/admin/tv/ecrans", headers=adm).json()["ecrans"]
    assert len(liste) == 1 and "empreinte" not in liste[0] and liste[0]["vu_le"]
    assert c.delete(f"/api/admin/tv/ecrans/{ecran_id}", headers=adm).status_code == 200
    assert c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).status_code == 401
    assert c.get(f"/api/tv/appairage/{d['appairage_id']}", headers={"x-tv-secret": SECRET}).json()["etat"] == "expire"


def test_perimetre_de_la_societe_comme_le_centre_de_messagerie():
    """Lot 298 — le client choisi à l'appairage est un compte de la société ; les messages sont rangés sous le compte principal."""
    base = AsyncMongoMockClient()["test_tv_298"]
    _run(base.users.insert_many([{"id": "sous-compte", "company": "SAWALI", "client_id": "racine"}, {"id": "racine", "company": "SAWALI"}]))
    _run(base.whatsapp_messages.insert_one({"id": "m1", "client_id": "racine", "direction": "inbound", "body": "Bonjour",
                                            "phone_digits": "22670001122", "created_at": "2026-10-26T10:00:00+00:00"}))
    _run(base.support_tickets.insert_one({"id": "t1", "client_id": "racine", "number": "TKT-9", "motif": "Panne", "status": "open",
                                          "opened_at": "2026-10-26T09:00:00+00:00"}))

    async def admin(request: Request):
        return {"email": "admin@test"}

    async def perimetre(compte):          # même rôle que _resolve_visible_client_ids : compte, rattachement, société
        return [compte["id"], compte.get("client_id") or compte["id"]]

    api = APIRouter(prefix="/api")
    setup_ecran_tv_routes(db=base, api=api, get_current_admin=admin, resolve_visible_client_ids=perimetre)
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app)
    d = c.post("/api/tv/appairage", json={"secret": SECRET}).json()
    assert c.post("/api/admin/tv/appairer", json={"code": d["code"], "nom": "Bureau", "client_id": "sous-compte"}).status_code == 200
    f = c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()
    assert [m["id"] for m in f["messages"]] == ["m1"] and [t["numero"] for t in f["support"]] == ["TKT-9"]


def test_fils_avec_noms_et_non_lus():
    """Lot 299 — l'écran reçoit les conversations (nom du contact, dernier message, non-lus) et les messages portent le nom du contact."""
    c, base = _app()
    _run(base.directory_contacts.insert_one({"id": "k1", "name": "Dr GACKO", "client_id": "cli-1"}))
    _run(base.whatsapp_messages.insert_many([
        {"id": "n1", "client_id": "cli-1", "contact_id": "k1", "direction": "inbound", "body": "Bonsoir", "phone_digits": "22607332313",
         "created_at": "2026-10-26T11:00:00+00:00", "read_by_us_at": None},
        {"id": "n2", "client_id": "cli-1", "contact_id": "k1", "direction": "inbound", "body": "Merci", "phone_digits": "22607332313",
         "created_at": "2026-10-26T11:05:00+00:00", "read_by_us_at": None},
        {"id": "n3", "client_id": "cli-1", "contact_id": "k1", "direction": "inbound", "body": "Déjà lu", "phone_digits": "22607332313",
         "created_at": "2026-10-26T10:00:00+00:00", "read_by_us_at": "2026-10-26T10:01:00+00:00"}]))
    d = c.post("/api/tv/appairage", json={"secret": SECRET}).json()
    c.post("/api/admin/tv/appairer", headers={"x-admin": "1"}, json={"code": d["code"], "nom": "Hall", "client_id": "cli-1"})
    f = c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()
    gacko = next(x for x in f["fils"] if x["cle"] == "k1")
    assert gacko["nom"] == "Dr GACKO" and gacko["non_lus"] == 2 and gacko["dernier"] == "Merci"
    assert all(m["nom"] == "Dr GACKO" for m in f["messages"] if m["fil"] == "k1")
    assert "22607332313" not in str(f) and f["non_lus_total"] >= 2


# ------------------------------------------------------------------------------------------------ lot 300 : hall
def _doc(medecin, debut=None, ordre=None, type_evt=None, rdv=1, recu="2026-10-26T07:00:00+00:00", maj="2026-10-26T07:00:00+00:00"):
    d = {"medecin": medecin, "is_rdv": rdv, "start_at": debut, "received_at": recu, "updated_at": maj, "numero_ordre": ordre}
    if type_evt:
        d["type_evenement"] = type_evt
    return d


def test_hall_prochain_patient_porte_et_etats():
    """Lot 305 : les RDV sont pris tels quels (type_evenement ignoré) ; le prochain RDV non passé donne le « prochain patient »."""
    from datetime import datetime, timezone
    from routes.ecran_tv import forme_hall
    maintenant = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)
    docs = [
        _doc("Dr X", "2026-10-26T10:30:00+00:00"),                                   # RDV à venir
        _doc("Dr X", "2026-10-26T10:10:00+00:00", ordre=12),                         # RDV plus proche
        _doc("Dr X", "2026-10-26T09:30:00+00:00", ordre=9, type_evt="CST"),          # type ignoré : simple RDV déjà passé
        _doc("Dr Y", None, ordre=21, rdv=0, recu="2026-10-26T09:40:00+00:00"),       # arrivée sans heure
    ]
    h = forme_hall(docs, {"dr x": "Bureau 3"}, maintenant)
    x = next(m for m in h["medecins"] if m["medecin"] == "Dr X")
    assert x["porte"] == "Bureau 3" and x["prochain_min"] == 10
    assert [(r["heure"], r["passe"]) for r in x["rdv"]] == [("09:30", True), ("10:10", False), ("10:30", False)]
    assert h["prochain"] == {"medecin": "Dr X", "porte": "Bureau 3", "libelle": "10:10"}
    assert "patient" not in str(h).lower()                                            # aucun nom de patient dans le flux


def test_hall_flux_portes_et_type_evenement():
    c, base = _app()
    from datetime import datetime, timezone, timedelta
    auj = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    _run(base.planning_appointments.insert_many([
        {"id": "p1", "tenant_id": "cli-1", "medecin": "Dr X", "patient": "SECRET", "is_rdv": 1, "start_at": (auj + timedelta(days=0)).isoformat(),
         "received_at": auj.isoformat(), "numero_ordre": 7}]))
    adm = {"x-admin": "1"}
    d = c.post("/api/tv/appairage", json={"secret": SECRET}).json()
    c.post("/api/admin/tv/appairer", headers=adm, json={"code": d["code"], "nom": "Hall", "client_id": "cli-1", "modules": {"hall": True}})
    assert c.put("/api/admin/tv/portes", headers=adm, json={"portes": [{"medecin": "dr x", "porte": "Bureau 3"}, {"medecin": "", "porte": "x"}]}).json()["portes"] == [{"medecin": "dr x", "porte": "Bureau 3"}]
    f = c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()
    assert "messages" not in f and "support" not in f
    assert f["hall"]["medecins"][0]["porte"] == "Bureau 3" and "SECRET" not in str(f)
    assert "Dr X" in c.get("/api/admin/tv/portes", headers=adm).json()["medecins_connus"]


def test_conversation_choisie_sur_la_tele():
    """Lot 301 — `fil` limite le fil en direct à une conversation (clic sur la télé) ; la liste des conversations reste complète."""
    c, base = _app()
    _run(base.whatsapp_messages.insert_many([
        {"id": "a1", "client_id": "cli-1", "contact_id": "kA", "contact_name": "Alice", "direction": "inbound", "body": "Salut", "created_at": "2026-10-26T11:00:00+00:00"},
        {"id": "b1", "client_id": "cli-1", "contact_id": "kB", "contact_name": "Bob", "direction": "inbound", "body": "Coucou", "created_at": "2026-10-26T11:01:00+00:00"},
        {"id": "a2", "client_id": "cli-1", "contact_id": "kA", "contact_name": "Alice", "direction": "outbound", "body": "Re", "created_at": "2026-10-26T11:02:00+00:00"}]))
    d = c.post("/api/tv/appairage", json={"secret": SECRET}).json()
    c.post("/api/admin/tv/appairer", headers={"x-admin": "1"}, json={"code": d["code"], "nom": "Hall", "client_id": "cli-1"})
    f = c.get("/api/tv/flux", params={"fil": "kA"}, headers={"x-tv-secret": SECRET}).json()
    assert [m["id"] for m in f["messages"]] == ["a1", "a2"] and f["fil_choisi"] == "kA"
    assert {x["cle"] for x in f["fils"]} >= {"kA", "kB"}
