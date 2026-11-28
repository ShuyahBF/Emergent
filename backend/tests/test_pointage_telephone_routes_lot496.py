# Lot 496 — pointage par téléphone : parcours complet des routes (base MongoDB simulée, aucun réseau).
import json
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


BASE = {}


@pytest.fixture
def client():
    db = AsyncMongoMockClient()["test"]
    BASE["db"] = db
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
        "structure": {"source": "loois", "id": "s1"}, "nom_fichier": "InventaireSélectionné_PPH_INV069.json", "contenu": json.dumps(_export()),
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
    r = client.post("/api/admin/pointage-inventaires", json={"structure": {"source": "loois", "id": "inconnue"}, "contenu": json.dumps(_export())})
    assert r.status_code == 400


def test_reserve_a_l_administrateur(client):
    UTILISATEUR["role"] = "client"
    try:
        assert client.get("/api/admin/pointage-inventaires").status_code == 403
    finally:
        UTILISATEUR["role"] = "admin"


def test_commerce_declare_et_csv(client):
    """Lot 497 : un commerce quelconque (pas d'Aizenta) — déclaré ici, liste des produits en CSV, export CSV."""
    com = client.post("/api/admin/pointage-structures", json={"nom": "Boutique Awa", "type": "Boutique", "ville": "Koudougou"}).json()
    assert com["code"].startswith("CS-")
    trouves = client.get("/api/admin/pointage-inventaires/structures", params={"q": "awa"}).json()["structures"]
    assert [t["source"] for t in trouves] == ["commerce"]
    inv = client.post("/api/admin/pointage-inventaires", json={
        "structure": {"source": "commerce", "id": com["id"]}, "nom_fichier": "stock.csv",
        "contenu": "Désignation;Stock\nSavon Lux;24\nRiz;10\n", "lieux": [{"nom": "Rayon", "colonne": "SV"}]}).json()
    assert (inv["format"], inv["lignes_total"], inv["structure"]["code"]) == ("csv", 2, com["code"])
    jeton = client.get(f"/api/admin/pointage-inventaires/{inv['id']}").json()["jeton"]
    client.post(f"/api/public/pointage/{jeton}/saisies", json={"prenom": "Awa", "appareil": "appareil-0001",
                                                                "saisies": [{"uid": "saisie-0001", "chrono": 1, "qte": 20, "lieu": "L1"}]})
    assert client.get(f"/api/admin/pointage-inventaires/{inv['id']}/export", params={"format": "json"}).status_code == 400
    csv = client.get(f"/api/admin/pointage-inventaires/{inv['id']}/export", params={"format": "csv"})
    assert csv.status_code == 200 and "1;;Savon Lux;;24;20;20;-4;;Awa" in csv.content.decode("utf-8-sig")
    assert client.get("/api/admin/pointage-inventaires").json()["inventaires"][0]["lignes_comptees"] == 1


def test_officine_dans_la_recherche(client):
    client.portal.call(BASE["db"].officines.insert_one, {"id": "off-123456789", "name": "Pharmacie Wend Denda", "city": "Ouagadougou"})
    r = client.get("/api/admin/pointage-inventaires/structures", params={"q": "wend"}).json()["structures"]
    assert r == [{"source": "officine", "id": "off-123456789", "libelle": "Pharmacie Wend Denda", "code": "OFF-1234", "type": "Officine", "ville": "Ouagadougou"}]


def test_reprise_des_fiches_du_lot_496(client):
    """Un inventaire créé par le lot 496 (fiche « settings ») est repris dans les nouvelles collections, saisies comprises."""
    ancien = pt.creer_inventaire(ident="ancien", numero="PT-0009", structure={"id": "s1", "code": "PPH", "libelle": "Clinique Philadelphie"},
                                 lieux=[], export=_export(), nom_fichier="InventaireSélectionné_PPH_INV069.json", par="a")
    ancien = ancien | {"_id": pt.PREFIXE_ID + "ancien", "saisies": [{"uid": "saisie-0001", "chrono": 9, "qte": 7, "lieu": "L1", "prenom": "Awa"}]}
    client.portal.call(BASE["db"].settings.insert_one, ancien)
    d = client.get("/api/admin/pointage-inventaires/ancien").json()
    assert (d["numero"], d["lignes_comptees"], d["structure"]["source"]) == ("PT-0009", 1, "loois")
    assert client.portal.call(BASE["db"].settings.find_one, {"_id": pt.PREFIXE_ID + "ancien"}) is None
