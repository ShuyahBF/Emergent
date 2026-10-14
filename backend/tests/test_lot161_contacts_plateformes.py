"""Lot 161 — contacts des plateformes récupérés par SAWALI dans des groupes « Plateforme X » : signature, adresse,
création / mise à jour / adoption, groupe, consentement jamais coché d'office. MongoDB simulé, aucun appel réseau.
Lancer : cd backend && python -m pytest tests/test_lot161_contacts_plateformes.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.contacts_plateformes as cp  # noqa: E402


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_signature_comme_l_export_e_kol():
    attendu = hmac.new(b"cle", b"1700000000.GET /api/sawali/contacts?limite=500&page=1", hashlib.sha256).hexdigest()
    assert cp.signer("cle", "1700000000", "/api/sawali/contacts", "limite=500&page=1") == attendu
    assert cp.variable_cle("adlyn") == "CONTACTS_HMAC_ADLYN" and cp.variable_cle("e-kol") == "CONTACTS_HMAC_E_KOL"


def test_adresses_acceptees():
    assert cp.adresse_acceptee("https://api.zandgo.shop")
    for mauvaise in ("http://api.zandgo.shop", "https://localhost", "https://127.0.0.1", "https://192.168.1.5", "ftp://x.y", "n'importe quoi"):
        assert not cp.adresse_acceptee(mauvaise), mauvaise


def test_normalisation_des_contacts():
    c = cp.normaliser_contact({"id": 7, "nom": "  Awa   Ouedraogo ", "telephone": "+226 70 11 22 33", "role": "client"}, "ZandGo")
    assert c["telephone"] == "22670112233" and c["nom"] == "Awa Ouedraogo" and c["societe"] == "ZandGo · client" and c["accepte"] is False
    assert cp.normaliser_contact({"id": 1, "telephone": "123"}, "ZandGo") is None                    # numéro trop court
    assert cp.normaliser_contact({"telephone": "22670112233"}, "ZandGo") is None                      # sans identifiant
    assert cp.normaliser_contact({"id": 2, "telephone": "70112233", "accepte_whatsapp": "oui"}, "Z")["accepte"] is False   # seul « vrai » compte


@pytest.fixture()
def db(monkeypatch):
    base = mongomock_motor.AsyncMongoMockClient()["sawali_test"]
    monkeypatch.setenv("CONTACTS_HMAC_ZANDGO", "cle-partagee")
    lancer(base.users.insert_one({"id": "admin1", "full_name": "Propriétaire", "email": "p@x.bf"}))
    lancer(cp._enregistrer_plateforme(base, "zandgo", {"nom": "ZandGo", "url": "https://api.zandgo.shop", "actif": True}, proprietaire_id="admin1"))
    return base


def faux_serveur(pages):
    """Plateforme simulée : renvoie les pages données et vérifie la signature de chaque requête."""
    appels = []

    async def appeler(url, entetes):
        chemin, _, requete = url.partition("https://api.zandgo.shop")[2].partition("?")
        assert entetes["X-Signature"] == cp.signer("cle-partagee", entetes["X-Timestamp"], chemin, requete)
        appels.append(url)
        n = int(requete.split("page=")[1])
        return {"page": n, "pages": len(pages), "contacts": pages[n - 1]}
    appeler.appels = appels
    return appeler


def test_synchro_cree_adopte_met_a_jour_et_range_dans_le_groupe(db):
    # Un contact déjà dans l'annuaire avec le même numéro (autre source) : adopté sans modification
    lancer(db.directory_contacts.insert_one({"id": "exist", "client_id": "admin1", "name": "Awa (ancienne fiche)", "whatsapp": "+226 70 11 22 33"}))
    pages = [[{"id": "1", "nom": "Awa Ouedraogo", "telephone": "22670112233"}, {"id": "2", "nom": "Issa", "telephone": "22675000001"}],
             [{"id": "3", "nom": "Marie", "telephone": "22676000002", "accepte_whatsapp": True, "accepte_le": "2026-10-01T10:00:00+00:00"},
              {"id": "4", "nom": "Sans numéro", "telephone": ""}]]
    srv = faux_serveur(pages)
    b = lancer(cp.synchroniser(db, "zandgo", appeler=srv))
    assert b["ok"] and b["recus"] == 4 and b["crees"] == 2 and b["adoptes"] == 1 and b["sans_numero"] == 1 and len(srv.appels) == 2
    groupe = lancer(db.contact_groups.find_one({"source_plateforme": "zandgo"}))
    assert groupe["name"] == "Plateforme ZandGo" and groupe["client_id"] == "admin1" and len(groupe["contact_ids"]) == 3
    assert "exist" in groupe["contact_ids"]
    adopte = lancer(db.directory_contacts.find_one({"id": "exist"}))
    assert adopte["name"] == "Awa (ancienne fiche)" and not adopte.get("source_plateforme")          # inchangé
    # Consentement : seulement celui que la plateforme affirme ; jamais pour les autres
    marie = lancer(db.directory_contacts.find_one({"name": "Marie"}))
    issa = lancer(db.directory_contacts.find_one({"name": "Issa"}))
    assert marie["accepte_whatsapp"] is True and "ZandGo" in marie["accepte_whatsapp_moyen"] and not issa.get("accepte_whatsapp")
    # Deuxième passage : rien n'est dupliqué ; un contact disparu de la plateforme sort du groupe mais reste dans l'annuaire
    pages2 = [[{"id": "1", "nom": "Awa O.", "telephone": "22670112233"}, {"id": "3", "nom": "Marie", "telephone": "22676000002"}]]
    b2 = lancer(cp.synchroniser(db, "zandgo", appeler=faux_serveur(pages2)))
    assert b2["crees"] == 0 and b2["retires_du_groupe"] == 1
    assert lancer(db.directory_contacts.count_documents({"source_plateforme": "zandgo"})) == 2   # Issa et Marie ; Awa est l'ancienne fiche adoptée
    groupe = lancer(db.contact_groups.find_one({"source_plateforme": "zandgo"}))
    assert len(groupe["contact_ids"]) == 2 and lancer(db.directory_contacts.find_one({"name": "Issa"})) is not None


def test_un_retrait_deja_enregistre_n_est_jamais_ecrase(db):
    lancer(db.directory_contacts.insert_one({"id": "k1", "client_id": "admin1", "name": "Marie", "whatsapp": "22676000002", "source_plateforme": "zandgo",
                                             "id_externe": "3", "accepte_whatsapp": False, "accepte_whatsapp_le": "2026-09-01T00:00:00+00:00"}))
    pages = [[{"id": "3", "nom": "Marie", "telephone": "22676000002", "accepte_whatsapp": True}]]
    lancer(cp.synchroniser(db, "zandgo", appeler=faux_serveur(pages)))
    assert lancer(db.directory_contacts.find_one({"id": "k1"}))["accepte_whatsapp"] is False         # le STOP reste valable


def test_erreurs_lisibles_et_jamais_bloquantes(db, monkeypatch):
    async def refuse(url, entetes):
        raise RuntimeError("La plateforme refuse la signature : la clé doit être la même des deux côtés.")
    b = lancer(cp.synchroniser(db, "zandgo", appeler=refuse))
    assert b["ok"] is False and "signature" in b["erreur"]
    assert lancer(db.settings.find_one({"_id": "contacts_plateformes"}))["plateformes"]["zandgo"]["resultat"]["ok"] is False
    monkeypatch.delenv("CONTACTS_HMAC_ZANDGO")
    assert "CONTACTS_HMAC_ZANDGO" in lancer(cp.synchroniser(db, "zandgo", appeler=refuse))["erreur"]
    assert "Adresse" in lancer(cp.synchroniser(db, "ster"))["erreur"]                               # adresse non renseignée


def test_routes_des_parametres(db, monkeypatch):
    """GET / PUT / POST synchroniser, avec une petite application et un administrateur simulé."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    app, api = FastAPI(), APIRouter(prefix="/api")
    cp.setup_contacts_plateformes_routes(db=db, api=api, get_current_admin=lambda: {"id": "admin1"})
    app.include_router(api)
    c = TestClient(app)
    etat = c.get("/api/admin/contacts-plateformes").json()
    ids = [p["id"] for p in etat["plateformes"]]
    assert ids[:2] == ["zandgo", "ekol"] and "adlyn" in ids and etat["chemin"] == "/api/sawali/contacts"
    zg = next(p for p in etat["plateformes"] if p["id"] == "zandgo")
    assert zg["actif"] and zg["cle_saisie"] and zg["variable"] == "CONTACTS_HMAC_ZANDGO"
    # Adresse refusée (http, locale), activation sans adresse refusée, plateforme inconnue refusée
    assert c.put("/api/admin/contacts-plateformes/adlyn", json={"url": "http://adlyn.exemple.com", "actif": True}).status_code == 422
    assert c.put("/api/admin/contacts-plateformes/adlyn", json={"url": "", "actif": True}).status_code == 422
    assert c.put("/api/admin/contacts-plateformes/Mauvais Id", json={"url": ""}).status_code == 422
    ok = c.put("/api/admin/contacts-plateformes/adlyn", json={"url": "https://api.adlyn.exemple.com/", "actif": True})
    assert ok.status_code == 200 and next(p for p in ok.json()["plateformes"] if p["id"] == "adlyn")["url"] == "https://api.adlyn.exemple.com"
    assert c.post("/api/admin/contacts-plateformes/inconnue/synchroniser").status_code == 404
    # Synchro sans clé saisie pour adLyn : échec lisible, jamais d'erreur 500
    r = c.post("/api/admin/contacts-plateformes/adlyn/synchroniser").json()
    assert r["bilan"]["ok"] is False and "CONTACTS_HMAC_ADLYN" in r["bilan"]["erreur"]
