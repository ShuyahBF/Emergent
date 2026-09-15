"""Ordonnance PDF sécurisée — Sécurisation VIDAL (portage site-meetafrican, lot 11).

Porte le comportement documenté sur l'explication "Sécuriser une ordonnance"
de la maquette d'origine : *"Imprimez l'ordonnance sécurisée — un QR code de
vérification est ajouté automatiquement, la pharmacie peut confirmer son
authenticité en un scan"*.

Même pattern ReportLab + QR que `routes/cashier.py` (`build_receipt_pdf`,
`build_qr_png`, endpoint public `/public/receipt-pdf/{token}`) — repris ici
pour rester cohérent avec le seul autre générateur de PDF déjà en place dans
l'app, plutôt que d'introduire un style différent.

Deux documents distincts, par demande explicite de l'utilisateur :
  1. Le PDF remis au médecin/patient (nom + n° WhatsApp en clair) — jamais
     stocké, régénéré à la demande depuis `db.vidal_ordonnances`.
  2. Une version ANONYMISÉE (patient identifié uniquement par la référence
     interne, jamais par son nom/numéro) archivée sur R2 dédié VIDAL
     (`R2_VIDAL_*`, voir r2_vidal_client.py — jamais les identifiants R2
     génériques, qui appartiennent à un projet tiers sans rapport) pour la
     conformité, ET utilisée telle quelle par le scan QR de vérification
     pharmacie : la pharmacie confirme l'authenticité et voit la liste des
     médicaments prescrits, jamais l'identité du patient.
"""
from __future__ import annotations

import asyncio
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

logger = logging.getLogger("sawali.vidal.ordonnance")

# 2026-09-15 fix (même cause que le hotfix appliqué à vidal_securisation.py/
# vidal_patients.py — "Impossible de générer l'ordonnance") — ces modèles
# DOIVENT vivre au scope module, pas dans une closure de
# attach_vidal_ordonnance_routes. Combiné à `from __future__ import
# annotations` en tête de fichier, une classe Pydantic définie dans une
# fonction devient une ForwardRef que Pydantic v2 ne résout jamais depuis
# une closure (`PydanticUserError: class-not-fully-defined`), d'où un 500
# sur CHAQUE POST /vidal/ordonnance/generate.
class OrdonnanceLinePayload(BaseModel):
    label: Optional[str] = None
    dose: Optional[str] = None
    unit: Optional[str] = None
    duration: Optional[str] = None
    durationType: Optional[str] = None
    frequency: Optional[str] = None
    route: Optional[str] = None


class OrdonnanceGeneratePayload(BaseModel):
    patient_name: Optional[str] = None
    patient_whatsapp: Optional[str] = None
    patient: Dict[str, Any] = {}
    lines: List[OrdonnanceLinePayload] = []
    alerts_summary: List[Dict[str, Any]] = []


class SendWhatsappPayload(BaseModel):
    phone: Optional[str] = None  # écrase le n° enregistré sur l'ordonnance, si fourni


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_line(l: Dict[str, Any]) -> List[str]:
    parts = [p for p in [l.get("dose"), l.get("unit")] if p]
    dose = " ".join(parts) or "—"
    freq = l.get("frequency") or "—"
    duration = " ".join([p for p in [l.get("duration"), l.get("durationType")] if p]) or "—"
    return [l.get("label") or "—", dose, freq, duration, l.get("route") or "—"]


def build_ordonnance_pdf(data: Dict[str, Any], *, anonymized: bool, verify_url: Optional[str] = None) -> bytes:
    """PDF A4 — mêmes briques ReportLab que build_receipt_pdf/build_invoice_pdf
    (routes/cashier.py) pour rester visuellement cohérent avec le reste de
    l'app plutôt que d'introduire un style de document différent."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=32, bottomMargin=28, leftMargin=32, rightMargin=32,
        title="Ordonnance sécurisée VIDAL",
    )
    styles = getSampleStyleSheet()
    # #9C1616 = rouge exact de l'identité visuelle Sécurisation VIDAL
    # (échantillonné sur la maquette d'origine, voir lot 10).
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=16, textColor=colors.HexColor("#9C1616"))
    h2 = ParagraphStyle("H2", parent=styles["Heading3"], fontSize=11, spaceAfter=4, textColor=colors.HexColor("#0E1F3D"))
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9.5, leading=13)
    muted = ParagraphStyle("Muted", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#64748b"), leading=11)

    ref6 = (data.get("id") or "")[:6].upper()
    patient = data.get("patient") or {}
    if anonymized:
        patient_line = f"Patient anonymisé — réf. {ref6}"
    else:
        who = data.get("patient_name") or "—"
        wa = data.get("patient_whatsapp")
        patient_line = f"{who}" + (f" — WhatsApp {wa}" if wa else "")

    profile_bits = []
    if patient.get("dateOfBirth"):
        profile_bits.append(f"Né(e) le {patient['dateOfBirth']}")
    if patient.get("gender"):
        profile_bits.append({"MALE": "Homme", "FEMALE": "Femme"}.get(patient["gender"], patient["gender"]))
    if patient.get("height"):
        profile_bits.append(f"{patient['height']} cm")
    if patient.get("weight"):
        profile_bits.append(f"{patient['weight']} kg")

    created = data.get("created_at")
    date_str = created.strftime("%d/%m/%Y à %H:%M") if isinstance(created, datetime) else str(created or "")[:16]

    story: List[Any] = [
        Paragraph("ORDONNANCE SÉCURISÉE — VIDAL", title_style),
        Paragraph("Analyse automatisée : interactions, contre-indications, posologie", muted),
        Spacer(1, 10),
        Paragraph(f"<b>Prescripteur</b> : {data.get('doctor_name') or '—'}", body),
        Paragraph(f"<b>Date</b> : {date_str}", body),
        Paragraph(f"<b>Patient</b> : {patient_line}", body),
    ]
    if profile_bits:
        story.append(Paragraph(" · ".join(profile_bits), muted))
    story.append(Spacer(1, 10))
    story.append(Paragraph("PRESCRIPTION", h2))

    lines = data.get("lines") or []
    rows = [["Médicament", "Dose", "Fréquence", "Durée", "Voie"]] + [_fmt_line(l) for l in lines]
    tbl = Table(rows, colWidths=[170, 60, 80, 70, 90])
    tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FDECEC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
    ]))
    story.append(tbl)

    alerts_summary = data.get("alerts_summary") or []
    if alerts_summary:
        story.append(Spacer(1, 10))
        story.append(Paragraph("ALERTES VÉRIFIÉES (VIDAL)", h2))
        for a in alerts_summary[:12]:
            label = (a.get("label") or a.get("category") or "").strip()
            severity = a.get("severity") or ""
            if label:
                story.append(Paragraph(f"• {label} <font color='#64748b' size='7'>({severity})</font>", body))

    story.append(Spacer(1, 14))
    if verify_url:
        try:
            from routes.cashier import build_qr_png
            png = build_qr_png(verify_url)
            story.append(RLImage(io.BytesIO(png), width=72, height=72, hAlign="LEFT"))
            story.append(Paragraph(f"<font color='#64748b' size='7'>Vérification pharmacie : {verify_url}</font>", muted))
        except Exception:  # noqa: BLE001 — le QR est un plus, jamais bloquant pour l'ordonnance elle-même
            logger.exception("[vidal_ordonnance] QR generation failed")
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Document généré électroniquement à partir d'une analyse VIDAL. Vérifiez son authenticité via le "
        "QR code. Ne remplace pas le jugement clinique du prescripteur.",
        muted,
    ))
    doc.build(story)
    return buf.getvalue()


def attach_vidal_ordonnance_routes(*, api, db, get_current_user, wa_send_media=None, wa_send_text=None):
    """`wa_send_media`/`wa_send_text` : coroutines exposées par
    `routes/whatsapp_helpers.py` (déjà utilisées pour `!doc`/`!rech`),
    passées depuis `server.py` → `routes/vidal.py::attach_vidal_routes`.
    Optionnelles : sans elles, "Envoi WA" renvoie une 503 explicite plutôt
    que de planter — même règle que pour les autres modules VIDAL."""
    from fastapi import Body, Depends, HTTPException, Response

    def _public_base_url() -> str:
        import os
        return (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")

    @api.post("/vidal/ordonnance/generate", tags=["VIDAL"])
    async def generate_ordonnance(payload: OrdonnanceGeneratePayload = Body(...), user: dict = Depends(get_current_user)):
        if not payload.lines:
            raise HTTPException(status_code=400, detail="Au moins une ligne de prescription est requise")
        oid = str(uuid.uuid4())
        qr_token = uuid.uuid4().hex
        # Jeton DISTINCT du qr_token : le qr_token est imprimé/encodé en QR sur
        # le document (n'importe qui peut le scanner → sert la version
        # ANONYMISÉE uniquement). full_token n'est jamais imprimé, seulement
        # utilisé côté serveur pour le lien "document" envoyé PAR WhatsApp
        # directement au patient concerné (voir send_ordonnance_whatsapp).
        full_token = uuid.uuid4().hex
        doc_data = {
            "id": oid, "qr_token": qr_token, "full_token": full_token, "user_id": user["id"],
            "doctor_name": user.get("full_name") or user.get("email"),
            "patient_name": payload.patient_name, "patient_whatsapp": payload.patient_whatsapp,
            "patient": payload.patient, "lines": [l.model_dump() for l in payload.lines],
            "alerts_summary": payload.alerts_summary, "created_at": _now(),
        }
        await db.vidal_ordonnances.insert_one(dict(doc_data))

        base = _public_base_url()
        verify_url = f"{base}/api/vidal/ordonnance/verify/{qr_token}" if base else None

        # Archivage anonymisé sur R2 dédié VIDAL — best-effort : ne bloque
        # jamais la remise de l'ordonnance au médecin si R2 est indisponible
        # ou non configuré (règle déjà établie pour ce module).
        try:
            from r2_vidal_client import is_configured, put_bytes
            if is_configured():
                anon_pdf = build_ordonnance_pdf(doc_data, anonymized=True, verify_url=verify_url)
                await asyncio.to_thread(put_bytes, f"ordonnances/{oid}.pdf", anon_pdf, "application/pdf")
        except Exception:  # noqa: BLE001
            logger.exception("[vidal_ordonnance] archivage R2 échoué pour %s", oid)

        full_pdf = build_ordonnance_pdf(doc_data, anonymized=False, verify_url=verify_url)
        return Response(
            content=full_pdf, media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="ordonnance-{oid[:8]}.pdf"',
                # L'id est nécessaire côté frontend pour proposer "Envoi WA" —
                # le corps de la réponse est le PDF lui-même, pas du JSON.
                "X-Ordonnance-Id": oid,
            },
        )

    @api.get("/vidal/ordonnance/verify/{token}", tags=["VIDAL"])
    async def verify_ordonnance(token: str):
        """Public (pas d'auth) — scanné par la pharmacie. Renvoie la version
        ANONYMISÉE (jamais le nom/n° du patient) : confirme l'authenticité et
        montre la liste des médicaments, sans exposer l'identité du patient
        à qui que ce soit qui scanne le QR (perte de l'ordonnance papier,
        etc.)."""
        doc = await db.vidal_ordonnances.find_one({"qr_token": token}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Ordonnance introuvable ou invalide")
        pdf = build_ordonnance_pdf(doc, anonymized=True)
        return Response(
            content=pdf, media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="ordonnance-verif-{token[:8]}.pdf"',
                "Cache-Control": "public, max-age=300",
            },
        )

    @api.get("/vidal/ordonnance/full-pdf/{full_token}", tags=["VIDAL"])
    async def full_pdf_ordonnance(full_token: str):
        """Public (pas d'auth) — requis pour que les serveurs WhatsApp/Meta
        puissent récupérer le média lors de l'envoi (même contrainte que
        `/api/public/receipt-pdf/{token}` dans routes/cashier.py). `full_token`
        est distinct du `qr_token` imprimé sur le document : il n'est utilisé
        QUE côté serveur pour le lien envoyé directement au patient concerné,
        jamais affiché ni scanné par un tiers."""
        doc = await db.vidal_ordonnances.find_one({"full_token": full_token}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Ordonnance introuvable ou invalide")
        base = _public_base_url()
        verify_url = f"{base}/api/vidal/ordonnance/verify/{doc['qr_token']}" if base else None
        pdf = build_ordonnance_pdf(doc, anonymized=False, verify_url=verify_url)
        return Response(
            content=pdf, media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="ordonnance-{doc["id"][:8]}.pdf"',
                "Cache-Control": "private, max-age=300",
            },
        )

    @api.post("/vidal/ordonnance/{ordonnance_id}/send-whatsapp", tags=["VIDAL"])
    async def send_ordonnance_whatsapp(
        ordonnance_id: str,
        payload: SendWhatsappPayload = Body(default_factory=SendWhatsappPayload),
        user: dict = Depends(get_current_user),
    ):
        if wa_send_media is None and wa_send_text is None:
            raise HTTPException(status_code=503, detail="Envoi WhatsApp non configuré côté serveur")
        doc = await db.vidal_ordonnances.find_one({"id": ordonnance_id, "user_id": user["id"]}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Ordonnance introuvable")
        phone = (payload.phone or doc.get("patient_whatsapp") or "").strip()
        if not phone:
            raise HTTPException(status_code=400, detail="Aucun n° WhatsApp pour ce patient — renseigne-le sur l'ordonnance ou dans le champ patient.")
        base = _public_base_url()
        if not base:
            raise HTTPException(status_code=503, detail="PUBLIC_BASE_URL non configuré — impossible de générer un lien accessible par WhatsApp")
        pdf_url = f"{base}/api/vidal/ordonnance/full-pdf/{doc['full_token']}"
        caption = f"📄 Ordonnance sécurisée VIDAL — {doc.get('doctor_name') or 'votre médecin'}"

        result = {"ok": False}
        method = None
        # Message média libre en premier (aucun modèle Meta à préconfigurer,
        # fonctionne tant que la fenêtre de service client de 24h est ouverte
        # — même mécanisme déjà utilisé pour !doc/!rech WhatsApp).
        if wa_send_media is not None:
            result = await wa_send_media(phone, "document", public_url=pdf_url, caption=caption, filename="ordonnance.pdf")
            method = "document"
        if not result.get("ok") and wa_send_text is not None:
            text = f"{caption}\nTéléchargez votre ordonnance : {pdf_url}"
            result = await wa_send_text(phone, text)
            method = "text"
        if not result.get("ok"):
            raise HTTPException(status_code=502, detail=result.get("error") or "Envoi WhatsApp échoué")
        return {"ok": True, "method": method}
