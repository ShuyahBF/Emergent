"""Lot 78 — carrousel : enregistrement automatique du travail en cours et lien par défaut des cartes libres."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
pytest.importorskip("mongomock_motor")

# Réutilise l'environnement de test du carrousel (lot 40) : utilisateurs, contacts, envoi WhatsApp simulé
from test_carrousel_whatsapp import env, h  # noqa: E402,F401

BASE = "/api/me/whatsapp/carrousel"
SANS_LIEN = [{"source": "libre", "image_url": "https://x/a.jpg", "titre": "A", "texte": "a", "lien": ""},
             {"source": "libre", "image_url": "https://x/b.jpg", "titre": "B", "texte": "b"}]


def test_brouillon_auto_enregistre_et_restaure_par_utilisateur(env):
    client, _, _ = env
    # Rien au départ
    assert client.get(f"{BASE}/brouillon-auto", headers=h("cli_a")).json()["brouillon"] is None
    # Deux enregistrements successifs : un seul brouillon automatique (mis à jour)
    for msg in ("Premier jet", "Second jet"):
        r = client.put(f"{BASE}/brouillon-auto", headers=h("cli_a"), json={"message": msg, "cartes": SANS_LIEN})
        assert r.status_code == 200 and r.json()["enregistre_le"]
    b = client.get(f"{BASE}/brouillon-auto", headers=h("cli_a")).json()["brouillon"]
    assert b["message"] == "Second jet" and len(b["cartes"]) == 2
    # L'utilisateur suivi du même client a son propre brouillon automatique
    assert client.get(f"{BASE}/brouillon-auto", headers=h("suivi_a")).json()["brouillon"] is None
    # Le brouillon automatique n'apparaît pas dans « Mes carrousels »
    assert client.get(f"{BASE}/brouillons", headers=h("cli_a")).json()["carrousels"] == []


def test_lien_par_defaut_valide_et_utilise_a_l_envoi(env):
    client, _, envois = env
    client.put(f"{BASE}/consentements", headers=h("cli_a"), json={"ids": ["c1"], "accepte": True})
    corps = {"message": "Promo", "cartes": SANS_LIEN, "ids": ["c1"]}
    # Lot 94 — sans lien ni lien par défaut : accepté, les cartes mèneront à leur page de présentation
    r = client.post(f"{BASE}/envoyer", headers=h("cli_a"), json=corps)
    assert r.status_code == 202, r.text
    camp0 = client.get(f"{BASE}/campagnes/{r.json()['id']}", headers=h("cli_a")).json()
    assert [c["lien"] for c in camp0["cartes"]] == ["", ""]
    # Lien par défaut invalide refusé, valide accepté
    assert client.put(f"{BASE}/preferences", headers=h("cli_a"), json={"lien_defaut": "ftp://x"}).status_code == 400
    assert client.put(f"{BASE}/preferences", headers=h("cli_a"), json={"lien_defaut": "https://boutique.bf"}).status_code == 200
    assert client.get(f"{BASE}/preferences", headers=h("cli_a")).json()["lien_defaut"] == "https://boutique.bf"
    # Envoi accepté : les cartes sans lien prennent le lien par défaut
    r = client.post(f"{BASE}/envoyer", headers=h("cli_a"), json=corps)
    assert r.status_code == 202, r.text
    camp = client.get(f"{BASE}/campagnes/{r.json()['id']}", headers=h("cli_a")).json()
    assert [c["lien"] for c in camp["cartes"]] == ["https://boutique.bf", "https://boutique.bf"]
    # L'envoi garde les cartes complètes : elles peuvent être rechargées dans l'éditeur
    assert camp["cartes"][0]["image_url"] == "https://x/a.jpg" and camp["message"] == "Promo"


# --- Lot 78.1 : destinataires élargis ----------------------------------------------------------
def test_portail_propose_les_utilisateurs_suivis(env):
    client, db, _ = env
    client.portal.call(db.tracked_users.insert_many, [
        {"id": "t1", "client_id": "cli_a", "name": "Suivi A", "whatsapp_number": "+226 70 00 00 01"},
        {"id": "t2", "client_id": "cli_b", "name": "Suivi B", "whatsapp_number": "+226 70 00 00 02"}])
    d = client.get(f"{BASE}/destinataires", headers=h("cli_a")).json()
    assert "t1" in {c["id"] for c in d["contacts"]} and "t2" not in {c["id"] for c in d["contacts"]}
    assert any(g["id"] == "@suivis" and g["contact_ids"] == ["t1"] for g in d["groupes"])
    # Consentement : seulement le suivi de son propre client
    r = client.put(f"{BASE}/consentements", headers=h("cli_a"), json={"ids": ["t1", "t2"], "accepte": True})
    assert r.json()["modifies"] == 1


def test_admin_clients_suivis_et_contacts_par_groupes(env):
    client, db, envois = env
    client.portal.call(db.tracked_users.insert_one, {"id": "t1", "client_id": "cli_a", "name": "Suivi A",
                                                      "whatsapp_number": "+226 70 00 00 01"})
    client.portal.call(db.directory_contacts.insert_one, {"id": "ca", "client_id": "admin", "name": "Contact admin",
                                                           "whatsapp": "+226 70 00 00 03"})
    d = client.get("/api/admin/whatsapp/carrousel/destinataires", headers=h("admin")).json()
    ids = {c["id"] for c in d["contacts"]}
    assert {"t1", "ca", "cli_a"} <= ids and "c1" not in ids          # pas les contacts des clients
    groupes = {g["id"]: g["contact_ids"] for g in d["groupes"]}
    assert groupes["@suivis"] == ["t1"] and groupes["@contacts"] == ["ca"]
    assert client.put("/api/admin/whatsapp/carrousel/consentements", headers=h("admin"),
                      json={"ids": ["t1", "ca"], "accepte": True}).json()["modifies"] == 2
    # Envoi par groupes (sans cocher les personnes une à une)
    cartes = [dict(c, lien="https://exemple.bf/promo") for c in SANS_LIEN]
    r = client.post("/api/admin/whatsapp/carrousel/envoyer", headers=h("admin"),
                    json={"message": "Promo", "cartes": cartes, "groupes": ["@suivis", "@contacts"]})
    assert r.status_code == 202, r.text
    assert r.json()["destinataires"] == 2


def test_lien_vide_redirige(env):
    client, _, _ = env
    assert client.get("/api/public/carrousel/l/", follow_redirects=False).status_code == 302
