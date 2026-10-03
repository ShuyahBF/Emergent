"""
backend/vidal_v2/traitements_en_cours.py
----------------------------------------
Lot 56 — repris de Ster (app/utils/vidal_traitements_en_cours.py) ; code
inchangé, commentaire d'en-tête reformulé.

§ doc VIDAL : la sécurisation doit porter sur la nouvelle prescription ET
sur les traitements courants du patient, c'est-à-dire les lignes des
prescriptions antérieures encore en cours à la date du jour.

Ce module, sans dépendance Mongo/FastAPI (portable), déduit ces
traitements courants d'une liste d'ordonnances déjà enregistrées :
  - si la ligne porte ses données de sécurisation structurées
    (`donnees_vidal`, enregistrées depuis la v2 au moment où la ligne a
    été sécurisée), la période / la durée exactes servent au calcul ;
  - sinon, la durée texte libre historique ("7 jours", "2 sem", "1 mois")
    est interprétée à partir de la date de l'ordonnance ;
  - une durée impossible à interpréter n'exclut pas la ligne : elle est
    PROPOSÉE non cochée (au médecin de décider), seulement pour les
    ordonnances des 30 derniers jours.
Seules les lignes rapprochées d'un produit VIDAL (vidal_id) sont
retenues : les autres ne peuvent pas être analysées par le moteur.
"""

import re
from datetime import date, datetime, timedelta
from typing import Optional

# Durée (en jours) d'une unité de durée VIDAL — mois et année approchés (30 j / 365 j).
_JOURS_PAR_UNITE = {"MINUTE": 0, "HOUR": 0, "DAY": 1, "WEEK": 7, "MONTH": 30, "YEAR": 365}

_DUREE_TEXTE_RE = re.compile(
    r"(\d+)\s*(minutes?|min|heures?|h|jours?|j|semaines?|sem|mois|m|ans?|années?|annees?)\b",
    re.IGNORECASE,
)
_UNITES_TEXTE = {
    "min": "MINUTE", "minute": "MINUTE", "minutes": "MINUTE",
    "h": "HOUR", "heure": "HOUR", "heures": "HOUR",
    "j": "DAY", "jour": "DAY", "jours": "DAY",
    "sem": "WEEK", "semaine": "WEEK", "semaines": "WEEK",
    "m": "MONTH", "mois": "MONTH",
    "an": "YEAR", "ans": "YEAR", "année": "YEAR", "années": "YEAR", "annee": "YEAR", "annees": "YEAR",
}

JOURS_PROPOSITION_DUREE_INCONNUE = 30


def interpreter_duree_texte(texte: Optional[str]) -> Optional[tuple[int, str]]:
    """"7 jours" -> (7, "DAY") ; "2 sem" -> (2, "WEEK") ; texte non interprétable -> None."""
    if not texte:
        return None
    m = _DUREE_TEXTE_RE.search(texte)
    if not m:
        return None
    unite = _UNITES_TEXTE.get(m.group(2).lower())
    return (int(m.group(1)), unite) if unite else None


def _en_date(valeur) -> Optional[date]:
    if valeur in (None, ""):
        return None
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    try:
        return date.fromisoformat(str(valeur)[:10])
    except ValueError:
        return None


def date_fin_estimee(debut: date, duree: int, type_duree: str) -> date:
    """Dernier jour d'administration : un traitement de 7 jours commencé le 1er se termine le 7."""
    jours = duree * _JOURS_PAR_UNITE.get(type_duree, 1)
    return debut + timedelta(days=max(jours - 1, 0))


def lignes_traitements_en_cours(ordonnances: list[dict], aujourdhui: Optional[date] = None) -> list[dict]:
    """Lignes (format du payload de sécurisation) des ordonnances antérieures encore en cours à la date du jour."""
    jour = aujourdhui or date.today()
    resultat: list[dict] = []
    for ordonnance in ordonnances:
        date_ordonnance = _en_date(ordonnance.get("date_creation"))
        for ligne in ordonnance.get("lignes") or []:
            # § validation VIDAL : une ligne d'ordonnance fictive non encore
            # rapprochée de VIDAL (nom à rechercher) est PROPOSÉE non cochée,
            # à rapprocher par le médecin ; toute autre ligne hors VIDAL est ignorée.
            if not ligne.get("vidal_id") and not ligne.get("recherche_vidal"):
                continue
            structure = ligne.get("donnees_vidal") or {}
            debut = _en_date(structure.get("startDate")) or date_ordonnance
            fin_saisie = _en_date(structure.get("endDate"))
            fin = fin_saisie
            duree_transcrite = None
            if fin is None and debut is not None:
                if structure.get("duration") and structure.get("durationType"):
                    fin = date_fin_estimee(debut, int(structure["duration"]), structure["durationType"])
                else:
                    duree_transcrite = interpreter_duree_texte(ligne.get("duree"))
                    if duree_transcrite:
                        fin = date_fin_estimee(debut, *duree_transcrite)
            if fin is not None and fin < jour:
                continue  # traitement terminé
            if fin is None and (debut is None or (jour - debut).days > JOURS_PROPOSITION_DUREE_INCONNUE):
                continue  # durée inconnue et ordonnance trop ancienne : on ne propose pas
            resultat.append({
                **{k: v for k, v in structure.items() if k not in ("groupType", "groupId", "status")},
                "drugRef": ligne.get("vidal_id") or None,
                "a_rapprocher": not ligne.get("vidal_id"), "recherche_vidal": ligne.get("recherche_vidal"),
                "label": ligne.get("designation"),
                # § aucune valeur devinée envoyée à VIDAL : la fin ESTIMÉE (mois
                # approchés à 30 jours) ne sert qu'à décider si le traitement est
                # en cours et à l'affichage ; seule une date de fin SAISIE part
                # dans <period>. Une durée texte ("3 mois") est transcrite telle quelle.
                "startDate": debut.isoformat() if debut else None,
                "endDate": fin_saisie.isoformat() if fin_saisie else None,
                "fin_estimee": fin.isoformat() if fin else None,
                **({"duration": duree_transcrite[0], "durationType": duree_transcrite[1]} if duree_transcrite else {}),
                "candidats_vidal": ligne.get("candidats_vidal") or [], "statut_reference": ligne.get("statut_reference"),
                "status": "ACTIVE",
                "groupType": "PREVIOUS_ORDER",
                # Métadonnées d'affichage (jamais transmises à VIDAL).
                "ordonnance_reference": ordonnance.get("reference"),
                "date_ordonnance": date_ordonnance.isoformat() if date_ordonnance else None,
                "duree_texte": ligne.get("duree"),
                "duree_connue": fin is not None,
                "coche_par_defaut": fin is not None and bool(ligne.get("vidal_id")),
            })
    return resultat
