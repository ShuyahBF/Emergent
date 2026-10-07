"""Lot 74 — corrections des modèles WhatsApp Meta (anomalies A1 à A6) et message d'absence WhatsApp."""
import ast
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
mongomock_motor = pytest.importorskip("mongomock_motor")

import modeles_meta  # noqa: E402
from routes import message_absence as absence  # noqa: E402


# ---------- A1 : confirmation de paiement client distincte du reçu de caisse ----------
def test_a1_par_defaut_un_modele_propre_aux_clients():
    nom, langue, remarque = modeles_meta.modele_paiement_client(None, {})
    assert nom == "confirmation_paiement_client" and langue == "fr" and remarque is None


def test_a1_fiche_client_prioritaire_puis_reglage_general():
    assert modeles_meta.modele_paiement_client("mon_modele", {"wa_template_client_payment": "general"})[0] == "mon_modele"
    assert modeles_meta.modele_paiement_client("", {"wa_template_client_payment": "general",
                                                    "wa_template_client_payment_language": "en"})[:2] == ("general", "en")


def test_a1_fiche_avec_le_modele_du_recu_de_caisse_ignoree():
    # L'ancien défaut (reçu de caisse : 4 variables + PDF) ne peut pas servir à une confirmation à 5 variables
    nom, _, remarque = modeles_meta.modele_paiement_client("confirmation_paiement_avecrecu", {})
    assert nom == "confirmation_paiement_client" and "reçu de caisse" in remarque
    nom, _, _ = modeles_meta.modele_paiement_client("recu_perso", {"wa_template_receipt_name": "recu_perso"})
    assert nom == "confirmation_paiement_client"


def test_a1_a2_branches_dans_le_serveur():
    p05 = (RACINE / "server_parts/p05_admin_crm_documents.py").read_text(encoding="utf-8")
    assert "_modeles_meta.modele_paiement_client(" in p05 and 'or "confirmation_paiement_avecrecu"' not in p05
    p17 = (RACINE / "server_parts/p17_demarrage_planificateur.py").read_text(encoding="utf-8")
    assert "_modeles_meta.parametres_alerte_retard(settings_doc)" in p17
    assert "_wa_send_template(super_wa, wa_template, wa_lang, components)" in p17
    p01 = (RACINE / "server_parts/p01_sante_auth_public.py").read_text(encoding="utf-8")
    assert "import modeles_meta as _modeles_meta" in p01


# ---------- A2 : alerte de retard réglable ----------
def test_a2_alerte_retard_reglages():
    assert modeles_meta.parametres_alerte_retard({}) == ("alerte_retard_paiement", "fr", "")
    assert modeles_meta.parametres_alerte_retard({"contract_overdue_wa_template": "retard", "contract_overdue_wa_language": "fr_FR",
                                                  "super_admin_phone": " 22670000000 "}) == ("retard", "fr_FR", "22670000000")


def test_a2_ecran_dans_les_parametres():
    page = (RACINE.parent / "frontend/src/pages/admin/AdminSettings.jsx").read_text(encoding="utf-8")
    for cle in ("contract_overdue_wa_template", "contract_overdue_wa_language", "super_admin_phone",
                "wa_template_client_payment", "wa_template_client_payment_language"):
        assert f'upd("{cle}"' in page, cle
    assert '<Filterable title="Contrats — Seuil de retard de paiement (par défaut)"' in page


# ---------- A3 : renvoi du WhatsApp d'un ticket ----------
def _fonction(fichier, nom):
    source = (RACINE / fichier).read_text(encoding="utf-8")
    noeud = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.AsyncFunctionDef) and n.name == nom)
    return ast.get_source_segment(source, noeud)


def test_a3_renvoi_ticket_lit_les_vrais_tickets():
    code = _fonction("server_parts/p18_abonnements_tickets.py", "me_ticket_resend_wa")
    assert "db.support_tickets.find_one" in code and "db.tickets.find_one" not in code
    assert 'ticket.get("motif")' in code and "wa_template_ticket_language" in code
    assert '_wa_send_template(phone, tpl_name, tpl_lang, components)' in code


# ---------- A4 : retours à la ligne (déjà nettoyés par _wa_send_template) ----------
def test_a4_retours_a_la_ligne_nettoyes_avant_meta():
    from routes.whatsapp_helpers import _wa_clean_template_components
    comps = [{"type": "body", "parameters": [{"type": "text", "text": "ligne 1\nligne 2\r\n\tligne 3"}]}]
    texte = _wa_clean_template_components(comps)[0]["parameters"][0]["text"]
    assert "\n" not in texte and "\t" not in texte and "ligne 1 · ligne 2 · ligne 3" == texte


# ---------- A5 : envois programmés complets ----------
def test_a5_envoi_groupe_programme_garde_les_boutons():
    source = (RACINE / "server_parts/p12_sms.py").read_text(encoding="utf-8")
    assert '"button_specs": payload.button_specs,\n            "scheduled_at": sched_dt' in source


def test_a5_automatisation_differee_garde_les_jetons_de_l_evenement():
    code = _fonction("server_parts/p14_whatsapp_admin_automations.py", "_run_scheduled_whatsapp")
    assert 'sc.get("extra_ctx")' in code


# ---------- A6 : rappels de RDV par modèle Meta ----------
def _planning(db, envois):
    from fastapi import FastAPI
    from routes.planning import attach_planning_routes

    async def envoyer_texte(to, texte):
        envois.append(("texte", to, texte))
        return {"ok": True, "message_id": "t1"}

    async def envoyer_modele(to, nom, langue, composants):
        envois.append(("modele", to, nom, langue, composants))
        return {"ok": True, "message_id": "m1"}

    return attach_planning_routes(
        api=FastAPI(), db=db, get_current_user=lambda: {}, get_current_admin=lambda: {},
        _is_admin_or_superviseur=lambda u: True, _resolve_visible_client_ids=None, _is_super_admin=lambda u: True,
        _public_base_url=lambda r: "", wa_send_text=envoyer_texte, wa_send_template=envoyer_modele)


async def _rdv(db):
    debut = (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat()
    await db.planning_appointments.insert_one({"id": "r1", "start_at": debut, "patient": "Awa", "medecin": "Dr Ki",
                                               "motif": "Contrôle", "patient_phone": "22670000001"})


def test_a6_rappel_par_modele_quand_il_est_regle():
    async def scenario():
        db = mongomock_motor.AsyncMongoMockClient()["t"]
        await db.settings.insert_one({"_id": "global", "planning_reminder_wa_template": "rappel_rdv",
                                      "planning_reminder_wa_language": "fr"})
        await _rdv(db)
        envois = []
        res = await _planning(db, envois)["run_planning_wa_reminders"]()
        assert res["sent"] == 1
        genre, to, nom, langue, comps = envois[0]
        assert (genre, nom, langue) == ("modele", "rappel_rdv", "fr")
        valeurs = [p["text"] for p in comps[0]["parameters"]]
        assert valeurs[0] == "Awa" and valeurs[1] == "Dr Ki" and valeurs[3] == "Contrôle" and len(valeurs) == 4
    asyncio.run(scenario())


def test_a6_sans_modele_le_texte_libre_reste():
    async def scenario():
        db = mongomock_motor.AsyncMongoMockClient()["t"]
        await _rdv(db)
        envois = []
        await _planning(db, envois)["run_planning_wa_reminders"]()
        assert envois[0][0] == "texte" and "Awa" in envois[0][2]
    asyncio.run(scenario())


# ---------- Message d'absence ----------
REGLAGES = {"wa_absence_actif": True, "business_open_time": "08:00", "business_close_time": "17:30",
            "business_days": [0, 1, 2, 3, 4]}
MERCREDI_SOIR = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)      # 7 octobre 2026 = mercredi
MERCREDI_MATIN = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
SAMEDI_MIDI = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def test_absence_heures_et_jours():
    assert absence.est_ouvert(REGLAGES, MERCREDI_MATIN)
    assert not absence.est_ouvert(REGLAGES, MERCREDI_SOIR)
    assert not absence.est_ouvert(REGLAGES, SAMEDI_MIDI)
    assert not absence.est_ouvert(REGLAGES, datetime(2026, 10, 7, 17, 45, tzinfo=timezone.utc))  # minutes comptées
    nuit = {**REGLAGES, "business_open_time": "20:00", "business_close_time": "02:00"}
    assert absence.est_ouvert(nuit, datetime(2026, 10, 7, 23, 0, tzinfo=timezone.utc))


def test_absence_decisions():
    d = lambda r, **k: absence.decider(r, numero=k.get("numero", "22670000001"), texte_recu=k.get("texte", "Bonjour"),
                                       maintenant=k.get("quand", MERCREDI_SOIR), dernier_envoi=k.get("dernier"))
    assert d(REGLAGES) == (True, "envoye")
    assert d({**REGLAGES, "wa_absence_actif": False})[1] == "desactive"
    assert d(REGLAGES, quand=MERCREDI_MATIN)[1] == "heures_ouvrables"
    assert d({**REGLAGES, "wa_absence_mode": "toujours"}, quand=MERCREDI_MATIN)[0] is True
    assert d(REGLAGES, texte="!garde")[1] == "commande"
    assert d({**REGLAGES, "wa_absence_exclus": "+226 70 00 00 01, 22671111111"})[1] == "numero_exclu"
    assert d(REGLAGES, dernier=(MERCREDI_SOIR - timedelta(hours=3)).isoformat())[1] == "deja_envoye"
    assert d(REGLAGES, dernier=(MERCREDI_SOIR - timedelta(hours=13)).isoformat())[0] is True


def test_absence_texte_et_marqueurs():
    t = absence.composer_texte({**REGLAGES, "wa_absence_texte": "Bonjour {nom}, ouverts de {ouverture} à {fermeture}. {autre}"}, "Awa")
    assert t == "Bonjour Awa, ouverts de 08:00 à 17:30. {autre}"
    assert "cher client" in absence.composer_texte(REGLAGES, None)


def test_absence_envoyee_une_fois_et_copiee_dans_le_fil():
    async def scenario():
        db = mongomock_motor.AsyncMongoMockClient()["t"]
        envois = []

        async def envoyer(to, texte):
            envois.append((to, texte))
            return {"ok": True, "message_id": "wamid.1"}
        args = dict(reglages=REGLAGES, numero="22670000001", de="22670000001", texte_recu="Bonjour", nom="Awa",
                    client_id="c1", contact_id="k1", send_text=envoyer, maintenant=MERCREDI_SOIR)
        r1 = await absence.traiter_message_entrant(db, **args)
        r2 = await absence.traiter_message_entrant(db, **{**args, "maintenant": MERCREDI_SOIR + timedelta(hours=1)})
        assert r1["envoye"] and not r2["envoye"] and r2["raison"] == "deja_envoye"
        assert len(envois) == 1
        copie = await db.whatsapp_messages.find_one({"ai_source": "message_absence"})
        assert copie["direction"] == "outbound" and copie["client_id"] == "c1" and "Awa" in copie["body"]
    asyncio.run(scenario())


def test_absence_branchee_sur_la_reception_whatsapp():
    source = (RACINE / "server_parts/p12_sms.py").read_text(encoding="utf-8")
    assert "from routes.message_absence import traiter_message_entrant as _absence_entrant" in source
    page = (RACINE.parent / "frontend/src/pages/admin/AdminSettings.jsx").read_text(encoding="utf-8")
    assert '<Filterable title="🌙 Message d\'absence WhatsApp"' in page and 'upd("wa_absence_texte"' in page
