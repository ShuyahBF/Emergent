"""Cache local du référentiel produits VIDAL (portage site-meetafrican).

Chaque frappe clavier dans la recherche médicament (Fiche produit,
Posologie, autocomplete de Sécurisation — `GET /vidal/search/parsed`,
voir vidal_fiche.py) déclenchait un aller-retour réseau réel vers VIDAL.
Ce module ajoute une synchronisation optionnelle (activée par l'admin) de
tout le catalogue VIDAL vers une collection Mongo locale
(`vidal_cache_referentiel_produits`), pour une recherche instantanée sans
appel réseau à chaque frappe.

Chiffres réels confirmés par test (voir PORTAGE-SAWALI-VIDAL.md) : VIDAL
a 15 680 produits au total, paginés 25/page (`GET /products` avec `q`
vide) → ~628 appels pour un sync complet. C'est une opération admin, PAS
soumise au quota journalier anti-abus (`_quota_check_and_increment`,
protège contre des utilisateurs finaux — jamais appelé ici).

Portée volontairement limitée à `/vidal/search/parsed` (autocomplete réel
ajouté dans ce lot) — l'ancien `/vidal/search` (onglet "Recherche" de
Vidal.jsx, déjà en production) n'est pas modifié, pour ne pas changer un
comportement déjà déployé sans demande explicite.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Query

logger = logging.getLogger("sawali.vidal.sync")

_CONFIG_ID = "singleton"
_PAGE_SIZE = 25
_SCHEDULER_CHECK_INTERVAL_SECONDS = 3600  # vérifie 1x/heure si une sync est due
_TOTAL_RESULTS_RE = re.compile(r"<opensearch:totalResults>(\d+)</opensearch:totalResults>", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_total_results(raw: Optional[str]) -> int:
    if not isinstance(raw, str):
        return 0
    m = _TOTAL_RESULTS_RE.search(raw)
    return int(m.group(1)) if m else 0


async def get_sync_config(db) -> Dict[str, Any]:
    """Config de synchronisation — créée avec des valeurs par défaut
    prudentes si absente : mode "temps_reel" par défaut (on ne bascule
    jamais la recherche sur un cache vide sans sync préalable)."""
    doc = await db.vidal_sync_config.find_one({"id": _CONFIG_ID}, {"_id": 0})
    if doc:
        return doc
    default = {
        "id": _CONFIG_ID,
        "mode": "temps_reel",  # "temps_reel" | "cache"
        # Portage — 0 (désactivé) par défaut, PAS 7 comme dans le prototype
        # site-meetafrican : sur un premier déploiement Sawali, `last_sync_at`
        # est null donc une fréquence non nulle déclencherait un sync complet
        # (~628 appels VIDAL) dès le démarrage du serveur, sans action admin.
        # Point explicitement signalé comme "à confirmer" dans
        # PORTAGE-SAWALI-VIDAL.md — on part du comportement le plus prudent
        # (l'admin choisit une fréquence ou lance "Synchroniser maintenant"
        # explicitement) plutôt que de décider à sa place.
        "frequency_days": 0,
        "last_sync_at": None,
        "sync_in_progress": False,
        "updated_at": _now(),
    }
    await db.vidal_sync_config.update_one({"id": _CONFIG_ID}, {"$setOnInsert": default}, upsert=True)
    return default


async def update_sync_config(db, mode: Optional[str] = None, frequency_days: Optional[int] = None) -> Dict[str, Any]:
    if mode is not None and mode not in ("temps_reel", "cache"):
        raise ValueError("mode invalide (attendu : temps_reel | cache)")
    update: Dict[str, Any] = {"updated_at": _now()}
    if mode is not None:
        update["mode"] = mode
    if frequency_days is not None:
        update["frequency_days"] = max(0, int(frequency_days))
    await get_sync_config(db)  # garantit l'existence du doc avant le $set
    await db.vidal_sync_config.update_one({"id": _CONFIG_ID}, {"$set": update})
    return await get_sync_config(db)


async def has_cached_referentiel(db) -> bool:
    config = await get_sync_config(db)
    return config.get("last_sync_at") is not None


async def search_cached_referentiel(db, q: str, limit: int = 25) -> List[Dict[str, Any]]:
    """Recherche dans le cache local — même forme de résultat que
    `_parse_atom_entries` ({title, vidal_id, vmp_id}) pour rester un
    remplacement transparent côté `/vidal/search/parsed`."""
    cursor = db.vidal_cache_referentiel_produits.find(
        {"name": {"$regex": re.escape(q), "$options": "i"}}
    ).limit(limit)
    results = []
    async for doc in cursor:
        results.append({"title": doc.get("name"), "vidal_id": doc.get("product_id"), "vmp_id": doc.get("vmp_id")})
    return results


async def run_referentiel_sync(db, triggered_by: str = "cron") -> Dict[str, Any]:
    """Parcourt tout le catalogue VIDAL et met à jour le cache Mongo.
    Toujours journalisé (succès, échec ou partiel) — jamais d'exécution
    silencieuse."""
    from routes.vidal import _load_config, _ensure_active, _vidal_call
    from routes.vidal_riche import _parse_atom_entries

    config = await get_sync_config(db)
    if config.get("sync_in_progress"):
        logger.info("[vidal_sync] déjà en cours, run ignoré (%s)", triggered_by)
        return {"status": "skipped_already_running"}

    await db.vidal_sync_config.update_one({"id": _CONFIG_ID}, {"$set": {"sync_in_progress": True}})
    start = _now()
    page = 1
    total_expected: Optional[int] = None
    synced_count = 0
    api_calls = 0
    error_message: Optional[str] = None

    try:
        cfg = await _load_config(db)
        _ensure_active(cfg)
        while True:
            data = await _vidal_call(
                cfg, "GET", "/products",
                params={"q": "", "start-page": page, "page-size": _PAGE_SIZE},
            )
            api_calls += 1
            raw = (data or {}).get("raw")
            if total_expected is None:
                total_expected = _parse_total_results(raw)
            entries = _parse_atom_entries(raw)
            if not entries:
                break

            now = _now()
            for e in entries:
                if not e.get("vidal_id"):
                    continue
                await db.vidal_cache_referentiel_produits.update_one(
                    {"product_id": e["vidal_id"]},
                    {"$set": {
                        "product_id": e["vidal_id"], "name": e.get("title"),
                        "vmp_id": e.get("vmp_id"), "synced_at": now,
                    }},
                    upsert=True,
                )
                synced_count += 1

            if total_expected and synced_count >= total_expected:
                break
            page += 1
    except Exception as exc:  # noqa: BLE001 — on journalise puis on relance, jamais d'échec silencieux
        error_message = str(exc)[:500]
        logger.exception("[vidal_sync] erreur pendant la synchronisation du référentiel")
    finally:
        await db.vidal_sync_config.update_one({"id": _CONFIG_ID}, {"$set": {"sync_in_progress": False}})

    finished = _now()
    duration_seconds = (finished - start).total_seconds()
    status = "error" if (error_message and synced_count == 0) else ("partial" if error_message else "success")
    result_summary = (
        f"{synced_count} produit(s) synchronisé(s) sur {total_expected or '?'} annoncés, "
        f"{api_calls} appel(s) API VIDAL, {duration_seconds:.0f}s"
        + (f" — erreur : {error_message}" if error_message else "")
    )
    log_entry = {
        "ts": start, "type": "sync_refer", "status": status, "result": result_summary,
        "products_synced": synced_count, "products_expected": total_expected,
        "api_calls": api_calls, "duration_seconds": round(duration_seconds, 1),
        "triggered_by": triggered_by, "error_message": error_message,
    }
    await db.vidal_sync_log.insert_one(log_entry.copy())
    if status != "error":
        await db.vidal_sync_config.update_one({"id": _CONFIG_ID}, {"$set": {"last_sync_at": start}})
    logger.info("[vidal_sync] terminé : %s", result_summary)
    return log_entry


async def _maybe_run_scheduled_sync(db) -> None:
    config = await get_sync_config(db)
    frequency_days = config.get("frequency_days") or 0
    if frequency_days <= 0:
        return  # 0 = planification désactivée, seule la sync manuelle reste possible
    last_sync_at = config.get("last_sync_at")
    if isinstance(last_sync_at, datetime) and last_sync_at.tzinfo is None:
        last_sync_at = last_sync_at.replace(tzinfo=timezone.utc)
    due = last_sync_at is None or (_now() - last_sync_at) >= timedelta(days=frequency_days)
    if due:
        await run_referentiel_sync(db, triggered_by="cron")


async def sync_scheduler_loop(db) -> None:
    """Boucle de fond démarrée au démarrage du serveur (voir server.py).
    Pas de vrai service cron externe (volume trop faible pour le justifier) ;
    la fréquence reste reconfigurable dynamiquement par l'admin."""
    while True:
        try:
            await _maybe_run_scheduled_sync(db)
        except Exception:  # noqa: BLE001 — la boucle ne doit jamais s'arrêter sur une erreur ponctuelle
            logger.exception("[vidal_sync] erreur dans la boucle de planification")
        await asyncio.sleep(_SCHEDULER_CHECK_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# Route attachment
# ---------------------------------------------------------------------------
def attach_vidal_sync_routes(*, api, db, get_current_admin):
    @api.get("/vidal/admin/sync-config", tags=["Admin — VIDAL"])
    async def get_sync_config_route(_: dict = Depends(get_current_admin)):
        return await get_sync_config(db)

    @api.put("/vidal/admin/sync-config", tags=["Admin — VIDAL"])
    async def update_sync_config_route(
        mode: Optional[str] = Body(None, embed=True),
        frequency_days: Optional[int] = Body(None, embed=True),
        _: dict = Depends(get_current_admin),
    ):
        try:
            return await update_sync_config(db, mode=mode, frequency_days=frequency_days)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @api.post("/vidal/admin/sync-now", tags=["Admin — VIDAL"])
    async def trigger_sync_now(_: dict = Depends(get_current_admin)):
        config = await get_sync_config(db)
        if config.get("sync_in_progress"):
            return {"status": "already_running"}
        asyncio.create_task(run_referentiel_sync(db, triggered_by="manuel"))
        return {"status": "started"}

    @api.get("/vidal/admin/sync-log", tags=["Admin — VIDAL"])
    async def get_sync_log(limit: int = Query(20, ge=1, le=100), _: dict = Depends(get_current_admin)):
        cursor = db.vidal_sync_log.find({}, {"_id": 0}).sort("ts", -1).limit(limit)
        return {"entries": [entry async for entry in cursor]}

    logger.info("[vidal_sync] routes mounted under /api/vidal/admin/sync-*")
