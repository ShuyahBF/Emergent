"""2026-02 fork (P3) — Envoi quotidien du planning RDV d'un médecin par WhatsApp.

Chaque tracked-user (`tracked_role == "Médecin"`) peut activer via
`/portal/my-account` :
  - `planning_wa_digest_enabled: bool`
  - `planning_wa_digest_hour: int` (0-23, Africa/Abidjan == UTC+0)

Toutes les 5 min, un cron lit tous les médecins qui matchent l'heure courante
et n'ont pas encore reçu leur digest du jour (idempotence via
`planning_wa_last_digest_at`). Il expédie un texte WhatsApp listant les RDV
prévus aujourd'hui pour ce médecin.

2026-02 fork (P3 recap) — Le message WA inclut un DEEP-LINK signé (JWT scope
`wa_planning_recap`, TTL 30 min) qui permet au médecin d'ouvrir son planning
sans re-saisir email/mot de passe/OTP. Le frontend `/wa-recap?t=<token>`
échange ce jeton contre un JWT auth classique via
`POST /api/auth/wa-planning-exchange`.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Awaitable, Dict, List, Optional

import jwt as pyjwt
from fastapi import Depends, HTTPException

logger = logging.getLogger("sawali.medecin_planning")

# 2026-02 fork (P3 recap) — Signing secret for WA planning recap tokens.
_RECAP_JWT_SECRET = (
    os.environ.get("WA_PLANNING_RECAP_SECRET")
    or os.environ.get("LINK_JWT_SECRET")
    or (os.environ.get("JWT_SECRET", "fallback-insecure") + "-wa-recap")
)
_RECAP_JWT_ALGO = "HS256"
_RECAP_TTL_SECONDS = 30 * 60  # 30 minutes


def _issue_recap_token(user_id: str) -> str:
    """Sign a scope=wa_planning_recap short-lived JWT for a médecin."""
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "sub": user_id,
        "scope": "wa_planning_recap",
        "iat": now,
        "exp": now + _RECAP_TTL_SECONDS,
    }
    return pyjwt.encode(claims, _RECAP_JWT_SECRET, algorithm=_RECAP_JWT_ALGO)


def _decode_recap_token(token: str) -> Dict[str, Any]:
    """Decode + validate a recap token. Raises ValueError on any issue."""
    try:
        claims = pyjwt.decode(token, _RECAP_JWT_SECRET, algorithms=[_RECAP_JWT_ALGO])
    except pyjwt.ExpiredSignatureError as exc:
        raise ValueError("expired") from exc
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid") from exc
    if claims.get("scope") != "wa_planning_recap":
        raise ValueError("bad_scope")
    if not claims.get("sub"):
        raise ValueError("missing_sub")
    return claims


def _public_base_from_env() -> str:
    """Preview + prod compatible base URL. Priority : PUBLIC_BASE_URL env var
    (canonical, used by the deploy scripts) → REACT_APP_BACKEND_URL as fallback
    for dev preview → empty string (link will be relative)."""
    base = (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
    return base


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
        # 2026-02 fork (P3 recap) — Deep-link auto-login (30 min).
        recap_token = _issue_recap_token(u["id"])
        base = _public_base_from_env()
        recap_url = f"{base}/wa-recap?t={recap_token}" if base else f"/wa-recap?t={recap_token}"
        if not rdvs:
            text = (
                f"Bonjour Dr {name} — aucun rendez-vous programmé aujourd'hui ({today_str}).\n"
                f"Consulter tout de même mon planning : {recap_url}\n"
                "(Lien valable 30 min, connexion automatique)\n"
                "— SAWALI"
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
            lines.append(f"Valider / annuler / reprogrammer : {recap_url}")
            lines.append("(Lien valable 30 min, connexion automatique)")
            lines.append("— SAWALI")
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
            # 2026-02 fork (analytics) — log a "sent" event for admin metrics
            try:
                await db.planning_digest_events.insert_one({
                    "id": str(uuid.uuid4()),
                    "kind": "sent",
                    "user_id": u["id"],
                    "email": (u.get("email") or "").lower(),
                    "tenant_id": (u.get("parent_client_id") or u.get("client_id") or u.get("id") or ""),
                    "rdv_count": len(rdvs),
                    "recipient_digits": "".join(ch for ch in recipient if ch.isdigit())[-4:],
                    "recap_token_issued": True,
                    "at": now.isoformat(),
                })
            except Exception:  # noqa: BLE001
                pass  # analytics is best-effort — never block sending
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

    # 2026-02 fork (P3 recap) — Exchange the short-lived WA planning recap
    # token for a full-fledged auth JWT (same TTL as a normal login) so the
    # médecin can act on their planning without re-entering email/password/OTP.
    @api.post("/auth/wa-planning-exchange", tags=["Portail Client — Planning"])
    async def wa_planning_exchange(payload: Dict[str, Any]):
        raw_token = (payload or {}).get("t") or (payload or {}).get("token")
        if not raw_token:
            raise HTTPException(status_code=400, detail="Token manquant")
        try:
            claims = _decode_recap_token(str(raw_token))
        except ValueError as exc:
            reason = str(exc)
            code = 401 if reason in ("expired", "invalid", "bad_scope", "missing_sub") else 400
            raise HTTPException(status_code=code, detail=f"Token {reason}")
        u = await db.users.find_one({"id": claims["sub"]}, {"_id": 0, "password_hash": 0})
        if not u:
            raise HTTPException(status_code=404, detail="Compte introuvable")
        if u.get("account_status") != "active":
            raise HTTPException(status_code=403, detail="Compte désactivé")
        if (u.get("tracked_role") or "") != "Médecin":
            raise HTTPException(status_code=403, detail="Réservé aux comptes Médecin")
        # Issue a normal auth JWT (12h TTL). Reuse server.create_access_token.
        from auth import create_access_token as _mint  # type: ignore
        from server import _to_user_public  # type: ignore
        access = _mint(u["id"], u.get("role") or "client")
        # 2026-02 fork (analytics) — log the "opened" event
        try:
            await db.planning_digest_events.insert_one({
                "id": str(uuid.uuid4()),
                "kind": "opened",
                "user_id": u["id"],
                "email": (u.get("email") or "").lower(),
                "tenant_id": (u.get("parent_client_id") or u.get("client_id") or u.get("id") or ""),
                "at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:  # noqa: BLE001
            pass
        return {"access_token": access, "token_type": "Bearer", "user": _to_user_public(u)}

    # 2026-02 fork (analytics) — Admin dashboard for the planning digest.
    @api.get("/admin/planning-digest/analytics", tags=["Admin — Planning"])
    async def admin_planning_digest_analytics(days: int = 30, user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux admins")
        d = max(1, min(365, days))
        since = (datetime.now(timezone.utc) - timedelta(days=d)).isoformat()
        pipeline = [
            {"$match": {"at": {"$gte": since}}},
            {"$group": {
                "_id": {
                    "kind": "$kind",
                    "day": {"$substrCP": ["$at", 0, 10]},
                },
                "count": {"$sum": 1},
            }},
        ]
        try:
            rows = await db.planning_digest_events.aggregate(pipeline).to_list(4000)
        except Exception:  # noqa: BLE001
            rows = []

        by_day: Dict[str, Dict[str, int]] = {}
        totals = {"sent": 0, "opened": 0}
        for row in rows:
            k = row["_id"]["kind"]
            day = row["_id"]["day"]
            n = int(row.get("count") or 0)
            by_day.setdefault(day, {"sent": 0, "opened": 0})
            if k in ("sent", "opened"):
                by_day[day][k] += n
                totals[k] += n

        # Add engagement rate (opened / sent), guard division by zero
        rate = None
        if totals["sent"]:
            rate = round(100.0 * totals["opened"] / totals["sent"], 1)

        # Sorted day breakdown
        breakdown = [
            {"day": day, **counts, "rate": (round(100.0 * counts["opened"] / counts["sent"], 1) if counts["sent"] else None)}
            for day, counts in sorted(by_day.items())
        ]

        # Recent 20 events (audit stream)
        recent = await db.planning_digest_events.find(
            {"at": {"$gte": since}}, {"_id": 0}
        ).sort("at", -1).to_list(20)
        return {
            "days": d,
            "totals": totals,
            "engagement_rate_pct": rate,
            "breakdown": breakdown,
            "recent": recent,
        }

    return api
