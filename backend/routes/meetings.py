"""S-iter39b — PV de réunions internes (Meeting Minutes).

Auto-numbered, rich-text minutes of internal meetings. Linked to the tenant.
Authoring is open to any user in the tenant; editing/deletion is reserved to
admin/superviseur or to the original author. A PDF can be generated on demand
via /api/me/meetings/{id}/pdf using reportlab.

Schema (collection: `meeting_minutes`):
  - id              str (uuid)
  - tenant_id       str
  - numero          str  (e.g. "PV-2026-001")
  - meeting_date    str  ISO date (YYYY-MM-DD)
  - started_at      str  ISO datetime
  - ended_at        str  ISO datetime  (auto on save, can be edited)
  - title           str
  - attendees       str  (optional free text)
  - body_html       str  (rich text)
  - author_id       str
  - author_name     str
  - author_email    str
  - created_at      str  ISO datetime
  - updated_at      str  ISO datetime
  - deleted_at      str|None
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Response, Query
from pydantic import BaseModel, Field

from ._counters import next_seq


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_admin_or_sup(user: dict) -> bool:
    return (user.get("role") or "") in ("admin", "superviseur")


def _is_elevated_tracked(user: dict) -> bool:
    return (user.get("tracked_role") or "") in ("Administrateur", "Superviseur")


def _can_edit(user: dict, doc: dict) -> bool:
    if _is_admin_or_sup(user) or _is_elevated_tracked(user):
        return True
    return doc.get("author_id") == user.get("id")


def _can_delete(user: dict) -> bool:
    return _is_admin_or_sup(user) or _is_elevated_tracked(user)


class MeetingCreate(BaseModel):
    meeting_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    started_at: str = Field(..., max_length=64)  # ISO datetime
    title: str = Field(..., min_length=1, max_length=240)
    body_html: str = Field("", max_length=200_000)
    attendees: Optional[str] = Field(None, max_length=2000)


class MeetingUpdate(BaseModel):
    meeting_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    started_at: Optional[str] = Field(None, max_length=64)
    ended_at: Optional[str] = Field(None, max_length=64)
    title: Optional[str] = Field(None, min_length=1, max_length=240)
    body_html: Optional[str] = Field(None, max_length=200_000)
    attendees: Optional[str] = Field(None, max_length=2000)


def make_router(*, db, get_current_user):
    router = APIRouter(prefix="/me/meetings", tags=["PV de réunions"])

    async def _resolve_tenant_id(user: dict) -> str:
        for key in ("parent_client_id", "client_id"):
            ref = user.get(key)
            if ref and ref != user.get("id"):
                return ref
        return user["id"]

    async def _list_query(user: dict) -> Dict[str, Any]:
        tid = await _resolve_tenant_id(user)
        return {"tenant_id": tid, "deleted_at": None}

    @router.get("")
    async def list_meetings(
        q: Optional[str] = Query(None, max_length=200),
        limit: int = Query(100, ge=1, le=500),
        user: dict = Depends(get_current_user),
    ):
        base = await _list_query(user)
        if q:
            qr = q.strip()
            base["$or"] = [
                {"title": {"$regex": qr, "$options": "i"}},
                {"numero": {"$regex": qr, "$options": "i"}},
                {"attendees": {"$regex": qr, "$options": "i"}},
            ]
        cursor = db.meeting_minutes.find(base, {"_id": 0, "body_html": 0}).sort("meeting_date", -1).limit(limit)
        items = [m async for m in cursor]
        return {"items": items, "count": len(items)}

    @router.post("", status_code=201)
    async def create_meeting(payload: MeetingCreate, user: dict = Depends(get_current_user)):
        tid = await _resolve_tenant_id(user)
        # Auto-number: PV-YYYY-NNN per tenant per year
        year = payload.meeting_date.split("-")[0]
        counter_key = f"meeting_minutes-{tid}-{year}"
        seq = await next_seq(db, counter_key)
        numero = f"PV-{year}-{str(seq).zfill(3)}"
        ended_at = _now()  # set to NOW because the user just clicked Enregistrer
        doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": tid,
            "numero": numero,
            "meeting_date": payload.meeting_date,
            "started_at": payload.started_at,
            "ended_at": ended_at,
            "title": payload.title.strip(),
            "body_html": payload.body_html or "",
            "attendees": (payload.attendees or "").strip() or None,
            "author_id": user["id"],
            "author_name": user.get("full_name") or user.get("email") or "—",
            "author_email": user.get("email"),
            "created_at": _now(),
            "updated_at": _now(),
            "deleted_at": None,
        }
        await db.meeting_minutes.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.get("/{mid}")
    async def get_meeting(mid: str, user: dict = Depends(get_current_user)):
        scope = await _list_query(user)
        doc = await db.meeting_minutes.find_one({**scope, "id": mid}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="PV introuvable")
        return doc

    @router.put("/{mid}")
    async def update_meeting(mid: str, payload: MeetingUpdate, user: dict = Depends(get_current_user)):
        scope = await _list_query(user)
        doc = await db.meeting_minutes.find_one({**scope, "id": mid}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="PV introuvable")
        if not _can_edit(user, doc):
            raise HTTPException(status_code=403, detail="Modification réservée à l'auteur, admin ou superviseur")
        update: Dict[str, Any] = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
        if not update:
            return doc
        update["updated_at"] = _now()
        await db.meeting_minutes.update_one({"id": mid}, {"$set": update})
        doc.update(update)
        return doc

    @router.delete("/{mid}")
    async def delete_meeting(mid: str, user: dict = Depends(get_current_user)):
        if not _can_delete(user):
            raise HTTPException(status_code=403, detail="Suppression réservée à admin/superviseur")
        scope = await _list_query(user)
        doc = await db.meeting_minutes.find_one({**scope, "id": mid}, {"_id": 0, "id": 1})
        if not doc:
            raise HTTPException(status_code=404, detail="PV introuvable")
        await db.meeting_minutes.update_one({"id": mid}, {"$set": {"deleted_at": _now()}})
        return {"ok": True}

    @router.get("/{mid}/pdf")
    async def export_pdf(mid: str, user: dict = Depends(get_current_user)):
        scope = await _list_query(user)
        doc = await db.meeting_minutes.find_one({**scope, "id": mid}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="PV introuvable")
        pdf_bytes = _render_pdf(doc)
        filename = f"{doc.get('numero', 'PV')}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    return router


def _render_pdf(doc: dict) -> bytes:
    """Render a single-PV PDF with reportlab Platypus (already pinned for
    other modules). Strips HTML to plain paragraphs but preserves bold/italic
    by feeding the body_html directly into Paragraph which understands a
    limited subset of HTML tags (b, i, u, br, p)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    import re

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            title=doc.get("numero", "PV"))
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ti", parent=styles["Title"], fontSize=18, alignment=1, textColor=colors.HexColor("#1E3A8A"))
    meta_style = ParagraphStyle("mt", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#475569"))
    body_style = ParagraphStyle("bd", parent=styles["BodyText"], fontSize=11, leading=15, spaceBefore=4, spaceAfter=4)
    h_style = ParagraphStyle("h", parent=styles["Heading2"], fontSize=13, textColor=colors.HexColor("#1E40AF"))

    story = [
        Paragraph("Procès-Verbal de Réunion Interne", title_style),
        Spacer(1, 6),
        Paragraph(f"<b>{doc.get('numero', '')}</b>", meta_style),
        Spacer(1, 10),
    ]

    # Meta table
    started = doc.get("started_at") or ""
    ended = doc.get("ended_at") or ""
    try:
        started_h = datetime.fromisoformat(started.replace("Z", "+00:00")).strftime("%H:%M")
    except (ValueError, TypeError):
        started_h = started
    try:
        ended_h = datetime.fromisoformat(ended.replace("Z", "+00:00")).strftime("%H:%M")
    except (ValueError, TypeError):
        ended_h = ended
    rows = [
        ["Titre", doc.get("title") or ""],
        ["Date de la réunion", doc.get("meeting_date") or ""],
        ["Heure de début", started_h],
        ["Heure de fin", ended_h],
        ["Auteur du PV", doc.get("author_name") or doc.get("author_email") or "—"],
    ]
    if doc.get("attendees"):
        rows.append(["Participants", doc["attendees"]])
    table = Table(rows, colWidths=[4.5 * cm, 12 * cm])
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F5F9")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1E3A8A")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E2E8F0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    story.append(Spacer(1, 16))

    story.append(Paragraph("Contenu", h_style))
    story.append(Spacer(1, 6))

    # Clean HTML: ReportLab Paragraph understands a small HTML subset (b, i,
    # u, br, font, p). We strip unsupported tags but keep line-breaks and
    # paragraphs by converting <p>, <ul>, <ol>, <li>, <h*> to newlines.
    body_html = doc.get("body_html") or "<p>—</p>"
    text = body_html
    text = re.sub(r"</p>|</li>|</h[1-6]>|</div>", "<br/>", text, flags=re.IGNORECASE)
    text = re.sub(r"<(p|ul|ol|div|h[1-6])[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.IGNORECASE)
    # Drop unsupported attributes to avoid ReportLab parse errors
    text = re.sub(r"<(b|i|u|em|strong|br)([^>]*)>", lambda m: f"<{m.group(1).lower()}{'/' if m.group(1).lower()=='br' else ''}>", text, flags=re.IGNORECASE)
    # Drop any remaining unknown tags
    text = re.sub(r"</?(?!(?:b|i|u|em|strong|br|font))[^>]+>", "", text, flags=re.IGNORECASE)
    for chunk in text.split("<br/>") if "<br/>" in text else [text]:
        chunk = chunk.strip()
        if chunk:
            try:
                story.append(Paragraph(chunk, body_style))
            except Exception:
                # ReportLab parsing fallback: strip ALL tags and try again
                plain = re.sub(r"<[^>]+>", "", chunk)
                if plain.strip():
                    story.append(Paragraph(plain, body_style))

    pdf.build(story)
    buf.seek(0)
    return buf.read()


__all__ = ["make_router"]
