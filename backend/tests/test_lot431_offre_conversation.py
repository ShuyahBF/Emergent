"""Lot 431 — « Produits et services » d'une conversation du Centre de messagerie : sans tarifs, éditable par le superviseur seulement.
Lancer : cd backend && python -m pytest tests/test_lot431_offre_conversation.py -q
"""
from routes import offre_client as oc
from tests.test_puce_contrat_lot120 import SAWALI, _app, _run

OFFRE = [{"id": "o1", "type": "logiciel", "nom": "Pharmacie Plus", "description": "Gestion de stock", "version": "3.2", "actif": True,
          "montant": 450000, "devise": "FCFA", "duree_jours": 365, "rappel_jours": [7, 3], "alerte_active": True, "date_debut": "2026-01-01"},
         {"id": "o2", "type": "service", "nom": "Maintenance", "description": "", "version": "", "actif": True, "montant": 60000}]


def test_vue_sans_tarif_et_fusion_gardent_les_tarifs():
    existantes = oc.normaliser_offre(OFFRE)
    vue = oc.vue_sans_tarif(existantes)
    assert set(vue[0]) == set(oc.CHAMPS_SANS_TARIF) and "montant" not in vue[0] and "rappel_jours" not in vue[0]
    # édition SANS tarifs : o1 renommée, o2 retirée, une ligne neuve ajoutée
    maj = oc.modifier_sans_tarif(existantes, [{"id": "o1", "type": "logiciel", "nom": "Pharmacie Plus Pro", "description": "Stock + caisse", "version": "4.0", "actif": True},
                                              {"type": "produit", "nom": "Lecteur code-barres", "description": "USB"}])
    o1 = next(l for l in maj if l["id"] == "o1")
    assert o1["nom"] == "Pharmacie Plus Pro" and o1["version"] == "4.0"
    assert o1["montant"] == 450000 and o1["duree_jours"] == 365 and o1["rappel_jours"] == [7, 3] and o1["alerte_active"] is True      # tarif et échéance intacts
    assert "o2" not in [l["id"] for l in maj]
    neuve = next(l for l in maj if l["nom"] == "Lecteur code-barres")
    assert neuve["montant"] == 0 and neuve["type"] == "produit" and neuve["id"]
    # un identifiant inventé n'hérite de rien
    assert oc.modifier_sans_tarif(existantes, [{"id": "inconnu", "nom": "X"}])[0]["montant"] == 0


def test_roles_d_edition():
    assert oc.peut_modifier_offre("superviseur") and oc.peut_modifier_offre("admin")
    assert not oc.peut_modifier_offre("client") and not oc.peut_modifier_offre(None)


def test_routes_lecture_sans_tarif_et_edition_reservee():
    client, db, _ = _app({"id": "sup", "email": "sup@sawalismartsystems.com", "role": "superviseur", "client_id": SAWALI, "company": "SAWALI SMART SYSTEMS"})
    _run(db.users.update_one({"id": "pA"}, {"$set": {"offre_client": OFFRE}}))
    r = client.post("/api/me/contact-offre", json={"contact_id": "k1"}).json()                  # k1 = caisse de la pharmacie A
    assert r["client"]["nom"] == "Pharmacie A" and r["modifiable"] is True and [l["nom"] for l in r["lignes"]] == ["Pharmacie Plus", "Maintenance"]
    assert all("montant" not in l and "devise" not in l and "rappel_jours" not in l for l in r["lignes"])
    # contact sans société, inconnu ou hors périmètre : rien
    for cid in ("k7", "n'existe-pas", "k6"):
        assert client.post("/api/me/contact-offre", json={"contact_id": cid}).json()["client"] is None
    # édition par le superviseur : le tarif reste en base
    e = client.put("/api/me/contact-offre", json={"contact_id": "k1", "lignes": [{"id": "o1", "type": "logiciel", "nom": "Pharmacie Plus 2", "actif": True}]})
    assert e.status_code == 200 and [l["nom"] for l in e.json()["lignes"]] == ["Pharmacie Plus 2"] and "montant" not in e.json()["lignes"][0]
    en_base = _run(db.users.find_one({"id": "pA"}))
    assert en_base["offre_client"][0]["montant"] == 450000 and en_base["offre_client_maj"]["par"] is not None
    assert client.put("/api/me/contact-offre", json={"contact_id": "k7", "lignes": []}).status_code == 404


def test_edition_refusee_aux_autres_roles():
    client, db, _ = _app({"id": "sa2", "email": "agent@sawalismartsystems.com", "role": "client", "client_id": SAWALI})
    r = client.post("/api/me/contact-offre", json={"contact_id": "k1"}).json()
    assert r["modifiable"] is False
    e = client.put("/api/me/contact-offre", json={"contact_id": "k1", "lignes": []})
    assert e.status_code == 403
