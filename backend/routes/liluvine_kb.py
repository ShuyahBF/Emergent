"""Iter38r-fix9c — Liluvine PRO Knowledge Base.

Provides a CRUD admin module to feed Liluvine PRO with custom SAWALI content
(FAQ entries, software documentation snippets, internal procedures…). Every
entry is stored in `liluvine_knowledge`. PDF/TXT files can also be uploaded —
they are parsed locally into ~1500-char chunks.

The aggregated content is injected into the Liluvine system message at every
conversation start (capped at ~6 KB to keep Claude's context manageable).

Endpoints (admin / superviseur only):
  GET    /api/admin/liluvine-pro/kb              — list entries
  POST   /api/admin/liluvine-pro/kb              — create text entry
  PUT    /api/admin/liluvine-pro/kb/{id}         — update text entry
  DELETE /api/admin/liluvine-pro/kb/{id}         — delete entry
  POST   /api/admin/liluvine-pro/kb/upload       — upload PDF/TXT (multipart)

Public helper:
  build_kb_context(db, max_chars=6000) -> str    — injected by liluvine_pro.py
"""
from __future__ import annotations

import io
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.liluvine_kb")

# Hard caps to protect the LLM context window and storage
MAX_ENTRY_CHARS = 8000
MAX_CHUNK_CHARS = 1500
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_CONTEXT_BUDGET = 6000

# Iter38r-fix9t — In-memory cache for build_kb_context (per-process)
# Key = max_chars, Value = (timestamp, rendered_context)
_KB_CONTEXT_CACHE: Dict[int, tuple] = {}
_KB_CONTEXT_TTL = 60.0  # seconds


class KbEntryCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=MAX_ENTRY_CHARS)
    tags: Optional[List[str]] = None


class KbEntryUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, min_length=1, max_length=MAX_ENTRY_CHARS)
    tags: Optional[List[str]] = None
    enabled: Optional[bool] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chunk_text(content: str, *, max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    """Split on paragraph boundaries, then hard-wrap if a paragraph is too long."""
    if len(content) <= max_chars:
        return [content.strip()]
    chunks: List[str] = []
    buf = ""
    for para in content.replace("\r\n", "\n").split("\n\n"):
        if not para.strip():
            continue
        if len(buf) + len(para) + 2 <= max_chars:
            buf += ("\n\n" if buf else "") + para
        else:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            # Hard-wrap if the paragraph itself is too long
            while len(para) > max_chars:
                chunks.append(para[:max_chars])
                para = para[max_chars:]
            buf = para
    if buf:
        chunks.append(buf.strip())
    return chunks


def _parse_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF parser unavailable: {exc}")
    try:
        reader = PdfReader(io.BytesIO(raw))
        out: List[str] = []
        for page in reader.pages:
            try:
                out.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                pass
        return "\n\n".join(s.strip() for s in out if s and s.strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF illisible : {exc}")


async def _ocr_image_with_claude_vision(raw: bytes, mime: str) -> str:
    """Iter38r-fix9h — Send the image to Claude Sonnet 4.6 Vision and ask it
    to OCR all text from it. Returns the extracted text (no description),
    formatted as plain text for storage in the KB."""
    import base64
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY non configurée")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"emergentintegrations indisponible : {exc}")
    b64 = base64.b64encode(raw).decode("ascii")
    img = ImageContent(image_base64=b64)
    chat = LlmChat(
        api_key=api_key,
        session_id=f"liluvine-kb-ocr-{secrets.token_urlsafe(6)}",
        system_message=(
            "Tu es un moteur OCR précis. L'utilisateur va te montrer une image "
            "qui contient du texte. Extrait EXCLUSIVEMENT le texte visible dans "
            "l'image, sans description, sans commentaire, sans annotation. "
            "Préserve la mise en page (paragraphes, listes, tableaux). "
            "Si aucun texte n'est lisible, réponds exactement : "
            "[AUCUN_TEXTE_DETECTE]."
        ),
    ).with_model("anthropic", "claude-haiku-4-5-20251001")
    try:
        result = await chat.send_message(UserMessage(
            text="Extrais tout le texte visible dans cette image, en respectant la mise en page.",
            file_contents=[img],
        ))
    except Exception as exc:
        logger.exception("[kb_ocr] vision call failed")
        raise HTTPException(status_code=502, detail=f"OCR Claude Vision échec : {str(exc)[:200]}")
    text = (result or "").strip()
    if not text or "[AUCUN_TEXTE_DETECTE]" in text.upper():
        raise HTTPException(status_code=422, detail="Aucun texte détecté dans l'image")
    return text


def _rasterize_pdf_to_images(raw: bytes, max_pages: int = 30, dpi: int = 150) -> List[bytes]:
    """Iter38r-fix9k — Rasterize a PDF into PNG pages for Claude Vision OCR.
    Capped at `max_pages` to control cost and runtime."""
    try:
        import fitz  # PyMuPDF
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PyMuPDF indisponible : {exc}")
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF illisible pour OCR : {exc}")
    pages: List[bytes] = []
    page_count = min(doc.page_count, max_pages)
    for i in range(page_count):
        page = doc.load_page(i)
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pages.append(pix.tobytes("png"))
    doc.close()
    return pages


async def _ocr_pdf_with_claude_vision(raw: bytes, settings_doc: Dict[str, Any]) -> tuple[str, int]:
    """Rasterize the PDF then OCR every page via Claude Vision. Returns
    (concatenated_text, pages_used). Page limit comes from settings."""
    try:
        max_pages = int(settings_doc.get("kb_ocr_pdf_max_pages") or 30)
    except Exception:
        max_pages = 30
    pages = _rasterize_pdf_to_images(raw, max_pages=max_pages)
    if not pages:
        raise HTTPException(status_code=400, detail="PDF vide ou sans page lisible")
    chunks: List[str] = []
    used = 0
    for idx, png in enumerate(pages):
        try:
            text = await _ocr_image_with_claude_vision(png, "image/png")
        except HTTPException as exc:
            if exc.status_code == 422:
                # No text on this page → skip but continue
                continue
            raise
        used += 1
        chunks.append(f"--- Page {idx + 1} ---\n{text.strip()}")
    if not chunks:
        raise HTTPException(status_code=422, detail="Aucun texte détecté dans le PDF (OCR)")
    return "\n\n".join(chunks), used


async def build_kb_context(db, *, max_chars: int = DEFAULT_CONTEXT_BUDGET, query: Optional[str] = None) -> str:
    """Aggregate enabled KB entries into a compact context string.

    S038 — When `query` is provided AND `settings.qdrant_enabled` is True,
    we run a semantic search (RAG) across all Qdrant collections flagged
    `enabled_for_liluvine` and concatenate the results. The RAG block
    consumes up to ~60% of `max_chars`; the remaining budget falls back
    to the legacy MongoDB KB. If RAG returns nothing (or fails), we use
    100% of the budget for the MongoDB KB (no behavior change).
    """
    # ---- S038 — RAG semantic block (uses query when available) ----
    rag_block = ""
    rag_budget = 0
    if query and (query or "").strip():
        try:
            from routes.qdrant_rag import build_rag_context
            rag_budget = int(max_chars * 0.6)
            rag_block = await build_rag_context(db, query=query, max_chars=rag_budget)
        except Exception:  # noqa: BLE001
            rag_block = ""
    remaining = max_chars - len(rag_block)
    # Cache lookup (legacy MongoDB KB only — keyed by remaining budget)
    now = time.time()
    cached = _KB_CONTEXT_CACHE.get(remaining)
    if cached and (now - cached[0] < _KB_CONTEXT_TTL):
        mongo_block = cached[1]
    else:
        cur = db.liluvine_knowledge.find(
            {"enabled": True, "is_deleted": {"$ne": True}},
            {"_id": 0, "title": 1, "content": 1, "kind": 1, "tags": 1},
        ).sort([("priority", -1), ("updated_at", -1)])
        items = await cur.to_list(50)
        if not items:
            mongo_block = ""
        else:
            parts: List[str] = ["[Base de connaissance SAWALI — Liluvine PRO]"]
            used = len(parts[0])
            for it in items:
                title = (it.get("title") or "").strip()
                content = (it.get("content") or "").strip()
                if not content:
                    continue
                block = f"\n\n## {title}\n{content}"
                if used + len(block) > remaining:
                    rest = remaining - used - len(title) - 12
                    if rest > 80:
                        parts.append(f"\n\n## {title}\n{content[:rest]}…")
                    break
                parts.append(block)
                used += len(block)
            mongo_block = "".join(parts)
        _KB_CONTEXT_CACHE[remaining] = (now, mongo_block)
    # Concatenate (RAG first for higher LLM attention)
    if rag_block and mongo_block:
        return rag_block + "\n\n" + mongo_block
    return rag_block or mongo_block


def invalidate_kb_cache() -> None:
    """Iter38r-fix9t — Called after any KB mutation (upload/update/delete/toggle)."""
    _KB_CONTEXT_CACHE.clear()


def setup_liluvine_kb_routes(app, db, get_current_user):
    """Mount the KB admin endpoints onto the existing FastAPI router."""
    api: APIRouter = app

    def _ensure_admin(user: Dict[str, Any]):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")

    @api.get("/admin/liluvine-pro/kb", tags=["Admin — Liluvine PRO"])
    async def kb_list(user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        cur = db.liluvine_knowledge.find(
            {"is_deleted": {"$ne": True}},
            {"_id": 0},
        ).sort([("updated_at", -1)])
        items = await cur.to_list(200)
        # Aggregate totals
        total_chars = sum(len((it.get("content") or "")) for it in items)
        enabled_count = sum(1 for it in items if it.get("enabled"))
        return {
            "items": items,
            "stats": {
                "total": len(items),
                "enabled": enabled_count,
                "total_chars": total_chars,
                "context_budget_chars": DEFAULT_CONTEXT_BUDGET,
            },
        }

    @api.post("/admin/liluvine-pro/kb", tags=["Admin — Liluvine PRO"])
    async def kb_create(payload: KbEntryCreate = Body(...), user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        eid = secrets.token_urlsafe(10)
        doc = {
            "id": eid,
            "title": payload.title.strip(),
            "content": payload.content.strip(),
            "tags": [t.strip().lower() for t in (payload.tags or []) if t.strip()],
            "kind": "text",
            "enabled": True,
            "priority": 0,
            "char_count": len(payload.content),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "created_by": user.get("email"),
        }
        await db.liluvine_knowledge.insert_one(doc.copy())
        invalidate_kb_cache()
        return {"ok": True, "id": eid, "entry": doc}

    @api.put("/admin/liluvine-pro/kb/{eid}", tags=["Admin — Liluvine PRO"])
    async def kb_update(eid: str, payload: KbEntryUpdate = Body(...), user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        update: Dict[str, Any] = {}
        if payload.title is not None:
            update["title"] = payload.title.strip()
        if payload.content is not None:
            update["content"] = payload.content.strip()
            update["char_count"] = len(update["content"])
        if payload.tags is not None:
            update["tags"] = [t.strip().lower() for t in payload.tags if t.strip()]
        if payload.enabled is not None:
            update["enabled"] = bool(payload.enabled)
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        update["updated_at"] = _now_iso()
        update["updated_by"] = user.get("email")
        res = await db.liluvine_knowledge.update_one({"id": eid, "is_deleted": {"$ne": True}}, {"$set": update})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Entrée introuvable")
        invalidate_kb_cache()
        return {"ok": True, "id": eid}

    @api.delete("/admin/liluvine-pro/kb/{eid}", tags=["Admin — Liluvine PRO"])
    async def kb_delete(eid: str, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        res = await db.liluvine_knowledge.update_one(
            {"id": eid, "is_deleted": {"$ne": True}},
            {"$set": {"is_deleted": True, "deleted_at": _now_iso(), "deleted_by": user.get("email")}},
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Entrée introuvable")
        invalidate_kb_cache()
        return {"ok": True, "id": eid}

    @api.get("/admin/liluvine-pro/kb/ocr-usage", tags=["Admin — Liluvine PRO"])
    async def kb_ocr_usage(
        month: Optional[str] = None,
        client_id: Optional[str] = None,
        user: dict = Depends(get_current_user),
    ):
        """Iter38r-fix9k — Monthly OCR usage report (pages + XOF cost).
        `month` = "YYYY-MM" (defaults to current month).
        Iter38r-fix9q — `client_id` (optional) scopes the result to a single
        tenant; per-tenant pricing/cap from the client's features doc override
        the global settings when present.
        """
        _ensure_admin(user)
        ym = (month or datetime.now(timezone.utc).strftime("%Y-%m"))
        query = {"resource": "kb_ocr", "ym": ym}
        if client_id:
            query["tenant_id"] = client_id
        cursor = db.ai_usage.find(query, {"_id": 0})
        items = await cursor.to_list(2000)
        g = await db.settings.find_one({"_id": "global"}) or {}
        cap_xof = int(g.get("kb_ocr_xof_monthly_cap") or 0)
        per_page = int(g.get("kb_ocr_xof_per_page") or 0)
        # Per-tenant override
        if client_id:
            tenant_doc = await db.users.find_one({"id": client_id}, {"_id": 0, "features": 1}) or {}
            tfeats = (tenant_doc.get("features") or {})
            try:
                if tfeats.get("kb_ocr_xof_monthly_cap") not in (None, 0):
                    cap_xof = int(tfeats["kb_ocr_xof_monthly_cap"])
                if tfeats.get("kb_ocr_xof_per_page") not in (None, 0):
                    per_page = int(tfeats["kb_ocr_xof_per_page"])
            except (TypeError, ValueError):
                pass
        total_pages = sum(int(it.get("units") or 0) for it in items)
        total_xof = sum(int(it.get("cost_xof") or 0) for it in items)
        return {
            "month": ym,
            "client_id": client_id,
            "pages": total_pages,
            "cost_xof": total_xof,
            "monthly_cap_xof": cap_xof,
            "xof_per_page": per_page,
            "remaining_xof": max(0, cap_xof - total_xof) if cap_xof > 0 else None,
            "count_uploads": len(items),
        }

    @api.post("/admin/liluvine-pro/kb/upload", tags=["Admin — Liluvine PRO"])
    async def kb_upload(
        file: UploadFile = File(...),
        title: str = Form(...),
        force_ocr: Optional[str] = Form(default=None),
        user: dict = Depends(get_current_user),
    ):
        """Iter38r-fix9i — `force_ocr` (form, optional) :
        - 'true'  → mode OCR (image obligatoire, Claude Vision)
        - 'false' / absent → mode classique (PDF/TXT uniquement, pas d'OCR sur image)
        """
        _ensure_admin(user)
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Fichier vide")
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {MAX_UPLOAD_BYTES // 1024 // 1024} Mo)")
        ocr_mode = str(force_ocr or "").strip().lower() in ("1", "true", "yes", "on")
        name = (file.filename or "kb").lower()
        is_pdf = name.endswith(".pdf") or (file.content_type or "").endswith("pdf")
        is_txt = name.endswith(".txt") or (file.content_type or "").startswith("text/")
        is_img = name.endswith((".png", ".jpg", ".jpeg", ".webp")) or (file.content_type or "").startswith("image/")

        if ocr_mode:
            # Iter38r-fix9o (Item 2) — per-client OCR control. Resolve flags from
            # the calling user's parent (tenant). Admins still respect overrides
            # placed in global settings as a fallback. Per-tenant precedence:
            #   client_features.kb_ocr_enabled (bool) — must be True
            #   client_features.kb_ocr_xof_per_page (int)
            #   client_features.kb_ocr_xof_monthly_cap (int)
            tid = user.get("client_id") or user.get("parent_client_id") or user["id"]
            tenant_doc = await db.users.find_one({"id": tid}, {"_id": 0, "features": 1, "company": 1}) or {}
            tenant_feats = (tenant_doc.get("features") or {})
            g = await db.settings.find_one({"_id": "global"}) or {}
            # Effective flags (per-tenant overrides global)
            ocr_enabled_for_client = bool(tenant_feats.get("kb_ocr_enabled", True))
            if not ocr_enabled_for_client:
                raise HTTPException(status_code=403, detail="OCR Claude Vision désactivé pour ce client (cf. fiche tenant)")
            try:
                cap_xof = int(tenant_feats.get("kb_ocr_xof_monthly_cap") if tenant_feats.get("kb_ocr_xof_monthly_cap") is not None else (g.get("kb_ocr_xof_monthly_cap") or 0))
            except Exception:
                cap_xof = 0
            if cap_xof > 0:
                ym = datetime.now(timezone.utc).strftime("%Y-%m")
                # Filter on tenant_id for accurate per-client accounting
                spent_cursor = db.ai_usage.find(
                    {"resource": "kb_ocr", "ym": ym, "tenant_id": tid},
                    {"_id": 0, "cost_xof": 1},
                )
                spent_xof = 0
                async for u in spent_cursor:
                    spent_xof += int(u.get("cost_xof") or 0)
                if spent_xof >= cap_xof:
                    raise HTTPException(
                        status_code=429,
                        detail=f"Plafond OCR mensuel atteint pour {tenant_doc.get('company') or 'ce client'} ({cap_xof} XOF). Augmentez-le sur la fiche tenant.",
                    )
            # OCR strict: image OU PDF (rasterisation page-par-page)
            if is_img:
                mime = file.content_type or ("image/png" if name.endswith(".png") else "image/jpeg")
                text = await _ocr_image_with_claude_vision(raw, mime)
                kind = "image_ocr"
                pages_used = 1
            elif is_pdf:
                # Iter38r-fix9k — PDF OCR : rasterize each page with PyMuPDF then Claude Vision
                text, pages_used = await _ocr_pdf_with_claude_vision(raw, g)
                kind = "pdf_ocr"
            else:
                raise HTTPException(
                    status_code=415,
                    detail="Mode OCR : seuls les images (PNG/JPG/WEBP) et PDF sont supportés.",
                )
            # Track AI cost (XOF per page) into ai_usage for billing/quota visibility.
            # Iter38r-fix9o (Item 2) — Per-client cost from tenant features, fallback global.
            try:
                cost_xof_per_page = int(tenant_feats.get("kb_ocr_xof_per_page") if tenant_feats.get("kb_ocr_xof_per_page") is not None else (g.get("kb_ocr_xof_per_page") or 0))
            except Exception:
                cost_xof_per_page = 0
            total_cost_xof = max(0, cost_xof_per_page * pages_used)
            if total_cost_xof > 0:
                try:
                    await db.ai_usage.insert_one({
                        "id": secrets.token_urlsafe(10),
                        "resource": "kb_ocr",
                        "model": "claude-haiku-4-5-20251001-vision",
                        "units": pages_used,  # pages
                        "cost_xof": total_cost_xof,
                        "kind": kind,
                        "filename": file.filename,
                        "user_email": user.get("email"),
                        "tenant_id": tid,
                        "created_at": _now_iso(),
                        "ym": datetime.now(timezone.utc).strftime("%Y-%m"),
                    })
                except Exception:
                    logger.warning("[kb_ocr] ai_usage insert failed", exc_info=True)
        else:
            # Import classique : PDF / TXT (pas d'OCR sur image)
            if is_pdf:
                text = _parse_pdf(raw)
                kind = "pdf"
            elif is_txt:
                try:
                    text = raw.decode("utf-8", errors="ignore")
                except Exception:
                    text = raw.decode("latin-1", errors="ignore")
                kind = "txt"
            elif is_img:
                raise HTTPException(
                    status_code=415,
                    detail="Les images ne sont acceptées qu'en mode OCR. Utilisez le bouton « Importer avec OCR ».",
                )
            else:
                raise HTTPException(status_code=415, detail="Seuls les PDF et TXT sont supportés en mode classique")
        text = (text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Aucun texte extrait du fichier")
        # Chunk it (each chunk = 1 entry) so that large PDFs don't explode
        chunks = _chunk_text(text, max_chars=MAX_CHUNK_CHARS)
        upload_batch = secrets.token_urlsafe(8)
        ids = []
        for i, chunk in enumerate(chunks):
            eid = secrets.token_urlsafe(10)
            doc = {
                "id": eid,
                "title": f"{title} — partie {i + 1}/{len(chunks)}" if len(chunks) > 1 else title,
                "content": chunk,
                "tags": [],
                "kind": kind,
                "enabled": True,
                "priority": 0,
                "char_count": len(chunk),
                "source_filename": file.filename,
                "upload_batch": upload_batch,
                "chunk_index": i,
                "chunk_total": len(chunks),
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "created_by": user.get("email"),
            }
            await db.liluvine_knowledge.insert_one(doc.copy())
            ids.append(eid)
        invalidate_kb_cache()
        return {"ok": True, "ids": ids, "chunks": len(chunks), "kind": kind, "batch": upload_batch}

    return api
