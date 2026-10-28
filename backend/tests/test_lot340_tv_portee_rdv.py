"""Lot 340 — écran TV : portée des RDV du hall (tous les médecins du périmètre ou le compte de la télé seul) et affichage en clair au choix."""
from routes.ecran_tv import PORTEES_RDV, forme_hall, hall_en_clair, perimetre_rdv, portee_rdv_valide
from datetime import datetime, timezone


def test_portee_valide_par_defaut_tous():
    assert PORTEES_RDV == ("tous", "compte", "medecin")
    assert portee_rdv_valide("compte") == "compte" and portee_rdv_valide("tous") == "tous"
    assert portee_rdv_valide(None) == "tous" and portee_rdv_valide("n'importe quoi") == "tous"


def test_perimetre_compte_seul_ou_tous_les_medecins():
    assert perimetre_rdv("compte", "cli-1", ["cli-1", "cli-2"], ["CMCO"]) == {"tenant_id": "cli-1"}
    assert perimetre_rdv("tous", "cli-1", ["cli-1", "cli-2"], ["CMCO"]) == {"$or": [{"tenant_id": {"$in": ["cli-1", "cli-2"]}}, {"code_clinique": {"$in": ["CMCO"]}}]}
    assert perimetre_rdv("tous", "cli-1", ["cli-1"], []) == {"tenant_id": {"$in": ["cli-1"]}}


def test_clair_seulement_pour_un_ecran_limite_au_compte():
    assert hall_en_clair("compte", True, False) is True
    assert hall_en_clair("tous", True, False) is False          # tous les médecins : toujours anonymisé
    assert hall_en_clair("compte", False, False) is False
    assert hall_en_clair("tous", False, True) is True           # page administrateur (lot 328) inchangée


def test_hall_clair_ou_anonymise():
    maintenant = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
    docs = [{"medecin": "Dr X", "is_rdv": 1, "start_at": "2026-10-28T10:00:00+00:00", "patient": "GUYO Paulin : 70001122", "patient_phone": "70001122"}]
    anonyme = forme_hall(docs, {}, maintenant, clair=False)["medecins"][0]["rdv"][0]
    clair = forme_hall(docs, {}, maintenant, clair=True)["medecins"][0]["rdv"][0]
    assert "*" in anonyme["qui"] and anonyme["tel"] == "7*****22"
    assert clair["qui"] == "GUYO Paulin" and clair["tel"] == "70001122"
