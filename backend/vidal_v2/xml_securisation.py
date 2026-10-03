"""
backend/vidal_v2/xml_securisation.py
----------------------------------------
Lot 56 — repris de Ster (app/utils/vidal_securisation.py), qui était
lui-même parti de l'ancien `routes/vidal_securisation.py` de SAWALI puis
avait été aligné sur le manuel d'intégration VIDAL (sécurisation v2). Ce
module REMPLACE la construction XML de l'ancienne page Sécurisation.

§ Révision "sécurisation v2" (suite à la revue d'implémentation VIDAL) :
données cliniques femme (grossesse en SA, allaitement), fonction rénale
transmise par ses 3 valeurs, balises nil, ordre des balises et lignes de
prescription complètes (méthode 1/2, dosages, période, ALD) — le payload
est validé AVANT d'arriver ici (vidal_v2/modeles.py).
"""

import re
import xml.etree.ElementTree as ET
from typing import Any, Optional

from vidal_v2.fonction_renale import clairance_transmise
from vidal_v2.referentiels import SCHEMAS_URI_MEDICAMENT

# 18 types d'alerte réels du manuel VIDAL — les 4 premiers sont cochés par défaut côté UI.
TYPES_ALERTE = [
    "CONTRA_INDICATION", "ALLERGY", "DRUG_INTERACTION", "POSOLOGY",
    "PRECAUTION", "WARNING", "SIDE_EFFECT", "PHYSICO_CHEMICAL_INTERACTION",
    "SURVEILLANCE", "REDUNDANT_ACTIVE_INGREDIENT", "SAME_DRUG",
    "FOOD_INTERACTION", "DISPENSING_RISK", "PRESCRIPTION_CONTEXT",
    "EXONERATION", "INDICATOR", "FOCUS", "HAS",
]
TYPES_ALERTE_DEFAUT = ["CONTRA_INDICATION", "ALLERGY", "DRUG_INTERACTION", "POSOLOGY"]


# (SAWALI) La construction du corps de /posology-descriptors (page Posologie de
# Ster) n'est pas reprise : la page Posologie de SAWALI garde son propre flux.


def _set_text(parent: ET.Element, tag: str, value: Any) -> None:
    if value in (None, ""):
        return
    ET.SubElement(parent, tag).text = str(value)


# § doc VIDAL : certaines balises "désactivées" s'écrivent en nil XML
# Schema (attribut xsi:nil="true") plutôt que d'être omises. Les deux
# attributs (xsi:nil et la déclaration de l'espace de noms xsi) sont posés
# littéralement sur l'élément, pour éviter le préfixe "ns0" qu'ajouterait
# ElementTree.
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"


def _set_nil(parent: ET.Element, tag: str) -> None:
    el = ET.SubElement(parent, tag)
    el.set("xsi:nil", "true")
    el.set("xmlns:xsi", XSI_NS)


def _set_text_ou_nil(parent: ET.Element, tag: str, value: Any) -> None:
    if value in (None, ""):
        _set_nil(parent, tag)
    else:
        _set_text(parent, tag, value)


def _nombre(valeur: Any) -> Optional[str]:
    """80.0 -> "80", 2.5 -> "2.5" : jamais de ".0" superflu dans le XML."""
    if valeur in (None, ""):
        return None
    try:
        f = float(valeur)
    except (TypeError, ValueError):
        return str(valeur)
    return str(int(f)) if f.is_integer() else f"{round(f, 4):g}"


def _deux_decimales(valeur: Any) -> Optional[str]:
    """§ doc VIDAL : créatininémie (et DFG) écrits avec 2 décimales et un point décimal (ex. 70.00)."""
    return None if valeur in (None, "") else f"{float(valeur):.2f}"


def _date_vidal(valeur: Any, heure: str = "00:00:00") -> Optional[str]:
    """"2026-09-09" -> "2026-09-09T00:00:00" (format AAAA-MM-JJTHH:MM:SS attendu par VIDAL)."""
    if valeur in (None, ""):
        return None
    texte = valeur.isoformat() if hasattr(valeur, "isoformat") else str(valeur)
    return texte if "T" in texte else f"{texte[:10]}T{heure}"


def _build_patient(el: ET.Element, patient: dict) -> None:
    """
    Bloc <patient>, dans l'ordre des balises de la doc VIDAL :
    dateOfBirth, gender, weight, height, breastFeeding,
    breastFeedingStartDate, weeksOfAmenorrhea, creatin, serumCreatinine,
    glomerularFiltrationRate, hepaticInsufficiency, allergies, molecules,
    pathologies.

    § reproche VIDAL n°1 : grossesse et allaitement ne concernent QUE les
    femmes — pour un homme (ou sexe non précisé), aucune de ces balises
    n'est émise. Pour une femme, <breastFeeding> est toujours présent
    (NONE par défaut) et <breastFeedingStartDate> vaut la date de début
    ou nil (pas d'allaitement / date inconnue), comme le prévoit la doc.

    § reproche VIDAL n°2 : la fonction rénale est transmise par ses TROIS
    valeurs (clairance, créatininémie, DFG) — <creatin> passe à nil si
    aucune clairance n'est connue.
    """
    _set_text(el, "dateOfBirth", _date_vidal(patient.get("dateOfBirth")))
    _set_text_ou_nil(el, "gender", patient.get("gender"))
    _set_text(el, "weight", _nombre(patient.get("weight")))
    _set_text(el, "height", _nombre(patient.get("height")))
    # § MI §6.2.6/6.2.7 : grossesse/allaitement pour une patiente, ou pour
    # un sexe non renseigné quand ces données sont effectivement saisies.
    donnees_femme = any(patient.get(k) not in (None, "", "NONE") for k in ("breastFeeding", "breastFeedingStartDate", "weeksOfAmenorrhea"))
    if patient.get("gender") == "FEMALE" or (patient.get("gender") in (None, "") and donnees_femme):
        # § aucune valeur par défaut : <breastFeeding> n'est émis que s'il a
        # été RENSEIGNÉ (le formulaire envoie NONE quand « Allaitement en
        # cours » n'est pas coché) ; la date passe alors en nil sans allaitement.
        allaitement = patient.get("breastFeeding")
        if allaitement:
            _set_text(el, "breastFeeding", allaitement)
            debut = patient.get("breastFeedingStartDate") if allaitement != "NONE" else None
            _set_text_ou_nil(el, "breastFeedingStartDate", _date_vidal(debut))
        _set_text(el, "weeksOfAmenorrhea", patient.get("weeksOfAmenorrhea"))
    # § MI §6.2.8 : <creatin> en ENTIER (ni virgule ni point), jamais 0 —
    # inconnue -> nil. Compatibilité : ancien champ "clairance" (frontend antérieur).
    clairance = patient.get("creatin")
    if clairance in (None, "") and isinstance(patient.get("clairance"), (int, float)):
        clairance = patient["clairance"]
    _set_text_ou_nil(el, "creatin", None if clairance in (None, "") else clairance_transmise(float(clairance)))
    _set_text(el, "serumCreatinine", _deux_decimales(patient.get("serumCreatinine")))
    _set_text(el, "glomerularFiltrationRate", _deux_decimales(patient.get("glomerularFiltrationRate")))
    _set_text(el, "hepaticInsufficiency", patient.get("hepaticInsufficiency"))
    _build_ref_block(el, "allergies", "allergy", patient.get("allergies"))
    _build_ref_block(el, "molecules", "molecule", patient.get("molecules"))
    _build_ref_block(el, "pathologies", "pathology", patient.get("pathologies"))


def _build_ref_block(parent: ET.Element, block_tag: str, item_tag: str, items: Any) -> None:
    refs = [it.get("ref") for it in (items or []) if isinstance(it, dict) and it.get("ref")]
    if not refs:
        return
    block_el = ET.SubElement(parent, block_tag)
    for ref in refs:
        _set_text(block_el, item_tag, ref)


def _build_line(lines_el: ET.Element, line: dict) -> None:
    """
    Une <prescription-line>, dans l'ordre de la doc : médicament (méthode
    1 <drugId>+<drugType> pour un groupe de dénomination commune, méthode
    2 <drug>vidal://...</drug> sinon), dose, unitId, duration,
    durationType, frequencyType, routes, indications, dosages, period,
    status, group, aldStatus.
    """
    li = ET.SubElement(lines_el, "prescription-line")
    drug_ref = line.get("drugRef")
    type_medicament = line.get("drugType") or "PRODUCT"
    if type_medicament == "COMMON_NAME_GROUP":
        _set_text(li, "drugId", drug_ref)
        _set_text(li, "drugType", type_medicament)
    else:
        schema = SCHEMAS_URI_MEDICAMENT.get(type_medicament, "product")
        _set_text(li, "drug", f"vidal://{schema}/{drug_ref}" if drug_ref else None)
    _set_text(li, "dose", _nombre(line.get("dose")))
    _set_text(li, "unitId", line.get("unitId"))
    _set_text(li, "duration", line.get("duration"))
    _set_text(li, "durationType", line.get("durationType"))
    _set_text(li, "frequencyType", line.get("frequencyType"))
    route_ref = line.get("route")
    if route_ref:
        routes_el = ET.SubElement(li, "routes")
        route_ref = str(route_ref)
        _set_text(routes_el, "route", route_ref if route_ref.startswith("vidal://") else f"vidal://route/{route_ref}")
    indication_ref = line.get("indication")
    if indication_ref:
        indications_el = ET.SubElement(li, "indications")
        _set_text(indications_el, "indication", indication_ref)
    dosages = [d for d in (line.get("dosages") or line.get("posologies") or [])
               if d.get("dose") not in (None, "") or d.get("intervalMin") not in (None, "") or d.get("intervalMax") not in (None, "")]
    if dosages:
        dosages_el = ET.SubElement(li, "dosages")
        for p in dosages:
            dosage_el = ET.SubElement(dosages_el, "dosage")
            _set_text(dosage_el, "dose", _nombre(p.get("dose")))
            _set_text(dosage_el, "unitId", p.get("unitId") or line.get("unitId"))
            if p.get("intervalMin") not in (None, "") or p.get("intervalMax") not in (None, ""):
                interval_el = ET.SubElement(dosage_el, "interval")
                _set_text(interval_el, "min", _nombre(p.get("intervalMin")))
                _set_text(interval_el, "max", _nombre(p.get("intervalMax")))
                # § aucune unité par défaut : l'unité d'intervalle est obligatoire à la saisie.
                _set_text(interval_el, "unitId", p.get("intervalUnitId"))
    if line.get("startDate") or line.get("endDate"):
        period_el = ET.SubElement(li, "period")
        # § fin de période à 23:59:59 : une ligne du 01 au 01 couvre bien la journée entière.
        _set_text(period_el, "startDate", _date_vidal(line.get("startDate")))
        _set_text(period_el, "endDate", _date_vidal(line.get("endDate"), "23:59:59"))
    _set_text(li, "status", line.get("status") or "ACTIVE")
    group_el = ET.SubElement(li, "group")
    _set_text(group_el, "groupId", line.get("groupId") if line.get("groupId") is not None else 1)
    _set_text(group_el, "groupType", line.get("groupType") or "SAME_ORDER")
    if line.get("ald"):
        ald_el = ET.SubElement(li, "aldStatus")
        _set_text(ald_el, "ald", "true")
        _set_text(ald_el, "aldCode", line.get("aldCode"))


def construire_xml_prescription(patient: dict, lignes: list[dict], types_alerte: Optional[list[str]] = None,
                                inclure_types_alerte: bool = True, rubriques_html: Optional[list[str]] = None) -> str:
    """Construit le body XML de /alerts/full (et /alerts/full/html) : patient / prescription-lines / alert-types.

    § `inclure_types_alerte=False` pour le rapport HTML : la doc le décrit
    comme EXHAUSTIF (toutes les alertes, quelle que soit leur sévérité) —
    aucun filtre <alert-types> n'y est transmis ; un filtrage d'affichage
    passe par `rubriques_html` (<alert-display-types>, MI §6.5.5)."""
    root = ET.Element("prescription")
    patient_el = ET.SubElement(root, "patient")
    _build_patient(patient_el, patient or {})
    lines_el = ET.SubElement(root, "prescription-lines")
    for line in (lignes or []):
        if not line.get("drugRef") and not line.get("drug"):
            continue
        _build_line(lines_el, line)
    if inclure_types_alerte:
        types_el = ET.SubElement(root, "alert-types")
        for t in (types_alerte or TYPES_ALERTE_DEFAUT):
            _set_text(types_el, "alert-type", t)
    # § MI §6.5.5 : rapport HTML filtré sur certaines rubriques — balise
    # distincte de <alert-types> ; absente = rapport complet.
    if rubriques_html:
        rubriques_el = ET.SubElement(root, "alert-display-types")
        for r in rubriques_html:
            _set_text(rubriques_el, "alert-display-type", r)
    xml_str = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


# ---------------------------------------------------------------------------
# Réponse /alerts/full — schéma confirmé (manuel MI_APIREST REV_03)
# ---------------------------------------------------------------------------
_SUMMARY_RE = re.compile(r'<vidal:(max\w+Severity)\b([^>]*)\bseverity="([^"]*)"([^>]*)>(.*?)</vidal:\1>', re.DOTALL | re.IGNORECASE)
_URL_SUFFIX_RE = re.compile(r'urlSuffix="#?([^"]*)"', re.IGNORECASE)
_ALERT_ENTRY_RE = re.compile(r'<entry\b[^>]*\bvidal:categories="ALERT"[^>]*>(.*?)</entry>', re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_CONTENT_RE = re.compile(r'<content\b[^>]*>(.*?)</content>', re.DOTALL | re.IGNORECASE)
_ALERT_TYPE_RE = re.compile(r'<vidal:alertType\b[^>]*\bname="([^"]*)"[^>]*>(.*?)</vidal:alertType>', re.DOTALL | re.IGNORECASE)
_SEVERITY_RE = re.compile(r"<vidal:severity>(.*?)</vidal:severity>", re.DOTALL | re.IGNORECASE)
_SUBTYPE_RE = re.compile(r'<vidal:subType\b[^>]*\bname="([^"]*)"[^>]*>(.*?)</vidal:subType>', re.DOTALL | re.IGNORECASE)
_DETAIL_RE = re.compile(r'<vidal:detail\b[^>]*>(.*?)</vidal:detail>', re.DOTALL | re.IGNORECASE)
_TRIGGERED_BY_RE = re.compile(r'<vidal:triggeredBy\b[^>]*\bid="([^"]*)"[^>]*\btype="([^"]*)"[^>]*>(.*?)</vidal:triggeredBy>', re.DOTALL | re.IGNORECASE)
import html as _html_module

_SOURCE_RE = re.compile(r'<vidal:source\b[^>]*\bdate="([^"]*)"[^>]*>(.*?)</vidal:source>', re.DOTALL | re.IGNORECASE)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")

# Gravité croissante — sert à trier les alertes et choisir une couleur.
ORDRE_SEVERITE = {"NO_ALERT": 0, "INFO": 1, "LEVEL_1": 2, "LEVEL_2": 3, "LEVEL_3": 4, "LEVEL_4": 5}


def _clean(text: Optional[str]) -> str:
    """
    § signalé par l'utilisateur (2 fois) : d'abord des caractères
    accentués illisibles ("R&amp;eacute;serv&amp;eacute;"), maintenant des
    balises visibles en toutes lettres ("<p>", "</p>", "<span>") dans le
    texte affiché — même cause : les balises de mise en forme VIDAL sont
    elles-mêmes échappées en entités HTML (ex : "&lt;p&gt;...&lt;/p&gt;"),
    donc invisibles pour un simple retrait de balises tant que ces
    entités n'ont pas été décodées. L'ordre correct est : décoder D'ABORD
    (double passage, une des deux couches d'échappement pouvant elle-même
    être ré-échappée), PUIS retirer les balises devenues réelles — jamais
    l'inverse, qui les laissait passer telles quelles.
    Les fins de paragraphe/retours à la ligne (`</p>`, `<br>`) sont
    converties en saut de ligne AVANT le retrait des balises, pour que
    plusieurs `<p>` (ex : risque, conduite à tenir) restent lisibles comme
    des paragraphes distincts plutôt que collés en un seul bloc de texte.
    """
    if not text:
        return ""
    texte = _html_module.unescape(_html_module.unescape(text))
    texte = re.sub(r"</p\s*>|<br\s*/?>", "\n", texte, flags=re.IGNORECASE)
    texte = _TAG_STRIP_RE.sub("", texte)
    lignes = [l.strip() for l in texte.split("\n")]
    return "\n".join(l for l in lignes if l).strip()


def parser_reponse_alertes(raw: Optional[str]) -> dict:
    """Parse la réponse /alerts/full : résumé par catégorie puis alertes détaillées, triées par gravité décroissante."""
    summary: list[dict] = []
    alerts: list[dict] = []
    if not isinstance(raw, str) or "<" not in raw:
        return {"summary": summary, "alerts": alerts}

    for category, avant, severity, apres, label in _SUMMARY_RE.findall(raw):
        # § MI §6.5.4.1 : urlSuffix (ex. "#menu_posology") = ancre de la
        # rubrique correspondante du rapport HTML.
        ancre = _URL_SUFFIX_RE.search(avant + apres)
        summary.append({"category": category, "severity": severity, "label": _clean(label), "anchor": ancre.group(1) if ancre else None})

    for block in _ALERT_ENTRY_RE.findall(raw):
        title_m, content_m = _TITLE_RE.search(block), _CONTENT_RE.search(block)
        type_m, severity_m = _ALERT_TYPE_RE.search(block), _SEVERITY_RE.search(block)
        subtype_m, detail_m = _SUBTYPE_RE.search(block), _DETAIL_RE.search(block)
        triggered_m, source_m = _TRIGGERED_BY_RE.search(block), _SOURCE_RE.search(block)
        alerts.append({
            "title": _clean(title_m.group(1)) if title_m else None,
            "content": _clean(content_m.group(1)) if content_m else None,
            "alert_type": type_m.group(1) if type_m else None,
            "alert_type_label": _clean(type_m.group(2)) if type_m else None,
            "severity": severity_m.group(1).strip() if severity_m else None,
            "sub_type": subtype_m.group(1) if subtype_m else None,
            "sub_type_label": _clean(subtype_m.group(2)) if subtype_m else None,
            "detail": _clean(detail_m.group(1)) if detail_m else None,
            "triggered_by_label": _clean(triggered_m.group(3)) if triggered_m else None,
            "source_date": source_m.group(1) if source_m else None,
            "source_label": _clean(source_m.group(2)) if source_m else None,
        })
    alerts.sort(key=lambda a: ORDRE_SEVERITE.get(a.get("severity"), -1), reverse=True)
    return {"summary": summary, "alerts": alerts}


def extraire_patient_envoye(xml_corps: str) -> dict:
    """
    § historique clinique (instantané de sécurisation) : données patient
    RÉELLEMENT transmises à VIDAL, relues dans le corps XML construit
    (et non dans la saisie) — {balise: valeur}, None pour une balise nil,
    listes pour allergies/molécules/pathologies.
    """
    racine = ET.fromstring(xml_corps.split("\n", 1)[-1])
    patient = racine.find("patient")
    resultat: dict = {}
    if patient is None:
        return resultat
    for el in patient:
        if len(el):
            resultat[el.tag] = [enfant.text for enfant in el]
        else:
            resultat[el.tag] = None if el.get("xsi:nil") == "true" else el.text
    return resultat
