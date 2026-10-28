"""Lot 341 — écran TV : portée « un médecin seul » (reconnu par e-mail ou nom), e-mail du médecin conservé, clair au choix."""
from routes.ecran_tv import PORTEES_RDV, hall_en_clair, normaliser_portes, perimetre_rdv, portee_rdv_valide


def test_portee_medecin_acceptee():
    assert "medecin" in PORTEES_RDV and portee_rdv_valide("medecin") == "medecin"
    assert portee_rdv_valide("autre") == "tous"


def test_perimetre_un_medecin_par_email_et_nom():
    q = perimetre_rdv("medecin", "cli-1", ["cli-1"], ["CMCO"], medecin="Dr DG", email="dg@clinique.bf")
    assert q["$and"][0] == perimetre_rdv("tous", "cli-1", ["cli-1"], ["CMCO"])       # reste dans le périmètre normal de la télé
    ou = q["$and"][1]["$or"]
    assert {"medecin_email": {"$regex": "^dg@clinique\\.bf$", "$options": "i"}} in ou
    assert {"medecin": {"$regex": "^Dr\\ DG$", "$options": "i"}} in ou


def test_perimetre_medecin_sans_identite_retombe_sur_tous():
    assert perimetre_rdv("medecin", "cli-1", ["cli-1"], []) == perimetre_rdv("tous", "cli-1", ["cli-1"], [])


def test_clair_pour_medecin_seul_mais_jamais_pour_tous():
    assert hall_en_clair("medecin", True, False) is True
    assert hall_en_clair("medecin", False, False) is False
    assert hall_en_clair("tous", True, False) is False


def test_email_du_medecin_conserve_et_valide():
    r = normaliser_portes([{"medecin": "Dr DG", "porte": "", "email": " DG@Clinique.BF "}, {"medecin": "Dr X", "porte": "B2", "email": "pas un mail"}])
    assert r[0] == {"medecin": "Dr DG", "porte": "", "email": "dg@clinique.bf"}       # une ligne avec seulement l'e-mail est gardée
    assert "email" not in r[1] and r[1]["porte"] == "B2"
