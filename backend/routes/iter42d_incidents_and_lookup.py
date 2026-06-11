"""Iter42d (2026-02) — Webhook entrant pour incidents serveur + Lookup AMM
public + champ country_code sur les AMM.

ENDPOINTS :
  - POST /api/public/incidents  (auth via mot de passe simple — header
                                  `X-Webhook-Password` ou body `password`)
                                 → crée un ticket dans `support_tickets`
  - POST /api/officines-portal/inventory/lookup-amm  (auth officine JWT)
                                 → cherche dans `amm_numbers` par CIP +
                                   country_code (= settings.amm_default_country)

ADMIN HELPERS :
  - GET  /api/admin/incidents-webhook  → renvoie l'URL publique +
                                          si le mot de passe est configuré.
  - POST /api/admin/incidents-webhook/regenerate-password → génère un nouveau
                                          mot de passe et le retourne en clair
                                          (one-shot display).
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.iter42d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_ticket_number(db) -> Any:  # async-compatible
    # Pattern existant dans le code : id = secrets.token_urlsafe(12)
    # Pour le numéro affiché type SUP-YYYYMM-XXXX
    async def _gen():
        prefix = datetime.now(timezone.utc).strftime("SUP-%Y%m")
        count = await db.support_tickets.count_documents({"number": {"$regex": f"^{prefix}"}})
        return f"{prefix}-{count + 1:04d}"
    return _gen()


class IncidentWebhookIn(BaseModel):
    """Format générique (rétro-compatible) — utilisé par Watchdog/Uptime-bot."""
    password: Optional[str] = None  # password peut être passé dans le body OU le header
    title: str = Field(..., min_length=3, max_length=300)
    description: Optional[str] = None
    severity: Optional[str] = Field("medium", pattern="^(low|medium|high|critical)$")
    source: Optional[str] = None  # ex: "server-prod", "watchdog", "uptime-bot"
    metadata: Optional[Dict[str, Any]] = None


def _adapt_aizenta_payload(body: Dict[str, Any]) -> Dict[str, Any]:
    """Iter43 (2026-02) — Adapte un payload Aizenta `{TicketDemnde: {...}}`
    vers le format générique attendu par IncidentWebhookIn.

    Mapping :
      - title       ← TypeTicket + CompteClient (fallback : 1ère ligne du Motif)
      - description ← Motif complet
      - severity    ← déduit du TypeTicket / Motif (Erreur/Critical → high, sinon medium)
      - source      ← `{Code_Client}/{CodeApplicatif}` (ex: AMY/WAB)
      - metadata    ← bloc TicketDemnde entier (pour traçabilité)
    """
    td = body.get("TicketDemnde") or {}
    if not isinstance(td, dict):
        return body  # pas un payload Aizenta, on laisse tel quel

    type_ticket = (td.get("TypeTicket") or "").strip()
    compte_client = (td.get("CompteClient") or "").strip()
    motif = (td.get("Motif") or "").strip()
    code_client = (td.get("Code_Client") or "").strip()
    code_applicatif = (td.get("CodeApplicatif") or "").strip()
    numero_genere = (td.get("Numéro_Généré") or td.get("Numero_Genere") or "").strip()

    # Titre = TypeTicket — CompteClient (ou Numéro Aizenta si dispo)
    title_parts = [p for p in [type_ticket, compte_client] if p]
    title = " — ".join(title_parts) or (motif.splitlines()[0] if motif else "Incident Aizenta")
    if numero_genere:
        title = f"{numero_genere} — {title}"
    title = title[:300]
    if len(title) < 3:
        title = (title + " (Aizenta)").strip()[:300]

    # Sévérité déduite
    low_blob = f"{type_ticket} {motif}".lower()
    if any(k in low_blob for k in ("critical", "fatal", "crash", "stop")):
        severity = "critical"
    elif any(k in low_blob for k in ("erreur", "error", "exception", "echec", "échec")):
        severity = "high"
    else:
        severity = "medium"

    source = "/".join(p for p in [code_client, code_applicatif] if p) or "aizenta"

    # On préserve le password si fourni au niveau racine (rare avec Aizenta)
    out = {
        "title": title,
        "description": motif,
        "severity": severity,
        "source": source,
        "metadata": td,
    }
    if body.get("password"):
        out["password"] = body["password"]
    return out


class AmmLookupIn(BaseModel):
    cip: str = Field(..., min_length=3, max_length=30)


def attach_iter42d_routes(
    api: APIRouter | FastAPI,
    *,
    db,
    get_current_admin,
    get_current_officine,
) -> None:
    # ============================================================ #
    # 1) Webhook entrant — Incidents serveur
    # ============================================================ #
    @api.post("/public/incidents", tags=["Public — Incidents Webhook"])
    async def public_incidents_webhook(
        request: Request,
        x_webhook_password: Optional[str] = Header(None, alias="X-Webhook-Password"),
    ):
        """Reçoit un incident depuis un serveur tiers (Watchdog, Uptime-Bot,
        Aizenta…).

        Auth : mot de passe simple. Le header `X-Webhook-Password` est
        prioritaire sur le champ `password` du body.

        Formats acceptés :
          1. Générique : `{title, description?, severity?, source?, metadata?}`
          2. **Aizenta** : `{TicketDemnde: {TypeTicket, Motif, CompteClient, ...}}`
             (mappé automatiquement vers le format générique).
        """
        # Lit le body brut pour pouvoir adapter avant la validation Pydantic.
        try:
            raw_body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Body JSON invalide")
        if not isinstance(raw_body, dict):
            raise HTTPException(status_code=400, detail="Body doit être un objet JSON")

        # Détecte le format Aizenta et adapte si besoin
        if "TicketDemnde" in raw_body:
            adapted = _adapt_aizenta_payload(raw_body)
        else:
            adapted = raw_body

        # Valide via Pydantic
        try:
            payload = IncidentWebhookIn.model_validate(adapted)
        except Exception as e:  # pydantic.ValidationError
            raise HTTPException(status_code=422, detail=str(e))
        settings = await db.settings.find_one({"_id": "global"}) or {}
        configured = (settings.get("incidents_webhook_password") or "").strip()
        if not configured:
            raise HTTPException(status_code=503, detail="Webhook incidents non configuré côté serveur")
        provided = (x_webhook_password or payload.password or "").strip()
        if not secrets.compare_digest(provided, configured):
            # log léger pour audit (sans secret)
            await db.incidents_webhook_log.insert_one({
                "id": str(uuid.uuid4()), "ok": False, "reason": "bad_password",
                "remote_ip": request.client.host if request.client else None,
                "title_preview": (payload.title or "")[:120],
                "created_at": _now_iso(),
            })
            raise HTTPException(status_code=401, detail="Mot de passe invalide")

        # Construit le ticket dans support_tickets
        gen = _next_ticket_number(db)
        number = await gen
        now_iso = _now_iso()
        severity = (payload.severity or "medium").lower()
        title = payload.title.strip()
        description = (payload.description or "").strip()
        details_md = description
        if payload.metadata:
            import json
            details_md += "\n\n---\n**Métadonnées :**\n```json\n" + json.dumps(payload.metadata, indent=2, ensure_ascii=False) + "\n```"
        ticket = {
            "id": secrets.token_urlsafe(12),
            "number": number,
            "client_id": None,
            "contact": {"name": payload.source or "incident-webhook", "phone": None, "email": None},
            "motif": f"[{severity.upper()}] {title}"[:300],
            "description": details_md,
            "severity": severity,
            "priority": "high" if severity in ("high", "critical") else "normal",
            "status": "open",
            "channel": "webhook",
            "source": payload.source or "incidents_webhook",
            "opened_by_id": None,
            "opened_by_label": f"Webhook ({payload.source or 'unknown'})",
            "closed_at": None,
            "closed_by_id": None,
            "closed_by_label": None,
            "outcome": None,
            "resolution_note": None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "metadata": payload.metadata or {},
        }
        await db.support_tickets.insert_one(ticket.copy())
        await db.incidents_webhook_log.insert_one({
            "id": str(uuid.uuid4()), "ok": True,
            "ticket_id": ticket["id"], "ticket_number": number,
            "remote_ip": request.client.host if request.client else None,
            "title_preview": title[:120], "severity": severity,
            "source": payload.source, "created_at": now_iso,
        })
        return {
            "ok": True, "ticket_number": number, "ticket_id": ticket["id"],
            "status": "open", "severity": severity,
        }

    # ============================================================ #
    # 2) Admin helpers — affichage URL + génération mot de passe
    # ============================================================ #
    @api.get("/admin/incidents-webhook", tags=["Admin — Incidents Webhook"])
    async def admin_get_incidents_webhook(_: dict = Depends(get_current_admin)):
        s = await db.settings.find_one({"_id": "global"}) or {}
        configured = bool((s.get("incidents_webhook_password") or "").strip())
        # Récupère stats des derniers logs
        recent = await db.incidents_webhook_log.find({}, {"_id": 0}).sort("created_at", -1).to_list(20)
        return {
            "configured": configured,
            "url": "/api/public/incidents",
            "auth_header": "X-Webhook-Password",
            "recent": recent,
        }

    @api.post("/admin/incidents-webhook/regenerate-password", tags=["Admin — Incidents Webhook"])
    async def admin_regen_incidents_password(user: dict = Depends(get_current_admin)):
        new_pwd = secrets.token_urlsafe(24)
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "incidents_webhook_password": new_pwd,
                "incidents_webhook_rotated_at": _now_iso(),
                "incidents_webhook_rotated_by": user.get("email"),
            }},
            upsert=True,
        )
        return {
            "ok": True,
            "password": new_pwd,
            "warning": "Ce mot de passe ne sera plus jamais affiché. Copiez-le immédiatement.",
        }

    @api.delete("/admin/incidents-webhook/password", tags=["Admin — Incidents Webhook"])
    async def admin_disable_incidents_webhook(user: dict = Depends(get_current_admin)):
        await db.settings.update_one(
            {"_id": "global"},
            {"$unset": {"incidents_webhook_password": ""},
             "$set": {"incidents_webhook_disabled_at": _now_iso(),
                      "incidents_webhook_disabled_by": user.get("email")}},
        )
        return {"ok": True, "disabled": True}

    # ============================================================ #
    # 3) Lookup AMM (par CIP + country_code par défaut)
    # ============================================================ #
    @api.post("/officines-portal/inventory/lookup-amm", tags=["Officines Portal"])
    async def lookup_amm(
        payload: AmmLookupIn = Body(...),
        _: dict = Depends(get_current_officine),
    ):
        """Cherche dans `amm_numbers` un produit correspondant au CIP scanné
        pour le pays par défaut configuré dans Admin Settings.

        Retourne `{found, country, product_name?, amm_number?, status?, expires_at?}`.
        """
        cip = payload.cip.strip()
        s = await db.settings.find_one({"_id": "global"}) or {}
        country = (s.get("amm_default_country") or "").strip().upper() or None

        # Recherche par CIP1 (le code scanné est généralement enregistré comme CIP1)
        # On accepte aussi sur amm_number au cas où le code scanné = AMM
        query: Dict[str, Any] = {"$or": [{"cip1": cip}, {"amm_number": cip}]}
        if country:
            # On préfère la même country mais on retombe sur tout si pas trouvé
            doc = await db.amm_numbers.find_one(
                {**query, "country_code": country}, {"_id": 0}
            )
            if not doc:
                # Fallback : produit existe mais sans country_code (legacy)
                doc = await db.amm_numbers.find_one(
                    {**query, "$or_country": [{"country_code": None}, {"country_code": ""}]} if False else
                    {**query, "country_code": {"$in": [None, ""]}}, {"_id": 0},
                )
        else:
            doc = await db.amm_numbers.find_one(query, {"_id": 0})

        if not doc:
            return {
                "found": False,
                "country": country,
                "cip": cip,
                "message": f"Aucun AMM trouvé pour ce code dans le catalogue {country or '(pays non configuré)'}. "
                           f"Le code reste enregistré tel quel dans votre fiche d'inventaire.",
            }

        # Détection d'expiration
        expired = False
        if doc.get("expires_at"):
            try:
                exp = datetime.fromisoformat(doc["expires_at"].replace("Z", "+00:00")) if "T" in str(doc["expires_at"]) else datetime.strptime(doc["expires_at"], "%Y-%m-%d")
                expired = exp.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) if exp.tzinfo is None else exp < datetime.now(timezone.utc)
            except Exception:  # noqa: BLE001
                expired = False
        return {
            "found": True,
            "country": doc.get("country_code") or country,
            "cip": cip,
            "product_name": doc.get("product_name"),
            "amm_number": doc.get("amm_number"),
            "laboratory": doc.get("laboratory"),
            "status": doc.get("status"),
            "expires_at": doc.get("expires_at"),
            "expired": expired,
            "internal_no": doc.get("internal_no"),
        }

    logger.info("[iter42d] incidents webhook + lookup AMM mounted")
