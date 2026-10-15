"""Lot 181 — classement des conversations par Liluvine : catégories, marqueur [CLASSE: …], assistant IA, message de mise en relation.
Lancer : cd backend && python -m pytest tests/test_lot181_classement_conversation.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes import liluvine_classement as c  # noqa: E402

AGENTS = [
    {"prenom": "Awa", "specialite": "Secrétaire"}, {"prenom": "Robert", "specialite": "Comptable"},
    {"prenom": "Gaspard", "specialite": "Technicien"}, {"prenom": "Gédéon", "specialite": "Commercial"},
]


def test_categories_par_defaut_et_reglees():
    assert c.categories({}) == c.CATEGORIES_DEFAUT
    assert c.categories({"liluvine_classement_categories": ["Juridique", " ", "RH"]}) == ["Juridique", "RH"]
    assert c.categories({"liluvine_classement_categories": "A\nB"}) == ["A", "B"]
    assert len(c.categories({"liluvine_classement_categories": [f"c{i}" for i in range(20)]})) == c.MAX_CATEGORIES
    assert c.actif({}) is True and c.actif({"liluvine_classement_actif": False}) is False


def test_marqueur_retire_et_categorie_validee():
    texte, cl = c.extraire_classement("Je regarde. [CLASSE: technique | Aizenta ne démarre plus]", c.CATEGORIES_DEFAUT)
    assert "CLASSE" not in texte and texte == "Je regarde."
    assert cl == {"categorie": "Technique", "motif": "Aizenta ne démarre plus"}
    _, cl = c.extraire_classement("ok [CLASSE: Comptabilite | facture]", c.CATEGORIES_DEFAUT)
    assert cl["categorie"] == "Comptabilité"                      # accents tolérés
    _, cl = c.extraire_classement("ok [CLASSE: Inconnue | truc]", c.CATEGORIES_DEFAUT)
    assert cl["categorie"] == "Autre"                              # hors liste → Autre
    _, cl = c.extraire_classement("Bonjour !", c.CATEGORIES_DEFAUT)
    assert cl is None


def test_assistant_de_la_categorie():
    assert c.agent_pour_categorie(AGENTS, "Technique")["prenom"] == "Gaspard"
    assert c.agent_pour_categorie(AGENTS, "Comptabilité")["prenom"] == "Robert"
    assert c.agent_pour_categorie(AGENTS, "Commercial")["prenom"] == "Gédéon"
    assert c.agent_pour_categorie(AGENTS, "Secrétariat / rendez-vous")["prenom"] == "Awa"
    assert c.agent_pour_categorie(AGENTS, "Autre") is None
    assert c.agent_pour_categorie([], "Technique") is None


def test_message_de_mise_en_relation():
    t = c.texte_mise_en_relation(AGENTS[2], "Aizenta ne démarre plus", "AMY-2026-0007")
    assert "Aizenta ne démarre plus" in t and "AMY-2026-0007" in t and "Gaspard (Technicien)" in t
    assert "ticket" not in c.texte_mise_en_relation(AGENTS[2], "x", None).lower()
    assert "votre assistant IA" in c.texte_mise_en_relation(None, "x", None)


def test_consignes():
    assert "[CLASSE:" in c.consignes_classement(c.CATEGORIES_DEFAUT) and "Technique" in c.consignes_classement(c.CATEGORIES_DEFAUT)
    assert "DÉJÀ classée" in c.consignes_classement(c.CATEGORIES_DEFAUT, "Technique")


def test_classement_valide_seulement_si_recent_et_actif_lot190():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
    iso = lambda minutes: (now - timedelta(minutes=minutes)).isoformat()
    cl = {"categorie": "Technique", "at": iso(10)}
    assert c.classement_encore_valide(cl, iso(2), now) == "Technique"                 # conversation en cours : pas de re-classement
    assert c.classement_encore_valide({"at": iso(61)}, iso(2), now) is None           # classement trop ancien (60 min)
    assert c.classement_encore_valide(cl, iso(31), now) is None                        # conversation endormie (30 min) : nouvelle demande
    assert c.classement_encore_valide({"at": iso(70), "categorie": "X"}, iso(40), now) is None   # l'ancien cas de 6 h
    assert c.classement_encore_valide({}, iso(1), now) is None and c.classement_encore_valide(None, None, now) is None
    assert c.classement_encore_valide({"at": "n'importe quoi"}, iso(1), now) is None
    assert c.classement_encore_valide({"at": iso(5)}, None, now) == "classée"          # sans activité connue : valable
