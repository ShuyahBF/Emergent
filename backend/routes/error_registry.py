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

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
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
    Motif: str = Field(..., min_length=1, max_length=200000)
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


class BulkIdsPayload(BaseModel):
    ids: List[str] = Field(default_factory=list, max_length=5000)


def _unwrap_payload(body: Any) -> Dict[str, Any]:
    """Iter43 (2026-03) — Accepte un body « plat » ou imbriqué.

    Détecte automatiquement les wrappers du type :
      {"TicketDemnde": {Motif, CodeApplicatif, ...}}      (Aizenta)
      {"Erreur": {Motif, CodeApplicatif, ...}}            (Biolog & autres)
      {"<n'importe quel wrapper>": {Motif, CodeApplicatif, ...}}

    Si le body racine contient EXACTEMENT 1 clé top-level et que sa valeur
    est un dict contenant `Motif` ET `CodeApplicatif`, on dépouille (unwrap).
    Sinon on garde le body tel quel.
    """
    if not isinstance(body, dict):
        return body
    # Si le body racine contient déjà Motif + CodeApplicatif → format plat
    if "Motif" in body and "CodeApplicatif" in body:
        return body
    # Cherche un wrapper unique contenant un dict avec Motif/CodeApplicatif
    candidate_keys = [
        k for k, v in body.items()
        if isinstance(v, dict) and "Motif" in v and "CodeApplicatif" in v
    ]
    if len(candidate_keys) == 1:
        inner = dict(body[candidate_keys[0]])
        # Préserve le password racine s'il est fourni
        if body.get("password") and "password" not in inner:
            inner["password"] = body["password"]
        return inner
    return body


def attach_error_registry_routes(*, api, db, get_current_user):

    @api.post("/errors/ingest", tags=["Registre des erreurs (Webhook)"])
    async def ingest_error(
        request: Request,
        authorization: Optional[str] = Header(default=None),
    ):
        """Webhook public utilisé par les logiciels clients pour pousser des exceptions/erreurs.

        Authentication : Bearer token in the `Authorization` header. The
        token must match `settings.global.errors_webhook_token`. If that
        setting is empty, the webhook accepts unauthenticated calls (dev
        only — admins must set a token in production).

        Iter43 (2026-03) — Accepte les formats imbriqués (Aizenta:
        `{TicketDemnde: {...}}`, Biolog: `{Erreur: {...}}` etc.) ainsi que
        le format plat historique. L'unwrap est automatique.
        """
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "errors_webhook_token": 1, "error_severity_mapping": 1}) or {}
        expected = (s.get("errors_webhook_token") or "").strip()
        if expected:
            got = (authorization or "").replace("Bearer ", "").strip()
            if got != expected:
                raise HTTPException(status_code=401, detail="Token invalide")
        # Lecture brute + unwrap auto si imbriqué
        try:
            raw_body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Body JSON invalide")
        adapted = _unwrap_payload(raw_body)
        try:
            payload = ErrorPayload.model_validate(adapted)
        except Exception as exc:  # pydantic.ValidationError
            raise HTTPException(status_code=422, detail=str(exc))
        doc = payload.model_dump()
        # Iter43-fix — Sévérité interne dérivée du mapping admin
        try:
            mapping = (s.get("error_severity_mapping") or {}) if isinstance(s, dict) else {}
            if not mapping:
                s2 = await db.settings.find_one({"_id": "global"}, {"_id": 0, "error_severity_mapping": 1}) or {}
                mapping = s2.get("error_severity_mapping") or {}
            statut = (doc.get("StatutEnCours") or "").strip().lower()
            # Recherche case-insensitive
            mapped = None
            for k, v in (mapping or {}).items():
                if (k or "").strip().lower() == statut and v in ("low", "medium", "high", "critical"):
                    mapped = v
                    break
            if mapped:
                doc["mapped_severity"] = mapped
            else:
                # Heuristique de secours sur le statut
                if statut in ("fatale", "fatal", "critical", "critique"):
                    doc["mapped_severity"] = "critical"
                elif statut in ("exception", "erreur", "error"):
                    doc["mapped_severity"] = "high"
                elif statut in ("warning", "avertissement"):
                    doc["mapped_severity"] = "medium"
                else:
                    doc["mapped_severity"] = "low"
        except Exception:
            doc["mapped_severity"] = "low"
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
        severity: Optional[str] = Query(default=None),  # Iter43-fix2 — low|medium|high|critical
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
            # Iter43-fix2 — match case-insensitive (les logiciels métier
            # envoient "Fatale", "fatale", "FATALE" indifféremment).
            import re as _re
            q["StatutEnCours"] = {"$regex": f"^{_re.escape(status)}$", "$options": "i"}
        if severity:
            sev_lc = (severity or "").strip().lower()
            if sev_lc in ("low", "medium", "high", "critical"):
                # Match soit sur le mapped_severity persisté soit sur l'heuristique
                # de secours pour les entrées legacy.
                heur_map = {
                    "critical": ["fatale", "fatal", "critical", "critique"],
                    "high": ["exception", "erreur", "error"],
                    "medium": ["warning", "avertissement"],
                }
                legacy_terms = heur_map.get(sev_lc, [])
                clauses = [{"mapped_severity": sev_lc}]
                if legacy_terms:
                    import re as _re
                    pattern = "^(" + "|".join(_re.escape(t) for t in legacy_terms) + ")$"
                    clauses.append({
                        "mapped_severity": {"$exists": False},
                        "StatutEnCours": {"$regex": pattern, "$options": "i"},
                    })
                if sev_lc == "low":
                    # Low = catch-all : entrées sans mapped_severity ET dont le
                    # StatutEnCours ne matche aucune heuristique high/critical/medium.
                    clauses.append({
                        "mapped_severity": {"$exists": False},
                        "$nor": [
                            {"StatutEnCours": {"$regex": "^(fatale|fatal|critical|critique|exception|erreur|error|warning|avertissement)$", "$options": "i"}},
                        ],
                    })
                # Combine avec le reste via $and pour préserver les autres filtres
                existing_or = q.pop("$or", None)
                q.setdefault("$and", []).append({"$or": clauses})
                if existing_or:
                    q["$and"].append({"$or": existing_or})
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
        # Iter43-fix2 (2026-03) — Point 4 : Code_Client envoyé par les logiciels
        # métier correspond à un tenant Sawali. On résout le nom (company)
        # pour chaque entrée en un seul lookup.
        codes = {(i.get("Code_Client") or "").strip().upper() for i in items if i.get("Code_Client")}
        codes.discard("")
        if codes:
            tenant_map: Dict[str, Dict[str, Any]] = {}
            # Match insensible à la casse : on charge tous les tenants candidats
            # (admin/sup) ayant ces codes.
            async for u in db.users.find(
                {
                    "role": {"$in": ["admin", "superviseur", "client"]},
                    "$or": [
                        {"client_code": {"$in": list(codes)}},
                        {"company": {"$in": list(codes)}},
                    ],
                },
                {"_id": 0, "id": 1, "company": 1, "full_name": 1, "client_code": 1, "email": 1},
            ):
                ccode = (u.get("client_code") or u.get("company") or "").strip().upper()
                if ccode:
                    tenant_map[ccode] = {
                        "tenant_id": u.get("id"),
                        "tenant_name": u.get("company") or u.get("full_name") or u.get("email"),
                    }
            for it in items:
                cc = (it.get("Code_Client") or "").strip().upper()
                t = tenant_map.get(cc)
                if t:
                    it["tenant_id"] = t["tenant_id"]
                    it["tenant_name"] = t["tenant_name"]
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
            # Iter43-fix — Liste détaillée pour la section AdminSettings (mapping)
            "by_status": [
                {"value": k, "count": v}
                for k, v in sorted(by_status.items(), key=lambda kv: kv[1], reverse=True)
            ],
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

    # Iter43-fix2 (2026-03) — Bulk acknowledge (multi-sélection UI)
    @api.post("/me/errors/bulk-acknowledge", tags=["Registre des erreurs"])
    async def bulk_acknowledge(payload: BulkIdsPayload = Body(...), user: dict = Depends(get_current_user)):
        if not _can_access(user):
            raise HTTPException(status_code=403, detail="Accès réservé")
        ids = [i for i in (payload.ids or []) if isinstance(i, str) and i]
        if not ids:
            raise HTTPException(status_code=400, detail="Aucun id fourni")
        res = await db.error_registry.update_many(
            {"id": {"$in": ids}, "acknowledged": {"$ne": True}},
            {"$set": {"acknowledged": True, "acknowledged_at": _now(), "acknowledged_by": user.get("email")}},
        )
        return {"ok": True, "acknowledged": res.modified_count}

    # Iter43-fix2 — Acknowledge ALL unread (visible) errors. Idempotent.
    @api.post("/me/errors/acknowledge-all", tags=["Registre des erreurs"])
    async def acknowledge_all(user: dict = Depends(get_current_user)):
        """Marque comme lues TOUTES les erreurs non lues, indépendamment des
        filtres actuels et de la pagination. Réservé Admin/Superviseur (le
        Modérateur peut lire mais pas tout marquer en masse)."""
        role = (user.get("role") or "").lower()
        if role not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé Admin/Superviseur")
        res = await db.error_registry.update_many(
            {"deleted_at": None, "acknowledged": {"$ne": True}},
            {"$set": {"acknowledged": True, "acknowledged_at": _now(), "acknowledged_by": user.get("email"), "acknowledged_bulk": True}},
        )
        return {"ok": True, "acknowledged": res.modified_count}

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

    # ================================================================ #
    # Iter43 (2026-03) — Bulk delete (multi-sélection UI) + Reset total
    # ================================================================ #
    @api.post("/me/errors/bulk-delete", tags=["Registre des erreurs"])
    async def bulk_delete_errors(
        payload: BulkIdsPayload = Body(...),
        user: dict = Depends(get_current_user),
    ):
        """Hard-delete les erreurs sélectionnées par leurs ids.
        Admin ou Superviseur uniquement (Modérateur = lecture)."""
        role = (user.get("role") or "").lower()
        if role not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Suppression réservée Admin/Superviseur")
        ids = [i for i in (payload.ids or []) if isinstance(i, str) and i]
        if not ids:
            raise HTTPException(status_code=400, detail="Aucun id fourni")
        res = await db.error_registry.delete_many({"id": {"$in": ids}})
        return {"ok": True, "deleted": res.deleted_count}

    @api.post("/me/errors/reset", tags=["Registre des erreurs"])
    async def reset_all_errors(user: dict = Depends(get_current_user)):
        """Hard-delete TOUTES les erreurs (remise à zéro complète).
        Réservé Admin/Superviseur."""
        role = (user.get("role") or "").lower()
        if role not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé Admin/Superviseur")
        res = await db.error_registry.delete_many({})
        return {"ok": True, "deleted": res.deleted_count}

    # ================================================================ #
    # Iter43 (2026-03) — Migration : récupère les entrées Aizenta qui ont
    # atterri par erreur dans support_tickets (via /api/public/incidents)
    # et les rebascule dans error_registry. Idempotent.
    # ================================================================ #
    @api.post("/admin/error-registry/migrate-from-tickets", tags=["Admin — Registre des erreurs"])
    async def migrate_from_tickets(user: dict = Depends(get_current_user)):
        role = (user.get("role") or "").lower()
        if role not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé Admin/Superviseur")
        # Repère les tickets webhook avec un body Aizenta-like dans metadata
        q = {
            "channel": "webhook",
            "$or": [
                {"metadata.IDTicketDemnde": {"$exists": True, "$ne": None}},
                {"metadata.Motif": {"$exists": True, "$ne": None}},
            ],
        }
        migrated = 0
        skipped_already = 0
        async for tk in db.support_tickets.find(q):
            md = tk.get("metadata") or {}
            # Skip si déjà présent dans error_registry (idempotence)
            existing = None
            if md.get("IDTicketDemnde"):
                existing = await db.error_registry.find_one(
                    {"IDTicketDemnde": md["IDTicketDemnde"]}, {"_id": 0, "id": 1}
                )
            if existing:
                skipped_already += 1
                continue
            # Construit le doc error_registry depuis le metadata Aizenta
            doc = {
                "id": str(uuid.uuid4()),
                "IDTicketDemnde": md.get("IDTicketDemnde") or str(uuid.uuid4()),
                "DateHeure_Création": md.get("DateHeure_Création") or md.get("DateHeure_Creation")
                or tk.get("created_at") or _now(),
                "DateHeure_Modification": md.get("DateHeure_Modification") or _now(),
                "NuméroDemandeur": md.get("NuméroDemandeur") or md.get("NumeroDemandeur"),
                "Motif": md.get("Motif") or tk.get("description") or tk.get("motif") or "(vide)",
                "Numéro_Généré": md.get("Numéro_Généré") or md.get("Numero_Genere"),
                "estActif": md.get("estActif", True),
                "StatutEnCours": md.get("StatutEnCours") or "exception",
                "Code_Client": md.get("Code_Client"),
                "CodeApplicatif": md.get("CodeApplicatif") or "INCONNU",
                "RefContrat": md.get("RefContrat"),
                "CoutTicket": md.get("CoutTicket") or 0,
                "estClos": md.get("estClos", False),
                "DateHeure_DébutExécution": md.get("DateHeure_DébutExécution"),
                "DateHeure_FinExécution": md.get("DateHeure_FinExécution"),
                "DateHeure_Approbation": md.get("DateHeure_Approbation"),
                "Résultats": md.get("Résultats"),
                "Recommandations": md.get("Recommandations"),
                "estFacturé": md.get("estFacturé", False),
                "NuméroFacture": md.get("NuméroFacture"),
                "Réalisé_par": md.get("Réalisé_par"),
                "EvaluationClient": md.get("EvaluationClient"),
                "CompteClient": md.get("CompteClient"),
                "TypeTicket": md.get("TypeTicket"),
                "DateExpiration": md.get("DateExpiration"),
                "CoutDéplacement": md.get("CoutDéplacement"),
                "Approuvé_par": md.get("Approuvé_par"),
                "DateHHeure_Validation": md.get("DateHHeure_Validation"),
                "estApprouvé": md.get("estApprouvé", False),
                "SurNomWA": md.get("SurNomWA"),
                "Autorité": md.get("Autorité"),
                "created_at": _now(),
                "deleted_at": None,
                "acknowledged": False,
                "migrated_from_ticket_id": tk.get("id"),
                "migrated_at": _now(),
            }
            if not doc["Numéro_Généré"]:
                year = datetime.now(timezone.utc).year
                try:
                    from ._counters import next_seq
                    seq = await next_seq(db, f"error_registry-{year}")
                    doc["Numéro_Généré"] = f"ERR-{year}-{str(seq).zfill(5)}"
                except Exception:
                    doc["Numéro_Généré"] = f"ERR-{year}-{uuid.uuid4().hex[:6].upper()}"
            await db.error_registry.insert_one(doc.copy())
            # Marque le ticket comme migré (on ne supprime PAS — l'utilisateur
            # pourra ensuite vider via le bouton "Reset" des tickets)
            await db.support_tickets.update_one(
                {"id": tk.get("id")},
                {"$set": {"migrated_to_error_registry": True, "migrated_at": _now()}},
            )
            migrated += 1
        return {
            "ok": True,
            "migrated": migrated,
            "skipped_already": skipped_already,
        }


__all__ = ["attach_error_registry_routes"]
