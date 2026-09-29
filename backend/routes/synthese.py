"""Iter41 Phase 3 (2026-02) — Synthèse Liluvine programmée

Two entry points :
  1. **Scheduled cron** (registered by `server.py` APScheduler) at the
     `synthese_hour` configured in AdminSettings. Generates the daily synthèse
     and dispatches to email + WhatsApp depending on `synthese_channels`.
  2. **WhatsApp command** `!synthese [début] [fin]` — manual on-demand
     synthèse for a date range (default = today).

Lot 41 — la synthèse inclut les FORMULAIRES et SONDAGES : nouvelles soumissions et réponses
de la période (avec les formulaires / sondages concernés) et les commandes WhatsApp
« !formulaire » (reçues, mises en ligne AUTO ou FORCÉ, en attente de paiement, en erreur).
Ce bloc est donné à Liluvine ET ajouté tel quel à la fin du message (chiffres garantis).

Date parsing accepts (case-insensitive) :
  - ISO (`AAAA-MM-JJ`)
  - French (`JJ/MM/AAAA`)
  - Keywords : `aujourd'hui`, `hier`, `semaine`, `mois`
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sawali.synthese")


SYNTHESE_CMD_RE = re.compile(r"^[!/]\s*synth[èe]se(?:\s+(.+))?\s*$", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Date parsing
# --------------------------------------------------------------------------- #
def _parse_date_token(token: str, fallback: date) -> date:
    """Parse a single date token. Returns `fallback` on any failure."""
    if not token:
        return fallback
    t = token.strip().lower()
    today = date.today()
    if t in ("aujourd'hui", "aujourdhui", "today"):
        return today
    if t in ("hier", "yesterday"):
        return today - timedelta(days=1)
    if t in ("semaine", "week"):
        return today - timedelta(days=7)
    if t in ("mois", "month"):
        return today - timedelta(days=30)
    # ISO YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return fallback
    # French JJ/MM/AAAA
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", t)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return fallback
    return fallback


def parse_synthese_args(arg_string: str) -> Tuple[date, date]:
    """Parse `[début] [fin]` arguments. Returns (start, end) — both
    default to today when missing/invalid."""
    today = date.today()
    if not arg_string:
        return today, today
    parts = arg_string.strip().split()
    if len(parts) == 1:
        d = _parse_date_token(parts[0], today)
        return d, d
    start = _parse_date_token(parts[0], today)
    end = _parse_date_token(parts[1], start)
    if end < start:
        start, end = end, start
    return start, end


# --------------------------------------------------------------------------- #
# Context builder (hybrid : prompt + structured KPIs)
# --------------------------------------------------------------------------- #
async def _gather_kpis(db, scope_uid: str, start: date, end: date) -> Dict[str, Any]:
    """Aggregate a small structured snapshot of the activity for the given
    date range. Designed to be cheap (single-tenant scope, count_documents).

    Iter43-fix24az (2026-02-26) — Fixed the collection / field names that
    were silently returning 0 across the board:
      - tickets         → support_tickets   (field `opened_at`, not `created_at`)
      - sms_outbox      → sms_messages
      - wa_outbox       → whatsapp_messages
      - suivis          → user_suivis
      - payments        → payment_transactions
      - bird_sms        → bird_sms_messages (new dedicated counter)
    """
    start_iso = start.isoformat()
    end_iso = (end + timedelta(days=1)).isoformat()  # exclusive upper bound
    kpi: Dict[str, Any] = {"period": {"start": start_iso, "end": end_iso}}

    async def _count(col: str, query: Dict[str, Any]) -> int:
        try:
            return await db[col].count_documents(query)
        except Exception:  # noqa: BLE001
            return 0

    # Common date filter on created_at strings (ISO format as stored in Mongo).
    drange_field = {"$gte": start_iso, "$lt": end_iso}
    drange = {"created_at": drange_field}
    # Tickets use `opened_at`, not `created_at`.
    drange_tickets = {"opened_at": drange_field}
    tenant_filter = {"client_id": scope_uid} if scope_uid else {}
    full = {**tenant_filter, **drange}
    full_tickets = {**tenant_filter, **drange_tickets}

    kpi["counts"] = {
        "new_contacts": await _count("directory_contacts", full),
        "new_tickets": await _count("support_tickets", full_tickets),
        "appointments": await _count("appointments", full),
        "rapports": await _count("rapports", full),
        "suivis": await _count("user_suivis", full),
        "sms_sent": await _count("sms_messages", full),
        "wa_sent": await _count("whatsapp_messages", full),
        "bird_sms_sent": await _count("bird_sms_messages", full),
        "invoices": await _count("invoices", full),
        "payments": await _count("payment_transactions", full),
    }
    kpi["formulaires_sondages"] = await _formulaires_sondages(db, scope_uid, start_iso, end_iso)
    # Last 5 tickets summary (uses opened_at).
    try:
        cursor = db.support_tickets.find(full_tickets, {"_id": 0}).sort("opened_at", -1).limit(5)
        tickets = []
        async for t in cursor:
            tickets.append({
                "id": t.get("id") or t.get("number"),
                "title": t.get("title") or t.get("motif"),
                "status": t.get("status"),
                "opened_at": t.get("opened_at") or t.get("created_at"),
            })
        kpi["recent_tickets"] = tickets
    except Exception:  # noqa: BLE001
        kpi["recent_tickets"] = []
    return kpi


async def _formulaires_sondages(db, scope_uid: str, start_iso: str, end_iso: str) -> Dict[str, Any]:
    """Lot 41 — données reçues sur les formulaires et sondages pendant la période
    (soumission nouvelle ou modifiée), et commandes « !formulaire »."""
    periode = {"$gte": start_iso, "$lt": end_iso}
    recu = {"$or": [{"created_at": periode}, {"updated_at": periode}]}
    res: Dict[str, Any] = {"soumissions": 0, "reponses": 0, "formulaires": [], "sondages": [],
                           "commandes": {"recues": 0, "auto": 0, "force": 0, "attente_paiement": 0, "erreurs": 0}}
    try:
        for coll_items, coll_data, cle, champ_n, champ_l in (
                ("forms", "form_submissions", "form_id", "soumissions", "formulaires"),
                ("wa_surveys", "wa_survey_responses", "survey_id", "reponses", "sondages")):
            q_items = {"client_id": scope_uid} if scope_uid else {}
            titres = {x["id"]: x.get("title") or x["id"] async for x in db[coll_items].find(
                q_items, {"_id": 0, "id": 1, "title": 1})}
            if not titres:
                continue
            lignes = []
            async for g in db[coll_data].aggregate([
                    {"$match": {cle: {"$in": list(titres)}, **recu}},
                    {"$group": {"_id": f"${cle}", "n": {"$sum": 1}}}]):
                lignes.append({"titre": titres.get(g["_id"], g["_id"]), "n": g["n"]})
            lignes.sort(key=lambda x: -x["n"])
            res[champ_n] = sum(x["n"] for x in lignes)
            res[champ_l] = lignes[:10]
        q_cmd = {"compte_id": scope_uid} if scope_uid else {}
        c = res["commandes"]
        c["recues"] = await db.liluvine_formulaires.count_documents({**q_cmd, "cree_le": periode,
                                                                     "statut": {"$ne": "mode_emploi"}})
        async for x in db.liluvine_formulaires.find({**q_cmd, "statut": "publie", "publie_le": periode},
                                                   {"_id": 0, "mode_realisation": 1}):
            c["force" if x.get("mode_realisation") == "force" else "auto"] += 1
        c["attente_paiement"] = await db.liluvine_formulaires.count_documents({**q_cmd, "statut": "en_attente_paiement"})
        c["erreurs"] = await db.liluvine_formulaires.count_documents({**q_cmd, "statut": "erreur", "cree_le": periode})
    except Exception:  # noqa: BLE001 — la synthèse part même si ce bloc échoue
        logger.warning("[synthese] bloc formulaires/sondages indisponible", exc_info=True)
    return res


def bloc_formulaires_sondages(kpis: Dict[str, Any]) -> str:
    """Lot 41 — bloc texte « Formulaires & sondages » (WhatsApp / email), chiffres exacts."""
    fs = kpis.get("formulaires_sondages") or {}
    if not fs:
        return ""
    c = fs.get("commandes") or {}
    lignes = ["📋 *Formulaires & sondages*",
              f"🟢 Formulaires : {fs.get('soumissions', 0)} soumission(s) reçue(s)"]
    lignes += [f"   • {x['titre']} : {x['n']}" for x in fs.get("formulaires") or []]
    lignes.append(f"🔵 Sondages : {fs.get('reponses', 0)} réponse(s) reçue(s)")
    lignes += [f"   • {x['titre']} : {x['n']}" for x in fs.get("sondages") or []]
    lignes.append(f"🤖 !formulaire : {c.get('recues', 0)} reçue(s), mises en ligne {c.get('auto', 0)} AUTO / "
                  f"{c.get('force', 0)} FORCÉ, {c.get('attente_paiement', 0)} en attente de paiement, "
                  f"{c.get('erreurs', 0)} en erreur")
    return "\n".join(lignes)


def _build_prompt(custom_prompt: str, kpis: Dict[str, Any], start: date, end: date) -> str:
    """Combine the user's custom prompt with the structured KPI block.

    Iter43-fix24az — render the KPIs as a clean bullet list instead of a
    raw Python dict literal. The previous formatting was so ambiguous that
    Liluvine often rounded everything down to 0 in the synthese."""
    base = custom_prompt or (
        "Tu es Liluvine. Synthétise l'activité de l'établissement sur la période "
        "indiquée en 5-8 puces actionnables. Mets en gras les points critiques."
    )
    period_label = f"du {start.isoformat()} au {end.isoformat()}" if start != end else f"le {start.isoformat()}"

    counts = kpis.get("counts") or {}
    # Friendly French labels (only for known keys; unknown keys fall through
    # raw so we don't silently lose any new KPI).
    LABELS = {
        "new_contacts": "Nouveaux contacts",
        "new_tickets": "Nouveaux tickets",
        "appointments": "Rendez-vous",
        "rapports": "Rapports",
        "suivis": "Suivis",
        "sms_sent": "SMS envoyés (Meta / legacy)",
        "wa_sent": "Messages WhatsApp",
        "bird_sms_sent": "SMS envoyés (Bird)",
        "invoices": "Factures",
        "payments": "Paiements",
    }
    counts_lines = "\n".join(
        f"  • {LABELS.get(k, k)} : {v}" for k, v in counts.items()
    ) or "  (aucune donnée)"

    tickets = kpis.get("recent_tickets") or []
    if tickets:
        tickets_lines = "\n".join(
            f"  • #{t.get('id','')} — {t.get('title','(sans titre)')} ({t.get('status','?')})"
            for t in tickets
        )
    else:
        tickets_lines = "  (aucun ticket sur la période)"

    return (
        f"{base}\n\n"
        f"[CONTEXTE STRUCTURÉ — {period_label}]\n"
        f"Indicateurs :\n{counts_lines}\n\n"
        f"5 derniers tickets :\n{tickets_lines}\n\n"
        f"{bloc_formulaires_sondages(kpis)}\n"
        f"[FIN CONTEXTE]\n\n"
        f"Consacre une puce aux formulaires et sondages (données reçues, commandes !formulaire AUTO / FORCÉ).\n"
        f"Génère la synthèse en français, en t'appuyant sur les chiffres ci-dessus. "
        f"N'invente PAS de chiffres : utilise ceux fournis. Si une catégorie est à 0, mentionne-le explicitement."
    )


async def _call_liluvine(db, full_prompt: str) -> str:
    """Send the synthèse prompt to Liluvine and return the plain-text reply."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        import os
        api_key = os.environ.get("EMERGENT_LLM_KEY")
        if not api_key:
            return "❌ EMERGENT_LLM_KEY absent — impossible de générer la synthèse."
        chat = (
            LlmChat(api_key=api_key, session_id="synthese-cron", system_message="Tu es Liluvine, assistante SAWALI.")
            .with_model("anthropic", "claude-sonnet-4-5-20250929")
        )
        msg = UserMessage(text=full_prompt)
        reply = await chat.send_message(msg)
        return str(reply)[:5000]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[synthese] LLM call failed", exc_info=True)
        return f"❌ Erreur génération synthèse : {str(exc)[:200]}"


# --------------------------------------------------------------------------- #
# Public helpers
# --------------------------------------------------------------------------- #
async def build_synthese(db, *, start: date, end: date, scope_uid: Optional[str] = None) -> str:
    """Generate a synthèse text for the given period. Used by both the cron
    and the WhatsApp command."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "synthese_prompt": 1}) or {}
    kpis = await _gather_kpis(db, scope_uid or "", start, end)
    prompt = _build_prompt(s.get("synthese_prompt") or "", kpis, start, end)
    texte = await _call_liluvine(db, prompt)
    bloc = bloc_formulaires_sondages(kpis)                  # lot 41 : chiffres exacts ajoutés tels quels
    return f"{texte}\n\n{bloc}" if bloc else texte


async def detect_and_handle_synthese_command(
    db, *, message_text: str, from_phone: str,
) -> Optional[Dict[str, Any]]:
    """Returns None if not a !synthese command, otherwise {ok, user_reply}."""
    m = SYNTHESE_CMD_RE.match(message_text or "")
    if not m:
        return None
    args = (m.group(1) or "").strip()
    start, end = parse_synthese_args(args)
    text = await build_synthese(db, start=start, end=end)
    period = f"{start.isoformat()} → {end.isoformat()}" if start != end else start.isoformat()
    return {
        "ok": True, "command": "synthese",
        "user_reply": f"📊 *Synthèse {period}*\n\n{text}",
        "period": {"start": start.isoformat(), "end": end.isoformat()},
    }


async def _dispatch_email(db, body: str) -> bool:
    """Send the synthèse by email. Returns True on success."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    to = (s.get("synthese_email_to") or "").strip()
    if not to:
        return False
    try:
        # Reuse the platform's existing email helper if available
        from routes.email_outbox import send_email_simple  # type: ignore
        await send_email_simple(
            to=to,
            subject=f"📊 Synthèse SAWALI — {datetime.now(timezone.utc).strftime('%d/%m/%Y')}",
            html=f"<pre style='font-family:monospace;white-space:pre-wrap'>{body}</pre>",
        )
        return True
    except Exception:  # noqa: BLE001
        logger.warning("[synthese] email dispatch failed", exc_info=True)
        return False


async def _dispatch_wa(db, body: str) -> bool:
    """Send the synthèse over WhatsApp to the configured number."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    to = (s.get("synthese_wa_to") or "").strip()
    if not to:
        return False
    try:
        # Use the bare-bones WA sender exposed by server.py
        import importlib
        srv = importlib.import_module("server")
        send = getattr(srv, "_wa_send_text", None)
        if not send:
            return False
        await send(to, body[:4000])  # WA caps around 4096 chars
        return True
    except Exception:  # noqa: BLE001
        logger.warning("[synthese] WA dispatch failed", exc_info=True)
        return False


async def run_scheduled_synthese(db) -> Dict[str, Any]:
    """Top-level cron — checks enabled flag and dispatches. Idempotent."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    if not s.get("synthese_enabled"):
        return {"skipped": True, "reason": "synthese disabled"}
    channels = (s.get("synthese_channels") or "both").lower()
    today = date.today()
    body = await build_synthese(db, start=today, end=today)
    sent_email = False
    sent_wa = False
    if channels in ("email", "both"):
        sent_email = await _dispatch_email(db, body)
    if channels in ("wa", "both"):
        sent_wa = await _dispatch_wa(db, body)
    return {
        "ok": True,
        "channels": channels,
        "sent_email": sent_email,
        "sent_wa": sent_wa,
        "preview": body[:300],
    }


async def run_synthese_test(db) -> Dict[str, Any]:
    """Iter42b — Test à la demande de la synthèse Liluvine.

    Force l'envoi (même si `synthese_enabled` est False) en utilisant la
    configuration courante. Retourne un payload détaillé pour l'admin.

    Iter43-fix24az — renvoie aussi les `kpis` calculés pour que l'admin
    puisse vérifier les chiffres bruts (ce qui était impossible avant et
    masquait le bug des noms de collection).
    """
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    channels = (s.get("synthese_channels") or "both").lower()
    today = date.today()
    kpis = await _gather_kpis(db, "", today, today)
    prompt = _build_prompt(s.get("synthese_prompt") or "", kpis, today, today)
    body = await _call_liluvine(db, prompt)
    bloc = bloc_formulaires_sondages(kpis)                  # lot 41
    if bloc:
        body = f"{body}\n\n{bloc}"
    sent_email = False
    sent_wa = False
    errors: list = []
    if channels in ("email", "both"):
        try:
            sent_email = await _dispatch_email(db, body)
            if not sent_email:
                errors.append("Email non envoyé (email destinataire vide ou SMTP non configuré)")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Email error: {str(exc)[:200]}")
    if channels in ("wa", "both"):
        try:
            sent_wa = await _dispatch_wa(db, body)
            if not sent_wa:
                errors.append("WhatsApp non envoyé (numéro vide ou WA non configuré)")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"WhatsApp error: {str(exc)[:200]}")
    return {
        "ok": (sent_email or sent_wa),
        "channels": channels,
        "sent_email": sent_email,
        "sent_wa": sent_wa,
        "errors": errors,
        "config": {
            "synthese_enabled": bool(s.get("synthese_enabled")),
            "email_to": s.get("synthese_email_to"),
            "wa_to": s.get("synthese_wa_to"),
            "hour": s.get("synthese_hour"),
        },
        "kpis": kpis,
        "preview": body[:500],
    }
