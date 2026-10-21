"""Lot 276 — contacts des « Ad Auto-Replies » : marqués « Prospect », pas d'appel du propriétaire, point à la connexion.
Lancer : cd backend && python -m pytest tests/test_lot276_prospects_pub_reactions.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("mongomock_motor")
import mongomock_motor  # noqa: E402
from routes import marquage_prospect_pub as m  # noqa: E402
from tests.test_lot67_appel_proprietaire import env, lancer, message, relais_envoyes  # noqa: E402,F401


def _modele(db, texte="Prospects Facebook - Publicité Pharmacies de Garde"):
    lancer(db.liluvine_ad_templates.insert_one(
        {"id": "t1", "name": "Facebook Publicités", "trigger_text": texte, "active": True, "response_text": "Bonjour"}))


def test_modele_pour_texte():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot276a"]
    _modele(db, "Puis-je en savoir plus sur votre entreprise ?")
    assert lancer(m.modele_pour_texte(db, "puis-je en savoir plus sur votre entreprise"))["id"] == "t1"
    assert lancer(m.modele_pour_texte(db, "Bonjour, ma commande ?")) is None
    assert lancer(m.modele_pour_texte(db, "")) is None


def test_message_publicitaire_pas_d_appel_mais_relais(env):
    _modele(env["db"], "Bonjour, ma commande ?")          # le texte par défaut du test correspond au modèle
    r = message(env["db"])
    assert not env["appels"] and relais_envoyes(env["requetes"])
    assert "publicité" in r["raison"]


def test_message_ordinaire_appelle_toujours(env):
    _modele(env["db"], "Une tout autre annonce Facebook")
    message(env["db"])
    assert env["appels"]


def test_marquer_numero_inconnu_et_point():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot276b"]
    lancer(db.wa_pending_imports.insert_one({"id": "p1", "phone_digits": "22670000009"}))
    assert lancer(m.marquer_numero_inconnu(db, "22670000009")) == 1
    assert lancer(db.wa_pending_imports.find_one({"id": "p1"}))["prospect_pub"] is True
    lancer(db.liluvine_contact_interactions.insert_many([
        {"id": "i1", "kind": "ad_template", "contact_id": "c1", "contact_name": "Awa", "phone_digits": "1", "tenant_id": "s",
         "template_name": "Facebook Publicités", "inbound_text": "Bonjour", "created_at": "2026-10-21T10:00:00+00:00"},
        {"id": "i2", "kind": "ad_template", "contact_id": "c1", "contact_name": "Awa", "phone_digits": "1", "tenant_id": "s",
         "template_name": "Facebook Publicités", "inbound_text": "Bonjour", "created_at": "2026-10-21T11:00:00+00:00"},
        {"id": "i3", "kind": "ad_template", "contact_id": "c2", "contact_name": "Boni", "phone_digits": "2", "tenant_id": "s",
         "template_name": "Wp comment allez vous", "inbound_text": "Salut", "created_at": "2026-10-21T12:00:00+00:00"},
        {"id": "i4", "kind": "fuzzy_cmd", "contact_id": "c3", "tenant_id": "s", "created_at": "2026-10-21T12:00:00+00:00"},
        {"id": "i5", "kind": "ad_template", "contact_id": "c4", "tenant_id": "autre", "template_name": "X",
         "created_at": "2026-10-21T12:00:00+00:00"},
        {"id": "i6", "kind": "ad_template", "contact_id": "c5", "tenant_id": "s", "template_name": "Vieux",
         "created_at": "2026-10-01T12:00:00+00:00"},
    ]))
    p = lancer(m.point_prospects_publicite(db, ["s"], "2026-10-20T00:00:00+00:00"))
    assert p["total"] == 3 and p["contacts"] == 2
    assert p["par_modele"][0] == {"modele": "Facebook Publicités", "nombre": 2}
    assert [c["nom"] for c in p["derniers"]] == ["Boni", "Awa"]
