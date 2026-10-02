"""Lot 50 — Contrôles d'accès faits à CHAQUE requête authentifiée (auth.get_current_user).

Dans cet ordre :
  1. maintenance de la plateforme (maintenance_plateforme.py) : 503 pendant la maintenance,
     401 pour une session ouverte avant la dernière maintenance ;
  2. session du compte (sessions_comptes.py) : session fermée (limite d'appareils, fermée
     depuis « Mon compte » ou par l'Admin) ou inactive trop longtemps → 401 ;
  3. lot 51 — cycle de vie du non-renouvellement (cycle_vie_abonnements.py) : client suspendu
     (J+110) ou archivé (J+113) → 403 « abonnement_suspendu » sur toutes les routes ;
  4. abonnement du client (abonnement_acces.py) : après la période de grâce → 402, sauf les
     routes de l'écran « Abonnement expiré » (profil minimal, état de l'abonnement,
     sessions, déconnexion).

Les refus portent un `code` lisible par le site (réponse {"detail": ..., "code": ...}) : le
navigateur affiche le bon écran (maintenance, session fermée, abonnement expiré).
Les Admins de la plateforme ne sont jamais bloqués ; une session « Voir en tant que » (lot 44)
n'est soumise ni à la limite d'appareils ni au contrôle d'inactivité (elle a sa propre durée).
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class RefusAcces(HTTPException):
    """Refus avec un code lisible par le site (ex. « maintenance_plateforme »)."""

    def __init__(self, status_code: int, detail: str, code: Optional[str] = None):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


async def gestionnaire_refus(_request: Request, exc: RefusAcces) -> JSONResponse:
    contenu = {"detail": exc.detail}
    if exc.code:
        contenu["code"] = exc.code
    return JSONResponse(status_code=exc.status_code, content=contenu)


def chemin_de(request: Optional[Request]) -> str:
    if request is None:
        return ""
    p = request.url.path or "/"
    return p.rstrip("/") if len(p) > 1 else p


def requete_de_fond(request: Optional[Request]) -> bool:
    """Requête automatique du navigateur (sondage périodique) : ne compte pas comme une activité."""
    if request is None:
        return False
    return (request.headers.get("x-requete-fond") or "").strip() in {"1", "true", "oui"}


async def controler_requete(user: dict, jeton: dict, request: Optional[Request]) -> None:
    import abonnement_acces
    import cycle_vie_abonnements
    import maintenance_plateforme
    import sessions_comptes

    await maintenance_plateforme.controler_session(user, jeton)
    await sessions_comptes.controler(user, jeton, request)
    await cycle_vie_abonnements.controler(user, jeton, chemin_de(request))
    await abonnement_acces.controler(user, jeton, chemin_de(request))
