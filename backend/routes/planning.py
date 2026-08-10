"""Iter43-fix24az-m (2026-07-18) — Module Planning médecins.

Feature :
- Webhook public `POST /api/webhooks/planning/{secret}` — reçoit un JSON de RDV
  depuis un système externe (clinique / cabinet médical) sans auth
- Endpoint tenant `GET /api/me/planning/appointments` — récupère les RDV pour
  un médecin sur une date donnée
- Endpoint tenant `GET /api/me/planning/doctors` — liste les médecins (tracked
  users avec `role="Médecin"`) du tenant courant
- Endpoint admin `GET/PUT /api/admin/planning/config` — gère le secret webhook +
  affiche l'URL complète à copier chez le prestataire
- Iter43-fix24az-n (2026-07-18) — SSE stream `/api/me/planning/stream` :
  remplace le polling frontend par un push serveur temps réel.
- Iter43-fix24az-n — Cron 5min `run_planning_wa_reminders` : envoi automatique
  d'un rappel WhatsApp au patient 1h avant chaque RDV.

Schéma `planning_appointments` :
    { id, tenant_id, code_clinique, medecin, medecin_id, medecin_email,
      patient, patient_phone, patient_email,
      start_at (ISO), end_at (ISO), motif, id_user,
      external_id, source, created_at, updated_at, received_at,
      reminder_sent_at, reminder_status }

Unicité : (tenant_id, code_clinique, medecin, patient, start_at) — upsert idempotent
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


# 2026-02 fork (P2) — Walk-in CRUD payload models (module-level so Pydantic
# can resolve forward refs when the endpoint uses `Body(...)`).
class WalkInCreatePayload(BaseModel):
    medecin_id: str = Field(..., description="ID du médecin (tracked user role=Médecin)")
    patient: str = Field(..., min_length=1, max_length=120)
    patient_phone: Optional[str] = Field(None, max_length=32)
    date: Optional[str] = Field(None, description="YYYY-MM-DD — défaut = aujourd'hui")
    motif: Optional[str] = Field(None, max_length=300)
    domaine: Optional[str] = Field(None, max_length=60)


class WalkInUpdatePayload(BaseModel):
    patient: Optional[str] = Field(None, min_length=1, max_length=120)
    patient_phone: Optional[str] = Field(None, max_length=32)
    motif: Optional[str] = Field(None, max_length=300)
    medecin_id: Optional[str] = None
    date: Optional[str] = None
    domaine: Optional[str] = Field(None, max_length=60)

logger = logging.getLogger("sawali.planning")

# ---------------------------------------------------------------------------
# In-memory SSE pubsub (single-worker uvicorn OK)
# ---------------------------------------------------------------------------
# _sse_subscribers: List of dicts { id, tenant_id, user_id, medecin_id (opt), queue }
# Broadcast helper filters by tenant_id + optional medecin_id match.
_sse_subscribers: List[Dict[str, Any]] = []
_sse_lock = asyncio.Lock()


async def _sse_broadcast(tenant_id: str, event_type: str, appointment: Dict[str, Any]) -> None:
    """Push an event to all matching subscribers (same tenant + optional medecin filter)."""
    if not _sse_subscribers:
        return
    payload = {
        "event": event_type,
        "appointment": appointment,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    dead: List[str] = []
    async with _sse_lock:
        for sub in list(_sse_subscribers):
            # Tenant scope check: subscriber has a list of allowed tenants
            allowed = sub.get("allowed_tenants")
            if allowed is None:
                # Super-admin — sees all
                pass
            elif tenant_id not in allowed:
                continue
            # Filter by medecin_id if set (server locks Médecin users to themselves)
            filt_medecin = sub.get("medecin_id_filter")
            if filt_medecin:
                if appointment.get("medecin_id") != filt_medecin and appointment.get("medecin_email") != sub.get("medecin_email"):
                    continue
            try:
                sub["queue"].put_nowait(payload)
            except Exception as exc:  # noqa: BLE001
                logger.debug("[planning] SSE queue full/broken for sub=%s: %s", sub.get("id"), exc)
                dead.append(sub["id"])
        if dead:
            _sse_subscribers[:] = [s for s in _sse_subscribers if s["id"] not in dead]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(v: Any) -> Optional[str]:
    """Parse un datetime en ISO 8601 UTC (accepte ISO strings ou timestamps)."""
    if not v:
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        # Format ISO avec ou sans TZ
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
        # Format "YYYY-MM-DD HH:MM:SS"
        try:
            dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            pass
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat()
        except (ValueError, OSError):
            return None
    return None


# ---------------------------------------------------------------------------
# Iter43-fix24az-z (2026-07-22) — Intelligent placement algorithm.
#
# When a new RDV arrives with a `start_at` that collides with an existing RDV
# for the same doctor (day), we search for the closest free slot around the
# requested time (before OR after) and place the appointment there. Returns
# the corrected (start_at, end_at, correction_applied, correction_reason).
# ---------------------------------------------------------------------------
def _find_free_slot(
    existing_intervals: List[tuple],  # [(start_iso, end_iso), ...] sorted by start
    requested_start_iso: str,
    duration_min: int,
    max_search_days: int = 1,
) -> tuple:
    """Search for a free slot of `duration_min` minutes as close as possible
    to `requested_start_iso`. Explores gaps between existing intervals and
    picks the one whose start (or end) is closest to the requested time.

    Returns (start_iso, end_iso). If the requested time is already free,
    returns it unchanged.
    """
    try:
        req_start = datetime.fromisoformat(requested_start_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return requested_start_iso, requested_start_iso
    req_end = req_start + timedelta(minutes=duration_min)

    def _overlaps(a_start: datetime, a_end: datetime, b_start_iso: str, b_end_iso: str) -> bool:
        try:
            b_start = datetime.fromisoformat(b_start_iso.replace("Z", "+00:00"))
            b_end = datetime.fromisoformat(b_end_iso.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return False
        return a_start < b_end and b_start < a_end

    # 1) Requested slot free ? Return as-is.
    if not any(_overlaps(req_start, req_end, s, e) for s, e in existing_intervals):
        return req_start.isoformat(), req_end.isoformat()

    # 2) Compute candidate free gaps :
    #    - Before the first interval (from start-of-day-window to first.start)
    #    - Between each pair of intervals
    #    - After the last interval (until end-of-day-window)
    day_min = req_start.replace(hour=0, minute=0, second=0, microsecond=0)
    day_max = day_min + timedelta(days=max_search_days)

    parsed: List[tuple] = []
    for s, e in existing_intervals:
        try:
            parsed.append((
                datetime.fromisoformat(s.replace("Z", "+00:00")),
                datetime.fromisoformat(e.replace("Z", "+00:00")),
            ))
        except (ValueError, AttributeError):
            continue
    parsed.sort(key=lambda t: t[0])

    gaps: List[tuple] = []  # (gap_start_dt, gap_end_dt)
    prev_end = day_min
    for s, e in parsed:
        if s > prev_end:
            gaps.append((prev_end, s))
        prev_end = max(prev_end, e)
    if prev_end < day_max:
        gaps.append((prev_end, day_max))

    # 3) Filter gaps that can accommodate the requested duration
    delta = timedelta(minutes=duration_min)
    fitting = [(gs, ge) for gs, ge in gaps if (ge - gs) >= delta]
    if not fitting:
        # Nothing fits within the search window — return requested unchanged
        # (caller will still upsert, but the correction_reason will note it).
        return req_start.isoformat(), req_end.isoformat()

    # 4) Pick the gap whose closest edge is nearest to req_start.
    def _distance(gap: tuple) -> timedelta:
        gs, ge = gap
        if req_start >= gs and req_start + delta <= ge:
            return timedelta(0)  # req fits inside this gap
        # Closest possible start within the gap
        candidate_start = min(max(req_start, gs), ge - delta)
        return abs(candidate_start - req_start)

    best_gap = min(fitting, key=_distance)
    gs, ge = best_gap
    # Place at the closest position inside the gap
    candidate_start = min(max(req_start, gs), ge - delta)
    return candidate_start.isoformat(), (candidate_start + delta).isoformat()


def _walk_in_list_key(day_iso: str, medecin_email: Optional[str], domaine: Optional[str]) -> str:
    """Build the walk-in list identifier `YYMMDD:medecin_email:domaine`.
    `medecin_email` and `domaine` are lowercased ; missing values → `unknown`.
    """
    try:
        dt = datetime.fromisoformat(day_iso.replace("Z", "+00:00")) if day_iso else datetime.now(timezone.utc)
    except (ValueError, AttributeError):
        dt = datetime.now(timezone.utc)
    day_key = dt.strftime("%y%m%d")
    email_key = (medecin_email or "unknown").lower().strip() or "unknown"
    dom_key = (domaine or "unknown").lower().strip() or "unknown"
    return f"{day_key}:{email_key}:{dom_key}"


class PlanningConfigUpdate(BaseModel):
    planning_webhook_secret: Optional[str] = Field(None, description="Secret du webhook (32 chars)")
    regenerate: Optional[bool] = Field(False, description="Génère un nouveau secret aléatoire")
    reminder_template: Optional[str] = Field(None, description="Template WA (placeholders {patient}, {medecin}, {start_time}, {motif})")


def attach_planning_routes(
    *,
    api,
    db,
    get_current_user,
    get_current_admin,
    _is_admin_or_superviseur,
    _resolve_visible_client_ids,
    _is_super_admin,
    _public_base_url,
    wa_send_text: Optional[Callable[..., Awaitable[dict]]] = None,
    wa_send_template: Optional[Callable[..., Awaitable[dict]]] = None,
    jwt_decode: Optional[Callable[[str], dict]] = None,
    users_collection_getter: Optional[Callable[[], Any]] = None,
):
    """Monte les endpoints du module Planning."""

    async def _get_user_from_token(token: str) -> Optional[dict]:
        """Résout un utilisateur depuis un JWT (utilisé par les endpoints SSE)."""
        if not token or not jwt_decode:
            return None
        try:
            payload = jwt_decode(token)
        except Exception:  # noqa: BLE001
            return None
        uid = payload.get("sub")
        if not uid:
            return None
        return await db.users.find_one({"id": uid})

    # ---- Bootstrap : index Mongo ----
    async def _ensure_indexes():
        try:
            await db.planning_appointments.create_index("tenant_id")
            await db.planning_appointments.create_index([("tenant_id", 1), ("start_at", 1)])
            await db.planning_appointments.create_index([("tenant_id", 1), ("medecin_id", 1), ("start_at", 1)])
            await db.planning_appointments.create_index(
                [("tenant_id", 1), ("code_clinique", 1), ("medecin", 1), ("patient", 1), ("start_at", 1)],
                unique=True,
                name="planning_unique_key",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[planning] index creation failed (may already exist): %s", exc)

    # -----------------------------------------------------------------
    # Iter43-fix24az-n — Reminders WA 1h avant RDV (invocable via cron + admin endpoint)
    # -----------------------------------------------------------------
    async def run_planning_wa_reminders_impl() -> Dict[str, Any]:
        """Envoie un rappel WA à chaque patient dont le RDV commence dans ~1h.
        - Fenêtre : `start_at ∈ [now+55min, now+65min]`
        - Filtre : `reminder_sent_at` absent + `patient_phone` défini
        - Template configurable via `settings.global.planning_reminder_template`
          (placeholders: {patient}, {medecin}, {start_time}, {motif})
        """
        if not wa_send_text:
            return {"ok": False, "sent": 0, "skipped": 0, "error": "wa_send_text non fourni"}

        now = datetime.now(timezone.utc)
        window_start = now + timedelta(minutes=55)
        window_end = now + timedelta(minutes=65)

        s = await db.settings.find_one({"_id": "global"}) or {}
        template = (s.get("planning_reminder_template") or "").strip() or (
            "Bonjour {patient}, rappel : votre rendez-vous avec {medecin} est prévu à {start_time}. "
            "Motif : {motif}. Merci de vous présenter 10 minutes en avance. — SAWALI"
        )

        query = {
            "start_at": {"$gte": window_start.isoformat(), "$lt": window_end.isoformat()},
            "patient_phone": {"$ne": None, "$exists": True, "$nin": ["", None]},
            "$or": [
                {"reminder_sent_at": None},
                {"reminder_sent_at": {"$exists": False}},
            ],
        }

        sent = 0
        skipped = 0
        errors: List[str] = []
        async for rdv in db.planning_appointments.find(query, {"_id": 0}):
            patient_phone = (rdv.get("patient_phone") or "").strip()
            if not patient_phone:
                skipped += 1
                continue
            try:
                start_iso = rdv.get("start_at") or ""
                try:
                    dt = datetime.fromisoformat(start_iso)
                    start_time = dt.strftime("%H:%M UTC")
                except Exception:  # noqa: BLE001
                    start_time = start_iso[11:16] if len(start_iso) > 16 else start_iso
                text = template.format(
                    patient=rdv.get("patient") or "",
                    medecin=rdv.get("medecin") or "",
                    start_time=start_time,
                    motif=rdv.get("motif") or "consultation",
                )
                result = await wa_send_text(patient_phone, text)
                status = "sent" if result and result.get("ok") else "failed"
                await db.planning_appointments.update_one(
                    {"id": rdv["id"]},
                    {"$set": {
                        "reminder_sent_at": _now_iso(),
                        "reminder_status": status,
                        "reminder_message_id": (result or {}).get("message_id"),
                        "reminder_error": (result or {}).get("error"),
                    }},
                )
                if status == "sent":
                    sent += 1
                else:
                    skipped += 1
                    errors.append(f"{rdv['id']}:{(result or {}).get('error')}")
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                errors.append(f"{rdv['id']}:{exc}")
        if sent or skipped:
            logger.info("[planning] WA reminders — sent=%d skipped=%d window=[+55,+65]min", sent, skipped)
        return {"ok": True, "sent": sent, "skipped": skipped, "errors": errors[:5]}

    # -----------------------------------------------------------------
    # ADMIN CONFIG
    # -----------------------------------------------------------------
    @api.get("/admin/planning/config", tags=["Admin — Planning"])
    async def admin_planning_config(request: Request, user: dict = Depends(get_current_admin)):
        s = await db.settings.find_one({"_id": "global"}) or {}
        secret = s.get("planning_webhook_secret")
        if not secret:
            secret = secrets.token_urlsafe(24)
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {"planning_webhook_secret": secret, "planning_webhook_created_at": _now_iso()}},
                upsert=True,
            )
        base = _public_base_url(request) or str(request.base_url).rstrip("/")
        return {
            "planning_webhook_secret": secret,
            "webhook_url": f"{base}/api/webhooks/planning/{secret}",
            "webhook_created_at": s.get("planning_webhook_created_at"),
            "reminder_template": s.get("planning_reminder_template") or "",
            "sample_payload": {
                "code_clinique": "CLI-001",
                "medecin": "Dr. Aissata Ouedraogo",
                "medecin_email": "aissata@clinique.bf",
                "patient": "Fatimata KANE",
                "patient_phone": "+22670001122",
                "start": "2026-07-18T09:00:00Z",
                "end": "2026-07-18T09:30:00Z",
                "motif": "Consultation générale",
                "id_user": "cli-user-42",
                "external_id": "RDV-2026-000123",
            },
        }

    @api.put("/admin/planning/config", tags=["Admin — Planning"])
    async def admin_planning_config_update(
        payload: PlanningConfigUpdate,
        request: Request,
        user: dict = Depends(get_current_admin),
    ):
        s = await db.settings.find_one({"_id": "global"}) or {}
        current = s.get("planning_webhook_secret") or ""
        if payload.regenerate:
            new_secret = secrets.token_urlsafe(24)
        elif payload.planning_webhook_secret is not None:
            new_secret = (payload.planning_webhook_secret or "").strip()
            if new_secret and not re.match(r"^[A-Za-z0-9_-]{16,64}$", new_secret):
                raise HTTPException(
                    status_code=400,
                    detail="Secret invalide (16-64 caractères alphanumériques, _, -).",
                )
        else:
            new_secret = current or secrets.token_urlsafe(24)
        set_doc: Dict[str, Any] = {
            "planning_webhook_secret": new_secret,
            "planning_webhook_updated_at": _now_iso(),
            "planning_webhook_updated_by": user.get("email"),
        }
        if payload.reminder_template is not None:
            set_doc["planning_reminder_template"] = payload.reminder_template.strip()
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": set_doc},
            upsert=True,
        )
        base = _public_base_url(request) or str(request.base_url).rstrip("/")
        return {
            "ok": True,
            "planning_webhook_secret": new_secret,
            "webhook_url": f"{base}/api/webhooks/planning/{new_secret}",
            "reminder_template": set_doc.get("planning_reminder_template", ""),
        }

    @api.post("/admin/planning/reminders/run", tags=["Admin — Planning"])
    async def admin_planning_reminders_run_now(user: dict = Depends(get_current_admin)):
        """Iter43-fix24az-n — Déclenche manuellement le job de rappels WA
        (utile pour démo/débug). Retourne le nombre de messages envoyés.
        """
        return await run_planning_wa_reminders_impl()

    # -----------------------------------------------------------------
    # WEBHOOK PUBLIC (no auth)
    # -----------------------------------------------------------------
    @api.post("/webhooks/planning/{secret}", tags=["Webhooks"])
    async def planning_webhook_receive(secret: str, request: Request):
        """Reçoit un RDV depuis un système externe (planning clinique).
        Payload minimum : {code_clinique, medecin, patient, start, end}.
        Champs optionnels : motif, id_user, medecin_email, external_id.
        Idempotent : upsert sur (tenant_id, code_clinique, medecin, patient, start_at).
        """
        s = await db.settings.find_one({"_id": "global"}) or {}
        expected = (s.get("planning_webhook_secret") or "").strip()
        if not expected or not secrets.compare_digest(secret, expected):
            # 404 (masque l'existence de l'endpoint) plutôt que 401.
            raise HTTPException(status_code=404, detail="Not found")

        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"JSON invalide : {exc}") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Payload doit être un objet JSON")

        # Validation champs obligatoires
        required = ["code_clinique", "medecin", "patient"]
        missing = [k for k in required if not (body.get(k) or "").strip()] if isinstance(body.get("code_clinique"), str) else required
        # Recompute missing more robustly
        missing = []
        for k in required:
            v = body.get(k)
            if not isinstance(v, str) or not v.strip():
                missing.append(k)
        if missing:
            raise HTTPException(status_code=400, detail=f"Champs obligatoires manquants : {', '.join(missing)}")
        start_at = _parse_dt(body.get("start") or body.get("start_at") or body.get("debut"))
        end_at = _parse_dt(body.get("end") or body.get("end_at") or body.get("fin"))
        # Iter43-fix24az-z (2026-07-22) — Walk-ins (is_rdv=0) n'ont pas
        # d'horaire fixé : ils sont juste stockés dans la liste avec un
        # `numero_ordre`. Le médecin les appelle dans l'ordre d'arrivée.
        # Pour les RDV (is_rdv=1), start_at reste obligatoire.
        raw_is_rdv_check = body.get("is_rdv", 1)
        try:
            _is_rdv_early = 1 if int(raw_is_rdv_check) == 1 else 0
        except Exception:  # noqa: BLE001
            _is_rdv_early = 1 if str(raw_is_rdv_check).strip().lower() in ("1", "true", "yes", "oui") else 0
        if _is_rdv_early == 1 and not start_at:
            raise HTTPException(status_code=400, detail="Champ 'start' invalide (ISO 8601 requis pour un RDV)")
        if start_at and not end_at:
            # end défaut = start + 30min
            try:
                sdt = datetime.fromisoformat(start_at)
                end_at = (sdt + timedelta(minutes=30)).isoformat()
            except Exception:  # noqa: BLE001
                end_at = start_at

        code_clinique = body["code_clinique"].strip()
        medecin_name = body["medecin"].strip()
        patient = body["patient"].strip()
        medecin_email = (body.get("medecin_email") or "").strip().lower() or None
        id_user = (body.get("id_user") or body.get("iduser") or "").strip() or None
        motif = (body.get("motif") or body.get("reason") or "").strip() or None
        external_id = (body.get("external_id") or body.get("externalId") or "").strip() or None
        # Iter43-fix24az-n — coordonnées patient pour les rappels WA 1h avant RDV
        patient_phone_raw = (body.get("patient_phone") or body.get("phone") or "").strip() or None
        patient_email = (body.get("patient_email") or "").strip().lower() or None
        # Iter43-fix24az-z (2026-07-22) — Nouveaux champs pour gestion
        # intelligente du planning (RDV vs walk-in / patients sans RDV).
        #   - `is_rdv`      : 1 = RDV planifié, 0 = walk-in (sans RDV).
        #                     Défaut : 1 pour rétro-compatibilité.
        #   - `numero_liste`: numéro de la liste de consultation (optionnel,
        #                     chaîne libre — ex: "L01", "matin", "42").
        #   - `numero_ordre`: rang du patient dans la liste. Si vide, on
        #                     attribue le prochain numéro chronologique.
        #   - `domaine`     : spécialité médicale libre (gyneco, pédiatrie…).
        # Les walk-ins (is_rdv=0) n'ont PAS besoin de `start_at`/`end_at` :
        # le médecin les traite dans l'ordre d'arrivée (`numero_ordre`).
        raw_is_rdv = body.get("is_rdv", 1)
        try:
            is_rdv = 1 if int(raw_is_rdv) == 1 else 0
        except Exception:  # noqa: BLE001
            is_rdv = 1 if str(raw_is_rdv).strip().lower() in ("1", "true", "yes", "oui") else 0
        numero_liste = (str(body.get("numero_liste") or body.get("liste_num") or "").strip() or None)
        raw_numero_ordre = body.get("numero_ordre")
        if raw_numero_ordre in (None, "", "null"):
            numero_ordre = None
        else:
            try:
                numero_ordre = int(raw_numero_ordre)
            except (TypeError, ValueError):
                numero_ordre = None
        domaine = (body.get("domaine") or body.get("specialite") or "").strip().lower() or None

        # Résout le tenant_id : par défaut super-admin du système. Si medecin_email
        # correspond à un utilisateur tracked, on utilise SON tenant.
        #
        # Iter43-fix24az-x (2026-07-22) — Bug prod : les médecins créés via
        # l'ancien chemin (sans bridged users row) OU dont l'email stocké en
        # base a une casse différente n'étaient pas résolus → tenant_id
        # tombait sur le super-admin fallback, et la scope du médecin lecteur
        # ne contenait pas ce tenant_id → tous les RDV invisibles.
        # Fix : (a) lookup case-insensitive, (b) fallback vers tracked_users
        # avec propagation de son user_account_id (bridged) comme medecin_id
        # + client_id (parent) comme tenant_id.
        tenant_id: Optional[str] = None
        medecin_id: Optional[str] = None
        if medecin_email:
            import re as _re
            email_regex = f"^{_re.escape(medecin_email)}$"
            u = await db.users.find_one(
                {"email": {"$regex": email_regex, "$options": "i"}},
                {"_id": 0, "id": 1, "client_id": 1, "parent_client_id": 1},
            )
            if u:
                medecin_id = u.get("id")
                tenant_id = u.get("parent_client_id") or u.get("client_id") or u.get("id")
            else:
                # Fallback : chercher dans tracked_users (cas d'un médecin
                # créé sans bridge users row, ou avec casse divergente).
                tu = await db.tracked_users.find_one(
                    {"email": {"$regex": email_regex, "$options": "i"}},
                    {"_id": 0, "id": 1, "client_id": 1, "user_account_id": 1},
                )
                if tu:
                    # Utilise l'id du bridged user si dispo (pour matcher côté
                    # GET où user.id == bridged users.id), sinon l'id tracked.
                    medecin_id = tu.get("user_account_id") or tu.get("id")
                    tenant_id = tu.get("client_id") or medecin_id
        if not tenant_id:
            # Fallback : super-admin comme tenant (le RDV apparaîtra dans le portail admin)
            admin = await db.users.find_one({"email": "admin@sawalismartsystems.com"}, {"_id": 0, "id": 1})
            tenant_id = (admin or {}).get("id") or "_global_"

        now = _now_iso()

        # Iter43-fix24az-z — Placement intelligent + gestion walk-ins.
        correction_applied = False
        correction_reason: Optional[str] = None
        original_start = start_at
        original_end = end_at
        walk_in_list = None
        assigned_numero_ordre = numero_ordre

        if is_rdv == 1 and start_at:
            # RDV : vérifie collisions avec autres RDV du même médecin le
            # même jour. Si conflit → chercher le slot libre le plus proche.
            try:
                day_start_dt = datetime.fromisoformat(start_at.replace("Z", "+00:00")).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                day_end_dt = day_start_dt + timedelta(days=1)
            except (ValueError, AttributeError):
                day_start_dt = None
                day_end_dt = None
            if day_start_dt is not None:
                # Requête : autres RDV (is_rdv=1) du médecin le même jour
                # (par medecin_id OU medecin_email).
                collision_q: Dict[str, Any] = {
                    "tenant_id": tenant_id,
                    "start_at": {"$gte": day_start_dt.isoformat(), "$lt": day_end_dt.isoformat()},
                    "is_rdv": {"$ne": 0},  # inclut RDV existants (défaut = 1)
                }
                med_or: List[Dict[str, Any]] = []
                if medecin_id:
                    med_or.append({"medecin_id": medecin_id})
                if medecin_email:
                    med_or.append({"medecin_email": medecin_email})
                if med_or:
                    collision_q["$or"] = med_or
                # Exclure le doc en cours (upsert idempotent : le doc existant
                # sur (code_clinique, medecin, patient, start_at) peut être
                # ré-envoyé sans être considéré comme collision).
                cursor = db.planning_appointments.find(
                    collision_q,
                    {"_id": 0, "start_at": 1, "end_at": 1, "patient": 1, "code_clinique": 1},
                )
                existing_intervals: List[tuple] = []
                async for doc in cursor:
                    # Skip the "same" doc (same code_clinique + patient + start_at)
                    if (doc.get("code_clinique") == code_clinique
                        and doc.get("patient") == patient
                        and doc.get("start_at") == start_at):
                        continue
                    if doc.get("start_at") and doc.get("end_at"):
                        existing_intervals.append((doc["start_at"], doc["end_at"]))
                if existing_intervals:
                    try:
                        sdt = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
                        edt = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
                        duration_min = max(15, int((edt - sdt).total_seconds() / 60))
                    except (ValueError, AttributeError):
                        duration_min = 30
                    new_start, new_end = _find_free_slot(
                        existing_intervals,
                        start_at,
                        duration_min,
                    )
                    if new_start != start_at:
                        correction_applied = True
                        correction_reason = "créneau occupé par un autre RDV — déplacé au slot libre le plus proche"
                        start_at, end_at = new_start, new_end

        elif is_rdv == 0:
            # Walk-in : pas de start_at/end_at requis. On calcule la clé
            # de liste + on assigne un numero_ordre chronologique si absent.
            walk_in_list = _walk_in_list_key(
                start_at or now,
                medecin_email,
                domaine,
            )
            if assigned_numero_ordre is None:
                # Prochain numero_ordre = MAX(existing_numero_ordre) + 1
                cursor2 = db.planning_appointments.find(
                    {"tenant_id": tenant_id, "walk_in_list": walk_in_list, "is_rdv": 0},
                    {"_id": 0, "numero_ordre": 1},
                )
                max_ord = 0
                async for d in cursor2:
                    try:
                        no = int(d.get("numero_ordre") or 0)
                        if no > max_ord:
                            max_ord = no
                    except (TypeError, ValueError):
                        pass
                assigned_numero_ordre = max_ord + 1

        upsert_query = {
            "tenant_id": tenant_id,
            "code_clinique": code_clinique,
            "medecin": medecin_name,
            "patient": patient,
            "start_at": start_at,
        } if is_rdv == 1 else {
            # Walk-ins n'ont pas de start_at : idempotence sur (list_key, patient, numero_ordre)
            "tenant_id": tenant_id,
            "walk_in_list": walk_in_list,
            "patient": patient,
            "numero_ordre": assigned_numero_ordre,
        }
        set_doc = {
            "end_at": end_at,
            "medecin_id": medecin_id,
            "medecin_email": medecin_email,
            "id_user": id_user,
            "motif": motif,
            "external_id": external_id,
            "patient_phone": patient_phone_raw,
            "patient_email": patient_email,
            "source": "webhook",
            "updated_at": now,
            "received_at": now,
            # Iter43-fix24az-z
            "is_rdv": is_rdv,
            "numero_liste": numero_liste,
            "numero_ordre": assigned_numero_ordre,
            "domaine": domaine,
            "walk_in_list": walk_in_list,
            "original_start_at": original_start,
            "correction_applied": correction_applied,
            "correction_reason": correction_reason,
        }
        set_on_insert = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "code_clinique": code_clinique,
            "medecin": medecin_name,
            "patient": patient,
            "start_at": start_at,
            "created_at": now,
        }
        try:
            res = await db.planning_appointments.update_one(
                upsert_query,
                {"$set": set_doc, "$setOnInsert": set_on_insert},
                upsert=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[planning] webhook upsert failed: %s", exc)
            raise HTTPException(status_code=500, detail="Erreur d'enregistrement du RDV") from exc

        # Iter43-fix24az-n — Push l'événement aux abonnés SSE (temps réel)
        try:
            fresh = await db.planning_appointments.find_one(upsert_query, {"_id": 0})
            if fresh:
                await _sse_broadcast(
                    tenant_id,
                    "created" if res.upserted_id else "updated",
                    fresh,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[planning] SSE broadcast failed: %s", exc)

        return {
            "ok": True,
            "created": res.upserted_id is not None,
            "modified": res.modified_count > 0,
            "tenant_id": tenant_id,
            "medecin_id": medecin_id,
            # Iter43-fix24az-z — Retour enrichi pour l'appelant du webhook.
            "is_rdv": is_rdv,
            "placed_at": start_at,
            "placed_end_at": end_at,
            "original_start_at": original_start,
            "correction_applied": correction_applied,
            "correction_reason": correction_reason,
            "numero_ordre": assigned_numero_ordre,
            "numero_liste": numero_liste,
            "domaine": domaine,
            "walk_in_list": walk_in_list,
        }

    # -----------------------------------------------------------------
    # TENANT (médecin / admin / superviseur)
    # -----------------------------------------------------------------
    def _tenant_scope_for(user: dict) -> List[str]:
        """Résout la liste des tenant_ids visibles par l'utilisateur."""
        # Super-admin sees all (empty list = no filter)
        if _is_super_admin(user):
            return []
        return None  # sentinel handled below

    @api.get("/me/planning/doctors", tags=["Portail Client — Planning"])
    async def planning_list_doctors(user: dict = Depends(get_current_user)):
        """Liste les utilisateurs suivis avec role='Médecin' du tenant courant."""
        # Determine scope
        if _is_super_admin(user):
            query: Dict[str, Any] = {"tracked_role": "Médecin"}
        else:
            scope = await _resolve_visible_client_ids(user)
            query = {
                "tracked_role": "Médecin",
                "$or": [
                    {"parent_client_id": {"$in": scope}},
                    {"client_id": {"$in": scope}},
                ],
            }
        docs: List[Dict[str, Any]] = []
        async for u in db.users.find(
            query,
            {"_id": 0, "id": 1, "email": 1, "full_name": 1, "tracked_role": 1, "role": 1},
        ):
            docs.append({
                "id": u.get("id"),
                "email": u.get("email"),
                "full_name": u.get("full_name") or u.get("email") or "—",
            })
        # Dedup by id
        seen = set()
        out = []
        for d in docs:
            if d["id"] in seen:
                continue
            seen.add(d["id"])
            out.append(d)
        return {"doctors": sorted(out, key=lambda x: (x.get("full_name") or "").lower())}

    @api.get("/me/planning/appointments", tags=["Portail Client — Planning"])
    async def planning_list_appointments(
        date: Optional[str] = Query(None, description="Date YYYY-MM-DD (défaut = aujourd'hui UTC)"),
        medecin_id: Optional[str] = Query(None, description="Filtre par médecin (id user)"),
        user: dict = Depends(get_current_user),
    ):
        """Retourne les RDV pour une date donnée + optionnellement un médecin."""
        # Résolution date
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Date invalide (format YYYY-MM-DD attendu)")
        from datetime import timedelta
        day_end = day_start + timedelta(days=1)
        start_iso = day_start.isoformat()
        end_iso = day_end.isoformat()

        is_medecin = (user.get("tracked_role") or "") == "Médecin"

        # Détermine le filtre médecin
        effective_medecin_id = medecin_id
        if is_medecin:
            # Médecin ne voit QUE ses RDV — surcharge le medecin_id demandé
            effective_medecin_id = user.get("id")

        # Détermine le scope tenant
        #
        # Iter43-fix24az-x (2026-07-22) — Élargissement défensif du scope pour
        # les médecins tracked : inclure aussi le `client_id` du tracked_users
        # row (ancien chemin) + l'`id` super-admin en dernier recours si
        # l'utilisateur n'a pas de parent_client_id explicite. Empêche les
        # RDV insérés par webhook (avec tenant_id = super-admin fallback)
        # d'être invisibles pour un médecin dont la bridge est incomplète.
        if _is_super_admin(user):
            q: Dict[str, Any] = {}
        else:
            scope = list(await _resolve_visible_client_ids(user))
            # Si l'utilisateur est un médecin tracked, ajouter aussi le
            # client_id de son tracked_users row (au cas où il diffère du
            # parent_client_id du bridged user).
            if is_medecin:
                try:
                    tu = await db.tracked_users.find_one(
                        {"email": (user.get("email") or "").lower()},
                        {"_id": 0, "id": 1, "client_id": 1, "user_account_id": 1},
                    )
                    if tu:
                        for cand in (tu.get("client_id"), tu.get("id"), tu.get("user_account_id")):
                            if cand and cand not in scope:
                                scope.append(cand)
                except Exception:  # noqa: BLE001
                    pass
            q = {"tenant_id": {"$in": scope}}
        # Iter43-fix24az-z (2026-07-22) — Include walk-ins (is_rdv=0) qui
        # n'ont PAS de start_at. Filtre : RDV du jour (start_at in range)
        # OR walk-in dont walk_in_list commence par YYMMDD:.
        time_clauses: List[Dict[str, Any]] = [
            {"start_at": {"$gte": start_iso, "$lt": end_iso}},
        ]
        try:
            _day_key = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).strftime("%y%m%d")
            time_clauses.append({"walk_in_list": {"$regex": f"^{_day_key}:"}})
        except (ValueError, AttributeError):
            pass
        medecin_or_clauses: List[Dict[str, Any]] = []
        if effective_medecin_id:
            # Match soit medecin_id OU medecin_email correspondant à cet utilisateur.
            # Case-insensitive email pour tolérer les emails stockés en casse mixte.
            u = await db.users.find_one({"id": effective_medecin_id}, {"_id": 0, "id": 1, "email": 1})
            medecin_or_clauses.append({"medecin_id": effective_medecin_id})
            if u and u.get("email"):
                import re as _re
                email_re = f"^{_re.escape(u['email'].lower())}$"
                medecin_or_clauses.append({"medecin_email": {"$regex": email_re, "$options": "i"}})
            # Egalement : matcher via tracked_users id si le bridge n'a pas
            # été utilisé au moment de l'insertion (medecin_id contient le
            # tracked_users.id au lieu du bridged users.id).
            try:
                tu = await db.tracked_users.find_one(
                    {"user_account_id": effective_medecin_id},
                    {"_id": 0, "id": 1},
                )
                if tu and tu.get("id"):
                    medecin_or_clauses.append({"medecin_id": tu["id"]})
            except Exception:  # noqa: BLE001
                pass
        # Compose final query with $and to combine time + medecin filters.
        if medecin_or_clauses:
            q["$and"] = [{"$or": time_clauses}, {"$or": medecin_or_clauses}]
        else:
            q["$or"] = time_clauses

        items: List[Dict[str, Any]] = []
        async for row in db.planning_appointments.find(q, {"_id": 0}).sort([("start_at", 1), ("numero_ordre", 1)]).limit(500):
            items.append(row)
        return {
            "date": date,
            "count": len(items),
            "is_medecin_view": is_medecin,
            "medecin_id_locked": effective_medecin_id if is_medecin else None,
            "items": items,
        }

    # -----------------------------------------------------------------
    # Iter43-fix24az-aa (2026-07-22) — Live counters (sidebar badge +
    # planning header). Un seul endpoint alimente 2 usages :
    #   1) Badge sidebar médecin  → `today_walk_ins_open` (walk-ins d'auj.)
    #   2) Header planning        → `upcoming_rdv_count` + `upcoming_walk_in_count`
    #      (à partir de la date sélectionnée + 1 jour, dans les 90j).
    # -----------------------------------------------------------------
    @api.get("/me/planning/counts", tags=["Portail Client — Planning"])
    async def planning_counts(
        date: Optional[str] = Query(None, description="Date de référence YYYY-MM-DD (défaut = aujourd'hui UTC)"),
        medecin_id: Optional[str] = Query(None, description="Filtre par médecin (admin/superviseur)"),
        horizon_days: int = Query(90, ge=1, le=365, description="Fenêtre pour les `upcoming_*` (défaut 90j)"),
        user: dict = Depends(get_current_user),
    ):
        """Compteurs live pour la sidebar et le header planning.

        Retourne :
          - `today_walk_ins_open` : walk-ins ouverts pour AUJOURD'HUI (peu importe la date)
          - `upcoming_rdv_count`  : RDV à partir de `date + 1 jour` sur `horizon_days`
          - `upcoming_walk_in_count` : walk-ins à partir de `date + 1 jour` sur `horizon_days`
          - `date`, `from_date`, `horizon_days` (echo pour le frontend)
        """
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            ref_day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Date invalide (YYYY-MM-DD)")
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        from_day = ref_day + timedelta(days=1)
        horizon_day = from_day + timedelta(days=horizon_days)

        # Détermine le médecin ciblé (médecin logé se voit lui-même,
        # admin/superviseur peuvent filtrer par medecin_id).
        is_medecin = (user.get("tracked_role") or "") == "Médecin"
        effective_medecin_id: Optional[str] = None
        if is_medecin:
            effective_medecin_id = user.get("id")
        elif medecin_id:
            effective_medecin_id = medecin_id

        # Tenant scope (élargi si médecin — voir fix24az-x)
        if _is_super_admin(user):
            base_q: Dict[str, Any] = {}
        else:
            scope = list(await _resolve_visible_client_ids(user))
            if is_medecin:
                try:
                    tu = await db.tracked_users.find_one(
                        {"email": (user.get("email") or "").lower()},
                        {"_id": 0, "id": 1, "client_id": 1, "user_account_id": 1},
                    )
                    if tu:
                        for cand in (tu.get("client_id"), tu.get("id"), tu.get("user_account_id")):
                            if cand and cand not in scope:
                                scope.append(cand)
                except Exception:  # noqa: BLE001
                    pass
            base_q = {"tenant_id": {"$in": scope}}

        # Match médecin (via medecin_id OU medecin_email)
        medecin_or: List[Dict[str, Any]] = []
        if effective_medecin_id:
            u = await db.users.find_one({"id": effective_medecin_id}, {"_id": 0, "id": 1, "email": 1})
            medecin_or.append({"medecin_id": effective_medecin_id})
            if u and u.get("email"):
                email_re = f"^{re.escape(u['email'].lower())}$"
                medecin_or.append({"medecin_email": {"$regex": email_re, "$options": "i"}})
            try:
                tu = await db.tracked_users.find_one(
                    {"user_account_id": effective_medecin_id}, {"_id": 0, "id": 1},
                )
                if tu and tu.get("id"):
                    medecin_or.append({"medecin_id": tu["id"]})
            except Exception:  # noqa: BLE001
                pass

        def _with_medecin(q: Dict[str, Any]) -> Dict[str, Any]:
            if medecin_or:
                return {**base_q, "$and": [q, {"$or": medecin_or}]}
            return {**base_q, **q}

        # 1) Walk-ins ouverts AUJOURD'HUI (clé walk_in_list préfixée YYMMDD auj.)
        today_key = today.strftime("%y%m%d")
        today_walk_ins_open = await db.planning_appointments.count_documents(
            _with_medecin({
                "is_rdv": 0,
                "walk_in_list": {"$regex": f"^{today_key}:"},
            })
        )

        # 2) RDV à venir (start_at >= from_day && < horizon)
        upcoming_rdv_count = await db.planning_appointments.count_documents(
            _with_medecin({
                "start_at": {"$gte": from_day.isoformat(), "$lt": horizon_day.isoformat()},
                "is_rdv": {"$ne": 0},
            })
        )

        # 3) Walk-ins à venir (walk_in_list préfixé par un jour dans le futur)
        # On construit un $or sur les préfixes YYMMDD des jours [from_day, horizon).
        future_prefixes: List[Dict[str, Any]] = []
        cursor_day = from_day
        while cursor_day < horizon_day:
            prefix = cursor_day.strftime("%y%m%d")
            future_prefixes.append({"walk_in_list": {"$regex": f"^{prefix}:"}})
            cursor_day += timedelta(days=1)
        upcoming_walk_in_count = 0
        if future_prefixes:
            upcoming_walk_in_count = await db.planning_appointments.count_documents(
                _with_medecin({"is_rdv": 0, "$or": future_prefixes})
            )

        return {
            "date": date,
            "from_date": from_day.strftime("%Y-%m-%d"),
            "horizon_days": horizon_days,
            "medecin_id": effective_medecin_id,
            "today_walk_ins_open": today_walk_ins_open,
            "upcoming_rdv_count": upcoming_rdv_count,
            "upcoming_walk_in_count": upcoming_walk_in_count,
        }

    # -----------------------------------------------------------------
    # Iter43-fix24az-ab (2026-07-22) — Next busy day. Retourne la première
    # date >= `after` où le médecin a AU MOINS 1 RDV ou walk-in. Alimente
    # le chip cliquable "Dès le DD/MM" du header planning : clic → saute
    # au prochain jour chargé.
    # -----------------------------------------------------------------
    @api.get("/me/planning/next-busy-day", tags=["Portail Client — Planning"])
    async def planning_next_busy_day(
        after: Optional[str] = Query(None, description="Date de départ YYYY-MM-DD (défaut = demain UTC)"),
        medecin_id: Optional[str] = Query(None, description="Filtre par médecin (admin/superviseur)"),
        horizon_days: int = Query(90, ge=1, le=365, description="Fenêtre de recherche (défaut 90j)"),
        user: dict = Depends(get_current_user),
    ):
        if not after:
            after = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            after_dt = datetime.strptime(after, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Date invalide (YYYY-MM-DD)")
        horizon_dt = after_dt + timedelta(days=horizon_days)

        # Détermine le médecin ciblé (même logique que /counts).
        is_medecin = (user.get("tracked_role") or "") == "Médecin"
        effective_medecin_id: Optional[str] = None
        if is_medecin:
            effective_medecin_id = user.get("id")
        elif medecin_id:
            effective_medecin_id = medecin_id

        # Tenant scope
        if _is_super_admin(user):
            base_q: Dict[str, Any] = {}
        else:
            scope = list(await _resolve_visible_client_ids(user))
            if is_medecin:
                try:
                    tu = await db.tracked_users.find_one(
                        {"email": (user.get("email") or "").lower()},
                        {"_id": 0, "id": 1, "client_id": 1, "user_account_id": 1},
                    )
                    if tu:
                        for cand in (tu.get("client_id"), tu.get("id"), tu.get("user_account_id")):
                            if cand and cand not in scope:
                                scope.append(cand)
                except Exception:  # noqa: BLE001
                    pass
            base_q = {"tenant_id": {"$in": scope}}

        # Match médecin
        medecin_or: List[Dict[str, Any]] = []
        if effective_medecin_id:
            u = await db.users.find_one({"id": effective_medecin_id}, {"_id": 0, "id": 1, "email": 1})
            medecin_or.append({"medecin_id": effective_medecin_id})
            if u and u.get("email"):
                email_re = f"^{re.escape(u['email'].lower())}$"
                medecin_or.append({"medecin_email": {"$regex": email_re, "$options": "i"}})
            try:
                tu = await db.tracked_users.find_one(
                    {"user_account_id": effective_medecin_id}, {"_id": 0, "id": 1},
                )
                if tu and tu.get("id"):
                    medecin_or.append({"medecin_id": tu["id"]})
            except Exception:  # noqa: BLE001
                pass

        # 1) 1er RDV avec start_at >= after_dt
        rdv_q: Dict[str, Any] = {
            **base_q,
            "is_rdv": {"$ne": 0},
            "start_at": {"$gte": after_dt.isoformat(), "$lt": horizon_dt.isoformat()},
        }
        if medecin_or:
            rdv_q["$or"] = medecin_or
        first_rdv = await db.planning_appointments.find_one(
            rdv_q, {"_id": 0, "start_at": 1}, sort=[("start_at", 1)],
        )
        rdv_date = (first_rdv or {}).get("start_at", "")[:10] if first_rdv else None

        # 2) 1er walk-in avec walk_in_list préfixé par un jour >= after
        # On construit un $or sur les préfixes YYMMDD des jours de la fenêtre.
        walk_prefixes: List[Dict[str, Any]] = []
        cursor_day = after_dt
        while cursor_day < horizon_dt:
            walk_prefixes.append({"walk_in_list": {"$regex": f"^{cursor_day.strftime('%y%m%d')}:"}})
            cursor_day += timedelta(days=1)
        walk_date: Optional[str] = None
        if walk_prefixes:
            walk_q: Dict[str, Any] = {**base_q, "is_rdv": 0, "$or": walk_prefixes}
            if medecin_or:
                # $or utilisé pour walk_prefixes, on wrap dans $and pour éviter la collision
                walk_q = {**base_q, "$and": [{"is_rdv": 0, "$or": walk_prefixes},
                                              {"$or": medecin_or}]}
            first_walk = await db.planning_appointments.find_one(
                walk_q, {"_id": 0, "walk_in_list": 1, "created_at": 1},
                sort=[("walk_in_list", 1)],
            )
            if first_walk and first_walk.get("walk_in_list"):
                # walk_in_list = YYMMDD:email:domaine → extraire la date
                key = first_walk["walk_in_list"].split(":", 1)[0]
                if len(key) == 6 and key.isdigit():
                    walk_date = f"20{key[0:2]}-{key[2:4]}-{key[4:6]}"

        # Prend la plus proche des deux dates
        candidates = [d for d in (rdv_date, walk_date) if d]
        next_date = min(candidates) if candidates else None

        return {
            "after": after,
            "next_busy_date": next_date,
            "has_rdv": bool(rdv_date),
            "has_walk_in": bool(walk_date),
            "horizon_days": horizon_days,
        }

    # -----------------------------------------------------------------
    # Iter43-fix24az-ad (2026-07-22) — Heatmap N jours. Retourne un tableau
    # de compteurs par jour (RDV + walk-ins) pour alimenter la mini-heatmap
    # latérale du planning. Permet au médecin de repérer les jours chargés
    # d'un coup d'œil.
    # -----------------------------------------------------------------
    @api.get("/me/planning/heatmap", tags=["Portail Client — Planning"])
    async def planning_heatmap(
        from_date: Optional[str] = Query(None, description="Date de début YYYY-MM-DD (défaut = aujourd'hui UTC)"),
        days: int = Query(30, ge=1, le=90, description="Nombre de jours (défaut 30)"),
        medecin_id: Optional[str] = Query(None, description="Filtre par médecin (admin/superviseur)"),
        user: dict = Depends(get_current_user),
    ):
        if not from_date:
            from_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            start_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Date invalide (YYYY-MM-DD)")
        end_dt = start_dt + timedelta(days=days)

        # Détermine le médecin (même logique que /counts + /next-busy-day)
        is_medecin = (user.get("tracked_role") or "") == "Médecin"
        effective_medecin_id: Optional[str] = None
        if is_medecin:
            effective_medecin_id = user.get("id")
        elif medecin_id:
            effective_medecin_id = medecin_id

        if _is_super_admin(user):
            base_q: Dict[str, Any] = {}
        else:
            scope = list(await _resolve_visible_client_ids(user))
            if is_medecin:
                try:
                    tu = await db.tracked_users.find_one(
                        {"email": (user.get("email") or "").lower()},
                        {"_id": 0, "id": 1, "client_id": 1, "user_account_id": 1},
                    )
                    if tu:
                        for cand in (tu.get("client_id"), tu.get("id"), tu.get("user_account_id")):
                            if cand and cand not in scope:
                                scope.append(cand)
                except Exception:  # noqa: BLE001
                    pass
            base_q = {"tenant_id": {"$in": scope}}

        medecin_or: List[Dict[str, Any]] = []
        if effective_medecin_id:
            u = await db.users.find_one({"id": effective_medecin_id}, {"_id": 0, "id": 1, "email": 1})
            medecin_or.append({"medecin_id": effective_medecin_id})
            if u and u.get("email"):
                email_re = f"^{re.escape(u['email'].lower())}$"
                medecin_or.append({"medecin_email": {"$regex": email_re, "$options": "i"}})
            try:
                tu = await db.tracked_users.find_one(
                    {"user_account_id": effective_medecin_id}, {"_id": 0, "id": 1},
                )
                if tu and tu.get("id"):
                    medecin_or.append({"medecin_id": tu["id"]})
            except Exception:  # noqa: BLE001
                pass

        def _with_medecin(q: Dict[str, Any]) -> Dict[str, Any]:
            if medecin_or:
                return {**base_q, "$and": [q, {"$or": medecin_or}]}
            return {**base_q, **q}

        # Initialise le tableau : 1 entrée par jour dans la fenêtre.
        counts_by_day: Dict[str, Dict[str, int]] = {}
        cursor_day = start_dt
        while cursor_day < end_dt:
            iso = cursor_day.strftime("%Y-%m-%d")
            counts_by_day[iso] = {"date": iso, "rdv_count": 0, "walk_in_count": 0}
            cursor_day += timedelta(days=1)

        # 1) Compte les RDV — agrège par jour (extrait YYYY-MM-DD de start_at).
        rdv_q = _with_medecin({
            "is_rdv": {"$ne": 0},
            "start_at": {"$gte": start_dt.isoformat(), "$lt": end_dt.isoformat()},
        })
        async for doc in db.planning_appointments.find(rdv_q, {"_id": 0, "start_at": 1}):
            iso = (doc.get("start_at") or "")[:10]
            if iso in counts_by_day:
                counts_by_day[iso]["rdv_count"] += 1

        # 2) Compte les walk-ins — extrait YYMMDD du champ walk_in_list.
        walk_prefix_or: List[Dict[str, Any]] = []
        cursor_day = start_dt
        while cursor_day < end_dt:
            walk_prefix_or.append({"walk_in_list": {"$regex": f"^{cursor_day.strftime('%y%m%d')}:"}})
            cursor_day += timedelta(days=1)
        if walk_prefix_or:
            walk_q = _with_medecin({"is_rdv": 0, "$or": walk_prefix_or})
            async for doc in db.planning_appointments.find(walk_q, {"_id": 0, "walk_in_list": 1}):
                key = (doc.get("walk_in_list") or "").split(":", 1)[0]
                if len(key) == 6 and key.isdigit():
                    iso = f"20{key[0:2]}-{key[2:4]}-{key[4:6]}"
                    if iso in counts_by_day:
                        counts_by_day[iso]["walk_in_count"] += 1

        # Compose la sortie sortée par date + total dérivé.
        items = []
        for iso in sorted(counts_by_day.keys()):
            entry = counts_by_day[iso]
            entry["total"] = entry["rdv_count"] + entry["walk_in_count"]
            items.append(entry)

        return {
            "from_date": from_date,
            "days": days,
            "medecin_id": effective_medecin_id,
            "items": items,
        }

    # -----------------------------------------------------------------
    # 2026-02 fork (P2) — Walk-in CRUD (Secrétaire médicale + admin/sup)
    # -----------------------------------------------------------------
    def _can_manage_walkins(u: dict) -> bool:
        """Rôles autorisés à gérer les walk-ins depuis le portail :
        - admin / superviseur (rôle plateforme)
        - tracked_role in {"Secrétaire médicale", "Administrateur",
                           "Superviseur", "Moderation", "Médecin"}
        """
        if _is_admin_or_superviseur(u):
            return True
        tr = (u.get("tracked_role") or "").strip()
        return tr in {"Secrétaire médicale", "Administrateur", "Superviseur", "Moderation", "Médecin"}

    async def _walkin_tenant_id_for_user(u: dict) -> str:
        """Résout le tenant_id à utiliser lors de la création d'un walk-in.
        Prend `parent_client_id` en priorité (secrétaire attachée à un client),
        sinon `client_id`, sinon `id`.
        """
        return u.get("parent_client_id") or u.get("client_id") or u["id"]

    @api.post("/me/planning/walk-in", tags=["Portail Client — Planning"])
    async def planning_create_walk_in(
        payload: WalkInCreatePayload = Body(...),
        user: dict = Depends(get_current_user),
    ):
        """Créer un walk-in (patient sans RDV). Ouvert aux secrétaires médicales
        et rôles élevés. La date par défaut est aujourd'hui.
        """
        if not _can_manage_walkins(user):
            raise HTTPException(status_code=403, detail="Rôle insuffisant pour créer un walk-in")

        # Résout le médecin choisi + vérifie qu'il est bien dans le scope
        medecin = await db.users.find_one(
            {"id": payload.medecin_id, "tracked_role": "Médecin"},
            {"_id": 0, "id": 1, "email": 1, "full_name": 1, "parent_client_id": 1, "client_id": 1},
        )
        if not medecin:
            raise HTTPException(status_code=404, detail="Médecin introuvable")
        if not _is_super_admin(user):
            scope = await _resolve_visible_client_ids(user)
            m_scope_ids = {medecin.get("parent_client_id"), medecin.get("client_id"), medecin.get("id")}
            if not any(mid in scope for mid in m_scope_ids if mid):
                raise HTTPException(status_code=403, detail="Médecin hors de votre scope")

        # Résolution date + walk_in_list
        day_iso = (payload.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()
        try:
            day_start = datetime.strptime(day_iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Date invalide (YYYY-MM-DD)")
        medecin_email = (medecin.get("email") or "").lower() or None
        domaine = (payload.domaine or "").strip().lower() or None
        walk_in_list = _walk_in_list_key(day_start.isoformat(), medecin_email, domaine)

        # Attribue le prochain numero_ordre chronologique
        tenant_id = await _walkin_tenant_id_for_user(user)
        max_ord = 0
        async for d in db.planning_appointments.find(
            {"tenant_id": tenant_id, "walk_in_list": walk_in_list, "is_rdv": 0},
            {"_id": 0, "numero_ordre": 1},
        ):
            try:
                no = int(d.get("numero_ordre") or 0)
                if no > max_ord:
                    max_ord = no
            except (TypeError, ValueError):
                pass
        numero_ordre = max_ord + 1

        now = _now_iso()
        doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "code_clinique": "manual",
            "medecin": medecin.get("full_name") or medecin.get("email") or "",
            "medecin_id": medecin.get("id"),
            "medecin_email": medecin_email,
            "patient": payload.patient.strip(),
            "patient_phone": (payload.patient_phone or "").strip() or None,
            "start_at": None,
            "end_at": None,
            "motif": (payload.motif or "").strip() or None,
            "is_rdv": 0,
            "domaine": domaine,
            "walk_in_list": walk_in_list,
            "numero_ordre": numero_ordre,
            "source": "manual",
            "created_at": now,
            "updated_at": now,
            "received_at": now,
            "created_by_id": user.get("id"),
            "created_by_email": user.get("email"),
        }
        await db.planning_appointments.insert_one(doc.copy())
        # Push SSE broadcast so open dashboards refresh instantly
        try:
            await _sse_broadcast(tenant_id, "created", doc)
        except Exception:  # noqa: BLE001
            pass
        doc.pop("_id", None)
        return {"ok": True, "walk_in": doc}

    @api.patch("/me/planning/walk-in/{wid}", tags=["Portail Client — Planning"])
    async def planning_update_walk_in(
        wid: str,
        payload: WalkInUpdatePayload = Body(...),
        user: dict = Depends(get_current_user),
    ):
        """Modifier un walk-in existant (patient, phone, médecin, date, motif)."""
        if not _can_manage_walkins(user):
            raise HTTPException(status_code=403, detail="Rôle insuffisant")
        existing = await db.planning_appointments.find_one({"id": wid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Walk-in introuvable")
        if existing.get("is_rdv") != 0:
            raise HTTPException(status_code=400, detail="Cet enregistrement n'est pas un walk-in")
        if not _is_super_admin(user):
            scope = await _resolve_visible_client_ids(user)
            if existing.get("tenant_id") not in scope:
                raise HTTPException(status_code=403, detail="Walk-in hors de votre scope")

        update: Dict[str, Any] = {"updated_at": _now_iso()}
        if payload.patient is not None:
            update["patient"] = payload.patient.strip()
        if payload.patient_phone is not None:
            update["patient_phone"] = payload.patient_phone.strip() or None
        if payload.motif is not None:
            update["motif"] = payload.motif.strip() or None

        # Change de médecin ou de date → recalcule walk_in_list
        new_medecin_email = existing.get("medecin_email")
        new_medecin_name = existing.get("medecin")
        new_medecin_id = existing.get("medecin_id")
        if payload.medecin_id and payload.medecin_id != existing.get("medecin_id"):
            m = await db.users.find_one(
                {"id": payload.medecin_id, "tracked_role": "Médecin"},
                {"_id": 0, "id": 1, "email": 1, "full_name": 1, "parent_client_id": 1, "client_id": 1},
            )
            if not m:
                raise HTTPException(status_code=404, detail="Médecin introuvable")
            new_medecin_email = (m.get("email") or "").lower() or None
            new_medecin_name = m.get("full_name") or m.get("email") or ""
            new_medecin_id = m.get("id")
            update["medecin_id"] = new_medecin_id
            update["medecin_email"] = new_medecin_email
            update["medecin"] = new_medecin_name

        new_day_iso: Optional[str] = None
        if payload.date is not None:
            try:
                dt = datetime.strptime(payload.date.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                new_day_iso = dt.isoformat()
            except ValueError:
                raise HTTPException(status_code=400, detail="Date invalide (YYYY-MM-DD)")

        domaine = existing.get("domaine")
        if payload.domaine is not None:
            domaine = (payload.domaine or "").strip().lower() or None
            update["domaine"] = domaine

        if new_medecin_email != existing.get("medecin_email") or new_day_iso or domaine != existing.get("domaine"):
            # Regenerate walk_in_list key based on the (potentially updated) day/email/domaine
            ref_day = new_day_iso or existing.get("received_at") or existing.get("created_at") or _now_iso()
            walk_in_list = _walk_in_list_key(ref_day, new_medecin_email, domaine)
            update["walk_in_list"] = walk_in_list
            # Re-assign numero_ordre if the list changed
            if walk_in_list != existing.get("walk_in_list"):
                max_ord = 0
                async for d in db.planning_appointments.find(
                    {"tenant_id": existing.get("tenant_id"), "walk_in_list": walk_in_list, "is_rdv": 0},
                    {"_id": 0, "numero_ordre": 1},
                ):
                    try:
                        no = int(d.get("numero_ordre") or 0)
                        if no > max_ord:
                            max_ord = no
                    except (TypeError, ValueError):
                        pass
                update["numero_ordre"] = max_ord + 1

        await db.planning_appointments.update_one({"id": wid}, {"$set": update})
        fresh = await db.planning_appointments.find_one({"id": wid}, {"_id": 0})
        try:
            await _sse_broadcast(existing.get("tenant_id"), "updated", fresh or {})
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "walk_in": fresh}

    @api.delete("/me/planning/walk-in/{wid}", tags=["Portail Client — Planning"])
    async def planning_delete_walk_in(wid: str, user: dict = Depends(get_current_user)):
        """Supprimer un walk-in existant."""
        if not _can_manage_walkins(user):
            raise HTTPException(status_code=403, detail="Rôle insuffisant")
        existing = await db.planning_appointments.find_one({"id": wid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Walk-in introuvable")
        if existing.get("is_rdv") != 0:
            raise HTTPException(status_code=400, detail="Cet enregistrement n'est pas un walk-in — utilisez le webhook pour les RDV")
        if not _is_super_admin(user):
            scope = await _resolve_visible_client_ids(user)
            if existing.get("tenant_id") not in scope:
                raise HTTPException(status_code=403, detail="Walk-in hors de votre scope")
        await db.planning_appointments.delete_one({"id": wid})
        try:
            await _sse_broadcast(existing.get("tenant_id"), "deleted", {"id": wid, **existing})
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "id": wid}

    # -----------------------------------------------------------------
    # Iter43-fix24az-n (2026-07-18) — SSE stream temps réel
    # -----------------------------------------------------------------
    @api.get("/me/planning/stream", tags=["Portail Client — Planning"])
    async def planning_sse_stream(
        request: Request,
        token: str = Query(..., description="JWT (query param car EventSource ne supporte pas les headers)"),
        medecin_id: Optional[str] = Query(None),
    ):
        """Server-Sent Events : push temps réel des nouveaux RDV/mises à jour.
        Auth via query param `token` (JWT). Filtre par medecin_id optionnel.
        Le stream envoie un ping toutes les 20s pour maintenir la connexion vivante
        (contourne les 60s de Cloudflare + les timeouts uvicorn keep-alive).
        """
        user = await _get_user_from_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="Token invalide")

        # Résolution tenant + éventuel verrouillage médecin
        is_medecin = (user.get("tracked_role") or "") == "Médecin"
        effective_medecin_id = user["id"] if is_medecin else medecin_id
        if _is_super_admin(user):
            allowed_tenants = None  # None = no filter (super-admin sees all)
        else:
            allowed_tenants = await _resolve_visible_client_ids(user)

        sub_id = str(uuid.uuid4())
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        sub: Dict[str, Any] = {
            "id": sub_id,
            "allowed_tenants": allowed_tenants,
            "user_id": user["id"],
            "medecin_id_filter": effective_medecin_id,
            "medecin_email": (user.get("email") or "").lower() if is_medecin else None,
            "queue": queue,
        }
        async with _sse_lock:
            _sse_subscribers.append(sub)
        logger.info("[planning] SSE +sub id=%s tenants=%s medecin_filter=%s (total=%d)",
                    sub_id[:8],
                    "*" if allowed_tenants is None else f"[{len(allowed_tenants)}]",
                    (effective_medecin_id or "-")[:8], len(_sse_subscribers))

        async def event_stream():
            # Hello event
            yield f"event: hello\ndata: {json.dumps({'sub_id': sub_id, 'ts': _now_iso()})}\n\n"
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                        yield f"event: {payload['event']}\ndata: {json.dumps(payload, default=str)}\n\n"
                    except asyncio.TimeoutError:
                        # Keep-alive ping
                        yield f"event: ping\ndata: {json.dumps({'ts': _now_iso()})}\n\n"
            finally:
                async with _sse_lock:
                    _sse_subscribers[:] = [s for s in _sse_subscribers if s["id"] != sub_id]
                logger.info("[planning] SSE -sub id=%s (total=%d)", sub_id[:8], len(_sse_subscribers))

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",  # disable proxy buffering
                "Connection": "keep-alive",
            },
        )

    # ---- Startup hook ----
    import asyncio as _asyncio
    _asyncio.create_task(_ensure_indexes())

    logger.info("[planning] routes mounted under /api/webhooks/planning/{secret}, /api/admin/planning/*, /api/me/planning/*, /api/me/planning/stream")

    # Expose la fonction reminders pour que server.py puisse l'appeler dans un cron
    return {"run_planning_wa_reminders": run_planning_wa_reminders_impl}
