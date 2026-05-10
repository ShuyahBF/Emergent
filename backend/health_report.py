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
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.widgets.markers import makeMarker

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


async def _gather_prev_week_stats(since_iso: str, prev_until_iso: str) -> Dict[str, int]:
    """Same counters as _gather_stats but for the previous-7-days window. Used
    for WoW (week-over-week) variation arrows on the KPI cards."""
    prev_win = {"$gte": since_iso, "$lt": prev_until_iso}
    return {
        "contacts": await _count("directory_contacts", {"created_at": prev_win}),
        "appointments": await _count("appointments", {"created_at": prev_win}),
        "interventions": await _count("interventions", {"created_at": prev_win}),
        "documents": await _count("documents", {"created_at": prev_win}),
        "payments": await _count("payments", {"created_at": prev_win}),
        "wa_messages": await _count("whatsapp_messages", {"created_at": prev_win}),
        "sms_messages": await _count("sms_messages", {"created_at": prev_win}),
    }


def _delta_label(current: int, previous: int) -> str:
    """Pretty WoW variation string with arrow + percent. Returns HTML inline."""
    if previous == 0 and current == 0:
        return ""
    if previous == 0:
        return "<font color='#16A34A' size='7'>↑ nouveau</font>"
    delta = current - previous
    pct = (delta / previous) * 100 if previous else 0
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
    color = "#16A34A" if delta > 0 else ("#E11D48" if delta < 0 else "#64748B")
    return f"<font color='{color}' size='7'>{arrow} {pct:+.0f}% vs S-1</font>"


async def _gather_user_activity_7d(since_iso: str, until_iso: str) -> Dict[str, Any]:
    """Collect last logins (top 5) + top pages (top 5) + a 7×24 heatmap of
    hits over the last 7 days for the PDF report. Joins access_logs with
    users for the company label."""
    win = {"$gte": since_iso, "$lt": until_iso}
    last_logins: List[Dict[str, Any]] = []
    top_pages: List[Dict[str, Any]] = []
    matrix = [[0] * 24 for _ in range(7)]
    peak_count = 0
    try:
        user_pipeline = [
            {"$match": {"created_at": win}},
            {"$group": {
                "_id": "$user_email",
                "user_name": {"$last": "$user_name"},
                "role": {"$last": "$role"},
                "last_seen_at": {"$max": "$created_at"},
                "hits": {"$sum": 1},
            }},
            {"$sort": {"last_seen_at": -1}},
            {"$limit": 5},
        ]
        async for r in db.access_logs.aggregate(user_pipeline):
            email = (r.get("_id") or "")
            u = await db.users.find_one({"email": email}, {"_id": 0, "company": 1, "full_name": 1}) or {}
            last_logins.append({
                "user_email": email,
                "user_name": r.get("user_name") or u.get("full_name") or email,
                "role": r.get("role") or "—",
                "company": u.get("company") or "—",
                "last_seen_at": r.get("last_seen_at"),
                "hits": r.get("hits", 0),
            })
    except Exception:
        pass
    try:
        page_pipeline = [
            {"$match": {"created_at": win}},
            {"$group": {
                "_id": {"module": "$module", "page": "$page"},
                "hits": {"$sum": 1},
                "users": {"$addToSet": "$user_email"},
            }},
            {"$project": {"module": "$_id.module", "page": "$_id.page", "hits": 1,
                          "unique_users": {"$size": "$users"}}},
            {"$sort": {"hits": -1}},
            {"$limit": 5},
        ]
        async for r in db.access_logs.aggregate(page_pipeline):
            top_pages.append({
                "module": r.get("module") or "—",
                "page": r.get("page") or "—",
                "hits": r.get("hits", 0),
                "unique_users": r.get("unique_users", 0),
            })
    except Exception:
        pass
    # Heatmap (7×24) — read raw timestamps and bucket in-memory
    try:
        cursor = db.access_logs.find({"created_at": win}, {"_id": 0, "created_at": 1})
        async for doc in cursor:
            try:
                d = datetime.fromisoformat((doc.get("created_at") or "").replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                wd = d.weekday()
                hr = d.hour
                matrix[wd][hr] += 1
                if matrix[wd][hr] > peak_count:
                    peak_count = matrix[wd][hr]
            except Exception:
                continue
    except Exception:
        pass
    return {"last_logins": last_logins, "top_pages": top_pages, "heatmap": matrix, "heatmap_peak": peak_count}


async def _gather_settings_meta() -> Dict[str, Any]:
    s = await db.settings.find_one({"_id": "global"}) or {}
    return {
        "support_load_level": s.get("support_load_level", 0),
        "support_load_label": s.get("support_load_label", ""),
        "incident_banner_enabled": bool(s.get("incident_banner_enabled")),
        "auto_snapshot_keep": s.get("auto_snapshot_keep", 4),
    }


async def _gather_30d_series(now: datetime) -> Dict[str, List[int]]:
    """Returns daily counts for the last 30 days for: contacts, appointments,
    whatsapp messages. Indexed oldest→newest. Aggregation done in-memory off a
    single fetch per collection to keep it cheap on small datasets."""
    days = 30
    series_keys = ("contacts", "appointments", "wa_messages")
    series: Dict[str, List[int]] = {k: [0] * days for k in series_keys}
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_iso = start.isoformat()

    def _bucket(iso_str: str) -> int:
        try:
            d = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        except Exception:
            return -1
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        delta = (d.date() - start.date()).days
        return delta if 0 <= delta < days else -1

    async def _fill(coll_name: str, key: str, date_field: str = "created_at"):
        try:
            cursor = db[coll_name].find(
                {date_field: {"$gte": start_iso}},
                {"_id": 0, date_field: 1},
            )
            async for doc in cursor:
                idx = _bucket(doc.get(date_field) or "")
                if idx >= 0:
                    series[key][idx] += 1
        except Exception:
            pass

    await _fill("directory_contacts", "contacts")
    await _fill("appointments", "appointments")
    await _fill("whatsapp_messages", "wa_messages")
    return series


def _build_trend_chart(series: List[int], color: colors.Color, width: float = 170 * mm, height: float = 28 * mm) -> Drawing:
    """Tiny line chart for a 30-day series. No axes labels — just the curve
    with a baseline + a marker on the last point."""
    days = len(series)
    data = [list(enumerate(series))]
    drawing = Drawing(width, height)
    lp = LinePlot()
    lp.x = 6
    lp.y = 6
    lp.height = height - 12
    lp.width = width - 12
    lp.data = data
    lp.lines[0].strokeColor = color
    lp.lines[0].strokeWidth = 1.4
    lp.lines.symbol = makeMarker("FilledCircle")
    lp.lines[0].symbol.fillColor = color
    lp.lines[0].symbol.strokeColor = color
    lp.lines[0].symbol.size = 3
    lp.xValueAxis.visible = 0
    lp.yValueAxis.visible = 0
    lp.xValueAxis.valueMin = 0
    lp.xValueAxis.valueMax = days - 1
    max_y = max(series) if series else 0
    lp.yValueAxis.valueMin = 0
    lp.yValueAxis.valueMax = max(1, max_y)
    drawing.add(lp)
    return drawing


def _kv_row(label: str, value: str | int, accent: bool = False, delta_html: str = "") -> List[Any]:
    label_html = f"<font color='#64748B' size='8'>{label}</font>"
    if delta_html:
        label_html += f"<br/>{delta_html}"
    return [
        Paragraph(label_html, getSampleStyleSheet()["BodyText"]),
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
    trend_30d = await _gather_30d_series(now)
    # WoW comparison data: previous 7-day window
    prev_start = (week_ago - timedelta(days=7)).isoformat()
    prev_stats = await _gather_prev_week_stats(prev_start, since_iso)
    user_activity = await _gather_user_activity_7d(since_iso, until_iso)

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

    # Activité de la semaine — KPI cards (3x3 grid avec WoW)
    story.append(Paragraph("Activité des 7 derniers jours", h2))
    kpi_data = [
        [
            *_kv_row("Nouveaux contacts", stats["contacts_new_week"], accent=True,
                     delta_html=_delta_label(stats["contacts_new_week"], prev_stats["contacts"])),
            *_kv_row("RDV créés", stats["appointments_new_week"], accent=True,
                     delta_html=_delta_label(stats["appointments_new_week"], prev_stats["appointments"])),
            *_kv_row("RDV à venir (7j)", stats["appointments_upcoming_7d"]),
        ],
        [
            *_kv_row("Interventions", stats["interventions_new_week"],
                     delta_html=_delta_label(stats["interventions_new_week"], prev_stats["interventions"])),
            *_kv_row("Documents", stats["documents_new_week"],
                     delta_html=_delta_label(stats["documents_new_week"], prev_stats["documents"])),
            *_kv_row("Paiements", stats["payments_new_week"],
                     delta_html=_delta_label(stats["payments_new_week"], prev_stats["payments"])),
        ],
        [
            *_kv_row("Messages WhatsApp", stats["wa_messages_week"],
                     delta_html=_delta_label(stats["wa_messages_week"], prev_stats["wa_messages"])),
            *_kv_row("Messages SMS", stats["sms_messages_week"],
                     delta_html=_delta_label(stats["sms_messages_week"], prev_stats["sms_messages"])),
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

    # Tendance 30 jours — sparklines
    story.append(Paragraph("Tendance des 30 derniers jours", h2))
    trend_specs = [
        ("Nouveaux contacts / jour", trend_30d.get("contacts", []), SAWALI_BLUE),
        ("RDV créés / jour", trend_30d.get("appointments", []), EMERALD),
        ("Messages WhatsApp reçus / jour", trend_30d.get("wa_messages", []), colors.HexColor("#7C3AED")),
    ]
    for label, serie, color in trend_specs:
        total = sum(serie)
        peak = max(serie) if serie else 0
        story.append(Paragraph(
            f"<font color='#334155'><b>{label}</b></font>"
            f" &nbsp;&nbsp; <font color='#64748B' size='8'>total : {total} · pic : {peak}</font>",
            body,
        ))
        story.append(_build_trend_chart(serie, color, width=170 * mm, height=24 * mm))
        story.append(Spacer(1, 4))

    # Connexions & visites — last 7 days
    if user_activity["last_logins"] or user_activity["top_pages"]:
        story.append(Paragraph("Connexions & pages visitées (7 derniers jours)", h2))
        if user_activity["last_logins"]:
            login_rows = [["Utilisateur", "Société", "Rôle", "Dernière activité", "Visites"]]
            for u in user_activity["last_logins"]:
                last_h = "—"
                try:
                    last_h = datetime.fromisoformat((u.get("last_seen_at") or "").replace("Z", "+00:00")).strftime("%d/%m %H:%M")
                except Exception:
                    pass
                login_rows.append([
                    u.get("user_name") or u.get("user_email") or "—",
                    u.get("company") or "—",
                    u.get("role") or "—",
                    last_h,
                    str(u.get("hits", 0)),
                ])
            login_tbl = Table(login_rows, colWidths=[50 * mm, 42 * mm, 22 * mm, 30 * mm, 18 * mm], hAlign="LEFT")
            login_tbl.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), SAWALI_NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#F1F5F9")),
                ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(login_tbl)
            story.append(Spacer(1, 4))
        if user_activity["top_pages"]:
            story.append(Paragraph("<font color='#334155' size='9'><b>Top pages visitées</b></font>", body))
            page_rows = [["Module", "Page", "Visites", "Utilisateurs"]]
            for p in user_activity["top_pages"]:
                page = (p.get("page") or "—")
                if len(page) > 50:
                    page = page[:48] + "…"
                page_rows.append([
                    p.get("module") or "—",
                    page,
                    str(p.get("hits", 0)),
                    str(p.get("unique_users", 0)),
                ])
            pages_tbl = Table(page_rows, colWidths=[35 * mm, 95 * mm, 18 * mm, 22 * mm], hAlign="LEFT")
            pages_tbl.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), SAWALI_NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#F1F5F9")),
                ("ALIGN", (-2, 0), (-1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(pages_tbl)

        # Heatmap (Mon→Sun × 0h→23h)
        if user_activity.get("heatmap"):
            story.append(Spacer(1, 4))
            story.append(Paragraph("<font color='#334155' size='9'><b>Heures d'activité (UTC) — carte de chaleur</b></font>", body))
            heat_matrix = user_activity["heatmap"]
            heat_peak = max(1, user_activity.get("heatmap_peak") or 0)
            weekdays_short = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
            # Header row: hour markers every 3h, the rest stays empty for clarity
            header = [""]
            for h in range(24):
                header.append(f"{h:02d}h" if h % 3 == 0 else "")
            heat_rows = [header]
            for wd, row in enumerate(heat_matrix):
                heat_rows.append([weekdays_short[wd], *[str(n) if n else "·" for n in row]])
            heat_tbl = Table(
                heat_rows,
                colWidths=[14 * mm, *[6.5 * mm] * 24],
                rowHeights=[7 * mm, *[7 * mm] * 7],
                hAlign="LEFT",
            )
            heat_style = [
                ("FONTSIZE", (0, 0), (-1, 0), 7),
                ("FONTSIZE", (0, 1), (-1, -1), 7.5),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F5F9")),
                ("TEXTCOLOR", (0, 1), (0, -1), SLATE_700),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("TEXTCOLOR", (1, 0), (-1, 0), SLATE_500),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("LINEAFTER", (0, 0), (0, -1), 0.7, colors.HexColor("#CBD5E1")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (1, 1), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 1),
                ("RIGHTPADDING", (0, 0), (-1, -1), 1),
            ]
            for r_idx, row in enumerate(heat_matrix, start=1):
                for c_idx, n in enumerate(row, start=1):
                    if n <= 0:
                        heat_style.append(("TEXTCOLOR", (c_idx, r_idx), (c_idx, r_idx), colors.HexColor("#CBD5E1")))
                        continue
                    ratio = (n / heat_peak) ** 0.5
                    alpha = 0.18 + ratio * 0.82
                    # Pre-blend RGB(30,144,255) over white at `alpha` to keep
                    # PDF readers honest (some don't render alpha-channel BG)
                    rr = int(round((1 - alpha) * 255 + alpha * 30))
                    gg = int(round((1 - alpha) * 255 + alpha * 144))
                    bb = int(round((1 - alpha) * 255 + alpha * 255))
                    bg = colors.Color(rr / 255, gg / 255, bb / 255)
                    heat_style.append(("BACKGROUND", (c_idx, r_idx), (c_idx, r_idx), bg))
                    if ratio > 0.55:
                        heat_style.append(("TEXTCOLOR", (c_idx, r_idx), (c_idx, r_idx), colors.white))
                        heat_style.append(("FONTNAME", (c_idx, r_idx), (c_idx, r_idx), "Helvetica-Bold"))
            heat_tbl.setStyle(TableStyle(heat_style))
            story.append(heat_tbl)

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
