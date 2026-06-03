"""S025 — Download approval workflow.

When a non-admin user wants to download a non-public document, the request
is gated by a WhatsApp approval flow:

  1. Frontend POSTs to /me/download-requests with resource_label + resource_url
  2. Backend creates a `download_approvals` row (status=pending, token=secure)
  3. WhatsApp message is sent to the admin-configured approver number
     - If `download_approval_template_name` is set → Meta interactive template
       with 2 quick-reply buttons (payload: download_approve_{token} /
       download_deny_{token}). Quick-reply payload triggers the webhook
       (see server.py handler) which calls /api/wa-action/{token}/{a}.
     - Else (fallback) → plain text with 2 magic links.
  4. Frontend polls /me/download-requests/{token} every 2 s.
  5. When status = approved, frontend triggers the actual download.
  6. When status = denied, frontend shows the "Désolé, l'opération n'a pas
     été confirmée" toast and gives up.

Admin/superviseur users BYPASS the gate entirely (download directly).
"""
from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_token() -> str:
    return secrets.token_urlsafe(16)


def _is_admin_or_sup(user: dict) -> bool:
    if (user.get("role") or "") in ("admin", "superviseur"):
        return True
    if (user.get("tracked_role") or "") in ("Administrateur", "Superviseur"):
        return True
    return False


class DownloadRequest(BaseModel):
    resource_label: str = Field(..., min_length=1, max_length=240)
    resource_url: str = Field(..., min_length=1, max_length=2000)


def make_router(*, db, get_current_user, wa_send_text, wa_send_template=None, request_base_url=""):
    router = APIRouter(prefix="/me/download-requests", tags=["Téléchargements protégés"])

    async def _get_settings() -> dict:
        # All download-approval settings live under the global settings doc.
        s = await db.settings.find_one(
            {"_id": "global"},
            {
                "_id": 0,
                "download_approval_enabled": 1,
                "download_approval_whatsapp": 1,
                "download_pending_message": 1,
                "download_approval_template_name": 1,
                "download_approval_template_lang": 1,
                "download_approval_text_body": 1,
                "download_gauge_enabled": 1,
            },
        )
        return s or {}

    @router.post("")
    async def create_request(payload: DownloadRequest, request: Request, user: dict = Depends(get_current_user)):
        # Admin/Superviseur bypass entirely
        if _is_admin_or_sup(user):
            return {
                "token": None,
                "status": "approved",
                "direct": True,
                "approved_url": payload.resource_url,
            }
        settings = await _get_settings()
        if not settings.get("download_approval_enabled"):
            # Approval globally disabled → either everyone is blocked or
            # everyone bypasses. We allow direct download to preserve UX.
            return {
                "token": None,
                "status": "approved",
                "direct": True,
                "approved_url": payload.resource_url,
                "note": "approval-disabled",
            }
        approver = (settings.get("download_approval_whatsapp") or "").strip()
        if not approver:
            raise HTTPException(
                status_code=503,
                detail="Le workflow d'approbation n'est pas entièrement configuré (numéro approbateur manquant).",
            )
        token = _new_token()
        now = _now()
        # Resolve client_id for scoping
        tenant_id = user.get("parent_client_id") or user.get("client_id") or user.get("id")
        doc = {
            "id": token,
            "token": token,
            "tenant_id": tenant_id,
            "requester_id": user["id"],
            "requester_email": user.get("email"),
            "requester_name": user.get("full_name") or user.get("email") or "—",
            "resource_label": payload.resource_label[:240],
            "resource_url": payload.resource_url[:2000],
            "status": "pending",
            "created_at": now,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            "decided_at": None,
            "decided_by_phone": None,
            "decided_via": None,  # "template_button" | "magic_link" | "admin_override"
            "wa_send_status": None,
            "wa_send_error": None,
        }
        await db.download_approvals.insert_one(doc.copy())
        doc.pop("_id", None)

        # Build the WA message — template if configured, magic links otherwise.
        # Try to derive a public base URL from the request itself.
        base = request_base_url or str(request.base_url).rstrip("/")
        approve_url = f"{base}/api/wa-action/{token}/approve"
        deny_url = f"{base}/api/wa-action/{token}/deny"
        try:
            tpl_name = (settings.get("download_approval_template_name") or "").strip()
            if tpl_name and wa_send_template:
                # Interactive Meta template (variables: requester, resource_label).
                # The template must declare 2 QUICK_REPLY buttons whose payloads
                # are `download_approve_{TOKEN}` and `download_deny_{TOKEN}`.
                lang = (settings.get("download_approval_template_lang") or "fr").strip()
                params = [
                    doc["requester_name"],
                    doc["resource_label"],
                ]
                # Inject the token into the payload of each quick-reply button.
                buttons_payload = [
                    {"sub_type": "quick_reply", "index": 0, "parameters": [
                        {"type": "payload", "payload": f"download_approve_{token}"},
                    ]},
                    {"sub_type": "quick_reply", "index": 1, "parameters": [
                        {"type": "payload", "payload": f"download_deny_{token}"},
                    ]},
                ]
                send_res = await wa_send_template(
                    to_e164=approver,
                    template_name=tpl_name,
                    language=lang,
                    body_params=params,
                    button_params=buttons_payload,
                )
                doc["wa_send_status"] = "template_sent" if send_res.get("ok") else "template_failed"
                doc["wa_send_error"] = send_res.get("error") if not send_res.get("ok") else None
            else:
                # Fallback: plain text with 2 magic links
                body = settings.get("download_approval_text_body") or (
                    "Demande de téléchargement reçue.\n\n"
                    "Utilisateur : {requester}\n"
                    "Document : {label}\n\n"
                    "✅ AUTORISER : {approve}\n"
                    "❌ REFUSER : {deny}\n\n"
                    "Liens valides 24 h."
                )
                body = (body
                    .replace("{requester}", doc["requester_name"])
                    .replace("{label}", doc["resource_label"])
                    .replace("{approve}", approve_url)
                    .replace("{deny}", deny_url))
                send_res = await wa_send_text(approver, body)
                doc["wa_send_status"] = "text_sent" if send_res.get("ok") else "text_failed"
                doc["wa_send_error"] = send_res.get("error") if not send_res.get("ok") else None
        except Exception as exc:  # noqa: BLE001
            doc["wa_send_status"] = "exception"
            doc["wa_send_error"] = str(exc)[:500]
        await db.download_approvals.update_one(
            {"token": token},
            {"$set": {
                "wa_send_status": doc["wa_send_status"],
                "wa_send_error": doc["wa_send_error"],
            }},
        )

        pending_msg = settings.get("download_pending_message") or "En attente d'approbation pour le téléchargement..."
        # P3 (2026-02) — Default to TRUE for back-compat. When admin sets
        # `download_gauge_enabled=False`, the frontend hides the central
        # fullscreen gauge and shows a discreet toast instead.
        gauge_enabled = settings.get("download_gauge_enabled")
        gauge_enabled = True if gauge_enabled is None else bool(gauge_enabled)
        return {
            "token": token,
            "status": "pending",
            "direct": False,
            "pending_message": pending_msg,
            "wa_send_status": doc["wa_send_status"],
            "expires_at": doc["expires_at"],
            "gauge_enabled": gauge_enabled,
        }

    @router.get("/{token}")
    async def get_status(token: str, user: dict = Depends(get_current_user)):
        # Only the requester can poll their own request (or admin/sup)
        doc = await db.download_approvals.find_one({"token": token}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Demande introuvable")
        if doc["requester_id"] != user["id"] and not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        # Auto-expire stale pending requests
        if doc["status"] == "pending":
            try:
                exp = datetime.fromisoformat(doc["expires_at"].replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > exp:
                    await db.download_approvals.update_one(
                        {"token": token},
                        {"$set": {"status": "expired", "decided_at": _now()}},
                    )
                    doc["status"] = "expired"
            except (ValueError, TypeError):
                pass
        return doc

    @router.post("/{token}/cancel")
    async def cancel_request(token: str, user: dict = Depends(get_current_user)):
        doc = await db.download_approvals.find_one({"token": token}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Demande introuvable")
        if doc["requester_id"] != user["id"] and not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        if doc["status"] != "pending":
            return doc
        await db.download_approvals.update_one(
            {"token": token},
            {"$set": {"status": "cancelled", "decided_at": _now()}},
        )
        doc["status"] = "cancelled"
        return doc

    # ----------------------------------------------------------------
    # S029 — Audit journal (admin/superviseur only). Returns the full
    # history of download-approval requests with optional filters.
    # ----------------------------------------------------------------
    @router.get("/admin/audit", tags=["Téléchargements protégés", "Admin"])
    async def admin_audit(
        status: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 200,
        user: dict = Depends(get_current_user),
    ):
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Accès réservé à admin/superviseur")
        limit = max(1, min(int(limit or 200), 1000))
        query: Dict[str, Any] = {}
        if status and status not in ("all", ""):
            valid = {"pending", "approved", "denied", "expired", "cancelled"}
            if status not in valid:
                raise HTTPException(status_code=400, detail=f"status doit être l'un de {sorted(valid | {'all'})}")
            query["status"] = status
        if q:
            qr = q.strip()
            query["$or"] = [
                {"requester_email": {"$regex": qr, "$options": "i"}},
                {"requester_name": {"$regex": qr, "$options": "i"}},
                {"resource_label": {"$regex": qr, "$options": "i"}},
            ]
        cursor = db.download_approvals.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
        items = [doc async for doc in cursor]
        # Counters (independent of filter — for the dashboard cards)
        counters = {}
        for k in ("pending", "approved", "denied", "expired", "cancelled"):
            counters[k] = await db.download_approvals.count_documents({"status": k})
        return {"items": items, "count": len(items), "counters": counters}

    return router


# -----------------------------------------------------------------
# Public (no-auth) endpoint for magic-link button clicks from WA.
# Mounted separately so its prefix doesn't get the /me protection.
# -----------------------------------------------------------------
def make_public_router(*, db, request_base_url=""):
    public = APIRouter(prefix="/wa-action", tags=["Téléchargements protégés (public)"])

    @public.get("/{token}/{action}")
    async def public_decide(token: str, action: str):
        if action not in ("approve", "deny"):
            raise HTTPException(status_code=400, detail="action doit être approve ou deny")
        doc = await db.download_approvals.find_one({"token": token}, {"_id": 0})
        if not doc:
            html = "<h2>Lien invalide ou expiré</h2>"
            return _html_resp(html, 404)
        if doc["status"] != "pending":
            html = f"<h2>Cette demande est déjà <strong>{doc['status']}</strong></h2>"
            return _html_resp(html, 200)
        new_status = "approved" if action == "approve" else "denied"
        await db.download_approvals.update_one(
            {"token": token},
            {"$set": {
                "status": new_status,
                "decided_at": _now(),
                "decided_via": "magic_link",
            }},
        )
        emoji = "✅" if new_status == "approved" else "❌"
        msg = "Téléchargement autorisé" if new_status == "approved" else "Téléchargement refusé"
        return _html_resp(f"""
<!doctype html><html><head><meta charset='utf-8'><title>Décision enregistrée</title>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<style>body{{font-family:system-ui;background:#0f172a;color:#f1f5f9;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:1rem}}
.card{{background:#1e293b;padding:2rem;border-radius:1rem;text-align:center;max-width:420px}}
.emoji{{font-size:3rem}} h1{{margin:0.5rem 0}} p{{color:#cbd5e1}}</style></head>
<body><div class='card'><div class='emoji'>{emoji}</div><h1>{msg}</h1>
<p>Document : <strong>{doc['resource_label']}</strong></p>
<p>Demande par : <strong>{doc['requester_name']}</strong></p>
<p style='font-size:.85rem;opacity:.7;margin-top:1.5rem'>Vous pouvez fermer cette fenêtre.</p></div></body></html>
""", 200)

    return public


def _html_resp(html: str, code: int):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html, status_code=code)


# -----------------------------------------------------------------
# Webhook helper — called from the existing WhatsApp webhook handler
# whenever an incoming message is an "interactive" button_reply OR a
# legacy template "button" reply. Returns True if the payload matched
# a download-approval token (so the caller can short-circuit normal
# message processing).
# -----------------------------------------------------------------
DOWNLOAD_BUTTON_PAYLOAD_RE = re.compile(r"^download_(approve|deny)_([A-Za-z0-9_\-]{6,64})$")


async def handle_button_payload(*, db, payload: str, from_phone: Optional[str]) -> bool:
    m = DOWNLOAD_BUTTON_PAYLOAD_RE.match(payload or "")
    if not m:
        return False
    action, token = m.group(1), m.group(2)
    doc = await db.download_approvals.find_one({"token": token}, {"_id": 0})
    if not doc or doc.get("status") != "pending":
        return True  # matched but already resolved — suppress regular processing
    new_status = "approved" if action == "approve" else "denied"
    await db.download_approvals.update_one(
        {"token": token},
        {"$set": {
            "status": new_status,
            "decided_at": _now(),
            "decided_via": "template_button",
            "decided_by_phone": from_phone,
        }},
    )
    return True


__all__ = ["make_router", "make_public_router", "handle_button_payload"]
