"""2026-02 fork (P3) — Envoi quotidien du planning RDV d'un médecin par WhatsApp.

Chaque tracked-user (`tracked_role == "Médecin"`) peut activer via
`/portal/my-account` :
  - `planning_wa_digest_enabled: bool`
  - `planning_wa_digest_hour: int` (0-23, Africa/Abidjan == UTC+0)

Toutes les 5 min, un cron lit tous les médecins qui matchent l'heure courante
et n'ont pas encore reçu leur digest du jour (idempotence via
`planning_wa_last_digest_at`). Il expédie un texte WhatsApp listant les RDV
prévus aujourd'hui pour ce médecin.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Awaitable, Dict, List, Optional

from fastapi import Depends, HTTPException

logger = logging.getLogger("sawali.medecin_planning")


async def run_medecin_planning_digest(
    db,
    send_wa_text_fn: Callable[..., Awaitable[bool]],
) -> Dict[str, Any]:
    """Envoie, toutes les 5 min, le planning du jour aux médecins qui ont
    opté-in ET dont l'heure de préférence == heure courante (Africa/Abidjan).
    Idempotent via `planning_wa_last_digest_at`.
    """
    now = datetime.now(timezone.utc)  # Africa/Abidjan == UTC+0
    cur_hour = now.hour
    today_str = now.strftime("%Y-%m-%d")

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    start_iso = day_start.isoformat()
    end_iso = day_end.isoformat()

    cursor = db.users.find(
        {
            "tracked_role": "Médecin",
            "planning_wa_digest_enabled": True,
            "planning_wa_digest_hour": cur_hour,
            "$or": [
                {"whatsapp": {"$exists": True, "$ne": ""}},
                {"phone": {"$exists": True, "$ne": ""}},
            ],
        },
        {
            "_id": 0,
            "id": 1,
            "email": 1,
            "whatsapp": 1,
            "phone": 1,
            "full_name": 1,
            "planning_wa_last_digest_at": 1,
        },
    )

    sent = 0
    skipped = 0
    async for u in cursor:
        last = u.get("planning_wa_last_digest_at") or ""
        if isinstance(last, str) and last.startswith(today_str):
            skipped += 1
            continue

        # Fetch today's appointments — match medecin_id OR medecin_email
        q: Dict[str, Any] = {
            "start_at": {"$gte": start_iso, "$lt": end_iso},
            "$or": [
                {"medecin_id": u["id"]},
            ],
        }
        email = (u.get("email") or "").strip().lower()
        if email:
            import re
            q["$or"].append({"medecin_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})

        rdvs: List[Dict[str, Any]] = await db.planning_appointments.find(
            q, {"_id": 0, "start_at": 1, "patient": 1, "motif": 1, "code_clinique": 1}
        ).sort("start_at", 1).to_list(50)

        recipient = (u.get("whatsapp") or u.get("phone") or "").strip()
        if not recipient:
            skipped += 1
            continue

        name = (u.get("full_name") or u.get("email") or "").split()[0] or "Docteur"
        if not rdvs:
            text = (
                f"Bonjour Dr {name} — aucun rendez-vous programmé aujourd'hui ({today_str}). "
                "Bonne journée ! — SAWALI"
            )
        else:
            lines = [f"Bonjour Dr {name}, votre planning du {today_str} :", ""]
            for i, r in enumerate(rdvs[:20]):
                start_iso_r = r.get("start_at") or ""
                try:
                    dt = datetime.fromisoformat(start_iso_r.replace("Z", "+00:00"))
                    hh = dt.strftime("%H:%M")
                except Exception:  # noqa: BLE001
                    hh = start_iso_r[11:16] if len(start_iso_r) > 16 else "—"
                patient = (r.get("patient") or "").strip() or "Patient"
                motif = (r.get("motif") or "").strip()
                clinique = (r.get("code_clinique") or "").strip()
                extras = " · ".join([x for x in (motif, clinique) if x])
                lines.append(f"{i + 1}. {hh} — {patient}" + (f" ({extras})" if extras else ""))
            if len(rdvs) > 20:
                lines.append(f"... et {len(rdvs) - 20} de plus.")
            lines.append("")
            lines.append("Bonne journée ! — SAWALI")
            text = "\n".join(lines)

        try:
            ok = await send_wa_text_fn(recipient, text, scope_user=u)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[medecin_planning] send failed for %s: %s", u.get("email"), exc)
            ok = False
        if ok:
            await db.users.update_one(
                {"id": u["id"]},
                {"$set": {"planning_wa_last_digest_at": now.isoformat()}},
            )
            sent += 1
        else:
            skipped += 1

    return {"ok": True, "sent": sent, "skipped": skipped, "hour": cur_hour}


def setup_medecin_planning_digest_routes(app, db, get_current_user):
    """Endpoints portail : lecture + mise à jour de l'opt-in par médecin."""
    api = app

    @api.get("/me/planning-wa-digest", tags=["Portail Client — Planning"])
    async def me_get_planning_wa_digest(user: dict = Depends(get_current_user)):
        if (user.get("tracked_role") or "") != "Médecin":
            raise HTTPException(status_code=403, detail="Réservé aux comptes Médecin")
        u = await db.users.find_one(
            {"id": user["id"]},
            {"_id": 0, "planning_wa_digest_enabled": 1, "planning_wa_digest_hour": 1},
        ) or {}
        return {
            "enabled": bool(u.get("planning_wa_digest_enabled")),
            "hour": int(u.get("planning_wa_digest_hour") or 7),
        }

    @api.put("/me/planning-wa-digest", tags=["Portail Client — Planning"])
    async def me_set_planning_wa_digest(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
        if (user.get("tracked_role") or "") != "Médecin":
            raise HTTPException(status_code=403, detail="Réservé aux comptes Médecin")
        update: Dict[str, Any] = {}
        if "enabled" in payload:
            update["planning_wa_digest_enabled"] = bool(payload["enabled"])
        if "hour" in payload:
            try:
                h = int(payload["hour"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Heure invalide (0-23 attendu)")
            if not 0 <= h <= 23:
                raise HTTPException(status_code=400, detail="Heure doit être entre 0 et 23")
            update["planning_wa_digest_hour"] = h
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        await db.users.update_one({"id": user["id"]}, {"$set": update})
        return {"ok": True, **update}

    @api.post("/admin/planning-wa-digest/run-now", tags=["Admin — Planning"])
    async def admin_run_planning_digest_now(user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux admins")
        from server import _send_wa_text_for_digest  # type: ignore
        return await run_medecin_planning_digest(db, _send_wa_text_for_digest)

    return api
