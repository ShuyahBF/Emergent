"""Lot 186 — compte rendu WhatsApp à l'administrateur à chaque envoi de carrousels.

À la fin d'une campagne de carrousels, SAWALI écrit au numéro réglé dans Paramètres (`carrousel_notif_wa_phone`) : qui a
envoyé, quel modèle, combien d'envois réussis / en échec. Numéro vide = aucune notification. Le texte est construit par
une fonction pure (testable) ; l'envoi lui-même ne bloque et ne fait JAMAIS échouer la campagne.
"""
from __future__ import annotations

from typing import Any, Dict


def texte_envoi_carrousel(c: Dict[str, Any]) -> str:
    """Message de compte rendu d'une campagne de carrousels terminée. Fonction pure."""
    compte = c.get("compte") or {}
    envoyes, echecs, total = int(compte.get("envoyes") or 0), int(compte.get("echecs") or 0), int(compte.get("total") or 0)
    origine = "administration SAWALI" if c.get("perimetre") == "admin" else "un client"
    lignes = [
        "📣 Carrousel WhatsApp envoyé",
        f"Expéditeur : {c.get('expediteur') or '—'} ({origine})",
        f"Par : {c.get('cree_par_nom') or '—'}",
        f"Modèle : {c.get('modele') or '—'} · {len(c.get('cartes') or [])} carte(s)",
        f"Destinataires : {total} · envoyés {envoyes} · échecs {echecs}",
    ]
    if echecs:
        lignes.append("⚠️ Des envois ont échoué : voir le détail de la campagne dans le portail.")
    lignes.append(f"Campagne {str(c.get('id') or '')[:8]}")
    return "\n".join(lignes)
