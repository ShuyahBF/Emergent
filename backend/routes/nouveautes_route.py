"""Lot 68.3 — route des cartes « Nouveautés de la semaine » (page Paramètres).

La liste vient de backend/nouveautes.py (source unique, complétée à CHAQUE lot : règle du propriétaire,
vérifiée par tests/test_regle_nouveautes.py)."""


def setup_nouveautes_routes(*, api, get_current_user) -> None:
    """Branche GET /api/admin/nouveautes (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException
    from nouveautes import nouveautes_valides, lot_courant

    @api.get("/admin/nouveautes", tags=["Paramètres"])
    async def nouveautes(user: dict = Depends(get_current_user)):
        """Nouveautés des lots (les plus récentes en premier) et lot actuellement déployé."""
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return {"lot_courant": lot_courant(), "nouveautes": nouveautes_valides()}
