"""Lot 377 — posologies VIDAL (remarques 4, 5 et 6 de la démonstration). Logique pure : aucun réseau, aucune base.

1. Appel `/{product|package|vmp|ucd}/{id}/posology-descriptors` : corps XML `<posology-request><patient>…`
   (repris de Ster, validé contre le manuel VIDAL MI_APIREST REV_03 p.90-91 : dateOfBirth, gender, weight, height
   obligatoires pour que VIDAL propose des posologies) et lecture de la réponse (<entry vidal:categories="POSOLOGY_DESCRIPTOR">).
2. Informations manquantes (âge, sexe, poids) : ce n'est JAMAIS bloquant — on prévient simplement l'utilisateur
   que VIDAL ne proposera aucune posologie (`patient_manquants`, `message_manquants`).
3. Schéma de prise COMPLEXE (remarque 4) et dégressif / progressif (remarque 6) : le schéma complet est conservé
   et imprimé tel quel ; à VIDAL on n'envoie que le palier à la dose journalière la PLUS ÉLEVÉE (`palier_maximal`).
"""
from __future__ import annotations

import html as _html
import re
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 1. Corps XML et lecture de la réponse /posology-descriptors
# ---------------------------------------------------------------------------


def _texte(parent: ET.Element, balise: str, valeur: Any) -> None:
    """Ajoute <balise>valeur</balise> sauf si la valeur est vide."""
    if valeur in (None, ""):
        return
    ET.SubElement(parent, balise).text = str(valeur)


def _nombre(valeur: Any) -> Optional[str]:
    """80.0 -> "80", 2.5 -> "2.5"."""
    if valeur in (None, ""):
        return None
    try:
        f = float(valeur)
    except (TypeError, ValueError):
        return str(valeur)
    return str(int(f)) if f.is_integer() else f"{round(f, 4):g}"


def _date_vidal(valeur: Any) -> Optional[str]:
    """"2026-09-09" -> "2026-09-09T00:00:00"."""
    if valeur in (None, ""):
        return None
    texte = valeur.isoformat() if hasattr(valeur, "isoformat") else str(valeur)
    return texte if "T" in texte else f"{texte[:10]}T00:00:00"


def construire_xml_posology_request(patient: dict, route_ref: Optional[str] = None) -> str:
    """Corps XML de /…/posology-descriptors : <posology-request><patient> dateOfBirth, gender, weight, height,
    [breastFeedingStartDate], [hepaticInsufficiency], [routes/route]. Les valeurs vides sont omises."""
    patient = patient or {}
    racine = ET.Element("posology-request")
    p = ET.SubElement(racine, "patient")
    _texte(p, "dateOfBirth", _date_vidal(patient.get("dateOfBirth")))
    _texte(p, "gender", patient.get("gender"))
    _texte(p, "weight", _nombre(patient.get("weight")))
    _texte(p, "height", _nombre(patient.get("height")))
    if patient.get("gender") == "FEMALE":
        _texte(p, "breastFeedingStartDate", _date_vidal(patient.get("breastFeedingStartDate")))
    _texte(p, "hepaticInsufficiency", patient.get("hepaticInsufficiency"))
    if route_ref:
        routes = ET.SubElement(p, "routes")
        _texte(routes, "route", f"vidal://route/{route_ref}")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(racine, encoding="unicode")


_ENTREE_RE = re.compile(r"<entry\b[^>]*>(.*?)</entry>", re.DOTALL | re.IGNORECASE)


def _balise_re(nom: str) -> "re.Pattern[str]":
    return re.compile(rf"<(?:[a-z][a-z0-9]*:)?{nom}\b[^>]*>([^<]*)</(?:[a-z][a-z0-9]*:)?{nom}>", re.IGNORECASE)


_DOSE_RE, _FREQ_RE, _INDIC_RE, _ROUTE_RE = _balise_re("doseRange"), _balise_re("frequencyRange"), _balise_re("indication"), _balise_re("route")


def _nettoyer(brut: str) -> str:
    """Décode les entités (deux passes : VIDAL double-échappe) puis retire les balises résiduelles."""
    t = _html.unescape(_html.unescape(brut or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()


def parser_descripteurs_posologie(brut: Optional[str]) -> list[dict]:
    """[{indication, route, doses:[…], frequence}] — une par <entry> POSOLOGY_DESCRIPTOR.
    `doses` : la même dose exprimée dans plusieurs unités (ex. « 3 sachets par jour » et « 30 g par jour »).
    Réponse illisible ou sans posologie -> liste vide, jamais d'exception."""
    if not isinstance(brut, str) or "POSOLOGY_DESCRIPTOR" not in brut:
        return []
    sortie: list[dict] = []
    for bloc in _ENTREE_RE.findall(brut):
        doses = [_nettoyer(d) for d in _DOSE_RE.findall(bloc) if d.strip()]
        if not doses:
            continue
        f, i, r = _FREQ_RE.search(bloc), _INDIC_RE.search(bloc), _ROUTE_RE.search(bloc)
        sortie.append({
            "doses": doses,
            "frequence": _nettoyer(f.group(1)) if f else None,
            "indication": _nettoyer(i.group(1)) if i else None,
            "route": _nettoyer(r.group(1)) if r else None,
        })
    return sortie


# ---------------------------------------------------------------------------
# 2. Informations patient manquantes : alerte, jamais un blocage
# ---------------------------------------------------------------------------


def patient_manquants(patient: Optional[dict]) -> list[str]:
    """Libellés des informations dont VIDAL a besoin pour proposer une posologie et qui sont absentes."""
    patient = patient or {}
    manquants = []
    if not patient.get("dateOfBirth"):
        manquants.append("l'âge (date de naissance)")
    if patient.get("gender") not in ("MALE", "FEMALE"):
        manquants.append("le sexe (Homme ou Femme)")
    if patient.get("weight") in (None, "", 0, "0"):
        manquants.append("le poids")
    return manquants


def message_manquants(manquants: list[str]) -> Optional[str]:
    """Texte d'alerte affiché à l'utilisateur (None si rien ne manque)."""
    if not manquants:
        return None
    return ("VIDAL ne propose aucune posologie sans " + ", ".join(manquants)
            + ". Renseignez-le(s) pour obtenir des propositions ; vous pouvez néanmoins saisir la posologie vous-même.")


# ---------------------------------------------------------------------------
# 3. Schéma de prise complexe / dégressif / progressif
# ---------------------------------------------------------------------------
# Un schéma = liste de PALIERS. Un palier = {"debut_jour": 0, "fin_jour": 4 | None, "prises": [prise, …]}
# Une prise = {"moment": "matin|midi|soir|coucher|heure", "heure": "08:00" (si moment=heure),
#              "quantite": 2, "repas": "avant|pendant|apres|indifferent"}
# `debut_jour` : décalage en jours depuis le début du traitement (0 = aujourd'hui). `fin_jour` None = jusqu'à la fin.

MOMENTS = {"matin": "le matin", "midi": "à midi", "soir": "le soir", "coucher": "au coucher", "heure": "à l'heure indiquée"}
REPAS = {"avant": "avant le repas", "pendant": "pendant le repas", "apres": "après le repas", "indifferent": ""}


def dose_journaliere(palier: dict) -> float:
    """Somme des quantités des prises du palier (dose par 24 h)."""
    total = 0.0
    for prise in (palier or {}).get("prises") or []:
        try:
            total += float(prise.get("quantite") or 0)
        except (TypeError, ValueError):
            continue
    return total


def palier_maximal(schema: list[dict]) -> Optional[dict]:
    """Palier à la dose journalière la plus élevée (le premier en cas d'égalité) — c'est lui qui part à VIDAL."""
    paliers = [p for p in (schema or []) if dose_journaliere(p) > 0]
    if not paliers:
        return None
    return max(paliers, key=dose_journaliere)  # max() garde le premier en cas d'égalité


def tendance(schema: list[dict]) -> str:
    """'constant' (un seul palier ou doses égales), 'progressif' (doses croissantes), 'degressif' (décroissantes), 'variable'."""
    doses = [dose_journaliere(p) for p in (schema or []) if dose_journaliere(p) > 0]
    if len(doses) <= 1 or len(set(doses)) == 1:
        return "constant"
    if all(a <= b for a, b in zip(doses, doses[1:])):
        return "progressif"
    if all(a >= b for a, b in zip(doses, doses[1:])):
        return "degressif"
    return "variable"


def _q(valeur: float) -> str:
    return str(int(valeur)) if float(valeur).is_integer() else f"{valeur:g}".replace(".", ",")


def libelle_prise(prise: dict, unite: str = "") -> str:
    """« 2 comprimés le matin avant le repas »."""
    quantite = float(prise.get("quantite") or 0)
    moment = MOMENTS.get(prise.get("moment"), "")
    if prise.get("moment") == "heure" and prise.get("heure"):
        moment = f"à {prise['heure']}"
    repas = REPAS.get(prise.get("repas") or "indifferent", "")
    return " ".join(x for x in (_q(quantite), unite, moment, repas) if x).strip()


def libelle_schema(schema: list[dict], unite: str = "") -> str:
    """Texte imprimable du schéma complet, un palier par ligne (ex. « Dès aujourd'hui : 2 cp le matin ; dans 5 jours : 1 cp le matin »)."""
    lignes = []
    for palier in schema or []:
        prises = " ; ".join(libelle_prise(p, unite) for p in palier.get("prises") or [] if float(p.get("quantite") or 0) > 0)
        if not prises:
            continue
        debut = int(palier.get("debut_jour") or 0)
        fin = palier.get("fin_jour")
        if debut == 0:
            quand = "Dès aujourd'hui" if fin is None else "À partir d'aujourd'hui"
        else:
            quand = f"À partir du jour {debut + 1} (dans {debut} jour{'s' if debut > 1 else ''})"
        if fin is not None:
            quand += f", jusqu'au jour {int(fin) + 1}"
        lignes.append(f"{quand} : {prises}")
    return "\n".join(lignes)


def valider_schema(schema: list[dict]) -> list[str]:
    """Erreurs lisibles (liste vide = schéma correct) : paliers qui se chevauchent, quantités négatives, moment inconnu."""
    erreurs: list[str] = []
    precedent_fin: Optional[int] = None
    for i, p in enumerate(schema or [], 1):
        debut, fin = int(p.get("debut_jour") or 0), p.get("fin_jour")
        if debut < 0:
            erreurs.append(f"Palier {i} : le jour de début ne peut pas être négatif.")
        if fin is not None and int(fin) < debut:
            erreurs.append(f"Palier {i} : le jour de fin précède le jour de début.")
        if precedent_fin is not None and debut <= precedent_fin:
            erreurs.append(f"Palier {i} : chevauche le palier précédent (il doit commencer après le jour {precedent_fin + 1}).")
        precedent_fin = int(fin) if fin is not None else 10 ** 6
        for prise in p.get("prises") or []:
            if float(prise.get("quantite") or 0) < 0:
                erreurs.append(f"Palier {i} : une quantité est négative.")
            if prise.get("moment") not in MOMENTS:
                erreurs.append(f"Palier {i} : moment de la journée inconnu ({prise.get('moment')}).")
    return erreurs


def ligne_vidal_depuis_schema(schema: list[dict]) -> Optional[dict]:
    """Ce qui est transmis à VIDAL pour un schéma : {dose (par 24 h), nb_prises, palier} du palier maximal, ou None."""
    palier = palier_maximal(schema)
    if not palier:
        return None
    return {"dose": dose_journaliere(palier), "nb_prises": len([p for p in palier["prises"] if float(p.get("quantite") or 0) > 0]), "palier": palier}
