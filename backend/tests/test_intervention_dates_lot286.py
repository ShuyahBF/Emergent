"""Lot 286 — les dates de début/fin d'une intervention sont conservées par les modèles de création et de mise à jour."""
from models import InterventionCreate, InterventionUpdate


def test_creation_conserve_la_plage_debut_fin():
    p = InterventionCreate(client_id="c1", title="t", intervention_date="2026-10-24",
                           date_heure_debut="2026-10-23T14:00", date_heure_fin="2026-10-24T08:00")
    d = p.model_dump()
    assert d["date_heure_debut"] == "2026-10-23T14:00" and d["date_heure_fin"] == "2026-10-24T08:00"


def test_mise_a_jour_conserve_la_plage_et_accepte_l_effacement():
    d = InterventionUpdate(date_heure_debut="", date_heure_fin="").model_dump()
    assert d["date_heure_debut"] == "" and d["date_heure_fin"] == ""
