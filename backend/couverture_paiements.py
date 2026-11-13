"""Lot 390 — VALIDITÉ DU CONTRAT : jusqu'à quelle date le client a PAYÉ (couverture), et non « date du dernier paiement + période ».

PROBLÈME (constat du propriétaire, 14/11/2026) : l'échéance était calculée à partir de la DATE DU DERNIER PAIEMENT. Or un client peut avoir payé hier une facture de
prestations de JANVIER : il n'est pas à jour pour autant. Date de paiement ≠ période payée.

RÈGLE (comptable : un paiement règle d'abord la plus ancienne échéance impayée)
  - chaque paiement peut porter la PÉRIODE DE PRESTATIONS qu'il règle (`periode_debut`, `periode_fin`) ;
  - le contrat est couvert jusqu'à `couvert_jusqu_au` = fin de la couverture CONTINUE des périodes réglées (un mois manquant interrompt la couverture) ;
  - l'échéance = le lendemain de cette date ; le retard, la suspension, la puce de contrat, les rappels de facturation et l'accès à l'abonnement en partent.
Trois façons d'imputer un paiement (`imputation`) :
  - « date_paiement »  (par défaut, ANCIEN fonctionnement) : la période commence à la date du paiement ;
  - « plus_ancienne »  : le paiement règle la plus ancienne période impayée (nombre de périodes au choix) : le cas du client qui paie en retard ;
  - « periode »        : l'utilisateur indique les prestations réglées (du … au …).
Un client dont le dernier paiement n'a pas de période garde l'ancien calcul (aucun changement tant qu'on n'utilise pas les nouveaux modes).
Logique pure, testée par tests/test_lot390_couverture_paiements.py. Le champ `users.couvert_jusqu_au` est recalculé à chaque ajout ou suppression de paiement.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

IMPUTATIONS = ("date_paiement", "plus_ancienne", "periode")
PERIODES_JOURS = {"monthly": 30, "quarterly": 90, "annual": 365}      # même table que retard_echeance
MAX_JOURS_PERIODE = 800                                                # une période réglée ne dépasse pas ~2 ans


def jour(valeur: Any) -> Optional[date]:
    """« 2026-01-31 » (ou date ISO complète) → date ; None si vide ou illisible."""
    try:
        return datetime.strptime(str(valeur or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def jours_periode(u: Dict[str, Any]) -> int:
    """Durée d'une période de facturation du client, en jours (mensuelle par défaut)."""
    return PERIODES_JOURS.get(str(u.get("contract_billing_period") or "").strip().lower(), PERIODES_JOURS["monthly"])


def _est_paiement_de_contrat(p: Dict[str, Any]) -> bool:
    """Les frais de réouverture et autres lignes typées ne règlent pas une période de prestations."""
    return not p.get("type")


def _ordre(p: Dict[str, Any]) -> str:
    return str(p.get("created_at") or p.get("payment_date") or "")


def couvert_jusqu_au(paiements: List[Dict[str, Any]], periode_jours: int) -> Optional[date]:
    """Fin de la couverture continue, ou None (= ancien calcul : le dernier paiement n'a pas de période).
    Le dernier paiement SANS période (ancien mode) fixe le point de départ : sa couverture va de sa date à date + période − 1 ; les paiements avec période enregistrés
    APRÈS lui la prolongent tant qu'ils se suivent sans trou (un jour d'écart est toléré : fin 31/01, début 01/02)."""
    lignes = sorted((p for p in paiements if _est_paiement_de_contrat(p)), key=_ordre)
    dernier_ancien = next((i for i in range(len(lignes) - 1, -1, -1) if not (jour(lignes[i].get("periode_debut")) and jour(lignes[i].get("periode_fin")))), None)
    base: Optional[date] = None
    apres = lignes
    if dernier_ancien is not None:
        d = jour(lignes[dernier_ancien].get("payment_date"))
        base = d + timedelta(days=periode_jours - 1) if d else None
        apres = lignes[dernier_ancien + 1:]
    intervalles: List[Tuple[date, date]] = sorted((jour(p["periode_debut"]), jour(p["periode_fin"])) for p in apres if jour(p.get("periode_debut")) and jour(p.get("periode_fin")))
    if not intervalles:
        return None
    courant = base
    for debut, fin in intervalles:
        if courant is None:
            courant = fin                                                        # premier intervalle : départ de la chaîne
        elif debut <= courant + timedelta(days=1):
            courant = max(courant, fin)
        else:
            break                                                                # trou : la couverture s'arrête au dernier jour continu
    return courant


def fin_de_couverture_actuelle(u: Dict[str, Any], paiements: List[Dict[str, Any]]) -> Optional[date]:
    """Dernier jour déjà payé aujourd'hui : couverture calculée, sinon ancien calcul (dernier règlement + période − 1, à défaut signature + période − 1)."""
    pj = jours_periode(u)
    c = couvert_jusqu_au(paiements, pj)
    if c:
        return c
    ref = jour(u.get("last_payment_at")) or jour(u.get("contract_signed_at"))
    return ref + timedelta(days=pj - 1) if ref else None


def periode_a_imputer(imputation: str, u: Dict[str, Any], paiements: List[Dict[str, Any]], date_paiement: date, nb_periodes: int = 1,
                      debut: Optional[date] = None, fin: Optional[date] = None) -> Tuple[Optional[date], Optional[date]]:
    """Période de prestations réglée par un nouveau paiement. (None, None) = ancien mode. Lève ValueError si les dates saisies sont incohérentes."""
    if imputation not in IMPUTATIONS:
        raise ValueError("Imputation inconnue : date_paiement, plus_ancienne ou periode")
    pj = jours_periode(u)
    if imputation == "date_paiement":
        return None, None
    if imputation == "periode":
        if not debut or not fin:
            raise ValueError("Indiquez le début et la fin des prestations réglées")
        if fin < debut:
            raise ValueError("La fin des prestations doit suivre leur début")
        if (fin - debut).days > MAX_JOURS_PERIODE:
            raise ValueError("Période trop longue (2 ans au plus)")
        return debut, fin
    n = max(1, min(int(nb_periodes or 1), 24))
    actuelle = fin_de_couverture_actuelle(u, paiements)
    d = actuelle + timedelta(days=1) if actuelle else date_paiement                # rien de connu : la première période commence au paiement
    return d, d + timedelta(days=n * pj - 1)


def echeance_client(u: Dict[str, Any], periode_jours: int) -> Optional[date]:
    """ÉCHÉANCE d'un client : le lendemain du dernier jour couvert (`couvert_jusqu_au`), sinon l'ancien calcul (dernier règlement, à défaut signature, + période)."""
    c = jour(u.get("couvert_jusqu_au"))
    if c:
        return c + timedelta(days=1)
    ref = jour(u.get("last_payment_at")) or jour(u.get("contract_signed_at"))
    return ref + timedelta(days=periode_jours) if ref else None
