"""Lot 86.2 — modèles WhatsApp Meta du lien des requêtes : définitions, envoi par modèle, repli sur message libre.
Lancer : cd backend && python -m pytest tests/test_lot86_2_modeles_meta_requetes.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import requetes_clients as rc  # noqa: E402


def test_definitions_et_parametres():
    lien, suivi = rc.definitions_modeles("https://ex.com/")
    assert lien["name"] == "sawali_lien_requetes" and lien["category"] == "UTILITY" and lien["language"] == "fr"
    bouton = lien["components"][-1]["buttons"][0]
    assert bouton["type"] == "URL" and bouton["url"] == "https://ex.com/requete/{{1}}"
    # Variable jamais en tout début ni en toute fin du corps (refusé par Meta)
    for d in (lien, suivi):
        corps = d["components"][0]["text"]
        assert not corps.startswith("{{") and not corps.endswith("}}")
    comp = rc.composants_modele("ligne 1\nligne 2", "JETON")
    assert comp[0]["parameters"][0]["text"] == "ligne 1 ligne 2"
    assert comp[1]["sub_type"] == "url" and comp[1]["parameters"][0]["text"] == "JETON"


class _Rep:
    def __init__(self, code, data):
        self.status_code, self._d = code, data

    def json(self):
        return self._d


class _FauxMeta:
    """Remplace httpx.AsyncClient : enregistre les appels à Meta."""
    appels = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        _FauxMeta.appels.append(("GET", params["name"]))
        return _Rep(200, {"data": [{"name": params["name"], "status": "APPROVED", "language": "fr"}]})

    async def post(self, url, json=None, headers=None):
        _FauxMeta.appels.append(("POST", json["name"]))
        if json["name"] == "sawali_suivi_requetes":
            return _Rep(400, {"error": {"message": "Content in this language already exists"}})
        return _Rep(200, {"id": "1", "status": "PENDING"})


def test_envoi_par_modele_et_repli():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot862"]
    boucle = asyncio.new_event_loop()
    boucle.run_until_complete(db.users.insert_one({"id": "t1", "company": "AL BARKA", "whatsapp_number": "22670000000", "role": "client"}))
    boucle.run_until_complete(db.settings.insert_one({"_id": "global", "wa_access_token": "x", "wa_business_account_id": "w"}))
    utilisateur = {"v": {"id": "adm", "role": "admin", "full_name": "SAWALI"}}
    envois = []
    modele_ok = {"v": True}

    async def faux_modele(numero, nom, langue, composants, tenant_id=None):
        envois.append(("modele", numero, nom, composants, tenant_id))
        return {"ok": modele_ok["v"], "error": None if modele_ok["v"] else "Template not approved"}

    async def faux_texte(numero, texte, reply_to_message_id=None, tenant_id=None):
        envois.append(("texte", numero, texte, tenant_id))
        return {"ok": True}
    app, api = FastAPI(), APIRouter(prefix="/api")
    rc.setup_requetes_clients_routes(db=db, api=api, get_current_user=lambda: utilisateur["v"], wa_send_text=faux_texte,
                                     wa_send_template=faux_modele, upload_dir="/tmp", base_url="https://ex.com",
                                     meta_http=_FauxMeta)
    app.include_router(api)
    c = TestClient(app)

    # Modèles : création (le 2e existe déjà = sans effet) puis état
    res = c.post("/api/admin/requetes-modeles-meta").json()["resultats"]
    assert [r["ok"] for r in res] == [True, True] and res[1]["etat"] == "EXISTANT"
    etat = c.get("/api/admin/requetes-modeles-meta").json()["modeles"]
    assert {m["nom"]: m["etat"] for m in etat} == {"sawali_lien_requetes": "APPROVED", "sawali_suivi_requetes": "APPROVED"}

    # Envoi du lien : par le modèle, depuis le numéro de SAWALI (aucun tenant_id), jeton dans le bouton
    r = c.post("/api/admin/requetes-liens", json={"tenant_id": "t1"}).json()
    jeton = r["url"].rsplit("/", 1)[1]
    assert r["envoye"]["mode"] == "modele"
    _, numero, nom, comps, tenant = envois[-1]
    assert nom == "sawali_lien_requetes" and tenant is None and comps[1]["parameters"][0]["text"] == jeton
    assert comps[0]["parameters"][0]["text"] == "AL BARKA"

    # Modèle non approuvé : repli sur le message libre, toujours sans tenant_id
    modele_ok["v"] = False
    r = c.post("/api/admin/requetes-liens", json={"tenant_id": "t1"}).json()
    assert r["envoye"]["mode"] == "texte" and envois[-1][0] == "texte" and envois[-1][3] is None
