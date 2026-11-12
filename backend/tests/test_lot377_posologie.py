"""Lot 377 — posologies VIDAL (remarques 4, 5, 6) : logique pure.
Lancer : cd backend && python -m pytest tests/test_lot377_posologie.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vidal_v2.posologie import (  # noqa: E402
    construire_xml_posology_request, libelle_schema, ligne_vidal_depuis_schema, message_manquants,
    palier_maximal, parser_descripteurs_posologie, patient_manquants, tendance, valider_schema,
)

SCHEMA_COMPLEXE = [  # 2 unités en 1 prise aujourd'hui, puis 1 unité en 1 prise dans 5 jours
    {"debut_jour": 0, "fin_jour": 4, "prises": [{"moment": "matin", "quantite": 2, "repas": "avant"}]},
    {"debut_jour": 5, "fin_jour": None, "prises": [{"moment": "matin", "quantite": 1, "repas": "indifferent"}]},
]


def test_alerte_si_age_sexe_ou_poids_manquent_sans_rien_bloquer():
    assert len(patient_manquants({})) == 3
    assert patient_manquants({"dateOfBirth": "1980-01-01", "gender": "MALE", "weight": 70}) == []
    assert "sexe" in " ".join(patient_manquants({"dateOfBirth": "1980-01-01", "weight": 70}))
    assert message_manquants([]) is None and "aucune posologie" in message_manquants(["le poids"])


def test_corps_xml_posology_request():
    xml = construire_xml_posology_request({"dateOfBirth": "1980-01-01", "gender": "MALE", "weight": 70.0, "height": 175}, "12")
    assert "<dateOfBirth>1980-01-01T00:00:00</dateOfBirth>" in xml and "<weight>70</weight>" in xml
    assert "<route>vidal://route/12</route>" in xml and "breastFeeding" not in xml


def test_lecture_de_la_reponse_vidal():
    brut = ('<feed><entry vidal:categories="POSOLOGY_DESCRIPTOR"><vidal:doseRange>3 sachets par jour</vidal:doseRange>'
            '<vidal:doseRange>30 g par jour</vidal:doseRange><vidal:frequencyRange>1 à 3 fois par jour</vidal:frequencyRange>'
            '<vidal:indication>Constipation</vidal:indication><vidal:route>orale</vidal:route></entry></feed>')
    r = parser_descripteurs_posologie(brut)
    assert r == [{"doses": ["3 sachets par jour", "30 g par jour"], "frequence": "1 à 3 fois par jour", "indication": "Constipation", "route": "orale"}]
    assert parser_descripteurs_posologie("rien") == [] and parser_descripteurs_posologie(None) == []


def test_schema_complexe_palier_maximal_et_libelle():
    assert palier_maximal(SCHEMA_COMPLEXE)["debut_jour"] == 0
    assert ligne_vidal_depuis_schema(SCHEMA_COMPLEXE)["dose"] == 2
    texte = libelle_schema(SCHEMA_COMPLEXE, "comprimé")
    assert "Dès" in texte or "À partir" in texte
    assert "2 comprimé le matin avant le repas" in texte and "jour 6" in texte
    assert valider_schema(SCHEMA_COMPLEXE) == []


def test_tendances_degressif_progressif():
    assert tendance(SCHEMA_COMPLEXE) == "degressif"
    progressif = [{"debut_jour": 0, "fin_jour": 2, "prises": [{"moment": "soir", "quantite": 1}]},
                  {"debut_jour": 3, "fin_jour": None, "prises": [{"moment": "soir", "quantite": 2}]}]
    assert tendance(progressif) == "progressif" and palier_maximal(progressif)["debut_jour"] == 3
    assert tendance(progressif[:1]) == "constant"


def test_trois_moments_dans_la_journee():
    palier = {"debut_jour": 0, "fin_jour": None, "prises": [
        {"moment": "matin", "quantite": 1}, {"moment": "midi", "quantite": 1}, {"moment": "soir", "quantite": 2, "repas": "apres"}]}
    assert ligne_vidal_depuis_schema([palier])["dose"] == 4 and ligne_vidal_depuis_schema([palier])["nb_prises"] == 3


def test_schema_invalide_detecte():
    assert valider_schema([{"debut_jour": 0, "fin_jour": 5, "prises": []}, {"debut_jour": 3, "fin_jour": None, "prises": []}])
    assert valider_schema([{"debut_jour": 0, "fin_jour": None, "prises": [{"moment": "nuit", "quantite": 1}]}])


def test_ordonnance_imprime_le_schema_complet():
    """Lot 378 : le schéma de prise figure sous le nom du médicament, la colonne Dose renvoie au schéma."""
    from routes.vidal_ordonnance import _fmt_line
    cellules = _fmt_line({"label": "Prednisolone", "dose": "2", "unit": "comprimé", "schema": SCHEMA_COMPLEXE})
    assert "Prednisolone" in cellules[0] and "jour 6" in cellules[0] and "le matin" in cellules[0]
    assert cellules[1] == "selon schéma"
    assert _fmt_line({"label": "A", "dose": "1"})[0] == "A"          # sans schéma : inchangé
