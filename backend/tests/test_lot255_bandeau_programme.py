"""Lot 255 — bandeau d'incident programmable (début / fin d'affichage)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bandeau_fenetre import bandeau_visible, debut_a_venir, valider_fenetre

MAINTENANT = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def iso(h):
    return (MAINTENANT + timedelta(hours=h)).isoformat()


def test_le_bandeau_ne_s_affiche_que_dans_sa_fenetre():
    assert bandeau_visible(True, None, None, MAINTENANT)                         # sans programmation : comme avant
    assert not bandeau_visible(False, None, None, MAINTENANT)                    # désactivé : jamais
    assert not bandeau_visible(True, iso(2), None, MAINTENANT)                   # début dans 2 h : pas encore
    assert bandeau_visible(True, iso(-1), iso(3), MAINTENANT)                    # dans la fenêtre
    assert not bandeau_visible(True, iso(-5), iso(-1), MAINTENANT)               # fin passée : retiré tout seul
    assert bandeau_visible(True, "", "", MAINTENANT)                             # dates vides = pas de programmation
    assert bandeau_visible(True, "n'importe quoi", None, MAINTENANT)             # dates illisibles déjà enregistrées : on n'efface pas


def test_un_debut_dans_le_futur_n_ouvre_pas_d_incident():
    assert debut_a_venir(iso(2), MAINTENANT) is True
    assert debut_a_venir(iso(-2), MAINTENANT) is False
    assert debut_a_venir(None, MAINTENANT) is False and debut_a_venir("illisible", MAINTENANT) is False


def test_validation_de_la_fenetre():
    d, f = valider_fenetre(iso(1), iso(2))
    assert d < f
    assert valider_fenetre("", "") == (None, None)
    with pytest.raises(ValueError):
        valider_fenetre("demain", None)
    with pytest.raises(ValueError):
        valider_fenetre(iso(2), iso(1))                                          # fin avant le début


def test_branchement_dans_la_lecture_publique_et_l_enregistrement():
    racine = Path(__file__).resolve().parents[1]
    public = (racine / "server_parts" / "p01_sante_auth_public.py").read_text(encoding="utf-8")
    assert "_bandeau_visible(bool(s.get(\"incident_banner_enabled\", False))" in public and "incident_banner_start_at" in public
    maj = (racine / "server_parts" / "p09_supervision_parametres.py").read_text(encoding="utf-8")
    assert "valider_fenetre" in maj and "debut_a_venir" in maj
    assert "incident_banner_start_at" in (racine / "models.py").read_text(encoding="utf-8")
