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

Schéma `planning_appointments` :
    { id, tenant_id, code_clinique, medecin, medecin_id, medecin_email,
      patient, start_at (ISO), end_at (ISO), motif, id_user,
      external_id, source, created_at, updated_at, received_at }

Unicité : (tenant_id, code_clinique, medecin, patient, start_at) — upsert idempotent
"""
from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.planning")


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


class PlanningConfigUpdate(BaseModel):
    planning_webhook_secret: Optional[str] = Field(None, description="Secret du webhook (32 chars)")
    regenerate: Optional[bool] = Field(False, description="Génère un nouveau secret aléatoire")


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
):
    """Monte les endpoints du module Planning."""

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
            "sample_payload": {
                "code_clinique": "CLI-001",
                "medecin": "Dr. Aissata Ouedraogo",
                "medecin_email": "aissata@clinique.bf",
                "patient": "Fatimata KANE",
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
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "planning_webhook_secret": new_secret,
                "planning_webhook_updated_at": _now_iso(),
                "planning_webhook_updated_by": user.get("email"),
            }},
            upsert=True,
        )
        base = _public_base_url(request) or str(request.base_url).rstrip("/")
        return {
            "ok": True,
            "planning_webhook_secret": new_secret,
            "webhook_url": f"{base}/api/webhooks/planning/{new_secret}",
        }

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
        if not start_at:
            raise HTTPException(status_code=400, detail="Champ 'start' invalide (ISO 8601 requis)")
        if not end_at:
            # end défaut = start + 30min
            try:
                sdt = datetime.fromisoformat(start_at)
                from datetime import timedelta
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

        # Résout le tenant_id : par défaut super-admin du système. Si medecin_email
        # correspond à un utilisateur tracked, on utilise SON tenant.
        tenant_id: Optional[str] = None
        medecin_id: Optional[str] = None
        if medecin_email:
            u = await db.users.find_one(
                {"email": medecin_email.lower()},
                {"_id": 0, "id": 1, "client_id": 1, "parent_client_id": 1},
            )
            if u:
                medecin_id = u.get("id")
                tenant_id = u.get("parent_client_id") or u.get("client_id") or u.get("id")
        if not tenant_id:
            # Fallback : super-admin comme tenant (le RDV apparaîtra dans le portail admin)
            admin = await db.users.find_one({"email": "admin@sawalismartsystems.com"}, {"_id": 0, "id": 1})
            tenant_id = (admin or {}).get("id") or "_global_"

        now = _now_iso()
        upsert_query = {
            "tenant_id": tenant_id,
            "code_clinique": code_clinique,
            "medecin": medecin_name,
            "patient": patient,
            "start_at": start_at,
        }
        set_doc = {
            "end_at": end_at,
            "medecin_id": medecin_id,
            "medecin_email": medecin_email,
            "id_user": id_user,
            "motif": motif,
            "external_id": external_id,
            "source": "webhook",
            "updated_at": now,
            "received_at": now,
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

        return {
            "ok": True,
            "created": res.upserted_id is not None,
            "modified": res.modified_count > 0,
            "tenant_id": tenant_id,
            "medecin_id": medecin_id,
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
        if _is_super_admin(user):
            q: Dict[str, Any] = {}
        else:
            scope = await _resolve_visible_client_ids(user)
            q = {"tenant_id": {"$in": scope}}
        q["start_at"] = {"$gte": start_iso, "$lt": end_iso}
        if effective_medecin_id:
            # Match soit medecin_id OU medecin_email correspondant à cet utilisateur
            u = await db.users.find_one({"id": effective_medecin_id}, {"_id": 0, "id": 1, "email": 1})
            or_clauses = [{"medecin_id": effective_medecin_id}]
            if u and u.get("email"):
                or_clauses.append({"medecin_email": u["email"].lower()})
            q["$or"] = or_clauses

        items: List[Dict[str, Any]] = []
        async for row in db.planning_appointments.find(q, {"_id": 0}).sort("start_at", 1).limit(500):
            items.append(row)
        return {
            "date": date,
            "count": len(items),
            "is_medecin_view": is_medecin,
            "medecin_id_locked": effective_medecin_id if is_medecin else None,
            "items": items,
        }

    # ---- Startup hook ----
    import asyncio as _asyncio
    _asyncio.create_task(_ensure_indexes())

    logger.info("[planning] routes mounted under /api/webhooks/planning/{secret}, /api/admin/planning/*, /api/me/planning/*")
