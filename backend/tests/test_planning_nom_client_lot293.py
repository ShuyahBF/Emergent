"""Lot 293 — le nom du client (ex. « Clinique CMCO ») est cité dans le rappel de RDV et dans la réponse aux reports."""
import asyncio
from datetime import datetime, timedelta, timezone

import mongomock_motor

from routes.planning_report_rdv import normaliser_noms_clients, nom_client, remplir, simuler_reponse
from tests.test_lot74_modeles_meta_et_absence import _planning


def test_nom_affiche_par_code_sans_casse_et_vide_si_inconnu():
    r = {"planning_clients_noms": [{"code_clinique": "cmco", "nom": "Clinique CMCO"}, {"code_clinique": "SAWALI-2S", "nom": "SAWALI SMART SYSTEMS"},
                                   {"code_clinique": "", "nom": "x"}, {"code_clinique": "Z", "nom": ""}]}
    assert nom_client(r, "CMCO") == "Clinique CMCO" and nom_client(r, "sawali-2s") == "SAWALI SMART SYSTEMS"
    assert nom_client(r, "AUTRE") == "" and nom_client({}, "CMCO") == ""
    assert len(normaliser_noms_clients(r["planning_clients_noms"])) == 2


def test_marqueur_client_dans_les_reponses_aux_reports():
    r = {"planning_report_reponses": [{"code_clinique": "CMCO", "message": "{client} : appelez le 78267900.", "emoji": "📞"}],
         "planning_clients_noms": [{"code_clinique": "CMCO", "nom": "Clinique CMCO"}]}
    assert simuler_reponse(r, "CMCO")["message"] == "📞 Clinique CMCO : appelez le +226 78 26 79 00."
    assert remplir("De la part de {client}", {}, "") == "De la part de "


async def _rdv(db, code):
    debut = (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat()
    await db.planning_appointments.insert_one({"id": "r1", "start_at": debut, "patient": "Awa", "medecin": "Dr Ki", "motif": "Contrôle",
                                               "patient_phone": "22670000001", "code_clinique": code})


def test_rappel_texte_cite_le_client_et_reste_inchange_sans_nom():
    async def scenario():
        for reglages, attendu_client in (({"planning_clients_noms": [{"code_clinique": "CMCO", "nom": "Clinique CMCO"}]}, True), ({}, False)):
            db = mongomock_motor.AsyncMongoMockClient()["t"]
            await db.settings.insert_one({"_id": "global", **reglages})
            await _rdv(db, "CMCO")
            envois = []
            await _planning(db, envois)["run_planning_wa_reminders"]()
            texte = envois[0][2]
            assert ("rappel de Clinique CMCO" in texte) is attendu_client and "Awa" in texte
    boucle = asyncio.new_event_loop()
    try:
        boucle.run_until_complete(scenario())
    finally:
        boucle.close()


def test_rappel_modele_meta_5e_variable_ou_ajout_au_medecin():
    async def scenario():
        base = {"planning_reminder_wa_template": "rappel_rdv", "planning_clients_noms": [{"code_clinique": "CMCO", "nom": "Clinique CMCO"}]}
        # Modèle à 4 variables (déjà approuvé) : le nom du client est ajouté au médecin
        db = mongomock_motor.AsyncMongoMockClient()["t"]
        await db.settings.insert_one({"_id": "global", **base})
        await _rdv(db, "CMCO")
        envois = []
        await _planning(db, envois)["run_planning_wa_reminders"]()
        valeurs = [p["text"] for p in envois[0][4][0]["parameters"]]
        assert len(valeurs) == 4 and valeurs[1] == "Dr Ki — Clinique CMCO"
        # Modèle à 5 variables : le client est la 5e, le médecin reste seul
        db2 = mongomock_motor.AsyncMongoMockClient()["t2"]
        await db2.settings.insert_one({"_id": "global", **base, "planning_reminder_wa_variable_client": True})
        await _rdv(db2, "CMCO")
        envois2 = []
        await _planning(db2, envois2)["run_planning_wa_reminders"]()
        v2 = [p["text"] for p in envois2[0][4][0]["parameters"]]
        assert len(v2) == 5 and v2[1] == "Dr Ki" and v2[4] == "Clinique CMCO"
    boucle = asyncio.new_event_loop()
    try:
        boucle.run_until_complete(scenario())
    finally:
        boucle.close()
