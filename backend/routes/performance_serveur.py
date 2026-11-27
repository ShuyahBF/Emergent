# routes/performance_serveur.py — Lot 463 : mémoire du serveur et appels les plus lents (Paramètres → « ⏱️ Performance du serveur »). Administrateur SEUL.
#   GET  /admin/performance/memoire            mesure immédiate (lecture locale) + échantillons horaires
#   GET  /admin/performance/appels             classement des routes par durée moyenne (en direct, sinon dernier relevé horaire)
#   POST /admin/performance/appels/reinitialiser   remet les compteurs à zéro (pour mesurer une action précise)
# Logique, stockage et alerte : voir backend/performance_serveur.py.
from __future__ import annotations

from fastapi import Depends, HTTPException

import performance_serveur as ps


def setup_performance_serveur_routes(*, db, api, get_current_user) -> None:
    def _admin(user: dict) -> None:
        if user.get("role") not in ("admin", "super_admin") and user.get("tracked_role") != "Administrateur":
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")

    @api.get("/admin/performance/memoire", tags=["Admin — Santé"])
    async def memoire(user: dict = Depends(get_current_user)):
        _admin(user)
        return await ps.mesurer(db)

    @api.get("/admin/performance/appels", tags=["Admin — Santé"])
    async def appels(limite: int = 40, user: dict = Depends(get_current_user)):
        _admin(user)
        # 500 routes au plus : l'export complet du tableau (le suivi garde 400 routes au plus)
        return await ps.appels(db, max(1, min(int(limite), 500)))

    @api.post("/admin/performance/appels/reinitialiser", tags=["Admin — Santé"])
    async def reinitialiser(user: dict = Depends(get_current_user)):
        _admin(user)
        ps.SUIVI.reinitialiser()
        ps.RETARD.reinitialiser()               # lot 474 : le relevé de réactivité repart aussi de zéro
        return {"ok": True, **ps.SUIVI.resume()}
