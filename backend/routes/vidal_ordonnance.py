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

Lot 57 — même circuit que Ster (demande du propriétaire) :
  - l'ordonnance s'imprime en A5 (QR code de 35 mm en haut à droite, taille
    physique gardée pour une lecture fiable) ;
  - le QR mène à la page PUBLIQUE de l'officine (/officine/ordonnance/<jeton>,
    sans compte) : l'officine vérifie l'ordonnance (patient anonymisé), indique
    pour chaque produit ce qu'elle a servi (quantité), servi en partie, ou
    « en rupture », puis valide ;
  - le médecin voit en retour, dans « Mes ordonnances — retour des officines »,
    si chaque ordonnance a pu être servie (et où un produit était en rupture).
  - GET  /public/vidal-ordonnance/{jeton}          lecture par l'officine
  - POST /public/vidal-ordonnance/{jeton}/servir   service / rupture
  - GET  /vidal/ordonnances                        retour pour le médecin
  - GET  /vidal/ordonnances/{id}/pdf               aperçu de l'ordonnance
L'ancien lien /vidal/ordonnance/verify/{jeton} (ordonnances déjà imprimées)
renvoie désormais vers la page de l'officine.
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


# Lot 57 — statut d'une ligne indiqué par l'officine
STATUTS_LIGNE = {"servi": "Servi", "partiel": "Servi en partie", "rupture": "En rupture", "non_servi": "Non servi"}


class LigneServieOfficine(BaseModel):
    index: int                                  # numéro de la ligne de l'ordonnance (0, 1, 2…)
    statut: str = "servi"                       # servi | partiel | rupture | non_servi
    quantite_servie: Optional[int] = None       # nombre d'unités / boîtes servies


class ServiceOfficinePayload(BaseModel):
    nom_officine: str
    ville: Optional[str] = None
    lignes: List[LigneServieOfficine] = []
    commentaire: Optional[str] = None


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


def reference_ordonnance(data: Dict[str, Any]) -> str:
    """Référence courte affichée sur l'ordonnance et à l'officine (8 premiers caractères de l'id)."""
    return (data.get("id") or "")[:8].upper()


def build_ordonnance_pdf(data: Dict[str, Any], *, anonymized: bool, verify_url: Optional[str] = None) -> bytes:
    """PDF A5 (lot 57, comme Ster) — mêmes briques ReportLab que build_receipt_pdf
    (routes/cashier.py). Largeur utile 128 mm (148 - 2 × 10 mm de marge) : toutes
    les colonnes sont recalculées pour ce format ; le QR code garde 35 mm (taille
    physique nécessaire à une lecture fiable en officine)."""
    from reportlab.lib.pagesizes import A5
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A5,
        topMargin=10 * mm, bottomMargin=10 * mm, leftMargin=10 * mm, rightMargin=10 * mm,
        title="Ordonnance sécurisée VIDAL",
    )
    styles = getSampleStyleSheet()
    # #9C1616 = rouge exact de l'identité visuelle Sécurisation VIDAL
    # (échantillonné sur la maquette d'origine, voir lot 10).
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=12.5, leading=15, alignment=0, textColor=colors.HexColor("#9C1616"))
    h2 = ParagraphStyle("H2", parent=styles["Heading3"], fontSize=9.5, spaceAfter=3, textColor=colors.HexColor("#0E1F3D"))
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=8.5, leading=11)
    muted = ParagraphStyle("Muted", parent=styles["Normal"], fontSize=7, textColor=colors.HexColor("#64748b"), leading=9)
    cellule = ParagraphStyle("Cellule", parent=styles["Normal"], fontSize=7.5, leading=9)

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

    # En-tête : textes à gauche, QR code (35 mm) à droite — comme l'ordonnance A5 de Ster
    entete_texte: List[Any] = [
        Paragraph("ORDONNANCE SÉCURISÉE — VIDAL", title_style),
        Paragraph("Analyse automatisée : interactions, contre-indications, posologie", muted),
        Spacer(1, 2 * mm),
        Paragraph(f"<b>Prescripteur</b> : {data.get('doctor_name') or '—'}", body),
        Paragraph(f"<b>Date</b> : {date_str}", body),
        Paragraph(f"<b>Patient</b> : {patient_line}", body),
    ]
    if profile_bits:
        entete_texte.append(Paragraph(" · ".join(profile_bits), muted))
    entete_texte.append(Paragraph(f"Référence : {reference_ordonnance(data)}", muted))
    qr_cellule: Any = ""
    if verify_url:
        try:
            from routes.cashier import build_qr_png
            qr_cellule = RLImage(io.BytesIO(build_qr_png(verify_url)), width=35 * mm, height=35 * mm)
        except Exception:  # noqa: BLE001 — le QR est un plus, jamais bloquant pour l'ordonnance elle-même
            logger.exception("[vidal_ordonnance] QR generation failed")
    entete = Table([[entete_texte, qr_cellule]], colWidths=[93 * mm, 35 * mm])
    entete.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story: List[Any] = [entete]
    if verify_url:
        story.append(Paragraph("Officine : scannez le QR code pour vérifier et enregistrer la délivrance",
                               ParagraphStyle("QrLegende", parent=muted, alignment=TA_RIGHT)))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("PRESCRIPTION", h2))

    lines = data.get("lines") or []
    # Cellules en Paragraph : un nom de médicament long revient à la ligne au lieu de déborder
    rows = [["Médicament", "Dose", "Fréquence", "Durée", "Voie"]] + [
        [Paragraph(str(v), cellule) for v in _fmt_line(l)] for l in lines
    ]
    tbl = Table(rows, colWidths=[46 * mm, 18 * mm, 24 * mm, 20 * mm, 20 * mm])
    tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FDECEC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
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

    story.append(Spacer(1, 6 * mm))
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

    def _url_officine(qr_token: str) -> str:
        """Lot 57 — adresse imprimée dans le QR : page PUBLIQUE de l'officine sur le site
        (FRONTEND_PUBLIC_URL, sinon https://sawalismartsystems.com)."""
        import os
        site = (os.environ.get("FRONTEND_PUBLIC_URL") or "https://sawalismartsystems.com").rstrip("/")
        return f"{site}/officine/ordonnance/{qr_token}"

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

        verify_url = _url_officine(qr_token)  # Lot 57 — QR vers la page de l'officine

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
        """Public (pas d'auth) — ancien lien des QR déjà imprimés. Lot 57 : renvoie
        vers la page de l'officine (vérification + délivrance), qui n'affiche
        jamais l'identité du patient."""
        from fastapi.responses import RedirectResponse
        doc = await db.vidal_ordonnances.find_one({"qr_token": token}, {"_id": 0, "id": 1})
        if not doc:
            raise HTTPException(status_code=404, detail="Ordonnance introuvable ou invalide")
        return RedirectResponse(_url_officine(token), status_code=307)

    # ------------------------------------------------------------------
    # Lot 57 — circuit officine (comme Ster) : vérification, délivrance, rupture
    # ------------------------------------------------------------------
    def _resume_services(services: List[Dict[str, Any]], nb_lignes: int) -> Dict[str, Any]:
        """État de l'ordonnance pour le médecin, d'après TOUS les retours d'officines :
        « servie » (toutes les lignes servies), « partielle », « rupture » (au moins
        une ligne en rupture et rien d'autre de servi) ou « en_attente »."""
        if not services:
            return {"etat": "en_attente", "libelle": "En attente de l'officine", "ruptures": []}
        servies, ruptures = set(), []
        for s in services:
            for l in s.get("lignes") or []:
                if l.get("statut") == "servi":
                    servies.add(l.get("index"))
                elif l.get("statut") == "rupture":
                    ruptures.append({"index": l.get("index"), "officine": s.get("nom_officine")})
        if nb_lignes and len(servies) >= nb_lignes:
            return {"etat": "servie", "libelle": "Servie", "ruptures": ruptures}
        if servies or any(l.get("statut") == "partiel" for s in services for l in s.get("lignes") or []):
            return {"etat": "partielle", "libelle": "Servie en partie", "ruptures": ruptures}
        if ruptures:
            return {"etat": "rupture", "libelle": "Produit(s) en rupture", "ruptures": ruptures}
        return {"etat": "non_servie", "libelle": "Non servie", "ruptures": ruptures}

    def _services_publics(services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{k: s.get(k) for k in ("nom_officine", "ville", "lignes", "commentaire", "date_service")} for s in services]

    @api.get("/public/vidal-ordonnance/{token}", tags=["VIDAL — officine"])
    async def lire_ordonnance_officine(token: str):
        """Public (sans compte) — ouvert par l'officine en scannant le QR. Patient
        ANONYMISÉ (jamais son nom ni son numéro) ; lignes prescrites et retours
        déjà enregistrés par d'autres officines, relus en direct."""
        doc = await db.vidal_ordonnances.find_one({"qr_token": token}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Ordonnance introuvable ou invalide")
        services = await db.vidal_ordonnance_services.find({"ordonnance_id": doc["id"]}, {"_id": 0}).sort("date_service", 1).to_list(50)
        patient = doc.get("patient") or {}
        return {
            "reference": reference_ordonnance(doc),
            "date": doc.get("created_at"),
            "prescripteur": doc.get("doctor_name"),
            "patient": {"sexe": {"MALE": "Homme", "FEMALE": "Femme"}.get(patient.get("gender"), None),
                        "date_naissance": patient.get("dateOfBirth")},
            "lignes": [{"index": i, "libelle": l.get("label"), "detail": " · ".join(x for x in _fmt_line(l)[1:] if x and x != "—")}
                       for i, l in enumerate(doc.get("lines") or [])],
            "services": _services_publics(services),
            "statuts": STATUTS_LIGNE,
        }

    @api.post("/public/vidal-ordonnance/{token}/servir", tags=["VIDAL — officine"])
    async def servir_ordonnance_officine(token: str, payload: ServiceOfficinePayload = Body(...)):
        """Public (sans compte) — l'officine enregistre, pour chaque produit, ce qu'elle a
        servi (quantité), servi en partie, ou « en rupture ». L'ordonnance vient
        EXCLUSIVEMENT du jeton imprimé dans le QR, jamais du formulaire."""
        doc = await db.vidal_ordonnances.find_one({"qr_token": token}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Ordonnance introuvable ou invalide")
        nom = (payload.nom_officine or "").strip().upper()[:120]
        if not nom:
            raise HTTPException(status_code=422, detail="Le nom de l'officine est obligatoire.")
        nb_lignes = len(doc.get("lines") or [])
        lignes = []
        for l in payload.lignes:
            if not 0 <= l.index < nb_lignes:
                raise HTTPException(status_code=422, detail="Ligne d'ordonnance inconnue.")
            if l.statut not in STATUTS_LIGNE:
                raise HTTPException(status_code=422, detail="Statut de ligne inconnu.")
            if l.quantite_servie is not None and not 0 <= l.quantite_servie <= 1000:
                raise HTTPException(status_code=422, detail="Quantité servie invalide (0 à 1000).")
            if l.statut in ("servi", "partiel") and not l.quantite_servie:
                raise HTTPException(status_code=422, detail="Indiquez la quantité servie pour chaque produit servi.")
            lignes.append({"index": l.index, "libelle": (doc["lines"][l.index] or {}).get("label"), "statut": l.statut,
                           "quantite_servie": l.quantite_servie if l.statut in ("servi", "partiel") else None})
        if not lignes:
            raise HTTPException(status_code=422, detail="Indiquez au moins un produit.")
        if await db.vidal_ordonnance_services.count_documents({"ordonnance_id": doc["id"]}) >= 20:
            raise HTTPException(status_code=429, detail="Trop de retours enregistrés pour cette ordonnance.")
        service = {
            "id": str(uuid.uuid4()), "ordonnance_id": doc["id"], "user_id": doc.get("user_id"),
            "nom_officine": nom, "ville": (payload.ville or "").strip()[:80] or None,
            "lignes": lignes, "commentaire": (payload.commentaire or "").strip()[:500] or None,
            "date_service": _now(),
        }
        await db.vidal_ordonnance_services.insert_one(dict(service))
        services = await db.vidal_ordonnance_services.find({"ordonnance_id": doc["id"]}, {"_id": 0}).to_list(50)
        resume = _resume_services(services, nb_lignes)
        await db.vidal_ordonnances.update_one({"id": doc["id"]}, {"$set": {"etat_service": resume["etat"], "dernier_service_at": _now(), "retour_lu": False}})
        return {"ok": True, "etat": resume["etat"], "libelle": resume["libelle"]}

    @api.get("/vidal/ordonnances", tags=["VIDAL"])
    async def mes_ordonnances(user: dict = Depends(get_current_user)):
        """Lot 57 — ordonnances du médecin connecté (100 dernières) avec le retour des officines."""
        docs = await db.vidal_ordonnances.find(
            {"user_id": user["id"]}, {"_id": 0, "qr_token": 0, "full_token": 0},
        ).sort("created_at", -1).to_list(100)
        ids = [d["id"] for d in docs]
        par_ordonnance: Dict[str, List[Dict[str, Any]]] = {}
        async for s in db.vidal_ordonnance_services.find({"ordonnance_id": {"$in": ids}}, {"_id": 0}).sort("date_service", 1):
            par_ordonnance.setdefault(s["ordonnance_id"], []).append(s)
        resultat = []
        for d in docs:
            services = par_ordonnance.get(d["id"], [])
            resultat.append({
                "id": d["id"], "reference": reference_ordonnance(d), "date": d.get("created_at"),
                "patient_name": d.get("patient_name"),
                "lignes": [l.get("label") for l in d.get("lines") or []],
                "services": _services_publics(services),
                "resume": _resume_services(services, len(d.get("lines") or [])),
                "retour_lu": d.get("retour_lu", True),
            })
        non_lus = sum(1 for r in resultat if not r["retour_lu"])
        return {"ordonnances": resultat, "retours_non_lus": non_lus, "statuts": STATUTS_LIGNE}

    @api.post("/vidal/ordonnances/retours-lus", tags=["VIDAL"])
    async def marquer_retours_lus(user: dict = Depends(get_current_user)):
        """Lot 57 — le médecin a consulté les retours : la pastille « nouveau » disparaît."""
        await db.vidal_ordonnances.update_many({"user_id": user["id"], "retour_lu": False}, {"$set": {"retour_lu": True}})
        return {"ok": True}

    @api.get("/vidal/ordonnances/{ordonnance_id}/pdf", tags=["VIDAL"])
    async def pdf_mon_ordonnance(ordonnance_id: str, user: dict = Depends(get_current_user)):
        """Lot 57 — aperçu (intégré à la page) d'une ordonnance déjà émise par ce médecin."""
        doc = await db.vidal_ordonnances.find_one({"id": ordonnance_id, "user_id": user["id"]}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Ordonnance introuvable")
        pdf = build_ordonnance_pdf(doc, anonymized=False, verify_url=_url_officine(doc["qr_token"]))
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="ordonnance-{reference_ordonnance(doc)}.pdf"'})

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
        pdf = build_ordonnance_pdf(doc, anonymized=False, verify_url=_url_officine(doc["qr_token"]))
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
