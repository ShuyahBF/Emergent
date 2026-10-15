"""Lot 168 — l'administration choisit une SOCIÉTÉ, voit ses groupes de contacts (ex. « Prospects publicités Facebook »),
envoie / programme la demande d'accord (ou le carrousel) ; le superviseur de la société en voit ensuite les statuts.
Envoi WhatsApp et Meta simulés, MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_lot168_societes_carrousel.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
mongomock_motor = pytest.importorskip("mongomock_motor")

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.accord_modele_meta as amm  # noqa: E402
import routes.carrousel_whatsapp as cw  # noqa: E402
from test_carrousel_whatsapp import BASE, USERS, h  # noqa: E402

URL = "/api/admin/whatsapp/carrousel"


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "secret-de-test")

    async def faux_statut(**kw):
        return {"statut": "APPROVED", "motif": None, "erreur": None}
    monkeypatch.setattr(amm, "lire_statut", faux_statut)

    db = mongomock_motor.AsyncMongoMockClient()["sawali_l168"]
    envois = []

    async def get_user(request: Request):
        u = USERS.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    async def get_admin(request: Request):
        u = await get_user(request)
        if u["role"] != "admin":
            raise HTTPException(status_code=403)
        return u

    async def envoyer(to, nom, langue, comps, tenant_id=None):
        envois.append({"to": to, "modele": nom, "composants": comps})
        return {"ok": True, "status": 200, "message_id": f"wamid.{len(envois)}", "error": None}

    async def creds(tenant_id):
        return {"access_token": "t", "phone_number_id": "1", "waba_id": "W", "source": "global", "tenant_id": None}

    async def active(user, cle):
        return True

    async def visibles(user):
        return [user.get("parent_client_id") or user["id"]]

    api = APIRouter(prefix="/api")
    moteur = cw.attach_carrousel_whatsapp_routes(
        api=api, db=db, get_current_user=get_user, get_current_admin=get_admin, fonction_active=active,
        visible_client_ids=visibles, wa_send_template=envoyer, resolve_wa_credentials=creds, base_publique=lambda: BASE)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.moteur = moteur
    p = client.portal
    p.call(db.users.insert_many, [dict(u) for u in USERS.values()])
    # La société « cli_a » possède 2 prospects (utilisateurs suivis) rangés dans un groupe que l'admin ne voit pas
    p.call(db.tracked_users.insert_many, [
        {"id": "t1", "client_id": "cli_a", "name": "Prospect Un", "whatsapp_number": "+226 76 55 55 01"},
        {"id": "t2", "client_id": "cli_a", "name": "Prospect Deux", "whatsapp_number": "+226 76 55 55 02"}])
    p.call(db.contact_groups.insert_one, {"id": "g1", "client_id": "cli_a", "name": "Prospects publicités Facebook",
                                           "contact_ids": ["t1", "t2"]})
    p.call(db.settings.replace_one, {"_id": "global"}, {"_id": "global", "wa_accord_modele": "sawali_accord_lien",
                                                         "wa_accord_modele_langue": "fr"}, True)
    yield client, db, envois
    client.__exit__(None, None, None)


def test_liste_des_societes_et_de_leurs_groupes(env):
    client, _, _ = env
    soc = client.get(URL + "/societes", headers=h("admin")).json()["societes"]
    a = next(s for s in soc if s["id"] == "cli_a")
    assert a["suivis"] == 2 and a["groupes"] == 1 and a["nom"] == "Pharmacie A"
    assert client.get(URL + "/societes", headers=h("cli_a")).status_code == 403          # réservé à l'administration
    ann = client.get(URL + "/destinataires?societe=cli_a", headers=h("admin")).json()
    assert {c["id"] for c in ann["contacts"]} >= {"t1", "t2"}
    assert any(g["nom"] == "Prospects publicités Facebook" for g in ann["groupes"])
    # Sans société : le groupe de la société reste invisible (comportement d'avant)
    assert not any(g["nom"] == "Prospects publicités Facebook"
                   for g in client.get(URL + "/destinataires", headers=h("admin")).json()["groupes"])


def test_demande_d_accord_immediate_a_une_societe(env):
    client, db, envois = env
    r = client.post(URL + "/demande-accord-modele", headers=h("admin"), json={"ids": ["t1", "t2"], "societe_id": "cli_a"})
    assert r.status_code == 200, r.text
    assert r.json()["envoyees"] == 2 and len(envois) == 2
    # Sans la société, ces personnes sont introuvables : rien ne part
    r = client.post(URL + "/demande-accord-modele", headers=h("admin"), json={"ids": ["t1"]})
    assert r.json()["envoyees"] == 0


def test_programmation_visible_du_superviseur_de_la_societe(env):
    client, db, envois = env
    quand = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M")
    r = client.post(URL + "/demande-accord-modele", headers=h("admin"),
                    json={"ids": ["t1", "t2"], "societe_id": "cli_a", "programme_le": quand})
    assert r.status_code == 200 and r.json()["statut"] == "PROGRAMMEE" and envois == []
    mine = client.get("/api/me/whatsapp/carrousel/demandes-accord", headers=h("cli_a")).json()["demandes"]
    assert len(mine) == 1 and mine[0]["statut"] == "PROGRAMMEE" and mine[0]["nb"] == 2
    assert "ids" not in mine[0]
    # Une autre société ne voit rien
    assert client.get("/api/me/whatsapp/carrousel/demandes-accord", headers=h("cli_b")).json()["demandes"] == []
    # À l'heure dite, l'envoi part et le statut passe à TERMINEE chez le superviseur
    doc = client.portal.call(db.settings.find_one, {"_id": "accord_programmations"})
    for it in doc["items"]:
        it["programme_le"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    client.portal.call(db.settings.replace_one, {"_id": "accord_programmations"}, doc)
    assert client.portal.call(client.moteur["accords_echus"]) == 1 and len(envois) == 2
    fin = client.get("/api/me/whatsapp/carrousel/demandes-accord", headers=h("cli_a")).json()["demandes"][0]
    assert fin["statut"] == "TERMINEE" and fin["resultat"]["envoyees"] == 2
    # La date de la demande apparaît sur la ligne du contact
    ligne = next(c for c in client.get("/api/me/whatsapp/carrousel/destinataires", headers=h("cli_a")).json()["contacts"]
                 if c["id"] == "t1")
    assert ligne["demande_le"]


def test_carrousel_admin_pour_une_societe_visible_non_annulable_du_superviseur(env):
    client, db, _ = env
    # Un envoi de carrousel de l'administration est enregistré avec sa société
    client.portal.call(db.carrousel_campagnes.insert_one, {
        "id": "camp1", "perimetre": "admin", "tenant_id": None, "societe_id": "cli_a", "statut": "EN_COURS",
        "cree_le": "2026-10-15T08:30:00+00:00", "cartes": [], "destinataires": [], "id_public": "pub1",
        "compte": {"total": 2, "envoyes": 0, "echecs": 0}})
    camps = client.get("/api/me/whatsapp/carrousel/campagnes", headers=h("cli_a")).json()["campagnes"]
    assert [c["id"] for c in camps] == ["camp1"] and camps[0]["annulable"] is False
    assert client.get("/api/me/whatsapp/carrousel/campagnes", headers=h("cli_b")).json()["campagnes"] == []
    assert client.get("/api/me/whatsapp/carrousel/campagnes/camp1", headers=h("cli_a")).status_code == 200
    assert client.get("/api/me/whatsapp/carrousel/campagnes/camp1", headers=h("cli_b")).status_code == 404


def test_sawali_smart_systems_dans_la_liste_des_societes(env):
    """Lot 168.1 — le compte de l'administration (SAWALI SMART SYSTEMS) figure parmi les sociétés, avec ses groupes."""
    client, db, envois = env
    p = client.portal
    p.call(db.tracked_users.insert_many, [
        {"id": "f1", "client_id": "admin", "name": "Prospect FB", "whatsapp_number": "+226 76 66 66 01"}])
    p.call(db.contact_groups.insert_one, {"id": "gf", "client_id": "admin", "name": "Prospects publicités Facebook",
                                           "contact_ids": ["f1"]})
    soc = client.get(URL + "/societes", headers=h("admin")).json()["societes"]
    s = next(x for x in soc if x["nom"] == "SAWALI SMART SYSTEMS")
    assert s["id"] == "@plateforme" and s["groupes"] == 1 and s["suivis"] == 1
    ann = client.get(URL + "/destinataires?societe=@plateforme", headers=h("admin")).json()
    assert any(g["nom"] == "Prospects publicités Facebook" for g in ann["groupes"])
    r = client.post(URL + "/demande-accord-modele", headers=h("admin"), json={"ids": ["f1"], "societe_id": "@plateforme"})
    assert r.json()["envoyees"] == 1 and len(envois) == 1


def test_plateforme_regroupe_les_comptes_de_la_meme_societe_et_anciens_identifiants(env):
    """Lot 168.2 — données éparpillées : sous un collègue de la même société et sous un ancien client_id."""
    client, db, _ = env
    p = client.portal
    p.call(db.users.update_one, {"id": "admin"}, {"$set": {"company": "SAWALI-2S"}})
    p.call(db.users.insert_many, [
        {"id": "ines", "role": "client", "email": "ines@sawalismartsystems.com", "company": "sawali-2s", "client_id": "ines"},
        {"id": "jf", "role": "pharmacien", "email": "jf@x.bf", "company": "SAWALI-2S", "client_id": "ancien_scope"}])
    p.call(db.directory_contacts.insert_many, [
        {"id": f"k{i}", "client_id": "ines", "name": f"Contact {i}", "whatsapp": f"+226 76 70 00 0{i}"} for i in range(5)])
    p.call(db.contact_groups.insert_many, [
        {"id": f"gg{i}", "client_id": ("ancien_scope" if i % 2 else "ines"), "name": f"Groupe {i}", "contact_ids": ["k0"]}
        for i in range(10)])
    s = next(x for x in client.get(URL + "/societes", headers=h("admin")).json()["societes"] if x["id"] == "@plateforme")
    assert s["groupes"] == 10 and s["contacts"] == 5 and s["nom"] == "SAWALI SMART SYSTEMS"
    ann = client.get(URL + "/destinataires?societe=@plateforme", headers=h("admin")).json()
    assert len(ann["groupes"]) == 10 and len([c for c in ann["contacts"] if c["id"].startswith("k")]) == 5


def test_plateforme_societe_ecrite_autrement_et_contacts_crees_par_un_compte(env):
    """Lot 168.3 — « SAWALI-2S » et « SAWALI SMART SYSTEMS » sont la même société ; contacts / groupes retrouvés
    aussi par `owner_id` (comme la page « Groupes de contacts »)."""
    client, db, _ = env
    p = client.portal
    p.call(db.users.update_one, {"id": "admin"}, {"$set": {"company": "SAWALI SMART SYSTEMS"}})
    p.call(db.users.insert_one, {"id": "ines", "role": "client", "email": "ines@sawalismartsystems.com",
                                 "company": "SAWALI-2S", "client_id": "ines"})
    p.call(db.directory_contacts.insert_many, [
        {"id": "o1", "client_id": "inconnu", "owner_id": "ines", "name": "Via owner", "whatsapp": "+226 76 71 00 01"}])
    p.call(db.contact_groups.insert_many, [
        {"id": f"og{i}", "client_id": "autre", "owner_id": "ines", "name": f"Groupe {i}", "contact_ids": ["o1"]} for i in range(10)])
    s = next(x for x in client.get(URL + "/societes", headers=h("admin")).json()["societes"] if x["id"] == "@plateforme")
    assert s["groupes"] == 10 and s["contacts"] == 1
    ann = client.get(URL + "/destinataires?societe=@plateforme", headers=h("admin")).json()
    assert len(ann["groupes"]) == 10 and any(c["id"] == "o1" for c in ann["contacts"])
