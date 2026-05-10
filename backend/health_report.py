"""Weekly health-report PDF generator.

Builds a lightweight one/two-page PDF summarizing the platform's last-7-days
activity. Designed to be attached alongside the .json.gz snapshot email so
admins get a portable, printable status update without logging in.

Pure-Python (reportlab), no system deps. Returns the PDF bytes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from db import db


SAWALI_NAVY = colors.HexColor("#0E1F3D")
SAWALI_BLUE = colors.HexColor("#1E90FF")
SLATE_500 = colors.HexColor("#64748B")
SLATE_700 = colors.HexColor("#334155")
EMERALD = colors.HexColor("#10B981")
ROSE = colors.HexColor("#E11D48")


async def _count(coll: str, q: dict) -> int:
    try:
        return await db[coll].count_documents(q)
    except Exception:
        return 0


async def _gather_stats(since_iso: str, until_iso: str) -> Dict[str, Any]:
    """Collect headline counts for the last 7-day window."""
    win = {"$gte": since_iso, "$lt": until_iso}
    upcoming_until = (datetime.fromisoformat(until_iso) + timedelta(days=7)).isoformat()

    stats: Dict[str, Any] = {
        "users_total": await _count("users", {}),
        "contacts_total": await _count("directory_contacts", {}),
        "contacts_new_week": await _count("directory_contacts", {"created_at": win}),
        "appointments_total": await _count("appointments", {}),
        "appointments_new_week": await _count("appointments", {"created_at": win}),
        "appointments_upcoming_7d": await _count(
            "appointments", {"start_at": {"$gte": until_iso, "$lt": upcoming_until}}
        ),
        "interventions_new_week": await _count("interventions", {"created_at": win}),
        "documents_new_week": await _count("documents", {"created_at": win}),
        "wa_messages_week": await _count("whatsapp_messages", {"created_at": win}),
        "sms_messages_week": await _count("sms_messages", {"created_at": win}),
        "wa_schedules_pending": await _count("whatsapp_schedules", {"status": "pending"}),
        "sms_schedules_pending": await _count("sms_schedules", {"status": "pending"}),
        "incidents_open": await _count("incidents", {"resolved": {"$ne": True}}),
        "payments_new_week": await _count("payments", {"created_at": win}),
        "formations_active": await _count("formations", {"state": {"$nin": ["annulée", "archivée"]}}),
    }
    # Top 5 most recent contacts
    try:
        cursor = db.directory_contacts.find(
            {"created_at": win}, {"_id": 0, "name": 1, "company": 1, "created_at": 1}
        ).sort("created_at", -1).limit(5)
        stats["recent_contacts"] = [c async for c in cursor]
    except Exception:
        stats["recent_contacts"] = []
    return stats


async def _gather_settings_meta() -> Dict[str, Any]:
    s = await db.settings.find_one({"_id": "global"}) or {}
    return {
        "support_load_level": s.get("support_load_level", 0),
        "support_load_label": s.get("support_load_label", ""),
        "incident_banner_enabled": bool(s.get("incident_banner_enabled")),
        "auto_snapshot_keep": s.get("auto_snapshot_keep", 4),
    }


def _kv_row(label: str, value: str | int, accent: bool = False) -> List[Any]:
    return [
        Paragraph(f"<font color='#64748B' size='8'>{label}</font>", getSampleStyleSheet()["BodyText"]),
        Paragraph(
            f"<font color='{'#1E90FF' if accent else '#0E1F3D'}' size='14'><b>{value}</b></font>",
            getSampleStyleSheet()["BodyText"],
        ),
    ]


async def build_weekly_health_pdf(snapshot_meta: Dict[str, Any] | None = None) -> bytes:
    """Generate the weekly health-report PDF and return its bytes.
    `snapshot_meta` (optional) embeds the companion snapshot's stats."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    since_iso = week_ago.isoformat()
    until_iso = now.isoformat()

    stats = await _gather_stats(since_iso, until_iso)
    smeta = await _gather_settings_meta()

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=14 * mm,
        title="SAWALI — Rapport hebdomadaire",
        author="SAWALI SMART SYSTEMS",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, textColor=SAWALI_NAVY, spaceAfter=4)
    sub = ParagraphStyle("sub", parent=styles["BodyText"], fontSize=9, textColor=SLATE_500, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, textColor=SAWALI_BLUE, spaceAfter=6, spaceBefore=10)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, textColor=SLATE_700)
    small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=8, textColor=SLATE_500)

    story: List[Any] = []
    story.append(Paragraph("SAWALI SMART SYSTEMS — Rapport hebdomadaire", h1))
    story.append(Paragraph(
        f"Période : {week_ago.strftime('%d/%m/%Y %H:%M')} → {now.strftime('%d/%m/%Y %H:%M')} (UTC)",
        sub,
    ))

    # Activité de la semaine — KPI cards (2x3 grid)
    story.append(Paragraph("Activité des 7 derniers jours", h2))
    kpi_data = [
        [
            *_kv_row("Nouveaux contacts", stats["contacts_new_week"], accent=True),
            *_kv_row("RDV créés", stats["appointments_new_week"], accent=True),
            *_kv_row("RDV à venir (7j)", stats["appointments_upcoming_7d"]),
        ],
        [
            *_kv_row("Interventions", stats["interventions_new_week"]),
            *_kv_row("Documents", stats["documents_new_week"]),
            *_kv_row("Paiements", stats["payments_new_week"]),
        ],
        [
            *_kv_row("Messages WhatsApp", stats["wa_messages_week"]),
            *_kv_row("Messages SMS", stats["sms_messages_week"]),
            *_kv_row("Formations actives", stats["formations_active"]),
        ],
    ]
    kpi_table = Table(kpi_data, colWidths=[28 * mm, 22 * mm] * 3, hAlign="LEFT")
    kpi_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#F1F5F9")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(kpi_table)

    # État de la plateforme
    story.append(Paragraph("État de la plateforme", h2))
    load_lvl = int(smeta.get("support_load_level") or 0)
    load_color = ("#16A34A" if load_lvl <= 3 else "#F59E0B" if load_lvl <= 5 else "#E11D48")
    state_data = [
        [Paragraph("<b>Jauge Support technique</b>", body),
         Paragraph(f"<font color='{load_color}'>{load_lvl}/7</font> — {smeta.get('support_load_label') or '—'}", body)],
        [Paragraph("<b>Incidents ouverts</b>", body),
         Paragraph(
            f"<font color='{'#E11D48' if stats['incidents_open'] else '#16A34A'}'>{stats['incidents_open']}</font>",
            body)],
        [Paragraph("<b>Planifications WA en attente</b>", body),
         Paragraph(f"{stats['wa_schedules_pending']}", body)],
        [Paragraph("<b>Planifications SMS en attente</b>", body),
         Paragraph(f"{stats['sms_schedules_pending']}", body)],
        [Paragraph("<b>Bandeau d'incident public</b>", body),
         Paragraph("Actif" if smeta["incident_banner_enabled"] else "Inactif", body)],
    ]
    state_tbl = Table(state_data, colWidths=[80 * mm, 90 * mm], hAlign="LEFT")
    state_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#F1F5F9")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(state_tbl)

    # Nouveaux contacts détaillés
    if stats["recent_contacts"]:
        story.append(Paragraph("Derniers contacts ajoutés", h2))
        rows = [["Nom", "Société", "Ajouté le"]]
        for c in stats["recent_contacts"]:
            created = c.get("created_at") or ""
            try:
                created_h = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
            except Exception:
                created_h = (created[:16] if created else "—")
            rows.append([c.get("name") or "—", c.get("company") or "—", created_h])
        contacts_tbl = Table(rows, colWidths=[60 * mm, 60 * mm, 50 * mm], hAlign="LEFT")
        contacts_tbl.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), SAWALI_NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#F1F5F9")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(contacts_tbl)

    # Snapshot companion summary
    if snapshot_meta:
        story.append(Paragraph("Sauvegarde DB jointe", h2))
        snap_rows = [
            [Paragraph("<b>Fichier</b>", body), Paragraph(snapshot_meta.get("file_name") or "—", body)],
            [Paragraph("<b>Documents</b>", body), Paragraph(f"{snapshot_meta.get('total_documents', 0)} sur {snapshot_meta.get('collections_count', 0)} collections", body)],
            [Paragraph("<b>Taille</b>", body), Paragraph(f"{(snapshot_meta.get('size_bytes', 0) / 1024):.1f} kB", body)],
            [Paragraph("<b>Secrets masqués</b>", body), Paragraph("Oui" if snapshot_meta.get("mask_secrets") else "Non", body)],
        ]
        snap_tbl = Table(snap_rows, colWidths=[55 * mm, 115 * mm], hAlign="LEFT")
        snap_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#F1F5F9")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(snap_tbl)

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f"Généré automatiquement le {now.strftime('%d/%m/%Y à %H:%M:%S')} UTC — SAWALI SMART SYSTEMS",
        small,
    ))

    doc.build(story)
    return buf.getvalue()
