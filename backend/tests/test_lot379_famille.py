"""Lot 379 — « Ma famille » : comptes, invitation à usage unique, vérification des deux côtés, messagerie chiffrée (serveur sans clé), anti-devinette.
Sans réseau ni vraie base (mongomock_motor). Lancer : cd backend && python -m pytest tests/test_lot379_famille.py -q
"""
from __future__ import annotations

import base64
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes.famille import setup_famille_routes  # noqa: E402
from services import famille as fam  # noqa: E402

CLE = base64.b64encode(b"x" * 91).decode()          # forme plausible d'une clé EC X.509 (le serveur ne la déchiffre jamais)


def _client():
    db = mongomock_motor.AsyncMongoMockClient()[f"lot379_{time.time_ns()}"]
    app = FastAPI(); routeur = APIRouter(prefix="/api")
    setup_famille_routes(app=routeur, db=db)
    app.include_router(routeur)
    return TestClient(app), db


def _inscrire(c, nom):
    r = c.post("/api/famille/inscription", json={"nom": nom, "cle_publique": CLE})
    assert r.status_code == 200, r.text
    j = r.json()
    return {"X-Famille-Compte": j["compte_id"], "X-Famille-Jeton": j["jeton"]}, j["compte_id"]


def _lier(c):
    """Deux comptes liés (non vérifiés) : retourne (entetes_A, id_A, entetes_B, id_B, lien_id)."""
    a, ida = _inscrire(c, "BADINI Awa"); b, idb = _inscrire(c, "BADINI Issa")
    code = c.post("/api/famille/invitations", headers=a).json()["code"]
    r = c.post("/api/famille/invitations/accepter", json={"code": code.lower()}, headers=b)      # casse et tiret tolérés
    assert r.status_code == 200, r.text
    return a, ida, b, idb, r.json()["lien_id"]


def test_inscription_validation_et_jeton_non_stocke_en_clair():
    c, db = _client()
    assert c.post("/api/famille/inscription", json={"nom": "A", "cle_publique": CLE}).status_code == 422
    assert c.post("/api/famille/inscription", json={"nom": "Awa", "cle_publique": "pas du base64!"}).status_code == 422
    entetes, cid = _inscrire(c, "BADINI Awa")
    import asyncio
    doc = asyncio.get_event_loop().run_until_complete(db.famille_comptes.find_one({"_id": cid}))
    assert entetes["X-Famille-Jeton"] not in str(doc) and doc["jeton_hash"] == fam.empreinte_jeton(entetes["X-Famille-Jeton"])


def test_acces_refuse_sans_bon_jeton():
    c, _ = _client()
    entetes, cid = _inscrire(c, "BADINI Awa")
    assert c.get("/api/famille/liens").status_code == 401
    assert c.get("/api/famille/liens", headers={"X-Famille-Compte": cid, "X-Famille-Jeton": "faux"}).status_code == 401
    assert c.get("/api/famille/liens", headers=entetes).status_code == 200


def test_invitation_usage_unique_et_pas_soi_meme():
    c, _ = _client()
    a, _ida, b, _idb, _ = _lier(c)
    code = c.post("/api/famille/invitations", headers=a).json()["code"]
    assert c.post("/api/famille/invitations/accepter", json={"code": code}, headers=a).status_code == 422          # sa propre invitation
    d, _ = _inscrire(c, "BADINI Moussa")
    assert c.post("/api/famille/invitations/accepter", json={"code": code}, headers=d).status_code == 200
    e, _ = _inscrire(c, "BADINI Zara")
    assert c.post("/api/famille/invitations/accepter", json={"code": code}, headers=e).status_code == 404         # déjà utilisé
    # déjà liés : refusé
    code2 = c.post("/api/famille/invitations", headers=a).json()["code"]
    assert c.post("/api/famille/invitations/accepter", json={"code": code2}, headers=b).status_code == 422


def test_anti_devinette_apres_dix_codes_faux():
    c, _ = _client()
    a, _ = _inscrire(c, "BADINI Awa"); b, _ = _inscrire(c, "BADINI Issa")
    c.post("/api/famille/invitations", headers=a)
    for _ in range(10):
        assert c.post("/api/famille/invitations/accepter", json={"code": "AAAA-BBBB"}, headers=b).status_code == 404
    assert c.post("/api/famille/invitations/accepter", json={"code": "AAAA-BBBB"}, headers=b).status_code == 429


def test_lien_verifie_seulement_quand_les_deux_ont_confirme_et_cles_visibles():
    c, _ = _client()
    a, ida, b, idb, lien = _lier(c)
    va = c.get("/api/famille/liens", headers=a).json()["liens"][0]
    assert va["statut"] == "a_verifier" and va["correspondant"]["compte_id"] == idb and va["correspondant"]["cle_publique"] == CLE
    r = c.post(f"/api/famille/liens/{lien}/verifier", headers=a).json()
    assert r["statut"] == "a_verifier" and r["verifie_par_moi"] and not r["verifie_par_lui"]
    r = c.post(f"/api/famille/liens/{lien}/verifier", headers=b).json()
    assert r["statut"] == "verifie" and r["verifie_par_moi"] and r["verifie_par_lui"]
    assert c.get("/api/famille/liens", headers=a).json()["liens"][0]["verifie_par_lui"] is True


def test_messagerie_reservee_aux_liens_verifies_et_curseur():
    c, db = _client()
    a, ida, b, idb, lien = _lier(c)
    msg = {"nonce": base64.b64encode(b"n" * 12).decode(), "chiffre": base64.b64encode(b"texte chiffre").decode()}
    assert c.post(f"/api/famille/liens/{lien}/messages", json=msg, headers=a).status_code == 403              # pas encore vérifié
    c.post(f"/api/famille/liens/{lien}/verifier", headers=a); c.post(f"/api/famille/liens/{lien}/verifier", headers=b)
    s1 = c.post(f"/api/famille/liens/{lien}/messages", json=msg, headers=a).json()["seq"]
    s2 = c.post(f"/api/famille/liens/{lien}/messages", json=msg, headers=b).json()["seq"]
    assert s2 > s1
    tous = c.get(f"/api/famille/liens/{lien}/messages", headers=b).json()["messages"]
    assert [m["de"] for m in tous] == [ida, idb] and tous[0]["chiffre"] == msg["chiffre"]
    apres = c.get(f"/api/famille/liens/{lien}/messages?apres={s1}", headers=a).json()["messages"]
    assert [m["seq"] for m in apres] == [s2]
    for mauvais in [{"nonce": "", "chiffre": ""}, {"nonce": "%%%", "chiffre": msg["chiffre"]}, {"nonce": msg["nonce"], "chiffre": "A" * 9000}]:
        assert c.post(f"/api/famille/liens/{lien}/messages", json=mauvais, headers=a).status_code == 422


def test_un_tiers_ne_voit_ni_le_lien_ni_les_messages_et_la_rupture_efface_tout():
    c, db = _client()
    a, ida, b, idb, lien = _lier(c)
    c.post(f"/api/famille/liens/{lien}/verifier", headers=a); c.post(f"/api/famille/liens/{lien}/verifier", headers=b)
    msg = {"nonce": base64.b64encode(b"n" * 12).decode(), "chiffre": base64.b64encode(b"secret").decode()}
    c.post(f"/api/famille/liens/{lien}/messages", json=msg, headers=a)
    tiers, _ = _inscrire(c, "Intrus")
    assert c.get(f"/api/famille/liens/{lien}/messages", headers=tiers).status_code == 404
    assert c.post(f"/api/famille/liens/{lien}/verifier", headers=tiers).status_code == 404
    assert c.delete(f"/api/famille/liens/{lien}", headers=tiers).status_code == 404
    assert c.delete(f"/api/famille/liens/{lien}", headers=b).status_code == 200
    assert c.get("/api/famille/liens", headers=a).json()["liens"] == []
    import asyncio
    assert asyncio.get_event_loop().run_until_complete(db.famille_messages.count_documents({})) == 0
