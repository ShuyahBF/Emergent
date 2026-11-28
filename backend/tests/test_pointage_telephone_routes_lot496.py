# Lot 496 — pointage par téléphone : parcours complet des routes (base MongoDB simulée, aucun réseau).
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

import pointage_telephone as pt  # noqa: E402
from routes.pointage_telephone import setup_pointage_telephone_routes  # noqa: E402

UTILISATEUR = {"role": "admin", "email": "admin@test"}


def _export():
    return {pt.CLE_TABLE: [
        {"Chrono": 1, "Libellé": "ACETYL SALICLYLATE", "Mesure": "B/1", "IMagasin": 0, "ISalle": 0, "StockAvant_SV": -2,
         "StockAvant_MG": 0, "Peremption1": " ", "Diff": 2},
        {"Chrono": 9, "Libellé": "ACTISKENAN 10MG", "Mesure": "B/1", "IMagasin": 0, "ISalle": 0, "StockAvant_SV": 5,
         "StockAvant_MG": 20, "Peremption1": " ", "Diff": -25}]}


@pytest.fixture
def client():
    db = AsyncMongoMockClient()["test"]
    app, api = FastAPI(), APIRouter(prefix="/api")

    async def utilisateur():
        return UTILISATEUR
    setup_pointage_telephone_routes(db=db, api=api, get_current_user=utilisateur)
    app.include_router(api)
    with TestClient(app) as c:      # le « portail » du client de test exécute les appels asynchrones à la base
        c.portal.call(db.loois_cles_clients.insert_one, {"id": "s1", "code": "PPH", "libelle": "Clinique Philadelphie", "actif": True})
        yield c


def test_parcours_complet(client):
    assert client.get("/api/admin/pointage-inventaires/structures").json()["structures"][0]["code"] == "PPH"
    r = client.post("/api/admin/pointage-inventaires", json={
        "structure_id": "s1", "nom_fichier": "InventaireSélectionné_PPH_INV069.json", "export": _export(),
        "lieux": [{"nom": "Salle de vente", "colonne": "SV"}, {"nom": "Magasin", "colonne": "MG"}]})
    assert r.status_code == 200, r.text
    inv = r.json()
    assert (inv["numero"], inv["code_inv"], inv["lignes_total"]) == ("PT-0001", "INV069", 2)
    jeton = client.get(f"/api/admin/pointage-inventaires/{inv['id']}").json()["jeton"]

    # Téléphone : ouverture, puis envoi groupé (la même saisie renvoyée deux fois ne compte qu'une fois)
    ouvert = client.get(f"/api/public/pointage/{jeton}").json()
    assert ouvert["structure"] == "Clinique Philadelphie" and len(ouvert["lignes"]) == 2
    corps = {"prenom": "Awa", "appareil": "appareil-0001", "saisies": [
        {"uid": "saisie-0001", "chrono": 9, "qte": 12, "lieu": "L1", "peremption": "03/2027"},
        {"uid": "saisie-0001", "chrono": 9, "qte": 12, "lieu": "L1", "peremption": "03/2027"},
        {"uid": "saisie-0002", "chrono": 9, "qte": 5, "lieu": "L1"},
        {"uid": "saisie-0003", "chrono": 77, "qte": 5, "lieu": "L1"}]}
    rep = client.post(f"/api/public/pointage/{jeton}/saisies", json=corps).json()
    assert len(rep["refusees"]) == 1 and rep["doublons"] == [{"uid": "saisie-0002", "chrono": 9}]
    # Annulation : seulement par le téléphone qui a saisi
    assert client.post(f"/api/public/pointage/{jeton}/annuler", json={"appareil": "autre-appareil", "uid": "saisie-0002"}).status_code == 404
    assert client.post(f"/api/public/pointage/{jeton}/annuler", json={"appareil": "appareil-0001", "uid": "saisie-0002"}).status_code == 200

    detail = client.get(f"/api/admin/pointage-inventaires/{inv['id']}").json()
    assert (detail["lignes_comptees"], detail["saisies"], detail["annulees"]) == (1, 1, 1)

    export = client.get(f"/api/admin/pointage-inventaires/{inv['id']}/export")
    ligne9 = export.json()[pt.CLE_TABLE][1]
    assert (ligne9["ISalle"], ligne9["Peremption1"], ligne9["Diff"]) == (12, "20270301", -13)
    assert b"\\u00e9" in export.content                       # format WinDev : accents échappés

    # Clôture : le QR code ne sert plus
    client.post(f"/api/admin/pointage-inventaires/{inv['id']}/cloturer")
    assert client.get(f"/api/public/pointage/{jeton}").status_code == 404
    assert client.get("/api/admin/pointage-inventaires").json()["inventaires"][0]["etat"] == "cloture"


def test_structure_sans_cle_refusee(client):
    r = client.post("/api/admin/pointage-inventaires", json={"structure_id": "inconnue", "export": _export()})
    assert r.status_code == 400


def test_reserve_a_l_administrateur(client):
    UTILISATEUR["role"] = "client"
    try:
        assert client.get("/api/admin/pointage-inventaires").status_code == 403
    finally:
        UTILISATEUR["role"] = "admin"
