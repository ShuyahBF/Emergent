"""Lot 320 — les 3 boutons « Avec contrat / Sans contrat / En express » : marqueur, réponses vérifiées, clic traité sans l'IA."""
import asyncio

from mongomock_motor import AsyncMongoMockClient

from routes.niveaux_boutons import BOUTONS, MARQUEUR, retirer_marqueur, texte_choix, texte_contrat, traiter_clic
from routes.niveaux_service import normaliser_config


def _run(c):
    return asyncio.get_event_loop().run_until_complete(c)


CONFIG = normaliser_config({"actif": True, "niveaux": {
    "contrat": {"delai": "72 heures maximum", "description": "Prise en charge prioritaire"},
    "standard": {"delai": "Selon disponibilité"}, "express": {"delai": "2 heures"}}})


def test_trois_boutons_titres_courts():
    assert [t for _, t in BOUTONS] == ["Avec contrat", "Sans contrat", "En express"]
    assert all(len(t) <= 20 for _, t in BOUTONS)                         # limite WhatsApp


def test_marqueur_retire_du_texte():
    texte, present = retirer_marqueur(f"Je peux vous aider.\n{MARQUEUR}")
    assert present and MARQUEUR not in texte and texte == "Je peux vous aider."
    assert retirer_marqueur("Bonjour") == ("Bonjour", False)


def test_contrat_valide_donne_les_infos_sans_montant():
    fiche = {"etat": "valide", "numero": "CT-12", "fin": "2027-03-31", "mois_restants": 5, "echeance_prochaine": "2026-11-05", "services_suspendus": []}
    txt, applicable = texte_contrat(fiche, CONFIG["niveaux"]["contrat"])
    assert applicable and "CT-12" in txt and "31/03/2027" in txt and "5 mois" in txt and "72 heures maximum" in txt and "FCFA" not in txt


def test_contrat_en_retard_ou_absent_est_dit_clairement():
    txt, ok = texte_contrat({"etat": "retard", "numero": "CT-12", "jours_retard": 9}, CONFIG["niveaux"]["contrat"])
    assert not ok and "retard de paiement" in txt and "9 jour" in txt
    txt, ok = texte_contrat({"etat": "aucun", "statut_libelle": "Contrat expiré"}, CONFIG["niveaux"]["contrat"])
    assert not ok and "pas de contrat valide" in txt.lower() and "contrat expiré" in txt.lower()


def test_choix_standard_et_express():
    txt, rep = texte_choix("standard", CONFIG, {}, None)
    assert "Selon disponibilité" in txt and not rep
    txt, rep = texte_choix("express", CONFIG, {}, 25000)
    assert "2 heures" in txt and "25 000 FCFA" in txt and "OUI" in txt
    assert "à préciser avant l'intervention" in texte_choix("express", CONFIG, {}, 0)[0]
    # contrat non applicable → les 3 boutons sont reproposés
    assert texte_choix("contrat", CONFIG, {"etat": "aucun"}, None)[1] is True


def test_clic_traite_sans_ia_et_journalise():
    base = AsyncMongoMockClient()["test_niv_320"]
    _run(base.settings.insert_one({"_id": "global", "niveaux_service": {k: v for k, v in CONFIG.items() if k != "configure"}}))
    envoyes, boutons = [], []

    async def envoyer(a, t, **k):
        envoyes.append(t); return {"ok": True, "message_id": "m1"}

    async def prop(a, t):
        boutons.append(t); return {"ok": True}
    assert _run(traiter_clic(base, bouton_id="niv:contrat", chiffres="22670001122", destinataire="+22670001122", wa_send_text=envoyer, wa_send_boutons=prop))
    assert "pas de contrat valide" in envoyes[0].lower() and boutons                     # contact inconnu : pas de contrat → boutons reproposés
    assert _run(base.whatsapp_messages.find_one({"ai_source": "niveaux_boutons"}))
    assert _run(traiter_clic(base, bouton_id="autre:x", chiffres="22670001122", destinataire="+1", wa_send_text=envoyer, wa_send_boutons=prop)) is False


def test_clic_ignore_si_niveaux_non_configures():
    base = AsyncMongoMockClient()["test_niv_320b"]

    async def envoyer(a, t, **k):
        raise AssertionError("rien ne doit partir")
    assert _run(traiter_clic(base, bouton_id="niv:express", chiffres="22670001122", destinataire="+1", wa_send_text=envoyer, wa_send_boutons=None)) is False


def test_clic_avec_contrat_valide_verifie_le_vrai_contrat():
    """Contact relié (par sa société) à un client dont le contrat est en cours et à jour → la réponse donne ses infos, sans reproposer."""
    from datetime import datetime, timedelta, timezone
    auj = datetime.now(timezone.utc).date()
    base = AsyncMongoMockClient()["test_niv_320c"]
    _run(base.settings.insert_one({"_id": "global", "niveaux_service": {k: v for k, v in CONFIG.items() if k != "configure"}}))
    _run(base.users.insert_one({"id": "cli-1", "role": "client", "company": "Pharmacie Amitié", "email": "pharma@test.bf", "contract_number": "CT-77",
                                "contract_start_at": (auj - timedelta(days=60)).isoformat(), "contract_end_at": (auj + timedelta(days=300)).isoformat(),
                                "last_payment_at": auj.isoformat(), "contract_billing_period": "monthly", "flat_rate": 25000}))
    _run(base.directory_contacts.insert_one({"id": "c1", "client_id": "cli-1", "company": "Pharmacie Amitié", "whatsapp": "+22670001122", "name": "Awa"}))
    envoyes, boutons = [], []

    async def envoyer(a, t, **k):
        envoyes.append(t); return {"ok": True}

    async def prop(a, t):
        boutons.append(t); return {"ok": True}
    assert _run(traiter_clic(base, bouton_id="niv:contrat", chiffres="22670001122", destinataire="+22670001122", wa_send_text=envoyer, wa_send_boutons=prop))
    assert "est valide" in envoyes[0] and "CT-77" in envoyes[0] and "72 heures maximum" in envoyes[0] and not boutons
