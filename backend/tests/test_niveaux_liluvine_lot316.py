"""Lot 316 — Liluvine et l'EXPRESS : bloc de prompt (niveaux, délai, tarif = forfait du client), rien sans configuration."""
import asyncio

from mongomock_motor import AsyncMongoMockClient

from routes.niveaux_service import normaliser_config
from routes.niveaux_service_liluvine import A_PRECISER, bloc_pour_prompt, construire_bloc, texte_forfait


def _run(c):
    return asyncio.get_event_loop().run_until_complete(c)


CONFIG = normaliser_config({"actif": True, "niveaux": {
    "contrat": {"delai": "72 heures maximum"}, "standard": {"delai": "Selon disponibilité (sans engagement)"}, "express": {"delai": "2 heures"}}})


def test_texte_forfait():
    assert texte_forfait(25000) == "25 000 FCFA"
    assert texte_forfait(0) == A_PRECISER and texte_forfait(None) == A_PRECISER and texte_forfait("x") == A_PRECISER


def test_aucun_bloc_sans_configuration():
    assert construire_bloc(normaliser_config(None), "valide", 25000) == ""          # rien n'est annoncé par défaut


def test_bloc_contrat_valide_avec_forfait():
    b = construire_bloc(CONFIG, "valide", 25000)
    assert "72 heures maximum" in b and "Selon disponibilité (sans engagement)" in b and "2 heures" in b
    assert "25 000 FCFA" in b and "son contrat est valide" in b
    assert "[ESCALATE: EXPRESS accepté" in b and "AU PLUS 3 questions" in b            # prévient le propriétaire à l'acceptation


def test_bloc_sans_contrat_et_forfait_a_zero():
    b = construire_bloc(CONFIG, "aucun", 0)
    assert "pas de contrat valide" in b and "seul le niveau « standard »" in b
    assert A_PRECISER in b and "FCFA" not in b                                            # aucun montant inventé


def test_bloc_pour_prompt_lit_les_reglages_et_le_forfait_du_client():
    base = AsyncMongoMockClient()["test_niveaux_liluvine_316"]
    _run(base.users.insert_many([{"id": "parent", "flat_rate": 30000}, {"id": "enfant", "parent_client_id": "parent"}]))
    assert _run(bloc_pour_prompt(base, {"id": "enfant"}, "valide")) == ""               # rubrique non configurée : rien
    _run(base.settings.insert_one({"_id": "global", "niveaux_service": {"actif": True, "niveaux": {
        "contrat": {"delai": "72 heures maximum"}, "standard": {"delai": "48 heures"}, "express": {"delai": "1 heure"}}}}))
    b = _run(bloc_pour_prompt(base, {"id": "enfant"}, "valide"))                         # forfait lu sur le compte principal
    assert "30 000 FCFA" in b and "1 heure" in b
    assert A_PRECISER in _run(bloc_pour_prompt(base, None, "aucun"))                    # contact non relié à un client
