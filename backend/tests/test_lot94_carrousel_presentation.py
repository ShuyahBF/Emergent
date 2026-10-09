"""Lot 94 — carte de carrousel SANS lien : son bouton mène à la page de présentation du site
(<site>/presentation/{code}), alimentée par GET /api/public/carrousel/carte/{code} (photo, titre, texte, prix
et description du produit), au lieu d'une page d'erreur. Les anciens liens automatiques
/api/public/og/product/… mènent aussi à cette page.
Lancer : cd backend && python -m pytest tests/test_lot94_carrousel_presentation.py -q
"""
from __future__ import annotations

import routes.carrousel_whatsapp as cw
from tests.test_carrousel_whatsapp import BASE, CARTES_PRODUITS, env, h  # noqa: F401


def test_doit_presenter():
    assert cw.doit_presenter("") and cw.doit_presenter(None)
    assert cw.doit_presenter(f"{BASE}/api/public/og/product/p1")      # ancien lien automatique d'un produit
    assert not cw.doit_presenter("https://boutique.bf/promo")         # lien saisi : conservé


def test_carte_sans_lien_presentee(env):
    client, db, _ = env
    client.put("/api/me/whatsapp/carrousel/consentements", headers=h("cli_a"), json={"ids": ["c1"], "accepte": True})
    libre = {"source": "libre", "image_url": f"{BASE}/api/files/c/1.png", "titre": "Journée santé", "texte": "Samedi 9h"}
    r = client.post("/api/me/whatsapp/carrousel/envoyer", headers=h("cli_a"),
                    json={"message": "Nouveautés", "cartes": [CARTES_PRODUITS[0], libre], "ids": ["c1"]})
    assert r.status_code == 202, r.text
    camp = client.get(f"/api/me/whatsapp/carrousel/campagnes/{r.json()['id']}", headers=h("cli_a")).json()
    code_produit, code_libre = (c["code_lien"] for c in camp["cartes"])

    # Les deux boutons mènent à la page de présentation du site (clic compté)
    for code in (code_produit, code_libre):
        rr = client.get(f"/api/public/carrousel/l/{code}", follow_redirects=False)
        assert rr.status_code == 302 and rr.headers["location"] == f"{BASE}/presentation/{code}"

    # Contenu public de la carte produit : prix et nom du produit, expéditeur ; carte libre : son texte
    p = client.get(f"/api/public/carrousel/carte/{code_produit}").json()
    assert p["titre"] == "DOLIPRANE 1000" and p["produit"]["prix"] == "1 500 FCFA" and p["plateforme"] is False
    assert p["expediteur"] and "destinataires" not in p
    l = client.get(f"/api/public/carrousel/carte/{code_libre}").json()
    assert l["titre"] == "Journée santé" and l["texte"] == "Samedi 9h" and l["produit"] is None
    assert client.get("/api/public/carrousel/carte/inconnu").status_code == 404


def test_lien_saisi_conserve(env):
    client, db, _ = env
    client.put("/api/me/whatsapp/carrousel/consentements", headers=h("cli_a"), json={"ids": ["c1"], "accepte": True})
    libre = {"source": "libre", "image_url": f"{BASE}/api/files/c/1.png", "titre": "Promo", "lien": "https://boutique.bf/promo"}
    r = client.post("/api/me/whatsapp/carrousel/envoyer", headers=h("cli_a"),
                    json={"message": "x", "cartes": [libre, CARTES_PRODUITS[0]], "ids": ["c1"]})
    camp = client.get(f"/api/me/whatsapp/carrousel/campagnes/{r.json()['id']}", headers=h("cli_a")).json()
    rr = client.get(f"/api/public/carrousel/l/{camp['cartes'][0]['code_lien']}", follow_redirects=False)
    assert rr.headers["location"] == "https://boutique.bf/promo"
