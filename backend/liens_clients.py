"""Lien « client lié canonique » d'une fiche client : règle de validation (lot 451.2, propriétaire 23/11/2026).

Constat : à la mise à jour de la fiche d'un NOUVEAU client, SAWALI répondait « Client canonique introuvable » alors que le lien avait été accepté par
l'administrateur à la création (suggestion « cette société existe déjà »). Cause : la création accepte n'importe quel compte comme client canonique,
mais la mise à jour re-vérifiait le lien à chaque enregistrement avec une liste de rôles plus étroite (admin, superviseur, modérateur, client) :
si le client canonique avait un autre rôle, l'enregistrement était refusé même sans changer le lien.
Règle maintenant : un lien INCHANGÉ n'est jamais re-vérifié ; un lien CHANGÉ doit viser un compte existant (quel que soit son rôle, comme à la création)."""
from typing import Optional


def lien_a_valider(lien_demande: Optional[str], parent_actuel: Optional[str]) -> bool:
    """Vrai si le lien demandé est NOUVEAU (à vérifier) ; faux s'il est vide ou identique au lien déjà enregistré (rien à vérifier)."""
    lien = (lien_demande or "").strip()
    return bool(lien) and lien != (parent_actuel or "").strip()
