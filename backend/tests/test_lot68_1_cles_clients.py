"""Lot 68.1 — Clés clients Loois (une clé par client) et structure de référence téléchargée par Loois.
Vérifie : seule l'empreinte est stockée, la clé n'est montrée qu'une fois, révocation / régénération / réactivation,
site différent de la clé → 403, clé commune refusée pour la synchro par défaut (acceptée avec le réglage de
transition), clé commune toujours acceptée pour le support et la présence, présence « vérifié · <client> »,
route /structure et empreinte annoncée par /config. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot68_1_cles_clients.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.loois_cles_clients as cles  # noqa: E402
import routes.loois_synchro as ls  # noqa: E402
import routes.versions_deployees as vd  # noqa: E402

UTILISATEURS = {"admin": {"id": "admin", "role": "admin", "full_name": "Admin SAWALI"},
                "phl": {"id": "phl", "role": "pharmacien", "client_code": "PHL"}}
COMMUNE = {"X-Cle-Loois": "cle-commune"}


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def env(monkeypatch):
    """Clé commune définie, pas de poivre ; état « clés actives » remis à zéro après le test."""
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-commune")
    monkeypatch.delenv("LOOIS_CLES_PEPPER", raising=False)
    yield
    cles.ETAT["clients_actifs"] = False


def application(db):
    """Application FastAPI minimale : clés clients + synchro + présence ; utilisateur choisi par l'en-tête X-User."""
    async def utilisateur(request: Request):
        u = UTILISATEURS.get(request.headers.get("X-User", "admin"))
        if not u:
            raise HTTPException(status_code=401)
        return u

    api = APIRouter(prefix="/api")
    cles.setup_loois_cles_clients_routes(db=db, api=api, get_current_user=utilisateur)
    ls.setup_loois_synchro_routes(db=db, api=api, get_current_user=utilisateur)
    vd.setup_versions_deployees_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def creer(c, code="Lycée Privé X", applications=("eKol",), libelle="Lycée Privé X"):
    """Crée une clé client par la page d'administration ; renvoie la réponse JSON."""
    r = c.post("/api/admin/loois-cles-clients", json={"code": code, "libelle": libelle, "applications": list(applications)})
    assert r.status_code == 200, r.text
    return r.json()


def morceau(site="LYCEE-PRIVE-X", table="Paiements"):
    """Morceau minimal (une ligne) tel que Loois l'envoie."""
    return {"application": "eKol", "site": site, "machine": "PC-1", "table": table, "lot": "lot1", "sequence": 0,
            "complet": False, "fin": True, "cle": ["IDPaiements"], "lignes_source": 1,
            "upserts": [{"cle": "1", "ligne": {"IDPaiements": 1, "Montant": "5000"}}], "suppressions": []}


# ---------------------------------------------------------------------------
# Logique pure
# ---------------------------------------------------------------------------
def test_generation_et_empreinte(monkeypatch):
    cle = cles.generer_cle()
    assert cle.startswith("LK-") and len(cle) == 3 + 32
    assert cles.generer_cle() != cle
    assert cles.prefixe_affiche(cle) == cle[:6]
    # Sans poivre : SHA-256 simple ; avec poivre : HMAC (différent), et l'ancienne empreinte reste candidate
    monkeypatch.delenv("LOOIS_CLES_PEPPER", raising=False)
    simple = cles.hacher_cle(cle)
    assert len(simple) == 64 and cle not in simple
    monkeypatch.setenv("LOOIS_CLES_PEPPER", "poivre-de-test")
    poivree = cles.hacher_cle(cle, cles.poivre())
    assert poivree != simple
    assert cles.empreintes_candidates(cle) == [poivree, simple]


def test_nettoyage_et_applications():
    propre = cles.nettoyer_fiche({"code": "Lycée Privé X", "applications": ["e-Kol", "EKOL", "biolog"]}, creation=True)
    assert propre["code"] == "LYCEE-PRIVE-X" and propre["applications"] == ["eKol", "Biolog"]
    assert propre["libelle"] == "LYCEE-PRIVE-X"
    with pytest.raises(ValueError):
        cles.nettoyer_fiche({"code": ""}, creation=True)
    with pytest.raises(ValueError):
        cles.nettoyer_fiche({"code": "X", "applications": ["Inconnue"]}, creation=True)
    assert cles.application_autorisee({"type": "client", "applications": ["eKol"]}, "eKol")
    assert not cles.application_autorisee({"type": "client", "applications": ["eKol"]}, "Biolog")
    assert cles.application_autorisee({"type": "client", "applications": []}, "Biolog")
    assert cles.application_autorisee({"type": "commune"}, "Aizenta")
    assert not cles.application_autorisee(None, "eKol")


def test_structure_client_et_empreinte():
    s = ls.structure_client("eKol", ["Paiements", "ElèveEdu", "inconnue", "paiements"])
    assert [t["nom"] for t in s["tables"]] == ["Paiements", "ElèveEdu"]   # inconnue et doublon écartés
    assert s["tables"][0]["cle_detectee"] == ["IDPaiements"] and len(s["hash"]) == 32
    # Même liste → même empreinte ; liste différente → empreinte différente
    assert ls.structure_client("eKol", ["Paiements", "ElèveEdu"])["hash"] == s["hash"]
    assert ls.structure_client("eKol", ["Paiements"])["hash"] != s["hash"]


# ---------------------------------------------------------------------------
# Administration des clés
# ---------------------------------------------------------------------------
def test_seule_l_empreinte_est_stockee_et_cle_montree_une_fois(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot681a"]
    c = application(db)
    assert c.post("/api/admin/loois-cles-clients", json={"code": "X"}, headers={"X-User": "phl"}).status_code == 403
    r = creer(c)
    cle = r["cle"]
    assert cle.startswith("LK-") and r["fiche"]["prefixe"] == cle[:6] and "cle_hash" not in r["fiche"]
    stockee = lancer(db.loois_cles_clients.find_one({}, {"_id": 0}))
    assert stockee["cle_hash"] == cles.hacher_cle(cle) and cle not in str(stockee)   # jamais la clé en clair
    # La liste ne montre jamais la clé ni l'empreinte
    liste = c.get("/api/admin/loois-cles-clients").json()
    assert cle not in str(liste) and stockee["cle_hash"] not in str(liste)
    assert liste["cles"][0]["code"] == "LYCEE-PRIVE-X" and liste["reglages"]["accepter_cle_commune_synchro"] is False
    # Un seul code par client
    assert c.post("/api/admin/loois-cles-clients", json={"code": "lycee prive x"}).status_code == 409


def test_revocation_regeneration_reactivation(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot681b"]
    c = application(db)
    r = creer(c)
    ancienne, ident = r["cle"], r["fiche"]["id"]
    params = {"application": "eKol", "machine": "PC-1"}
    assert c.get("/api/loois/synchro/config", params=params, headers={"X-Cle-Loois": ancienne}).status_code == 200
    # Révocation : refus immédiat (401 + en-tête de refus lu par Loois)
    c.post(f"/api/admin/loois-cles-clients/{ident}/revoquer")
    refus = c.get("/api/loois/synchro/config", params=params, headers={"X-Cle-Loois": ancienne})
    assert refus.status_code == 401 and refus.headers.get("X-Cle-Loois-Refus") == "1"
    # Réactivation : la même clé redevient valable
    c.post(f"/api/admin/loois-cles-clients/{ident}/reactiver")
    assert c.get("/api/loois/synchro/config", params=params, headers={"X-Cle-Loois": ancienne}).status_code == 200
    # Régénération : nouvelle clé (montrée une fois), l'ancienne est refusée
    nouvelle = c.post(f"/api/admin/loois-cles-clients/{ident}/regenerer").json()["cle"]
    assert nouvelle != ancienne
    assert c.get("/api/loois/synchro/config", params=params, headers={"X-Cle-Loois": ancienne}).status_code == 401
    ok = c.get("/api/loois/synchro/config", params=params, headers={"X-Cle-Loois": nouvelle})
    assert ok.status_code == 200 and ok.json()["site"] == "LYCEE-PRIVE-X" and ok.json()["client"] == "Lycée Privé X"
    fiche = c.get("/api/admin/loois-cles-clients").json()["cles"][0]
    assert fiche["derniere_machine"] == "PC-1" and fiche["derniere_utilisation"]
    assert [h["action"] for h in fiche["historique"]] == ["creation", "revocation", "reactivation", "regeneration"]
    # Modification du libellé et des applications
    assert c.put(f"/api/admin/loois-cles-clients/{ident}", json={"libelle": "Lycée X (Ouaga)", "applications": ["Biolog"]}).status_code == 200
    assert c.get("/api/loois/synchro/config", params=params, headers={"X-Cle-Loois": nouvelle}).status_code == 403   # e-Kol plus autorisé


# ---------------------------------------------------------------------------
# Synchro : client pris dans la clé, clé commune refusée par défaut
# ---------------------------------------------------------------------------
def test_site_de_la_cle_et_site_different_refuse(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot681c"]
    c = application(db)
    cle = {"X-Cle-Loois": creer(c)["cle"]}
    # Site absent → celui de la clé ; site identique (autre écriture) → accepté
    assert c.get("/api/loois/synchro/config", params={"application": "eKol"}, headers=cle).json()["site"] == "LYCEE-PRIVE-X"
    assert c.get("/api/loois/synchro/config", params={"application": "eKol", "site": "Lycée privé X"}, headers=cle).status_code == 200
    # Site d'un autre client → 403
    autre = c.get("/api/loois/synchro/config", params={"application": "eKol", "site": "ECOLE-Y"}, headers=cle)
    assert autre.status_code == 403 and autre.headers.get("X-Cle-Loois-Refus") == "1"
    assert c.post("/api/loois/synchro/lot", json=morceau(site="ECOLE-Y"), headers=cle).status_code == 403
    assert c.post("/api/loois/synchro/etat", json={"application": "eKol", "site": "ECOLE-Y", "tables": []}, headers=cle).status_code == 403
    # Bon site → morceau accepté et rangé dans la collection du client de la clé
    r = c.post("/api/loois/synchro/lot", json=morceau(), headers=cle)
    assert r.status_code == 200 and r.json()["upserts"] == 1
    assert lancer(db[ls.nom_collection("eKol", "LYCEE-PRIVE-X", "Paiements")].count_documents({})) == 1


def test_cle_commune_refusee_pour_la_synchro_sauf_transition(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot681d"]
    c = application(db)
    params = {"application": "eKol", "site": "ECOLE-Y", "machine": "PC-1"}
    refus = c.get("/api/loois/synchro/config", params=params, headers=COMMUNE)
    assert refus.status_code == 403 and refus.headers.get("X-Cle-Loois-Refus") == "1"
    assert c.post("/api/loois/synchro/lot", json=morceau(site="ECOLE-Y"), headers=COMMUNE).status_code == 403
    assert c.get("/api/loois/synchro/structure", params={"application": "eKol"}, headers=COMMUNE).status_code == 403
    # Réglage de transition coché : la clé commune refonctionne (site envoyé par le poste)
    assert c.put("/api/admin/loois-cles-clients-reglages", json={"accepter_cle_commune_synchro": True}, headers={"X-User": "phl"}).status_code == 403
    assert c.put("/api/admin/loois-cles-clients-reglages", json={"accepter_cle_commune_synchro": True}).json()["reglages"]["accepter_cle_commune_synchro"]
    ok = c.get("/api/loois/synchro/config", params=params, headers=COMMUNE)
    assert ok.status_code == 200 and ok.json()["site"] == "ECOLE-Y" and ok.json()["client"] is None
    # Clé absente ou fausse : 401
    assert c.get("/api/loois/synchro/config", params=params).status_code == 401
    assert c.get("/api/loois/synchro/config", params=params, headers={"X-Cle-Loois": "LK-faux"}).status_code == 401


def test_structure_telechargee_et_empreinte_annoncee(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot681e"]
    c = application(db)
    cle = {"X-Cle-Loois": creer(c)["cle"]}
    config = c.get("/api/loois/synchro/config", params={"application": "eKol", "machine": "PC-1"}, headers=cle).json()
    structure = c.get("/api/loois/synchro/structure", params={"application": "eKol"}, headers=cle)
    assert structure.status_code == 200
    s = structure.json()
    # Tables configurées seulement (liste intégrée e-Kol : Paiements, ElèveEdu), même empreinte que /config
    assert [t["nom"] for t in s["tables"]] == ["Paiements", "ElèveEdu"] and s["hash"] == config["structure_hash"]
    assert s["tables"][0]["colonnes"] and s["tables"][0]["cle_detectee"] == ["IDPaiements"]
    # Liste du client modifiée → nouvelle empreinte annoncée
    c.put("/api/admin/loois-synchro/config", json={"application": "eKol", "site": "LYCEE-PRIVE-X", "tables": [{"nom": "Paiements"}]})
    config2 = c.get("/api/loois/synchro/config", params={"application": "eKol", "machine": "PC-1"}, headers=cle).json()
    assert config2["structure_hash"] != config["structure_hash"]
    assert c.get("/api/loois/synchro/structure", params={"application": "eKol"}, headers=cle).json()["hash"] == config2["structure_hash"]
    assert c.get("/api/loois/synchro/structure", params={"application": "eKol"}).status_code == 401


# ---------------------------------------------------------------------------
# Présence et support : clé client OU clé commune
# ---------------------------------------------------------------------------
def test_presence_verifiee_par_client_ou_cle_commune(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot681f"]
    c = application(db)
    cle = creer(c)["cle"]
    corps = {"application": "Loois", "version": "1.0", "machine": "PC-A"}
    assert c.post("/api/presence-logiciel", json=corps, headers={"X-Cle-Loois": cle}).status_code == 200
    assert c.post("/api/presence-logiciel", json={**corps, "machine": "PC-B"}, headers=COMMUNE).status_code == 200
    assert c.post("/api/presence-logiciel", json={**corps, "machine": "PC-C"}, headers={"X-Cle-Loois": "faux"}).status_code == 200
    fiches = {f["machine"]: f for f in lancer(_tout(db.presences_logiciels))}
    assert fiches["PC-A"]["verifie"] is True and fiches["PC-A"]["verifie_client"] == "Lycée Privé X"
    assert fiches["PC-B"]["verifie"] is True and fiches["PC-B"]["verifie_client"] is None
    assert fiches["PC-C"]["verifie"] is False


async def _tout(collection):
    """Tous les documents d'une collection simulée."""
    return [d async for d in collection.find({}, {"_id": 0})]


def test_support_accepte_cle_client_et_cle_commune(env, monkeypatch):
    import routes.internal_chat as ic
    import routes.support_loois as sl

    monkeypatch.setenv("LOOIS_SUPPORT_LILUVINE", "0")
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot681g"]
    admin = {"id": "adm1", "role": "admin", "full_name": "Admin", "email": "a@s.test", "account_status": "active",
             "created_at": "2026-01-01T00:00:00+00:00"}

    async def get_user(request: Request):
        return admin

    api = APIRouter(prefix="/api")
    api.include_router(ic.make_router(db=db, get_current_user=get_user, decode_token=lambda t: {}))
    cles.setup_loois_cles_clients_routes(db=db, api=api, get_current_user=get_user)
    app = FastAPI()
    app.include_router(api)
    url = "/api/ws/support-loois?ecole=Lycee%20X&poste=PC-1&utilisateur=marie&version=1.0"
    with TestClient(app) as c:
        c.portal.call(db.users.insert_one, dict(admin))
        cle = c.post("/api/admin/loois-cles-clients", json={"code": "LYCEE-X", "libelle": "Lycée X"}).json()["cle"]
        with c.websocket_connect(url, headers={"X-Loois-Cle": cle}) as ws:
            assert ws.receive_json()["type"] == "hello"
        poste = c.portal.call(db.support_loois_postes.find_one, {}, {"_id": 0})
        assert poste["cle_client_code"] == "LYCEE-X" and poste["cle_client_libelle"] == "Lycée X"
        with c.websocket_connect(url, headers={"X-Loois-Cle": "cle-commune"}) as ws:   # ancienne clé : toujours acceptée
            assert ws.receive_json()["type"] == "hello"
        with c.websocket_connect(url, headers={"X-Loois-Cle": "LK-inconnue"}) as ws:
            assert ws.receive_json()["type"] == "erreur"
        # Clé commune retirée de Render : le support reste ouvert grâce aux clés clients
        monkeypatch.delenv("LOOIS_SUPPORT_CLE")
        assert sl.actif()
        with c.websocket_connect(url, headers={"X-Loois-Cle": cle}) as ws:
            assert ws.receive_json()["type"] == "hello"
