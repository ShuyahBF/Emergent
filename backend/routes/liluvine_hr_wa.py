"""Iter40 (2026-02) — Commandes WhatsApp HR via Liluvine PRO.

Permet aux employés d'envoyer depuis WhatsApp les commandes :
  - `!absence YYYY-MM-DD [YYYY-MM-DD] [motif…]`
       Crée une demande d'absence (statut « pending_approval ») et désactive
       temporairement l'accès au portail jusqu'à validation admin.
  - `!avance MONTANT [motif…]`
       Crée une demande d'avance sur salaire (statut « pending_approval »).

Workflow :
  1. Lookup : récupérer le user via numéro WhatsApp (matching last 9-12 digits).
  2. Lookup : tenant_id + hr_employees entry pour cet utilisateur.
  3. Insertion : doc hr_absences ou hr_advances avec flag pending_approval.
  4. Si absence : passer user.account_status = "inactive" + flag wa_disabled_at.
  5. Notification admin/superviseur tenant : WhatsApp + email.
  6. Confirmation au requester.

Validation des commandes :
  - L'utilisateur doit être enregistré comme hr_employees actif.
  - Sinon → refus avec message explicatif.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sawali.liluvine_hr_wa")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


ABSENCE_RE = re.compile(
    r"^[!/]\s*(absence|absent|conge|congé|absences)\s+"
    r"(\d{4}-\d{2}-\d{2})"
    r"(?:\s+(?:au|to|->)\s+(\d{4}-\d{2}-\d{2}))?"
    r"(?:\s+(.+))?\s*$",
    re.IGNORECASE,
)
ADVANCE_RE = re.compile(
    r"^[!/]\s*(avance|advance)\s+"
    r"(\d+(?:[.,]\d+)?)"
    r"(?:\s+(.+))?\s*$",
    re.IGNORECASE,
)


def detect_hr_command(text: str) -> Optional[str]:
    """Return 'absence' | 'advance' | None."""
    if not text:
        return None
    t = text.strip()
    if ABSENCE_RE.match(t):
        return "absence"
    if ADVANCE_RE.match(t):
        return "advance"
    return None


async def _resolve_employee(db, phone_digits: str) -> Tuple[Optional[dict], Optional[dict]]:
    """Look up the user account + hr_employees row matching this phone.

    Returns (user_doc, employee_doc). Either may be None.
    """
    if not phone_digits or len(phone_digits) < 6:
        return None, None
    # Match on last 9 digits to ignore country code variants.
    tail = phone_digits[-9:]
    user = await db.users.find_one(
        {
            "$or": [
                {"phone": {"$regex": tail + "$"}},
                {"whatsapp": {"$regex": tail + "$"}},
                {"whatsapp_number": {"$regex": tail + "$"}},
            ],
            "account_status": {"$ne": "deleted"},
        },
        {"_id": 0},
    )
    if not user:
        return None, None
    # Find employee
    emp = await db.hr_employees.find_one(
        {"user_id": user["id"], "deleted_at": None},
        {"_id": 0},
    )
    return user, emp


async def _notify_admins(
    db,
    *,
    tenant_id: str,
    text: str,
    wa_send_text=None,
) -> None:
    """Notify tenant admins/superviseur of the new pending HR request."""
    if not wa_send_text:
        return
    admins = []
    async for u in db.users.find(
        {
            "$or": [
                {"id": tenant_id, "role": {"$in": ["admin", "superviseur"]}},
                {"parent_client_id": tenant_id, "role": {"$in": ["admin", "superviseur"]}},
            ],
            "account_status": {"$ne": "deleted"},
        },
        {"_id": 0, "phone": 1, "whatsapp": 1, "whatsapp_number": 1, "email": 1, "full_name": 1},
    ):
        admins.append(u)
    for adm in admins:
        ph = (adm.get("whatsapp_number") or adm.get("whatsapp") or adm.get("phone") or "").strip()
        if not ph:
            continue
        try:
            await wa_send_text(ph, text)
        except Exception:  # noqa: BLE001
            logger.warning("[hr_wa_notify] send to admin failed")


async def handle_absence_command(
    db,
    *,
    user: dict,
    employee: dict,
    text: str,
    phone_digits: str,
    wa_send_text=None,
) -> Dict[str, Any]:
    m = ABSENCE_RE.match(text.strip())
    if not m:
        return {"ok": False, "reason": "regex_mismatch"}
    start = m.group(2)
    end = m.group(3) or start
    if end < start:
        return {
            "ok": False,
            "reason": "date_order",
            "user_reply": (
                "❌ Date de fin antérieure à la date de début. "
                "Format : !absence YYYY-MM-DD [au YYYY-MM-DD] motif."
            ),
        }
    motif = (m.group(4) or "").strip() or "Demande via WhatsApp"
    # Compute hours (8h per business day)
    try:
        d1 = datetime.fromisoformat(start)
        d2 = datetime.fromisoformat(end)
        days = max(1, (d2 - d1).days + 1)
    except Exception:
        days = 1
    tenant_id = employee.get("tenant_id")
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "employee_id": employee["id"],
        "start_date": start,
        "end_date": end,
        "hours_count": float(days * 8),
        "abs_type": "non_justifiee",
        "is_justified": False,
        "justification": motif,
        "status": "pending_approval",
        "source": "whatsapp_wa_command",
        "wa_from_phone": phone_digits,
        "wa_user_id": user["id"],
        "auto_detected": False,
        "created_at": _now_iso(),
        "created_by": user["id"],
    }
    await db.hr_absences.insert_one(doc.copy())
    # Disable portal access until approval
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "account_status": "inactive",
            "wa_absence_disabled_at": _now_iso(),
            "wa_absence_request_id": doc["id"],
        }},
    )
    # Notify admins
    notify_msg = (
        "📥 Nouvelle demande d'absence (WhatsApp)\n\n"
        f"Employé : {user.get('full_name') or user.get('email') or phone_digits}\n"
        f"Période : {start} → {end} ({days} j)\n"
        f"Motif : {motif}\n\n"
        "Accès au portail désactivé jusqu'à validation.\n"
        "Approuver via /portal/hr/absences."
    )
    if tenant_id and wa_send_text:
        await _notify_admins(db, tenant_id=tenant_id, text=notify_msg, wa_send_text=wa_send_text)
    return {
        "ok": True,
        "command": "absence",
        "id": doc["id"],
        "user_reply": (
            f"✅ Demande d'absence enregistrée.\n"
            f"📅 {start} → {end} ({days} jour(s))\n"
            f"📝 {motif}\n\n"
            "⚠️ Votre accès au portail est temporairement désactivé en attendant "
            "la validation par l'administrateur."
        ),
    }


async def handle_advance_command(
    db,
    *,
    user: dict,
    employee: dict,
    text: str,
    phone_digits: str,
    wa_send_text=None,
) -> Dict[str, Any]:
    m = ADVANCE_RE.match(text.strip())
    if not m:
        return {"ok": False, "reason": "regex_mismatch"}
    amount_raw = (m.group(2) or "0").replace(",", ".")
    try:
        amount = float(amount_raw)
    except Exception:
        return {
            "ok": False,
            "reason": "amount_invalid",
            "user_reply": "❌ Montant invalide. Format : !avance MONTANT motif.",
        }
    if amount <= 0:
        return {
            "ok": False,
            "reason": "amount_zero",
            "user_reply": "❌ Le montant de l'avance doit être supérieur à 0.",
        }
    motif = (m.group(3) or "").strip() or "Demande via WhatsApp"
    tenant_id = employee.get("tenant_id")
    today = datetime.now(timezone.utc).date().isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "employee_id": employee["id"],
        "amount": amount,
        "currency": "XOF",
        "motive": motif,
        "granted_at": today,
        "auto_deduct": True,
        "repaid_amount": 0.0,
        "status": "pending_approval",
        "source": "whatsapp_wa_command",
        "wa_from_phone": phone_digits,
        "wa_user_id": user["id"],
        "created_at": _now_iso(),
        "created_by": user["id"],
    }
    await db.hr_advances.insert_one(doc.copy())
    notify_msg = (
        "📥 Nouvelle demande d'avance (WhatsApp)\n\n"
        f"Employé : {user.get('full_name') or user.get('email') or phone_digits}\n"
        f"Montant : {amount:,.0f} XOF\n"
        f"Motif : {motif}\n\n"
        "Approuver via /portal/hr/advances."
    )
    if tenant_id and wa_send_text:
        await _notify_admins(db, tenant_id=tenant_id, text=notify_msg, wa_send_text=wa_send_text)
    return {
        "ok": True,
        "command": "advance",
        "id": doc["id"],
        "user_reply": (
            f"✅ Demande d'avance enregistrée.\n"
            f"💰 Montant : {amount:,.0f} XOF\n"
            f"📝 {motif}\n\n"
            "Un administrateur va l'examiner sous peu."
        ),
    }


async def try_handle_hr_wa_command(
    db,
    *,
    from_phone: str,
    message_text: str,
    wa_send_text=None,
) -> Optional[Dict[str, Any]]:
    """Top-level entry. Returns None if no HR command detected. Otherwise
    returns {ok, command, user_reply?, reason?, id?}. The caller is
    responsible for actually sending `user_reply` back via WhatsApp."""
    cmd = detect_hr_command(message_text)
    if not cmd:
        return None
    phone_digits = _digits(from_phone)
    user, employee = await _resolve_employee(db, phone_digits)
    if not user:
        return {
            "ok": False,
            "command": cmd,
            "reason": "user_not_found",
            "user_reply": (
                "❌ Numéro non reconnu. Cette commande est réservée aux "
                "employés enregistrés dans la GRH SAWALI."
            ),
        }
    if not employee:
        return {
            "ok": False,
            "command": cmd,
            "reason": "not_an_employee",
            "user_reply": (
                "❌ Vous n'êtes pas enregistré(e) comme employé(e) dans la "
                "GRH. Contactez votre administrateur."
            ),
        }
    if cmd == "absence":
        return await handle_absence_command(
            db, user=user, employee=employee, text=message_text,
            phone_digits=phone_digits, wa_send_text=wa_send_text,
        )
    if cmd == "advance":
        return await handle_advance_command(
            db, user=user, employee=employee, text=message_text,
            phone_digits=phone_digits, wa_send_text=wa_send_text,
        )
    return None


__all__ = [
    "try_handle_hr_wa_command",
    "detect_hr_command",
    "handle_absence_command",
    "handle_advance_command",
    "ABSENCE_RE",
    "ADVANCE_RE",
]
