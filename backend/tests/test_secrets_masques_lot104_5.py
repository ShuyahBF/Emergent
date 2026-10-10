"""Lot 104.5 — « Enregistrer » dans les Paramètres ne réécrit jamais un secret masqué (« ******** »),
quel que soit le champ (jeton Facebook, LinkedIn, Twitter, PawaPay…)."""
import ast
from typing import Any, Dict

from _source_serveur import source_serveur


def _fonction():
    tree = ast.parse(source_serveur())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "retirer_valeurs_masquees")
    ns: Dict[str, Any] = {"Dict": Dict, "Any": Any}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "server", "exec"), ns)  # noqa: S102
    return ns["retirer_valeurs_masquees"]


def test_valeurs_masquees_ignorees():
    f = _fonction()
    maj = {"facebook_user_access_token": "********", "linkedin_access_token": " ******** ",
           "pawapay_api_token_sandbox": "********", "facebook_page_name": "SAWALI", "wa_enabled": True,
           "nouveau_secret": "abc123"}
    assert f(maj) == {"facebook_page_name": "SAWALI", "wa_enabled": True, "nouveau_secret": "abc123"}


def test_le_filtre_est_bien_appele_par_l_enregistrement():
    src = source_serveur()
    debut = src.index("async def admin_update_settings")
    assert "retirer_valeurs_masquees(update)" in src[debut:debut + 8000]
