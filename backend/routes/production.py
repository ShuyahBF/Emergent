"""Iter43-fix24az-f (2026-02-26) — Production module for `business_type=fabricant` tenants.

Data model
==========
- `production_intrants` (raw materials & overhead resources) — one bag per tenant
    { id, client_id, name, unit, unit_cost, category, notes, created_at, updated_at }
    category ∈ { raw_material, packaging, water, electricity, labor, amortization, other }
    unit ∈ ml, g, kWh, h, unit, kg, L, m3, min

- `production_recipes` — one recipe = one finished product (variant)
    { id, client_id, name, variant_label, output_batch_units, output_unit_label,
      intrants: [{intrant_id, quantity, unit_cost_snapshot, name_snapshot, unit_snapshot, category_snapshot}],
      pricing_mode, margin_pct, public_price,
      catalog_product_id, notes, created_at, updated_at }

Pricing
=======
`cost_price` per finished unit = Σ (intrant.quantity × intrant.unit_cost) / output_batch_units
`margin_pct` and `public_price` are linked by:
    public_price = cost_price × (1 + margin_pct / 100)
The client decides via `pricing_mode`:
    - "margin_first" → user sets margin_pct, we compute public_price
    - "price_first"  → user sets public_price, we compute margin_pct
Default margin for fabricants = 42% (settings.production_default_margin_pct).

PDF exports
===========
- GET /api/production/export/recipes.pdf → global table (like the user's Cout de Prod PDF)
- GET /api/production/export/recipe/{id}.pdf → single recipe sheet with intrants breakdown

Access control
==============
Only admin/superviseur users of a `business_type=fabricant` tenant can access.
"""
from __future__ import annotations

import io
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.production")

VALID_CATEGORIES = {
    "raw_material",
    "packaging",
    "water",
    "electricity",
    "labor",
    "amortization",
    "other",
}
VALID_UNITS = {"ml", "g", "kWh", "h", "min", "unit", "kg", "L", "m3", "pct"}
VALID_PRICING_MODES = {"margin_first", "price_first"}
DEFAULT_MARGIN_PCT = 42.0


# ---------------------------------------------------------------------------
# Pydantic payloads
# ---------------------------------------------------------------------------
class IntrantPayload(BaseModel):
    name: str
    unit: str = "ml"
    unit_cost: float = 0.0
    category: str = "raw_material"
    notes: Optional[str] = None


class RecipeIntrantIn(BaseModel):
    intrant_id: str
    # Legacy field kept for backward-compat with old recipes.
    # Iter43-fix24az-h (2026-02-26) — With the new dosage model, each intrant's
    # cost contribution = unit_cost × recipe.dosage_number, so the per-intrant
    # quantity is no longer used for new recipes. It stays 0 by default.
    quantity: float = 0.0


class RecipePayload(BaseModel):
    name: str
    variant_label: Optional[str] = None  # auto-derived from dosage_* when saved
    # Iter43-fix24az-h (2026-02-26) — Dosage split into number + unit.
    # The cost of each intrant in the recipe = intrant.unit_cost × dosage_number.
    # 4-decimal precision supported for unit_cost.
    dosage_number: Optional[float] = None
    dosage_unit: Optional[str] = "ml"
    output_batch_units: float = 1.0
    output_unit_label: Optional[str] = "unit"
    intrants: List[RecipeIntrantIn] = Field(default_factory=list)
    pricing_mode: str = "margin_first"
    margin_pct: Optional[float] = None
    public_price: Optional[float] = None
    catalog_product_id: Optional[str] = None
    notes: Optional[str] = None


class SettingsPayload(BaseModel):
    production_default_margin_pct: Optional[float] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tenant_scope(user: Dict[str, Any]) -> str:
    """Consistent tenant scope: prefer `client_id` (linked tenant),
    otherwise the user's own id."""
    return user.get("client_id") or user["id"]


async def _tenant_business_type(db, user: Dict[str, Any]) -> str:
    """Business type lives on the tenant's *primary* admin document. For
    linked users (client_id != id), we look it up on the parent tenant."""
    tenant_id = _tenant_scope(user)
    if tenant_id == user["id"]:
        return (user.get("business_type") or "").lower()
    parent = await db.users.find_one({"id": tenant_id}, {"_id": 0, "business_type": 1})
    return ((parent or {}).get("business_type") or "").lower()


async def _require_fabricant_admin(db, user: Dict[str, Any]) -> None:
    if user.get("role") not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Réservé aux admin/superviseur")
    bt = await _tenant_business_type(db, user)
    if bt != "fabricant":
        raise HTTPException(status_code=403, detail="Réservé aux tenants Fabricant")


async def _default_margin(db) -> float:
    try:
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "production_default_margin_pct": 1}) or {}
        v = s.get("production_default_margin_pct")
        if v is not None:
            return float(v)
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_MARGIN_PCT


def _compute_recipe(recipe: Dict[str, Any], default_margin: float) -> Dict[str, Any]:
    """Compute cost_price, public_price, margin_pct from stored recipe data.

    Iter43-fix24az-h (2026-02-26) — Cost model has TWO branches :

    * NEW (dosage-based) : when `recipe.dosage_number` > 0, the cost of most
      intrants = intrant.unit_cost_snapshot × dosage_number.
      Iter43-fix24az-l (2026-02-26) — `packaging` and `other` categories do NOT
      scale with the dosage (they are per-unit fixed costs like flacons,
      étiquettes). Their contribution stays = unit_cost_snapshot × 1.
      All OTHER categories (raw_material, water, electricity, labor,
      amortization) DO scale with dosage.
      Supports up to 4 decimals on unit_cost.

    * LEGACY (per-intrant quantity) : older recipes without dosage_number keep
      the historical formula cost = Σ(quantity × unit_cost_snapshot). This
      guarantees backward-compatibility for existing data.

    Uses each intrant's snapshotted unit_cost so the computation is stable
    even if the intrant's unit_cost is later modified in the library.
    """
    intrants = recipe.get("intrants") or []
    dosage_number = recipe.get("dosage_number")
    try:
        dosage_number = float(dosage_number) if dosage_number is not None else None
    except (TypeError, ValueError):
        dosage_number = None
    cost_batch = 0.0
    # Categories whose cost does NOT scale with the recipe dosage.
    _FIXED_CATEGORIES = {"packaging", "other"}
    if dosage_number is not None and dosage_number > 0:
        # New model
        for it in intrants:
            cat = it.get("category_snapshot") or "raw_material"
            uc = float(it.get("unit_cost_snapshot") or 0)
            if cat in _FIXED_CATEGORIES:
                cost_batch += uc  # per-batch fixed cost
            else:
                cost_batch += uc * dosage_number
    else:
        # Legacy model
        for it in intrants:
            qty = float(it.get("quantity") or 0)
            cost = float(it.get("unit_cost_snapshot") or 0)
            cost_batch += qty * cost
    batch_units = float(recipe.get("output_batch_units") or 1.0)
    if batch_units <= 0:
        batch_units = 1.0
    cost_price = cost_batch / batch_units
    pricing_mode = recipe.get("pricing_mode") or "margin_first"
    margin_pct = recipe.get("margin_pct")
    public_price = recipe.get("public_price")
    if pricing_mode == "price_first" and public_price is not None:
        try:
            public_price = float(public_price)
        except (TypeError, ValueError):
            public_price = 0.0
        margin_pct = (public_price / cost_price - 1.0) * 100.0 if cost_price > 0 else 0.0
    else:
        # margin_first (default)
        try:
            margin_pct = float(margin_pct) if margin_pct is not None else float(default_margin)
        except (TypeError, ValueError):
            margin_pct = float(default_margin)
        public_price = cost_price * (1.0 + margin_pct / 100.0)
    profit = public_price - cost_price
    recipe["cost_price"] = round(cost_price, 4)
    recipe["public_price"] = round(public_price, 2)
    recipe["margin_pct"] = round(margin_pct, 2)
    recipe["profit_per_unit"] = round(profit, 2)
    recipe["intrants_total_batch"] = round(cost_batch, 4)
    return recipe


async def _hydrate_intrants_snapshot(db, tenant: str, intrants_in: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach snapshot data (name/unit/cost/category) to each recipe intrant."""
    if not intrants_in:
        return []
    ids = [i["intrant_id"] for i in intrants_in if i.get("intrant_id")]
    cursor = db.production_intrants.find(
        {"client_id": tenant, "id": {"$in": ids}}, {"_id": 0},
    )
    idx = {i["id"]: i async for i in cursor}
    hydrated: List[Dict[str, Any]] = []
    for it in intrants_in:
        ref = idx.get(it["intrant_id"])
        if not ref:
            continue
        hydrated.append({
            "intrant_id": it["intrant_id"],
            "quantity": float(it.get("quantity") or 0),
            "unit_cost_snapshot": float(ref.get("unit_cost") or 0),
            "name_snapshot": ref.get("name") or "?",
            "unit_snapshot": ref.get("unit") or "unit",
            "category_snapshot": ref.get("category") or "raw_material",
        })
    return hydrated


# ---------------------------------------------------------------------------
# Route attachment
# ---------------------------------------------------------------------------
def attach_production_routes(*, api, db, get_current_user):

    # ---- INTRANTS ----
    @api.get("/production/intrants", tags=["Production"])
    async def list_intrants(
        category: Optional[str] = Query(None),
        user: Dict = Depends(get_current_user),
    ):
        await _require_fabricant_admin(db, user)
        q: Dict[str, Any] = {"client_id": _tenant_scope(user)}
        if category:
            q["category"] = category
        items: List[Dict] = []
        async for i in db.production_intrants.find(q, {"_id": 0}).sort("name", 1):
            items.append(i)
        return {"items": items, "count": len(items)}

    @api.post("/production/intrants", tags=["Production"])
    async def create_intrant(payload: IntrantPayload, user: Dict = Depends(get_current_user)):
        await _require_fabricant_admin(db, user)
        if not payload.name.strip():
            raise HTTPException(status_code=400, detail="Nom requis")
        if payload.category not in VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Catégorie invalide (autorisées : {sorted(VALID_CATEGORIES)})")
        if payload.unit not in VALID_UNITS:
            raise HTTPException(status_code=400, detail=f"Unité invalide (autorisées : {sorted(VALID_UNITS)})")
        if payload.unit_cost < 0:
            raise HTTPException(status_code=400, detail="Coût unitaire doit être ≥ 0")
        now = _now_iso()
        doc = {
            "id": str(uuid.uuid4()),
            "client_id": _tenant_scope(user),
            "name": payload.name.strip(),
            "unit": payload.unit,
            "unit_cost": float(payload.unit_cost),
            "category": payload.category,
            "notes": (payload.notes or "").strip(),
            "created_at": now,
            "updated_at": now,
            "created_by": user.get("email"),
        }
        await db.production_intrants.insert_one(doc)
        doc.pop("_id", None)
        return doc

    @api.put("/production/intrants/{iid}", tags=["Production"])
    async def update_intrant(iid: str, payload: IntrantPayload, user: Dict = Depends(get_current_user)):
        await _require_fabricant_admin(db, user)
        if payload.category not in VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail="Catégorie invalide")
        if payload.unit not in VALID_UNITS:
            raise HTTPException(status_code=400, detail="Unité invalide")
        if payload.unit_cost < 0:
            raise HTTPException(status_code=400, detail="Coût unitaire doit être ≥ 0")
        res = await db.production_intrants.update_one(
            {"id": iid, "client_id": _tenant_scope(user)},
            {"$set": {
                "name": payload.name.strip(),
                "unit": payload.unit,
                "unit_cost": float(payload.unit_cost),
                "category": payload.category,
                "notes": (payload.notes or "").strip(),
                "updated_at": _now_iso(),
                "updated_by": user.get("email"),
            }},
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Intrant introuvable")
        return {"ok": True, "id": iid}

    @api.delete("/production/intrants/{iid}", tags=["Production"])
    async def delete_intrant(iid: str, user: Dict = Depends(get_current_user)):
        await _require_fabricant_admin(db, user)
        # Refuser si utilisé dans au moins une recette (protège l'historique)
        in_use = await db.production_recipes.count_documents(
            {"client_id": _tenant_scope(user), "intrants.intrant_id": iid},
        )
        if in_use > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Impossible de supprimer : {in_use} recette(s) utilisent cet intrant.",
            )
        res = await db.production_intrants.delete_one({"id": iid, "client_id": _tenant_scope(user)})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Intrant introuvable")
        return {"ok": True, "id": iid}

    # ---- RECIPES ----
    @api.get("/production/recipes", tags=["Production"])
    async def list_recipes(user: Dict = Depends(get_current_user)):
        await _require_fabricant_admin(db, user)
        default_m = await _default_margin(db)
        items: List[Dict] = []
        async for r in db.production_recipes.find(
            {"client_id": _tenant_scope(user)}, {"_id": 0},
        ).sort("name", 1):
            items.append(_compute_recipe(r, default_m))
        # Chart-friendly summary
        summary = {
            "total_recipes": len(items),
            "avg_cost_price": round(sum(r["cost_price"] for r in items) / len(items), 2) if items else 0,
            "avg_public_price": round(sum(r["public_price"] for r in items) / len(items), 2) if items else 0,
            "avg_margin_pct": round(sum(r["margin_pct"] for r in items) / len(items), 2) if items else 0,
        }
        return {"items": items, "summary": summary, "default_margin_pct": default_m}

    @api.post("/production/recipes", tags=["Production"])
    async def create_recipe(payload: RecipePayload, user: Dict = Depends(get_current_user)):
        await _require_fabricant_admin(db, user)
        if payload.pricing_mode not in VALID_PRICING_MODES:
            raise HTTPException(status_code=400, detail=f"pricing_mode invalide : {payload.pricing_mode}")
        if payload.output_batch_units <= 0:
            raise HTTPException(status_code=400, detail="output_batch_units doit être > 0")
        tenant = _tenant_scope(user)
        now = _now_iso()
        default_m = await _default_margin(db)
        hydrated = await _hydrate_intrants_snapshot(db, tenant, [i.model_dump() for i in payload.intrants])
        # Iter43-fix24az-h — auto-derive variant_label from dosage_number + dosage_unit
        # (e.g. dosage_number=50 + dosage_unit="ml" -> "50 ml"). Legacy payloads
        # that still send variant_label keep priority when dosage is absent.
        dosage_number = float(payload.dosage_number) if payload.dosage_number is not None else None
        dosage_unit = (payload.dosage_unit or "ml").strip() or "ml"
        variant_label = (payload.variant_label or "").strip() or None
        if variant_label is None and dosage_number is not None and dosage_number > 0:
            # Prefer integer formatting when dosage_number is a whole number
            n_str = f"{dosage_number:g}"
            variant_label = f"{n_str} {dosage_unit}"
        # Iter43-fix24az-l — Uniqueness constraint (Task 4) : (name + dosage_number + dosage_unit)
        _dup_q: Dict[str, Any] = {
            "client_id": tenant,
            "name": {"$regex": f"^{re.escape(payload.name.strip())}$", "$options": "i"},
            "dosage_number": dosage_number,
            "dosage_unit": dosage_unit,
        }
        if await db.production_recipes.find_one(_dup_q, {"_id": 0, "id": 1}):
            raise HTTPException(
                status_code=409,
                detail=f"Une recette existe déjà avec ce nom + dosage : « {payload.name.strip()} {dosage_number or ''} {dosage_unit or ''} ».",
            )
        doc: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "client_id": tenant,
            "name": payload.name.strip(),
            "variant_label": variant_label,
            "dosage_number": dosage_number,
            "dosage_unit": dosage_unit,
            "output_batch_units": float(payload.output_batch_units),
            "output_unit_label": (payload.output_unit_label or "unit").strip(),
            "intrants": hydrated,
            "pricing_mode": payload.pricing_mode,
            "margin_pct": payload.margin_pct if payload.margin_pct is not None else None,
            "public_price": payload.public_price,
            "catalog_product_id": payload.catalog_product_id,
            "notes": (payload.notes or "").strip(),
            "created_at": now,
            "updated_at": now,
            "created_by": user.get("email"),
        }
        await db.production_recipes.insert_one(doc)
        doc.pop("_id", None)
        return _compute_recipe(doc, default_m)

    @api.put("/production/recipes/{rid}", tags=["Production"])
    async def update_recipe(rid: str, payload: RecipePayload, user: Dict = Depends(get_current_user)):
        await _require_fabricant_admin(db, user)
        if payload.pricing_mode not in VALID_PRICING_MODES:
            raise HTTPException(status_code=400, detail="pricing_mode invalide")
        if payload.output_batch_units <= 0:
            raise HTTPException(status_code=400, detail="output_batch_units doit être > 0")
        tenant = _tenant_scope(user)
        hydrated = await _hydrate_intrants_snapshot(db, tenant, [i.model_dump() for i in payload.intrants])
        default_m = await _default_margin(db)
        dosage_number = float(payload.dosage_number) if payload.dosage_number is not None else None
        dosage_unit = (payload.dosage_unit or "ml").strip() or "ml"
        variant_label = (payload.variant_label or "").strip() or None
        if variant_label is None and dosage_number is not None and dosage_number > 0:
            n_str = f"{dosage_number:g}"
            variant_label = f"{n_str} {dosage_unit}"
        # Iter43-fix24az-l — Uniqueness on (name + dosage_number + dosage_unit)
        _dup_q: Dict[str, Any] = {
            "client_id": tenant,
            "name": {"$regex": f"^{re.escape(payload.name.strip())}$", "$options": "i"},
            "dosage_number": dosage_number,
            "dosage_unit": dosage_unit,
            "id": {"$ne": rid},
        }
        if await db.production_recipes.find_one(_dup_q, {"_id": 0, "id": 1}):
            raise HTTPException(
                status_code=409,
                detail=f"Une autre recette existe déjà avec ce nom + dosage : « {payload.name.strip()} {dosage_number or ''} {dosage_unit or ''} ».",
            )
        res = await db.production_recipes.update_one(
            {"id": rid, "client_id": tenant},
            {"$set": {
                "name": payload.name.strip(),
                "variant_label": variant_label,
                "dosage_number": dosage_number,
                "dosage_unit": dosage_unit,
                "output_batch_units": float(payload.output_batch_units),
                "output_unit_label": (payload.output_unit_label or "unit").strip(),
                "intrants": hydrated,
                "pricing_mode": payload.pricing_mode,
                "margin_pct": payload.margin_pct,
                "public_price": payload.public_price,
                "catalog_product_id": payload.catalog_product_id,
                "notes": (payload.notes or "").strip(),
                "updated_at": _now_iso(),
                "updated_by": user.get("email"),
            }},
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Recette introuvable")
        doc = await db.production_recipes.find_one({"id": rid, "client_id": tenant}, {"_id": 0})
        return _compute_recipe(doc, default_m)

    @api.delete("/production/recipes/{rid}", tags=["Production"])
    async def delete_recipe(rid: str, user: Dict = Depends(get_current_user)):
        await _require_fabricant_admin(db, user)
        res = await db.production_recipes.delete_one({"id": rid, "client_id": _tenant_scope(user)})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Recette introuvable")
        return {"ok": True, "id": rid}

    # Iter43-fix24az-l (2026-02-26) — Task 3 : Duplicate a recipe.
    # The duplicate has the SAME name/intrants/margin/notes but the dosage is
    # CLEARED (must be set by the user before saving). This preserves the
    # (name, dosage_number, dosage_unit) uniqueness constraint since a null
    # dosage differs from the source's dosage.
    @api.post("/production/recipes/{rid}/duplicate", tags=["Production"])
    async def duplicate_recipe(rid: str, user: Dict = Depends(get_current_user)):
        await _require_fabricant_admin(db, user)
        tenant = _tenant_scope(user)
        src = await db.production_recipes.find_one({"id": rid, "client_id": tenant}, {"_id": 0})
        if not src:
            raise HTTPException(status_code=404, detail="Recette source introuvable")
        default_m = await _default_margin(db)
        now = _now_iso()
        new_id = str(uuid.uuid4())
        # Compute a unique suffix on the name to avoid the uniqueness clash
        # when the user later saves without changing the dosage.
        base_name = src.get("name") or "Recette"
        candidate = f"{base_name} (copie)"
        idx = 2
        while await db.production_recipes.find_one({
            "client_id": tenant,
            "name": {"$regex": f"^{re.escape(candidate)}$", "$options": "i"},
            "dosage_number": None,
            "dosage_unit": src.get("dosage_unit") or "ml",
        }, {"_id": 0, "id": 1}):
            candidate = f"{base_name} (copie {idx})"
            idx += 1
        doc: Dict[str, Any] = {
            "id": new_id,
            "client_id": tenant,
            "name": candidate,
            "variant_label": None,
            "dosage_number": None,  # cleared — user must set
            "dosage_unit": src.get("dosage_unit") or "ml",
            "output_batch_units": float(src.get("output_batch_units") or 1),
            "output_unit_label": src.get("output_unit_label") or "unit",
            "intrants": src.get("intrants") or [],
            "pricing_mode": src.get("pricing_mode") or "margin_first",
            "margin_pct": src.get("margin_pct"),
            "public_price": src.get("public_price"),
            "catalog_product_id": src.get("catalog_product_id"),
            "notes": src.get("notes") or "",
            "created_at": now,
            "updated_at": now,
            "created_by": user.get("email"),
            "duplicated_from": rid,
        }
        await db.production_recipes.insert_one(doc)
        doc.pop("_id", None)
        return _compute_recipe(doc, default_m)



    # ---- SETTINGS ----
    @api.get("/production/settings", tags=["Production"])
    async def get_prod_settings(user: Dict = Depends(get_current_user)):
        await _require_fabricant_admin(db, user)
        default_m = await _default_margin(db)
        return {"production_default_margin_pct": default_m}

    @api.put("/production/settings", tags=["Production"])
    async def put_prod_settings(payload: SettingsPayload, user: Dict = Depends(get_current_user)):
        await _require_fabricant_admin(db, user)
        if payload.production_default_margin_pct is None:
            raise HTTPException(status_code=400, detail="production_default_margin_pct requis")
        v = float(payload.production_default_margin_pct)
        if v < -100 or v > 1000:
            raise HTTPException(status_code=400, detail="Marge doit être entre -100 et 1000")
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"production_default_margin_pct": v, "production_updated_by": user.get("email"), "production_updated_at": _now_iso()}},
            upsert=True,
        )
        return {"ok": True, "production_default_margin_pct": v}

    # ---- PDF EXPORTS ----
    @api.get("/production/export/recipes.pdf", tags=["Production"])
    async def export_recipes_pdf(user: Dict = Depends(get_current_user)):
        """Global table (like the joined 'Cout de Prod' PDF)."""
        await _require_fabricant_admin(db, user)
        default_m = await _default_margin(db)
        tenant = _tenant_scope(user)
        recipes: List[Dict] = []
        async for r in db.production_recipes.find({"client_id": tenant}, {"_id": 0}).sort("name", 1):
            recipes.append(_compute_recipe(r, default_m))
        # Iter43-fix24az-l retest — Offload CPU-intensive ReportLab rendering
        # to a thread so it doesn't block the uvicorn event loop (Cloudflare 520
        # mitigation on single-worker deploys).
        import asyncio as _asyncio  # local alias — module already imports asyncio elsewhere
        tenant_name = user.get("company") or user.get("full_name") or ""
        buf = await _asyncio.to_thread(_render_recipes_pdf, recipes, tenant_name=tenant_name)
        return Response(
            content=buf,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="production_recipes.pdf"'},
        )

    @api.get("/production/export/recipe/{rid}.pdf", tags=["Production"])
    async def export_single_recipe_pdf(rid: str, user: Dict = Depends(get_current_user)):
        await _require_fabricant_admin(db, user)
        default_m = await _default_margin(db)
        r = await db.production_recipes.find_one(
            {"id": rid, "client_id": _tenant_scope(user)}, {"_id": 0},
        )
        if not r:
            raise HTTPException(status_code=404, detail="Recette introuvable")
        rec = _compute_recipe(r, default_m)
        # Iter43-fix24az-l retest — Offload CPU-intensive ReportLab rendering.
        import asyncio as _asyncio
        tenant_name = user.get("company") or user.get("full_name") or ""
        buf = await _asyncio.to_thread(_render_single_recipe_pdf, rec, tenant_name=tenant_name)
        return Response(
            content=buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="recipe_{rid[:8]}.pdf"'},
        )


# ---------------------------------------------------------------------------
# PDF rendering helpers (reportlab)
# ---------------------------------------------------------------------------
def _render_recipes_pdf(recipes: List[Dict[str, Any]], *, tenant_name: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm, topMargin=12 * mm, bottomMargin=10 * mm)
    styles = getSampleStyleSheet()
    story: List[Any] = []
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    story.append(Paragraph(f"<b>PRIX DE REVIENT / COÛT DE PRODUCTION</b> — {tenant_name}", styles["Title"]))
    story.append(Paragraph(f"<font size=8 color='#666'>Édité le {now_str} · {len(recipes)} recette(s)</font>", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))
    if not recipes:
        story.append(Paragraph("Aucune recette enregistrée.", styles["Normal"]))
    else:
        # Build a matrix : rows = intrants (union), cols = recipes
        intrant_key = lambda i: i.get("name_snapshot", "?")  # noqa: E731
        # Sorted list of intrants (raw materials first, then packaging, then indirect)
        cat_order = {"raw_material": 0, "packaging": 1, "water": 2, "electricity": 3, "labor": 4, "amortization": 5, "other": 6}
        all_intrants: Dict[str, Dict[str, Any]] = {}
        for r in recipes:
            for i in r.get("intrants", []):
                k = intrant_key(i)
                if k not in all_intrants:
                    all_intrants[k] = {
                        "name": k,
                        "unit": i.get("unit_snapshot"),
                        "unit_cost": i.get("unit_cost_snapshot", 0),
                        "category": i.get("category_snapshot", "raw_material"),
                    }
        int_sorted = sorted(
            all_intrants.values(),
            key=lambda x: (cat_order.get(x["category"], 9), x["name"] or ""),
        )
        header = ["INTRANTS", "COÛT UNIT."] + [_recipe_label(r) for r in recipes]
        data: List[List[Any]] = [header]
        for intrant in int_sorted:
            row: List[Any] = [intrant["name"], f"{intrant['unit_cost']:.4f} / {intrant['unit']}"]
            for r in recipes:
                # Iter43-fix24az-h — dosage-aware quantity display.
                dosage_number = r.get("dosage_number")
                try:
                    dosage_number = float(dosage_number) if dosage_number is not None else None
                except (TypeError, ValueError):
                    dosage_number = None
                use_dosage = dosage_number is not None and dosage_number > 0
                q = 0.0
                present = False
                for i in r.get("intrants", []):
                    if intrant_key(i) == intrant["name"]:
                        present = True
                        q = dosage_number if use_dosage else i.get("quantity", 0)
                        break
                if not present:
                    row.append("—")
                elif use_dosage:
                    row.append(f"{q:g}")
                else:
                    row.append(f"{q:g}" if q else "—")
            data.append(row)
        # TOTAL row (cost per batch)
        total_row: List[Any] = ["TOTAL BATCH CFA", ""] + [f"{r.get('intrants_total_batch', 0):.0f}" for r in recipes]
        data.append(total_row)
        # PU cost (cost per unit)
        pu_row: List[Any] = ["Prix de revient (u)", ""] + [f"{r['cost_price']:.2f}" for r in recipes]
        data.append(pu_row)
        # Marge
        marge_row: List[Any] = ["Marge %", ""] + [f"{r['margin_pct']:.1f}%" for r in recipes]
        data.append(marge_row)
        # Prix vente
        pv_row: List[Any] = ["Prix public", ""] + [f"{r['public_price']:.2f}" for r in recipes]
        data.append(pv_row)

        t = Table(data, repeatRows=1)
        style = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, -4), (-1, -4), colors.HexColor("#fef3c7")),
            ("FONTNAME", (0, -4), (-1, -4), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#dcfce7")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ])
        t.setStyle(style)
        story.append(t)
    doc.build(story)
    return buf.getvalue()


def _render_single_recipe_pdf(r: Dict[str, Any], *, tenant_name: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    story: List[Any] = []
    story.append(Paragraph(f"<b>FICHE PRODUCTION — {r.get('name', '?')}</b>", styles["Title"]))
    subtitle_parts = []
    if r.get("variant_label"):
        subtitle_parts.append(r["variant_label"])
    subtitle_parts.append(f"{r.get('output_batch_units', 1)} {r.get('output_unit_label', 'unit')}/batch")
    story.append(Paragraph(f"<font size=10>{' · '.join(subtitle_parts)}</font>", styles["Normal"]))
    story.append(Paragraph(f"<font size=8 color='#666'>Tenant : {tenant_name} · Édité le {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}</font>", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    header = ["Intrant", "Catégorie", "Quantité", "Coût unit.", "Coût partiel"]
    data: List[List[Any]] = [header]
    # Iter43-fix24az-h — Cost model : each intrant's contribution =
    # unit_cost × dosage_number when dosage_number is set, else legacy qty×cost.
    dosage_number = r.get("dosage_number")
    try:
        dosage_number = float(dosage_number) if dosage_number is not None else None
    except (TypeError, ValueError):
        dosage_number = None
    use_dosage = dosage_number is not None and dosage_number > 0
    dosage_unit = r.get("dosage_unit") or "ml"
    for i in r.get("intrants") or []:
        uc = float(i.get("unit_cost_snapshot") or 0)
        if use_dosage:
            q = dosage_number
            q_display = f"{dosage_number:g} {dosage_unit}"
        else:
            q = float(i.get("quantity") or 0)
            q_display = f"{q:g} {i.get('unit_snapshot', '')}"
        data.append([
            i.get("name_snapshot", "?"),
            _cat_label(i.get("category_snapshot", "raw_material")),
            q_display,
            f"{uc:.4f}",
            f"{q * uc:.4f}",
        ])
    data.append(["TOTAL BATCH CFA", "", "", "", f"{r.get('intrants_total_batch', 0):.4f}"])
    t = Table(data, colWidths=[60 * mm, 30 * mm, 30 * mm, 25 * mm, 30 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fef3c7")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(t)
    story.append(Spacer(1, 8 * mm))

    # Pricing summary
    sum_data = [
        ["Prix de revient (par unité)", f"{r['cost_price']:.2f} CFA"],
        ["Marge bénéficiaire", f"{r['margin_pct']:.1f} %"],
        ["Prix public (par unité)", f"{r['public_price']:.2f} CFA"],
        ["Bénéfice par unité", f"{r['profit_per_unit']:.2f} CFA"],
    ]
    st = Table(sum_data, colWidths=[100 * mm, 60 * mm])
    st.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, -2), (-1, -2), colors.HexColor("#dcfce7")),
    ]))
    story.append(st)

    if r.get("notes"):
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(f"<b>Notes :</b> {r['notes']}", styles["Normal"]))
    doc.build(story)
    return buf.getvalue()


def _recipe_label(r: Dict[str, Any]) -> str:
    parts = [r.get("name", "?")]
    if r.get("variant_label"):
        parts.append(r["variant_label"])
    return " ".join(parts)


def _cat_label(cat: str) -> str:
    return {
        "raw_material": "Matière 1ère",
        "packaging": "Emballage",
        "water": "Eau",
        "electricity": "Électricité",
        "labor": "Main d'œuvre",
        "amortization": "Amortissement",
        "other": "Autre",
    }.get(cat, cat)


__all__ = ["attach_production_routes"]
