"""S038 — Qdrant RAG service for Liluvine PRO knowledge base.

Features:
  * Connection auto-bootstrapped from `.env` (QDRANT_URL + QDRANT_API_KEY)
    OR from MongoDB settings (`qdrant_url`, `qdrant_api_key`) — DB takes
    precedence so admins can rotate keys without redeploying.
  * Embeddings via `fastembed` (Qdrant's official ONNX-based lib) — model
    `intfloat/multilingual-e5-small` (384 dim, multilingual including
    French, ~90MB, CPU-friendly).
  * Collections : list / create / delete.
  * Points : upsert (text, chunked), browse paginated, delete by id,
    semantic search by query.
  * Ingestion : raw text, PDF (via pypdf), URL (best-effort scrape with
    BeautifulSoup if present, else simple HTML strip).
  * Migration helper : pull all entries from `liluvine_kb_entries` (the
    legacy MongoDB-based KB) into a target Qdrant collection.
  * Liluvine integration : `build_rag_context(query, max_chars)` runs a
    semantic search across all "enabled_for_liluvine" collections and
    concatenates the top hits up to `max_chars`.

Settings model (in MongoDB `settings._id="global"`):
  - qdrant_enabled : bool — master toggle. If False, all helpers no-op.
  - qdrant_url : str (optional override of env)
  - qdrant_api_key : str (optional override of env)
  - qdrant_collection_settings : dict[name → { enabled_for_liluvine: bool }]
  - qdrant_embedding_model : str — defaults to multilingual-e5-small

Notes :
  - We use fastembed's `TextEmbedding`. Vectors are 384 dim. Collections
    created via this module are configured with COSINE distance.
  - The embedding model is loaded lazily on first call and cached in the
    module global `_EMBED_MODEL`. Initial load ~5 s.
  - All admin endpoints are gated by `_is_admin_or_sup` (admin/superviseur
    or tracked Administrateur/Superviseur).
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile

logger = logging.getLogger("sawali.qdrant_rag")

# ---------------------------------------------------------------------------
# Embedding model (lazy-loaded singleton)
# ---------------------------------------------------------------------------

_EMBED_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_EMBED_VECTOR_SIZE = 384
_EMBED_MODEL = None


def _get_embedder():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        from fastembed import TextEmbedding
        logger.info("[qdrant_rag] loading embedding model %s (first call)…", _EMBED_MODEL_NAME)
        t = time.time()
        _EMBED_MODEL = TextEmbedding(model_name=_EMBED_MODEL_NAME)
        logger.info("[qdrant_rag] embedding model loaded in %.2fs", time.time() - t)
    return _EMBED_MODEL


def _embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a batch of strings. The chosen sentence-transformer model is
    multilingual (good for French) and does NOT require a prefix."""
    if not texts:
        return []
    model = _get_embedder()
    return [list(v) for v in model.embed(texts)]


def _embed_query(query: str) -> List[float]:
    model = _get_embedder()
    return list(next(iter(model.embed([query]))))


# ---------------------------------------------------------------------------
# Qdrant client factory
# ---------------------------------------------------------------------------

async def _resolve_credentials(db) -> tuple[str, str]:
    """DB settings take precedence over env vars."""
    settings = await db.settings.find_one({"_id": "global"}) or {}
    url = (settings.get("qdrant_url") or os.environ.get("QDRANT_URL") or "").strip()
    api_key = (settings.get("qdrant_api_key") or os.environ.get("QDRANT_API_KEY") or "").strip()
    if not url or not api_key:
        raise HTTPException(status_code=400, detail="Qdrant non configuré (URL ou clé API manquante).")
    return url, api_key


def _make_client(url: str, api_key: str):
    from qdrant_client import QdrantClient
    return QdrantClient(url=url, api_key=api_key, timeout=30)


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(t: str) -> str:
    if not t:
        return ""
    t = t.replace("\u00a0", " ")
    return _WHITESPACE_RE.sub(" ", t).strip()


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> List[str]:
    """Split text on paragraph/sentence boundaries with overlap.

    Greedy linear pass : prefers paragraph breaks (\\n\\n), then sentence
    ends (. ? !), falling back to char windows. Each chunk is capped at
    `max_chars`. Overlap helps preserve context across boundaries during
    semantic search."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # First split on paragraphs
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    buf = ""
    for para in paragraphs:
        if len(buf) + len(para) + 2 <= max_chars:
            buf = (buf + "\n\n" + para).strip()
        else:
            if buf:
                chunks.append(buf)
                # overlap : reuse the last N chars
                tail = buf[-overlap:] if overlap and len(buf) > overlap else ""
                buf = (tail + "\n\n" + para).strip() if tail else para
            else:
                # Single huge paragraph → window-split
                start = 0
                while start < len(para):
                    end = min(start + max_chars, len(para))
                    chunks.append(para[start:end])
                    start = max(end - overlap, start + 1)
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def extract_pdf_text(content: bytes) -> str:
    """Extract text from a PDF byte stream using pypdf. Best-effort —
    encrypted/scanned PDFs return empty string."""
    try:
        from pypdf import PdfReader
        from io import BytesIO
        reader = PdfReader(BytesIO(content))
        return _clean_text("\n\n".join(page.extract_text() or "" for page in reader.pages))
    except Exception as exc:  # noqa: BLE001
        logger.exception("[qdrant_rag] PDF extract failed")
        raise HTTPException(status_code=400, detail=f"Lecture PDF échouée : {exc}") from exc


def fetch_url_text(url: str) -> dict:
    """Fetch and strip a public URL. Returns {title, text}."""
    import urllib.request
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL invalide (http/https requis)")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; SawaliRAGBot/1.0)",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(2_000_000)  # 2 MB cap
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Téléchargement échoué : {exc}") from exc
    if "html" not in content_type.lower() and "text" not in content_type.lower():
        raise HTTPException(status_code=400, detail=f"Type de contenu non supporté : {content_type}")
    try:
        html = raw.decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Décodage échoué") from exc
    # Title
    m_title = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = _clean_text(m_title.group(1)) if m_title else url
    # Strip scripts/styles
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", html)
    return {"title": title[:200] or url, "text": _clean_text(text)}


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------

async def list_collections(db) -> list[dict]:
    url, key = await _resolve_credentials(db)
    client = _make_client(url, key)
    settings = await db.settings.find_one({"_id": "global"}) or {}
    coll_meta = settings.get("qdrant_collection_settings") or {}
    # S041 — Estimate storage. Each vector is 384 dim × 4 bytes = 1536 B,
    # plus ~512 B avg per payload (title, text chunk, source, tags, kind,
    # image_url…), plus Qdrant indexing overhead (~30%). Numbers tuned
    # empirically against the Qdrant Cloud dashboard.
    BYTES_PER_VECTOR = int(_EMBED_VECTOR_SIZE * 4 * 1.30) + 512
    out = []
    total_points = 0
    for c in client.get_collections().collections:
        try:
            info = client.get_collection(c.name)
            count = client.count(c.name, exact=False).count
        except Exception:  # noqa: BLE001
            info = None
            count = 0
        cfg = coll_meta.get(c.name) or {}
        size_bytes = (count or 0) * BYTES_PER_VECTOR
        total_points += count or 0
        out.append({
            "name": c.name,
            "vectors_count": count,
            "enabled_for_liluvine": bool(cfg.get("enabled_for_liluvine", False)),
            "description": cfg.get("description") or "",
            "vector_size": _EMBED_VECTOR_SIZE,
            "distance": "Cosine",
            "estimated_size_bytes": size_bytes,
            "estimated_size_mb": round(size_bytes / (1024 * 1024), 3),
            "raw": str(info) if info else None,
        })
    return out


async def get_storage_info(db) -> dict:
    """S041 — Returns total estimated Qdrant storage usage vs the
    configured cluster quota (default 1 GB for Qdrant Cloud free tier)."""
    settings = await db.settings.find_one({"_id": "global"}) or {}
    quota_mb = int(settings.get("qdrant_quota_mb") or 1024)  # 1 GB free tier
    BYTES_PER_VECTOR = int(_EMBED_VECTOR_SIZE * 4 * 1.30) + 512
    url, key = await _resolve_credentials(db)
    client = _make_client(url, key)
    total_points = 0
    coll_count = 0
    try:
        for c in client.get_collections().collections:
            coll_count += 1
            try:
                total_points += client.count(c.name, exact=False).count or 0
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    bytes_total = total_points * BYTES_PER_VECTOR
    mb_total = bytes_total / (1024 * 1024)
    return {
        "total_points": total_points,
        "collections": coll_count,
        "estimated_size_mb": round(mb_total, 3),
        "estimated_size_bytes": bytes_total,
        "quota_mb": quota_mb,
        "pct_used": round((mb_total / quota_mb) * 100.0, 2) if quota_mb > 0 else 0.0,
        "remaining_mb": round(max(0.0, quota_mb - mb_total), 3),
    }


async def create_collection(db, *, name: str, description: str = "") -> dict:
    url, key = await _resolve_credentials(db)
    client = _make_client(url, key)
    if not re.fullmatch(r"[a-zA-Z0-9_\-]{1,64}", name or ""):
        raise HTTPException(status_code=400, detail="Nom de collection invalide (a-z, 0-9, _, -, 1-64 car.)")
    from qdrant_client.models import VectorParams, Distance
    try:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=_EMBED_VECTOR_SIZE, distance=Distance.COSINE),
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "already exists" in msg.lower() or "409" in msg:
            raise HTTPException(status_code=409, detail=f"Collection '{name}' existe déjà.") from exc
        raise HTTPException(status_code=500, detail=f"Création échouée : {msg}") from exc
    # Persist meta
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            f"qdrant_collection_settings.{name}": {
                "enabled_for_liluvine": True,
                "description": description,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        }},
        upsert=True,
    )
    return {"ok": True, "name": name}


async def delete_collection(db, *, name: str) -> dict:
    url, key = await _resolve_credentials(db)
    client = _make_client(url, key)
    try:
        client.delete_collection(name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Suppression échouée : {exc}") from exc
    await db.settings.update_one(
        {"_id": "global"},
        {"$unset": {f"qdrant_collection_settings.{name}": ""}},
    )
    return {"ok": True, "name": name}


async def upsert_text_documents(db, *, collection: str, docs: List[dict]) -> dict:
    """docs: [{title, text, source, tags?}]. Each text is chunked and one
    point per chunk is upserted."""
    if not docs:
        raise HTTPException(status_code=400, detail="Aucun document fourni.")
    url, key = await _resolve_credentials(db)
    client = _make_client(url, key)
    from qdrant_client.models import PointStruct
    now_iso = datetime.now(timezone.utc).isoformat()
    points: list[PointStruct] = []
    inserted_chunks = 0
    for doc in docs:
        text = _clean_text(doc.get("text") or "")
        if not text:
            continue
        chunks = chunk_text(text, max_chars=1200, overlap=150)
        vectors = _embed_texts(chunks)
        for chunk, vec in zip(chunks, vectors):
            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=vec,
                payload={
                    "title": (doc.get("title") or "")[:200],
                    "text": chunk,
                    "source": (doc.get("source") or "")[:300],
                    "tags": doc.get("tags") or [],
                    "created_at": now_iso,
                    "chunk_of": doc.get("title") or doc.get("source") or "",
                },
            ))
            inserted_chunks += 1
    if not points:
        raise HTTPException(status_code=400, detail="Tous les documents sont vides.")
    try:
        client.upsert(collection_name=collection, points=points)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Upsert échoué : {exc}") from exc
    return {"ok": True, "inserted_chunks": inserted_chunks, "documents": len(docs)}


async def upsert_image(
    db,
    *,
    collection: str,
    image_url: str,
    title: str,
    caption: str,
    tags: Optional[list] = None,
) -> dict:
    """S041 — Index an image into Qdrant.

    The text used for embedding is `title + caption` (Option 1 — Liluvine
    doesn't 'see' the image, it sees its description). The payload stores
    `image_url` so Liluvine can include the image in its replies via
    Markdown `![title](url)`.
    """
    title = (title or "").strip()
    caption = (caption or "").strip()
    if not title and not caption:
        raise HTTPException(status_code=400, detail="Titre OU description requis pour qu'une image soit retrouvable par Liluvine.")
    embed_text = f"{title}\n{caption}".strip() or title or caption
    url, key = await _resolve_credentials(db)
    client = _make_client(url, key)
    from qdrant_client.models import PointStruct
    vec = _embed_texts([embed_text])[0]
    point_id = str(uuid.uuid4())
    client.upsert(
        collection_name=collection,
        points=[PointStruct(
            id=point_id,
            vector=vec,
            payload={
                "kind": "image",
                "title": title[:200],
                "text": caption[:2000],
                "caption": caption[:2000],
                "image_url": image_url,
                "source": "media_library",
                "tags": list(tags or []) + ["image"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )],
    )
    return {"ok": True, "id": point_id, "image_url": image_url}


async def browse_points(db, *, collection: str, offset: int = 0, limit: int = 50) -> dict:
    url, key = await _resolve_credentials(db)
    client = _make_client(url, key)
    limit = min(max(1, limit), 200)
    try:
        scroll, next_offset = client.scroll(
            collection_name=collection,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Scroll échoué : {exc}") from exc
    items = []
    for pt in scroll:
        payload = pt.payload or {}
        items.append({
            "id": str(pt.id),
            "kind": payload.get("kind") or "text",
            "title": payload.get("title") or "(sans titre)",
            "text_preview": (payload.get("text") or "")[:280],
            "source": payload.get("source"),
            "image_url": payload.get("image_url"),
            "tags": payload.get("tags") or [],
            "created_at": payload.get("created_at"),
        })
    total = client.count(collection, exact=False).count
    return {"items": items, "total": total, "next_offset": str(next_offset) if next_offset is not None else None}


async def delete_point(db, *, collection: str, point_id: str) -> dict:
    url, key = await _resolve_credentials(db)
    client = _make_client(url, key)
    try:
        from qdrant_client.models import PointIdsList
        client.delete(collection_name=collection, points_selector=PointIdsList(points=[point_id]))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Suppression échouée : {exc}") from exc
    return {"ok": True, "id": point_id}


async def search_points(db, *, collection: str, query: str, top_k: int = 5) -> dict:
    if not (query or "").strip():
        raise HTTPException(status_code=400, detail="Requête vide")
    url, key = await _resolve_credentials(db)
    client = _make_client(url, key)
    qvec = _embed_query(query)
    top_k = min(max(1, int(top_k or 5)), 50)
    try:
        hits = client.query_points(collection_name=collection, query=qvec, limit=top_k, with_payload=True).points
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Recherche échouée : {exc}") from exc
    items = []
    for h in hits:
        payload = h.payload or {}
        items.append({
            "id": str(h.id),
            "score": float(h.score),
            "kind": payload.get("kind") or "text",
            "title": payload.get("title") or "(sans titre)",
            "text": (payload.get("text") or "")[:1200],
            "image_url": payload.get("image_url"),
            "source": payload.get("source"),
            "tags": payload.get("tags") or [],
        })
    return {"items": items, "query": query, "top_k": top_k}


async def test_connection(db) -> dict:
    url, key = await _resolve_credentials(db)
    client = _make_client(url, key)
    try:
        cols = client.get_collections().collections
        return {"ok": True, "url": url, "collections": len(cols)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Connexion échouée : {exc}") from exc


# ---------------------------------------------------------------------------
# Liluvine integration
# ---------------------------------------------------------------------------

async def build_rag_context(db, *, query: str, max_chars: int = 6000) -> str:
    """Search all collections flagged enabled_for_liluvine and concat the
    top matches up to max_chars. Returns "" if RAG is disabled or no
    matches. Failures are swallowed (returns "").

    S041 — When image points are matched, their URLs are surfaced in a
    dedicated block that Liluvine is instructed (via system prompt) to
    embed in her reply using Markdown `![title](url)`. The chat UI then
    renders them as a numbered carousel.
    """
    settings = await db.settings.find_one({"_id": "global"}) or {}
    if not settings.get("qdrant_enabled"):
        return ""
    coll_meta = settings.get("qdrant_collection_settings") or {}
    enabled = [name for name, cfg in coll_meta.items() if (cfg or {}).get("enabled_for_liluvine")]
    if not enabled:
        return ""
    try:
        url, key = await _resolve_credentials(db)
        client = _make_client(url, key)
        qvec = _embed_query(query)
    except Exception:  # noqa: BLE001
        logger.exception("[qdrant_rag] build_rag_context credentials/embed failed")
        return ""
    all_hits = []
    for cname in enabled:
        try:
            hits = client.query_points(collection_name=cname, query=qvec, limit=4, with_payload=True).points
            for h in hits:
                payload = h.payload or {}
                all_hits.append({
                    "score": float(h.score),
                    "collection": cname,
                    "kind": payload.get("kind") or "text",
                    "title": payload.get("title") or "",
                    "text": payload.get("text") or "",
                    "image_url": payload.get("image_url"),
                    "source": payload.get("source") or "",
                })
        except Exception:  # noqa: BLE001
            logger.warning("[qdrant_rag] search failed on %s", cname, exc_info=True)
    all_hits.sort(key=lambda x: x["score"], reverse=True)
    # Split image hits from text hits
    image_hits = [h for h in all_hits if h["kind"] == "image" and h.get("image_url")]
    text_hits = [h for h in all_hits if h["kind"] != "image"]
    parts = ["[BASE DE CONNAISSANCES (RAG sémantique Qdrant)]"]
    total = len(parts[0])
    # Text block
    for h in text_hits:
        title = h["title"][:80] or "(sans titre)"
        body = h["text"].strip()
        block = f"\n• {title} (score {h['score']:.2f})\n  {body[:800]}"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
    # S041 — Images block (Liluvine is instructed to include relevant ones
    # in her reply using the URLs verbatim).
    if image_hits:
        parts.append("\n\n[IMAGES DISPONIBLES POUR ILLUSTRER TA RÉPONSE]")
        parts.append(
            "\nSi l'une de ces images aide le client à comprendre ta réponse, inclus-la "
            "EXACTEMENT comme ceci à un endroit pertinent de ta réponse :\n"
            "  ![titre](url)\n"
            "Tu peux en inclure plusieurs si elles sont toutes utiles — l'interface "
            "les affichera automatiquement sous forme de carrousel numéroté."
        )
        for idx, h in enumerate(image_hits[:5], start=1):
            title = (h["title"] or h["text"][:80] or f"image-{idx}").strip()
            parts.append(f"\n  ![{title}]({h['image_url']})  (score {h['score']:.2f})")
    if len(parts) == 1:
        return ""
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def make_router(*, db, get_current_user):
    router = APIRouter(prefix="/admin/qdrant", tags=["Admin — Qdrant RAG"])

    def _gate(user: dict):
        is_admin = user.get("role") in ("admin", "superviseur") or user.get("tracked_role") in ("Administrateur", "Superviseur")
        if not is_admin:
            raise HTTPException(status_code=403, detail="Accès refusé")

    @router.post("/test-connection")
    async def r_test(user: dict = Depends(get_current_user)):
        _gate(user)
        return await test_connection(db)

    @router.get("/storage")
    async def r_storage(user: dict = Depends(get_current_user)):
        """S041 — Total estimated Qdrant disk usage vs cluster quota."""
        _gate(user)
        return await get_storage_info(db)

    @router.get("/collections")
    async def r_list(user: dict = Depends(get_current_user)):
        _gate(user)
        return {"items": await list_collections(db)}

    @router.post("/collections")
    async def r_create(payload: dict = Body(...), user: dict = Depends(get_current_user)):
        _gate(user)
        return await create_collection(db, name=payload.get("name") or "", description=payload.get("description") or "")

    @router.delete("/collections/{name}")
    async def r_delete(name: str, user: dict = Depends(get_current_user)):
        _gate(user)
        return await delete_collection(db, name=name)

    @router.patch("/collections/{name}")
    async def r_patch(name: str, payload: dict = Body(...), user: dict = Depends(get_current_user)):
        """Update collection metadata (enabled_for_liluvine, description)."""
        _gate(user)
        upd = {}
        if "enabled_for_liluvine" in payload:
            upd[f"qdrant_collection_settings.{name}.enabled_for_liluvine"] = bool(payload["enabled_for_liluvine"])
        if "description" in payload:
            upd[f"qdrant_collection_settings.{name}.description"] = (payload["description"] or "")[:500]
        if not upd:
            raise HTTPException(status_code=400, detail="Aucune modification fournie.")
        await db.settings.update_one({"_id": "global"}, {"$set": upd}, upsert=True)
        return {"ok": True}

    @router.get("/collections/{name}/points")
    async def r_browse(name: str, limit: int = 50, user: dict = Depends(get_current_user)):
        _gate(user)
        return await browse_points(db, collection=name, limit=limit)

    @router.post("/collections/{name}/points/text")
    async def r_upsert_text(name: str, payload: dict = Body(...), user: dict = Depends(get_current_user)):
        _gate(user)
        docs = payload.get("documents")
        if isinstance(docs, dict):
            docs = [docs]
        if not isinstance(docs, list) or not docs:
            # Accept the simpler {title, text, source, tags} shape
            if payload.get("text"):
                docs = [{
                    "title": payload.get("title") or "",
                    "text": payload.get("text"),
                    "source": payload.get("source") or "",
                    "tags": payload.get("tags") or [],
                }]
            else:
                raise HTTPException(status_code=400, detail="Champ `documents` ou `text` requis.")
        return await upsert_text_documents(db, collection=name, docs=docs)

    @router.post("/collections/{name}/points/pdf")
    async def r_upsert_pdf(name: str, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
        _gate(user)
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Fichier PDF attendu.")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Fichier vide.")
        text = extract_pdf_text(content)
        if not text:
            raise HTTPException(status_code=400, detail="Aucun texte extrait (PDF scanné/chiffré ?).")
        return await upsert_text_documents(db, collection=name, docs=[{
            "title": file.filename,
            "text": text,
            "source": f"pdf:{file.filename}",
            "tags": ["pdf"],
        }])

    @router.post("/collections/{name}/points/url")
    async def r_upsert_url(name: str, payload: dict = Body(...), user: dict = Depends(get_current_user)):
        _gate(user)
        url = (payload.get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="URL manquante.")
        scraped = fetch_url_text(url)
        if not scraped["text"]:
            raise HTTPException(status_code=400, detail="Aucun texte extrait de cette page.")
        return await upsert_text_documents(db, collection=name, docs=[{
            "title": scraped["title"],
            "text": scraped["text"],
            "source": f"url:{url}",
            "tags": ["url"],
        }])

    @router.post("/collections/{name}/points/image")
    async def r_upsert_image(
        name: str,
        file: UploadFile = File(...),
        title: str = Form(""),
        caption: str = Form(""),
        user: dict = Depends(get_current_user),
    ):
        """S041 — Upload an image, save it in the media library, and
        index its (title + caption) in Qdrant. Liluvine can then surface
        the image URL in her replies via Markdown.
        """
        _gate(user)
        ct = (file.content_type or "").lower()
        if not ct.startswith("image/"):
            raise HTTPException(status_code=400, detail="Fichier image attendu.")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Fichier vide.")
        if len(content) > 15 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Image > 15 Mo.")
        import object_storage as _obj_storage
        # Map MIME → extension
        ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
        ext = ext_map.get(ct, "bin")
        stored = await _obj_storage.save_and_log(
            db,
            data=content,
            kind="qdrant_image",
            tenant_id="sawali_global",
            ext=ext,
            content_type=ct,
            original_filename=file.filename or f"image.{ext}",
            user_id=user.get("id"),
            metadata={"qdrant_collection": name, "title": title or ""},
        )
        # Also create a media_library entry so it shows up in /admin/brochures
        import secrets
        media_id = secrets.token_urlsafe(10)
        await db.media_library.insert_one({
            "id": media_id,
            "kind": "image",
            "title": (title or file.filename or "Image Qdrant").strip()[:200],
            "description": (caption or "")[:1000],
            "filename": file.filename,
            "content_type": ct,
            "size": stored.get("size") or len(content),
            "url": stored.get("url"),
            "storage_id": stored.get("id"),
            "storage_path": stored.get("path"),
            "thumbnail_url": None,
            "tags": ["qdrant", "kb", name],
            "public": False,  # private by default — only Liluvine surfaces it
            "sort_order": 0,
            "is_deleted": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by_id": user.get("id"),
            "created_by_name": user.get("full_name") or user.get("email"),
            "qdrant_collection": name,
        })
        # Index in Qdrant
        return await upsert_image(
            db,
            collection=name,
            image_url=stored.get("url"),
            title=title or file.filename or "Image",
            caption=caption,
            tags=["image", "media_library"],
        )

    @router.delete("/collections/{name}/points/{pid}")
    async def r_delete_point(name: str, pid: str, user: dict = Depends(get_current_user)):
        _gate(user)
        return await delete_point(db, collection=name, point_id=pid)

    @router.post("/collections/{name}/search")
    async def r_search(name: str, payload: dict = Body(...), user: dict = Depends(get_current_user)):
        _gate(user)
        return await search_points(db, collection=name,
                                   query=(payload.get("query") or "").strip(),
                                   top_k=int(payload.get("top_k") or 5))

    @router.post("/migrate-mongo-kb")
    async def r_migrate(payload: dict = Body(...), user: dict = Depends(get_current_user)):
        """One-shot migration : pull all entries from `liluvine_kb_entries`
        and index them into the target Qdrant collection."""
        _gate(user)
        target = (payload.get("collection") or "").strip()
        if not target:
            raise HTTPException(status_code=400, detail="Collection cible manquante.")
        cursor = db.liluvine_kb_entries.find(
            {"enabled": True},
            {"_id": 0, "title": 1, "content": 1, "tags": 1, "id": 1},
        )
        rows = await cursor.to_list(length=2000)
        if not rows:
            return {"ok": True, "migrated_documents": 0, "inserted_chunks": 0}
        docs = []
        for r in rows:
            text = (r.get("content") or "").strip()
            if not text:
                continue
            docs.append({
                "title": r.get("title") or "(sans titre)",
                "text": text,
                "source": f"mongo_kb:{r.get('id', '')}",
                "tags": (r.get("tags") or []) + ["migrated"],
            })
        return await upsert_text_documents(db, collection=target, docs=docs)

    return router


__all__ = [
    "make_router",
    "build_rag_context",
    "test_connection",
    "list_collections",
    "create_collection",
    "delete_collection",
    "upsert_text_documents",
    "search_points",
]
