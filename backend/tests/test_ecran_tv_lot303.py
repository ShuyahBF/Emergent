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


def test_planning_du_jour_anonymise_pour_le_hall():
    """Lot 305 : « GU**. R. Pa**** | 7*****42 | R-2026302201 » — le hall est public, rien de lisible au-delà des 2 premiers caractères."""
    from routes.ecran_tv import anonymiser_nom, forme_hall, masquer_tel_hall
    assert anonymiser_nom("GUYO. R. Paulin : 70001122") == "GU**. R. Pa****"
    assert anonymiser_nom("DABRE SAFOURA : 70369266") == "DA*** SA*****"          # le téléphone collé au nom est retiré
    assert anonymiser_nom("") == "—"
    assert masquer_tel_hall("70001142") == "7*****42" and masquer_tel_hall("+226 70 00 11 42") == "7*****42" and masquer_tel_hall("") == ""
    maintenant = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)
    docs = [{"medecin": "DR X", "patient": "KANE Fatimata : 70001122", "patient_phone": "70001122", "is_rdv": 1, "start_at": "2026-10-26T10:20:00+00:00",
             "numero_recu": "R-2026302201", "type_evenement": "RCU"},
            {"medecin": "DR X", "patient": "OUEDRAOGO Ali", "patient_phone": "70003344", "is_rdv": 1, "start_at": "2026-10-26T09:30:00+00:00"}]
    m = forme_hall(docs, {}, maintenant)["medecins"][0]
    assert [(r["heure"], r["qui"], r["tel"], r["recu"]) for r in m["rdv"]] == [("09:30", "OU******* Al*", "7*****44", ""), ("10:20", "KA** Fa******", "7*****22", "R-2026302201")]
    assert m["prochain_min"] == 20                                                  # le type RCU est ignoré : le RDV reste « à venir »
    texte = str(m)
    assert "KANE" not in texte and "Fatimata" not in texte and "70001122" not in texte and "70003344" not in texte


def test_recu_saisi_apres_le_telephone_dans_le_champ_patient():
    """Lot 306 : « OUOBA Alphone :  25614545 : R-202660230 » → patient « OUOBA Alphone : 25614545 », téléphone, reçu."""
    from routes.planning import separer_patient_tel_recu
    assert separer_patient_tel_recu("OUOBA Alphone :  25614545 : R-202660230") == ("OUOBA Alphone : 25614545", "25614545", "R-202660230")
    assert separer_patient_tel_recu("OUOBA JF 77000155") == ("OUOBA JF : 77000155", "77000155", "")            # sans reçu : inchangé
    assert separer_patient_tel_recu("SOMDA") == ("SOMDA", None, "")
    from routes.ecran_tv import forme_hall, recu_du_patient
    assert recu_du_patient("OUOBA Alphone : 25614545 : R-202660230") == "R-202660230" and recu_du_patient("OUOBA : 25614545") == ""
    maintenant = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)
    m = forme_hall([{"medecin": "DR X", "patient": "OUOBA Alphone : 25614545 : R-202660230", "patient_phone": "25614545", "is_rdv": 1,
                    "start_at": "2026-10-26T10:20:00+00:00"}], {}, maintenant)["medecins"][0]
    assert (m["rdv"][0]["qui"], m["rdv"][0]["tel"], m["rdv"][0]["recu"]) == ("OU*** Al*****", "2*****45", "R-202660230")


def test_compatibilite_ancienne_page_et_version_de_page():
    """Lot 307 : une télé qui garde une ancienne page en cache lit encore `prochains`/`etat` (pas d'erreur), et le flux annonce la version de la page."""
    from routes.ecran_tv import PAGE_TV_VERSION, forme_hall
    maintenant = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)
    docs = [{"medecin": "DR X", "patient": "KANE Sali", "is_rdv": 1, "start_at": "2026-10-26T10:20:00+00:00"},
            {"medecin": "DR X", "patient": "SOMDA", "is_rdv": 1, "start_at": "2026-10-26T09:00:00+00:00"}]
    m = forme_hall(docs, {}, maintenant)["medecins"][0]
    assert m["prochains"][0]["libelle"] == "10:20" and [r["etat"] for r in m["rdv"]] == ["termine", "attente"]
    html = open("../frontend/public/tv-ecran.html", encoding="utf-8").read()
    assert f'VERSION_PAGE = "{PAGE_TV_VERSION}"' in html            # la page et le serveur annoncent la même version


def test_patient_nom_puis_telephone_puis_recu_lot308():
    """Lot 308 : nom et prénoms, puis le téléphone (après le 1er « : » ou premier numéro qui suit), puis le reçu."""
    from routes.planning import separer_patient_tel_recu as f
    assert f("OUOBA Alphone :  25614545 : R-202660230") == ("OUOBA Alphone : 25614545", "25614545", "R-202660230")
    assert f("OUOBA Alphone 25614545 R-202660230") == ("OUOBA Alphone : 25614545", "25614545", "R-202660230")      # sans « : »
    assert f("KANE Sali Marie : +226 70 00 11 22 : R-1") == ("KANE Sali Marie : +226 70 00 11 22", "+226 70 00 11 22", "R-1")
    assert f("DABRE SAFOURA ; 70369266 ; R-20263") == ("DABRE SAFOURA : 70369266", "70369266", "R-20263")
    assert f("OUOBA JF 77000155") == ("OUOBA JF : 77000155", "77000155", "") and f("SOMDA") == ("SOMDA", None, "")


def test_avancer_reculer_dans_une_liste_lot309():
    """Lot 309 : le curseur « en consultation » avance et recule dans une liste (avec RDV ou sans RDV)."""
    from routes.planning_avancement import calculer_avancement as c
    assert c([None, None, None], "avant") == {0: "en_cours"}                                  # premier appel : le 1er patient
    assert c(["en_cours", None, None], "avant") == {0: "fait", 1: "en_cours"}                  # on passe au suivant
    assert c(["fait", "en_cours", None], "arriere") == {1: None, 0: "en_cours"}                # on rappelle le précédent
    assert c([None, None], "arriere") == {}                                                    # rien avant le début
    assert c(["fait", "en_cours"], "avant") == {1: "fait"}                                     # fin de liste : plus personne en cours
    assert c(["fait", "fait"], "arriere") == {1: "en_cours"}                                   # retour depuis la fin de liste
    assert c([], "avant") == {}


def _app_planning():
    db = AsyncMongoMockClient()["test_avancement_309"]
    auj = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    jour = auj.strftime("%y%m%d")
    _run(db.users.insert_many([{"id": "med-1", "email": "m1@x"}, {"id": "med-2", "email": "m2@x"}]))
    _run(db.planning_appointments.insert_many([
        {"id": "r1", "tenant_id": "t", "medecin_id": "med-1", "is_rdv": 1, "start_at": (auj + timedelta(hours=1)).isoformat(), "patient": "A"},
        {"id": "r2", "tenant_id": "t", "medecin_id": "med-1", "is_rdv": 1, "start_at": (auj + timedelta(hours=2)).isoformat(), "patient": "B"},
        {"id": "w1", "tenant_id": "t", "medecin_id": "med-1", "is_rdv": 0, "walk_in_list": f"{jour}:med-1", "numero_ordre": 1, "patient": "C"},
        {"id": "w2", "tenant_id": "t", "medecin_id": "med-1", "is_rdv": 0, "walk_in_list": f"{jour}:med-1", "numero_ordre": 2, "patient": "D"},
        {"id": "x1", "tenant_id": "t", "medecin_id": "med-2", "is_rdv": 1, "start_at": (auj + timedelta(hours=1)).isoformat(), "patient": "AUTRE MEDECIN"},
    ]))
    from routes.planning_avancement import attach_planning_avancement_routes

    async def utilisateur(request: Request):
        return {"id": request.headers.get("x-id", "med-1"), "email": "m1@x", "role": "client", "tracked_role": "Secrétaire médicale" if request.headers.get("x-role") == "secretaire" else "Médecin"}

    async def visibles(user):
        return ["t"]

    api = APIRouter(prefix="/api")
    attach_planning_avancement_routes(api=api, db=db, get_current_user=utilisateur, is_admin_like=lambda u: False,
                                      is_super_admin=lambda u: False, resolve_visible_client_ids=visibles)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), db, auj.strftime("%Y-%m-%d")


def test_endpoint_avancer_ses_deux_listes_seulement():
    c, db, jour = _app_planning()
    # liste avec RDV : on avance deux fois, puis on recule
    r = c.post("/api/me/planning/avancer", json={"liste": "rdv", "sens": "avant", "date": jour}).json()
    assert [(e["id"], e["etat_consult"]) for e in r["etats"]] == [("r1", "en_cours"), ("r2", None)]
    c.post("/api/me/planning/avancer", json={"liste": "rdv", "sens": "avant", "date": jour})
    assert _run(db.planning_appointments.find_one({"id": "r1"}))["etat_consult"] == "fait"
    assert _run(db.planning_appointments.find_one({"id": "r2"}))["etat_consult"] == "en_cours"
    c.post("/api/me/planning/avancer", json={"liste": "rdv", "sens": "arriere", "date": jour})
    assert _run(db.planning_appointments.find_one({"id": "r1"}))["etat_consult"] == "en_cours"
    assert "etat_consult" not in _run(db.planning_appointments.find_one({"id": "r2"}))
    # la liste sans RDV est indépendante ; l'autre médecin n'est jamais touché
    c.post("/api/me/planning/avancer", json={"liste": "sans_rdv", "sens": "avant", "date": jour})
    assert _run(db.planning_appointments.find_one({"id": "w1"}))["etat_consult"] == "en_cours"
    assert "etat_consult" not in _run(db.planning_appointments.find_one({"id": "x1"}))
    # droits : une secrétaire médicale ne pilote pas les listes du médecin
    assert c.post("/api/me/planning/avancer", headers={"x-role": "secretaire"}, json={"liste": "rdv", "sens": "avant", "date": jour}).status_code == 403
    assert c.post("/api/me/planning/avancer", json={"liste": "autre", "sens": "avant", "date": jour}).status_code == 400


def test_hall_deux_listes_et_curseur_lot309():
    from routes.ecran_tv import forme_hall
    maintenant = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)
    docs = [{"medecin": "DR X", "patient": "A Un", "is_rdv": 1, "start_at": "2026-10-26T09:00:00+00:00", "etat_consult": "fait"},
            {"medecin": "DR X", "patient": "B Deux", "is_rdv": 1, "start_at": "2026-10-26T10:30:00+00:00", "etat_consult": "en_cours"},
            {"medecin": "DR X", "patient": "C Trois", "is_rdv": 1, "start_at": "2026-10-26T11:00:00+00:00"},
            {"medecin": "DR X", "patient": "D Quatre", "is_rdv": 0, "numero_ordre": 2, "received_at": "2026-10-26T08:00:00+00:00"},
            {"medecin": "DR X", "patient": "E Cinq", "is_rdv": 0, "numero_ordre": 1, "received_at": "2026-10-26T07:00:00+00:00", "etat_consult": "en_cours"}]
    m = forme_hall(docs, {}, maintenant)["medecins"][0]
    assert [(r["heure"], r["etat"]) for r in m["rdv"]] == [("09:00", "fait"), ("10:30", "en_cours"), ("11:00", "attente")]
    assert [(r["ordre"], r["etat"]) for r in m["sans_rdv"]] == [(1, "en_cours"), (2, "attente")]
    assert m["prochain_min"] == 60                                           # le patient « en cours » n'est plus « le prochain »
    assert [r["passe"] for r in m["rdv"]] == [True, False, False]


def test_hall_perimetre_par_code_clinique_lot309():
    """Les RDV de médecins rangés sous un autre compte mais de la même clinique (même code) s'affichent aussi ; une autre clinique non."""
    db = AsyncMongoMockClient()["test_tv_309"]
    _run(db.users.insert_one({"id": "cli-1", "company": "Clinique A"}))
    auj = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    _run(db.planning_appointments.insert_many([
        {"id": "p1", "tenant_id": "cli-1", "code_clinique": "CMCO", "medecin": "DR UN", "patient": "A", "is_rdv": 1, "start_at": auj.isoformat()},
        {"id": "p2", "tenant_id": "autre-compte", "code_clinique": "CMCO", "medecin": "DR DEUX", "patient": "B", "is_rdv": 1, "start_at": auj.isoformat()},
        {"id": "p3", "tenant_id": "autre-client", "code_clinique": "AUTRE", "medecin": "DR TROIS", "patient": "C", "is_rdv": 1, "start_at": auj.isoformat()},
    ]))

    async def admin(request: Request):
        return {"email": "admin@test"}

    api = APIRouter(prefix="/api")
    setup_ecran_tv_routes(db=db, api=api, get_current_admin=admin)
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app)
    d = c.post("/api/tv/appairage", json={"secret": SECRET}).json()
    c.post("/api/admin/tv/appairer", json={"code": d["code"], "nom": "Hall", "client_id": "cli-1", "modules": {"hall": True}})
    f = c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()
    assert sorted(m["medecin"] for m in f["hall"]["medecins"]) == ["DR DEUX", "DR UN"]
    assert f["ecran"]["taille_heure"] == "grande"                                              # valeur par défaut
    ecran_id = c.get("/api/admin/tv/ecrans").json()["ecrans"][0]["id"]
    assert c.put(f"/api/admin/tv/ecrans/{ecran_id}", json={"taille_heure": "geante"}).json()["taille_heure"] == "geante"
    assert c.put(f"/api/admin/tv/ecrans/{ecran_id}", json={"taille_heure": "enorme"}).status_code == 400
    assert c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()["ecran"]["taille_heure"] == "geante"
