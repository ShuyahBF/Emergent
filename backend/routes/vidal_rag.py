"""Iter41 Phase 2 (2026-02) — VIDAL Qdrant RAG bridge.

Strategy : **Hybride**
  1. *Lazy* — chaque fois qu'un utilisateur consulte `/vidal/product/{id}` ou
     `/vidal/search`, on indexe la fiche reçue dans la collection Qdrant
     `VIDAL_db` (chunks de RCP + monographie + métadonnées).
  2. *Nightly* — un cron (`_scheduled_vidal_new_import`) scanne
     `/products/status?status=NEW` et indexe les nouveautés.

Le helper `build_vidal_rag_context(query, max_chars)` est utilisé par Liluvine
(web chat + WhatsApp) pour citer la fiche VIDAL pertinente quand l'utilisateur
demande des informations sur un médicament. Il ne se déclenche QUE si le
collection `VIDAL_db` existe et que `qdrant_enabled = True`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sawali.vidal_rag")

VIDAL_COLLECTION = "VIDAL_db"


def _serialize_product(product_id: int, data: Dict[str, Any]) -> Dict[str, str]:
    """Build a plain-text representation of a VIDAL product for indexing."""
    if not isinstance(data, dict):
        return {"title": str(product_id), "text": str(data)[:8000]}
    # VIDAL may wrap the actual content under various keys (Atom-style)
    inner = data.get("product") or data.get("entry") or data
    name = (
        inner.get("name")
        or inner.get("title")
        or (data.get("entries", [{}])[0].get("title") if data.get("entries") else None)
        or f"VIDAL {product_id}"
    )
    parts: List[str] = [f"Produit : {name}", f"ID VIDAL : {product_id}"]
    for k in ("substance", "active_substance", "molecule", "dci"):
        if inner.get(k):
            parts.append(f"Substance active : {inner[k]}")
            break
    for k in ("laboratory", "company", "manufacturer"):
        if inner.get(k):
            parts.append(f"Laboratoire : {inner[k]}")
            break
    for k in ("atc_class", "atc", "classification"):
        if inner.get(k):
            parts.append(f"Classe ATC : {inner[k]}")
            break
    for k in ("indication", "indications", "therapeutic_indication"):
        if inner.get(k):
            v = inner[k]
            if isinstance(v, list):
                v = "; ".join(str(x) for x in v[:5])
            parts.append(f"Indications : {str(v)[:1500]}")
            break
    # Fallback dump for anything else we may have missed.
    if len(parts) < 5:
        parts.append("Détails bruts :")
        import json as _json
        try:
            parts.append(_json.dumps(data, ensure_ascii=False)[:5000])
        except Exception:  # noqa: BLE001
            parts.append(str(data)[:5000])
    return {"title": str(name)[:200], "text": "\n".join(parts)}


async def _vidal_qdrant_enabled(db) -> bool:
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "qdrant_enabled": 1}) or {}
    return bool(s.get("qdrant_enabled"))


async def _ensure_vidal_collection(db) -> bool:
    """Create `VIDAL_db` if it does not exist. Returns True if available."""
    if not await _vidal_qdrant_enabled(db):
        return False
    try:
        from routes.qdrant_rag import _resolve_credentials, _make_client, _EMBED_VECTOR_SIZE
        url, key = await _resolve_credentials(db)
        client = _make_client(url, key)
        try:
            existing = client.get_collections()
            names = {c.name for c in (existing.collections or [])}
        except Exception:  # noqa: BLE001
            names = set()
        if VIDAL_COLLECTION not in names:
            from qdrant_client.models import VectorParams, Distance
            try:
                client.create_collection(
                    collection_name=VIDAL_COLLECTION,
                    vectors_config=VectorParams(size=_EMBED_VECTOR_SIZE, distance=Distance.COSINE),
                )
                logger.info(f"[vidal_rag] created Qdrant collection {VIDAL_COLLECTION}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[vidal_rag] could not create collection: {exc}")
                return False
        return True
    except Exception:  # noqa: BLE001
        logger.warning("[vidal_rag] _ensure_vidal_collection failed", exc_info=True)
        return False


async def index_product(db, product_id: int, data: Dict[str, Any], source: str = "lazy_product") -> None:
    """Lazy-index a single product into VIDAL_db. Idempotent — re-ingesting
    a product just overwrites the chunks (Qdrant deduplicates by point id is
    NOT automatic, but volume per product is small so we tolerate duplicates)."""
    if not await _ensure_vidal_collection(db):
        return
    serialized = _serialize_product(product_id, data)
    try:
        from routes.qdrant_rag import upsert_text_documents
        await upsert_text_documents(
            db,
            collection=VIDAL_COLLECTION,
            docs=[{
                "title": serialized["title"],
                "text": serialized["text"],
                "source": f"vidal://product/{product_id}",
                "tags": ["vidal", source, f"product_{product_id}"],
            }],
        )
    except Exception:  # noqa: BLE001
        logger.warning(f"[vidal_rag] index_product({product_id}) failed", exc_info=True)


async def index_search_results(db, data: Dict[str, Any], source: str = "lazy_search") -> None:
    """Lazy-index search hits — only the top-level metadata (no RCP) to keep
    the cost low. Useful so Liluvine can answer "do you know XYZ ?" without
    paying for a full product fetch."""
    if not await _ensure_vidal_collection(db):
        return
    entries = (
        (data or {}).get("entries")
        or (data or {}).get("items")
        or ((data or {}).get("feed", {}) or {}).get("entries")
        or []
    )
    if not isinstance(entries, list):
        return
    docs = []
    for e in entries[:20]:
        if not isinstance(e, dict):
            continue
        pid = e.get("id") or e.get("product_id") or e.get("vidal_id")
        try:
            pid_int = int(pid) if pid else None
        except (TypeError, ValueError):
            pid_int = None
        title = e.get("title") or e.get("name") or e.get("label") or str(pid or "?")
        text_parts = [f"Nom : {title}", f"ID VIDAL : {pid or '?'}"]
        if e.get("substance"):
            text_parts.append(f"Substance : {e['substance']}")
        if e.get("type"):
            text_parts.append(f"Type : {e['type']}")
        docs.append({
            "title": str(title)[:200],
            "text": "\n".join(text_parts),
            "source": f"vidal://search/{pid_int or 'unknown'}",
            "tags": ["vidal", source, "search_hit"],
        })
    if not docs:
        return
    try:
        from routes.qdrant_rag import upsert_text_documents
        await upsert_text_documents(db, collection=VIDAL_COLLECTION, docs=docs)
    except Exception:  # noqa: BLE001
        logger.warning("[vidal_rag] index_search_results failed", exc_info=True)


async def build_vidal_rag_context(db, *, query: str, max_chars: int = 3000) -> str:
    """Used by Liluvine to inject VIDAL knowledge into the system prompt.

    Returns an empty string when : Qdrant is disabled, the VIDAL_db collection
    doesn't exist, or the query yields no relevant hits. Otherwise returns
    a [Base de connaissance VIDAL France] block ready for prompt injection.
    """
    if not query or len(query.strip()) < 3:
        return ""
    if not await _vidal_qdrant_enabled(db):
        return ""
    try:
        from routes.qdrant_rag import search_points
        res = await search_points(db, collection=VIDAL_COLLECTION, query=query, top_k=4)
    except Exception:  # noqa: BLE001
        return ""
    hits = (res or {}).get("results") or (res or {}).get("hits") or []
    if not hits:
        return ""
    lines = ["[BASE DE CONNAISSANCE VIDAL France]"]
    total = 0
    for h in hits:
        payload = h.get("payload") or {}
        title = payload.get("title") or "(sans titre)"
        text = payload.get("text") or ""
        snippet = text[:800].strip()
        block = f"\n## {title}\n{snippet}\n"
        if total + len(block) > max_chars:
            break
        lines.append(block)
        total += len(block)
    if len(lines) == 1:
        return ""
    lines.append("[FIN BASE VIDAL]\n")
    return "\n".join(lines)


async def scheduled_import_new_products(db, vidal_call_fn) -> Dict[str, Any]:
    """Nightly cron — calls VIDAL /products/status?status=NEW then indexes
    the top 50 nouveautés. `vidal_call_fn` is the bound `_vidal_call` of
    routes/vidal.py (passed in to avoid circular imports).
    """
    if not await _vidal_qdrant_enabled(db):
        return {"skipped": True, "reason": "qdrant disabled"}
    from routes.vidal import _load_config, _ensure_active
    cfg = await _load_config(db)
    try:
        _ensure_active(cfg)
    except Exception:
        return {"skipped": True, "reason": "vidal disabled or no creds"}
    try:
        data = await vidal_call_fn(cfg, "GET", "/products/status", params={"status": "NEW"})
    except Exception as exc:  # noqa: BLE001
        return {"skipped": True, "reason": f"vidal call failed: {exc}"}
    entries = (
        (data or {}).get("entries")
        or (data or {}).get("items")
        or []
    )[:50]
    count = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        pid = e.get("id") or e.get("product_id")
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            continue
        await index_product(db, pid_int, {"product": e}, source="scheduled_new")
        count += 1
    return {"indexed": count, "scanned": len(entries)}
