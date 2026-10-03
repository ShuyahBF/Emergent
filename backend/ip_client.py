"""Lot 55 — Adresse IP réelle du visiteur : UNE seule fonction, utilisée partout.

Sur Render (comme avant derrière l'ingress Kubernetes), le serveur ne voit que l'adresse du
répartiteur de charge : l'adresse du visiteur est le PREMIER élément de l'en-tête
`X-Forwarded-For` (« client, proxy1, proxy2 »). Sans cet en-tête (appel direct, tests), on
prend l'adresse de la connexion (`request.client.host`).

Avant ce lot, la même lecture était recopiée dans plusieurs fichiers (server.py,
sessions_comptes.py, formulaires publics, suivi des visites, restauration…) ; elle est
maintenant factorisée ici.
"""
from __future__ import annotations

from typing import Any

LONGUEUR_MAX = 64   # une IPv6 complète tient en 45 caractères ; on borne ce qui est stocké


def ip_reelle(request: Any) -> str:
    """IP du visiteur : premier élément de X-Forwarded-For, sinon request.client.host ; "" si inconnue."""
    if request is None:
        return ""
    entetes = getattr(request, "headers", None) or {}
    xff = entetes.get("x-forwarded-for") or entetes.get("X-Forwarded-For") or ""
    if xff:
        premiere = xff.split(",")[0].strip()
        if premiere:
            return premiere[:LONGUEUR_MAX]
    client = getattr(request, "client", None)
    return ((getattr(client, "host", "") or "") if client else "")[:LONGUEUR_MAX]
