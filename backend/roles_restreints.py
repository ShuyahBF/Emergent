"""Lot 54 — Rôle « Auxiliaire en Pharmacie » : contrôle CÔTÉ SERVEUR des routes permises.

L'utilisateur suivi dont le rôle (`users.tracked_role`, recopié depuis `tracked_users.role`) est
« Auxiliaire en Pharmacie » n'accède qu'à :
  - « Fiche Produit » et « Posologie » : recherche VIDAL et lecture des fiches produit
    (GET /api/vidal/search…, /api/vidal/product/…, /api/vidal/vmp/…) ;
  - « Ordonnances et Stock », réduit au scan et à l'OCR : POST /api/ordonnances-stock (dépôt des
    photos et lecture), GET /api/ordonnances-stock (historique de SES ordonnances scannées) et
    GET /api/ordonnances-stock/{id} (sans les données de stock ni les réservations) ;
  - les routes techniques du portail (connexion, profil, « Mon compte », sessions, fonctions
    activées, journal d'accès, signal d'activité).
Toute autre route authentifiée répond 403 (code « role_restreint »). Ce contrôle est appelé par
controle_acces.controler_requete, donc par CHAQUE dépendance auth.get_current_user ; « Ordonnances
et Stock » reste en plus soumis à la fonction cochée pour le client dans Outils+.
"""
from __future__ import annotations

import re
from typing import Optional

from controle_acces import RefusAcces

AUXILIAIRE_PHARMACIE = "Auxiliaire en Pharmacie"
CODE_REFUS = "role_restreint"
MESSAGE_REFUS = ("Accès refusé : le rôle « Auxiliaire en Pharmacie » donne accès uniquement à « Fiche Produit », "
                 "« Posologie » et « Ordonnances et Stock » (scan et OCR).")

# (méthodes, expression du chemin sans le préfixe /api)
_PERMIS = [
    ({"GET", "POST", "PUT", "DELETE"}, r"/auth/.*"),
    ({"GET"}, r"/me/(features|branding|access-summary|tenant-meta|abonnement|account-detail|officines-permissions)"),
    ({"POST"}, r"/me/(access-log|api-trace|activite|profile-update-request)"),
    ({"GET"}, r"/me/sessions"),
    ({"DELETE"}, r"/me/sessions/[^/]+"),
    # Fiche Produit / Posologie (VIDAL, lecture seule)
    ({"GET"}, r"/vidal/search(/.*)?"),
    ({"GET"}, r"/vidal/product/[^/]+(/.*)?"),
    ({"GET"}, r"/vidal/vmp/[^/]+(/.*)?"),
    # Ordonnances et Stock : scan + OCR et historique, rien d'autre
    ({"GET", "POST"}, r"/ordonnances-stock"),
    ({"GET"}, r"/ordonnances-stock/[^/]+"),
]
_PERMIS_RE = [(m, re.compile(r"^" + motif + r"$")) for m, motif in _PERMIS]


def est_auxiliaire(user: Optional[dict]) -> bool:
    if not user or (user.get("role") or "") in ("admin", "superviseur"):
        return False
    return (user.get("tracked_role") or "").strip().lower() == AUXILIAIRE_PHARMACIE.lower()


def chemin_permis(methode: str, chemin: str) -> bool:
    """Route permise à l'Auxiliaire en Pharmacie ? `chemin` avec ou sans le préfixe /api."""
    c = chemin or "/"
    if c.startswith("/api/") or c == "/api":
        c = c[4:] or "/"
    c = c.rstrip("/") or "/"
    m = (methode or "GET").upper()
    if m in ("HEAD", "OPTIONS"):
        m = "GET"
    return any(m in methodes and rx.match(c) for methodes, rx in _PERMIS_RE)


async def controler(user: dict, methode: str, chemin: str) -> None:
    """403 « role_restreint » pour toute route hors de la liste ci-dessus."""
    if not est_auxiliaire(user) or not chemin:
        return
    if not chemin_permis(methode, chemin):
        raise RefusAcces(403, MESSAGE_REFUS, CODE_REFUS)
