"""Lot 129 — règle UNIQUE du retard de paiement d'un client (même règle que la puce de contrat, lot 127.3).

Le retard se compte à partir de l'ÉCHÉANCE, et non plus du jour du dernier règlement :
    échéance = dernier règlement (`last_payment_at`, à défaut `contract_signed_at`) + périodicité
               (`contract_billing_period` : mensuel 30 j — par défaut —, trimestriel 90 j, annuel 365 j)
    retard   = jours écoulés depuis l'échéance (0 tant qu'elle n'est pas passée)
Le client est « en retard » quand ce retard atteint son seuil (`contract_overdue_days`, sinon le seuil global).

Utilisée par : Admin → Clients (colonne « Retard », via /api/admin/clients), l'alerte quotidienne des retards et la
suspension automatique (p17), la validité du contrat lue par Liluvine (liluvine_wa_autoreply).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

# Durée de chaque périodicité de facturation, en jours (même table que la puce de contrat et abonnement_acces)
PERIODES_JOURS = {"monthly": 30, "quarterly": 90, "annual": 365}


def _jour(valeur: Any) -> Optional[date]:
    """« 2026-10-15 » (ou date ISO complète) → date ; None si vide ou illisible."""
    try:
        return datetime.strptime(str(valeur or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def retard_client(u: Dict[str, Any], aujourdhui: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """Retard de paiement d'une fiche client.

    Renvoie None si aucune date de référence n'est connue, sinon :
      {jours, ref_iso, ref_field, echeance_iso, periode_jours}
      - jours        : jours de retard comptés depuis l'échéance (0 si l'échéance n'est pas encore passée)
      - ref_iso      : date du dernier règlement (ou de signature)
      - ref_field    : « last_payment_at » ou « contract_signed_at »
      - echeance_iso : date d'échéance calculée
    """
    aujourdhui = aujourdhui or datetime.now(timezone.utc).date()
    ref_field = "last_payment_at" if u.get("last_payment_at") else "contract_signed_at"
    ref = _jour(u.get(ref_field))
    if not ref:
        return None
    # Périodicité inconnue → mensuelle (comme la puce de contrat)
    periode = str(u.get("contract_billing_period") or "").strip().lower()
    periode_jours = PERIODES_JOURS.get(periode, PERIODES_JOURS["monthly"])
    echeance = ref + timedelta(days=periode_jours)
    return {
        "jours": max(0, (aujourdhui - echeance).days),
        "ref_iso": ref.isoformat(), "ref_field": ref_field,
        "echeance_iso": echeance.isoformat(), "periode_jours": periode_jours,
    }
