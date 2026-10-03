"""
backend/vidal_v2/groupes_dfg.py
-------------------------------
Lot 56 — repris TEL QUEL de Ster (app/utils/vidal_groupes_dfg.py), seuls les imports changent.

§ demande utilisateur : "L'interprétation du DFG dépend des groupes de
population [...]. Rendre ces valeurs normales paramétrables avec
possibilité de choisir un « Groupe » (paramétrable et éditable). Le
médecin précise le groupe pour apprécier le résultat par rapport à la
valeur normale. Ce groupe n'est JAMAIS transmis à VIDAL."

Groupes de référence du DFG : libellé NEUTRE éditable, valeur normale du
DFG (ml/min/1,73 m²), actif/inactif, ordre d'affichage, un groupe par
défaut. Paramétrés par établissement (gestionnaire), voir routes/vidal_securisation.py
(GET/PUT /api/vidal/groupes-dfg) et le bloc « Paramètres VIDAL » de la page Sécurisation.

Interprétation AFFICHÉE uniquement (aide visuelle, pas un diagnostic) :
pourcentage = DFG / valeur normale du groupe × 100, puis
  - ≥ seuil "normal" (90 % par défaut)         -> normal ;
  - ≥ seuil "légèrement diminué" (60 % par défaut) -> légèrement diminué ;
  - en dessous                                   -> diminué.
Le DFG calculé et transmis (CKD-EPI sans coefficient) ne dépend JAMAIS du
groupe : ce module ne sert qu'à l'affichage et n'est appelé par aucune
construction XML ni aucun appel VIDAL.

Sans dépendance FastAPI/Mongo : portable tel quel (SAWALI).
"""

from typing import Optional

GROUPES_DFG_DEFAUT = [
    {"id": "groupe_a", "libelle": "Groupe A (référence 84)", "valeur_normale": 84.0, "actif": True, "ordre": 1, "par_defaut": True},
    {"id": "groupe_b", "libelle": "Groupe B (référence 74)", "valeur_normale": 74.0, "actif": True, "ordre": 2, "par_defaut": False},
]
SEUILS_DFG_DEFAUT = {"normal_pct": 90.0, "leger_pct": 60.0}
BORNES_VALEUR_NORMALE = (1.0, 200.0)

LIBELLES_INTERPRETATION = {
    "NORMAL": "Normal",
    "LEGEREMENT_DIMINUE": "Légèrement diminué",
    "DIMINUE": "Diminué",
}


def configuration_dfg_par_defaut() -> dict:
    return {"groupes": [dict(g) for g in GROUPES_DFG_DEFAUT], "seuils": dict(SEUILS_DFG_DEFAUT)}


def groupe_par_defaut(groupes: list[dict]) -> Optional[dict]:
    actifs = sorted([g for g in groupes if g.get("actif")], key=lambda g: g.get("ordre", 0))
    return next((g for g in actifs if g.get("par_defaut")), actifs[0] if actifs else None)


def interpreter_dfg(dfg: Optional[float], valeur_normale: Optional[float], seuils: Optional[dict] = None) -> Optional[dict]:
    """{pourcentage, niveau, libelle} — None si le DFG ou la référence manque."""
    if dfg is None or not valeur_normale:
        return None
    s = seuils or SEUILS_DFG_DEFAUT
    pourcentage = round(dfg / valeur_normale * 100, 1)
    if pourcentage >= s["normal_pct"]:
        niveau = "NORMAL"
    elif pourcentage >= s["leger_pct"]:
        niveau = "LEGEREMENT_DIMINUE"
    else:
        niveau = "DIMINUE"
    return {"pourcentage": pourcentage, "niveau": niveau, "libelle": LIBELLES_INTERPRETATION[niveau]}


def controler_configuration(groupes: list[dict], seuils: dict) -> list[dict]:
    """Contrôles de cohérence -> [{champ, message}] (vide si correct)."""
    erreurs: list[dict] = []
    if not groupes:
        erreurs.append({"champ": "groupes", "message": "Au moins un groupe est nécessaire."})
    ids = [g.get("id") for g in groupes]
    if len(set(ids)) != len(ids):
        erreurs.append({"champ": "groupes", "message": "Deux groupes ont le même identifiant."})
    for i, g in enumerate(groupes):
        if not (g.get("libelle") or "").strip():
            erreurs.append({"champ": f"groupes[{i}].libelle", "message": "Le libellé est obligatoire."})
        v = g.get("valeur_normale")
        if v is None or not (BORNES_VALEUR_NORMALE[0] <= v <= BORNES_VALEUR_NORMALE[1]):
            erreurs.append({"champ": f"groupes[{i}].valeur_normale",
                            "message": f"La valeur normale du DFG (ml/min/1,73 m²) doit être comprise entre {BORNES_VALEUR_NORMALE[0]:g} et {BORNES_VALEUR_NORMALE[1]:g}."})
    actifs = [g for g in groupes if g.get("actif")]
    if groupes and not actifs:
        erreurs.append({"champ": "groupes", "message": "Au moins un groupe doit être actif."})
    defauts = [g for g in groupes if g.get("par_defaut")]
    if len(defauts) != 1:
        erreurs.append({"champ": "groupes", "message": "Un et un seul groupe doit être le groupe par défaut."})
    elif not defauts[0].get("actif"):
        erreurs.append({"champ": "groupes", "message": "Le groupe par défaut doit être actif."})
    normal, leger = seuils.get("normal_pct"), seuils.get("leger_pct")
    if normal is None or leger is None or not (0 < leger < normal <= 150):
        erreurs.append({"champ": "seuils", "message": "Seuils (%) invalides : il faut 0 < « légèrement diminué » < « normal » ≤ 150."})
    return erreurs
