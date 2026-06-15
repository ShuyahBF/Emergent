"""Iter43-fix23 (2026-06) — Webhook REST POST pour les inventaires d'officines.

Permet aux officines (ou à leur SI) de pousser leur inventaire complet via une
simple requête REST POST authentifiée par Bearer token, en complément des modes
existants (CSV / JSON / endpoint HMAC).

Format payload identique au CSV :
    POST /api/webhooks/officines/inventory
    Authorization: Bearer <token>
    Content-Type: application/json

    {
      "officine_id": "uuid-de-l-officine",        # OBLIGATOIRE
      "items": [
        {
          "Nom de la pharmacie": "...",            # ignoré ici (info officine)
          "Téléphone": "...",
          "Ville": "...",
          "Indications de localisation": "...",
          "Numéro d'ordre": "...",
          # OU format inventaire (recommandé) :
          "product_name": "Doliprane 1000mg",
          "cip": "3400930000000",
          "lot_number": "LOT2026A",
          "expiry_date": "2027-12-31",
          "quantity": 25,
          "unit_price": 1500,
          "currency": "XOF",
          "available": true
        },
        ...
      ]
    }

Le token Bearer est partagé entre toutes les officines (configuré dans
`settings.global.officines_inventory_webhook_token`). En complément, chaque
payload doit identifier l'officine par `officine_id` — ce qui peut être un
secret par officine pour traçabilité.

Le format CSV (clés FR) est aussi accepté pour rétrocompatibilité avec les
imports CSV existants.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("sawali.officines_inventory_webhook")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    return str(s).strip()


class OfficineInventoryWebhookPayload(BaseModel):
    officine_id: str
    items: List[Dict[str, Any]]
    # Optional metadata pour audit
    source: Optional[str] = "webhook"
    notes: Optional[str] = None


def setup_officines_inventory_webhook_routes(*, db, api):
    """Monte le webhook d'inventaire officine.

    Note : `Depends(get_current_admin)` n'est PAS utilisé ici. L'auth se fait
    via Bearer token partagé (côté SI officine) + officine_id dans le payload.
    """

    @api.post(
        "/webhooks/officines/inventory",
        tags=["Webhooks — Officines"],
    )
    async def receive_inventory_webhook(
        payload: OfficineInventoryWebhookPayload = Body(...),
        authorization: Optional[str] = Header(None),
    ):
        """Reçoit l'inventaire d'une officine via Bearer token."""
        # 1) Auth Bearer
        s = await db.settings.find_one(
            {"_id": "global"},
            {"_id": 0, "officines_inventory_webhook_token": 1},
        ) or {}
        expected_token = (s.get("officines_inventory_webhook_token") or "").strip()
        if not expected_token:
            raise HTTPException(
                status_code=503,
                detail="Webhook d'inventaire non configuré (token absent côté admin).",
            )
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Authorization Bearer requis")
        token = authorization.split(" ", 1)[1].strip()
        # comparaison constant-time
        import hmac as _hmac
        if not _hmac.compare_digest(token, expected_token):
            raise HTTPException(status_code=401, detail="Token Bearer invalide")

        # 2) Vérifier que l'officine existe
        officine_id = (payload.officine_id or "").strip()
        if not officine_id:
            raise HTTPException(status_code=400, detail="`officine_id` requis")
        officine = await db.officines.find_one(
            {"id": officine_id},
            {"_id": 0, "id": 1, "name": 1, "status": 1},
        )
        if not officine:
            raise HTTPException(status_code=404, detail=f"Officine introuvable : {officine_id}")
        if officine.get("status") == "suspended":
            raise HTTPException(status_code=403, detail="Cette officine est suspendue")

        # 3) Normaliser les items (accepte 2 formats : CSV-keys FR ou JSON natif)
        items = payload.items or []
        if not isinstance(items, list):
            raise HTTPException(status_code=400, detail="`items` doit être une liste")
        if len(items) > 5000:
            raise HTTPException(status_code=413, detail="Trop d'items (max 5000 par appel)")

        created = 0
        updated = 0
        skipped = 0
        results: List[Dict[str, Any]] = []
        now = _now()

        for idx, raw in enumerate(items):
            if not isinstance(raw, dict):
                results.append({"index": idx, "skipped": True, "reason": "Item invalide (pas un objet)"})
                skipped += 1
                continue
            # Accepte les 2 conventions de clés
            product_name = _norm(
                raw.get("product_name")
                or raw.get("Nom du produit")
                or raw.get("Nom de la pharmacie")  # cas CSV : 1 produit = 1 ligne officine
            )
            if not product_name:
                # Si pas de produit explicite, on essaye d'extraire du champ CSV "Nom"
                product_name = _norm(raw.get("Nom") or raw.get("nom"))
            if not product_name:
                results.append({"index": idx, "skipped": True, "reason": "Nom du produit manquant"})
                skipped += 1
                continue

            cip = _norm(raw.get("cip") or raw.get("CIP") or raw.get("code_cip")) or None
            lot_number = _norm(raw.get("lot_number") or raw.get("Lot")) or None
            expiry_date = _norm(raw.get("expiry_date") or raw.get("Date de péremption") or raw.get("expiration")) or None
            try:
                quantity = int(raw.get("quantity") or raw.get("Quantité") or raw.get("qty") or 0)
            except (TypeError, ValueError):
                quantity = 0
            try:
                unit_price_raw = raw.get("unit_price") or raw.get("Prix unitaire") or raw.get("price")
                unit_price = float(unit_price_raw) if unit_price_raw is not None else None
            except (TypeError, ValueError):
                unit_price = None
            currency = _norm(raw.get("currency") or raw.get("Devise") or "XOF").upper()
            avail_raw = raw.get("available")
            available = True if avail_raw is None else bool(avail_raw)
            notes = _norm(raw.get("notes")) or None

            # Upsert : on identifie un item par (officine_id, product_name, lot_number)
            match = {"officine_id": officine_id, "product_name": product_name}
            if lot_number:
                match["lot_number"] = lot_number
            existing = await db.officine_inventory_items.find_one(match, {"_id": 0, "id": 1})
            if existing:
                await db.officine_inventory_items.update_one(
                    {"id": existing["id"]},
                    {"$set": {
                        "cip": cip,
                        "expiry_date": expiry_date,
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "currency": currency,
                        "available": available,
                        "notes": notes,
                        "updated_at": now,
                        "updated_via": payload.source or "webhook",
                    }},
                )
                updated += 1
                results.append({"index": idx, "updated": True, "item_id": existing["id"], "product_name": product_name})
            else:
                item_id = str(uuid.uuid4())
                doc = {
                    "id": item_id,
                    "officine_id": officine_id,
                    "cip": cip,
                    "product_name": product_name,
                    "lot_number": lot_number,
                    "expiry_date": expiry_date,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "currency": currency,
                    "available": available,
                    "notes": notes,
                    "created_at": now,
                    "updated_at": now,
                    "created_via": payload.source or "webhook",
                }
                await db.officine_inventory_items.insert_one(doc.copy())
                created += 1
                results.append({"index": idx, "created": True, "item_id": item_id, "product_name": product_name})

        # 4) Audit log
        try:
            await db.officine_audit_log.insert_one({
                "id": str(uuid.uuid4()),
                "officine_id": officine_id,
                "action": "inventory_webhook",
                "actor": "webhook",
                "details": {
                    "source": payload.source,
                    "items_received": len(items),
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                    "notes": payload.notes,
                },
                "created_at": now,
            })
        except Exception:  # noqa: BLE001
            pass

        # 5) Tracker registry (compteur global)
        try:
            await db.officines_inventory.update_one(
                {"officine_id": officine_id},
                {
                    "$set": {
                        "officine_id": officine_id,
                        "officine_name": officine.get("name"),
                        "last_webhook_at": now,
                        "inventory_count": await db.officine_inventory_items.count_documents({"officine_id": officine_id}),
                    },
                    "$inc": {"updates_count": 1, "webhook_calls": 1},
                },
                upsert=True,
            )
        except Exception:  # noqa: BLE001
            pass

        return {
            "ok": True,
            "officine_id": officine_id,
            "officine_name": officine.get("name"),
            "items_received": len(items),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "results": results[:200],  # cap la réponse
        }

    @api.get(
        "/webhooks/officines/inventory/docs",
        tags=["Webhooks — Officines"],
    )
    async def webhook_inventory_docs():
        """Documentation rapide pour intégrateurs SI officine."""
        return {
            "endpoint": "POST /api/webhooks/officines/inventory",
            "auth": "Authorization: Bearer <token-configuré-côté-admin>",
            "content_type": "application/json",
            "payload_schema": {
                "officine_id": "string (UUID de l'officine)",
                "items": [
                    {
                        "product_name": "string (obligatoire)",
                        "cip": "string (optionnel)",
                        "lot_number": "string (optionnel)",
                        "expiry_date": "string ISO YYYY-MM-DD (optionnel)",
                        "quantity": "int (>=0)",
                        "unit_price": "float (optionnel)",
                        "currency": "string (XOF/EUR/USD, défaut XOF)",
                        "available": "bool (défaut true)",
                        "notes": "string (optionnel)",
                    }
                ],
                "source": "string (optionnel — tag d'audit, ex. 'pharma-soft-v2')",
                "notes": "string (optionnel)",
            },
            "csv_compatibility": (
                "Les clés CSV françaises sont aussi acceptées : "
                "'Nom du produit', 'CIP', 'Lot', 'Date de péremption', "
                "'Quantité', 'Prix unitaire', 'Devise'."
            ),
            "limits": {"items_per_call": 5000, "rate_limit": "à venir"},
            "example_curl": (
                "curl -X POST https://sawalismartsystems.com/api/webhooks/officines/inventory "
                '-H "Authorization: Bearer YOUR_TOKEN" '
                '-H "Content-Type: application/json" '
                '-d \'{"officine_id":"abc-123","items":[{"product_name":"Doliprane 1000mg","cip":"3400930000000","quantity":50,"unit_price":1500}]}\''
            ),
        }

    logger.info("[officines_inventory_webhook] route mounted under /api/webhooks/officines/inventory")
