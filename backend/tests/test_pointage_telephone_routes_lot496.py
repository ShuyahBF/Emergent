# Lot 496 — pointage par téléphone : parcours complet des routes (base MongoDB simulée, aucun réseau).
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET", "secret-de-test")

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
    # Lot 498 : sans clé de pointage, pas d'inventaire ; la clé est générée une à une par l'administrateur
    sans_cle = client.post("/api/admin/pointage-inventaires", json={"structure": {"source": "loois", "id": "s1"}, "contenu": json.dumps(_export())})
    assert sans_cle.status_code == 400 and "clé de pointage" in sans_cle.json()["detail"]
    acces = client.post("/api/admin/pointage-acces", json={"source": "loois", "id": "s1"}).json()
    assert acces["cle"].startswith("CP-") and len(acces["mot_de_passe"]) == 9
    assert client.post("/api/admin/pointage-acces", json={"source": "loois", "id": "s1"}).status_code == 409
    r = client.post("/api/admin/pointage-inventaires", json={
        "structure": {"source": "loois", "id": "s1"}, "nom_fichier": "InventaireSélectionné_PPH_INV069.json", "contenu": json.dumps(_export()),
        "lieux": [{"nom": "Salle de vente", "colonne": "SV"}, {"nom": "Magasin", "colonne": "MG"}]})
    assert r.status_code == 200, r.text
    inv = r.json()
    assert (inv["numero"], inv["code_inv"], inv["lignes_total"]) == ("PT-0001", "INV069", 2)
    jeton = client.get(f"/api/admin/pointage-inventaires/{inv['id']}").json()["jeton"]

    # Téléphone : sans mot de passe, ni liste des produits ni saisie ; avec le mot de passe (saisi en majuscules) : jeton du téléphone
    ouvert = client.get(f"/api/public/pointage/{jeton}").json()
    assert ouvert["structure"] == "Clinique Philadelphie" and "lignes" not in ouvert and ouvert["mot_de_passe_requis"]
    assert client.post(f"/api/public/pointage/{jeton}/saisies", json={"prenom": "Awa", "appareil": "appareil-0001", "saisies": []}).status_code == 401
    assert client.post(f"/api/public/pointage/{jeton}/acces", json={"mot_de_passe": "faux-faux"}).status_code == 401
    tel = client.post(f"/api/public/pointage/{jeton}/acces", json={"mot_de_passe": acces["mot_de_passe"].upper()}).json()
    assert len(tel["lignes"]) == 2
    client.headers["X-Pointage-Telephone"] = tel["jeton_telephone"]
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

    # Nouveau mot de passe : le téléphone doit le ressaisir
    client.post(f"/api/admin/pointage-acces/{acces['id']}/mot-de-passe")
    assert client.post(f"/api/public/pointage/{jeton}/saisies", json=corps).status_code == 401
    del client.headers["X-Pointage-Telephone"]

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
    assert com["code"].startswith("CS-") and com["acces"]["cle"].startswith("CP-") and com["mot_de_passe"]
    trouves = client.get("/api/admin/pointage-inventaires/structures", params={"q": "awa"}).json()["structures"]
    assert [t["source"] for t in trouves] == ["commerce"]
    inv = client.post("/api/admin/pointage-inventaires", json={
        "structure": {"source": "commerce", "id": com["id"]}, "nom_fichier": "stock.csv",
        "contenu": "Désignation;Stock\nSavon Lux;24\nRiz;10\n", "lieux": [{"nom": "Rayon", "colonne": "SV"}]}).json()
    assert (inv["format"], inv["lignes_total"], inv["structure"]["code"]) == ("csv", 2, com["code"])
    jeton = client.get(f"/api/admin/pointage-inventaires/{inv['id']}").json()["jeton"]
    tel = client.post(f"/api/public/pointage/{jeton}/acces", json={"mot_de_passe": com["mot_de_passe"]}).json()
    client.post(f"/api/public/pointage/{jeton}/saisies", headers={"X-Pointage-Telephone": tel["jeton_telephone"]},
                json={"prenom": "Awa", "appareil": "appareil-0001", "saisies": [{"uid": "saisie-0001", "chrono": 1, "qte": 20, "lieu": "L1"}]})
    assert client.get(f"/api/admin/pointage-inventaires/{inv['id']}/export", params={"format": "json"}).status_code == 400
    csv = client.get(f"/api/admin/pointage-inventaires/{inv['id']}/export", params={"format": "csv"})
    assert csv.status_code == 200 and "1;;Savon Lux;;24;20;20;-4;;Awa" in csv.content.decode("utf-8-sig")
    assert client.get("/api/admin/pointage-inventaires").json()["inventaires"][0]["lignes_comptees"] == 1


def test_officine_dans_la_recherche(client):
    client.portal.call(BASE["db"].officines.insert_one, {"id": "off-123456789", "name": "Pharmacie Wend Denda", "city": "Ouagadougou"})
    r = client.get("/api/admin/pointage-inventaires/structures", params={"q": "wend"}).json()["structures"]
    assert r == [{"source": "officine", "id": "off-123456789", "libelle": "Pharmacie Wend Denda", "code": "OFF-1234", "type": "Officine",
                  "ville": "Ouagadougou", "acces": None}]
    # Clé générée une à une pour une officine déjà connue
    a = client.post("/api/admin/pointage-acces", json={"source": "officine", "id": "off-123456789"}).json()
    r = client.get("/api/admin/pointage-inventaires/structures", params={"q": "wend"}).json()["structures"]
    assert r[0]["acces"] == {"cle": a["cle"], "actif": True}


def test_reprise_des_fiches_du_lot_496(client):
    """Un inventaire créé par le lot 496 (fiche « settings ») est repris dans les nouvelles collections, saisies comprises."""
    ancien = pt.creer_inventaire(ident="ancien", numero="PT-0009", structure={"id": "s1", "code": "PPH", "libelle": "Clinique Philadelphie"},
                                 lieux=[], export=_export(), nom_fichier="InventaireSélectionné_PPH_INV069.json", par="a")
    ancien = ancien | {"_id": pt.PREFIXE_ID + "ancien", "saisies": [{"uid": "saisie-0001", "chrono": 9, "qte": 7, "lieu": "L1", "prenom": "Awa"}]}
    client.portal.call(BASE["db"].settings.insert_one, ancien)
    d = client.get("/api/admin/pointage-inventaires/ancien").json()
    assert (d["numero"], d["lignes_comptees"], d["structure"]["source"]) == ("PT-0009", 1, "loois")
    assert client.portal.call(BASE["db"].settings.find_one, {"_id": pt.PREFIXE_ID + "ancien"}) is None


def test_espace_pointage_et_etancheite(client):
    """Lot 498 : le responsable se connecte avec clé + mot de passe et ne voit QUE ses inventaires."""
    a = client.post("/api/admin/pointage-structures", json={"nom": "Boutique Awa", "type": "Boutique"}).json()
    b = client.post("/api/admin/pointage-structures", json={"nom": "Quincaillerie Badini", "type": "Quincaillerie"}).json()
    inv_b = client.post("/api/admin/pointage-inventaires", json={"structure": {"source": "commerce", "id": b["id"]}, "contenu": "Article\nMarteau\n"}).json()
    assert client.get("/api/pointage-espace/inventaires").status_code == 401
    cx = client.post("/api/pointage-espace/connexion", json={"cle": a["acces"]["cle"].lower().replace("-", " "), "mot_de_passe": a["mot_de_passe"]}).json()
    h = {"X-Pointage-Jeton": cx["jeton"]}
    assert cx["commerce"]["structure"]["libelle"] == "Boutique Awa"
    cree = client.post("/api/pointage-espace/inventaires", headers=h, json={"contenu": "Désignation;Stock\nSavon;3\n",
                                                                             "structure": {"source": "commerce", "id": b["id"]}}).json()
    assert cree["structure"]["id"] == a["id"]                       # structure imposée par la connexion, jamais celle envoyée
    assert [i["id"] for i in client.get("/api/pointage-espace/inventaires", headers=h).json()["inventaires"]] == [cree["id"]]
    assert client.get(f"/api/pointage-espace/inventaires/{inv_b['id']}", headers=h).status_code == 404
    assert client.post(f"/api/pointage-espace/inventaires/{inv_b['id']}/cloturer", headers=h).status_code == 404
    assert client.get(f"/api/pointage-espace/inventaires/{cree['id']}/export", headers=h, params={"format": "csv"}).status_code == 200
    # Clé révoquée : l'espace se ferme aussitôt
    client.post(f"/api/admin/pointage-acces/{cx['commerce']['id']}/revoquer")
    assert client.get("/api/pointage-espace/inventaires", headers=h).status_code == 401


def test_blocage_apres_cinq_essais(client):
    a = client.post("/api/admin/pointage-structures", json={"nom": "Boutique Awa", "type": "Boutique"}).json()
    for _ in range(5):
        assert client.post("/api/pointage-espace/connexion", json={"cle": a["acces"]["cle"], "mot_de_passe": "zzzz-zzzz"}).status_code == 401
    r = client.post("/api/pointage-espace/connexion", json={"cle": a["acces"]["cle"], "mot_de_passe": a["mot_de_passe"]})
    assert r.status_code == 429                                     # même le bon mot de passe attend la fin du blocage


def test_pays_langue_anglais_et_fichier_fusionne(client):
    """Lot 499 : commerce en anglais (alertes, CSV) ; un fichier fusionné garde le prénom de chaque saisie."""
    com = client.post("/api/admin/pointage-structures", json={"nom": "Corner Shop", "type": "Boutique", "pays": "Ghana", "langue": "en"}).json()
    assert (com["pays"], com["langue"]) == ("Ghana", "en")
    inv = client.post("/api/admin/pointage-inventaires", json={"structure": {"source": "commerce", "id": com["id"]},
                                                              "contenu": "Product;Stock\nSoap;4\nRice;50\n"}).json()
    assert inv["langue"] == "en"
    jeton = client.get(f"/api/admin/pointage-inventaires/{inv['id']}").json()["jeton"]
    assert client.get(f"/api/public/pointage/{jeton}").json()["langue"] == "en"
    tel = client.post(f"/api/public/pointage/{jeton}/acces", json={"mot_de_passe": com["mot_de_passe"]}).json()
    h = {"X-Pointage-Telephone": tel["jeton_telephone"]}
    # Envoi du responsable : saisies de deux téléphones fusionnées, chacune avec son prénom et son appareil
    client.post(f"/api/public/pointage/{jeton}/saisies", headers=h, json={"prenom": "Kofi", "appareil": "appareil-resp1", "saisies": [
        {"uid": "saisie-a001", "chrono": 2, "qte": 3, "lieu": "L1", "prenom": "Ama", "appareil": "appareil-ama1", "le": "2026-11-28T08:10:00+00:00"},
        {"uid": "saisie-b001", "chrono": 2, "qte": 4, "lieu": "L2", "prenom": "Yaw", "appareil": "appareil-yaw1"}]})
    d = client.get(f"/api/admin/pointage-inventaires/{inv['id']}").json()
    assert {a["prenom"] for a in d["par_auxiliaire"]} == {"Ama", "Yaw"}
    assert any(a["message"].startswith("large difference") for a in d["alertes"])
    csv = client.get(f"/api/admin/pointage-inventaires/{inv['id']}/export", params={"format": "csv"}).content.decode("utf-8-sig")
    assert csv.splitlines()[0].startswith("No.;Code;Product;Unit;Expected stock")
    # Pays et langue modifiables
    acces = client.get("/api/admin/pointage-acces").json()["acces"][0]
    assert client.put(f"/api/admin/pointage-acces/{acces['id']}", json={"pays": "Togo", "langue": "fr"}).json()["langue"] == "fr"


def test_langue_invalide_refusee(client):
    assert client.post("/api/admin/pointage-structures", json={"nom": "X Shop", "type": "Boutique", "langue": "de"}).status_code == 422
