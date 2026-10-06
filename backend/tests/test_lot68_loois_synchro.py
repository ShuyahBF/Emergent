"""Lot 68 — Synchro des tables HFSQL des clients Loois vers MongoDB : clé obligatoire, configuration (commune par
application + surcharge par client), poste désigné, morceaux idempotents, upsert / suppression, fin d'envoi complet,
conversion des types d'après le schéma de référence (GitHub), nom des collections, limites de taille, page d'admin.
MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_lot68_loois_synchro.py -q
"""
from __future__ import annotations

import asyncio
import gzip
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import Request  # noqa: E402  (annotation résolue malgré « from __future__ »)

import routes.loois_synchro as ls  # noqa: E402

UTILISATEURS = {"admin": {"id": "admin", "role": "admin", "full_name": "Admin SAWALI"},
                "phl": {"id": "phl", "role": "pharmacien", "client_code": "PHL"}}
CLE = {"X-Cle-Loois": "cle-test"}


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def env(monkeypatch):
    """Clé du support définie pour les tests."""
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-test")


def client(db):
    """Application FastAPI minimale avec les routes du lot 68 ; utilisateur choisi par en-tête X-User."""
    from fastapi import APIRouter, FastAPI, HTTPException
    from fastapi.testclient import TestClient

    async def utilisateur(request: Request):
        u = UTILISATEURS.get(request.headers.get("X-User", "admin"))
        if not u:
            raise HTTPException(status_code=401)
        return u

    api = APIRouter(prefix="/api")
    ls.setup_loois_synchro_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def morceau(table="Paiements", lot="lot1", sequence=0, upserts=None, suppressions=None, complet=False, fin=True, site="Ecole X"):
    """Corps d'un morceau tel que Loois l'envoie (SynchroTablesLogique.CorpsMorceau)."""
    return {"application": "eKol", "site": site, "machine": "PC-1", "table": table, "lot": lot, "sequence": sequence,
            "complet": complet, "fin": fin, "cle": ["IDPaiements"], "lignes_source": 3,
            "upserts": upserts or [], "suppressions": suppressions or []}


def paiement(id_, montant="15000.5", date="2026-10-06"):
    """Ligne Paiements avec les noms HFSQL exacts (accents compris) et des valeurs JSON telles que Loois les convertit."""
    return {"cle": str(id_), "ligne": {"IDPaiements": id_, "MontantPayé": montant, "DatePaiement": date,
                                       "DateHeure_Création": "2026-10-06T08:30:00", "Verifié": 1, "Motif": "Scolarité",
                                       "IMG_Paiement": "AAAA", "AnnéeScolaire": "2025-2026"}}


def post_gzip(c, corps, headers=CLE):
    """Envoi compressé (Content-Encoding: gzip), comme Loois."""
    return c.post("/api/loois/synchro/lot", content=gzip.compress(json.dumps(corps).encode("utf-8")),
                  headers={**headers, "Content-Encoding": "gzip", "Content-Type": "application/json"})


# ---------------------------------------------------------------------------
# Logique pure
# ---------------------------------------------------------------------------
def test_noms_site_et_collection():
    """Même code de site que Loois ; collection sûre pour MongoDB ; colonnes conservées."""
    assert ls.code_site("Lycée Privé Wend-Panga") == "LYCEE-PRIVE-WEND-PANGA"
    assert ls.code_site("  scf ") == "SCF" and ls.code_site("") == ""
    assert ls.nom_collection("eKol", "ECOLE-X", "ElèveEdu") == "hf_ekol_ECOLE_X_EleveEdu"
    assert len(ls.nom_collection("Biolog", "S" * 40, "T" * 200)) == 120
    assert ls.cle_mongo("Prénoms") == "Prénoms" and ls.cle_mongo("$a.b") == "_a_b"
    assert ls.normaliser_application("e-Kol") == "eKol" and ls.normaliser_application("autre") is None


def test_schema_de_reference_et_cle():
    """Schéma embarqué (GitHub) : tables e-Kol Paiements et ElèveEdu, clés détectées comme dans Loois."""
    paiements = ls.table_reference("eKol", "paiements")
    eleves = ls.table_reference("eKol", "EleveEdu")                 # sans accent : retrouvée quand même
    assert paiements and eleves and eleves["nom"] == "ElèveEdu"
    assert ls.detecter_cle(paiements["nom"], paiements["colonnes"]) == ["IDPaiements"]
    assert ls.detecter_cle(eleves["nom"], eleves["colonnes"]) == ["IDElève"]
    assert set(ls.colonnes_binaires(paiements["colonnes"])) == {"IMG_Paiement", "ImagePDF"}
    assert ls.table_reference("Biolog", "Patient") and ls.table_reference("Aizenta", "Produit")


def test_conversion_des_types():
    """Entiers, réels, booléens, dates d'après le schéma ; binaire écarté ; colonne inconnue signalée."""
    ref = ls.table_reference("eKol", "Paiements")["colonnes"]
    doc, anomalies, inconnues = ls.convertir_ligne({**paiement(7)["ligne"], "Nouvelle": "x"}, ref)
    assert doc["IDPaiements"] == 7 and doc["MontantPayé"] == 15000.5 and doc["Verifié"] is True
    assert doc["DatePaiement"] == datetime(2026, 10, 6) and doc["DateHeure_Création"] == datetime(2026, 10, 6, 8, 30)
    assert "IMG_Paiement" not in doc and doc["AnnéeScolaire"] == "2025-2026"
    assert anomalies == 0 and inconnues == ["Nouvelle"]
    valeur, ok = ls.convertir_valeur("pas une date", "DBDate")
    assert not ok and valeur == "pas une date"
    assert ls.convertir_valeur("12", "BigInt") == (12, True) and ls.convertir_valeur("1,5", "Numeric") == (1.5, True)


def test_validation_et_limites():
    """Morceau invalide ou trop gros refusé ; bombe gzip refusée."""
    with pytest.raises(ValueError):
        ls.valider_lot({**morceau(), "lot": "../x"})
    with pytest.raises(ValueError):
        ls.valider_lot(morceau(upserts=[paiement(i) for i in range(ls.MAX_LIGNES_LOT + 1)]))
    with pytest.raises(ValueError):
        ls.lire_corps(gzip.compress(b" " * (ls.MAX_OCTETS_LOT + 10)), "gzip")
    assert ls.lire_corps(gzip.compress(b'{"a":1}'), "gzip") == {"a": 1}


def test_configuration_effective():
    """Surcharge du client > valeur commune de l'application > liste intégrée (e-Kol : Paiements, ElèveEdu)."""
    integree = ls.config_effective("eKol", None, None)
    assert integree["origine"] == "integree" and [t["nom"] for t in integree["tables"]] == ["Paiements", "ElèveEdu"]
    assert ls.config_effective("Biolog", None, None)["tables"] == []
    commune = {"actif": True, "tables": [{"nom": "Paiements"}]}
    assert ls.config_effective("eKol", commune, None)["origine"] == "application"
    assert ls.config_effective("eKol", commune, {"actif": False, "tables": []})["origine"] == "client"
    with pytest.raises(ValueError):
        ls.nettoyer_config("eKol", {"tables": [{"nom": "TableInexistante"}]})
    with pytest.raises(ValueError):
        ls.nettoyer_config("eKol", {"tables": [{"nom": "Paiements", "cle": ["Inconnue"]}]})
    propre = ls.nettoyer_config("eKol", {"tables": [{"nom": "paiements"}, "Paiements", {"nom": "EleveEdu", "colonnes_ignorees": ["photo"]}]})
    assert [t["nom"] for t in propre["tables"]] == ["Paiements", "ElèveEdu"] and propre["tables"][1]["colonnes_ignorees"] == ["Photo"]


# ---------------------------------------------------------------------------
# Routes Loois
# ---------------------------------------------------------------------------
def test_cle_obligatoire(env):
    """Sans clé (ou mauvaise clé) : 401 sur toutes les routes Loois."""
    c = client(mongomock_motor.AsyncMongoMockClient()["sawali_lot68a"])
    assert c.get("/api/loois/synchro/config", params={"application": "eKol", "site": "X"}).status_code == 401
    assert c.get("/api/loois/synchro/config", params={"application": "eKol", "site": "X"}, headers={"X-Cle-Loois": "faux"}).status_code == 401
    assert c.post("/api/loois/synchro/lot", json=morceau()).status_code == 401
    assert c.post("/api/loois/synchro/etat", json={}).status_code == 401


def test_config_et_poste_designe(env):
    """Liste par défaut e-Kol, clé et colonnes binaires fournies ; un seul poste désigné par site."""
    c = client(mongomock_motor.AsyncMongoMockClient()["sawali_lot68b"])
    r = c.get("/api/loois/synchro/config", params={"application": "e-Kol", "site": "Ecole X", "machine": "PC-1"}, headers=CLE)
    assert r.status_code == 200
    d = r.json()
    assert d["site"] == "ECOLE-X" and d["actif"] and d["poste_actif"]
    tables = {t["nom"]: t for t in d["tables"]}
    assert tables["Paiements"]["cle"] == ["IDPaiements"] and "ImagePDF" in tables["Paiements"]["colonnes_ignorees"]
    assert tables["ElèveEdu"]["cle"] == ["IDElève"] and "Photo" in tables["ElèveEdu"]["colonnes_ignorees"]
    autre = c.get("/api/loois/synchro/config", params={"application": "eKol", "site": "Ecole X", "machine": "PC-2"}, headers=CLE).json()
    assert not autre["poste_actif"] and autre["poste_designe"] == "PC-1"


def test_morceaux_idempotents_upsert_suppression(env):
    """Upsert par clé, renvoi sans effet, suppression, fin d'envoi complet qui retire les lignes disparues."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot68c"]
    c = client(db)
    coll = db[ls.nom_collection("eKol", "ECOLE-X", "Paiements")]
    # Envoi complet en 2 morceaux
    r = post_gzip(c, morceau(lot="L1", sequence=0, complet=True, fin=False, upserts=[paiement(1), paiement(2)]))
    assert r.status_code == 200 and r.json()["upserts"] == 2 and not r.json()["deja_recu"]
    assert post_gzip(c, morceau(lot="L1", sequence=1, complet=True, fin=True, upserts=[paiement(3)])).json()["nb_documents"] == 3
    # Renvoi du même morceau (accusé perdu) : rien n'est rejoué
    r = post_gzip(c, morceau(lot="L1", sequence=0, complet=True, fin=False, upserts=[paiement(1, montant="1")]))
    assert r.json()["deja_recu"]
    assert lancer(coll.find_one({"_hf_cle": "1"}))["MontantPayé"] == 15000.5
    # Modification + suppression (envoi différentiel)
    r = post_gzip(c, morceau(lot="L2", upserts=[paiement(2, montant="99")], suppressions=["3"]))
    assert r.json()["suppressions"] == 1 and r.json()["nb_documents"] == 2
    doc = lancer(coll.find_one({"_hf_cle": "2"}))
    assert doc["MontantPayé"] == 99.0 and doc["DatePaiement"] == datetime(2026, 10, 6) and "IMG_Paiement" not in doc
    # Nouvel envoi complet qui ne contient que la ligne 2 : la ligne 1 (disparue de HFSQL) est retirée
    r = post_gzip(c, morceau(lot="L3", complet=True, fin=True, upserts=[paiement(2, montant="99")]))
    assert r.json()["retirees"] == 1 and r.json()["nb_documents"] == 1
    # Catalogue à jour
    cat = lancer(db.loois_synchro_tables.find_one({"site": "ECOLE-X", "table": "Paiements"}))
    assert cat["nb_documents"] == 1 and cat["collection"] == "hf_ekol_ECOLE_X_Paiements" and cat["derniere_synchro"]


def test_table_non_configuree_refusee(env):
    """Une table hors de la configuration du client ne crée aucune collection (403)."""
    c = client(mongomock_motor.AsyncMongoMockClient()["sawali_lot68d"])
    assert c.post("/api/loois/synchro/lot", json=morceau(table="Enseignants"), headers=CLE).status_code == 403
    assert c.post("/api/loois/synchro/lot", json={**morceau(), "lot": "bad lot!"}, headers=CLE).status_code == 422


def test_etat_du_poste(env):
    """L'état envoyé par Loois (en attente, erreur) est rangé dans le catalogue pour les tables configurées seulement."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot68e"]
    c = client(db)
    r = c.post("/api/loois/synchro/etat", headers=CLE, json={"application": "eKol", "site": "ECOLE-X", "machine": "PC-1", "tables": [
        {"nom": "Paiements", "en_attente": 12, "erreur": "délai dépassé", "mode_detection": "sondage"}, {"nom": "Autre", "en_attente": 1}]})
    assert r.json()["tables"] == 1
    cat = lancer(db.loois_synchro_tables.find_one({"table": "Paiements"}))
    assert cat["en_attente"] == 12 and cat["erreur_poste"] == "délai dépassé"


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------
def test_admin_config_resynchro_donnees_csv(env):
    """Configuration commune puis surcharge d'un client, resynchronisation, lecture paginée, recherche et CSV."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot68f"]
    c = client(db)
    assert c.get("/api/admin/loois-synchro/vue", params={"application": "eKol"}, headers={"X-User": "phl"}).status_code == 403
    cat = c.get("/api/admin/loois-synchro/catalogue", params={"application": "eKol"}).json()
    assert any(t["nom"] == "Paiements" and t["cle_detectee"] == ["IDPaiements"] for t in cat["tables"])
    # Liste commune e-Kol : Paiements seulement ; puis le client ECOLE-Y ajoute ElèveEdu
    assert c.put("/api/admin/loois-synchro/config", json={"application": "eKol", "site": "*", "tables": [{"nom": "Paiements"}]}).status_code == 200
    assert c.put("/api/admin/loois-synchro/config", json={"application": "eKol", "site": "*", "tables": [{"nom": "Inconnue"}]}).status_code == 422
    c.put("/api/admin/loois-synchro/config", json={"application": "eKol", "site": "Ecole Y", "tables": [{"nom": "Paiements"}, {"nom": "ElèveEdu"}]})
    conf_x = c.get("/api/loois/synchro/config", params={"application": "eKol", "site": "ECOLE-X", "machine": "A"}, headers=CLE).json()
    conf_y = c.get("/api/loois/synchro/config", params={"application": "eKol", "site": "ECOLE-Y", "machine": "B"}, headers=CLE).json()
    assert [t["nom"] for t in conf_x["tables"]] == ["Paiements"] and len(conf_y["tables"]) == 2 and conf_y["origine"] == "client"
    # Resynchroniser tout : jeton transmis à Loois
    jeton = c.post("/api/admin/loois-synchro/resynchroniser", json={"application": "eKol", "site": "ECOLE-X", "table": "Paiements"}).json()["jeton"]
    conf_x = c.get("/api/loois/synchro/config", params={"application": "eKol", "site": "ECOLE-X", "machine": "A"}, headers=CLE).json()
    assert conf_x["tables"][0]["resynchro_jeton"] == jeton
    # Données reçues puis lues dans la page
    post_gzip(c, morceau(site="ECOLE-X", upserts=[paiement(1), {**paiement(2), "ligne": {**paiement(2)["ligne"], "Motif": "Cantine"}}]))
    d = c.get("/api/admin/loois-synchro/donnees", params={"application": "eKol", "site": "ECOLE-X", "table": "Paiements", "par_page": 1}).json()
    assert d["total"] == 2 and len(d["documents"]) == 1 and "MontantPayé" in d["colonnes"] and "IMG_Paiement" not in d["colonnes"]
    assert d["documents"][0]["DatePaiement"].startswith("2026-10-06")
    trouve = c.get("/api/admin/loois-synchro/donnees", params={"application": "eKol", "site": "ECOLE-X", "table": "Paiements", "recherche": "cantine"}).json()
    assert trouve["total"] == 1
    csv = c.get("/api/admin/loois-synchro/export-csv", params={"application": "eKol", "site": "ECOLE-X", "table": "Paiements"})
    assert csv.status_code == 200 and csv.text.startswith("﻿") and "MontantPayé" in csv.text.splitlines()[0]
    vue = c.get("/api/admin/loois-synchro/vue", params={"application": "eKol"}).json()
    sites = {cl["site"]: cl for cl in vue["clients"]}
    assert sites["ECOLE-Y"]["origine"] == "client" and sites["ECOLE-X"]["tables"][0]["nb_documents"] == 2
    # Retrait de la surcharge : ECOLE-Y reprend la liste commune
    c.delete("/api/admin/loois-synchro/config", params={"application": "eKol", "site": "ECOLE-Y"})
    conf_y = c.get("/api/loois/synchro/config", params={"application": "eKol", "site": "ECOLE-Y", "machine": "B"}, headers=CLE).json()
    assert conf_y["origine"] == "application"
