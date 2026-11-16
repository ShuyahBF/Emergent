"""Lot 426 — remise à zéro du coffre des plateformes (secret ET code de secours perdus).
Lancer : cd backend && python -m pytest tests/test_lot426_archives_reinitialiser.py -q
"""
from __future__ import annotations

from tests.test_lot227_formules_plateformes import SEL, VERIF, arch, env, U  # noqa: F401  (fixture « env »)

PREUVE = "P" * 43 + "="


def test_remise_a_zero_efface_cle_code_et_permet_un_coffre_neuf(env):
    u = U()
    # coffre existant : clé + code contrôlé par le serveur
    arch(env, "cle", u, sel=SEL, verif=VERIF)
    arch(env, "pin/enregistrer", u, preuve=PREUVE, verif_actuelle=VERIF)
    e = arch(env, "etat", u).json()
    assert e["verif"] == VERIF and e["pin"]
    # remise à zéro : plus de clé, plus de code, aucun document
    r = arch(env, "reinitialiser", u)
    assert r.status_code == 200 and r.json()["ok"] is True
    e = arch(env, "etat", u).json()
    assert e["verif"] is None and e["sel"] is None and e["pin"] is None and e["a2f"] is False and e["nombre"] == 0
    # un coffre NEUF peut être créé avec un autre sel (refusé avant la remise à zéro)
    autre_sel = "Z" * len(SEL)
    assert arch(env, "cle", u, sel=autre_sel, verif=VERIF).status_code == 200
    assert arch(env, "etat", u).json()["sel"] == autre_sel


def test_remise_a_zero_ne_touche_que_l_utilisateur_concerne(env):
    a, b = U(), U()
    b["id"] = "autre-utilisateur-426"
    arch(env, "cle", a, sel=SEL, verif=VERIF)
    arch(env, "cle", b, sel=SEL, verif=VERIF)
    assert arch(env, "reinitialiser", a).status_code == 200
    assert arch(env, "etat", a).json()["verif"] is None
    assert arch(env, "etat", b).json()["verif"] == VERIF
