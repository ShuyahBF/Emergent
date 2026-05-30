"""Iter38r-fix9l — Bonus features pack:
  - WhatsApp Tasks bidirectional sync (morning digest + parse replies)
  - Liluvine PRO weekly digest (Monday 8h, email only)
  - GDPR automated anonymization (contacts/messages/logs)
  - GDPR "Export my data" button (user-facing endpoint)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger("sawali.bonus_pack")


# =====================================================================
# Reply parser (Iter38r-fix9l) for WA task acknowledgements
# Accepts: "OK 1,3,5" / "FAIT 2 5" / "DONE 1, 4" / "✅ 1 2 3" / "Done :1,3"
# =====================================================================
_TASK_ACK_KEYWORDS = ("ok", "fait", "done", "✅", "✔", "tache", "tâche", "tasks")
_TASK_ACK_RE = re.compile(r"\d+")


def parse_task_ack(text: str) -> List[int]:
    """Return the 1-based indexes mentioned in a WA reply, only when the
    message clearly intends to mark tasks as done. Empty list otherwise."""
    if not text:
        return []
    low = text.strip().lower()
    if not any(kw in low for kw in _TASK_ACK_KEYWORDS):
        return []
    nums = [int(m) for m in _TASK_ACK_RE.findall(low) if int(m) > 0 and int(m) < 1000]
    return list(dict.fromkeys(nums))  # dedupe, keep order


# =====================================================================
# WA Task digest cron — runs every 5 min, sends the digest at the configured
# hour. We let the cron tick frequently so different tenants can opt for
# different send hours without splitting the scheduler.
# =====================================================================
async def run_wa_tasks_digest(db, send_wa_text_fn, get_settings_async_fn) -> Dict[str, Any]:
    """Iter38r-fix9l — WA Task digest job.
    For each user with `wa_tasks_digest_enabled` and `wa_tasks_digest_hour == current_hour`
    (Africa/Abidjan), send the user's pending task_items as a numbered list."""
    now = datetime.now(timezone.utc) + timedelta(hours=0)  # Africa/Abidjan = UTC+0
    sent = 0
    # Fetch global enable flag — admin can kill-switch the whole feature
    s = await get_settings_async_fn()
    if not s.get("wa_tasks_digest_enabled"):
        return {"sent": 0, "skipped_reason": "global_disabled"}
    cur_hour = now.hour
    # Find users who opted-in for this hour
    cursor = db.users.find(
        {
            "wa_tasks_digest_enabled": True,
            "wa_tasks_digest_hour": cur_hour,
            "$or": [
                {"whatsapp": {"$exists": True, "$ne": ""}},
                {"phone": {"$exists": True, "$ne": ""}},
            ],
        },
        {"_id": 0, "id": 1, "email": 1, "whatsapp": 1, "phone": 1, "full_name": 1, "wa_tasks_last_digest_at": 1},
    )
    today_str = now.strftime("%Y-%m-%d")
    async for u in cursor:
        # Avoid double-send for the same day (idempotent)
        last = u.get("wa_tasks_last_digest_at") or ""
        if isinstance(last, str) and last.startswith(today_str):
            continue
        # Collect pending tasks for this user
        notes = await db.user_tasks_personal.find(
            {"owner_id": u["id"]},
            {"_id": 0, "id": 1, "title": 1, "task_items": 1, "created_at": 1},
        ).sort("created_at", -1).limit(5).to_list(5)
        pending: List[Dict[str, Any]] = []
        for n in notes:
            for idx, it in enumerate(n.get("task_items") or []):
                if not it.get("done"):
                    pending.append({
                        "note_id": n["id"],
                        "note_title": n.get("title") or "(sans titre)",
                        "item_id": it.get("id"),
                        "item_text": it.get("text") or "",
                        "item_index": idx,
                    })
        if not pending:
            continue
        # Build a numbered list (cap at 15 to fit a single WA message)
        capped = pending[:15]
        # Persist the "mapping" so the inbound parser knows which item_ids the
        # numbers refer to.
        mapping_doc = {
            "user_id": u["id"],
            "sent_at": now.isoformat(),
            "date": today_str,
            "items": [{"n": i + 1, **p} for i, p in enumerate(capped)],
            "expires_at": (now + timedelta(hours=20)).isoformat(),
        }
        await db.wa_tasks_digest_state.update_one(
            {"user_id": u["id"]},
            {"$set": mapping_doc},
            upsert=True,
        )
        name = (u.get("full_name") or u.get("email") or "").split()[0] or "👋"
        lines = [f"Bonjour {name} ! Voici vos tâches du jour :", ""]
        for i, p in enumerate(capped):
            lines.append(f"{i + 1}. {p['item_text']}")
        lines.append("")
        lines.append("Pour cocher : répondez `OK 1,3` ou `FAIT 2 5`.")
        text = "\n".join(lines)
        recipient = u.get("whatsapp") or u.get("phone") or ""
        try:
            ok = await send_wa_text_fn(recipient, text, scope_user=u)
        except Exception as exc:
            logger.warning("[wa_tasks_digest] send failed for %s: %s", u.get("email"), exc)
            ok = False
        if ok:
            await db.users.update_one(
                {"id": u["id"]},
                {"$set": {"wa_tasks_last_digest_at": now.isoformat()}},
            )
            sent += 1
    return {"sent": sent, "ok": True}


async def apply_task_ack_for_user(db, user_id: str, indexes: List[int]) -> Dict[str, Any]:
    """Iter38r-fix9l — Mark the listed indexes (1-based, from the morning
    digest) as done. Returns counts and updated note ids."""
    state = await db.wa_tasks_digest_state.find_one({"user_id": user_id}, {"_id": 0})
    if not state:
        return {"matched": 0, "updated_notes": [], "reason": "no_active_digest"}
    items = state.get("items") or []
    by_n: Dict[int, Dict[str, Any]] = {int(it["n"]): it for it in items}
    affected: Dict[str, List[str]] = {}
    for n in indexes:
        rec = by_n.get(n)
        if not rec:
            continue
        affected.setdefault(rec["note_id"], []).append(rec["item_id"])
    updated_notes: List[str] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for note_id, item_ids in affected.items():
        note = await db.user_tasks_personal.find_one({"id": note_id}, {"_id": 0})
        if not note:
            continue
        new_items = []
        changed = False
        for it in note.get("task_items") or []:
            if it.get("id") in item_ids and not it.get("done"):
                changed = True
                it = {**it, "done": True, "done_at": now_iso}
            new_items.append(it)
        if changed:
            await db.user_tasks_personal.update_one(
                {"id": note_id},
                {"$set": {"task_items": new_items, "updated_at": now_iso}},
            )
            updated_notes.append(note_id)
    return {"matched": sum(len(v) for v in affected.values()), "updated_notes": updated_notes}


# =====================================================================
# Liluvine PRO weekly digest — Monday 8h Africa/Abidjan, email only
# =====================================================================
async def run_liluvine_weekly_digest(db, send_email_fn, get_settings_async_fn) -> Dict[str, Any]:
    """Per-admin recap of last 7 days of Liluvine activity."""
    s = await get_settings_async_fn()
    if not s.get("liluvine_weekly_digest_enabled"):
        return {"sent": 0, "skipped_reason": "disabled"}
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    week_ago_iso = week_ago.isoformat()
    cursor = db.users.find(
        {"role": {"$in": ["admin", "superviseur"]}, "account_status": {"$ne": "disabled"}},
        {"_id": 0, "id": 1, "email": 1, "full_name": 1},
    )
    sent = 0
    async for u in cursor:
        client_id = u["id"]
        # 1. Top 5 most active WA contacts
        pipeline = [
            {"$match": {
                "client_id": client_id,
                "created_at": {"$gte": week_ago_iso},
                "phone_digits": {"$ne": None},
            }},
            {"$group": {"_id": "$phone_digits", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]
        top_contacts = []
        async for row in db.whatsapp_messages.aggregate(pipeline):
            top_contacts.append({"phone": row["_id"], "count": row["count"]})
        # 2. ROI cumul Liluvine PRO (use existing welcome briefing stats)
        autoreplies = await db.whatsapp_messages.count_documents({
            "client_id": client_id,
            "is_autoreply": True,
            "created_at": {"$gte": week_ago_iso},
        })
        roi_minutes = autoreplies * 2  # 2 minutes saved per auto-reply
        roi_xof = autoreplies * 100  # 100 XOF / interaction saved
        # 3. Sessions reprises manuellement
        takeovers = await db.liluvine_pro_sessions.count_documents({
            "client_id": client_id,
            "human_takeover": True,
        })
        # Build HTML email
        rows = "".join(
            f"<tr><td style='padding:4px 8px'><code>+{c['phone']}</code></td><td style='padding:4px 8px;text-align:right'><strong>{c['count']}</strong></td></tr>"
            for c in top_contacts
        ) or "<tr><td colspan='2' style='padding:4px 8px;color:#888;text-align:center;font-style:italic'>Aucun échange WA cette semaine</td></tr>"
        # Build the "Lancer une campagne ciblée" CTA URL with pre-filled msisdns
        msisdns = ",".join(c["phone"] for c in top_contacts)
        campaign_url = f"{s.get('public_base_url') or 'https://sawalismartsystems.com'}/admin/messaging?prefill_msisdns={msisdns}"
        html = (
            f"<div style='font-family:Inter,Arial,sans-serif;max-width:560px;margin:0 auto;color:#1e293b'>"
            f"<h2 style='color:#a855f7;margin:0 0 8px'>SAWALI — Liluvine PRO 🤖</h2>"
            f"<p style='margin:0 0 16px;color:#64748b'>Bonjour {(u.get('full_name') or '').split()[0] or 'Admin'}, voici votre digest de la semaine.</p>"
            f"<div style='background:#f5f3ff;padding:16px;border-radius:12px;margin-bottom:16px'>"
            f"<h3 style='margin:0 0 8px;color:#7c3aed'>📊 ROI Liluvine</h3>"
            f"<p style='margin:0'><strong>{autoreplies}</strong> auto-réponses · <strong>{roi_minutes // 60}h{roi_minutes % 60:02d}</strong> de temps gagné · <strong>{roi_xof:,} XOF</strong> économisés</p>"
            f"</div>"
            f"<h3 style='margin:0 0 8px'>🔥 Top 5 contacts WhatsApp</h3>"
            f"<table style='width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;margin-bottom:16px'>"
            f"<thead><tr style='background:#f1f5f9'><th style='padding:6px 8px;text-align:left;font-size:11px;text-transform:uppercase;color:#64748b'>Numéro</th><th style='padding:6px 8px;text-align:right;font-size:11px;text-transform:uppercase;color:#64748b'>Messages</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            f"<div style='background:#fffbeb;padding:12px;border-radius:8px;margin-bottom:16px'>"
            f"<strong>🤝 Conversations reprises manuellement :</strong> {takeovers}"
            f"</div>"
            f"<a href='{campaign_url}' style='display:inline-block;background:#a855f7;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600'>🚀 Lancer une campagne ciblée</a>"
            f"<p style='margin:24px 0 0;color:#94a3b8;font-size:11px'>Email automatique — SAWALI Iter38r-fix9l Weekly Digest</p>"
            f"</div>"
        )
        text = (
            f"SAWALI - Liluvine PRO Digest hebdo\n\n"
            f"ROI: {autoreplies} auto-réponses, {roi_minutes // 60}h{roi_minutes % 60:02d} économisés, {roi_xof} XOF\n"
            f"Top 5 contacts WhatsApp: " + ", ".join(f"+{c['phone']} ({c['count']})" for c in top_contacts) + "\n"
            f"Conversations reprises: {takeovers}\n"
            f"Lancer une campagne: {campaign_url}\n"
        )
        try:
            ok = await send_email_fn(
                to_email=u["email"],
                subject="SAWALI — Digest hebdo Liluvine PRO 🤖",
                html_body=html,
                text_body=text,
            )
            if ok:
                sent += 1
        except Exception as exc:
            logger.warning("[liluvine_digest] email failed for %s: %s", u["email"], exc)
    return {"sent": sent, "ok": True}


# =====================================================================
# GDPR automated anonymization — daily 03:30
# =====================================================================
async def run_gdpr_anonymization(db, get_settings_async_fn) -> Dict[str, Any]:
    """Apply tenant-configured retention rules:
       - inactive contacts older than X months → delete
       - WA/SMS messages older than X months → anonymize content
       - access_logs / api_traces older than X days → delete
    `notes_strict_tasks_only` is unrelated. All thresholds default to the
    standard config requested by user: 24m / 12m / 90j.
    """
    s = await get_settings_async_fn()
    if not s.get("gdpr_auto_anonymize_enabled"):
        return {"skipped_reason": "disabled"}
    # Defaults (months / days)
    contact_inactive_months = int(s.get("gdpr_contact_inactive_months") or 24)
    msg_retention_months = int(s.get("gdpr_msg_retention_months") or 12)
    log_retention_days = int(s.get("gdpr_log_retention_days") or 90)
    now = datetime.now(timezone.utc)
    cutoff_contact = (now - timedelta(days=30 * contact_inactive_months)).isoformat()
    cutoff_msg = (now - timedelta(days=30 * msg_retention_months)).isoformat()
    cutoff_log = (now - timedelta(days=log_retention_days)).isoformat()
    report = {"started_at": now.isoformat()}
    # 1. Delete inactive contacts
    res_contacts = await db.contacts.delete_many({
        "last_interaction_at": {"$lt": cutoff_contact},
    })
    report["contacts_deleted"] = res_contacts.deleted_count
    # 2. Anonymize WA messages
    res_wa = await db.whatsapp_messages.update_many(
        {"created_at": {"$lt": cutoff_msg}, "content": {"$exists": True, "$ne": "[ANONYMIZED]"}},
        {"$set": {"content": "[ANONYMIZED]", "anonymized_at": now.isoformat()}},
    )
    report["wa_messages_anonymized"] = res_wa.modified_count
    # 3. Anonymize SMS
    res_sms = await db.sms_messages.update_many(
        {"created_at": {"$lt": cutoff_msg}, "content": {"$exists": True, "$ne": "[ANONYMIZED]"}},
        {"$set": {"content": "[ANONYMIZED]", "anonymized_at": now.isoformat()}},
    )
    report["sms_messages_anonymized"] = res_sms.modified_count
    # 4. Logs rotation
    res_acc = await db.access_logs.delete_many({"created_at": {"$lt": cutoff_log}})
    report["access_logs_deleted"] = res_acc.deleted_count
    res_api = await db.api_traces.delete_many({"created_at": {"$lt": cutoff_log}})
    report["api_traces_deleted"] = res_api.deleted_count
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    # Audit trail
    await db.gdpr_anonymization_runs.insert_one({**report, "id": str(int(now.timestamp()))})
    return report


# =====================================================================
# FastAPI routes wiring
# =====================================================================
def setup_bonus_pack_routes(app, db, get_current_user):
    api: APIRouter = app

    # --- "Reprendre les tâches" admin endpoint to fire the WA digest now ---
    @api.post("/admin/wa-tasks-digest/run-now", tags=["Admin — Bonus pack"])
    async def admin_run_wa_tasks_digest(user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux admins")
        from server import _send_wa_text_for_digest, _get_settings_async  # type: ignore
        return await run_wa_tasks_digest(db, _send_wa_text_for_digest, _get_settings_async)

    @api.post("/admin/liluvine-weekly-digest/run-now", tags=["Admin — Bonus pack"])
    async def admin_run_weekly_digest(user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux admins")
        from server import send_email, _get_settings_async  # type: ignore
        return await run_liluvine_weekly_digest(db, send_email, _get_settings_async)

    @api.post("/admin/gdpr/anonymize-now", tags=["Admin — Bonus pack"])
    async def admin_anonymize_now(user: dict = Depends(get_current_user)):
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
        from server import _get_settings_async  # type: ignore
        return await run_gdpr_anonymization(db, _get_settings_async)

    # --- "Exporter mes données" user-facing endpoint (GDPR right to portability) ---
    @api.get("/me/gdpr/export", tags=["Portail Client — GDPR"])
    async def me_gdpr_export(user: dict = Depends(get_current_user)):
        uid = user["id"]
        # Strip sensitive internals from the user doc
        u = await db.users.find_one({"id": uid}, {
            "_id": 0, "password_hash": 0, "otp_code": 0, "otp_expires_at": 0,
            "reset_token": 0, "totp_secret": 0,
        }) or {}
        contacts = await db.contacts.find({"owner_id": uid}, {"_id": 0}).to_list(5000)
        wa_in = await db.whatsapp_messages.find({"client_id": uid, "direction": "in"}, {"_id": 0}).to_list(5000)
        wa_out = await db.whatsapp_messages.find({"client_id": uid, "direction": "out"}, {"_id": 0}).to_list(5000)
        sms = await db.sms_messages.find({"client_id": uid}, {"_id": 0}).to_list(5000)
        tasks = await db.user_tasks_personal.find({"owner_id": uid}, {"_id": 0}).to_list(2000)
        notes = await db.user_notes_personal.find({"owner_id": uid}, {"_id": 0}).to_list(2000)
        reports = await db.user_reports.find({"owner_id": uid}, {"_id": 0}).to_list(2000)
        suivis = await db.user_suivis.find({"owner_id": uid}, {"_id": 0}).to_list(2000)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user": u,
            "contacts": contacts,
            "whatsapp_messages": {"inbound": wa_in, "outbound": wa_out},
            "sms_messages": sms,
            "tasks": tasks,
            "notes": notes,
            "reports": reports,
            "suivis": suivis,
        }

    # --- User-side opt-in for WA task digest ---
    @api.put("/me/wa-tasks-digest", tags=["Portail Client — Bonus pack"])
    async def me_set_wa_digest(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
        update: Dict[str, Any] = {}
        if "enabled" in payload:
            update["wa_tasks_digest_enabled"] = bool(payload["enabled"])
        if "hour" in payload:
            h = int(payload["hour"])
            if not 0 <= h <= 23:
                raise HTTPException(status_code=400, detail="Heure doit être entre 0 et 23")
            update["wa_tasks_digest_hour"] = h
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        await db.users.update_one({"id": user["id"]}, {"$set": update})
        return {"ok": True, **update}

    @api.get("/me/wa-tasks-digest", tags=["Portail Client — Bonus pack"])
    async def me_get_wa_digest(user: dict = Depends(get_current_user)):
        u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "wa_tasks_digest_enabled": 1, "wa_tasks_digest_hour": 1}) or {}
        return {
            "enabled": bool(u.get("wa_tasks_digest_enabled")),
            "hour": int(u.get("wa_tasks_digest_hour") or 7),
        }

    return api
