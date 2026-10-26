"""Lot 321 — suivi du RDV par le patient : identification téléphone + 2 initiales, fenêtre de 3 h, rien d'autre que son propre RDV."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes import suivi_rdv as sr
from routes.suivi_rdv import (base_autorisee, chiffres8, dans_la_fenetre, initiales_possibles, normaliser_initiales,
                              personnes_devant, setup_suivi_rdv_routes)


def _run(c):
    return asyncio.get_event_loop().run_until_complete(c)


def test_initiales_dans_les_deux_sens_et_sans_accent():
    assert initiales_possibles("OUEDRAOGO Alphonse : 25614545 : R-1") == {"OA", "AO"}
    assert initiales_possibles("Éléonore  Zongo") == {"EZ", "ZE"}
    assert initiales_possibles("KABORE") == {"KA"} and initiales_possibles("") == set()
    assert normaliser_initiales("o.a") == "OA" and normaliser_initiales("O") == "" and normaliser_initiales("OAB") == ""


def test_telephone_8_derniers_chiffres():
    assert chiffres8("+226 70 00 11 22") == "70001122" and chiffres8("12") == ""


def test_fenetre_de_3h_avant_et_3h_apres():
    d = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)
    assert dans_la_fenetre(d, d - timedelta(hours=3)) and dans_la_fenetre(d, d + timedelta(hours=3))
    assert not dans_la_fenetre(d, d - timedelta(hours=3, minutes=1)) and not dans_la_fenetre(d, d + timedelta(hours=3, minutes=1))


def test_personnes_devant_avec_et_sans_curseur():
    now = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)
    h = lambda m: (now + timedelta(minutes=m)).isoformat()
    a, b, c = {"id": "a", "start_at": h(10)}, {"id": "b", "start_at": h(30)}, {"id": "c", "start_at": h(50)}
    assert personnes_devant(c, [a, b, c], now) == 2                       # sans curseur : heures pas encore atteintes
    assert personnes_devant(c, [{**a, "etat_consult": "fait"}, b, c], now) == 1   # curseur utilisé : « fait » ne compte plus
    assert personnes_devant(a, [a, b, c], now) == 0


def test_qr_seulement_pour_nos_sites():
    assert base_autorisee("https://app.sawalismartsystems.com") == "https://app.sawalismartsystems.com"
    assert base_autorisee("https://evil.example.com") is None and base_autorisee("javascript:alert(1)") is None
    assert sr.png_qr("https://app.sawalismartsystems.com/suivi-rdv")[:4] == b"\x89PNG"


def _app():
    base = AsyncMongoMockClient()["test_suivi_321"]

    async def admin(request: Request):
        if request.headers.get("x-admin") != "1":
            raise HTTPException(status_code=403, detail="admin requis")
        return {"email": "a@test"}
    api = APIRouter(prefix="/api")
    setup_suivi_rdv_routes(db=base, api=api, get_current_admin=admin)
    app = FastAPI()
    app.include_router(api)
    sr._echecs.clear(); sr._requetes.clear()
    return TestClient(app), base


def _rdv(base, ident, patient, tel, minutes, medecin="DR X", **k):
    d = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    _run(base.planning_appointments.insert_one({"id": ident, "medecin": medecin, "is_rdv": 1, "patient": patient, "patient_phone": tel,
                                                "start_at": d.isoformat(), **k}))


def test_service_eteint_par_defaut_puis_active():
    c, base = _app()
    assert c.get("/api/suivi-rdv/info").json() == {"actif": False}
    assert c.post("/api/suivi-rdv/etat", json={"telephone": "70001122", "initiales": "OA"}).status_code == 403
    assert c.put("/api/admin/suivi-rdv", json={"actif": True}).status_code == 403              # réservé à l'administrateur
    assert c.put("/api/admin/suivi-rdv", headers={"x-admin": "1"}, json={"actif": True}).json() == {"actif": True}
    assert c.get("/api/suivi-rdv/info").json() == {"actif": True}


def test_patient_voit_seulement_son_rdv():
    c, base = _app()
    c.put("/api/admin/suivi-rdv", headers={"x-admin": "1"}, json={"actif": True})
    _run(base.settings.update_one({"_id": "global"}, {"$set": {"tv_portes": [{"medecin": "DR X", "porte": "Salle 2"}]}}, upsert=True))
    _rdv(base, "p1", "DIALLO Awa : 70009999", "70009999", 20)
    _rdv(base, "p2", "OUEDRAOGO Alphonse : 70001122", "+226 70 00 11 22", 60)
    r = c.post("/api/suivi-rdv/etat", json={"telephone": "70 00 11 22", "initiales": "oa"})
    assert r.status_code == 200
    d = r.json()
    assert d["medecin"] == "DR X" and d["porte"] == "Salle 2" and d["devant"] == 1 and "1 personne avant vous" in d["message"]
    assert "DIALLO" not in str(d) and "70009999" not in str(d)                       # rien sur les autres patients
    # mauvaises initiales / mauvais téléphone : même réponse uniforme
    for corps in ({"telephone": "70001122", "initiales": "ZZ"}, {"telephone": "70001123", "initiales": "OA"}, {"telephone": "", "initiales": "OA"}):
        x = c.post("/api/suivi-rdv/etat", json=corps)
        assert x.status_code == 404 and "Aucun rendez-vous" in x.json()["detail"]


def test_hors_fenetre_et_annule_sont_refuses_sans_explication():
    c, base = _app()
    c.put("/api/admin/suivi-rdv", headers={"x-admin": "1"}, json={"actif": True})
    _rdv(base, "p1", "OUEDRAOGO Alphonse", "70001122", 4 * 60)                       # dans 4 h : trop tôt
    _rdv(base, "p2", "KONE Aminata", "70003344", 30, status="cancelled")            # annulé
    assert c.post("/api/suivi-rdv/etat", json={"telephone": "70001122", "initiales": "OA"}).status_code == 404
    assert c.post("/api/suivi-rdv/etat", json={"telephone": "70003344", "initiales": "KA"}).status_code == 404


def test_etat_en_consultation_et_blocage_apres_8_echecs():
    c, base = _app()
    c.put("/api/admin/suivi-rdv", headers={"x-admin": "1"}, json={"actif": True})
    _rdv(base, "p1", "OUEDRAOGO Alphonse", "70001122", -10, etat_consult="en_cours")
    assert c.post("/api/suivi-rdv/etat", json={"telephone": "70001122", "initiales": "OA"}).json()["etat"] == "en_cours"
    for _ in range(8):
        assert c.post("/api/suivi-rdv/etat", json={"telephone": "70001122", "initiales": "ZZ"}).status_code == 404
    assert c.post("/api/suivi-rdv/etat", json={"telephone": "70001122", "initiales": "OA"}).status_code == 429    # même le bon essai : blocage


def test_qr_png_refuse_un_site_inconnu():
    c, _ = _app()
    assert c.get("/api/suivi-rdv/qr.png", params={"base": "https://app.sawalismartsystems.com"}).status_code == 200
    assert c.get("/api/suivi-rdv/qr.png", params={"base": "https://evil.example.com"}).status_code == 400
