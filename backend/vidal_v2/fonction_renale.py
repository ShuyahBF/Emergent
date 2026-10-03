"""
backend/vidal_v2/fonction_renale.py
-----------------------------------
Lot 56 — repris TEL QUEL de Ster (app/utils/vidal_fonction_renale.py), seuls les imports changent.

§ Revue d'implémentation VIDAL (reproche n°2 : "la créatininémie ne doit
pas être transmise seule") — l'API attend TROIS valeurs dans <patient> :
  - <creatin>                  clairance de la créatinine (ml/min), ENTIER
                               de 1 à 120 (MI VIDAL §6.2.8 : jamais 0, sans
                               décimale) ;
  - <serumCreatinine>          créatininémie (µmol/l) ;
  - <glomerularFiltrationRate> débit de filtration glomérulaire (ml/min/1,73 m²).
MI §6.2.8 : seule la clairance déclenche les contre-indications et
précautions liées au rein ; le DFG, s'il est présent, sert aux contrôles
de posologie — d'où l'envoi systématique des deux.

Calculateurs VIDAL (MI §5.2.2.3 à 5.2.2.5), en POST text/xml avec un corps
<patient> (date de naissance AAAA-MM-JJ, sexe, poids...) :
  - /calculators/ccreat/cockroft-gault + <serumCreatinine> : clairance
    -> <vidal:estimatedCreatinineClearance> (ml/min), <vidal:renalInsufficiency> ;
  - /calculators/renal-function + <serumCreatinine> : DFG CKD-EPI
    -> entrée GLOMERULAR_FILTRATION_RATE (<vidal:nonAfroAmerican kdigoGfrStage=...>) ;
  - /calculators/renal-function + <creatin> : créatininémie
    (<vidal:serumCreatinine>, > 15 ans, 40 à 100 kg) et DFG (≥ 18 ans).
VIDAL renvoie deux DFG (avec et sans coefficient ethnique) : seul le DFG
SANS coefficient (<vidal:nonAfroAmerican>, identique au calcul local) est
retenu et transmis. L'appréciation du DFG selon un groupe de référence est
une aide d'affichage locale (vidal_v2/groupes_dfg.py), JAMAIS
transmise à VIDAL.

Calcul LOCAL de repli (mêmes formules, mêmes limites d'âge et de poids) :
  - Cockcroft & Gault : Cl = k × (140 − âge) × poids / créatininémie,
    k = 1,23 (homme) ou 1,04 (femme) ; inverse : créat = k × (140 − âge) × poids / Cl.
  - CKD-EPI 2009 (adulte ≥ 18 ans) :
    DFG = 141 × min(Scr/κ, 1)^α × max(Scr/κ, 1)^−1,209 × 0,993^âge [× 1,018 femme]
    Scr en mg/dL (= µmol/L / 88,4), κ = 0,7 / 0,9, α = −0,329 / −0,411
    (femme / homme), sans coefficient ethnique.

Aucune dépendance FastAPI/Mongo : portable tel quel (SAWALI).
"""

import math
import re
from datetime import date
from typing import Optional

from vidal_v2.referentiels import BORNES, FACTEUR_MG_DL_VERS_UMOL_L

CLAIRANCE_MAX_TRANSMISE = BORNES["clairance_ml_min"]["max"]
CLAIRANCE_MIN_TRANSMISE = BORNES["clairance_ml_min"]["min"]

# § limites des calculateurs VIDAL (MI §5.2.2.4 / 5.2.2.5), reprises en local.
AGE_MIN_DFG = 18
AGE_MIN_CREATININEMIE_CALCULEE = 15
POIDS_CREATININEMIE_CALCULEE = (40, 100)


def age_en_annees(date_naissance: date, reference: Optional[date] = None) -> int:
    """Âge en années révolues à la date de référence (aujourd'hui par défaut)."""
    ref = reference or date.today()
    return ref.year - date_naissance.year - ((ref.month, ref.day) < (date_naissance.month, date_naissance.day))


def mg_dl_vers_umol_l(valeur_mg_dl: float) -> float:
    return valeur_mg_dl * FACTEUR_MG_DL_VERS_UMOL_L


def umol_l_vers_mg_dl(valeur_umol_l: float) -> float:
    return valeur_umol_l / FACTEUR_MG_DL_VERS_UMOL_L


def _coefficient_cockcroft(sexe: str) -> Optional[float]:
    return {"MALE": 1.23, "FEMALE": 1.04}.get(sexe)


def clairance_cockcroft_gault(age: int, poids_kg: float, sexe: str, creatininemie_umol_l: float) -> Optional[float]:
    """Clairance estimée (ml/min) — None si le sexe n'est pas Homme/Femme (formule sexuée) ou une donnée manque."""
    k = _coefficient_cockcroft(sexe)
    if k is None or not poids_kg or not creatininemie_umol_l or age is None:
        return None
    return max(0.0, k * (140 - age) * poids_kg / creatininemie_umol_l)


def creatininemie_depuis_clairance(age: int, poids_kg: float, sexe: str, clairance_ml_min: float) -> Optional[float]:
    """Inverse de Cockcroft & Gault (µmol/L) — mêmes conditions que VIDAL : > 15 ans, 40 à 100 kg."""
    k = _coefficient_cockcroft(sexe)
    if k is None or not poids_kg or not clairance_ml_min or age is None or age >= 140:
        return None
    if age <= AGE_MIN_CREATININEMIE_CALCULEE or not (POIDS_CREATININEMIE_CALCULEE[0] <= poids_kg <= POIDS_CREATININEMIE_CALCULEE[1]):
        return None
    return k * (140 - age) * poids_kg / clairance_ml_min


def dfg_ckd_epi_2009(age: int, sexe: str, creatininemie_umol_l: float) -> Optional[float]:
    """DFG estimé (ml/min/1,73 m²) selon CKD-EPI 2009, sans coefficient ethnique — adulte (≥ 18 ans) uniquement."""
    if sexe not in ("MALE", "FEMALE") or not creatininemie_umol_l or age is None or age < AGE_MIN_DFG:
        return None
    scr = umol_l_vers_mg_dl(creatininemie_umol_l)
    femme = sexe == "FEMALE"
    kappa = 0.7 if femme else 0.9
    alpha = -0.329 if femme else -0.411
    ratio = scr / kappa
    dfg = 141 * (min(ratio, 1) ** alpha) * (max(ratio, 1) ** -1.209) * (0.993 ** age)
    if femme:
        dfg *= 1.018
    return dfg


def arrondi2(valeur: Optional[float]) -> Optional[float]:
    return None if valeur is None else round(valeur + 0.0, 2)


def clairance_transmise(clairance: Optional[float]) -> Optional[int]:
    """Valeur de <creatin> : entier arrondi, borné de 1 à 120 ml/min (MI §6.2.8 et doc VIDAL)."""
    if clairance is None:
        return None
    return int(min(max(math.floor(clairance + 0.5), CLAIRANCE_MIN_TRANSMISE), CLAIRANCE_MAX_TRANSMISE))


def categorie_insuffisance_renale(clairance: Optional[float]) -> Optional[str]:
    """§ MI §5.2.2.1 : ≥ 90 aucune, 60–90 légère, 30–60 modérée, < 30 sévère."""
    if clairance is None:
        return None
    if clairance >= 90:
        return "NONE"
    if clairance >= 60:
        return "MILD"
    if clairance >= 30:
        return "MODERATE"
    return "SEVERE"


def calculer_fonction_renale_locale(
    *, date_naissance: date, sexe: str, poids_kg: float,
    creatininemie_umol_l: Optional[float] = None, clairance_ml_min: Optional[float] = None,
    reference: Optional[date] = None,
) -> dict:
    """
    Calcule les 3 valeurs attendues par VIDAL à partir de la créatininémie
    (cas normal) OU, à défaut, de la clairance saisie.

    `creatin` est la valeur TRANSMISE (entier, bornée à 120 ml/min : au-delà
    la fonction rénale est normale) ; `creatin_calculee` garde la valeur
    brute pour l'affichage.
    """
    age = age_en_annees(date_naissance, reference)
    creat = creatininemie_umol_l
    clairance = clairance_ml_min
    if creat:
        clairance = clairance_cockcroft_gault(age, poids_kg, sexe, creat)
    elif clairance:
        creat = creatininemie_depuis_clairance(age, poids_kg, sexe, clairance)
    dfg = dfg_ckd_epi_2009(age, sexe, creat) if creat else None
    return {
        "creatin": clairance_transmise(clairance),
        "creatin_calculee": arrondi2(clairance),
        "plafonnee": clairance is not None and clairance > CLAIRANCE_MAX_TRANSMISE,
        "serumCreatinine": arrondi2(creat),
        "glomerularFiltrationRate": arrondi2(dfg),
        "insuffisanceRenale": categorie_insuffisance_renale(clairance),
        "stadeKdigo": None,
        "age": age,
    }


# ---------------------------------------------------------------------------
# Calculateurs VIDAL (format MI §5.2.2.3 à 5.2.2.5)
# ---------------------------------------------------------------------------

def construire_xml_cockroft_gault(*, date_naissance: date, sexe: str, poids_kg: float, taille_cm: Optional[float],
                                  creatininemie_umol_l: float) -> str:
    """Corps de POST /calculators/ccreat/cockroft-gault : <patient> avec la créatininémie (µmol/L)."""
    morceaux = [
        '<?xml version="1.0" encoding="UTF-8"?>', "<patient>",
        f"<dateOfBirth>{date_naissance.isoformat()}</dateOfBirth>",
        f"<gender>{sexe}</gender>",
    ]
    if taille_cm:
        morceaux.append(f"<height>{taille_cm:g}</height>")
    morceaux += [f"<weight>{poids_kg:g}</weight>", f"<serumCreatinine>{creatininemie_umol_l:.2f}</serumCreatinine>", "</patient>"]
    return "".join(morceaux)


def construire_xml_fonction_renale(*, date_naissance: date, sexe: str, poids_kg: float,
                                   creatininemie_umol_l: Optional[float] = None, clairance_ml_min: Optional[float] = None) -> str:
    """Corps de POST /calculators/renal-function : <serumCreatinine> (-> DFG) OU <creatin> (-> créatininémie + DFG)."""
    morceaux = ['<?xml version="1.0" encoding="UTF-8"?>', "<patient>"]
    if creatininemie_umol_l is not None:
        morceaux.append(f"<serumCreatinine>{creatininemie_umol_l:.2f}</serumCreatinine>")
    else:
        morceaux.append(f"<creatin>{clairance_ml_min:g}</creatin>")
    morceaux += [
        f"<dateOfBirth>{date_naissance.isoformat()}</dateOfBirth>",
        f"<gender>{sexe}</gender>",
        f"<weight>{poids_kg:g}</weight>",
        "</patient>",
    ]
    return "".join(morceaux)


def _balise_vidal(nom: str) -> re.Pattern:
    return re.compile(rf"<vidal:{nom}\b([^>]*)>\s*([^<]*?)\s*</vidal:{nom}>", re.IGNORECASE | re.DOTALL)


_CLAIRANCE_ESTIMEE_RE = _balise_vidal("estimatedCreatinineClearance")
_INSUFFISANCE_RENALE_RE = _balise_vidal("renalInsufficiency")
_METHODE_RE = _balise_vidal("calculationMethod")
_DFG_SANS_COEFFICIENT_RE = _balise_vidal("nonAfroAmerican")
_CREATININEMIE_RE = _balise_vidal("serumCreatinine")
_ATTRIBUT_RE = re.compile(r'(\w+)="([^"]*)"')


def _nombre(texte: Optional[str]) -> Optional[float]:
    try:
        return float(str(texte).replace(",", "."))
    except (TypeError, ValueError):
        return None


def lire_reponse_cockroft_gault(raw: Optional[str]) -> dict:
    """{clairance, insuffisanceRenale, methode} — dict vide si la clairance estimée est absente."""
    if not isinstance(raw, str):
        return {}
    m = _CLAIRANCE_ESTIMEE_RE.search(raw)
    clairance = _nombre(m.group(2)) if m else None
    if clairance is None:
        return {}
    insuffisance, methode = _INSUFFISANCE_RENALE_RE.search(raw), _METHODE_RE.search(raw)
    return {
        "clairance": clairance,
        "insuffisanceRenale": insuffisance.group(2).strip() if insuffisance else None,
        "methode": methode.group(2).replace("&amp;", "&").strip() if methode else None,
    }


def lire_reponse_fonction_renale(raw: Optional[str]) -> dict:
    """{dfg, stadeKdigo, methodeDfg, creatininemie} — seul le DFG SANS coefficient ethnique est lu."""
    resultat: dict = {}
    if not isinstance(raw, str):
        return resultat
    m = _DFG_SANS_COEFFICIENT_RE.search(raw)
    if m and _nombre(m.group(2)) is not None:
        attributs = dict(_ATTRIBUT_RE.findall(m.group(1)))
        resultat.update({"dfg": _nombre(m.group(2)), "stadeKdigo": attributs.get("kdigoGfrStage"), "methodeDfg": attributs.get("calculationMethod")})
    m = _CREATININEMIE_RE.search(raw)
    if m and _nombre(m.group(2)) is not None:
        resultat["creatininemie"] = _nombre(m.group(2))
    return resultat
