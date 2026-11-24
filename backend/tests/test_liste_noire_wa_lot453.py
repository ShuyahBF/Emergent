"""Lot 453 — liste noire WhatsApp (toutes lignes) et notifications désactivables par ticket / intervention.
Aucun accès réseau : base en mémoire, client HTTP simulé."""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot453")
from pathlib import Path

import mongomock_motor
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

import liste_noire_wa as ln
import tickets_clients as tc


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def db():
    ln.vider_cache()
    b = mongomock_motor.AsyncMongoMockClient()["test_lot453"]
    run(b.settings.insert_one({"_id": "global", "wa_access_token": "jeton", "wa_phone_number_id": "100"}))
    return b


def test_cle_numero_huit_derniers_chiffres():
    assert ln.cle_numero("+226 70 12 34 56") == "70123456" == ln.cle_numero("0022670123456")
    assert ln.cle_numero("1234") == ""                      # trop court : jamais de blocage au hasard


def test_bloquer_est_idempotent_et_debloquer(db):
    run(ln.bloquer(db, "+226 70 12 34 56", nom="AWA", par="admin"))
    run(ln.bloquer(db, "22670123456", nom="AWA BADINI", par="admin"))          # même numéro écrit autrement : une seule fiche
    assert len(run(ln.lister(db))) == 1 and run(ln.lister(db))[0]["nom"] == "AWA BADINI"
    assert run(ln.est_bloque(db, "70123456")) and not run(ln.est_bloque(db, "+22670000000"))
    assert run(ln.debloquer(db, "70123456")) and not run(ln.est_bloque(db, "+226 70 12 34 56"))
    assert run(ln.debloquer(db, "70123456")) is False
    with pytest.raises(ValueError):
        run(ln.bloquer(db, "123"))


def test_une_seule_fiche_de_settings_aucune_nouvelle_collection(db):
    run(ln.bloquer(db, "+22670123456"))
    assert run(db.list_collection_names()) == ["settings"]


class _FauxHttp:
    appels = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None, **k):
        _FauxHttp.appels.append(url)

        class R:
            status_code = 200
            text = "ok"

            def json(self_inner):
                return {"messages": [{"id": "wamid.1"}]}
        return R()


def test_aucun_envoi_vers_un_contact_bloque_sur_les_quatre_expediteurs(db, monkeypatch):
    from routes import whatsapp_helpers as wh
    monkeypatch.setattr(wh.httpx, "AsyncClient", _FauxHttp)
    aides = wh.attach_whatsapp_helpers(db=db, wa_graph_version="v22.0", wa_media_max_bytes=1000, upload_dir=Path("/tmp"),
                                       uuid_fn=lambda: "u", now_fn=lambda: "2026-11-24T10:00:00")
    _FauxHttp.appels.clear()
    assert run(aides["_wa_send_text"]("+22670123456", "Bonjour"))["ok"]                 # avant blocage : l'envoi part
    assert len(_FauxHttp.appels) == 1
    run(ln.bloquer(db, "+226 70 12 34 56"))
    _FauxHttp.appels.clear()
    for r in (run(aides["_wa_send_text"]("+22670123456", "Bonjour")),
              run(aides["_wa_send_template"]("+22670123456", "modele", "fr", None)),
              run(aides["_wa_send_interactive_button"]("+22670123456", "Texte", "id", "Oui")),
              run(aides["_wa_send_media"]("+22670123456", "image", public_url="https://x/y.png"))):
        assert r["ok"] is False and r["bloque"] is True
    assert _FauxHttp.appels == []                                                           # rien n'est parti vers Meta
    assert run(aides["_wa_send_text"]("+22670999999", "Bonjour"))["ok"]                     # un autre numéro n'est pas touché


def _app(db):
    from routes.liste_noire_wa import setup_liste_noire_wa_routes
    app = FastAPI()
    api = APIRouter(prefix="/api")

    async def utilisateur(request=None):
        from fastapi import Request
        return {"role": "admin", "full_name": "Admin"}

    async def simple():
        return {"role": "client", "full_name": "Client"}
    dependance = {"fn": utilisateur}

    async def courant():
        return await dependance["fn"]()
    setup_liste_noire_wa_routes(db=db, api=api, get_current_user=courant)
    app.include_router(api)
    return app, dependance, simple


def test_routes_admin_seulement_et_liste_visible_dans_les_parametres(db):
    app, dep, simple = _app(db)
    c = TestClient(app)
    assert c.post("/api/me/wa/liste-noire", json={"telephone": "+226 70 12 34 56", "nom": "AWA"}).json()["bloque"] is True
    assert c.get("/api/me/wa/liste-noire/etat", params={"telephone": "70123456"}).json() == {"bloque": True}      # un booléen, jamais la liste
    liste = c.get("/api/admin/wa/liste-noire").json()
    assert liste["total"] == 1 and liste["entrees"][0]["cle"] == "70123456"
    assert c.post("/api/me/wa/liste-noire", json={"telephone": "123"}).status_code == 422
    dep["fn"] = simple                                                                          # un client ordinaire : refusé partout
    assert c.post("/api/me/wa/liste-noire", json={"telephone": "+22670999999"}).status_code == 403
    assert c.get("/api/admin/wa/liste-noire").status_code == 403
    assert c.delete("/api/admin/wa/liste-noire/70123456").status_code == 403
    dep["fn"] = lambda: None


def test_debloquer_depuis_les_parametres(db):
    app, dep, simple = _app(db)
    c = TestClient(app)
    c.post("/api/me/wa/liste-noire", json={"telephone": "+226 70 12 34 56"})
    assert c.delete("/api/admin/wa/liste-noire/70123456").json() == {"ok": True}
    assert c.delete("/api/admin/wa/liste-noire/70123456").status_code == 404
    assert c.get("/api/me/wa/liste-noire/etat", params={"telephone": "70123456"}).json() == {"bloque": False}


def test_notifications_du_ticket_contact_et_responsable():
    ticket = {"contact_id": "c1"}
    assert tc.notification_autorisee(ticket, "c1", {}) and tc.notification_autorisee(ticket, "c2", {"is_decision_maker": True})     # défaut : oui
    t2 = {"contact_id": "c1", "notifier_contact": False}
    assert not tc.notification_autorisee(t2, "c1", {}) and tc.notification_autorisee(t2, "c2", {"is_decision_maker": True})
    t3 = {"contact_id": "c1", "notifier_responsable": False}
    assert tc.notification_autorisee(t3, "c1", {}) and not tc.notification_autorisee(t3, "c2", {"is_decision_maker": True})
    assert tc.notification_autorisee(t3, "c3", {})                   # un autre contact rattaché suit « contact »


def test_destinataires_du_ticket_respectent_les_interrupteurs(monkeypatch, db):
    from datetime import datetime, timezone
    monkeypatch.setattr(tc, "db", db)
    run(db.directory_contacts.insert_many([
        {"id": "c1", "name": "AWA", "whatsapp": "+22670000001", "client_id": "k1"},
        {"id": "c2", "name": "DG", "whatsapp": "+22670000002", "client_id": "k1", "is_decision_maker": True}]))
    quand = datetime(2026, 11, 24, 10, tzinfo=timezone.utc)
    base = {"id": "t1", "contact_id": "c1", "contact_ids": ["c1", "c2"]}
    assert {d["contact_id"] for d in run(tc.destinataires(base, quand))} == {"c1", "c2"}
    assert {d["contact_id"] for d in run(tc.destinataires({**base, "notifier_contact": False}, quand))} == {"c2"}
    assert {d["contact_id"] for d in run(tc.destinataires({**base, "notifier_responsable": False}, quand))} == {"c1"}
    assert run(tc.destinataires({**base, "notifier_contact": False, "notifier_responsable": False}, quand)) == []


def test_un_contact_bloque_n_est_plus_relaye(db, monkeypatch):
    """Ni relais au propriétaire (alerte + appel), ni relais aux plateformes de la Transmission universelle."""
    from routes import appel_proprietaire as ap
    from routes import liluvine_relais as lr
    run(db.settings.update_one({"_id": "global"}, {"$set": {"appel_proprietaire_actif": True}}, upsert=True))
    run(ln.bloquer(db, "+22670123456"))
    oui, raison = run(ap.decision_relais(db, {}, chiffres="22670123456", mtype="text", texte="Bonjour", contact=None))
    assert oui is False                                                      # refusé (par la liste noire ou une règle antérieure : jamais relayé)
    r = run(lr.traiter_message_entrant(db, de="+22670123456", type_message="text", texte="Bonjour"))
    assert r == {"traite": True, "liste_noire": True}


def test_le_superviseur_peut_bloquer_lister_et_debloquer(db):
    app, dep, simple = _app(db)
    c = TestClient(app)

    async def superviseur():
        return {"role": "superviseur", "full_name": "Superviseur"}

    async def suivi():
        return {"role": "client", "tracked_role": "Superviseur", "full_name": "Suivi"}
    dep["fn"] = superviseur
    assert c.post("/api/me/wa/liste-noire", json={"telephone": "+226 70 12 34 56", "nom": "AWA"}).status_code == 200
    assert c.get("/api/me/wa/liste-noire/etat", params={"telephone": "70123456"}).json() == {"bloque": True}
    assert c.get("/api/admin/wa/liste-noire").json()["total"] == 1               # la liste (Paramètres) lui est ouverte
    assert c.delete("/api/admin/wa/liste-noire/70123456").status_code == 200     # et il peut débloquer
    dep["fn"] = suivi
    assert c.post("/api/me/wa/liste-noire", json={"telephone": "+22670999999"}).status_code == 200
    dep["fn"] = simple                                                           # un client ordinaire reste refusé
    assert c.post("/api/me/wa/liste-noire", json={"telephone": "+22670888888"}).status_code == 403
