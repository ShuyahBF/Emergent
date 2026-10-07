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
    # Sans lien ni lien par défaut : refus explicite
    r = client.post(f"{BASE}/envoyer", headers=h("cli_a"), json=corps)
    assert r.status_code == 400 and "lien par défaut" in r.json()["detail"]
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
