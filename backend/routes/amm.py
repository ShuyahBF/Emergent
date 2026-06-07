"""Iter41 Phase 2 (2026-02) — Table AMM (Autorisation de Mise sur le Marché)
éditable par les utilisateurs disposant du rôle `regulateur` (ou admin/superviseur).

Iter42b (2026-02) — Ajout :
  - `internal_no` autogénéré (clé interne stable, jamais NULL)
  - `amm_number` et `cip1` désormais OPTIONNELS (peuvent être NULL)
  - Endpoint `POST /api/amm/import-csv` (multipart) — refuse globalement si conflits

Schéma (collection `amm_numbers`) :
  id, internal_no (auto, unique), vidal_product_id, product_name,
  amm_number (optionnel, unique si présent), laboratory,
  galenic_form, atc_class, status (active|withdrawn|suspended),
  granted_at, expires_at, notes, source (vidal_auto | manual | csv_import),
  created_by, created_at, updated_by, updated_at, tenant_type,
  cip1..cip5 (optionnels)
"""
from __future__ import annotations

import csv
import io
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

logger = logging.getLogger("sawali.amm")

AMM_ALLOWED_ROLES = ("admin", "superviseur", "regulateur")
# Iter42b — `editeur_vidal` peut LIRE (rechercher/filtrer/trier) mais pas écrire
AMM_READONLY_ROLES = ("editeur_vidal",)
AMM_STATUSES = ("active", "withdrawn", "suspended")


class AmmCreatePayload(BaseModel):
    vidal_product_id: Optional[int] = None
    product_name: str
    # Iter42b — amm_number devient OPTIONNEL (peut être NULL)
    amm_number: Optional[str] = None
    # Iter42d — code pays ISO2 (BF, CI, FR…) ; si absent, on prend
    # settings.amm_default_country au moment du POST/import.
    country_code: Optional[str] = None
    laboratory: Optional[str] = None
    galenic_form: Optional[str] = None
    atc_class: Optional[str] = None
    status: Optional[str] = "active"
    granted_at: Optional[str] = None  # ISO date
    expires_at: Optional[str] = None
    notes: Optional[str] = None
    # Iter41 Phase 3 — CIPs (jusqu'à 5 codes selon laboratoire/distributeur)
    cip1: Optional[str] = None
    cip2: Optional[str] = None
    cip3: Optional[str] = None
    cip4: Optional[str] = None
    cip5: Optional[str] = None


class AmmUpdatePayload(BaseModel):
    vidal_product_id: Optional[int] = None
    product_name: Optional[str] = None
    amm_number: Optional[str] = None
    country_code: Optional[str] = None
    laboratory: Optional[str] = None
    galenic_form: Optional[str] = None
    atc_class: Optional[str] = None
    status: Optional[str] = None
    granted_at: Optional[str] = None
    expires_at: Optional[str] = None
    notes: Optional[str] = None
    cip1: Optional[str] = None
    cip2: Optional[str] = None
    cip3: Optional[str] = None
    cip4: Optional[str] = None
    cip5: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_internal_no() -> str:
    """Auto-generated internal number for AMM rows (jamais affiché à l'utilisateur final
    mais sert d'identifiant stable côté DB). Format INT-XXXXXXXX (8 hex)."""
    return f"INT-{uuid.uuid4().hex[:8].upper()}"


def _can_write(user: Dict[str, Any]) -> bool:
    return (user.get("role") or "") in AMM_ALLOWED_ROLES


def _can_read(user: Dict[str, Any]) -> bool:
    # Tous les utilisateurs authentifiés peuvent lire la table (incl. editeur_vidal).
    return True


def attach_amm_routes(*, api, db, get_current_user):
    """Mount AMM CRUD endpoints under /api/amm/*."""

    @api.get("/amm", tags=["AMM"])
    async def list_amm(
        q: Optional[str] = Query(None, description="Recherche par nom ou numéro AMM"),
        status: Optional[str] = Query(None, regex="^(active|withdrawn|suspended)$"),
        limit: int = Query(100, ge=1, le=500),
        user: dict = Depends(get_current_user),
    ):
        if not _can_read(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status
        if q:
            query["$or"] = [
                {"product_name": {"$regex": q, "$options": "i"}},
                {"amm_number": {"$regex": q, "$options": "i"}},
                {"laboratory": {"$regex": q, "$options": "i"}},
            ]
        cursor = db.amm_numbers.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
        items = await cursor.to_list(limit)
        return {"items": items, "count": len(items)}

    @api.get("/amm/by-product/{vidal_product_id}", tags=["AMM"])
    async def get_amm_by_product(vidal_product_id: int, user: dict = Depends(get_current_user)):
        if not _can_read(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        doc = await db.amm_numbers.find_one(
            {"vidal_product_id": vidal_product_id},
            {"_id": 0},
        )
        if not doc:
            return {"found": False}
        return {"found": True, "amm": doc}

    @api.post("/amm", tags=["AMM"])
    async def create_amm(payload: AmmCreatePayload = Body(...), user: dict = Depends(get_current_user)):
        if not _can_write(user):
            raise HTTPException(status_code=403, detail="Réservé aux admins, superviseurs et régulateurs")
        # Iter42b — amm_number est optionnel. Vérifie unicité si présent.
        amm_clean = (payload.amm_number or "").strip() or None
        cip1_clean = (payload.cip1 or "").strip() or None
        if amm_clean:
            existing = await db.amm_numbers.find_one({"amm_number": amm_clean})
            if existing:
                raise HTTPException(status_code=409, detail=f"Numéro AMM {amm_clean} déjà enregistré")
        if cip1_clean:
            existing_cip = await db.amm_numbers.find_one({"cip1": cip1_clean})
            if existing_cip:
                raise HTTPException(status_code=409, detail=f"CIP1 {cip1_clean} déjà enregistré")
        status = (payload.status or "active").lower()
        if status not in AMM_STATUSES:
            status = "active"
        # Iter42d — country_code par défaut depuis settings.amm_default_country
        country_code = (payload.country_code or "").strip().upper() or None
        if not country_code:
            s = await db.settings.find_one({"_id": "global"}) or {}
            country_code = (s.get("amm_default_country") or "").strip().upper() or None
        doc = {
            "id": secrets.token_urlsafe(12),
            "internal_no": _gen_internal_no(),
            "vidal_product_id": payload.vidal_product_id,
            "product_name": payload.product_name.strip(),
            "amm_number": amm_clean,
            "country_code": country_code,
            "laboratory": (payload.laboratory or "").strip() or None,
            "galenic_form": (payload.galenic_form or "").strip() or None,
            "atc_class": (payload.atc_class or "").strip() or None,
            "status": status,
            "granted_at": payload.granted_at,
            "expires_at": payload.expires_at,
            "notes": (payload.notes or "").strip() or None,
            "cip1": cip1_clean,
            "cip2": (payload.cip2 or "").strip() or None,
            "cip3": (payload.cip3 or "").strip() or None,
            "cip4": (payload.cip4 or "").strip() or None,
            "cip5": (payload.cip5 or "").strip() or None,
            "source": "manual",
            "created_by": user.get("id"),
            "created_by_email": user.get("email"),
            "created_at": _now_iso(),
            "updated_by": None,
            "updated_by_email": None,
            "updated_at": None,
        }
        await db.amm_numbers.insert_one(doc)
        doc.pop("_id", None)
        return {"ok": True, "amm": doc}

    @api.post("/amm/import-csv", tags=["AMM"])
    async def import_csv(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
        """Import en masse depuis un CSV.

        Colonnes attendues (insensible à la casse, accents ignorés) :
            Nom du produit, AMM, CIP1, date expiration, Laboratoire, Note

        Règle utilisateur :
          - Doublons (AMM ou CIP1 déjà en DB OU dans le fichier) → refuse TOUT
            l'import et liste les conflits.
          - AMM et CIP1 peuvent être NULL — un internal_no est auto-généré.
        """
        if not _can_write(user):
            raise HTTPException(status_code=403, detail="Réservé aux admins, superviseurs et régulateurs")
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Le fichier doit être un .csv")
        raw = await file.read()
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 5 Mo)")
        # Best-effort decoding: UTF-8 then latin-1
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except UnicodeDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"Encodage non supporté : {exc}") from exc

        # Sniff dialect (comma vs semicolon)
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        except csv.Error:
            dialect = csv.excel  # default to comma

        reader = csv.reader(io.StringIO(text), dialect)
        rows = list(reader)
        if len(rows) < 2:
            raise HTTPException(status_code=400, detail="Le fichier CSV est vide (aucune ligne de données)")

        # Header normalization
        def _norm(s: str) -> str:
            import unicodedata
            s = unicodedata.normalize("NFD", s or "")
            s = "".join(c for c in s if unicodedata.category(c) != "Mn")
            return s.strip().lower()

        # Mapping header -> field
        HEADER_MAP = {
            "nom du produit": "product_name", "produit": "product_name", "nom": "product_name", "product_name": "product_name",
            "amm": "amm_number", "numero amm": "amm_number", "amm_number": "amm_number",
            "cip1": "cip1", "cip": "cip1", "code cip": "cip1",
            "date expiration": "expires_at", "expiration": "expires_at", "date_expiration": "expires_at", "expires_at": "expires_at",
            "laboratoire": "laboratory", "labo": "laboratory", "laboratory": "laboratory",
            "note": "notes", "notes": "notes", "remarque": "notes",
        }
        header = [_norm(h) for h in rows[0]]
        col_map: Dict[int, str] = {}
        for idx, h in enumerate(header):
            if h in HEADER_MAP:
                col_map[idx] = HEADER_MAP[h]
        if "product_name" not in col_map.values():
            raise HTTPException(
                status_code=400,
                detail=f"Colonne « Nom du produit » introuvable. En-têtes détectés : {header}",
            )

        # Parse data rows
        parsed: List[Dict[str, Any]] = []
        for line_no, raw_row in enumerate(rows[1:], start=2):
            if not any((c or "").strip() for c in raw_row):
                continue  # skip empty lines
            data = {"_line": line_no}
            for idx, val in enumerate(raw_row):
                field = col_map.get(idx)
                if field:
                    data[field] = (val or "").strip()
            if not (data.get("product_name") or "").strip():
                continue  # skip rows without product name (silently)
            # Normalize NULLs
            for k in ("amm_number", "cip1", "expires_at", "laboratory", "notes"):
                if not (data.get(k) or "").strip():
                    data[k] = None
            parsed.append(data)

        if not parsed:
            raise HTTPException(status_code=400, detail="Aucune ligne valide (vérifiez la colonne « Nom du produit »)")

        # Conflict detection (DB + intra-file)
        amm_values = [p["amm_number"] for p in parsed if p.get("amm_number")]
        cip_values = [p["cip1"] for p in parsed if p.get("cip1")]
        # Duplicates dans le fichier lui-même
        intra_conflicts: List[Dict[str, Any]] = []
        seen_amm: Dict[str, int] = {}
        seen_cip: Dict[str, int] = {}
        for p in parsed:
            a = p.get("amm_number")
            c = p.get("cip1")
            if a:
                if a in seen_amm:
                    intra_conflicts.append({"line": p["_line"], "field": "amm_number", "value": a,
                                            "conflict_with": f"ligne {seen_amm[a]} du même fichier"})
                else:
                    seen_amm[a] = p["_line"]
            if c:
                if c in seen_cip:
                    intra_conflicts.append({"line": p["_line"], "field": "cip1", "value": c,
                                            "conflict_with": f"ligne {seen_cip[c]} du même fichier"})
                else:
                    seen_cip[c] = p["_line"]

        # Conflits DB
        db_conflicts: List[Dict[str, Any]] = []
        if amm_values:
            cursor = db.amm_numbers.find({"amm_number": {"$in": amm_values}}, {"_id": 0, "amm_number": 1, "product_name": 1})
            async for d in cursor:
                # find the line(s)
                amm = d.get("amm_number")
                for p in parsed:
                    if p.get("amm_number") == amm:
                        db_conflicts.append({"line": p["_line"], "field": "amm_number", "value": amm,
                                             "conflict_with": f"AMM existante en base : {d.get('product_name', '?')}"})
        if cip_values:
            cursor = db.amm_numbers.find({"cip1": {"$in": cip_values}}, {"_id": 0, "cip1": 1, "product_name": 1})
            async for d in cursor:
                cip = d.get("cip1")
                for p in parsed:
                    if p.get("cip1") == cip:
                        db_conflicts.append({"line": p["_line"], "field": "cip1", "value": cip,
                                             "conflict_with": f"CIP1 existant en base : {d.get('product_name', '?')}"})

        if intra_conflicts or db_conflicts:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Import refusé : conflits détectés. Aucune ligne n'a été importée.",
                    "intra_file_conflicts": intra_conflicts,
                    "database_conflicts": db_conflicts,
                    "rows_parsed": len(parsed),
                },
            )

        # Insertion bulk
        now_iso = _now_iso()
        # Iter42d — country_code par défaut depuis settings au moment de l'import
        s = await db.settings.find_one({"_id": "global"}) or {}
        default_country = (s.get("amm_default_country") or "").strip().upper() or None
        docs = []
        for p in parsed:
            docs.append({
                "id": secrets.token_urlsafe(12),
                "internal_no": _gen_internal_no(),
                "vidal_product_id": None,
                "product_name": p["product_name"].strip(),
                "amm_number": p.get("amm_number"),
                "country_code": default_country,
                "laboratory": p.get("laboratory"),
                "galenic_form": None,
                "atc_class": None,
                "status": "active",
                "granted_at": None,
                "expires_at": p.get("expires_at"),
                "notes": p.get("notes"),
                "cip1": p.get("cip1"),
                "cip2": None, "cip3": None, "cip4": None, "cip5": None,
                "source": "csv_import",
                "created_by": user.get("id"),
                "created_by_email": user.get("email"),
                "created_at": now_iso,
                "updated_by": None,
                "updated_by_email": None,
                "updated_at": None,
            })
        if docs:
            await db.amm_numbers.insert_many(docs)
        return {
            "ok": True,
            "imported": len(docs),
            "skipped_empty": (len(rows) - 1) - len(parsed),
            "filename": file.filename,
        }

    @api.put("/amm/{amm_id}", tags=["AMM"])
    async def update_amm(amm_id: str, payload: AmmUpdatePayload = Body(...), user: dict = Depends(get_current_user)):
        if not _can_write(user):
            raise HTTPException(status_code=403, detail="Réservé aux admins, superviseurs et régulateurs")
        existing = await db.amm_numbers.find_one({"id": amm_id})
        if not existing:
            raise HTTPException(status_code=404, detail="AMM introuvable")
        update = payload.model_dump(exclude_none=True)
        if "amm_number" in update:
            update["amm_number"] = update["amm_number"].strip()
            if update["amm_number"] != existing["amm_number"]:
                dup = await db.amm_numbers.find_one({"amm_number": update["amm_number"], "id": {"$ne": amm_id}})
                if dup:
                    raise HTTPException(status_code=409, detail="Ce numéro AMM existe déjà")
        # Iter42d — normalisation country_code (ISO 2 lettres MAJUSCULES)
        if "country_code" in update:
            update["country_code"] = (update["country_code"] or "").strip().upper() or None
        if "status" in update:
            s = update["status"].lower()
            if s not in AMM_STATUSES:
                raise HTTPException(status_code=400, detail=f"status doit être un de {AMM_STATUSES}")
            update["status"] = s
        update["updated_by"] = user.get("id")
        update["updated_by_email"] = user.get("email")
        update["updated_at"] = _now_iso()
        await db.amm_numbers.update_one({"id": amm_id}, {"$set": update})
        merged = {**existing, **update}
        merged.pop("_id", None)
        return {"ok": True, "amm": merged}

    @api.delete("/amm/{amm_id}", tags=["AMM"])
    async def delete_amm(amm_id: str, user: dict = Depends(get_current_user)):
        if not _can_write(user):
            raise HTTPException(status_code=403, detail="Réservé aux admins, superviseurs et régulateurs")
        r = await db.amm_numbers.delete_one({"id": amm_id})
        if r.deleted_count == 0:
            raise HTTPException(status_code=404, detail="AMM introuvable")
        return {"ok": True}

    logger.info("[amm] routes mounted under /api/amm/*")


async def lookup_amm_for_product(db, vidal_product_id: Optional[int], product_name: Optional[str]) -> Optional[Dict[str, Any]]:
    """Helper used by the VIDAL fiche endpoint and WhatsApp `!vidal fiche/amm`
    commands to enrich the response with the locally-edited AMM record.
    """
    if vidal_product_id:
        doc = await db.amm_numbers.find_one({"vidal_product_id": vidal_product_id}, {"_id": 0})
        if doc:
            return doc
    if product_name:
        doc = await db.amm_numbers.find_one(
            {"product_name": {"$regex": f"^{product_name.strip()}$", "$options": "i"}},
            {"_id": 0},
        )
        if doc:
            return doc
    return None
