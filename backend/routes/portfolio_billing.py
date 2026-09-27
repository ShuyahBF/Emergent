"""Lot 27 — Facturation du portefeuille « Formulaires & Sondages WhatsApp » par client.

L'admin règle, dans la page SMART Communications de chaque client (tenant) :
  - les TARIFS : forfait mensuel, prix par formulaire actif, par sondage actif,
    par message WhatsApp envoyé, par réponse de sondage, par réponse de
    formulaire, par bilan avec analyse IA, et le taux de TVA ;
  - le PROMPT de l'analyse IA (un prompt par défaut est proposé).

En fin de période, il génère le BILAN du client :
  - chiffres de la période (formulaires, réponses, sondages, messages
    envoyés, taux de réponse, NPS, meilleurs contributeurs) ;
  - analyse rédigée par l'IA selon le prompt ;
  - lignes de facturation calculées avec les tarifs ;
  - PDF à livrer au client (lien public à jeton) ;
  - facture créée dans la Caisse/Facturation (émise par SAWALI au client).

Définitions (période = du … au …, jours inclus) :
  - formulaire actif : au moins une réponse reçue pendant la période ;
  - sondage actif : au moins un message envoyé ou une réponse pendant la période ;
  - message WhatsApp : invitation ou relance de sondage envoyée avec succès.

Collections : portfolio_billing (réglages par client), portfolio_reports (bilans).
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from routes.wa_surveys import compute_question_stats, in_period, rank_contributors

logger = logging.getLogger("sawali.portfolio_billing")

AI_MODEL = "claude-sonnet-5"
DEFAULT_PROMPT = (
    "Tu es consultant en relation client. À partir des statistiques ci-dessous (formulaires et "
    "sondages WhatsApp du client sur la période), rédige en français une analyse claire pour le "
    "dirigeant : 1) les chiffres clés en 3 phrases ; 2) les points forts ; 3) les points à améliorer "
    "(taux de réponse, insatisfactions, NPS, commentaires récurrents) ; 4) trois recommandations "
    "concrètes et chiffrées pour la période suivante. Reste factuel, n'invente aucun chiffre, "
    "utilise des titres courts (## ) et des listes à puces (- ). 400 mots maximum."
)
# Tarifs : clé -> libellé de la ligne de facture
TARIFFS = [
    ("monthly_fee", "Forfait mensuel — gestion du portefeuille formulaires & sondages", "mois"),
    ("per_active_form", "Formulaires actifs", "formulaire"),
    ("per_active_survey", "Sondages WhatsApp actifs", "sondage"),
    ("per_wa_message", "Messages WhatsApp envoyés (sondages)", "message"),
    ("per_survey_response", "Réponses aux sondages", "réponse"),
    ("per_form_submission", "Réponses aux formulaires", "réponse"),
    ("per_ai_report", "Bilan de période avec analyse IA", "bilan"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BillingSettings(BaseModel):
    enabled: bool = True
    monthly_fee: float = Field(0, ge=0)
    per_active_form: float = Field(0, ge=0)
    per_active_survey: float = Field(0, ge=0)
    per_wa_message: float = Field(0, ge=0)
    per_survey_response: float = Field(0, ge=0)
    per_form_submission: float = Field(0, ge=0)
    per_ai_report: float = Field(0, ge=0)
    tva_pct: float = Field(18, ge=0, le=100)
    ai_prompt: Optional[str] = Field(None, max_length=6000)
    due_days: int = Field(15, ge=0, le=180)            # échéance de la facture
    invoice_notes: Optional[str] = Field(None, max_length=1000)


class ReportRequest(BaseModel):
    date_from: str
    date_to: str
    with_ai: bool = True


class InvoiceRequest(BaseModel):
    kind: str = "invoice"                                # invoice | proforma
    apply_tva: Optional[bool] = None                     # choix du Superviseur pour CETTE facture (None = tarif du client)


# ---------------------------------------------------------------------------
# Fonctions pures (testées sans base)
# ---------------------------------------------------------------------------
def period_months(date_from: str, date_to: str) -> int:
    """Nombre de mois facturés pour le forfait : 1 par tranche de ~30 jours (au moins 1)."""
    d1 = date.fromisoformat(date_from[:10])
    d2 = date.fromisoformat(date_to[:10])
    days = (d2 - d1).days + 1
    return max(1, round(days / 30.4))


def billing_lines(settings: Dict[str, Any], metrics: Dict[str, Any], *, months: int, with_ai: bool) -> List[Dict[str, Any]]:
    """Lignes de facture (quantité × prix) à partir des tarifs et des chiffres de la période."""
    qty = {
        "monthly_fee": months,
        "per_active_form": metrics["forms"]["active"],
        "per_active_survey": metrics["surveys"]["active"],
        "per_wa_message": metrics["surveys"]["messages_sent"],
        "per_survey_response": metrics["surveys"]["responses"],
        "per_form_submission": metrics["forms"]["submissions"],
        "per_ai_report": 1 if with_ai else 0,
    }
    tva = float(settings.get("tva_pct") if settings.get("tva_pct") is not None else 18)
    lines = []
    for key, label, unit in TARIFFS:
        price = float(settings.get(key) or 0)
        q = qty[key]
        if price > 0 and q > 0:
            lines.append({"key": key, "label": label, "unit": unit, "quantity": q, "unit_price_ht": price,
                          "tva_pct": tva, "total_ht": round(q * price, 2)})
    return lines


def totals_of(lines: List[Dict[str, Any]]) -> Dict[str, float]:
    ht = sum(line["total_ht"] for line in lines)
    tva = sum(line["total_ht"] * line["tva_pct"] / 100 for line in lines)
    return {"total_ht": round(ht, 2), "total_tva": round(tva, 2), "total_ttc": round(ht + tva, 2)}


def _latin(text: str) -> str:
    """Texte affichable par la police PDF standard (émojis et symboles retirés)."""
    out = []
    for ch in str(text or ""):
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            out.append({"→": "->", "≥": ">=", "≤": "<=", "•": "-", "…": "..."}.get(ch, ""))
    return "".join(out)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def attach_portfolio_billing_routes(
    *,
    api,
    db,
    get_current_admin,
    uuid_fn: Callable[[], str],
    get_billing_manager=None,                     # admin ou Superviseur : bilans et factures
    public_base_url,                              # (request) -> str
    create_invoice_for_client=None,               # routes.cashier (hook)
    llm_send=None,                                # async (system, user_text) -> (texte, tokens)
    track_ai_usage=None,                          # routes.ai_quotas.track_ai_usage
) -> None:
    # Consulter les bilans et créer les factures : admin ET Superviseur (rôles système).
    # Les tarifs, le prompt et la génération des bilans restent à l'admin.
    manager = get_billing_manager or get_current_admin

    async def _client(cid: str) -> dict:
        u = await db.users.find_one({"id": cid}, {"_id": 0, "password_hash": 0})
        if not u:
            raise HTTPException(status_code=404, detail="Client introuvable")
        return u

    async def _settings(cid: str) -> Dict[str, Any]:
        doc = await db.portfolio_billing.find_one({"client_id": cid}, {"_id": 0}) or {}
        base = BillingSettings().model_dump()
        base.update({k: v for k, v in doc.items() if k in base})
        return base

    # ---- Réglages (tarifs + prompt) ---------------------------------------
    @api.get("/admin/clients/{cid}/portfolio-billing", tags=["Facturation portefeuille"])
    async def get_billing(cid: str, _: dict = Depends(get_current_admin)):
        await _client(cid)
        return {"settings": await _settings(cid), "default_prompt": DEFAULT_PROMPT,
                "tariffs": [{"key": k, "label": lbl, "unit": u} for k, lbl, u in TARIFFS]}

    @api.put("/admin/clients/{cid}/portfolio-billing", tags=["Facturation portefeuille"])
    async def put_billing(cid: str, payload: BillingSettings, admin: dict = Depends(get_current_admin)):
        await _client(cid)
        data = payload.model_dump()
        data["ai_prompt"] = (data.get("ai_prompt") or "").strip() or None      # vide = prompt par défaut
        await db.portfolio_billing.update_one(
            {"client_id": cid},
            {"$set": {**data, "client_id": cid, "updated_at": _now(), "updated_by": admin.get("email")}},
            upsert=True)
        return {"ok": True, "settings": await _settings(cid)}

    # ---- Chiffres de la période -------------------------------------------
    async def _metrics(cid: str, date_from: str, date_to: str) -> Dict[str, Any]:
        # Formulaires du client et réponses reçues pendant la période
        # Formulaires du client + formulaires partagés avec lui (« clients autorisés ») :
        # pour ces derniers, seules les réponses des utilisateurs du client comptent.
        forms = await db.forms.find({"$or": [{"client_id": cid}, {"access_client_ids": cid}]},
                                    {"_id": 0, "id": 1, "title": 1, "number": 1, "client_id": 1}).to_list(5000)
        own = {f["id"] for f in forms if f.get("client_id") == cid}
        fids = [f["id"] for f in forms]
        subs = await db.form_submissions.find({"form_id": {"$in": fids}},
                                              {"_id": 0, "form_id": 1, "client_id": 1, "created_at": 1}).to_list(None)
        subs = [x for x in subs if in_period(x.get("created_at"), date_from, date_to)
                and (x["form_id"] in own or x.get("client_id") == cid)]
        per_form: Dict[str, int] = {}
        for x in subs:
            per_form[x["form_id"]] = per_form.get(x["form_id"], 0) + 1
        form_rows = sorted(({"title": f["title"], "number": f.get("number"), "submissions": per_form.get(f["id"], 0)}
                            for f in forms if per_form.get(f["id"])), key=lambda r: -r["submissions"])
        # Sondages : messages envoyés (envois et relances), réponses, taux
        surveys = await db.wa_surveys.find({"client_id": cid}, {"_id": 0}).to_list(5000)
        sids = [s["id"] for s in surveys]
        camps = await db.wa_survey_campaigns.find({"survey_id": {"$in": sids}},
                                                   {"_id": 0, "survey_id": 1, "sent_ok": 1, "created_at": 1}).to_list(None)
        camps = [c for c in camps if in_period(c.get("created_at"), date_from, date_to)]
        responses = await db.wa_survey_responses.find({"survey_id": {"$in": sids}}, {"_id": 0}).to_list(None)
        responses = [r for r in responses if in_period(r.get("created_at"), date_from, date_to)]
        invites = await db.wa_survey_invites.find({"survey_id": {"$in": sids}}, {"_id": 0}).to_list(None)
        sent_by: Dict[str, int] = {}
        for c in camps:
            sent_by[c["survey_id"]] = sent_by.get(c["survey_id"], 0) + int(c.get("sent_ok") or 0)
        resp_by: Dict[str, List[dict]] = {}
        for r in responses:
            resp_by.setdefault(r["survey_id"], []).append(r)
        survey_rows = []
        for s in surveys:
            sent = sent_by.get(s["id"], 0)
            rs = resp_by.get(s["id"], [])
            if not sent and not rs:
                continue
            stats = compute_question_stats(s.get("questions") or [], rs, bool(s.get("anonymous")))
            nps = next((q.get("nps") for q in stats if q["type"] == "nps" and q.get("nps") is not None), None)
            survey_rows.append({"title": s["title"], "messages_sent": sent, "responses": len(rs),
                                "response_rate": round(100 * len(rs) / sent, 1) if sent else None,
                                "nps": nps, "questions": stats})
        survey_rows.sort(key=lambda r: -r["responses"])
        period_invites = [i for i in invites if in_period(i.get("answered_at") or i.get("last_sent_at"), date_from, date_to)]
        period_invites = [{**i, "answered_at": i.get("answered_at") if in_period(i.get("answered_at"), date_from, date_to) else None}
                          for i in period_invites]
        anonymous = {s["id"] for s in surveys if s.get("anonymous")}
        contributors = rank_contributors([i for i in period_invites if i["survey_id"] not in anonymous], 10)
        total_sent = sum(sent_by.values())
        return {
            "forms": {"total": len(forms), "active": len(form_rows), "submissions": len(subs), "items": form_rows[:30]},
            "surveys": {"total": len(surveys), "active": len(survey_rows), "messages_sent": total_sent,
                        "responses": len(responses),
                        "response_rate": round(100 * len(responses) / total_sent, 1) if total_sent else None,
                        "items": survey_rows[:30]},
            "contributors": [{k: c.get(k) for k in ("rank", "name", "company", "answered", "response_rate", "avg_delay_hours")}
                             for c in contributors],
        }

    # ---- Analyse IA -------------------------------------------------------
    async def _default_llm(system_text: str, user_text: str):
        from emergentintegrations.llm.chat import LlmChat, UserMessage   # import local : dépendance lourde
        key = os.environ.get("EMERGENT_LLM_KEY")
        if not key:
            raise HTTPException(status_code=503, detail="Clé IA absente (EMERGENT_LLM_KEY)")
        chat = LlmChat(api_key=key, session_id=f"bilan-{secrets.token_hex(6)}", system_message=system_text).with_model("anthropic", AI_MODEL)
        reply = await chat.send_message(UserMessage(text=user_text))
        return reply or "", max(1, int((len(system_text) + len(user_text) + len(reply or "")) / 4))

    def _ai_input(client: dict, date_from: str, date_to: str, m: Dict[str, Any]) -> str:
        """Statistiques compactes envoyées à l'IA (pas de numéros de téléphone)."""
        surveys = []
        for s in m["surveys"]["items"][:10]:
            qs = []
            for q in s["questions"]:
                item = {"question": q["label"], "type": q["type"], "reponses": q["answered"]}
                if q.get("options"):
                    item["repartition"] = {o["label"]: f"{o['pct']} %" for o in q["options"]}
                for k in ("average", "nps", "promoters", "passives", "detractors"):
                    if q.get(k) is not None:
                        item[k] = q[k]
                if q["type"] == "text":
                    item["commentaires"] = [a["text"][:300] for a in (q.get("answers") or [])[:25]]
                qs.append(item)
            surveys.append({"sondage": s["title"], "messages_envoyes": s["messages_sent"], "reponses": s["responses"],
                            "taux_reponse": s["response_rate"], "questions": qs})
        data = {
            "client": client.get("company") or client.get("full_name"),
            "periode": f"du {date_from} au {date_to}",
            "formulaires": {"total": m["forms"]["total"], "actifs": m["forms"]["active"],
                            "reponses": m["forms"]["submissions"], "detail": m["forms"]["items"][:15]},
            "sondages": {"total": m["surveys"]["total"], "actifs": m["surveys"]["active"],
                         "messages_envoyes": m["surveys"]["messages_sent"], "reponses": m["surveys"]["responses"],
                         "taux_reponse": m["surveys"]["response_rate"], "detail": surveys},
            "meilleurs_contributeurs": [{"rang": c["rank"], "reponses": c["answered"], "taux": c["response_rate"]}
                                        for c in m["contributors"][:5]],
        }
        return json.dumps(data, ensure_ascii=False, indent=1)

    # ---- Bilans -----------------------------------------------------------
    @api.post("/admin/clients/{cid}/portfolio-reports", tags=["Facturation portefeuille"])
    async def create_report(cid: str, payload: ReportRequest, request: Request, admin: dict = Depends(get_current_admin)):
        client = await _client(cid)
        try:
            d1, d2 = date.fromisoformat(payload.date_from[:10]), date.fromisoformat(payload.date_to[:10])
        except ValueError:
            raise HTTPException(status_code=400, detail="Dates invalides (AAAA-MM-JJ)")
        if d2 < d1:
            raise HTTPException(status_code=400, detail="La date de fin précède la date de début")
        settings = await _settings(cid)
        metrics = await _metrics(cid, d1.isoformat(), d2.isoformat())
        analysis, ai_error = None, None
        if payload.with_ai:
            prompt = settings.get("ai_prompt") or DEFAULT_PROMPT
            try:
                analysis, tokens = await (llm_send or _default_llm)(prompt, _ai_input(client, d1.isoformat(), d2.isoformat(), metrics))
                if track_ai_usage:
                    try:
                        await track_ai_usage(db, user=admin, resource="chat", units=tokens, model=AI_MODEL,
                                             metadata={"feature": "portfolio_report", "client_id": cid})
                    except Exception:  # noqa: BLE001
                        logger.warning("[bilan] suivi de consommation IA impossible", exc_info=True)
            except HTTPException as exc:
                ai_error = str(exc.detail)
            except Exception as exc:  # noqa: BLE001
                ai_error = f"Analyse IA indisponible : {str(exc)[:200]}"
        with_ai = bool(analysis)
        lines = billing_lines(settings, metrics, months=period_months(d1.isoformat(), d2.isoformat()), with_ai=with_ai)
        doc = {
            "id": uuid_fn(), "client_id": cid,
            "client_name": client.get("company") or client.get("full_name") or client.get("email"),
            "date_from": d1.isoformat(), "date_to": d2.isoformat(),
            "metrics": metrics, "analysis": analysis, "ai_error": ai_error, "with_ai": with_ai,
            "lines": lines, **totals_of(lines), "tva_pct": settings.get("tva_pct"),
            "billing_enabled": bool(settings.get("enabled")),
            "token": secrets.token_urlsafe(18),
            "base_url": (public_base_url(request) or "").rstrip("/"),
            "invoice_id": None, "invoice_number": None,
            "created_by": admin.get("email"), "created_at": _now(),
        }
        await db.portfolio_reports.insert_one(doc.copy())
        return doc

    @api.get("/admin/clients/{cid}/portfolio-reports", tags=["Facturation portefeuille"])
    async def list_reports(cid: str, _: dict = Depends(get_current_admin)):
        items = await db.portfolio_reports.find({"client_id": cid}, {"_id": 0, "metrics": 0}).sort("created_at", -1).to_list(100)
        return {"items": items}

    @api.get("/admin/portfolio-reports", tags=["Facturation portefeuille"])
    async def list_all_reports(status: Optional[str] = None, _: dict = Depends(manager)):
        """Bilans de tous les clients (page « Bilans à facturer ») : à facturer, facturés ou tous."""
        q: Dict[str, Any] = {}
        if status == "to_invoice":
            q = {"invoice_id": None, "total_ttc": {"$gt": 0}}
        elif status == "invoiced":
            q = {"invoice_id": {"$ne": None}}
        items = await db.portfolio_reports.find(q, {"_id": 0, "metrics": 0, "analysis": 0}).sort("created_at", -1).to_list(500)
        return {"items": items}

    @api.get("/admin/portfolio-reports/{rid}", tags=["Facturation portefeuille"])
    async def get_report(rid: str, _: dict = Depends(manager)):
        r = await db.portfolio_reports.find_one({"id": rid}, {"_id": 0})
        if not r:
            raise HTTPException(status_code=404, detail="Bilan introuvable")
        return r

    @api.delete("/admin/portfolio-reports/{rid}", tags=["Facturation portefeuille"])
    async def delete_report(rid: str, _: dict = Depends(get_current_admin)):
        await db.portfolio_reports.delete_one({"id": rid})
        return {"ok": True}

    @api.post("/admin/portfolio-reports/{rid}/invoice", tags=["Facturation portefeuille"])
    async def invoice_report(rid: str, payload: InvoiceRequest, admin: dict = Depends(manager)):
        r = await db.portfolio_reports.find_one({"id": rid}, {"_id": 0})
        if not r:
            raise HTTPException(status_code=404, detail="Bilan introuvable")
        if r.get("invoice_id") and payload.kind == "invoice":
            raise HTTPException(status_code=409, detail=f"Ce bilan est déjà facturé ({r.get('invoice_number')})")
        if not r.get("lines"):
            raise HTTPException(status_code=400, detail="Rien à facturer : aucun tarif ne s'applique à cette période")
        if not create_invoice_for_client:
            raise HTTPException(status_code=503, detail="Caisse/Facturation indisponible")
        settings = await _settings(r["client_id"])
        client = await _client(r["client_id"])
        period = f"du {datetime.fromisoformat(r['date_from']).strftime('%d/%m/%Y')} au {datetime.fromisoformat(r['date_to']).strftime('%d/%m/%Y')}"
        # TVA : décidée pour chaque facture par le Superviseur (ou l'admin) ; par défaut, taux du client
        apply_tva = payload.apply_tva if payload.apply_tva is not None else float(r.get("tva_pct") or 0) > 0
        items = [{"label": f"{ln['label']} — {period}", "quantity": ln["quantity"], "unit_price_ht": ln["unit_price_ht"],
                  "tva_pct": (ln["tva_pct"] if apply_tva else 0), "unit": ln["unit"]} for ln in r["lines"]]
        due = (datetime.now(timezone.utc) + timedelta(days=int(settings.get("due_days") or 15))).date().isoformat()
        notes = settings.get("invoice_notes") or f"Bilan Formulaires & Sondages WhatsApp {period}."
        inv = await create_invoice_for_client(admin, client, items, notes=notes, due_date=due, kind=payload.kind)
        if payload.kind == "invoice":
            await db.portfolio_reports.update_one({"id": rid}, {"$set": {"invoice_id": inv["id"], "invoice_number": inv["number"],
                                                                         "invoiced_at": _now(), "invoiced_with_tva": apply_tva,
                                                                         "invoiced_amount": inv.get("net_to_pay"),
                                                                         "invoiced_by": admin.get("email")}})
        return {"ok": True, "apply_tva": apply_tva,
                "invoice": {k: inv.get(k) for k in ("id", "number", "kind", "net_to_pay", "total_tva", "due_date", "qr_url")}}

    # ---- PDF --------------------------------------------------------------
    def _pdf(r: Dict[str, Any]) -> bytes:
        from reportlab.graphics.charts.barcharts import HorizontalBarChart
        from reportlab.graphics.shapes import Drawing
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        navy, blue = colors.HexColor("#0E1F3D"), colors.HexColor("#1E90FF")
        st = {
            "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=17, textColor=navy, leading=21),
            "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#64748B"), leading=13),
            "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5, textColor=blue, spaceBefore=10, spaceAfter=4),
            "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10.5, textColor=navy, spaceBefore=6, spaceAfter=2),
            "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13),
            "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=9.5, leading=13, leftIndent=10, bulletIndent=2),
        }

        def esc(t):
            t = _latin(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)

        def table(rows, widths, header=True):
            t = Table(rows, colWidths=widths, hAlign="LEFT")
            style = [("FONT", (0, 0), (-1, -1), "Helvetica", 8.8), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                     ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")])]
            if header:
                style += [("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                          ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.8)]
            t.setStyle(TableStyle(style))
            return t

        def pct(v):
            # Pourcentage à la française : 66,7 %
            return f"{v:g} %".replace(".", ",")

        def money(v):
            return f"{v:,.0f}".replace(",", " ") + " FCFA"

        m = r["metrics"]
        fmt = lambda d: datetime.fromisoformat(d).strftime("%d/%m/%Y")  # noqa: E731
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                                title=f"Bilan {r['client_name']}", author="SAWALI SMART SYSTEMS")
        el = [Paragraph(esc("Bilan Formulaires & Sondages WhatsApp"), st["h1"]),
              Paragraph(esc(f"{r['client_name']} — période du {fmt(r['date_from'])} au {fmt(r['date_to'])}"), st["sub"]),
              Spacer(1, 8)]
        # Chiffres clés
        s, f = m["surveys"], m["forms"]
        kpi = [["Sondages actifs", "Messages envoyés", "Réponses sondages", "Taux de réponse", "Formulaires actifs", "Réponses formulaires"],
               [str(s["active"]), str(s["messages_sent"]), str(s["responses"]),
                "—" if s["response_rate"] is None else pct(s['response_rate']), str(f["active"]), str(f["submissions"])]]
        k = table(kpi, [29 * mm] * 6)
        k.setStyle(TableStyle([("FONT", (0, 1), (-1, 1), "Helvetica-Bold", 14), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                               ("TEXTCOLOR", (0, 1), (-1, 1), blue), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5)]))
        el += [k]
        # Sondages : tableau + graphique des taux de réponse
        if s["items"]:
            el.append(Paragraph("Sondages WhatsApp", st["h2"]))
            rows = [["Sondage", "Envoyés", "Réponses", "Taux", "NPS"]]
            for it in s["items"]:
                rows.append([Paragraph(esc(it["title"]), st["body"]), it["messages_sent"], it["responses"],
                             "—" if it["response_rate"] is None else pct(it['response_rate']),
                             "—" if it["nps"] is None else f"{it['nps']:+d}"])
            el.append(table(rows, [86 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm]))
            rated = [it for it in s["items"][:8] if it["response_rate"] is not None]
            if rated:
                h = 14 + 14 * len(rated)
                d = Drawing(178 * mm, h * 1.25)
                ch = HorizontalBarChart()
                ch.x, ch.y, ch.width, ch.height = 55 * mm, 6, 110 * mm, h
                ch.data = [[min(100, it["response_rate"]) for it in rated]]
                ch.categoryAxis.categoryNames = [_latin(it["title"])[:32] for it in rated]
                ch.categoryAxis.labels.fontName = "Helvetica"
                ch.categoryAxis.labels.fontSize = 7
                ch.valueAxis.valueMin, ch.valueAxis.valueMax, ch.valueAxis.valueStep = 0, 100, 20
                ch.valueAxis.labels.fontSize = 7
                ch.bars[0].fillColor = colors.HexColor("#10B981")
                d.add(ch)
                el += [Spacer(1, 4), Paragraph("Taux de réponse par sondage (%)", st["h3"]), d]
        if f["items"]:
            el.append(Paragraph("Formulaires", st["h2"]))
            rows = [["Formulaire", "N°", "Réponses"]] + [[Paragraph(esc(it["title"]), st["body"]), it.get("number") or "", it["submissions"]]
                                                        for it in f["items"]]
            el.append(table(rows, [110 * mm, 40 * mm, 24 * mm]))
        if m["contributors"]:
            el.append(Paragraph("Meilleurs contributeurs", st["h2"]))
            rows = [["#", "Contact", "Entreprise", "Réponses", "Taux"]] + [
                [c["rank"], Paragraph(esc(c["name"]), st["body"]), Paragraph(esc(c.get("company") or ""), st["body"]),
                 c["answered"], pct(c['response_rate'])] for c in m["contributors"]]
            el.append(table(rows, [10 * mm, 62 * mm, 62 * mm, 20 * mm, 20 * mm]))
        # Analyse IA (titres « ## », puces « - », gras « ** »)
        if r.get("analysis"):
            el.append(Paragraph("Analyse", st["h2"]))
            for line in r["analysis"].splitlines():
                t = line.strip()
                if not t:
                    continue
                if t.startswith("#"):
                    el.append(Paragraph(esc(t.lstrip("# ")), st["h3"]))
                elif t[:2] in ("- ", "* ", "• "):
                    el.append(Paragraph(esc(t[2:]), st["bullet"], bulletText="•"))
                else:
                    el.append(Paragraph(esc(t), st["body"]))
        # Facturation de la période
        if r.get("lines"):
            el.append(Paragraph("Facturation de la période", st["h2"]))
            rows = [["Désignation", "Qté", "Prix unitaire HT", "Total HT"]] + [
                [Paragraph(esc(ln["label"]), st["body"]), ln["quantity"], money(ln["unit_price_ht"]), money(ln["total_ht"])] for ln in r["lines"]]
            rows += [["", "", "Total HT", money(r["total_ht"])], ["", "", f"TVA {r.get('tva_pct') or 0:g} %", money(r["total_tva"])],
                     ["", "", "Total TTC", money(r["total_ttc"])]]
            t = table(rows, [92 * mm, 16 * mm, 34 * mm, 32 * mm])
            t.setStyle(TableStyle([("FONT", (2, -1), (-1, -1), "Helvetica-Bold", 9.5), ("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
            el.append(t)
            if r.get("invoice_number"):
                el.append(Paragraph(esc(f"Facture n° {r['invoice_number']}"), st["sub"]))
        el += [Spacer(1, 10), Paragraph(esc(f"Document généré le {datetime.now(timezone.utc).strftime('%d/%m/%Y')} par SAWALI SMART SYSTEMS."), st["sub"])]
        doc.build(el)
        return buf.getvalue()

    def _pdf_response(r: Dict[str, Any], pdf: bytes) -> Response:
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", f"Bilan_{r['client_name']}_{r['date_from']}_{r['date_to']}")[:90]
        return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})

    @api.get("/admin/portfolio-reports/{rid}/pdf", tags=["Facturation portefeuille"])
    async def report_pdf(rid: str, _: dict = Depends(manager)):
        import asyncio
        r = await get_report(rid, _)
        return _pdf_response(r, await asyncio.to_thread(_pdf, r))          # PDF construit hors de la boucle

    @api.get("/public/portfolio-report/{token}", tags=["Facturation portefeuille"])
    async def public_report_pdf(token: str):
        """Lien à transmettre au client : le PDF du bilan, sans compte."""
        import asyncio
        r = await db.portfolio_reports.find_one({"token": token}, {"_id": 0})
        if not r:
            raise HTTPException(status_code=404, detail="Bilan introuvable")
        return _pdf_response(r, await asyncio.to_thread(_pdf, r))
