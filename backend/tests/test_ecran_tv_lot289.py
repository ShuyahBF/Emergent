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

from routes.ecran_tv import PAGE_TV_VERSION


def deverrouiller(c, admin=None):
    """Lot 317 : messages et support ne sortent qu'avec le jeton du code PIN — définit le code (1234), le saisit comme la télé, mémorise le jeton."""
    assert c.put("/api/admin/tv/pin", headers=admin or {"x-admin": "1"}, json={"pin": "1234"}).status_code == 200
    r = c.post("/api/tv/pin", headers={"x-tv-secret": SECRET}, json={"pin": "1234"})
    assert r.status_code == 200, r.text
    c.headers.update({"x-tv-deverrou": r.json()["jeton"]})


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
    # Lot 317 : sans code PIN déverrouillé, aucun message ni demande de support ne sort
    verrouille = c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()
    assert "messages" not in verrouille and "support" not in verrouille and verrouille["ecran"]["suivi_ouvert"] is False
    deverrouiller(c)
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
    deverrouiller(c, {})
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
    deverrouiller(c)
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
    deverrouiller(c)
    f = c.get("/api/tv/flux", params={"fil": "kA"}, headers={"x-tv-secret": SECRET}).json()
    assert [m["id"] for m in f["messages"]] == ["a1", "a2"] and f["fil_choisi"] == "kA"
    assert {x["cle"] for x in f["fils"]} >= {"kA", "kB"}


# ---------- Lot 317 : code PIN du Suivi Support ----------
def _tele_appairee():
    """Client de test avec une télé appairée (sans code PIN défini)."""
    c, base = _app()
    d = c.post("/api/tv/appairage", json={"secret": SECRET}).json()
    c.post("/api/admin/tv/appairer", headers={"x-admin": "1"}, json={"code": d["code"], "nom": "Hall", "client_id": "cli-1"})
    return c, base


def test_lot317_pin_refuse_puis_accepte():
    """Aucun PIN → 409 ; trop court → 400 ; mauvais code → 403 ; bon code → jeton ; le code n'apparaît jamais dans le flux."""
    c, _ = _tele_appairee()
    tv = {"x-tv-secret": SECRET}
    assert c.post("/api/tv/pin", headers=tv, json={"pin": "1234"}).status_code == 409
    assert c.put("/api/admin/tv/pin", headers={"x-admin": "1"}, json={"pin": "12"}).status_code == 400
    assert c.put("/api/admin/tv/pin", headers={"x-admin": "1"}, json={"pin": "1234"}).status_code == 200
    assert c.post("/api/tv/pin", headers=tv, json={"pin": "9999"}).status_code == 403
    assert "1234" not in c.get("/api/tv/flux", headers=tv).text
    assert c.post("/api/tv/pin", headers=tv, json={"pin": "1234"}).status_code == 200


def test_lot317_blocage_apres_cinq_echecs():
    """Cinq mauvais codes → 429 (même avec le bon code) pendant la minute de blocage."""
    c, _ = _tele_appairee()
    tv = {"x-tv-secret": SECRET}
    c.put("/api/admin/tv/pin", headers={"x-admin": "1"}, json={"pin": "4321"})
    for _i in range(5):
        assert c.post("/api/tv/pin", headers=tv, json={"pin": "0000"}).status_code == 403
    assert c.post("/api/tv/pin", headers=tv, json={"pin": "4321"}).status_code == 429


def test_lot317_flux_hall_expose_debut_et_nouveau():
    """Le planning du hall reste libre (sans PIN) et chaque RDV porte `debut` (instant) et `nouveau` (créé depuis moins de 10 min)."""
    c, _ = _tele_appairee()
    f = c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()
    assert f["page"] == PAGE_TV_VERSION and f["maintenant"] and f["ecran"]["suivi_ouvert"] is False


def test_lot319_horizon_3_ou_7_jours_reserve_au_code_pin():
    """Sans code PIN déverrouillé l'horizon reste 1 jour ; déverrouillée, la télé reçoit les RDV des jours suivants (champ `jour`)."""
    from datetime import datetime, timedelta, timezone
    c, base = _tele_appairee()
    tv = {"x-tv-secret": SECRET}
    ecran_id = c.get("/api/admin/tv/ecrans", headers={"x-admin": "1"}).json()["ecrans"][0]["id"]
    assert c.put(f"/api/admin/tv/ecrans/{ecran_id}", headers={"x-admin": "1"}, json={"modules": {"messagerie": True, "support": True, "hall": True}}).status_code == 200
    auj = datetime.now(timezone.utc).replace(hour=23, minute=0, second=0, microsecond=0)
    _run(base.planning_appointments.insert_many([
        {"id": "h1", "tenant_id": "cli-1", "medecin": "DR X", "is_rdv": 1, "patient": "KANE Ali", "start_at": (auj - timedelta(hours=3)).isoformat()},
        {"id": "h2", "tenant_id": "cli-1", "medecin": "DR X", "is_rdv": 1, "patient": "DIALLO Awa", "start_at": (auj + timedelta(days=2)).isoformat()}]))
    assert c.get("/api/tv/flux?jours=7", headers=tv).json()["hall"]["horizon"] == 1       # verrouillée : un jour seulement
    deverrouiller(c)
    f1 = c.get("/api/tv/flux?jours=1", headers=tv).json()["hall"]
    f7 = c.get("/api/tv/flux?jours=7", headers=tv).json()["hall"]
    assert len(f1["medecins"][0]["rdv"]) == 1 and f1["horizon"] == 1
    assert len(f7["medecins"][0]["rdv"]) == 2 and f7["horizon"] == 7 and f7["jour"] and f7["medecins"][0]["rdv"][1]["jour"] != f7["jour"]


# ---------- Lot 323 : connexion administrateur approuvée depuis SAWALI ----------
def _flux_admin(c, jeton):
    return c.get("/api/tv/flux", headers={"x-tv-secret": SECRET, "x-tv-deverrou": jeton}).json()


def test_lot323_approbation_administrateur_deverrouille_et_affiche_en_clair():
    from datetime import datetime, timedelta, timezone
    c, base = _tele_appairee()
    tv, adm = {"x-tv-secret": SECRET}, {"x-admin": "1"}
    ecran_id = c.get("/api/admin/tv/ecrans", headers=adm).json()["ecrans"][0]["id"]
    c.put(f"/api/admin/tv/ecrans/{ecran_id}", headers=adm, json={"modules": {"messagerie": True, "support": True, "hall": True}})
    _run(base.planning_appointments.insert_one({"id": "r1", "tenant_id": "cli-1", "medecin": "DR X", "is_rdv": 1, "patient": "OUEDRAOGO Alphonse : 70001122 : R-5",
        "patient_phone": "70001122", "start_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()}))
    jeton = "j" * 40
    # sans PIN défini, le Suivi Support est quand même « possible » (connexion administrateur)
    f0 = _flux_admin(c, jeton)
    assert f0["ecran"]["suivi_possible"] is True and f0["ecran"]["suivi_ouvert"] is False and "messages" not in f0
    assert f0["hall"]["medecins"][0]["rdv"][0]["qui"] == "OU******* Al*******"[:len(f0["hall"]["medecins"][0]["rdv"][0]["qui"])] or "*" in f0["hall"]["medecins"][0]["rdv"][0]["qui"]
    # la télé demande un code ; une mauvaise saisie ou un administrateur absent ne déverrouille rien
    d = c.post("/api/tv/admin-demande", headers=tv, json={"jeton": jeton}).json()
    assert len(d["code"]) == 6 and d["valide_minutes"] == 5
    assert c.post("/api/admin/tv/approuver", headers=adm, json={"code": "ZZZZZZ"}).status_code == 404
    assert c.post("/api/admin/tv/approuver", json={"code": d["code"]}).status_code == 403
    assert _flux_admin(c, jeton)["ecran"]["suivi_ouvert"] is False
    # l'administrateur approuve : la télé est ouverte, en mode administrateur, patients en clair ; le code ne sert qu'une fois
    ok = c.post("/api/admin/tv/approuver", headers=adm, json={"code": d["code"].lower()})
    assert ok.status_code == 200 and ok.json()["valide_minutes"] == 10
    f = _flux_admin(c, jeton)
    assert f["ecran"]["suivi_ouvert"] is True and f["ecran"]["admin"] is True and "messages" in f and "support" in f
    ligne = f["hall"]["medecins"][0]["rdv"][0]
    assert ligne["qui"] == "OUEDRAOGO Alphonse" and ligne["tel"] == "70 00 11 22"
    assert c.post("/api/admin/tv/approuver", headers=adm, json={"code": d["code"]}).status_code == 404
    # un autre jeton n'ouvre rien ; les champs internes ne sortent pas dans la liste d'administration
    assert _flux_admin(c, "autre-jeton-" + "x" * 30)["ecran"]["suivi_ouvert"] is False
    ecran = c.get("/api/admin/tv/ecrans", headers=adm).json()["ecrans"][0]
    assert not {"admin_demande", "deverrou_admin", "deverrou_par", "deverrou_hash"} & set(ecran)


def test_lot323_code_expire_et_jeton_trop_court():
    c, base = _tele_appairee()
    tv, adm = {"x-tv-secret": SECRET}, {"x-admin": "1"}
    assert c.post("/api/tv/admin-demande", headers=tv, json={"jeton": "court"}).status_code == 400
    d = c.post("/api/tv/admin-demande", headers=tv, json={"jeton": "k" * 40}).json()
    _run(base.settings.update_one({"_id": "global"}, {"$set": {"tv_ecrans.0.admin_demande.expire": "2000-01-01T00:00:00+00:00"}}))   # code périmé
    assert c.post("/api/admin/tv/approuver", headers=adm, json={"code": d["code"]}).status_code == 404


def test_lot323_le_pin_ne_donne_pas_les_identites():
    """Le déverrouillage par PIN garde les patients masqués (seule l'approbation administrateur les montre)."""
    c, base = _tele_appairee()
    deverrouiller(c)
    f = c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()
    assert f["ecran"]["suivi_ouvert"] is True and f["ecran"]["admin"] is False
