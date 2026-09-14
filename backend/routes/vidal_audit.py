"""Journal des appels API VIDAL réels — page "Suivi des logs" (portage
site-meetafrican, PR#7 "Journal des appels API VIDAL").

Ne journalise QUE les nouveaux endpoints de ce lot (Fiche produit,
Posologie, recherche structurée — voir vidal_fiche.py) : les appels déjà
en production (`/vidal/search`, `/vidal/product/{id}`, `!doc`/`!rech`,
actions VIDAL configurables) ne sont PAS instrumentés ici, pour ne pas
modifier le comportement de code déjà déployé et validé sans demande
explicite. `log_call` est fire-and-forget (jamais d'exception remontée à
l'appelant, jamais de blocage de la réponse HTTP réelle).

Note MAC address (voir PORTAGE-SAWALI-VIDAL.md, "Points à ne pas perdre") :
l'adresse MAC du poste n'est PAS capturable depuis un navigateur — cette
page ne tente donc jamais de l'afficher ni de la fabriquer ; elle
n'apparaît nulle part dans les entrées journalisées ci-dessous.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, Query

logger = logging.getLogger("sawali.vidal.audit")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def log_call(
    db, *, mode: str, method: str, path: str, status: str,
    elapsed_ms: Optional[int], user_email: Optional[str], error: Optional[str] = None,
) -> None:
    try:
        await db.vidal_api_calls_log.insert_one({
            "ts": _now(), "mode": mode, "method": method, "path": path,
            "status": status, "elapsed_ms": elapsed_ms, "user_email": user_email,
            "error": (error or "")[:300] or None,
        })
    except Exception:  # noqa: BLE001 — jamais bloquant pour l'appel VIDAL réel
        logger.exception("[vidal_audit] log_call failed")


def attach_vidal_audit_routes(*, api, db, get_current_admin):
    @api.get("/vidal/admin/api-calls-log", tags=["Admin — VIDAL"])
    async def get_api_calls_log(
        since: Optional[str] = Query(None, description="ISO 8601 — filtre 'à partir de'"),
        until: Optional[str] = Query(None, description="ISO 8601 — filtre 'jusqu'à'"),
        limit: int = Query(100, ge=1, le=500),
        _: dict = Depends(get_current_admin),
    ):
        query: Dict[str, Any] = {}
        ts_filter: Dict[str, Any] = {}
        if since:
            try:
                ts_filter["$gte"] = datetime.fromisoformat(since.replace("Z", "+00:00"))
            except ValueError:
                pass
        if until:
            try:
                ts_filter["$lte"] = datetime.fromisoformat(until.replace("Z", "+00:00"))
            except ValueError:
                pass
        if ts_filter:
            query["ts"] = ts_filter
        cursor = db.vidal_api_calls_log.find(query, {"_id": 0}).sort("ts", -1).limit(limit)
        return {"entries": [e async for e in cursor]}

    logger.info("[vidal_audit] routes mounted under /api/vidal/admin/api-calls-log")
