"""Lot 179 — Liluvine : délai anti-répétition plafonné (plus de silence à la 2e question) et consignes de conversation.
Lancer : cd backend && python -m pytest tests/test_lot179_liluvine_conversation.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.liluvine_wa_autoreply import (  # noqa: E402
    COOLDOWN_DEFAUT_SECONDS, COOLDOWN_MAX_SECONDS, consignes_conversation, delai_anti_repetition,
)


def test_delai_plafonne_et_zero_respecte():
    assert delai_anti_repetition(60) == COOLDOWN_MAX_SECONDS      # l'ancien défaut de 60 s ne bloque plus la conversation
    assert delai_anti_repetition("120") == COOLDOWN_MAX_SECONDS
    assert delai_anti_repetition(0) == 0                          # 0 = pas de délai (avant : retombait à 60)
    assert delai_anti_repetition(3) == 3
    assert delai_anti_repetition(None) == COOLDOWN_DEFAUT_SECONDS
    assert delai_anti_repetition("abc") == COOLDOWN_DEFAUT_SECONDS
    assert delai_anti_repetition(-5) == 0


def test_consignes_sans_re_presentation_ni_catalogue():
    for connue in (True, False):
        t = consignes_conversation(connue)
        assert "ne te présente" in t.lower() and "JAMAIS la liste de tous les logiciels" in t
    assert "offre de ce client" in consignes_conversation(True)
    assert "UNE seule question" in consignes_conversation(False)


def test_historique_rejoue_au_modele_lot182():
    """Lot 182 — la question précédente de Liluvine est rejouée, sinon « Koloko » est pris pour une nouvelle salutation."""
    from routes.liluvine_wa_autoreply import historique_pour_llm
    docs = [
        {"role": "assistant", "content": "message orphelin"},                   # ne peut pas ouvrir l'historique
        {"role": "user", "content": "Problème avec mon logiciel"},
        {"role": "assistant", "content": "Quel est le nom de votre logiciel ?"},
        {"role": "user", "content": "Koloko"},                                 # sans réponse : retiré (c'est le nouveau message)
        {"role": "tool", "content": "x"}, {"role": "user", "content": "  "},
    ]
    h = historique_pour_llm(docs)
    assert h == [{"role": "user", "content": "Problème avec mon logiciel"},
                 {"role": "assistant", "content": "Quel est le nom de votre logiciel ?"}]
    assert historique_pour_llm([]) == [] and historique_pour_llm(None) == []
    fusion = historique_pour_llm([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}, {"role": "assistant", "content": "c"}])
    assert fusion == [{"role": "user", "content": "a\nb"}, {"role": "assistant", "content": "c"}]
    assert len(historique_pour_llm([{"role": "user", "content": "x" * 5000}, {"role": "assistant", "content": "y"}])[0]["content"]) == 1200


def test_prompt_selon_contrat_lot183():
    from routes.liluvine_wa_autoreply import prompt_selon_contrat
    s = {"liluvine_wa_client_prompt": " À JOUR ", "liluvine_wa_client_retard_prompt": "RETARD"}
    assert prompt_selon_contrat(s, "valide") == "À JOUR"
    assert prompt_selon_contrat(s, "retard") == "RETARD" and prompt_selon_contrat(s, "aucun") == "RETARD"
    assert prompt_selon_contrat(s, None) == "" and prompt_selon_contrat(s, "inconnu") == ""   # état inconnu : prompt du compte
    assert prompt_selon_contrat({}, "valide") == "" and prompt_selon_contrat(None, "retard") == ""


def test_consignes_reglables_et_recherche_lot184():
    from routes.liluvine_wa_autoreply import consignes_conversation, requete_recherche
    # texte par défaut : base de connaissances uniquement, rien d'inventé, historique disponible
    d = consignes_conversation(False)
    assert "UNIQUEMENT à partir de la base de connaissances" in d and "N'invente rien" in d and "ne dis jamais que tu n'y as pas accès" in d
    # texte réglé : remplace la base, la phrase sur l'offre reste
    t = consignes_conversation(True, "  MES CONSIGNES  ")
    assert "MES CONSIGNES" in t and "N'invente rien" not in t and "offre de ce client" in t
    # requête Qdrant : les deux messages précédents du correspondant précèdent le message courant
    h = [{"role": "user", "content": "Comment faire une vente"}, {"role": "assistant", "content": "ok"},
         {"role": "user", "content": "Aizenta"}, {"role": "assistant", "content": "ok2"}]
    assert requete_recherche("Historique", h) == "Comment faire une vente Aizenta Historique"
    assert requete_recherche("Koloko", []) == "Koloko" and len(requete_recherche("x" * 900, [])) == 500


def test_choix_par_numero_lot185():
    from routes.liluvine_wa_autoreply import traduire_choix_numerique
    h = [{"role": "user", "content": "J'ai un souci"},
         {"role": "assistant", "content": "Quelle catégorie ?\n1. Technique\n2) *Comptabilité*\n3 - Commercial\n4️⃣ Autre\nRépondez par le numéro."}]
    assert traduire_choix_numerique("2", h) == "2 (option 2 : Comptabilité)"
    assert traduire_choix_numerique(" N°3. ", h) == "N°3. (option 3 : Commercial)"
    assert traduire_choix_numerique("4", h) == "4 (option 4 : Autre)"
    assert traduire_choix_numerique("9", h) == "9"                                    # numéro absent de la liste
    assert traduire_choix_numerique("2 factures impayées", h) == "2 factures impayées"  # phrase : jamais touchée
    assert traduire_choix_numerique("2", []) == "2"                                   # pas de liste : inchangé
    assert traduire_choix_numerique("", h) == ""


def test_donnees_du_compte_reservees_a_l_equipe_lot189():
    from routes.liluvine_wa_autoreply import est_membre_equipe
    comptes = [
        {"id": "a1", "role": "admin", "phone": "+226 58 43 70 50"},
        {"id": "s1", "role": "superviseur", "whatsapp": "22670112233"},
        {"id": "cl", "role": "client", "phone": "+22675000000"},                            # client : aucun rôle d'équipe
        {"id": "u9", "role": "agent", "parent_client_id": "sawali", "phone": "70 99 88 77 66"},  # rattaché au compte
    ]
    assert est_membre_equipe("22658437050", comptes, "sawali") is True        # espaces et signes ignorés
    assert est_membre_equipe("+226 70 11 22 33", comptes, "sawali") is True   # champ whatsapp
    assert est_membre_equipe("22699887766", comptes, "sawali") is True        # compte rattaché au tenant
    assert est_membre_equipe("22675000000", comptes, "sawali") is False       # client : jamais
    assert est_membre_equipe("22600000000", comptes, "sawali") is False       # inconnu
    assert est_membre_equipe("123", comptes, "sawali") is False and est_membre_equipe("", [], "sawali") is False


def test_signature_en_un_seul_exemplaire_lot191():
    from routes.liluvine_wa_autoreply import historique_pour_llm, retirer_signatures_fin
    base = "Pour faire un inventaire, ouvrez le menu Stock.\n\n1. Choisir le magasin\n2. Lancer le comptage"
    triple = base + "\n\n— visitez notre site www.sawalismartsystems.com\n\n— visitez notre site www.sawalismartsystems.com\n\n— visitez notre site\nwww.sawalismartsystems.com"
    assert retirer_signatures_fin(triple) == base                                   # 3 copies → texte nu
    assert retirer_signatures_fin(base + "\n\n— Illiass (Commercial), assistant Liluvine 🤖") == base
    assert retirer_signatures_fin(base + "\n\n— 🤖 Réponse automatique Liluvine PRO") == base
    assert retirer_signatures_fin(base + "\n\nMa signature perso", ["Ma signature perso"]) == base   # signature réglée
    assert retirer_signatures_fin("— Option A\n— Option B") == "— Option A\n— Option B"   # tirets d'une liste : conservés
    assert retirer_signatures_fin("") == "" and retirer_signatures_fin(None) == ""
    # historique rejoué : les réponses de Liluvine sans signature
    h = historique_pour_llm([{"role": "user", "content": "inventaire ?"},
                             {"role": "assistant", "content": base + "\n\n— visitez notre site www.sawalismartsystems.com"}])
    assert h[1]["content"] == base
