"""Lot 315 — tarif EXPRESS = « Forfait par intervention » (flat_rate) du client relié au contact ; 0 = à préciser avant l'intervention."""
from tests.test_puce_contrat_lot120 import SAWALI, _app, _run


def test_forfait_du_client_relie_au_contact():
    client, db, _ = _app({"id": "sa", "email": "admin@sawalismartsystems.com", "role": "admin", "client_id": SAWALI})
    _run(db.users.update_one({"id": "pA"}, {"$set": {"flat_rate": 25000}}))
    # k1 (caisse de la pharmacie A, reconnue par son téléphone) → forfait de A ; k2 (pharmacie B, forfait non renseigné) → 0
    assert client.post("/api/me/contact-forfait", json={"contact_id": "k1"}).json() == {"forfait": 25000.0}
    assert client.post("/api/me/contact-forfait", json={"contact_id": "k2"}).json() == {"forfait": 0.0}
    # contact sans société (k7), contact inconnu : aucun forfait connu
    assert client.post("/api/me/contact-forfait", json={"contact_id": "k7"}).json() == {"forfait": None}
    assert client.post("/api/me/contact-forfait", json={"contact_id": "n'existe-pas"}).json() == {"forfait": None}
