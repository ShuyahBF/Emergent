"""Iter40 (2026-02) — Registre des erreurs (logiciels externes).

Webhook public + endpoints CRUD pour collecter, lister, purger les erreurs
remontées par nos logiciels clients. Auth webhook par token Bearer dans
`settings.global.errors_webhook_token`. Si pas configuré, accepte sans auth
(mode dev only, masquer dans la prod).

Champs du modèle (collection `error_registry`, suivant la spec utilisateur) :
  - IDTicketDemnde (uuid), DateHeure_Création, DateHeure_Modification
  - NuméroDemandeur, Motif, Numéro_Généré, estActif, StatutEnCours
  - Code_Client (= tenant_id côté CRM), CodeApplicatif, RefContrat
  - CoutTicket, estClos, DateHeure_DébutExécution, DateHeure_FinExécution
  - DateHeure_Approbation, Résultats, Recommandations
  - estFacturé, NuméroFacture, Réalisé_par, EvaluationClient, CompteClient
  - IMG_QRCode (b64), TypeTicket, PDF_QrCode (b64), DateExpiration
  - CoutDéplacement, Approuvé_par, DateHHeure_Validation, estApprouvé
  - SurNomWA, Autorité

Endpoints :
  POST   /api/errors/ingest                  — webhook public (Bearer token)
  GET    /api/me/errors                      — list with filters
  GET    /api/me/errors/stats                — count by StatutEnCours
  GET    /api/me/errors/{eid}                — details
  DELETE /api/me/errors/{eid}                — soft-delete (Modérateur+)
  DELETE /api/me/errors/purge                — purge by date range (Superviseur ONLY)

ACL : Modérateur, Admin, Superviseur. Purge réservée Superviseur.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.error_registry")

ALLOWED_ROLES = ("moderator", "moderateur", "admin", "superviseur")
SUPERVISOR_ROLES = ("superviseur",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _can_access(user: dict) -> bool:
    role = (user.get("role") or "").lower()
    return role in ALLOWED_ROLES


def _can_purge(user: dict) -> bool:
    return (user.get("role") or "").lower() in SUPERVISOR_ROLES


class ErrorPayload(BaseModel):
    """Webhook ingestion payload — all fields optional except CodeApplicatif and Motif."""
    IDTicketDemnde: Optional[str] = Field(default=None, max_length=128)
    DateHeure_Création: Optional[str] = None
    DateHeure_Modification: Optional[str] = None
    NuméroDemandeur: Optional[str] = Field(default=None, max_length=64)
    Motif: str = Field(..., min_length=1, max_length=2000)
    Numéro_Généré: Optional[str] = Field(default=None, max_length=64)
    estActif: Optional[bool] = True
    StatutEnCours: Optional[str] = Field(default=None, max_length=40)  # "exception"|"fatale"|...
    Code_Client: Optional[str] = Field(default=None, max_length=64)
    CodeApplicatif: str = Field(..., min_length=1, max_length=64)
    RefContrat: Optional[str] = Field(default=None, max_length=64)
    CoutTicket: Optional[float] = None
    estClos: Optional[bool] = False
    DateHeure_DébutExécution: Optional[str] = None
    DateHeure_FinExécution: Optional[str] = None
    DateHeure_Approbation: Optional[str] = None
    Résultats: Optional[str] = None
    Recommandations: Optional[str] = None
    estFacturé: Optional[bool] = False
    NuméroFacture: Optional[str] = Field(default=None, max_length=64)
    Réalisé_par: Optional[str] = Field(default=None, max_length=128)
    EvaluationClient: Optional[int] = None
    CompteClient: Optional[str] = Field(default=None, max_length=64)
    IMG_QRCode: Optional[str] = None  # base64
    TypeTicket: Optional[str] = Field(default=None, max_length=40)
    PDF_QrCode: Optional[str] = None  # base64
    DateExpiration: Optional[str] = None
    CoutDéplacement: Optional[float] = None
    Approuvé_par: Optional[str] = Field(default=None, max_length=128)
    DateHHeure_Validation: Optional[str] = None
    estApprouvé: Optional[bool] = False
    SurNomWA: Optional[str] = Field(default=None, max_length=64)
    Autorité: Optional[str] = Field(default=None, max_length=64)


class PurgePayload(BaseModel):
    from_date: Optional[str] = None  # YYYY-MM-DD
    to_date: Optional[str] = None
    code_client: Optional[str] = None


def attach_error_registry_routes(*, api, db, get_current_user):

    @api.post("/errors/ingest", tags=["Registre des erreurs (Webhook)"])
    async def ingest_error(
        payload: ErrorPayload = Body(...),
        authorization: Optional[str] = Header(default=None),
    ):
        """Public webhook for client software to push exceptions/errors.

        Authentication : Bearer token in the `Authorization` header. The
        token must match `settings.global.errors_webhook_token`. If that
        setting is empty, the webhook accepts unauthenticated calls (dev
        only — admins must set a token in production).
        """
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "errors_webhook_token": 1}) or {}
        expected = (s.get("errors_webhook_token") or "").strip()
        if expected:
            got = (authorization or "").replace("Bearer ", "").strip()
            if got != expected:
                raise HTTPException(status_code=401, detail="Token invalide")
        doc = payload.model_dump()
        # ID + timestamps
        if not doc.get("IDTicketDemnde"):
            doc["IDTicketDemnde"] = str(uuid.uuid4())
        if not doc.get("DateHeure_Création"):
            doc["DateHeure_Création"] = _now()
        doc["DateHeure_Modification"] = _now()
        # System metadata
        doc["id"] = str(uuid.uuid4())
        doc["created_at"] = _now()
        doc["deleted_at"] = None
        doc["acknowledged"] = False  # for toast UI
        # Auto-generated number if not provided
        if not doc.get("Numéro_Généré"):
            year = datetime.now(timezone.utc).year
            try:
                from ._counters import next_seq
                seq = await next_seq(db, f"error_registry-{year}")
                doc["Numéro_Généré"] = f"ERR-{year}-{str(seq).zfill(5)}"
            except Exception:
                doc["Numéro_Généré"] = f"ERR-{year}-{uuid.uuid4().hex[:6].upper()}"
        await db.error_registry.insert_one(doc.copy())
        doc.pop("_id", None)
        return {"ok": True, "id": doc["id"], "number": doc["Numéro_Généré"]}

    @api.get("/me/errors", tags=["Registre des erreurs"])
    async def list_errors(
        code_client: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
        active_only: Optional[bool] = Query(default=None),
        search: Optional[str] = Query(default=None),
        date_window: Optional[str] = Query(default=None),  # "today" | "7d" | "30d"
        limit: int = Query(default=200, ge=1, le=2000),
        skip: int = Query(default=0, ge=0),
        user: dict = Depends(get_current_user),
    ):
        if not _can_access(user):
            raise HTTPException(status_code=403, detail="Accès réservé Modérateur/Admin/Superviseur")
        q: Dict[str, Any] = {"deleted_at": None}
        if code_client:
            q["Code_Client"] = code_client
        if status:
            q["StatutEnCours"] = status
        if active_only is not None:
            q["estActif"] = active_only
        if search:
            q["$or"] = [
                {"Motif": {"$regex": search, "$options": "i"}},
                {"SurNomWA": {"$regex": search, "$options": "i"}},
            ]
        if date_window:
            from datetime import timedelta
            now = datetime.now(timezone.utc)
            if date_window == "today":
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif date_window == "7d":
                start = now - timedelta(days=7)
            elif date_window == "30d":
                start = now - timedelta(days=30)
            else:
                start = None
            if start:
                q["DateHeure_Création"] = {"$gte": start.isoformat()}
        total = await db.error_registry.count_documents(q)
        cursor = db.error_registry.find(q, {"_id": 0}).sort("DateHeure_Création", -1).skip(skip).limit(limit)
        items = await cursor.to_list(limit)
        return {"items": items, "total": total}

    @api.get("/me/errors/stats", tags=["Registre des erreurs"])
    async def errors_stats(user: dict = Depends(get_current_user)):
        if not _can_access(user):
            raise HTTPException(status_code=403, detail="Accès réservé")
        # Counts by status (exception / fatale / autres)
        pipeline = [
            {"$match": {"deleted_at": None, "estActif": True}},
            {"$group": {"_id": "$StatutEnCours", "n": {"$sum": 1}}},
        ]
        by_status: Dict[str, int] = {}
        async for row in db.error_registry.aggregate(pipeline):
            st = (row.get("_id") or "autre").lower()
            by_status[st] = row["n"]
        total = await db.error_registry.count_documents({"deleted_at": None})
        unack = await db.error_registry.count_documents({"deleted_at": None, "acknowledged": False})
        return {
            "total": total,
            "unacknowledged": unack,
            "exception": by_status.get("exception", 0),
            "fatale": by_status.get("fatale", 0) + by_status.get("fatal", 0),
            "other": sum(v for k, v in by_status.items() if k not in ("exception", "fatale", "fatal")),
        }

    @api.post("/me/errors/{eid}/acknowledge", tags=["Registre des erreurs"])
    async def acknowledge(eid: str, user: dict = Depends(get_current_user)):
        if not _can_access(user):
            raise HTTPException(status_code=403, detail="Accès réservé")
        res = await db.error_registry.update_one(
            {"id": eid},
            {"$set": {"acknowledged": True, "acknowledged_at": _now(), "acknowledged_by": user.get("email")}},
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Erreur introuvable")
        return {"ok": True}

    @api.get("/me/errors/{eid}", tags=["Registre des erreurs"])
    async def get_error(eid: str, user: dict = Depends(get_current_user)):
        if not _can_access(user):
            raise HTTPException(status_code=403, detail="Accès réservé")
        doc = await db.error_registry.find_one({"id": eid}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Erreur introuvable")
        return doc

    @api.delete("/me/errors/{eid}", tags=["Registre des erreurs"])
    async def soft_delete_error(eid: str, user: dict = Depends(get_current_user)):
        if not _can_access(user):
            raise HTTPException(status_code=403, detail="Accès réservé")
        res = await db.error_registry.update_one(
            {"id": eid},
            {"$set": {"deleted_at": _now(), "deleted_by": user.get("email")}},
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Erreur introuvable")
        return {"ok": True}

    @api.post("/me/errors/purge", tags=["Registre des erreurs"])
    async def purge_errors(payload: PurgePayload = Body(...), user: dict = Depends(get_current_user)):
        """Hard-delete errors matching the date range. Superviseur ONLY."""
        if not _can_purge(user):
            raise HTTPException(status_code=403, detail="Purge réservée au Superviseur")
        q: Dict[str, Any] = {}
        if payload.from_date:
            q.setdefault("DateHeure_Création", {})["$gte"] = payload.from_date
        if payload.to_date:
            q.setdefault("DateHeure_Création", {})["$lte"] = payload.to_date + "T23:59:59"
        if payload.code_client:
            q["Code_Client"] = payload.code_client
        if not q:
            raise HTTPException(status_code=400, detail="Au moins un critère requis (from_date, to_date ou code_client)")
        res = await db.error_registry.delete_many(q)
        return {"ok": True, "deleted": res.deleted_count}


__all__ = ["attach_error_registry_routes"]
