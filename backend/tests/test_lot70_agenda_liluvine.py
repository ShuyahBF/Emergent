"""Lot 70 — agenda d'appels de Liluvine, anniversaires des utilisateurs suivis, voix clonées Story Studio.

Anniversaires (génération idempotente, âge, 29 février), modèle de texte, réclamation atomique (deux
réclamations simultanées → une seule gagne), plage horaire, autorisation d'appel (demande unique, attente,
réponse du contact), tentatives / sans réponse / message de repli, récurrences, lecture robuste du JSON de
l'IA, droits des routes, compte rendu de maintenance injecté dans le prompt, liste des voix Story Studio,
puis un appel SORTANT complet entre deux interlocuteurs WebRTC LOCAUX (aiortc).
MongoDB simulé, API Graph / transcription / IA / voix factices : aucun appel réseau.
Lancer : cd backend && python -m pytest tests/test_lot70_agenda_liluvine.py -q
"""
from __future__ import annotations

import asyncio
import json
import math
import struct
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.appel_proprietaire as ap  # noqa: E402
import routes.appels_wa as aw  # noqa: E402
import routes.liluvine_agenda as la  # noqa: E402
import routes.liluvine_decroche as ld  # noqa: E402

CONTACT = "22670000001"
# Mardi 6 octobre 2026, 10 h 00 à Ouagadougou (UTC)
MATIN = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)
NUIT = datetime(2026, 10, 6, 22, 30, tzinfo=timezone.utc)


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def db(monkeypatch):
    base = mongomock_motor.AsyncMongoMockClient()["sawali_lot70"]
    lancer(base.settings.insert_one({"_id": "global", "wa_phone_number_id": "PN-STANDARD",
                                     "wa_access_token": "jeton-factice"}))
    lancer(base.users.insert_one({"id": "sawali", "role": "superviseur", "company": "SAWALI"}))
    monkeypatch.setattr(ap, "_maintenant", lambda: MATIN)
    la._derniere_generation = None
    la._index_ok = False
    ld._actifs.clear()
    return base


def evenement(**autres):
    """Saisie d'un évènement valide (formulaire de l'agenda)."""
    p = {"date_heure": "2026-10-06T09:30", "type": "relance",
         "contact": {"source": "libre", "nom": "Awa KABORÉ", "telephone": "+226 70 00 00 01", "entreprise": "Pharmacie Wend Denda"},
         "objectif": "Savoir si la commande a été reçue.",
         "questions": [{"libelle": "Commande reçue ?", "type": "oui_non"},
                       {"libelle": "Montant payé", "type": "montant"},
                       {"libelle": "Satisfaction", "type": "choix", "choix": ["Bonne", "Moyenne", "Mauvaise"]}]}
    p.update(autres)
    return p


def inserer(db, **autres):
    """Insère un évènement planifié et le renvoie."""
    champs = la.valider_evenement(evenement(**autres), la.reglages_agenda({}))
    champs["client_id"] = "sawali"
    doc = la._nouvel_evenement(champs, par="Test", maintenant=MATIN)
    lancer(db.liluvine_agenda.insert_one(dict(doc)))
    return doc


# ---------------------------------------------------------------------------
# Dates : âge, 29 février, récurrences, plage horaire
# ---------------------------------------------------------------------------

def test_age_et_29_fevrier():
    n = date(1996, 2, 29)
    assert la.anniversaire_de(n, 2027) == date(2027, 2, 28)        # année non bissextile → 28/02
    assert la.anniversaire_de(n, 2028) == date(2028, 2, 29)
    assert la.age_a(n, date(2027, 2, 27)) == 30 and la.age_a(n, date(2027, 2, 28)) == 31
    assert la.prochain_anniversaire(date(1990, 10, 6), date(2026, 10, 6)) == date(2026, 10, 6)   # aujourd'hui compris
    assert la.prochain_anniversaire(date(1990, 10, 5), date(2026, 10, 6)) == date(2027, 10, 5)
    assert la.lire_date_naissance("06/10/1990") == date(1990, 10, 6)
    assert la.lire_date_naissance("1990-13-01") is None and la.lire_date_naissance("") is None


def test_recurrences():
    dt = datetime(2026, 1, 31, 9, 0, tzinfo=timezone.utc)
    assert la.prochaine_occurrence(dt, "aucune") is None
    assert la.prochaine_occurrence(dt, "quotidienne") == datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)
    assert la.prochaine_occurrence(dt, "hebdomadaire") == datetime(2026, 2, 7, 9, 0, tzinfo=timezone.utc)
    assert la.prochaine_occurrence(dt, "mensuelle") == datetime(2026, 2, 28, 9, 0, tzinfo=timezone.utc)
    assert la.prochaine_occurrence(datetime(2026, 12, 15, tzinfo=timezone.utc), "mensuelle").month == 1
    assert la.prochaine_occurrence(datetime(2028, 2, 29, 9, tzinfo=timezone.utc), "annuelle").date() == date(2029, 2, 28)


def test_plage_horaire_et_decision():
    cfga = la.reglages_agenda({})
    ev = {"type": "relance", "telephone": CONTACT}
    assert la.decision_execution(ev, cfga, MATIN, occupes=0, max_simultanes=2)["action"] == "appeler"
    d = la.decision_execution(ev, cfga, NUIT, occupes=0, max_simultanes=2)
    assert d["action"] == "reporter" and d["a"] == "2026-10-07T08:00:00+00:00" and "plage" in d["raison"]
    # Samedi soir → lundi ? Non : samedi est autorisé par défaut ; dimanche ne l'est pas
    samedi_soir = datetime(2026, 10, 10, 21, 0, tzinfo=timezone.utc)
    assert la.decision_execution(ev, cfga, samedi_soir, occupes=0, max_simultanes=2)["a"] == "2026-10-12T08:00:00+00:00"
    # « Appeler maintenant » : la plage est ignorée, pas la limite d'appels simultanés
    assert la.decision_execution(ev, cfga, NUIT, occupes=0, max_simultanes=2, force=True)["action"] == "appeler"
    d = la.decision_execution(ev, cfga, MATIN, occupes=2, max_simultanes=2)
    assert d["action"] == "reporter" and "limite 2" in d["raison"]
    # Plage propre à l'évènement
    assert la.decision_execution({**ev, "plage_debut": "11:00", "plage_fin": "12:00"}, cfga, MATIN, occupes=0,
                                 max_simultanes=2)["a"] == "2026-10-06T11:00:00+00:00"
    # Anniversaires désactivés, numéro manquant
    assert la.decision_execution({"type": "anniversaire", "telephone": CONTACT},
                                 la.reglages_agenda({"liluvine_agenda_anniv_actif": False}), MATIN,
                                 occupes=0, max_simultanes=2)["action"] == "annuler"
    assert la.decision_execution({"type": "relance", "telephone": "12"}, cfga, MATIN, occupes=0,
                                 max_simultanes=2)["action"] == "annuler"


# ---------------------------------------------------------------------------
# Textes : modèle, prénom, ouverture, prompt
# ---------------------------------------------------------------------------

def test_modele_et_noms():
    assert la.separer_nom("OUOBA Jean-François") == ("Jean-François", "OUOBA")
    assert la.separer_nom("Awa Kaboré") == ("Awa", "Kaboré")
    v = {"prenom": "Awa", "nom": "KABORÉ", "age": 35, "entreprise": "SAWALI"}
    assert la.rendre_modele("Joyeux anniversaire {prenom} {nom}, {age} ans ! {inconnue}", v) == \
        "Joyeux anniversaire Awa KABORÉ, 35 ans ! {inconnue}"
    assert la.rendre_modele("Bonjour {prenom} !", {"prenom": ""}) == "Bonjour !"
    texte = la.rendre_modele(la.ANNIV_TEXTE_DEFAUT, v)
    assert texte.startswith("Bonjour Awa !") and "équipe SAWALI" in texte and "{" not in texte


def test_validation_et_prompt():
    cfga = la.reglages_agenda({})
    c = la.valider_evenement(evenement(), cfga)
    assert c["date_heure"] == "2026-10-06T09:30:00+00:00" and c["telephone"] == CONTACT
    assert [q["id"] for q in c["questions"]] == ["q1", "q2", "q3"] and c["questions"][2]["choix"][0] == "Bonne"
    for mauvais, message in ((evenement(type="x"), "Type"), (evenement(date_heure=""), "Date"),
                             (evenement(contact={"telephone": "12"}), "Numéro"),
                             (evenement(questions=[{"libelle": "Q", "type": "choix", "choix": ["un"]}]), "deux choix"),
                             (evenement(recurrence="horaire"), "Récurrence")):
        with pytest.raises(ValueError, match=message):
            la.valider_evenement(mauvais, cfga)
    ouv = la.texte_ouverture({**c, "texte_a_lire": "Votre commande est prête, {prenom}."})
    assert ouv.startswith("Bonjour Awa, ici Liluvine") and "faire suite" in ouv and "prête, Awa." in ouv
    assert ouv.endswith("Avez-vous un petit moment ?")
    p = la.assembler_prompt_sortant("Tu es Liluvine PRO.", c, ouv, connaissances="[Base] Horaires 8 h – 18 h")
    assert p.startswith("Tu es Liluvine PRO.") and "c'est TOI qui appelles" in p and "[Base] Horaires" in p
    assert "Commande reçue ? (réponse oui ou non)" in p and "choix : Bonne, Moyenne, Mauvaise" in p
    assert "Savoir si la commande a été reçue." in p and "Tu as déjà dit en ouverture" in p and "[FIN]" in p


# ---------------------------------------------------------------------------
# Extraction : JSON de l'IA lu de façon robuste
# ---------------------------------------------------------------------------

QUESTIONS = la.nettoyer_questions(evenement()["questions"])


def test_extraction_json_propre_et_abime():
    bon = json.dumps({"resume": "Commande reçue, payée.", "reponses": {
        "q1": {"valeur": "oui", "confiance": 0.9}, "q2": {"valeur": "25 000 F", "confiance": 0.8},
        "q3": {"valeur": "bonne", "confiance": 2}},
        "action_suivante": {"texte": "Rappeler dans un mois", "type": "suivi_client", "date": "2026-11-06 10:00"}})
    r = la.analyser_extraction(f"Voici :\n```json\n{bon}\n```", QUESTIONS)
    assert [i["valeur"] for i in r["informations"]] == [True, 25000, "Bonne"]
    assert r["informations"][2]["confiance"] == 1.0 and r["erreur"] is None
    assert r["action_suivante"] == {"texte": "Rappeler dans un mois", "type": "suivi_client",
                                    "date": "2026-11-06T10:00:00+00:00"}
    # Virgule finale, apostrophes, valeurs absentes ou incohérentes
    abime = "{'resume': 'Pas disponible', 'reponses': {'q1': 'peut-être', 'q3': 'excellente'},}"
    r = la.analyser_extraction(abime, QUESTIONS)
    assert r["resume"] == "Pas disponible" and [i["valeur"] for i in r["informations"]] == [None, None, None]
    assert r["action_suivante"]["type"] == "aucune"
    # Texte sans JSON : aucune exception, résumé brut, erreur signalée
    r = la.analyser_extraction("Désolé, je ne peux pas.", QUESTIONS)
    assert r["erreur"] and r["resume"] == "Désolé, je ne peux pas." and len(r["informations"]) == 3
    assert la.normaliser_valeur("12/03/2027", {"type": "date"}) == "2027-03-12"


# ---------------------------------------------------------------------------
# Anniversaires : génération idempotente, mises à jour, annulation
# ---------------------------------------------------------------------------

def test_anniversaires_idempotents(db):
    lancer(db.tracked_users.insert_many([
        {"id": "tu1", "name": "OUOBA Jean-François", "whatsapp_number": "+226 70 11 22 33", "client_id": "sawali",
         "date_naissance": "1980-10-06", "status": "active"},
        {"id": "tu2", "name": "Bissextile Bintou", "phone": "+226 70 44 55 66", "date_naissance": "1996-02-29"},
        {"id": "tu3", "name": "Sans numéro", "date_naissance": "1990-01-01"},
        {"id": "tu4", "name": "Sans date", "whatsapp_number": "+226 70 77 88 99"},
    ]))
    s = {"liluvine_agenda_anniv_heure": "09:15"}
    r1 = lancer(la.generer_anniversaires(db, s, MATIN))
    r2 = lancer(la.generer_anniversaires(db, s, MATIN))
    assert r1["crees"] == 2 and r2 == {"crees": 0, "mis_a_jour": 0, "annules": 0}       # un par personne et par an
    assert lancer(db.liluvine_agenda.count_documents({})) == 2
    ev = lancer(db.liluvine_agenda.find_one({"id": "anniv-tu1-2026"}, {"_id": 0}))
    assert ev["date_heure"] == "2026-10-06T09:15:00+00:00" and ev["age"] == 46 and ev["telephone"] == "22670112233"
    assert ev["contact"]["entreprise"] == "SAWALI" and ev["statut"] == "planifie" and ev["titre"].endswith("(46 ans)")
    bis = lancer(db.liluvine_agenda.find_one({"id": "anniv-tu2-2027"}, {"_id": 0}))
    assert bis["date_heure"].startswith("2027-02-28") and bis["age"] == 31             # 29/02 → 28/02 en 2027
    # Nouvelle heure réglée : l'évènement planifié suit
    assert lancer(la.generer_anniversaires(db, {"liluvine_agenda_anniv_heure": "10:30"}, MATIN))["mis_a_jour"] == 2
    assert lancer(db.liluvine_agenda.find_one({"id": "anniv-tu1-2026"}))["prochaine_tentative"] == "2026-10-06T10:30:00+00:00"
    # Date de naissance retirée : l'anniversaire à venir est annulé
    lancer(db.tracked_users.update_one({"id": "tu2"}, {"$set": {"date_naissance": ""}}))
    assert lancer(la.generer_anniversaires(db, {}, MATIN))["annules"] == 1
    assert lancer(db.liluvine_agenda.find_one({"id": "anniv-tu2-2027"}))["statut"] == "annule"


def test_texte_anniversaire_et_ia(db, monkeypatch):
    lancer(db.tracked_users.insert_one({"id": "tu1", "name": "Awa Kaboré", "whatsapp_number": "22670000001",
                                        "date_naissance": "1991-10-06", "company": "Wend Denda"}))
    lancer(la.generer_anniversaires(db, {}, MATIN))
    ev = lancer(db.liluvine_agenda.find_one({"id": "anniv-tu1-2026"}, {"_id": 0}))
    cfga = la.reglages_agenda({"liluvine_agenda_anniv_texte": "Joyeux anniversaire {prenom}, {age} ans chez {entreprise} !"})
    ev = lancer(la.preparer_contenu(db, {}, cfga, ev))
    assert ev["texte_a_lire"] == "Joyeux anniversaire Awa, 35 ans chez Wend Denda !"

    async def fausse_ia(systeme, texte, max_jetons=900):
        return {"texte": "Très joyeux anniversaire Awa, toute l'équipe Wend Denda pense à vous !", "entree": 1, "sortie": 1}
    monkeypatch.setattr(la, "llm_texte", fausse_ia)
    ev = lancer(la.preparer_contenu(db, {}, {**cfga, "anniv_ia": True}, ev))
    assert ev["texte_a_lire"].startswith("Très joyeux anniversaire Awa")


# ---------------------------------------------------------------------------
# Moteur : réclamation atomique, autorisation, tentatives, repli
# ---------------------------------------------------------------------------

def test_reclamation_atomique(db):
    inserer(db)

    async def scenario():
        return await asyncio.gather(la.reclamer(db, MATIN), la.reclamer(db, MATIN))
    a, b = lancer(scenario())
    assert (a is None) != (b is None)                     # un seul gagnant
    gagnant = a or b
    assert gagnant["statut"] == "en_cours" and gagnant["verrou_par"] == la.INSTANCE
    assert lancer(la.reclamer(db, MATIN)) is None         # plus rien à prendre
    # Évènement futur : jamais réclamé avant l'heure
    inserer(db, date_heure="2026-10-06T11:00")
    assert lancer(la.reclamer(db, MATIN)) is None


class FauxGraph:
    """API Graph factice : autorisation d'appel au choix, messages et appels mémorisés."""

    def __init__(self, permission="no_permission"):
        self.permission = permission
        self.messages = []
        self.appels = []

    async def get(self, s, numero_id, chemin, params):
        return {"ok": True, "donnees": {"permission": {"status": self.permission}, "actions": [
            {"action_name": "start_call", "can_perform_action": self.permission in ("temporary", "permanent")},
            {"action_name": "send_call_permission_request", "can_perform_action": True}]}, "erreur": None}

    async def post(self, s, numero_id, chemin, corps):
        if chemin == "messages":
            self.messages.append(corps)
            return {"ok": True, "donnees": {"messages": [{"id": f"wamid.{len(self.messages)}"}]}, "erreur": None}
        self.appels.append(corps)
        return {"ok": True, "donnees": {"success": True}, "erreur": None}


def test_autorisation_demandee_une_fois_puis_reponse(db, monkeypatch):
    g = FauxGraph()
    monkeypatch.setattr(ap, "_graph_get", g.get)
    monkeypatch.setattr(ap, "_graph_post", g.post)
    appels = []

    async def faux_appel(*a, **kw):
        appels.append(1)
        return {"resultat": "sans_reponse", "raison": "pas de réponse", "call_id": "c1"}
    monkeypatch.setattr(la, "appeler_et_converser", faux_appel)
    ev = inserer(db)
    r = lancer(la.executer_echeances(db, lancer_en_fond=False))
    assert r["lances"] == [ev["id"]] and not appels
    doc = lancer(db.liluvine_agenda.find_one({"id": ev["id"]}))
    assert doc["statut"] == "attente_autorisation" and doc["autorisation_demandee_le"] == "2026-10-06T10:00:00+00:00"
    assert doc["prochaine_tentative"] == "2026-10-06T10:30:00+00:00"
    assert len(g.messages) == 1 and g.messages[0]["interactive"]["type"] == "call_permission_request"
    assert "Bonjour Awa, ici Liluvine" in g.messages[0]["interactive"]["body"]["text"]
    assert lancer(db.whatsapp_messages.count_documents({"message_type": "call_permission_request"})) == 1
    # Passage suivant (pas encore l'heure de revérifier) : rien ; à l'heure : pas de 2e demande
    assert lancer(la.executer_echeances(db, lancer_en_fond=False))["lances"] == []
    monkeypatch.setattr(ap, "_maintenant", lambda: datetime(2026, 10, 6, 10, 31, tzinfo=timezone.utc))
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    assert len(g.messages) == 1 and lancer(db.liluvine_agenda.find_one({"id": ev["id"]}))["statut"] == "attente_autorisation"
    # Le contact accepte (webhook) : l'évènement repart tout de suite et l'appel est passé
    lancer(aw.noter_reponse_permission(db, "+226 70 00 00 01", {"response": "accept", "is_permanent": True}))
    assert lancer(db.liluvine_agenda.find_one({"id": ev["id"]}))["prochaine_tentative"] == "2026-10-06T10:31:00+00:00"
    g.permission = "permanent"
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    assert appels == [1]
    doc = lancer(db.liluvine_agenda.find_one({"id": ev["id"]}))
    assert doc["statut"] == "planifie" and doc["tentatives"] == 1          # sans réponse : nouvelle tentative


def test_autorisation_refusee_et_limite_meta(db, monkeypatch):
    g = FauxGraph()
    monkeypatch.setattr(ap, "_graph_get", g.get)
    monkeypatch.setattr(ap, "_graph_post", g.post)
    ev = inserer(db)
    # Deux demandes déjà envoyées cette semaine à ce numéro (autre écran) : limite Meta atteinte
    for jour in ("2026-10-02T10:00:00+00:00", "2026-10-04T10:00:00+00:00"):
        lancer(db.whatsapp_messages.insert_one({"message_type": "call_permission_request",
                                                "phone_digits": CONTACT, "created_at": jour}))
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    doc = lancer(db.liluvine_agenda.find_one({"id": ev["id"]}))
    assert doc["statut"] == "attente_autorisation" and doc["autorisation_envoi"]["envoyee"] is False
    assert "limite" in doc["autorisation_envoi"]["raison"] and not g.messages
    # Le contact refuse : à son prochain passage, l'évènement s'arrête et le message de repli part
    lancer(aw.noter_reponse_permission(db, CONTACT, {"response": "reject"}))
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    doc = lancer(db.liluvine_agenda.find_one({"id": ev["id"]}))
    assert doc["statut"] == "echec" and "refusé" in doc["raison"] and doc["repli"]["ok"] is True
    assert g.messages[-1]["type"] == "text" and "J'ai essayé de vous joindre" in g.messages[-1]["text"]["body"]
    assert "• Commande reçue ?" in g.messages[-1]["text"]["body"]


def test_tentatives_puis_sans_reponse_et_repli(db, monkeypatch):
    g = FauxGraph(permission="permanent")
    monkeypatch.setattr(ap, "_graph_get", g.get)
    monkeypatch.setattr(ap, "_graph_post", g.post)

    async def sans_reponse(*a, **kw):
        return {"resultat": "sans_reponse", "raison": "pas de réponse", "call_id": "c1"}
    monkeypatch.setattr(la, "appeler_et_converser", sans_reponse)
    ev = inserer(db, tentatives_max=2, intervalle_min=15, recurrence="hebdomadaire")
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    doc = lancer(db.liluvine_agenda.find_one({"id": ev["id"]}))
    assert doc["statut"] == "planifie" and doc["tentatives"] == 1 and doc["prochaine_tentative"] == "2026-10-06T10:15:00+00:00"
    monkeypatch.setattr(ap, "_maintenant", lambda: datetime(2026, 10, 6, 10, 16, tzinfo=timezone.utc))
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    doc = lancer(db.liluvine_agenda.find_one({"id": ev["id"]}, {"_id": 0}))
    assert doc["statut"] == "sans_reponse" and doc["tentatives"] == 2 and doc["repli"]["ok"] is True
    assert len(g.messages) == 1 and "J'ai essayé de vous joindre" in g.messages[0]["text"]["body"]
    # Récurrence hebdomadaire : UNE occurrence suivante, même après un second passage
    suite = lancer(db.liluvine_agenda.find_one({"id": f"{ev['id']}-suite"}, {"_id": 0}))
    assert suite["date_heure"] == "2026-10-13T09:30:00+00:00" and suite["statut"] == "planifie"
    lancer(la.creer_occurrence_suivante(db, doc))
    assert lancer(db.liluvine_agenda.count_documents({"precedent_id": ev["id"]})) == 1


def test_resultat_conversation_et_relance(db, monkeypatch):
    g = FauxGraph(permission="permanent")
    monkeypatch.setattr(ap, "_graph_get", g.get)
    monkeypatch.setattr(ap, "_graph_post", g.post)
    lancer(db.settings.update_one({"_id": "global"}, {"$set": {"appel_proprio_tarif_appel_minute": "60",
                                                               "liluvine_agenda_relance_auto": True}}))

    async def conversation(db_, s, cfga, ev, **kw):
        await db_.wa_appels.insert_one({"id": "wacid.OUT", "direction": "sortant", "statut": "en_cours",
                                        "agenda_id": ev["id"]})
        return {"resultat": "decroche", "call_id": "wacid.OUT", "fin": "au revoir", "duree_s": 56, "transfert": False,
                "transcription": [{"qui": "liluvine", "texte": "Bonjour", "t": 0},
                                  {"qui": "appelant", "texte": "Oui, reçue, j'ai payé 25 000.", "t": 5}],
                "mesures": {"tts_caracteres": {"openai": 1000}, "llm_entree": 100, "llm_sortie": 10, "tours": 1,
                            "stt_secondes": 3, "stt_modele": "gpt-4o-mini-transcribe", "latences_s": [1.2]}}
    monkeypatch.setattr(la, "appeler_et_converser", conversation)

    async def extraction(systeme, texte, max_jetons=900):
        assert "id=q1 ; type=oui_non" in texte and "Oui, reçue" in texte
        return {"texte": json.dumps({"resume": "Commande reçue et payée.", "reponses": {
            "q1": {"valeur": True, "confiance": 0.95}, "q2": {"valeur": 25000, "confiance": 0.9}},
            "action_suivante": {"texte": "Proposer le réassort", "type": "relance", "date": "2026-10-20 09:00"}}),
            "entree": 300, "sortie": 60}
    monkeypatch.setattr(la, "llm_texte", extraction)
    ev = inserer(db)
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    doc = lancer(db.liluvine_agenda.find_one({"id": ev["id"]}, {"_id": 0}))
    r = doc["resultat"]
    assert doc["statut"] == "termine" and r["resume"] == "Commande reçue et payée."
    assert [i["valeur"] for i in r["informations"]] == [True, 25000, None]
    # 56 s → 10 tranches de 6 s = 60 s facturées à 60 FCFA la minute
    assert r["cout"]["secondes_facturees"] == 60 and r["cout"]["cout_appel"] == 60.0 and r["cout"]["devise"] == "FCFA"
    assert r["cout"]["ia_usd"] > 0
    journal = lancer(db.wa_appels.find_one({"id": "wacid.OUT"}, {"_id": 0}))
    assert journal["statut"] == "termine" and journal["liluvine"]["agenda"]["informations"][0]["valeur"] is True
    # Relance suggérée créée automatiquement (réglage)
    relance = lancer(db.liluvine_agenda.find_one({"id": f"{ev['id']}-relance"}, {"_id": 0}))
    assert relance["date_heure"] == "2026-10-20T09:00:00+00:00" and relance["objectif"] == "Proposer le réassort"
    # Durée officielle de Meta (webhook terminate) : coût recalculé avec le tarif figé
    lancer(aw.traiter_webhook_appels(db, {"metadata": {"phone_number_id": "PN-STANDARD"}, "calls": [
        {"id": "wacid.OUT", "event": "terminate", "duration": 61, "status": "COMPLETED"}]}))
    r = lancer(db.liluvine_agenda.find_one({"id": ev["id"]}))["resultat"]
    assert r["duree_meta_s"] == 61 and r["cout"]["secondes_facturees"] == 66 and r["cout"]["cout_appel"] == 66.0
    t = la.totaux([lancer(db.liluvine_agenda.find_one({"id": ev["id"]}, {"_id": 0}))])
    assert t["par_statut"]["termine"] == 1 and t["duree_s"] == 61 and t["cout"] == 66.0   # voix : tarif 0 par défaut


# ---------------------------------------------------------------------------
# Compte rendu de maintenance : résumé injecté dans le prompt
# ---------------------------------------------------------------------------

def test_compte_rendu_maintenance(db):
    lancer(db.maintenance_fiches.insert_one({
        "id": "f1", "numero": "MNT-SAW-2026-0007", "client_nom": "Awa Kaboré", "client_telephone": "+22670000001",
        "date_reception": "2026-10-01", "type_materiel": "Imprimante", "marque_modele": "HP LaserJet",
        "motif": "Bourrage papier", "diagnostic": "Rouleau usé", "remplacement_pieces": True,
        "pieces": "Rouleau d'entraînement", "statut": "pret",
        "interventions": [{"debut": "2026-10-02T08:00:00+00:00", "fin": "2026-10-02T09:35:00+00:00",
                           "duree_minutes": 95, "etat_fin": "termine", "equipe": "Issa"}]}))
    trouves = lancer(la.rechercher_maintenances(db, "MNT-SAW"))
    assert trouves[0]["source"] == "maintenance" and "Imprimante HP LaserJet" in trouves[0]["libelle"]
    resume = lancer(la.resume_maintenance(db, "maintenance", "f1"))
    assert "Rouleau usé" in resume and "Rouleau d'entraînement" in resume and "1 h 35 min" in resume
    ev = inserer(db, type="compte_rendu_maintenance", maintenance={"source": "maintenance", "id": "f1"}, questions=[])
    ev = lancer(la.preparer_contenu(db, {}, la.reglages_agenda({}), ev))
    prompt = la.assembler_prompt_sortant("Base", ev, la.texte_ouverture(ev))
    assert "Compte rendu de maintenance à présenter simplement" in prompt and "Rouleau usé" in prompt
    assert "compte rendu de la maintenance" in la.texte_ouverture(ev)


# ---------------------------------------------------------------------------
# Routes : droits, création, liste, export, annulation, voix Story Studio
# ---------------------------------------------------------------------------

def _client_http(db):
    utilisateurs = {"sup": {"id": "sawali", "role": "superviseur", "client_id": "sawali", "full_name": "Sup"},
                    "admin": {"id": "a1", "role": "admin", "full_name": "Admin"},
                    "client": {"id": "x", "role": "client", "client_id": "x"},
                    # Lot 73 — superviseur nommé (partage de Liluvine réglable par l'administrateur)
                    "support": {"id": "s2", "role": "superviseur", "email": "support@sawalismartsystems.com",
                                "full_name": "Support"}}

    async def utilisateur(request: Request):
        uid = request.headers.get("X-User")
        if uid not in utilisateurs:
            raise HTTPException(status_code=401)
        return utilisateurs[uid]
    api = APIRouter(prefix="/api")
    la.setup_liluvine_agenda_routes(db=db, api=api, get_current_user=utilisateur)
    ld.setup_liluvine_decroche_routes(db=db, api=api, get_current_user=utilisateur)
    from routes.liluvine_partage import setup_liluvine_partage_routes   # lot 73
    setup_liluvine_partage_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def test_routes_droits_et_parcours(db):
    c = _client_http(db)
    assert c.get("/api/admin/liluvine-agenda").status_code == 401
    for chemin in ("/api/admin/liluvine-agenda", "/api/admin/liluvine-agenda/reglages",
                   "/api/admin/liluvine-agenda/contacts?q=awa", "/api/admin/liluvine-decroche/voix-clonees"):
        assert c.get(chemin, headers={"X-User": "client"}).status_code == 403, chemin
    assert c.post("/api/admin/liluvine-agenda", json=evenement(), headers={"X-User": "client"}).status_code == 403
    h = {"X-User": "sup"}
    assert c.post("/api/admin/liluvine-agenda", json=evenement(type="inconnu"), headers=h).status_code == 422
    assert c.post("/api/admin/liluvine-agenda", json=evenement(maintenance={"source": "maintenance", "id": "absent"}),
                  headers=h).status_code == 422
    cree = c.post("/api/admin/liluvine-agenda", json=evenement(priorite="haute"), headers=h).json()
    assert cree["statut"] == "planifie" and cree["priorite_ordre"] == 0 and cree["cree_par"] == "Sup"
    copie = c.post(f"/api/admin/liluvine-agenda/{cree['id']}/dupliquer", json={"date_heure": "2026-10-08T15:00"},
                   headers={"X-User": "admin"}).json()
    assert copie["date_heure"] == "2026-10-08T15:00:00+00:00" and copie["copie_de"] == cree["id"]
    liste = c.get("/api/admin/liluvine-agenda?du=2026-10-06&au=2026-10-06", headers=h).json()
    assert [e["id"] for e in liste["evenements"]] == [cree["id"]] and liste["totaux"]["par_statut"]["planifie"] == 1
    assert liste["types"]["compte_rendu_maintenance"] == "Compte rendu de maintenance"
    assert len(c.get("/api/admin/liluvine-agenda?q=kabor", headers=h).json()["evenements"]) == 2
    csv_texte = c.get("/api/admin/liluvine-agenda/export.csv", headers=h).text
    assert csv_texte.startswith("﻿Date;Heure;Type") and "06/10/2026;09:30;Relance" in csv_texte
    modif = c.put(f"/api/admin/liluvine-agenda/{cree['id']}", json=evenement(date_heure="2026-10-07T08:30"), headers=h).json()
    assert modif["prochaine_tentative"] == "2026-10-07T08:30:00+00:00"
    assert c.post(f"/api/admin/liluvine-agenda/{cree['id']}/annuler", headers=h).status_code == 200
    assert c.post(f"/api/admin/liluvine-agenda/{cree['id']}/annuler", headers=h).status_code == 409
    assert c.post(f"/api/admin/liluvine-agenda/{cree['id']}/appeler-maintenant", headers=h).status_code == 409
    # Réglages : heure contrôlée, champs inconnus ignorés
    assert c.put("/api/admin/liluvine-agenda/reglages", json={"liluvine_agenda_anniv_heure": "9h"}, headers=h).status_code == 422
    assert c.put("/api/admin/liluvine-agenda/reglages", json={"liluvine_agenda_anniv_heure": "08:45", "x": 1},
                 headers=h).status_code == 200
    r = c.get("/api/admin/liluvine-agenda/reglages", headers=h).json()
    assert r["effectif"]["anniv_heure"] == "08:45" and r["effectif"]["anniv_actif"] is True and "x" not in r["reglages"]
    assert c.post("/api/admin/liluvine-agenda/apercu-anniversaire", json={"texte": "Bravo {prenom} !"},
                  headers=h).json()["texte"] == "Bravo Awa !"


def test_recherche_contacts_et_voix_story_studio(db):
    lancer(db.directory_contacts.insert_one({"id": "c1", "name": "Awa Kaboré", "whatsapp": "+226 70 00 00 01"}))
    lancer(db.tracked_users.insert_one({"id": "t1", "name": "Awa Ouédraogo", "whatsapp_number": "+226 75 00 00 02"}))
    lancer(db.users.insert_one({"id": "cl1", "role": "client", "company": "Pharmacie Awa", "phone": "+226 76 00 00 03"}))
    trouves = lancer(la.rechercher_contacts(db, "awa"))
    assert {t["source"] for t in trouves} == {"contact", "suivi", "client"}
    assert lancer(la.rechercher_contacts(db, "75 00"))[0]["id"] == "t1"
    lancer(db.users.insert_one({"id": "u9", "full_name": "Jean Conteur", "role": "client"}))
    lancer(db.eleven_voices.insert_many([
        {"id": "v1", "user_id": "u9", "name": "Voix de Jean", "voice_id": "AbCdEf123456", "created_at": "2026-10-01"},
        {"id": "v2", "user_id": "u9", "name": "Cassée", "voice_id": "x!", "created_at": "2026-10-02"}]))
    c = _client_http(db)
    r = c.get("/api/admin/liluvine-decroche/voix-clonees", headers={"X-User": "admin"}).json()
    assert [v["voice_id"] for v in r["voix"]] == ["AbCdEf123456"] and r["voix"][0]["auteur"] == "Jean Conteur"
    assert r["voix"][0]["source"] == "story_studio"


def test_date_naissance_des_utilisateurs_suivis():
    from models import TrackedUserCreate, TrackedUserUpdate
    assert TrackedUserUpdate(date_naissance="29/02/1996").date_naissance == "1996-02-29"
    assert TrackedUserUpdate(date_naissance="").date_naissance == ""           # effacée
    assert TrackedUserUpdate().date_naissance is None                         # non modifiée
    for mauvaise in ("2099-01-01", "31/02/1990", "n'importe quoi"):
        with pytest.raises(Exception):
            TrackedUserCreate(client_id="c", name="N", date_naissance=mauvaise)


# ---------------------------------------------------------------------------
# Appel sortant complet de bout en bout (deux interlocuteurs aiortc locaux)
# ---------------------------------------------------------------------------

def _pcm(secondes, amplitude=0, frequence=300, taux=16000):
    """PCM 16 bits mono : sinus (amplitude > 0) ou silence."""
    n = int(taux * secondes)
    return b"".join(struct.pack("<h", int(amplitude * math.sin(2 * math.pi * frequence * i / taux))) for i in range(n))


def _wav(secondes, amplitude=12000, frequence=440, taux=16000):
    """Petit fichier WAV (sinus) : voix simulée."""
    pcm = _pcm(secondes, amplitude, frequence, taux)
    entete = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, taux, taux * 2, 2, 16) + b"data" + struct.pack("<I", len(pcm))
    return entete + pcm


def test_appel_sortant_de_bout_en_bout(monkeypatch):
    pytest.importorskip("aiortc")
    pytest.importorskip("av")
    from aiortc import RTCPeerConnection, RTCSessionDescription

    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot70_e2e"]
    lancer(db.settings.insert_one({"_id": "global", "wa_phone_number_id": "PN-STANDARD",
                                   "wa_access_token": "jeton-factice", "liluvine_agenda_silence_s": 8,
                                   "appel_proprio_tarif_appel_minute": "30"}))
    lancer(db.users.insert_one({"id": "sawali", "role": "superviseur", "company": "SAWALI"}))
    monkeypatch.setattr(ap, "_maintenant", lambda: MATIN)
    monkeypatch.setattr(ap, "serveurs_ice", lambda: [])          # pas de STUN : tout reste local
    monkeypatch.setenv("OPENAI_API_KEY", "cle-factice")          # écoute « disponible » (simulée)
    la._derniere_generation, la._index_ok = None, False
    ld._actifs.clear()
    g = FauxGraph(permission="permanent")
    monkeypatch.setattr(ap, "_graph_get", g.get)

    voix_dites = []

    async def fausse_voix(texte, s, cfg):
        voix_dites.append(texte)
        return ap.decoder_pcm(_wav(0.4, 9000, 660)), "openai"
    monkeypatch.setattr(ld, "synthese_vocale", fausse_voix)

    async def faux_stt(wav, s, cfg):
        return "Oui, la commande est bien arrivée, j'ai payé vingt-cinq mille francs.", "gpt-4o-mini-transcribe"
    monkeypatch.setattr(ld, "transcrire", faux_stt)
    prompts = []

    async def faux_llm(systeme, historique, texte):
        prompts.append((systeme, texte))
        # Réponse « écrite » de l'IA : salutation redite + liste numérotée → corrigées avant la voix
        return {"texte": "Bonjour Awa ! Parfait, merci :\n1. Pour votre temps.\n2. Pour votre réponse. Au revoir ! [FIN]",
                "entree": 800, "sortie": 20}
    monkeypatch.setattr(ld, "repondre_llm", faux_llm)

    async def fausse_extraction(systeme, texte, max_jetons=900):
        return {"texte": '{"resume": "Commande reçue, 25 000 F payés.", "reponses": {"q1": {"valeur": "oui", '
                         '"confiance": 0.9}, "q2": {"valeur": 25000, "confiance": 0.85}}, '
                         '"action_suivante": {"texte": "Aucune", "type": "aucune", "date": null}}',
                "entree": 200, "sortie": 40}
    monkeypatch.setattr(la, "llm_texte", fausse_extraction)
    actions = []
    recu = {"son": 0}

    async def scenario():
        contact = RTCPeerConnection()
        voix_contact = ap.creer_piste(ap.decoder_pcm(_wav(1.2)), repetitions=1, pause_s=0.1)
        contact.addTrack(voix_contact)

        @contact.on("track")
        def sur_piste(piste):
            async def lire():
                while True:
                    try:
                        trame = await piste.recv()
                    except Exception:  # noqa: BLE001 — fin de l'appel
                        return
                    if any(bytes(trame.planes[0])[:400]):
                        recu["son"] += 1
            asyncio.ensure_future(lire())

        @contact.on("connectionstatechange")
        async def sur_etat():
            if contact.connectionState == "connected":
                await asyncio.sleep(3.0)           # le contact écoute l'ouverture puis répond
                voix_contact.lecture()

        async def faux_post(s, numero_id, chemin, corps):
            if chemin == "messages":
                g.messages.append(corps)
                return {"ok": True, "donnees": {"messages": [{"id": "wamid.x"}]}, "erreur": None}
            actions.append(corps.get("action"))
            if corps.get("action") == "connect":
                assert corps["to"] == CONTACT and corps["biz_opaque_callback_data"].startswith("agenda:")

                async def decrocher():
                    # « Meta » : le téléphone du contact sonne puis il décroche (réponse SDP par webhook)
                    await asyncio.sleep(0.5)
                    await contact.setRemoteDescription(RTCSessionDescription(sdp=corps["session"]["sdp"], type="offer"))
                    await contact.setLocalDescription(await contact.createAnswer())
                    await aw.traiter_webhook_appels(db, {"metadata": {"phone_number_id": "PN-STANDARD"}, "calls": [
                        {"id": "wacid.SORTANT", "event": "connect", "direction": "BUSINESS_INITIATED",
                         "to": CONTACT, "session": {"sdp_type": "answer", "sdp": contact.localDescription.sdp}}]})
                asyncio.ensure_future(decrocher())
                return {"ok": True, "donnees": {"calls": [{"id": "wacid.SORTANT"}]}, "erreur": None}
            return {"ok": True, "donnees": {"success": True}, "erreur": None}
        monkeypatch.setattr(ap, "_graph_post", faux_post)

        champs = la.valider_evenement(evenement(questions=evenement()["questions"][:2]), la.reglages_agenda({}))
        champs["client_id"] = "sawali"
        doc = la._nouvel_evenement(champs, par="Test", maintenant=MATIN)
        await db.liluvine_agenda.insert_one(dict(doc))
        await la.executer_echeances(db, lancer_en_fond=False)
        await contact.close()
        return doc["id"]

    ev_id = asyncio.run(asyncio.wait_for(scenario(), 60))
    assert actions == ["connect", "terminate"], actions
    assert recu["son"] > 10                                          # le contact a entendu Liluvine
    dit = " ".join(voix_dites)                                       # voix synthétisée phrase par phrase
    assert dit.startswith("Bonjour Awa, ici Liluvine") and "faire suite" in dit
    systeme, texte = prompts[0]
    assert "c'est TOI qui appelles" in systeme and "Commande reçue ?" in systeme and texte.startswith("Oui, la commande")
    ev = lancer(db.liluvine_agenda.find_one({"id": ev_id}, {"_id": 0}))
    assert ev["statut"] == "termine" and ev["tentatives"] == 1, ev.get("raison")
    r = ev["resultat"]
    assert r["fin"] == "au revoir" and r["resume"] == "Commande reçue, 25 000 F payés."
    assert [i["valeur"] for i in r["informations"]] == [True, 25000]
    assert [t["qui"] for t in r["transcription"]] == ["liluvine", "appelant", "liluvine"]
    assert r["transcription"][2]["texte"] == "Parfait, merci : Pour votre temps. Pour votre réponse. Au revoir !"
    assert r["qualite_audio"]["boucle_media"] is True and r["qualite_audio"]["sous_alimentations"] == 0
    assert r["cout"]["devise"] == "FCFA" and r["cout"]["secondes_facturees"] >= 6
    journal = lancer(db.wa_appels.find_one({"id": "wacid.SORTANT"}, {"_id": 0}))
    assert journal["direction"] == "sortant" and journal["motif"] == "Agenda — Relance" and journal["statut"] == "termine"
    assert journal["repondu_par"] == "Liluvine" and journal["liluvine"]["agenda"]["informations"][1]["valeur"] == 25000
    assert not ld._actifs


# ---------------------------------------------------------------------------
# Style oral (retour d'un vrai appel, appels entrants ET sortants) et identification de l'appelant
# ---------------------------------------------------------------------------

def test_nettoyage_du_texte_avant_la_voix():
    n = ld.nettoyer_pour_voix
    # Liste numérotée avec énumération entre parenthèses (cas réel du lot 69.2)
    assert n("Avec plaisir ! Pour vous orienter :\n1. Quel service souhaitez-vous ? "
             "(rendez-vous commercial, support technique…)\n2. Votre nom ?") == \
        "Avec plaisir ! Pour vous orienter : Quel service souhaitez-vous ? Votre nom ?"
    assert n("Les services :\n- Support\n- Vente\n• Formation") == "Les services : Support, Vente, Formation"
    assert n("Voici : 1. Le support 2. La vente") == "Voici : Le support, La vente"
    assert n("## **Horaires**\nNous ouvrons à 8 h.") == "Horaires, Nous ouvrons à 8 h."
    # Rien à retirer : nombres ordinaires et parenthèse simple gardés
    assert n("Nous fermons à 18. Nous restons là (le samedi aussi).") == "Nous fermons à 18. Nous restons là (le samedi aussi)."
    # Le nettoyage s'applique aussi via analyser_reponse (marqueurs de fin retirés)
    assert ld.analyser_reponse("1. Oui\n2. Non [FIN]") == ("Oui, Non", "fin")


def test_style_telephone_une_question_sans_resaluer():
    s = ld.style_telephone("Bonjour Awa ! Bien sûr. Quel service souhaitez-vous ? Et votre nom ?", deja_salue=True)
    assert s == "Bien sûr. Quel service souhaitez-vous ?"
    assert ld.style_telephone("Bonjour ! Comment allez-vous ?", deja_salue=False) == "Bonjour ! Comment allez-vous ?"
    assert ld.retirer_salutation("Rebonjour madame, je vous écoute.") == "Je vous écoute."
    assert ld.retirer_salutation("Bonjour") == "Bonjour"                       # rien d'autre : gardé
    for consigne in (ld.CONSIGNE_TELEPHONE, la.CONSIGNE_SORTANT):
        assert "JAMAIS de liste" in consigne and "Ne salue JAMAIS une seconde fois" in consigne
        assert "UNE seule question à la fois" in consigne
    p = ld.assembler_prompt("Base", contact_nom="+226 70 00 00 01", telephone=CONTACT, plateforme=None, ligne=None)
    assert "Appelant : inconnu (+22670000001)" in p                          # un numéro n'est pas un nom


def test_identification_de_l_appelant_numeros_formates(db):
    lancer(db.directory_contacts.insert_one({"id": "c1", "name": "Awa Kaboré", "whatsapp": "+226 70 00 00 01",
                                             "client_id": "sawali"}))
    lancer(db.tracked_users.insert_one({"id": "t1", "name": "Issa Traoré", "whatsapp_number": "+226-75-00-00-02",
                                        "client_id": "cl9"}))
    lancer(db.users.insert_one({"id": "cl1", "role": "client", "full_name": "Moussa Sawadogo",
                                "company": "Pharmacie du Centre", "phone": "(+226) 76 00 00 03"}))
    s = {"appel_proprio_numeros": "+226 77 00 00 04"}
    assert lancer(aw.identifier_appelant(db, "22670000001", s))["nom"] == "Awa Kaboré"
    r = lancer(aw.identifier_appelant(db, "22675000002", s))
    assert r["nom"] == "Issa Traoré" and r["source"] == "suivi" and r["client_id"] == "cl9"
    r = lancer(aw.identifier_appelant(db, "22676000003", s))
    assert r["nom"] == "Moussa Sawadogo (Pharmacie du Centre)" and r["client_id"] == "cl1"
    assert lancer(aw.identifier_appelant(db, "22677000004", s))["source"] == "proprietaire"
    assert lancer(aw.identifier_appelant(db, "22678000005", s))["nom"] is None
    # Webhook d'un appel entrant : le nom est inscrit au journal (plus « +226… » pour un utilisateur suivi)
    lancer(aw.traiter_webhook_appels(db, {"metadata": {"phone_number_id": "PN-STANDARD"}, "calls": [
        {"id": "in.1", "event": "connect", "from": "22675000002", "session": {"sdp": "v=0"}}]}))
    appel = lancer(db.wa_appels.find_one({"id": "in.1"}))
    assert appel["contact_nom"] == "Issa Traoré" and appel["appelant_source"] == "suivi"


# ---------------------------------------------------------------------------
# Lot 72 — alertes « Liluvine appelle … » (toast persistant de l'administrateur / superviseur)
# ---------------------------------------------------------------------------

def test_lot72_alerte_appel_sans_reponse_puis_nouvel_essai(db, monkeypatch):
    # Un appel sans réponse : l'alerte passe de « appel » à « nouvelle tentative » avec l'heure locale du prochain essai
    g = FauxGraph(permission="permanent")
    monkeypatch.setattr(ap, "_graph_get", g.get)
    monkeypatch.setattr(ap, "_graph_post", g.post)
    vues = []

    async def sans_reponse(db_, s, cfga, ev, **kw):
        # Pendant l'appel, l'alerte existe déjà à l'état « appel »
        vues.append(await db_.liluvine_agenda_alertes.find_one({"ev_id": ev["id"]}, {"_id": 0}))
        return {"resultat": "sans_reponse", "raison": "pas de réponse", "call_id": "c1"}
    monkeypatch.setattr(la, "appeler_et_converser", sans_reponse)
    ev = inserer(db, tentatives_max=2, intervalle_min=15)
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    assert vues[0]["etat"] == "appel" and vues[0]["type_libelle"] and vues[0]["tentative"] == 1
    alerte = lancer(db.liluvine_agenda_alertes.find_one({"ev_id": ev["id"]}, {"_id": 0}))
    # 10:15 UTC = 10:15 à Ouagadougou (UTC+0)
    assert alerte["etat"] == "nouvelle_tentative" and alerte["resultat"] == "pas de réponse — nouvel essai à 10:15"


def test_lot72_alerte_conversation_avec_resume_et_route(db, monkeypatch):
    # Conversation : l'alerte se termine avec le résumé de Liluvine ; la route est réservée à l'encadrement
    g = FauxGraph(permission="permanent")
    monkeypatch.setattr(ap, "_graph_get", g.get)
    monkeypatch.setattr(ap, "_graph_post", g.post)

    async def conversation(db_, s, cfga, ev, **kw):
        return {"resultat": "decroche", "call_id": "wacid.A", "fin": "au revoir", "duree_s": 30, "transfert": False,
                "transcription": [{"qui": "liluvine", "texte": "Bonjour", "t": 0},
                                  {"qui": "appelant", "texte": "Oui merci", "t": 3}], "mesures": {}}
    monkeypatch.setattr(la, "appeler_et_converser", conversation)

    async def extraction(systeme, texte, max_jetons=900):
        return {"texte": json.dumps({"resume": "Contact joint, tout va bien.", "reponses": {},
                                     "action_suivante": {"texte": "", "type": "aucune", "date": None}}),
                "entree": 10, "sortie": 5}
    monkeypatch.setattr(la, "llm_texte", extraction)
    ev = inserer(db)
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    alerte = lancer(db.liluvine_agenda_alertes.find_one({"ev_id": ev["id"]}, {"_id": 0}))
    assert alerte["etat"] == "termine" and alerte["resultat"] == "Conversation terminée"
    assert alerte["resume"] == "Contact joint, tout va bien."
    c = _client_http(db)
    assert c.get("/api/admin/liluvine-agenda/alertes", headers={"X-User": "client"}).status_code == 403
    corps = c.get("/api/admin/liluvine-agenda/alertes", headers={"X-User": "sup"}).json()
    assert [a["ev_id"] for a in corps["alertes"]] == [ev["id"]] and corps["server_now"]
    # Lecture incrémentale : seules les alertes modifiées depuis `since` (bornes comprises : une alerte modifiée
    # au même instant est renvoyée plutôt que perdue ; le portail l'ignore si rien n'a changé)
    plus_tard = "2099-01-01T00:00:00+00:00"
    assert c.get("/api/admin/liluvine-agenda/alertes", params={"since": plus_tard},
                 headers={"X-User": "sup"}).json()["alertes"] == []


def test_lot72_libelles_de_resultat():
    # Phrases affichées dans le toast pour chaque fin d'appel
    assert la.libelle_resultat({"resultat": "refuse"}, {"resultat": "refuse"}) == ("refuse", "Appel refusé par le contact")
    assert la.libelle_resultat({"resultat": "sans_reponse"}, {"resultat": "sans_reponse"}) == ("sans_reponse", "Pas de réponse")
    etat, phrase = la.libelle_resultat({"resultat": "echec", "raison": "connexion audio impossible"}, {"resultat": "echec"})
    assert etat == "echec" and "connexion audio impossible" in phrase


# ---------------------------------------------------------------------------
# Lot 73 — partage de Liluvine par superviseur, relance des demandes d'autorisation, voix clonée → Liluvine
# ---------------------------------------------------------------------------

def test_lot73_partage_par_superviseur(db):
    # Par défaut le superviseur voit tout ; l'administrateur restreint support@ à l'agenda seul
    c = _client_http(db)
    h = {"X-User": "support"}
    assert c.get("/api/me/liluvine-partage", headers=h).json() == {
        "restreint": False, "elements": ["agenda", "alertes", "historique", "pro"]}
    assert c.get("/api/admin/liluvine-agenda/alertes", headers=h).status_code == 200
    # Seul l'administrateur règle le partage
    assert c.put("/api/admin/liluvine-partage", json={"email": "support@sawalismartsystems.com", "elements": []},
                 headers={"X-User": "sup"}).status_code == 403
    assert c.put("/api/admin/liluvine-partage", json={"email": "Support@SawaliSmartSystems.com", "elements": ["agenda"]},
                 headers={"X-User": "admin"}).json()["partage"] == ["agenda"]
    assert c.get("/api/me/liluvine-partage", headers=h).json() == {"restreint": True, "elements": ["agenda"]}
    # Agenda autorisé, notifications refusées par le serveur
    assert c.get("/api/admin/liluvine-agenda", headers=h).status_code == 200
    r = c.get("/api/admin/liluvine-agenda/alertes", headers=h)
    assert r.status_code == 403 and "n'est pas partagé" in r.json()["detail"]
    # Un autre superviseur (non réglé) et l'administrateur gardent tout
    assert c.get("/api/admin/liluvine-agenda/alertes", headers={"X-User": "sup"}).status_code == 200
    assert c.get("/api/me/liluvine-partage", headers={"X-User": "admin"}).json()["restreint"] is False
    # Rien de partagé : l'agenda est refusé aussi ; « par défaut » (null) rend tout
    c.put("/api/admin/liluvine-partage", json={"email": "support@sawalismartsystems.com", "elements": []}, headers={"X-User": "admin"})
    assert c.get("/api/admin/liluvine-agenda", headers=h).status_code == 403
    c.put("/api/admin/liluvine-partage", json={"email": "support@sawalismartsystems.com", "elements": None}, headers={"X-User": "admin"})
    assert c.get("/api/admin/liluvine-agenda", headers=h).status_code == 200
    # Élément inconnu refusé ; la liste des superviseurs vient des comptes
    assert c.put("/api/admin/liluvine-partage", json={"email": "x@y.z", "elements": ["inconnu"]},
                 headers={"X-User": "admin"}).status_code == 422
    lancer(db.users.insert_one({"id": "s2", "role": "superviseur", "email": "support@sawalismartsystems.com", "full_name": "Support"}))
    lecture = c.get("/api/admin/liluvine-partage", headers={"X-User": "admin"}).json()
    assert [x["email"] for x in lecture["superviseurs"]] == ["support@sawalismartsystems.com"]


def test_lot73_relance_automatique_de_la_demande_d_autorisation(db, monkeypatch):
    # Sans réponse 24 h après la 1re demande : 2e demande envoyée ; la 3e est refusée par la limite Meta (2 / 7 jours)
    g = FauxGraph()
    monkeypatch.setattr(ap, "_graph_get", g.get)
    monkeypatch.setattr(ap, "_graph_post", g.post)
    lancer(db.settings.update_one({"_id": "global"}, {"$set": {"liluvine_agenda_attente_autorisation_h": 168}}))
    ev = inserer(db, intervalle_min=60)
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    assert len(g.messages) == 1
    # 23 h plus tard : pas encore de relance
    monkeypatch.setattr(ap, "_maintenant", lambda: datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc))
    lancer(db.liluvine_agenda.update_one({"id": ev["id"]}, {"$set": {"prochaine_tentative": "2026-10-07T09:00:00+00:00"}}))
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    assert len(g.messages) == 1
    # 24 h plus tard : relance automatique
    monkeypatch.setattr(ap, "_maintenant", lambda: datetime(2026, 10, 7, 10, 1, tzinfo=timezone.utc))
    lancer(db.liluvine_agenda.update_one({"id": ev["id"]}, {"$set": {"prochaine_tentative": "2026-10-07T10:01:00+00:00"}}))
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    doc = lancer(db.liluvine_agenda.find_one({"id": ev["id"]}))
    assert len(g.messages) == 2 and doc["autorisation_demandes"] == 2
    assert doc["historique"][-1]["resultat"] == "autorisation redemandée (relance automatique)"
    # Réglage désactivé : plus de relance automatique
    lancer(db.settings.update_one({"_id": "global"}, {"$set": {"liluvine_agenda_relance_autorisation": False}}))
    monkeypatch.setattr(ap, "_maintenant", lambda: datetime(2026, 10, 8, 11, 0, tzinfo=timezone.utc))
    lancer(db.liluvine_agenda.update_one({"id": ev["id"]}, {"$set": {"prochaine_tentative": "2026-10-08T11:00:00+00:00"}}))
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    assert len(g.messages) == 2


def test_lot73_bouton_renvoyer_la_demande(db, monkeypatch):
    # Bouton « Renvoyer la demande » : envoi, délai d'attente qui repart, puis limite Meta avec date du prochain essai
    g = FauxGraph()
    monkeypatch.setattr(ap, "_graph_get", g.get)
    monkeypatch.setattr(ap, "_graph_post", g.post)
    ev = inserer(db)
    lancer(la.executer_echeances(db, lancer_en_fond=False))                     # 1re demande (10:00)
    c = _client_http(db)
    h = {"X-User": "admin"}
    # Moins de 24 h après : refus avec la date du prochain essai possible (heure de Ouagadougou)
    r = c.post(f"/api/admin/liluvine-agenda/{ev['id']}/redemander-autorisation", headers=h)
    assert r.status_code == 409 and "prochaine demande possible le 07/10/2026 à 10:00" in r.json()["detail"]
    # Le lendemain : renvoyée, délai d'attente qui repart de zéro
    monkeypatch.setattr(ap, "_maintenant", lambda: datetime(2026, 10, 7, 10, 30, tzinfo=timezone.utc))
    r = c.post(f"/api/admin/liluvine-agenda/{ev['id']}/redemander-autorisation", headers=h)
    assert r.status_code == 200 and len(g.messages) == 2
    doc = r.json()["evenement"]
    assert doc["statut"] == "attente_autorisation" and doc["autorisation_demandee_le"] == "2026-10-07T10:30:00+00:00"
    assert doc["autorisation_demandes"] == 2 and doc["historique"][-1]["raison"] == "par Admin"
    # 3e demande dans la semaine : limite Meta (2 par 7 jours) → prochaine possible 7 jours après la 1re
    monkeypatch.setattr(ap, "_maintenant", lambda: datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc))
    r = c.post(f"/api/admin/liluvine-agenda/{ev['id']}/redemander-autorisation", headers=h)
    assert r.status_code == 409 and "13/10/2026 à 10:00" in r.json()["detail"]


def test_lot73_voix_clonee_transmise_a_liluvine(db, monkeypatch):
    # Voice Studio : « 🤖 Transmettre à Liluvine » règle le moteur ElevenLabs et la voix de Liluvine
    c = _client_http(db)
    lancer(db.eleven_voices.insert_one({"id": "v1", "user_id": "a1", "name": "Voix de Mariam",
                                        "voice_id": "AbCdEf123456", "provider": "elevenlabs"}))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert c.post("/api/me/liluvine-voix", json={"voice_id": "AbCdEf123456"}, headers={"X-User": "admin"}).status_code == 422
    monkeypatch.setenv("ELEVENLABS_API_KEY", "cle-factice")
    assert c.post("/api/me/liluvine-voix", json={"voice_id": "AbCdEf123456"}, headers={"X-User": "client"}).status_code == 403
    assert c.post("/api/me/liluvine-voix", json={"voice_id": "inconnue1"}, headers={"X-User": "admin"}).status_code == 404
    r = c.post("/api/me/liluvine-voix", json={"voice_id": "AbCdEf123456"}, headers={"X-User": "admin"})
    assert r.status_code == 200 and r.json()["nom"] == "Voix de Mariam"
    s = lancer(db.settings.find_one({"_id": "global"}))
    assert s["liluvine_decroche_voix"] == "elevenlabs" and s["liluvine_decroche_voix_elevenlabs"] == "AbCdEf123456"
    lecture = c.get("/api/me/liluvine-voix", headers={"X-User": "client"}).json()
    assert lecture["voice_id"] == "AbCdEf123456" and lecture["peut_modifier"] is False
