"""Lot 56 — Sécurisation VIDAL v2 portée depuis Ster.

Reprend (adaptés à SAWALI) les tests de Ster :
  - tests/test_vidal_securisation.py   : XML <patient>, fonction rénale,
    validation serveur (422 en français), lignes de prescription,
    endpoints avec l'API VIDAL simulée, référentiels backend/frontend ;
  - tests/test_vidal_historique_clinique.py : versions du profil clinique,
    instantanés de sécurisation, cloisonnement, export PDF ;
  - tests/test_vidal_validation.py     : mode validation (garde-fou, appels
    en production, journal, exports), patients fictifs, aucune valeur
    inventée.

Aucun appel réseau : l'API VIDAL est simulée (httpx.MockTransport injecté
dans le client HTTP existant de routes/vidal.py). Base MongoDB : un mongod
local (MONGO_URL), une base jetable par test. Identifiants VIDAL FICTIFS.

Lancer : cd backend && python -m pytest tests/test_lot56_vidal_securisation_v2.py -q
"""
from __future__ import annotations

import io
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")

import httpx  # noqa: E402
from fastapi import APIRouter, FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from pymongo import MongoClient  # noqa: E402

import routes.vidal as module_vidal  # noqa: E402
import routes.vidal_appels as appels_v2  # noqa: E402
from routes.vidal_fiche import attach_vidal_fiche_routes  # noqa: E402
from routes.vidal_patients import attach_vidal_patients_routes  # noqa: E402
from routes.vidal_securisation import (  # noqa: E402
    attach_vidal_securisation_routes, dedoublonner_traitements, ordonnances_depuis_audits, preparer_lignes_securisation,
)
from routes.vidal_validation import attach_vidal_validation_routes  # noqa: E402
from vidal_v2 import referentiels as R  # noqa: E402
from vidal_v2.fonction_renale import (  # noqa: E402
    calculer_fonction_renale_locale, clairance_cockcroft_gault, creatininemie_depuis_clairance, dfg_ckd_epi_2009,
)
from vidal_v2.groupes_dfg import GROUPES_DFG_DEFAUT, interpreter_dfg  # noqa: E402
from vidal_v2.historique_clinique import champs_modifies, valeurs_depuis_patient  # noqa: E402
from vidal_v2.journal_validation import classeur_xlsx  # noqa: E402
from vidal_v2.modeles import valider_payload_securisation  # noqa: E402
from vidal_v2.patients_fictifs import PROFILS, construire_patients_fictifs  # noqa: E402
from vidal_v2.traitements_en_cours import interpreter_duree_texte, lignes_traitements_en_cours  # noqa: E402
from vidal_v2.xml_securisation import construire_xml_prescription, parser_reponse_alertes  # noqa: E402

AUJOURDHUI = date.today()
URL_TEST = "https://api-test.vidal-simule.test/rest/api"
URL_PROD = "https://api-prod.vidal-simule.test/rest/api"
# Identifiants FICTIFS (jamais de vrais secrets dans les tests).
ID_TEST, CLE_TEST = "id_test", "cle_test"
ID_PROD, CLE_PROD = "id_prod_fictif", "cle_prod_fictive"
LIGNE = {"drugRef": "900001", "label": "MEDICAMENT TEST"}


def _iso(jours_avant: int) -> str:
    return (AUJOURDHUI - timedelta(days=jours_avant)).isoformat()


def _xml(payload: dict) -> str:
    """Valide le payload puis construit le XML exactement comme la route."""
    valide = valider_payload_securisation(payload)
    return construire_xml_prescription(valide.patient.model_dump(mode="json"), preparer_lignes_securisation(valide), valide.alert_types)


def _patient_xml(xml: str) -> ET.Element:
    return ET.fromstring(xml.split("\n", 1)[1]).find("patient")


def _erreurs(payload: dict) -> list:
    with pytest.raises(HTTPException) as exc:
        valider_payload_securisation(payload)
    assert exc.value.status_code == 422
    return exc.value.detail["erreurs"]


# ===========================================================================
# 1. XML <patient> (fonctions pures)
# ===========================================================================

def test_femme_enceinte_et_allaitante():
    patient = _patient_xml(_xml({
        "patient": {"dateOfBirth": "1992-04-12", "gender": "FEMALE", "weight": 62, "height": 165,
                    # 12 SA révolues (84 jours) : déduites de la date des dernières règles.
                    "lastMenstrualPeriodDate": _iso(84), "breastFeeding": "ALL", "breastFeedingStartDate": _iso(10)},
        "new_prescription_lines": [LIGNE],
    }))
    assert patient.findtext("weeksOfAmenorrhea") == "12"
    # Date de début < 30 jours -> catégorie déduite, quelle que soit la durée choisie.
    assert patient.findtext("breastFeeding") == "LESS_THAN_ONE_MONTH"
    assert patient.findtext("breastFeedingStartDate") == f"{_iso(10)}T00:00:00"
    assert [e.tag for e in patient][:7] == ["dateOfBirth", "gender", "weight", "height", "breastFeeding", "breastFeedingStartDate", "weeksOfAmenorrhea"]


def test_femme_allaitante_depuis_plus_d_un_mois_et_sans_date():
    patient = _patient_xml(_xml({"patient": {"gender": "FEMALE", "breastFeedingStartDate": _iso(45), "breastFeeding": "ALL"}, "new_prescription_lines": [LIGNE]}))
    assert patient.findtext("breastFeeding") == "MORE_THAN_ONE_MONTH"
    xml = _xml({"patient": {"gender": "FEMALE", "breastFeeding": "MORE_THAN_ONE_MONTH"}, "new_prescription_lines": [LIGNE]})
    assert '<breastFeedingStartDate xsi:nil="true" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" />' in xml


def test_femme_sans_allaitement_balise_nil_et_aucune_valeur_par_defaut():
    xml = _xml({"patient": {"gender": "FEMALE", "breastFeeding": "NONE"}, "new_prescription_lines": [LIGNE]})
    assert "<breastFeeding>NONE</breastFeeding>" in xml and '<breastFeedingStartDate xsi:nil="true"' in xml
    assert "weeksOfAmenorrhea" not in xml
    # Allaitement NON renseigné : aucune valeur par défaut, aucune balise.
    assert "breastFeeding" not in _xml({"patient": {"gender": "FEMALE"}, "new_prescription_lines": [LIGNE]})


def test_homme_et_sexe_indetermine_sans_balises_femme():
    xml = _xml({"patient": {"gender": "MALE", "weeksOfAmenorrhea": 12, "breastFeeding": "ALL", "breastFeedingStartDate": _iso(5),
                            "lastMenstrualPeriodDate": _iso(70)}, "new_prescription_lines": [LIGNE]})
    for balise in ("weeksOfAmenorrhea", "breastFeeding", "breastFeedingStartDate"):
        assert balise not in xml
    xml = _xml({"patient": {"gender": "UNKNOWN", "weeksOfAmenorrhea": 12}, "new_prescription_lines": [LIGNE]})
    assert "weeksOfAmenorrhea" not in xml and "<gender>UNKNOWN</gender>" in xml
    # Sexe NON renseigné : grossesse transmise, sexe en nil.
    xml = _xml({"patient": {"weeksOfAmenorrhea": 12}, "new_prescription_lines": [LIGNE]})
    assert "<weeksOfAmenorrhea>12</weeksOfAmenorrhea>" in xml and '<gender xsi:nil="true"' in xml


def test_sexe_absent_et_fonction_renale_inconnue_en_nil():
    xml = _xml({"patient": {}, "new_prescription_lines": [LIGNE]})
    assert '<gender xsi:nil="true" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" />' in xml
    assert '<creatin xsi:nil="true"' in xml
    assert "serumCreatinine" not in xml and "glomerularFiltrationRate" not in xml


# ===========================================================================
# 2. Fonction rénale
# ===========================================================================

def test_calculs_locaux_cas_de_reference():
    # Homme, 60 ans, 80 kg, créatininémie 70 µmol/L.
    assert clairance_cockcroft_gault(60, 80, "MALE", 70) == pytest.approx(112.457, abs=0.01)
    assert dfg_ckd_epi_2009(60, "MALE", 70) == pytest.approx(97.50, abs=0.05)
    assert creatininemie_depuis_clairance(60, 80, "MALE", 112.457) == pytest.approx(70, abs=0.01)
    assert clairance_cockcroft_gault(60, 80, "FEMALE", 70) == pytest.approx(95.086, abs=0.01)
    resultat = calculer_fonction_renale_locale(date_naissance=date(AUJOURDHUI.year - 60, 1, 1), sexe="MALE", poids_kg=80, creatininemie_umol_l=70)
    assert resultat == {"creatin": 112, "creatin_calculee": 112.46, "plafonnee": False, "serumCreatinine": 70.0,
                        "glomerularFiltrationRate": 97.5, "insuffisanceRenale": "NONE", "stadeKdigo": None, "age": 60}


def test_clairance_plafonnee_a_120():
    resultat = calculer_fonction_renale_locale(date_naissance=date(AUJOURDHUI.year - 26, 1, 1), sexe="MALE", poids_kg=90, creatininemie_umol_l=60)
    assert resultat["creatin_calculee"] > 120 and resultat["creatin"] == 120 and resultat["plafonnee"] is True


def test_trois_balises_renales_et_ancien_champ_clairance():
    xml = _xml({"patient": {"gender": "MALE", "creatin": 50, "serumCreatinine": 199.8, "glomerularFiltrationRate": 39.2}, "new_prescription_lines": [LIGNE]})
    assert "<creatin>50</creatin><serumCreatinine>199.80</serumCreatinine><glomerularFiltrationRate>39.20</glomerularFiltrationRate>" in xml
    # Ancien champ « clairance » de l'ancienne page SAWALI : arrondi et borné.
    assert _patient_xml(_xml({"patient": {"gender": "MALE", "clairance": 135.7}, "new_prescription_lines": [LIGNE]})).findtext("creatin") == "120"
    assert _patient_xml(_xml({"patient": {"gender": "MALE", "clairance": 47.6}, "new_prescription_lines": [LIGNE]})).findtext("creatin") == "48"


@pytest.mark.parametrize("valeur, message", [(0, "jamais 0"), (130, "entre 1 et 120")])
def test_clairance_zero_ou_hors_bornes_refusee(valeur, message):
    erreurs = _erreurs({"patient": {"creatin": valeur}})
    assert erreurs[0]["champ"] == "patient.creatin" and message in erreurs[0]["message"]


def test_clairance_decimale_refusee():
    assert _erreurs({"patient": {"creatin": 95.5}}) == [{"champ": "patient.creatin", "message": "Doit être un nombre entier (sans décimales)."}]


# ===========================================================================
# 3. Validation serveur (422 en français, champ par champ)
# ===========================================================================

@pytest.mark.parametrize("sa", [1, 43])
def test_semaines_amenorrhee_hors_bornes(sa):
    assert _erreurs({"patient": {"gender": "FEMALE", "weeksOfAmenorrhea": sa}}) == [
        {"champ": "patient.weeksOfAmenorrhea", "message": "Les semaines d'aménorrhée (SA) doivent être comprises entre 2 et 42."}]


def test_semaines_amenorrhee_bornes_acceptees():
    for sa in (2, 42):
        assert valider_payload_securisation({"patient": {"gender": "FEMALE", "weeksOfAmenorrhea": sa}}).patient.weeksOfAmenorrhea == sa


def test_date_dernieres_regles_et_allaitement_incoherents():
    erreurs = _erreurs({"patient": {"gender": "FEMALE", "lastMenstrualPeriodDate": _iso(400)}})
    assert erreurs[0]["champ"] == "patient.lastMenstrualPeriodDate" and "57 SA" in erreurs[0]["message"]
    erreurs = _erreurs({"patient": {"gender": "FEMALE", "lastMenstrualPeriodDate": _iso(84), "weeksOfAmenorrhea": 20}})
    assert erreurs[0]["champ"] == "patient.weeksOfAmenorrhea" and "Incohérence" in erreurs[0]["message"]
    erreurs = _erreurs({"patient": {"gender": "FEMALE", "lastMenstrualPeriodDate": (AUJOURDHUI + timedelta(days=3)).isoformat()}})
    assert "futur" in erreurs[0]["message"]
    erreurs = _erreurs({"patient": {"gender": "FEMALE", "breastFeeding": "NONE", "breastFeedingStartDate": _iso(3)}})
    assert erreurs[0]["champ"] == "patient.breastFeedingStartDate"


def test_controles_de_ligne():
    assert _erreurs({"new_prescription_lines": [{"drugRef": "1", "duration": 2.5, "durationType": "DAY"}]}) == [
        {"champ": "new_prescription_lines[0].duration", "message": "Doit être un nombre entier (sans décimales)."}]
    erreurs = _erreurs({"new_prescription_lines": [{"drugRef": "1", "dosages": [{"dose": 1, "intervalMin": 8, "intervalMax": 6}]}]})
    assert erreurs[0]["champ"] == "new_prescription_lines[0].dosages[0].intervalMax" and "supérieur ou égal" in erreurs[0]["message"]
    erreurs = _erreurs({"new_prescription_lines": [{"drugRef": "1", "dose": 0, "duration": 3, "frequencyType": "PAR_JOUR",
                                                    "startDate": "2026-10-10", "endDate": "2026-10-01", "ald": True}]})
    champs = {e["champ"]: e["message"] for e in erreurs}
    assert "strictement supérieur" in champs["new_prescription_lines[0].dose"] and "Fréquence" in champs["new_prescription_lines[0].frequencyType"]
    erreurs = _erreurs({"new_prescription_lines": [{"drugRef": "1", "duration": 3, "startDate": "2026-10-10", "endDate": "2026-10-01", "ald": True}]})
    assert {e["champ"] for e in erreurs} == {"new_prescription_lines[0].durationType", "new_prescription_lines[0].endDate", "new_prescription_lines[0].aldCode"}
    # La dose (cumulée par 24 h) exige sa fréquence ; un intervalle exige son unité (aucune unité par défaut).
    assert _erreurs({"new_prescription_lines": [{"drugRef": "1", "dose": 2, "unitId": "7"}]})[0]["champ"] == "new_prescription_lines[0].frequencyType"
    assert _erreurs({"new_prescription_lines": [{"drugRef": "1", "dosages": [{"dose": 1, "intervalMin": 6}]}]})[0]["champ"] == \
        "new_prescription_lines[0].dosages[0].intervalUnitId"


def test_types_et_listes_messages_francais():
    champs = {e["champ"]: e["message"] for e in _erreurs({"patient": {"gender": "X", "weight": "abc", "hepaticInsufficiency": "LOW", "dateOfBirth": "12/04/1990"}})}
    assert champs["patient.weight"] == "Doit être un nombre."
    assert "Homme (MALE)" in champs["patient.gender"] and "Modérée (MODERATE)" in champs["patient.hepaticInsufficiency"]
    assert "AAAA-MM-JJ" in champs["patient.dateOfBirth"]
    assert "entre 0.3 et 350" in _erreurs({"patient": {"weight": 500}})[0]["message"]


# ===========================================================================
# 4. Lignes de prescription et traitements en cours
# ===========================================================================

def test_ligne_complete_dosages_periode_ald():
    xml = _xml({"new_prescription_lines": [{
        "drugRef": 5001, "drugType": "UCD", "dose": "4", "unitId": 501, "duration": 1, "durationType": "MONTH", "frequencyType": "PER_DAY",
        "route": "vidal://route/" + "502", "indication": "503",
        "dosages": [{"dose": 1, "intervalMin": 6, "intervalMax": 6, "intervalUnitId": "41"}],
        "startDate": "2026-10-14", "endDate": "2026-11-14", "status": "ACTIVE", "groupType": "INFUSION", "ald": True, "aldCode": "ALD8",
    }]})
    ligne = ET.fromstring(xml.split("\n", 1)[1]).find("prescription-lines/prescription-line")
    assert [e.tag for e in ligne] == ["drug", "dose", "unitId", "duration", "durationType", "frequencyType", "routes", "indications",
                                      "dosages", "period", "status", "group", "aldStatus"]
    assert ligne.findtext("drug") == "vidal://ucd/5001" and ligne.findtext("routes/route") == "vidal://route/502"
    assert ligne.findtext("indications/indication") == "vidal://indication/503"
    assert ligne.findtext("dosages/dosage/unitId") == "501" and ligne.findtext("dosages/dosage/interval/unitId") == "41"
    assert ligne.findtext("period/startDate") == "2026-10-14T00:00:00" and ligne.findtext("period/endDate") == "2026-11-14T23:59:59"
    assert ligne.findtext("group/groupType") == "INFUSION"
    assert ligne.findtext("aldStatus/ald") == "true" and ligne.findtext("aldStatus/aldCode") == "ALD8"


def test_methode_1_groupe_denomination_commune_et_traitements_en_cours():
    xml = _xml({
        "current_treatments": [{"drugRef": "2957", "drugType": "COMMON_NAME_GROUP", "dose": 1, "unitId": "139", "frequencyType": "PER_DAY"}],
        "new_prescription_lines": [{"drugRef": "1498", "drugType": "VMP"}, {"drugRef": "25155", "drugType": "PACK"}, {"drugRef": "5387", "drugType": "PRESCRIBABLE"}],
    })
    lignes = ET.fromstring(xml.split("\n", 1)[1]).findall("prescription-lines/prescription-line")
    assert lignes[0].findtext("drugId") == "2957" and lignes[0].findtext("drugType") == "COMMON_NAME_GROUP"
    assert lignes[0].findtext("group/groupType") == "PREVIOUS_ORDER" and lignes[0].findtext("group/groupId") == "2"
    assert lignes[1].findtext("drug") == "vidal://vmp/1498" and lignes[1].findtext("group/groupType") == "SAME_ORDER"
    assert lignes[2].findtext("drug") == "vidal://package/25155" and lignes[3].findtext("drug") == "vidal://prescribable/5387"


def test_traitements_en_cours_depuis_ordonnances():
    ordonnances = [
        {"reference": "A", "date_creation": AUJOURDHUI - timedelta(days=3), "lignes": [
            {"designation": "MEDICAMENT 10", "vidal_id": "10", "duree": "7 jours"},   # en cours
            {"designation": "MEDICAMENT 11", "vidal_id": "11", "duree": "2 j"},       # terminé
            {"designation": "HORS VIDAL", "vidal_id": None, "duree": "7 jours"},      # ignoré
            {"designation": "MEDICAMENT 12", "vidal_id": "12", "duree": "si douleur"},  # durée inconnue : proposé non coché
        ]},
        {"reference": "B", "date_creation": AUJOURDHUI - timedelta(days=40), "lignes": [
            {"designation": "X", "vidal_id": "13", "donnees_vidal": {"startDate": _iso(40), "duration": 2, "durationType": "MONTH", "dose": 1, "unitId": "129"}},
            {"designation": "Y", "vidal_id": "14", "duree": "inconnue"},
        ]},
    ]
    resultat = {t["drugRef"]: t for t in lignes_traitements_en_cours(ordonnances)}
    assert set(resultat) == {"10", "12", "13"}
    assert resultat["10"]["fin_estimee"] == (AUJOURDHUI + timedelta(days=3)).isoformat() and resultat["10"]["coche_par_defaut"] is True
    assert resultat["10"]["endDate"] is None and (resultat["10"]["duration"], resultat["10"]["durationType"]) == (7, "DAY")
    assert resultat["12"]["coche_par_defaut"] is False
    assert resultat["13"]["unitId"] == "129" and resultat["13"]["groupType"] == "PREVIOUS_ORDER"
    assert interpreter_duree_texte("2 semaines") == (2, "WEEK") and interpreter_duree_texte("500 mg") is None


def test_traitements_en_cours_depuis_les_securisations_sawali():
    """(SAWALI) Les sécurisations précédentes tiennent lieu d'ordonnances ; un même médicament n'est proposé qu'une fois."""
    from datetime import datetime, timezone
    maintenant = datetime.now(timezone.utc)
    audits = [
        {"id": "aaaaaa-1", "created_at": maintenant - timedelta(days=1), "lignes_envoyees": [
            {"drugRef": "20", "label": "MED 20", "duration": 10, "durationType": "DAY", "startDate": _iso(1), "groupType": "SAME_ORDER", "groupId": 1},
            {"drugRef": "21", "label": "MED 21", "duration": 30, "durationType": "DAY", "groupType": "PREVIOUS_ORDER", "groupId": 2},
        ]},
        {"id": "bbbbbb-2", "created_at": maintenant - timedelta(days=2), "lignes_envoyees": [
            {"drugRef": "20", "label": "MED 20 (ancien)", "duration": 10, "durationType": "DAY", "groupType": "SAME_ORDER"},
        ]},
    ]
    ordonnances = ordonnances_depuis_audits(audits)
    assert [o["reference"] for o in ordonnances] == ["SEC-AAAAAA", "SEC-BBBBBB"]
    traitements = dedoublonner_traitements(lignes_traitements_en_cours(ordonnances))
    # La ligne déjà « traitement en cours » (PREVIOUS_ORDER) n'est pas une nouvelle ordonnance.
    assert [t["drugRef"] for t in traitements] == ["20"] and traitements[0]["label"] == "MED 20"
    assert traitements[0]["duration"] == 10 and traitements[0]["coche_par_defaut"] is True


# ===========================================================================
# 5. Divers (groupes DFG, lecture des alertes, référentiels JS, XLSX, code)
# ===========================================================================

def test_interpretation_dfg_selon_groupe():
    assert interpreter_dfg(80, 84) == {"pourcentage": 95.2, "niveau": "NORMAL", "libelle": "Normal"}
    assert interpreter_dfg(60, 84)["niveau"] == "LEGEREMENT_DIMINUE" and interpreter_dfg(45, 84)["niveau"] == "DIMINUE"
    assert interpreter_dfg(70, 74)["niveau"] == "NORMAL" and interpreter_dfg(70, 84)["niveau"] == "LEGEREMENT_DIMINUE"
    assert interpreter_dfg(70, 74, {"normal_pct": 100, "leger_pct": 80})["niveau"] == "LEGEREMENT_DIMINUE"
    assert interpreter_dfg(None, 84) is None


def test_lecture_alertes_ancres_et_non_securises():
    raw = ('<feed><vidal:maxPosologySeverity severity="LEVEL_4" urlSuffix="#menu_posology">risque lié à la posologie</vidal:maxPosologySeverity>'
           '<vidal:maxAllergySeverity severity="NO_ALERT">pas de risque</vidal:maxAllergySeverity>'
           '<entry vidal:categories="ALERT"><title>Médicament non sécurisé</title><vidal:alertType name="UNSECURIZED">Non sécurisé</vidal:alertType>'
           '<vidal:severity>INFO</vidal:severity></entry></feed>')
    analyse = parser_reponse_alertes(raw)
    assert analyse["summary"][0] == {"category": "maxPosologySeverity", "severity": "LEVEL_4", "label": "risque lié à la posologie", "anchor": "menu_posology"}
    assert analyse["summary"][1]["anchor"] is None and analyse["alerts"][0]["alert_type"] == "UNSECURIZED"


def test_referentiels_presents_cote_frontend():
    chemin_js = RACINE.parent / "frontend" / "src" / "lib" / "vidalReferentiels.js"
    if not chemin_js.exists():
        pytest.skip("frontend absent de cette copie du dépôt")
    js = chemin_js.read_text(encoding="utf-8")
    for referentiel in (R.SEXES, R.ALLAITEMENTS, R.INSUFFISANCES_HEPATIQUES, R.TYPES_DUREE, R.TYPES_FREQUENCE, R.TYPES_MEDICAMENT,
                        R.STATUTS_LIGNE, R.TYPES_GROUPE, R.UNITES_INTERVALLE, R.FORMES_GALENIQUES, R.ANCRES_RAPPORT_HTML,
                        R.RUBRIQUES_RAPPORT_HTML, R.INDICATEURS_DONNEES_PATIENT):
        for code in referentiel:
            assert re.search(rf"\b{re.escape(code)}\s*:", js), f"code {code} absent de vidalReferentiels.js"
    for cle in R.BORNES:
        assert cle in js, f"borne {cle} absente de vidalReferentiels.js"
    for g in GROUPES_DFG_DEFAUT:
        assert g["libelle"] in js


def test_aucune_uri_vidal_litterale_dans_le_code_du_lot():
    """« Rien ne doit être simulé ni venir des exemples de la documentation » :
    aucune référence VIDAL (vidal://<type>/<nombre>) écrite en dur."""
    motif = re.compile(r"vidal://[a-z_]+/(?:code/)?[0-9]")
    racine = RACINE.parent
    fichiers = list((RACINE / "vidal_v2").glob("*.py"))
    fichiers += [RACINE / "routes" / f for f in ("vidal_appels.py", "vidal_securisation.py", "vidal_patients.py", "vidal_validation.py")]
    front = racine / "frontend" / "src"
    if front.exists():
        fichiers += list((front / "components" / "vidal").glob("*.js*")) + [front / "lib" / "vidalReferentiels.js", front / "pages" / "portal" / "VidalSecurisation.jsx"]
    fautifs = [f"{f}:{n}" for f in fichiers if f.exists() for n, ligne in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if motif.search(ligne)]
    assert fautifs == []


def test_definitions_trois_patients_par_profil():
    patients = construire_patients_fictifs()
    assert len(PROFILS) >= 15 and len(patients) == 3 * len(PROFILS)
    for profil in PROFILS:
        assert len(profil["patients"]) == 3 and profil["prescriptions"]
    assert all(p["document"]["name"].startswith("FICTIF –") and p["document"]["est_fictif"] for p in patients)
    assert all(p["document"]["whatsapp_number"] is None for p in patients)
    assert all(p["document"]["profil_clinique"]["date_dernieres_regles"] for p in patients if p["code_fictif"].startswith("ENCEINTE"))
    assert "vidal://" not in str(patients)


def test_classeur_xlsx_sans_dependance():
    contenu = classeur_xlsx("Feuille", ["N°", "Texte"], [[1, "a < b & c"], [2, None]])
    with zipfile.ZipFile(io.BytesIO(contenu)) as archive:
        assert {"[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"} <= set(archive.namelist())
        feuille = archive.read("xl/worksheets/sheet1.xml").decode()
    ET.fromstring(feuille)  # XML bien formé
    assert "a &lt; b &amp; c" in feuille and "<v>1</v>" in feuille


def test_comparaison_des_versions_du_profil():
    v1 = valeurs_depuis_patient({"poids_kg": 62.0, "allergies": [{"label": "A", "ref": "vidal://allergy/" + "1"}]})
    assert {"poids_kg", "allergies"} <= set(champs_modifies(None, v1))
    v2 = valeurs_depuis_patient({"poids_kg": 62.0, "allergies": [{"label": "A", "ref": "vidal://allergy/" + "1"}]})
    assert champs_modifies(v1, v2) == []
    assert champs_modifies(v1, valeurs_depuis_patient({"poids_kg": 63.5})) == ["poids_kg", "allergies"]
    # Les SA sont recalculées (non comparées) : même DDR, jours différents -> aucun changement.
    ddr = (AUJOURDHUI - timedelta(days=70)).isoformat()
    a = valeurs_depuis_patient({"date_dernieres_regles": ddr}, reference=AUJOURDHUI)
    b = valeurs_depuis_patient({"date_dernieres_regles": ddr}, reference=AUJOURDHUI + timedelta(days=7))
    assert a["semaines_amenorrhee"] == 10 and b["semaines_amenorrhee"] == 11 and champs_modifies(a, b) == []


# ===========================================================================
# 6. Endpoints (MongoDB local, API VIDAL simulée)
# ===========================================================================

MEDECIN = {"id": "lot56_med1", "email": "medecin1@exemple.test", "role": "medecin", "parent_client_id": "lot56_cli1", "account_status": "active"}
MEDECIN_2 = {"id": "lot56_med2", "email": "medecin2@exemple.test", "role": "medecin", "parent_client_id": "lot56_cli1", "account_status": "active"}
CLIENT = {"id": "lot56_cli1", "email": "client1@exemple.test", "role": "client", "account_status": "active", "features": {"vidal_enabled": True}}

REPONSE_ALERTES = (
    '<feed xmlns:vidal="http://api.vidal.net/-/spec/vidal-api/1.0/">'
    '<vidal:maxPregnancySeverity severity="LEVEL_3" urlSuffix="#menu_pregnancy">Risque grossesse</vidal:maxPregnancySeverity>'
    '<entry vidal:categories="ALERT"><title>Contre-indication grossesse</title><content>Risque pendant la grossesse</content>'
    '<vidal:alertType name="PREGNANCY">Grossesse</vidal:alertType><vidal:severity>LEVEL_3</vidal:severity></entry></feed>'
)
REPONSE_ALERTE_NIVEAU_2 = (
    '<feed xmlns:vidal="http://api.vidal.net/-/spec/vidal-api/1.0/"><vidal:maxSeverity severity="LEVEL_2">Précaution</vidal:maxSeverity>'
    '<entry vidal:categories="ALERT"><title>Précaution</title><vidal:severity>LEVEL_2</vidal:severity></entry></feed>'
)
# Réponses des calculateurs au format décrit par la MI (§5.2.2.3 à 5.2.2.5), réduites à l'essentiel, valeurs inventées.
REPONSE_COCKROFT_GAULT = (
    '<feed><entry vidal:categories="CREATININE_CLEARANCE"><vidal:estimatedCreatinineClearance unit="ml/min">101.3</vidal:estimatedCreatinineClearance>'
    '<vidal:calculationMethod>Cockroft &amp; Gault</vidal:calculationMethod><vidal:renalInsufficiency>NONE</vidal:renalInsufficiency></entry></feed>'
)
REPONSE_FONCTION_RENALE = (
    '<feed><entry vidal:categories="GLOMERULAR_FILTRATION_RATE">'
    '<vidal:nonAfroAmerican calculationMethod="CKD-EPI" kdigoGfrStage="G2" unit="ml/min/1,73m²">81.48</vidal:nonAfroAmerican>'
    '<vidal:afroAmerican calculationMethod="CKD-EPI" kdigoGfrStage="G1" unit="ml/min/1,73m²">93.93</vidal:afroAmerican></entry>'
    '<entry vidal:categories="SERUM_CREATININE"><vidal:serumCreatinine unit="µmol/L">85.8</vidal:serumCreatinine></entry></feed>'
)


@pytest.fixture()
def ctx(monkeypatch):
    """Application réduite aux routes VIDAL ; base MongoDB jetable ; VIDAL simulé."""
    nom_base = f"test_lot56_{time.time_ns()}"
    synchrone = MongoClient(os.environ["MONGO_URL"])
    base = synchrone[nom_base]
    base.settings.insert_one({
        "_id": "global", "vidal_enabled": True, "vidal_mode": "test", "vidal_quota_per_user_per_day": 0,
        "vidal_test_base_url": URL_TEST, "vidal_test_app_id": ID_TEST, "vidal_test_app_key": CLE_TEST,
        "vidal_prod_base_url": URL_PROD, "vidal_prod_app_id": ID_PROD, "vidal_prod_app_key": CLE_PROD,
    })
    base.users.insert_many([dict(CLIENT), dict(MEDECIN), dict(MEDECIN_2)])
    appels_v2._index_ok["fait"] = False

    appels: list = []
    reponses: dict = {}
    specifiques: dict = {}

    def copie(reponse: httpx.Response) -> httpx.Response:
        """Réponse neuve à chaque appel, avec sa durée (le client SAWALI lit `elapsed`)."""
        neuve = httpx.Response(reponse.status_code, content=reponse.content, headers={"content-type": "application/atom+xml"})
        neuve.elapsed = timedelta(milliseconds=5)
        return neuve

    def repondre(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        q = requete.url.params.get("q")
        for (chemin, terme), reponse in specifiques.items():
            if requete.url.path == chemin and (terme is None or terme == q):
                return copie(reponse)
        for suffixe, reponse in reponses.items():
            if requete.url.path.endswith(suffixe):
                return copie(reponse)
        return copie(httpx.Response(404, text="inconnu"))

    vrai_client = httpx.AsyncClient

    def client_simule(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(repondre)
        return vrai_client(*args, **kwargs)

    monkeypatch.setattr(module_vidal.httpx, "AsyncClient", client_simule)

    utilisateur = dict(MEDECIN)

    async def utilisateur_courant():
        return utilisateur

    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[nom_base]
    app = FastAPI()
    api = APIRouter(prefix="/api")
    attach_vidal_fiche_routes(api=api, db=db, get_current_user=utilisateur_courant)
    attach_vidal_securisation_routes(api=api, db=db, get_current_user=utilisateur_courant)
    attach_vidal_patients_routes(api=api, db=db, get_current_user=utilisateur_courant)
    attach_vidal_validation_routes(api=api, db=db, get_current_user=utilisateur_courant)
    app.include_router(api)
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(client=client, base=base, appels=appels, reponses=reponses, specifiques=specifiques, utilisateur=utilisateur)
    finally:
        synchrone.drop_database(nom_base)  # base jetable supprimée même si le test échoue


def _hors_validation(ctx):
    """Désactive le mode validation de l'établissement (comportement « production réelle »)."""
    ctx.base.vidal_validation_config.insert_one({"scope_uid": CLIENT["id"], "mode_validation": False})


def _comme(ctx, utilisateur: dict):
    ctx.utilisateur.clear()
    ctx.utilisateur.update(utilisateur)


def _patient(ctx, nom="PATIENT REEL", **profil) -> str:
    r = ctx.client.post("/api/vidal/patients", json={"name": nom, "profil_clinique": profil or None})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_endpoint_analyse_422_en_francais(ctx):
    _hors_validation(ctx)
    r = ctx.client.post("/api/vidal/securisation/analyze", json={"patient": {"gender": "FEMALE", "weeksOfAmenorrhea": 43}, "new_prescription_lines": [LIGNE]})
    assert r.status_code == 422 and r.json()["detail"]["erreurs"][0]["champ"] == "patient.weeksOfAmenorrhea"
    assert not ctx.appels  # rien n'est envoyé à VIDAL


def test_endpoint_analyse_envoie_le_xml_valide_et_garde_l_instantane(ctx):
    _hors_validation(ctx)
    ctx.reponses["/alerts/full"] = httpx.Response(200, text=REPONSE_ALERTE_NIVEAU_2)
    pid = _patient(ctx)
    r = ctx.client.post("/api/vidal/securisation/analyze", json={
        "patient": {"dateOfBirth": "1990-01-01", "gender": "FEMALE", "weeksOfAmenorrhea": 20, "creatin": 95, "serumCreatinine": 70,
                    "glomerularFiltrationRate": 101.2, "breastFeeding": "NONE",
                    # Groupe de référence du DFG : aide locale, ne doit JAMAIS partir chez VIDAL.
                    "groupeReferenceDfg": "groupe_b"},
        "new_prescription_lines": [{"drugRef": "900001", "label": "MEDICAMENT TEST", "dose": 2, "unitId": "7", "duration": 3,
                                    "durationType": "DAY", "frequencyType": "PER_DAY"}],
        "patient_id": pid, "groupe_reference_dfg": "groupe_b",
    })
    assert r.status_code == 200, r.text
    assert r.json()["analyse"]["alerts"][0]["severity"] == "LEVEL_2" and r.json()["parsed"] == r.json()["analyse"]
    requete = ctx.appels[0]
    corps = requete.content.decode()
    # Hors mode validation : configuration du mode choisi (ici test) dans AdminSettings.
    assert str(requete.url).startswith(URL_TEST + "/alerts/full?") and requete.url.params["app_key"] == CLE_TEST
    assert requete.headers["content-type"].startswith("text/xml")
    assert "<weeksOfAmenorrhea>20</weeksOfAmenorrhea>" in corps and "<serumCreatinine>70.00</serumCreatinine>" in corps
    assert "groupe" not in corps.lower() and "PATIENT REEL" not in corps and pid not in corps
    instantane = ctx.base.vidal_prescription_audit.find_one({"id": r.json()["id"]})
    assert instantane["source"] == "securisation_v2" and instantane["patient_id"] == pid and instantane["patient_name"] == "PATIENT REEL"
    assert instantane["patient_envoye"]["creatin"] == "95" and instantane["patient_envoye"]["glomerularFiltrationRate"] == "101.20"
    assert instantane["patient_envoye"]["breastFeedingStartDate"] is None  # balise nil
    assert all("groupe" not in str(k).lower() for k in instantane["patient_envoye"])
    assert instantane["groupe_reference_dfg_local"] == "groupe_b" and instantane["resume_gravites"] == {"LEVEL_2": 1}
    assert instantane["lignes_envoyees"][0]["label"] == "MEDICAMENT TEST"
    # Historique « toutes sécurisations » existant : toujours alimenté.
    assert ctx.client.get("/api/vidal/securisation/history").json()["results"][0]["id"] == r.json()["id"]


def test_endpoint_rapport_html(ctx):
    _hors_validation(ctx)
    ctx.reponses["/alerts/full/html"] = httpx.Response(200, text='<html><a id="menu_posology"></a></html>')
    r = ctx.client.post("/api/vidal/securisation/rapport-html", json={"patient": {"gender": "MALE"}, "new_prescription_lines": [LIGNE]})
    assert r.status_code == 200 and "menu_posology" in r.text and r.headers["content-type"].startswith("text/html")
    corps = ctx.appels[0].content.decode()
    assert "alert-types" not in corps and "alert-display-types" not in corps  # rapport exhaustif
    ctx.client.post("/api/vidal/securisation/rapport-html", json={"patient": {}, "new_prescription_lines": [LIGNE], "alert_display_types": ["POSOLOGY", "ALLERGY"]})
    assert ("<alert-display-types><alert-display-type>POSOLOGY</alert-display-type><alert-display-type>ALLERGY</alert-display-type>"
            "</alert-display-types>") in ctx.appels[1].content.decode()
    assert ctx.client.post("/api/vidal/securisation/rapport-html", json={"patient": {}, "new_prescription_lines": [LIGNE], "alert_display_types": ["TOUT"]}).status_code == 422


def test_endpoint_fonction_renale_repli_local(ctx):
    _hors_validation(ctx)
    r = ctx.client.post("/api/vidal/calculateurs/fonction-renale", json={"dateOfBirth": "1966-01-01", "gender": "MALE", "weight": 80, "serumCreatinine": 70})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["sources"] == {"creatin": "local", "serumCreatinine": "saisie", "glomerularFiltrationRate": "local"}
    assert d["serumCreatinine"] == 70 and isinstance(d["creatin"], int)
    assert [a.url.path for a in ctx.appels] == ["/rest/api/calculators/ccreat/cockroft-gault", "/rest/api/calculators/renal-function"]


def test_endpoint_fonction_renale_calculateurs_vidal(ctx):
    _hors_validation(ctx)
    ctx.reponses["/calculators/ccreat/cockroft-gault"] = httpx.Response(200, text=REPONSE_COCKROFT_GAULT)
    ctx.reponses["/calculators/renal-function"] = httpx.Response(200, text=REPONSE_FONCTION_RENALE)
    d = ctx.client.post("/api/vidal/calculateurs/fonction-renale", json={
        "dateOfBirth": "1966-01-01", "gender": "MALE", "weight": 80, "height": 175, "serumCreatinine": 0.8, "serumCreatinineUnit": "mg_dl",
        "groupeReferenceDfg": "groupe_b",
    }).json()
    assert d["creatin_calculee"] == 101.3 and d["creatin"] == 101 and d["insuffisanceRenale"] == "NONE"
    # Seul le DFG SANS coefficient ethnique est retenu.
    assert d["glomerularFiltrationRate"] == 81.48 and d["stadeKdigo"] == "G2"
    assert d["serumCreatinine"] == pytest.approx(70.72, abs=0.01)  # 0,8 mg/dL × 88,4
    corps_cg, corps_rf = (a.content.decode() for a in ctx.appels)
    assert corps_cg.endswith("<patient><dateOfBirth>1966-01-01</dateOfBirth><gender>MALE</gender><height>175</height><weight>80</weight>"
                             "<serumCreatinine>70.72</serumCreatinine></patient>")
    assert "<patient><serumCreatinine>70.72</serumCreatinine><dateOfBirth>1966-01-01</dateOfBirth>" in corps_rf
    assert all("groupe" not in a.content.decode().lower() for a in ctx.appels)
    # Depuis une clairance saisie : créatininémie et DFG lus dans VIDAL.
    ctx.appels.clear()
    d = ctx.client.post("/api/vidal/calculateurs/fonction-renale", json={"dateOfBirth": "2000-03-20", "gender": "FEMALE", "weight": 73.17, "creatin": 102}).json()
    assert d["serumCreatinine"] == 85.8 and d["glomerularFiltrationRate"] == 81.48 and d["sources"]["serumCreatinine"] == "vidal"
    assert "<patient><creatin>102</creatin><dateOfBirth>2000-03-20</dateOfBirth><gender>FEMALE</gender><weight>73.17</weight></patient>" in ctx.appels[0].content.decode()
    # Sexe indéterminé : formule sexuée impossible -> 422.
    r = ctx.client.post("/api/vidal/calculateurs/fonction-renale", json={"dateOfBirth": "1966-01-01", "gender": "UNKNOWN", "weight": 80, "serumCreatinine": 70})
    assert r.status_code == 422 and r.json()["detail"]["erreurs"][0]["champ"] == "gender"


def test_endpoint_recherche_filtre_par_forme(ctx):
    ctx.reponses["/products"] = httpx.Response(200, text=(
        '<feed><entry><title>PRODUIT A 1000 mg cp</title><vidal:id>1</vidal:id><vidal:safetyAlert>true</vidal:safetyAlert>'
        '<vidal:galenicForm vidalId="59">comprimé</vidal:galenicForm></entry>'
        "<entry><title>PRODUIT A 2,4 % susp buv</title><vidal:id>2</vidal:id></entry>"
        "<entry><title>PRODUIT A 500 mg gél</title><vidal:id>3</vidal:id></entry></feed>"
    ))
    titres = lambda forme: [r["title"] for r in ctx.client.get("/api/vidal/search/parsed", params={"q": "produit", "forme": forme}).json()["results"]]
    assert titres("comp") == ["PRODUIT A 1000 mg cp"] and titres("susp_buv") == ["PRODUIT A 2,4 % susp buv"] and titres("gel") == ["PRODUIT A 500 mg gél"]
    tous = ctx.client.get("/api/vidal/search/parsed", params={"q": "produit"}).json()["results"]
    assert len(tous) == 3 and {"title", "vidal_id", "vmp_id"} <= set(tous[0])  # champs historiques conservés
    par_id = ctx.client.get("/api/vidal/search/parsed", params={"q": "produit", "forme": "59"}).json()["results"]
    assert [r["title"] for r in par_id] == ["PRODUIT A 1000 mg cp"] and par_id[0]["safety_alert"] is True


def test_endpoint_listes_par_type_de_medicament(ctx):
    _hors_validation(ctx)
    ctx.reponses["/package/25155/units"] = httpx.Response(200, text="<feed><entry><title>sachet</title><vidal:id>57</vidal:id></entry></feed>")
    ctx.reponses["/package/25155/routes"] = httpx.Response(200, text=(
        '<feed><entry vidal:categories="ROUTE"><title>rectale</title><vidal:id>40</vidal:id><vidal:ranking>1</vidal:ranking><vidal:outOfSPC>true</vidal:outOfSPC></entry>'
        '<entry vidal:categories="ROUTE"><title>orale</title><vidal:id>38</vidal:id><vidal:ranking>0</vidal:ranking><vidal:outOfSPC>false</vidal:outOfSPC></entry></feed>'
    ))
    ctx.reponses["/package/25155/indicators"] = httpx.Response(200, text='<feed><entry><vidal:indicator vidalId="26">Age</vidal:indicator><vidal:indicator vidalId="27">Poids</vidal:indicator></entry></feed>')
    assert ctx.client.get("/api/vidal/medicament/PACK/25155/units").json()["units"] == [{"id": "57", "label": "sachet"}]
    voies = ctx.client.get("/api/vidal/medicament/PACK/25155/routes").json()["routes"]
    assert [(v["label"], v["hors_amm"]) for v in voies] == [("orale", False), ("rectale", True)]  # tri par rang VIDAL
    assert ctx.client.get("/api/vidal/medicament/PACK/25155/indicators").json()["indicators"] == [{"id": "26", "label": "Age"}, {"id": "27", "label": "Poids"}]
    assert ctx.appels[0].url.path == "/rest/api/package/25155/units"
    # Deuxième lecture : servie par le cache (aucun nouvel appel).
    nombre = len(ctx.appels)
    ctx.client.get("/api/vidal/medicament/PACK/25155/units")
    assert len(ctx.appels) == nombre
    assert ctx.client.get("/api/vidal/medicament/COMMON_NAME_GROUP/1/units").status_code == 400
    assert ctx.client.get("/api/vidal/medicament/PRODUCT/999/units").status_code == 502  # VIDAL en erreur


def test_recherche_allergies_classes_molecules_et_ald(ctx):
    _hors_validation(ctx)
    ctx.reponses["/allergies"] = httpx.Response(200, text=(
        '<feed><entry vidal:categories="ALLERGY"><title>Classe d&amp;apos;allergie test</title><id>vidal://allergy/7001</id><vidal:id>7001</vidal:id></entry>'
        '<entry vidal:categories="MOLECULE"><title>substance test</title><id>vidal://molecule/7002</id><vidal:id>7002</vidal:id></entry></feed>'
    ))
    r = ctx.client.get("/api/vidal/referential/search", params={"kind": "allergy", "q": "test"}).json()["results"]
    assert [(x["ref"], x["type"]) for x in r] == [("vidal://allergy/7001", "ALLERGY"), ("vidal://molecule/7002", "MOLECULE")]
    assert r[0]["label"] == "Classe d'allergie test"  # entités décodées
    assert [x["ref"] for x in ctx.client.get("/api/vidal/referential/search", params={"kind": "molecule", "q": "test"}).json()["results"]] == ["vidal://molecule/7002"]
    ctx.reponses["/alds"] = httpx.Response(200, text='<feed><entry vidal:categories="ALD"><title>ALD TEST</title><id>vidal://ald/8</id><vidal:id>8</vidal:id><vidal:code>08</vidal:code></entry></feed>')
    assert ctx.client.get("/api/vidal/referential/search", params={"kind": "ald", "q": "test"}).json()["results"] == [
        {"label": "ALD TEST", "ref": "vidal://ald/8", "type": "ALD", "code": "08"}]


def test_endpoint_groupes_dfg(ctx):
    defaut = ctx.client.get("/api/vidal/groupes-dfg").json()
    assert [(g["libelle"], g["valeur_normale"], g["par_defaut"]) for g in defaut["groupes"]] == [
        ("Groupe A (référence 84)", 84.0, True), ("Groupe B (référence 74)", 74.0, False)]
    assert defaut["seuils"] == {"normal_pct": 90.0, "leger_pct": 60.0} and defaut["modifiable"] is False
    nouvelle = {"groupes": [*defaut["groupes"], {"id": "groupe_c", "libelle": "Groupe C", "valeur_normale": 90, "actif": True, "ordre": 3, "par_defaut": False}],
                "seuils": {"normal_pct": 85, "leger_pct": 55}}
    assert ctx.client.put("/api/vidal/groupes-dfg", json=nouvelle).status_code == 403  # médecin : lecture seule
    _comme(ctx, CLIENT)
    assert ctx.client.put("/api/vidal/groupes-dfg", json=nouvelle).status_code == 200
    # Le paramétrage du gestionnaire s'applique au médecin de son établissement.
    _comme(ctx, MEDECIN)
    assert [g["libelle"] for g in ctx.client.get("/api/vidal/groupes-dfg").json()["groupes"]][-1] == "Groupe C"
    _comme(ctx, CLIENT)
    invalide = {"groupes": [{**nouvelle["groupes"][0], "valeur_normale": 0}, {**nouvelle["groupes"][1], "par_defaut": True}], "seuils": {"normal_pct": 50, "leger_pct": 60}}
    r = ctx.client.put("/api/vidal/groupes-dfg", json=invalide)
    assert r.status_code == 422 and {"groupes[0].valeur_normale", "groupes", "seuils"} <= {e["champ"] for e in r.json()["detail"]["erreurs"]}


def test_profil_clinique_versions_seulement_si_changement(ctx):
    pid = _patient(ctx)
    url = f"/api/vidal/patients/{pid}/profil-clinique"
    r = ctx.client.put(url, params={"origine": "securisation"}, json={"poids_kg": 62, "taille_cm": 165, "derniere_creatininemie_umol_l": 70,
                                                                      "groupe_reference_dfg": "groupe_b", "sexe": "FEMALE"})
    assert r.json()["version_creee"] is True
    assert set(r.json()["champs_modifies"]) >= {"poids_kg", "taille_cm", "creatininemie_umol_l", "groupe_reference_dfg", "sexe"}
    # Même saisie : aucune nouvelle version.
    r = ctx.client.put(url, json={"poids_kg": 62, "taille_cm": 165, "derniere_creatininemie_umol_l": 70, "groupe_reference_dfg": "groupe_b"})
    assert r.json() == {"statut": "profil clinique enregistré", "version_creee": False, "champs_modifies": []}
    # Changement du poids et effacement du groupe : nouvelle version, rien d'écrasé.
    r = ctx.client.put(url, json={"poids_kg": 63.5, "groupe_reference_dfg": None})
    assert r.json()["champs_modifies"] == ["poids_kg", "groupe_reference_dfg"]
    versions = list(ctx.base.vidal_historique_profil_clinique.find({"patient_id": pid}).sort("date", 1))
    assert [v["numero_version"] for v in versions] == [1, 2]
    assert versions[0]["valeurs"]["poids_kg"] == 62 and versions[1]["valeurs"]["poids_kg"] == 63.5
    assert versions[0]["origine"] == "securisation" and versions[0]["login"] == MEDECIN["email"]
    assert versions[0]["valeurs"]["valeur_normale_dfg_groupe"] == 74.0  # référence du groupe B mémorisée avec la version
    assert ctx.base.vidal_patients.find_one({"id": pid})["profil_clinique"]["poids_kg"] == 63.5
    # Contrôles du modèle (valeurs autorisées) et cloisonnement par praticien.
    assert ctx.client.put(url, json={"sexe": "HOMME"}).status_code == 422
    _comme(ctx, MEDECIN_2)
    assert ctx.client.put(url, json={"poids_kg": 70}).status_code == 404
    assert ctx.client.get(f"/api/vidal/patients/{pid}/historique-clinique").status_code == 404


def test_enregistrement_patient_avec_profil_et_ancien_format(ctx):
    r = ctx.client.post("/api/vidal/patients", json={"name": "NOUVEAU", "profil_clinique": {"poids_kg": 80, "date_naissance": "1980-05-01"}})
    assert r.json()["version_creee"] is True and r.json()["profil_clinique"]["date_naissance"] == "1980-05-01"
    # Patient enregistré AVANT le lot 56 (ancien `profile`) : repris sans rien inventer.
    ctx.base.vidal_patients.insert_one({"id": "ancien1", "user_id": MEDECIN["id"], "name": "ANCIEN",
                                        "profile": {"dateOfBirth": "1970-01-01", "gender": "MALE", "weight": "75", "creatinine": ""}})
    ctx.client.put("/api/vidal/patients/ancien1/profil-clinique", json={"taille_cm": 180})
    clinique = ctx.base.vidal_patients.find_one({"id": "ancien1"})["profil_clinique"]
    assert (clinique["date_naissance"], clinique["sexe"], clinique["poids_kg"], clinique["taille_cm"]) == ("1970-01-01", "MALE", 75.0, 180)
    assert clinique["derniere_creatininemie_umol_l"] is None


def test_historique_clinique_instantanes_et_pdf(ctx):
    _hors_validation(ctx)
    ctx.reponses["/alerts/full"] = httpx.Response(200, text=REPONSE_ALERTE_NIVEAU_2)
    pid = _patient(ctx, poids_kg=62, derniere_creatininemie_umol_l=70, dfg_ml_min_173=98)
    ctx.client.put(f"/api/vidal/patients/{pid}/profil-clinique", json={"poids_kg": 61})
    r = ctx.client.post("/api/vidal/securisation/analyze", json={"patient": {"gender": "MALE"}, "new_prescription_lines": [LIGNE], "patient_id": pid})
    historique = ctx.client.get(f"/api/vidal/patients/{pid}/historique-clinique").json()
    assert len(historique["versions"]) == 2 and len(historique["securisations"]) == 1
    assert "analyse" not in historique["securisations"][0] and historique["securisations"][0]["resume_gravites"] == {"LEVEL_2": 1}
    detail = ctx.client.get(f"/api/vidal/patients/{pid}/historique-clinique/securisations/{r.json()['id']}").json()
    assert detail["analyse"]["alerts"][0]["severity"] == "LEVEL_2" and detail["lignes_envoyees"][0]["label"] == "MEDICAMENT TEST"
    autre = _patient(ctx, nom="AUTRE")
    assert ctx.client.get(f"/api/vidal/patients/{autre}/historique-clinique/securisations/{r.json()['id']}").status_code == 404
    pdf = ctx.client.get(f"/api/vidal/patients/{pid}/historique-clinique/pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")


def test_traitements_en_cours_apres_une_securisation(ctx):
    _hors_validation(ctx)
    ctx.reponses["/alerts/full"] = httpx.Response(200, text=REPONSE_ALERTE_NIVEAU_2)
    pid = _patient(ctx)
    ctx.client.post("/api/vidal/securisation/analyze", json={"patient": {"gender": "MALE"}, "patient_id": pid, "new_prescription_lines": [
        {"drugRef": "900002", "label": "TRAITEMENT LONG", "duration": 1, "durationType": "MONTH", "startDate": _iso(2)},
        {"drugRef": "900003", "label": "TRAITEMENT COURT", "duration": 1, "durationType": "DAY", "startDate": _iso(5)},
    ]})
    traitements = ctx.client.get(f"/api/vidal/securisation/traitements-en-cours/{pid}").json()["traitements"]
    assert [t["drugRef"] for t in traitements] == ["900002"]  # le traitement d'un jour est terminé
    assert traitements[0]["groupType"] == "PREVIOUS_ORDER" and traitements[0]["coche_par_defaut"] is True
    assert traitements[0]["endDate"] is None and traitements[0]["fin_estimee"]  # fin estimée jamais transmise
    _comme(ctx, MEDECIN_2)
    assert ctx.client.get(f"/api/vidal/securisation/traitements-en-cours/{pid}").status_code == 404


# ===========================================================================
# 7. Mode « Validation VIDAL » (activé par défaut)
# ===========================================================================

def _fictif(ctx, code: str) -> dict:
    return ctx.base.vidal_patients.find_one({"code_fictif": code, "user_id": MEDECIN["id"]})


def _preparer_recherches(ctx):
    """Réponses VIDAL simulées pour la génération des patients fictifs (valeurs inventées)."""
    ctx.specifiques[("/rest/api/products", "warfarine")] = httpx.Response(200, text=(
        '<feed><entry><title>PRODUIT A 2 MG CP</title><vidal:id>9101</vidal:id></entry>'
        '<entry><title>PRODUIT A 5 MG CP</title><vidal:id>9102</vidal:id></entry></feed>'))
    ctx.specifiques[("/rest/api/products", "amiodarone")] = httpx.Response(200, text='<feed><entry><title>PRODUIT B 200 MG CP</title><vidal:id>9201</vidal:id></entry></feed>')
    ctx.specifiques[("/rest/api/products", "paracétamol")] = httpx.Response(200, text='<feed><entry><title>PRODUIT C 500 MG CP</title><vidal:id>9301</vidal:id></entry></feed>')


def test_vrai_patient_aucune_requete_sortante(ctx):
    pid = _patient(ctx)
    r = ctx.client.post("/api/vidal/securisation/analyze", json={"patient": {"gender": "MALE"}, "new_prescription_lines": [LIGNE], "patient_id": pid})
    assert r.status_code == 403 and r.json()["detail"] == appels_v2.MESSAGE_PATIENT_NON_FICTIF
    # Sans patient identifié non plus (impossible de prouver qu'il est fictif).
    assert ctx.client.post("/api/vidal/securisation/analyze", json={"patient": {}, "new_prescription_lines": [LIGNE]}).status_code == 403
    assert ctx.client.post("/api/vidal/securisation/rapport-html", json={"patient": {}, "new_prescription_lines": [LIGNE], "patient_id": pid}).status_code == 403
    # Calculateur rénal : refusé (403), AUCUN calcul local de repli en mode validation.
    r = ctx.client.post("/api/vidal/calculateurs/fonction-renale", json={"dateOfBirth": "1966-01-01", "gender": "MALE", "weight": 80, "serumCreatinine": 70, "patient_id": pid})
    assert r.status_code == 403 and "creatin" not in r.json()
    assert ctx.appels == [] and ctx.base.vidal_journal_validation.count_documents({}) == 0
    assert ctx.base.vidal_prescription_audit.count_documents({}) == 0
    # Les appels SANS données patient restent autorisés, partent en PRODUCTION et sont journalisés.
    assert ctx.client.get("/api/vidal/referential/search", params={"kind": "pathology", "q": "asthme"}).status_code == 502  # 404 simulé
    assert len(ctx.appels) == 1 and str(ctx.appels[0].url).startswith(URL_PROD) and ctx.appels[0].url.params["app_id"] == ID_PROD
    assert ctx.base.vidal_journal_validation.count_documents({}) == 1


def test_generateur_idempotent_avec_versions_et_traitements(ctx):
    _preparer_recherches(ctx)
    bilan = ctx.client.post("/api/vidal/validation/patients-fictifs").json()
    total = 3 * len(PROFILS)
    assert {k: bilan[k] for k in ("crees", "remis_a_neuf", "versions_creees", "ordonnances_fictives", "vidal_interroge")} == {
        "crees": total, "remis_a_neuf": 0, "versions_creees": total, "ordonnances_fictives": 3, "vidal_interroge": True}
    assert bilan["references_trouvees"] >= 1 and bilan["references_a_choisir"] >= 1 and bilan["references_a_rechercher"] >= 1
    bilan = ctx.client.post("/api/vidal/validation/patients-fictifs").json()
    assert (bilan["crees"], bilan["remis_a_neuf"], bilan["versions_creees"], bilan["ordonnances_fictives"]) == (0, total, 0, 3)
    assert ctx.base.vidal_patients.count_documents({"est_fictif": True}) == total
    # Remise à neuf après modification : nouvelle version de l'historique.
    homme = _fictif(ctx, "HOMME-1")
    ctx.client.put(f"/api/vidal/patients/{homme['id']}/profil-clinique", json={"poids_kg": 99})
    assert ctx.client.post("/api/vidal/validation/patients-fictifs").json()["versions_creees"] == 1
    # Prescriptions de test : produit trouvé repris EXACTEMENT de VIDAL, sinon « à rechercher ».
    test_homme = {t["recherche"]: t["resolution"] for t in _fictif(ctx, "HOMME-1")["prescriptions_test_validation"]}
    assert test_homme["paracétamol"] == {"statut": "trouve", "reference": {"label": "PRODUIT C 500 MG CP", "ref": "vidal://product/9301", "vidal_id": "9301"}}
    assert test_homme["amoxicilline"]["statut"] == "a_rechercher"
    # Traitements en cours du polymédiqué : lignes à rapprocher de VIDAL.
    poly = _fictif(ctx, "POLYMEDIQUE-1")["id"]
    warfarine, amiodarone, metformine = ctx.client.get(f"/api/vidal/securisation/traitements-en-cours/{poly}").json()["traitements"]
    assert warfarine["a_rapprocher"] and warfarine["statut_reference"] == "a_choisir"
    assert [c["ref"] for c in warfarine["candidats_vidal"]] == ["vidal://product/9101", "vidal://product/9102"]
    assert amiodarone["drugRef"] == "9201" and amiodarone["label"] == "PRODUIT B 200 MG CP" and not amiodarone["a_rapprocher"]
    assert metformine["drugRef"] is None and metformine["statut_reference"] == "a_rechercher" and not metformine["coche_par_defaut"]
    # Les patients fictifs sont ceux du praticien qui les a générés.
    _comme(ctx, MEDECIN_2)
    assert ctx.client.get("/api/vidal/validation/patients-fictifs").json()["patients"] == []


def test_patient_fictif_envoye_en_production_sans_donnees_identifiantes_et_journal(ctx):
    ctx.client.post("/api/vidal/validation/patients-fictifs")
    ctx.reponses["/alerts/full"] = httpx.Response(200, text=REPONSE_ALERTES)
    enceinte = _fictif(ctx, "ENCEINTE-3")
    r = ctx.client.post("/api/vidal/securisation/analyze", json={
        "patient": {"dateOfBirth": "1992-01-01", "gender": "FEMALE", "weeksOfAmenorrhea": 34, "weight": 75,
                    "name": enceinte["name"], "whatsapp_number": "+226 70 00 00 00", "id": enceinte["id"]},
        "new_prescription_lines": [LIGNE], "patient_id": enceinte["id"], "patient_name": enceinte["name"], "groupe_reference_dfg": "groupe_b",
    })
    assert r.status_code == 200, r.text
    requete = ctx.appels[-1]
    assert str(requete.url).startswith(URL_PROD + "/alerts/full?")  # production, jamais la sandbox
    corps = requete.content.decode()
    for interdit in ("FICTIF", "+226", enceinte["id"], "groupe"):
        assert interdit not in corps
    entree = ctx.base.vidal_journal_validation.find_one({"type_appel": "Sécurisation (alertes structurées)"})
    assert entree["url"].startswith(URL_PROD + "/alerts/full?") and "app_id=***" in entree["url"] and "app_key=***" in entree["url"]
    assert entree["corps"] == corps and entree["statut_http"] == 200 and entree["reponse"] == REPONSE_ALERTES
    assert entree["profil"].startswith("Femme enceinte") and entree["patient_libelle"] == enceinte["name"]
    assert entree["resume_gravites"] == {"LEVEL_3": 1} and "Alerte attendue « grossesse » présente" in entree["observations_auto"]
    assert entree["date_locale"] and isinstance(entree["duree_ms"], int) and entree["scope_uid"] == CLIENT["id"]
    # Aucun secret stocké, nulle part dans le journal.
    for e in ctx.base.vidal_journal_validation.find({}):
        assert ID_PROD not in str(e) and CLE_PROD not in str(e)
    # L'instantané est rattaché au patient fictif (historique clinique : 1 version + 1 sécurisation).
    historique = ctx.client.get(f"/api/vidal/patients/{enceinte['id']}/historique-clinique").json()
    assert len(historique["securisations"]) == 1 and len(historique["versions"]) == 1
    assert ctx.base.vidal_prescription_audit.find_one({"id": r.json()["id"]})["mode_validation"] is True


def test_journal_exports_observation_et_visibilite(ctx):
    ctx.client.post("/api/vidal/validation/patients-fictifs")
    homme = _fictif(ctx, "HOMME-1")
    ctx.client.post("/api/vidal/securisation/analyze", json={"patient": {"gender": "MALE"}, "new_prescription_lines": [LIGNE], "patient_id": homme["id"]})
    liste = ctx.client.get("/api/vidal/validation/journal").json()
    nombre = len(liste["entrees"])
    assert nombre >= 2 and "corps" not in liste["entrees"][0] and "Recherche médicament" in liste["types"]
    numero = liste["entrees"][0]["numero"]
    assert ctx.client.patch(f"/api/vidal/validation/journal/{numero}", json={"observation_manuelle": "Conforme"}).json()["observation_manuelle"] == "Conforme"
    assert ctx.client.get(f"/api/vidal/validation/journal/{numero}").json()["observation_manuelle"] == "Conforme"
    assert len(ctx.client.get("/api/vidal/validation/journal", params={"type_appel": "Sécurisation (alertes structurées)"}).json()["entrees"]) == 1
    # Export XLSX : en-têtes + une ligne par appel, identifiants masqués.
    r = ctx.client.get("/api/vidal/validation/journal/export.xlsx")
    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        feuille = archive.read("xl/worksheets/sheet1.xml").decode()
    assert feuille.count("<row ") == nombre + 1 and "URL de la requête (identifiants masqués)" in feuille
    assert "app_key=***" in feuille and CLE_PROD not in feuille and ID_PROD not in feuille
    page = ctx.client.get("/api/vidal/validation/journal/export.html").text
    assert "Journal de validation VIDAL" in page and "app_id=***" in page and ID_PROD not in page
    # Un autre praticien ne voit pas ces appels ; le gestionnaire de l'établissement les voit tous.
    _comme(ctx, MEDECIN_2)
    assert ctx.client.get("/api/vidal/validation/journal").json()["entrees"] == []
    assert ctx.client.get(f"/api/vidal/validation/journal/{numero}").status_code == 404
    _comme(ctx, CLIENT)
    assert len(ctx.client.get("/api/vidal/validation/journal").json()["entrees"]) == nombre


def test_reglage_du_mode_et_suppression(ctx):
    assert ctx.client.get("/api/vidal/validation/etat").json()["mode_validation"] is True  # activé par défaut
    assert ctx.client.put("/api/vidal/validation/mode", json={"mode_validation": False, "confirmation": "DESACTIVER"}).status_code == 403  # médecin
    _comme(ctx, CLIENT)
    assert ctx.client.put("/api/vidal/validation/mode", json={"mode_validation": False}).status_code == 422
    assert ctx.client.put("/api/vidal/validation/mode", json={"mode_validation": False, "confirmation": "DESACTIVER"}).status_code == 200
    _comme(ctx, MEDECIN)
    assert ctx.client.get("/api/vidal/validation/etat").json()["mode_validation"] is False  # même établissement
    _comme(ctx, CLIENT)
    ctx.client.put("/api/vidal/validation/mode", json={"mode_validation": True})
    _comme(ctx, MEDECIN)
    vrai = _patient(ctx, nom="VRAI PATIENT")
    ctx.client.post("/api/vidal/validation/patients-fictifs")
    enceinte = _fictif(ctx, "ENCEINTE-1")
    ctx.client.post("/api/vidal/securisation/analyze", json={"patient": {"gender": "FEMALE"}, "new_prescription_lines": [LIGNE], "patient_id": enceinte["id"]})
    journal_avant = ctx.base.vidal_journal_validation.count_documents({})
    assert ctx.client.delete("/api/vidal/validation/patients-fictifs").json()["patients_supprimes"] == 3 * len(PROFILS)
    assert [p["id"] for p in ctx.base.vidal_patients.find({})] == [vrai]  # le vrai patient est intact
    assert ctx.base.vidal_prescription_audit.count_documents({}) == 0
    assert ctx.base.vidal_historique_profil_clinique.count_documents({"patient_id": {"$ne": vrai}}) == 0
    assert ctx.base.vidal_journal_validation.count_documents({}) == journal_avant  # journal de recette conservé


def test_generateur_sans_identifiants_production_aucune_valeur_inventee(ctx):
    ctx.base.settings.update_one({"_id": "global"}, {"$set": {"vidal_prod_app_id": "", "vidal_prod_app_key": ""}})
    bilan = ctx.client.post("/api/vidal/validation/patients-fictifs").json()
    assert bilan["vidal_interroge"] is False and "production" in bilan["message_vidal"]
    assert bilan["references_trouvees"] == 0 and bilan["references_a_choisir"] == 0 and bilan["references_a_rechercher"] > 0
    assert ctx.appels == []
    allergique = _fictif(ctx, "ALLERGIQUE-1")
    assert allergique["profil_clinique"]["allergies"] == [] and allergique["references_a_resoudre"][0]["statut"] == "a_rechercher"
    assert allergique["references_a_resoudre"][0]["recherche"] == "pénicillines"
    for p in ctx.base.vidal_patients.find({}):
        assert "vidal://" not in str(p)
    assert ctx.client.get("/api/vidal/validation/etat").json()["identifiants_production_configures"] is False
    # Et la sécurisation d'un patient fictif est refusée explicitement (503), sans requête.
    r = ctx.client.post("/api/vidal/securisation/analyze", json={"patient": {}, "new_prescription_lines": [LIGNE], "patient_id": allergique["id"]})
    assert r.status_code == 503 and "production" in r.json()["detail"] and ctx.appels == []


def test_generateur_reprend_exactement_les_references_vidal(ctx):
    ctx.specifiques[("/rest/api/allergies", "pénicillines")] = httpx.Response(200, text=(
        '<feed><entry vidal:categories="ALLERGY"><title>Classe renvoyée par VIDAL</title><id>vidal://allergy/7001</id><vidal:id>7001</vidal:id></entry>'
        '<entry vidal:categories="MOLECULE"><title>Substance renvoyée</title><id>vidal://molecule/7002</id><vidal:id>7002</vidal:id></entry></feed>'))
    ctx.specifiques[("/rest/api/pathologies", "asthme")] = httpx.Response(200, text=(
        '<feed><entry><title>Asthme A</title><id>vidal://cim10/7101</id><vidal:id>7101</vidal:id></entry>'
        '<entry><title>Asthme B</title><id>vidal://cim10/7102</id><vidal:id>7102</vidal:id></entry></feed>'))
    ctx.client.post("/api/vidal/validation/patients-fictifs")
    assert _fictif(ctx, "ALLERGIQUE-1")["profil_clinique"]["allergies"] == [{"label": "Classe renvoyée par VIDAL", "ref": "vidal://allergy/7001"}]
    patient3 = _fictif(ctx, "ALLERGIQUE-3")
    assert patient3["profil_clinique"]["pathologies"] == []
    a_choisir = next(r for r in patient3["references_a_resoudre"] if r["champ"] == "pathologies")
    assert a_choisir["statut"] == "a_choisir" and [c["ref"] for c in a_choisir["candidats"]] == ["vidal://cim10/7101", "vidal://cim10/7102"]
    assert ctx.base.vidal_journal_validation.count_documents({"type_appel": "Recherche référentielle"}) >= 1


REPONSE_CG_SEULE = ('<feed><entry vidal:categories="CREATININE_CLEARANCE"><vidal:estimatedCreatinineClearance unit="ml/min">64.4</vidal:estimatedCreatinineClearance>'
                    '<vidal:renalInsufficiency>MILD</vidal:renalInsufficiency></entry></feed>')


def test_calculateur_mode_validation_sans_valeur_locale(ctx):
    ctx.client.post("/api/vidal/validation/patients-fictifs")
    patient = _fictif(ctx, "INSUFFISANCE_RENALE-1")["id"]
    corps = {"dateOfBirth": "1964-01-01", "gender": "MALE", "weight": 75, "serumCreatinine": 115, "patient_id": patient}
    ctx.specifiques[("/rest/api/calculators/ccreat/cockroft-gault", None)] = httpx.Response(500, text="Erreur interne VIDAL")
    r = ctx.client.post("/api/vidal/calculateurs/fonction-renale", json=corps)
    assert r.status_code == 502 and "statut 500" in r.json()["detail"]["message"] and "Erreur interne VIDAL" in r.json()["detail"]["message"]
    ctx.specifiques[("/rest/api/calculators/ccreat/cockroft-gault", None)] = httpx.Response(200, text="<feed/>")
    assert ctx.client.post("/api/vidal/calculateurs/fonction-renale", json=corps).status_code == 502
    ctx.specifiques[("/rest/api/calculators/ccreat/cockroft-gault", None)] = httpx.Response(200, text=REPONSE_CG_SEULE)
    # Calculateur du DFG : réponse VIDAL sans DFG -> le DFG reste vide (jamais calculé localement).
    ctx.specifiques[("/rest/api/calculators/renal-function", None)] = httpx.Response(200, text="<feed/>")
    d = ctx.client.post("/api/vidal/calculateurs/fonction-renale", json=corps).json()
    assert d["creatin_calculee"] == 64.4 and d["creatin"] == 64 and d["insuffisanceRenale"] == "MILD"
    assert d["glomerularFiltrationRate"] is None and d["sources"]["glomerularFiltrationRate"] is None and d["mode_validation"] is True
