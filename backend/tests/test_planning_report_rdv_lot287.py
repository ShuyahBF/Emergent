"""Lot 287 — réponse de Liluvine aux demandes de report de RDV selon le code_clinique."""
import asyncio
from datetime import datetime, timedelta, timezone

from mongomock_motor import AsyncMongoMockClient

from routes.planning_report_rdv import (est_demande_report, message_pour_clinique, meme_numero,
                                        normaliser_reponses, remplir, repondre_report_rdv)

REGLAGES = {
    "planning_report_actif": True,
    "planning_report_reponses": [
        {"code_clinique": "cmc", "message": "Appelez l'accueil SVP : 78267900/70463624."},
        {"code_clinique": "CMCO", "message": "Bonjour {patient}, appelez le 70000000."},
    ],
    "planning_report_defaut": "",
}


def test_demande_de_report_reconnue_avec_ou_sans_accents():
    assert est_demande_report("Bonjour, je voudrais REPORTER mon rendez-vous")
    assert est_demande_report("Je suis indisponible demain")
    assert est_demande_report("Possible de décaler ?")
    assert not est_demande_report("Merci, j'arrive")


def test_numeros_compares_sur_les_8_derniers_chiffres():
    assert meme_numero("+226 70 00 11 22", "22670001122")
    assert not meme_numero("+22670001122", "22670001123")
    assert not meme_numero("", "22670001122")


def test_message_par_clinique_sans_casse_et_repli_sur_le_defaut():
    assert "78 26 79 00" in message_pour_clinique(REGLAGES, "CMC")
    assert "70 00 00 00" in message_pour_clinique(REGLAGES, "cmco")
    assert message_pour_clinique(REGLAGES, "AUTRE") == ""
    assert message_pour_clinique({**REGLAGES, "planning_report_defaut": "Appelez l'accueil."}, "AUTRE") == "Appelez l'accueil."


def test_normalisation_retire_les_lignes_vides_et_les_doublons():
    liste = normaliser_reponses([{"code_clinique": " cmc ", "message": "a"}, {"code_clinique": "CMC", "message": "b"},
                                 {"code_clinique": "", "message": "x"}, {"code_clinique": "Z", "message": ""}, "bizarre"])
    assert liste == [{"code_clinique": "CMC", "message": "b", "emoji": ""}]


def test_remplir_ne_plante_jamais_sur_un_marqueur_inconnu():
    assert remplir("Bonjour {patient} {inconnu}", {"patient": "KANE"}) == "Bonjour KANE {inconnu}"


def _base(rdvs):
    db = AsyncMongoMockClient()["t"]
    asyncio.get_event_loop().run_until_complete(db.planning_appointments.insert_many(rdvs))
    return db


def _rdv(code, tel="+22670001122", il_y_a_h=1, **plus):
    return {"id": f"r-{code}-{il_y_a_h}", "patient": "KANE", "medecin": "DR X", "code_clinique": code, "patient_phone": tel,
            "reminder_status": "sent",
            "reminder_sent_at": (datetime.now(timezone.utc) - timedelta(hours=il_y_a_h)).isoformat(), **plus}


def _lancer(db, texte, reglages=REGLAGES, tel="22670001122"):
    envoyes = []

    async def envoyer(to, txt):
        envoyes.append((to, txt))

    res = asyncio.get_event_loop().run_until_complete(
        repondre_report_rdv(db, phone_digits=tel, texte=texte, reglages=reglages, envoyer=envoyer, numero_destinataire=tel))
    return res, envoyes


def test_reponse_specifique_a_la_clinique_puis_une_seule_fois():
    db = _base([_rdv("CMC")])
    res, envoyes = _lancer(db, "Je veux reporter mon RDV")
    assert res["code_clinique"] == "CMC" and "+226 78 26 79 00" in envoyes[0][1]
    res2, envoyes2 = _lancer(db, "Je veux reporter mon RDV")   # déjà répondu pour ce RDV
    assert res2 is None and envoyes2 == []


def test_cmco_a_son_propre_message():
    db = _base([_rdv("CMCO")])
    _, envoyes = _lancer(db, "décaler svp")
    assert envoyes[0][1] == "Bonjour KANE, appelez le +226 70 00 00 00."


def test_rien_si_inactif_message_banal_rappel_trop_ancien_ou_autre_numero():
    assert _lancer(_base([_rdv("CMC")]), "report", {**REGLAGES, "planning_report_actif": False})[0] is None
    assert _lancer(_base([_rdv("CMC")]), "Merci beaucoup")[0] is None
    assert _lancer(_base([_rdv("CMC", il_y_a_h=30)]), "reporter")[0] is None
    assert _lancer(_base([_rdv("CMC")]), "reporter", tel="22671112233")[0] is None


def test_repondre_a_tout_message_si_demande():
    db = _base([_rdv("CMC")])
    res, _ = _lancer(db, "Merci beaucoup", {**REGLAGES, "planning_report_repondre_tout": True})
    assert res and res["ok"]


def test_simulation_pour_les_boutons_d_essai():
    from routes.planning_report_rdv import CODE_ESSAI_SANS_LIGNE, simuler_reponse
    avec = simuler_reponse(REGLAGES, "CMCO")
    assert avec["source"] == "ligne" and avec["message"] == "Bonjour PATIENT TEST, appelez le +226 70 00 00 00."
    assert simuler_reponse(REGLAGES, CODE_ESSAI_SANS_LIGNE) == {"source": "aucun", "message": ""}
    sans = simuler_reponse({**REGLAGES, "planning_report_defaut": "Appelez {patient}"}, CODE_ESSAI_SANS_LIGNE)
    assert sans == {"source": "defaut", "message": "Appelez PATIENT TEST"}


def test_pictogramme_en_tete_et_numeros_cliquables():
    from routes.planning_report_rdv import emoji_valide, lier_numeros, normaliser_reponses
    reglages = {"planning_report_reponses": [{"code_clinique": "cmc", "message": "Appelez 78267900/70463624.", "emoji": "📞"}],
                "planning_report_defaut": "Appelez l'accueil.", "planning_report_defaut_emoji": "🙏"}
    assert message_pour_clinique(reglages, "CMC") == "📞 Appelez +226 78 26 79 00/+226 70 46 36 24."
    assert message_pour_clinique(reglages, "AUTRE") == "🙏 Appelez l'accueil."
    # Un pictogramme hors de la liste proposée est refusé (aucun pictogramme)
    assert emoji_valide("💣") == "" and emoji_valide("📞") == "📞"
    assert normaliser_reponses([{"code_clinique": "A", "message": "m", "emoji": "💣"}])[0]["emoji"] == ""
    # Numéros déjà internationaux et longs identifiants laissés tels quels ; indicatif réglable
    assert lier_numeros("+226 70 00 11 22 et +22670001122 et 123456789012") == "+226 70 00 11 22 et +22670001122 et 123456789012"
    assert lier_numeros("70001122", "225") == "+225 70 00 11 22"
