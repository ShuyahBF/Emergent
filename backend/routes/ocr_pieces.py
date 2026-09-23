"""OCR sur Pièces — adaptateur Sawali du module commun `ocr_core`.

Page « OCR sur Pièces » (sidebar admin + pharmacies) : dépôt de pièces
(factures fournisseurs, bons de livraison, reçus…), analyse IA, et pour
l'admin/superviseur : choix du modèle, coût réel en FCFA, évaluation 1-5
étoiles + corrections, relance avec un autre modèle, tableau de bord.

Toute la logique d'OCR (modèles, préparation des pièces, appel IA, coût,
précision, statistiques) vit dans `backend/ocr_core/`, COPIE IDENTIQUE du
module commun maintenu dans le dépôt ShuyahBF/Claude (dossier ocr-core/).
Ce fichier-ci ne contient que ce qui est propre à Sawali :
  - qui a accès (admin/superviseur : tout ; pharmacies : leurs pièces) ;
  - le cloisonnement par tenant (client lié), résolu côté serveur depuis la
    session — jamais depuis un paramètre envoyé par le client
    (TECHNICAL_RULES.md, règle multi-tenant) ;
  - le stockage des fichiers (Emergent Object Storage, `object_storage.py`) ;
  - les collections Mongo : `ocr_pieces` (une pièce + sa synthèse la plus
    récente) et `ocr_piece_runs` (chaque analyse, avec coût et évaluation).
Les pharmacies ne voient jamais le modèle, le coût ni les évaluations.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

import ocr_core

logger = logging.getLogger("sawali.ocr_pieces")

# Consigne système propre à Sawali (le format de réponse est commun, dans ocr_core).
SYSTEM_PROMPT = ocr_core.build_system_prompt(
    organisation="SAWALI SMART SYSTEMS (plateforme de gestion pour pharmacies et officines, au Burkina Faso)",
    documents=(
        "facture fournisseur ou de grossiste-répartiteur, bon de livraison, avoir, reçu, "
        "relevé bancaire, facture de charges, pièce comptable de la pharmacie, etc."
    ),
)

PIECE_KINDS = ["facture", "bon_livraison", "avoir", "recu", "releve", "autre"]
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 Mo
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "webp", "txt", "csv"}

# Champs internes, jamais renvoyés à une pharmacie.
_INTERNAL_FIELDS = {
    "run_id", "model", "input_mode", "input_tokens", "output_tokens", "cost_usd", "cost_xof",
    "pages_analyzed", "duration_ms", "confidence", "uncertain_fields", "error", "requested_by",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_staff(user: dict) -> bool:
    """Admin/superviseur Sawali : accès complet (tous les tenants, outils OCR)."""
    return (user.get("role") or "") in ("admin", "superviseur")


def _is_pharmacy(user: dict) -> bool:
    """Pharmacie cliente : compte à rôle `pharmacien`, ou utilisateur suivi Pharmacien."""
    return (user.get("role") or "") == "pharmacien" or (user.get("tracked_role") or "") == "Pharmacien"


def _own_tenant_id(user: dict) -> str:
    """Tenant (client lié) d'une pharmacie, résolu depuis la session uniquement.

    Même ordre que `_resolve_client_lie` (routes/cashier.py) : parent_client_id,
    puis client_id ; à défaut, le compte pharmacie est lui-même le tenant."""
    for key in ("parent_client_id", "client_id"):
        ref = user.get(key)
        if ref and ref != user.get("id"):
            return ref
    return user["id"]


def _for_pharmacy(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in _INTERNAL_FIELDS}


def _ext_of(filename: str) -> str:
    return (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()


class ReviewPayload(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Note de 1 à 5 étoiles")
    comment: Optional[str] = Field(None, max_length=2000)
    corrected_fields: Dict[str, Any] = Field(default_factory=dict)


class ReanalyzePayload(BaseModel):
    model: str


def attach_ocr_pieces_routes(*, api, db, get_current_user):
    """Branche les routes /api/ocr-pieces (contrat commun décrit dans ocr-core/README.md)."""
    import object_storage as storage   # Emergent Object Storage (déjà utilisé par la plateforme)

    TAG = "Portail — OCR sur Pièces"

    # --- Dépendances d'accès -------------------------------------------------
    async def allowed_user(user: dict = Depends(get_current_user)) -> dict:
        if not (_is_staff(user) or _is_pharmacy(user)):
            raise HTTPException(status_code=403, detail="Accès réservé aux pharmacies et à l'administration")
        return user

    async def staff_user(user: dict = Depends(get_current_user)) -> dict:
        if not _is_staff(user):
            raise HTTPException(status_code=403, detail="Action réservée à l'administration Sawali")
        return user

    async def _get_piece(piece_id: str, user: dict) -> dict:
        piece = await db.ocr_pieces.find_one({"id": piece_id}, {"_id": 0})
        if not piece:
            raise HTTPException(status_code=404, detail="Pièce introuvable")
        if not _is_staff(user) and piece["tenant_id"] != _own_tenant_id(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        return piece

    # --- Analyse en tâche de fond ---------------------------------------------
    async def _analyze_and_store(piece_id: str, data: bytes, content_type: str, filename: str,
                                 tenant_id: str, model_id: Optional[str], requested_by: str) -> None:
        try:
            result = await ocr_core.analyze_document(
                data, content_type, filename, model_id,
                system_prompt=SYSTEM_PROMPT, default_model=ocr_core.default_model_id(),
            )
            run = {
                "id": str(uuid.uuid4()), "document_id": piece_id, "tenant_id": tenant_id,
                "summary": result.get("summary", ""),
                "extracted_fields": result.get("extracted_fields", {}),
                "document_type_guess": result.get("document_type"),
                "flags": result.get("flags", []),
                "confidence": result.get("confidence"),
                "uncertain_fields": result.get("uncertain_fields", []),
                "model": result.get("model"), "input_mode": result.get("input_mode"),
                "input_tokens": result.get("input_tokens", 0), "output_tokens": result.get("output_tokens", 0),
                "cost_usd": result.get("cost_usd", 0.0), "cost_xof": result.get("cost_xof", 0.0),
                "pages_analyzed": result.get("pages_analyzed", 0), "duration_ms": result.get("duration_ms", 0),
                "error": result.get("error"), "requested_by": requested_by,
                "review": None, "created_at": _now(),
            }
            await db.ocr_piece_runs.insert_one(run.copy())
            # Synthèse la plus récente recopiée sur la pièce (liste et vue pharmacie).
            latest = {k: run[k] for k in (
                "summary", "extracted_fields", "document_type_guess", "flags", "confidence",
                "uncertain_fields", "model", "cost_xof", "error",
            )}
            latest["run_id"] = run["id"]
            latest["analyzed_at"] = run["created_at"]
            latest["status"] = "erreur_analyse" if run["error"] else "analyse"
            await db.ocr_pieces.update_one({"id": piece_id}, {"$set": latest})
        except Exception:
            logger.exception("[ocr_pieces] analyse impossible pour %s", piece_id)
            await db.ocr_pieces.update_one({"id": piece_id}, {"$set": {"status": "erreur_analyse"}})

    # --- Référentiels (admin) ----------------------------------------------------
    @api.get("/ocr-pieces/ocr-models", tags=[TAG])
    async def ocr_models(user: dict = Depends(staff_user)):
        return ocr_core.public_catalog()

    @api.get("/ocr-pieces/tenants", tags=[TAG])
    async def ocr_tenants(user: dict = Depends(staff_user)):
        """Pharmacies pour le compte desquelles l'admin peut déposer une pièce."""
        rows = await db.users.find(
            {"role": {"$in": ["pharmacien", "client"]}, "tracked_role": {"$in": [None, ""]},
             "account_status": {"$ne": "suspended"}},
            {"_id": 0, "id": 1, "full_name": 1, "company": 1, "client_code": 1, "role": 1},
        ).sort("company", 1).to_list(2000)
        return rows

    @api.get("/ocr-pieces/ocr-stats", tags=[TAG])
    async def ocr_stats(period: str = "30d", user: dict = Depends(staff_user)):
        try:
            start = ocr_core.period_start(period)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        query: dict = {"created_at": {"$gte": start}} if start else {}
        rows = await db.ocr_piece_runs.find(query, {"_id": 0, "extracted_fields": 0, "summary": 0}).to_list(20000)
        return ocr_core.stats_by_model(rows, period)

    @api.post("/ocr-pieces/ocr-runs/{run_id}/review", tags=[TAG])
    async def review_run(run_id: str, payload: ReviewPayload, user: dict = Depends(staff_user)):
        run = await db.ocr_piece_runs.find_one({"id": run_id}, {"_id": 0})
        if not run:
            raise HTTPException(status_code=404, detail="Analyse introuvable")
        review = ocr_core.build_review(
            run.get("extracted_fields") or {}, payload.rating, payload.comment,
            payload.corrected_fields, user["id"], user.get("full_name"),
        )
        await db.ocr_piece_runs.update_one({"id": run_id}, {"$set": {"review": review}})
        return review

    # --- Pièces --------------------------------------------------------------
    @api.get("/ocr-pieces", tags=[TAG])
    async def list_pieces(tenant_id: Optional[str] = Query(None), user: dict = Depends(allowed_user)):
        query: dict = {}
        if _is_staff(user):
            if tenant_id:
                query["tenant_id"] = tenant_id
        else:
            query["tenant_id"] = _own_tenant_id(user)   # jamais le paramètre du client
        pieces = await db.ocr_pieces.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
        if not _is_staff(user):
            return [_for_pharmacy(p) for p in pieces]
        if pieces:
            runs = await db.ocr_piece_runs.find(
                {"document_id": {"$in": [p["id"] for p in pieces]}},
                {"_id": 0, "id": 1, "document_id": 1, "model": 1, "cost_xof": 1, "review": 1, "created_at": 1},
            ).sort("created_at", 1).to_list(5000)
            by_piece: Dict[str, List[dict]] = {}
            for r in runs:
                by_piece.setdefault(r["document_id"], []).append({
                    "id": r["id"], "model": r.get("model"), "cost_xof": r.get("cost_xof"),
                    "rating": (r.get("review") or {}).get("rating"),
                })
            for p in pieces:
                p["ocr_runs"] = by_piece.get(p["id"], [])
        return pieces

    @api.post("/ocr-pieces", tags=[TAG])
    async def upload_piece(
        file: UploadFile = File(...),
        kind: str = Form("facture"),
        tenant_id: Optional[str] = Form(None),
        model: Optional[str] = Form(None),
        user: dict = Depends(allowed_user),
    ):
        if kind not in PIECE_KINDS:
            raise HTTPException(status_code=400, detail=f"Type de pièce invalide (attendu : {PIECE_KINDS})")
        ext = _ext_of(file.filename or "")
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Extension non autorisée : .{ext}")
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 20 Mo)")

        if _is_staff(user):
            if not tenant_id:
                raise HTTPException(status_code=400, detail="Choisissez la pharmacie concernée")
            owner = await db.users.find_one({"id": tenant_id}, {"_id": 0, "id": 1, "company": 1, "full_name": 1, "client_code": 1})
            if not owner:
                raise HTTPException(status_code=404, detail="Pharmacie introuvable")
            if model and not ocr_core.get_model(model):
                raise HTTPException(status_code=400, detail=f"Modèle d'IA inconnu : {model}")
            model_id = model or ocr_core.default_model_id()
        else:
            tenant_id = _own_tenant_id(user)            # une pharmacie ne choisit ni tenant ni modèle
            owner = await db.users.find_one({"id": tenant_id}, {"_id": 0, "id": 1, "company": 1, "full_name": 1, "client_code": 1}) or {}
            model_id = ocr_core.default_model_id()

        content_type = storage.guess_content_type(ext, file.content_type or "application/octet-stream")
        stored = await storage.save_and_log(
            db, data=data, kind="ocr_pieces", tenant_id=tenant_id, ext=ext,
            content_type=content_type, original_filename=file.filename, user_id=user["id"],
        )
        piece = {
            "id": str(uuid.uuid4()), "tenant_id": tenant_id,
            "tenant_label": owner.get("company") or owner.get("full_name"),
            "client_code": owner.get("client_code"),
            "uploaded_by": user["id"], "kind": kind,
            "storage_path": stored["path"], "original_filename": file.filename,
            "content_type": content_type, "size": stored.get("size") or len(data),
            "status": "en_analyse", "created_at": _now(),
        }
        await db.ocr_pieces.insert_one(piece.copy())
        asyncio.create_task(_analyze_and_store(
            piece["id"], data, content_type, file.filename or "", tenant_id, model_id, user["id"],
        ))
        return piece

    @api.get("/ocr-pieces/{piece_id}", tags=[TAG])
    async def get_piece(piece_id: str, user: dict = Depends(allowed_user)):
        piece = await _get_piece(piece_id, user)
        if not _is_staff(user):
            return _for_pharmacy(piece)
        piece["ocr_runs"] = await db.ocr_piece_runs.find(
            {"document_id": piece_id}, {"_id": 0},
        ).sort("created_at", 1).to_list(200)
        return piece

    @api.post("/ocr-pieces/{piece_id}/reanalyze", tags=[TAG])
    async def reanalyze_piece(piece_id: str, payload: ReanalyzePayload, user: dict = Depends(staff_user)):
        piece = await _get_piece(piece_id, user)
        if not ocr_core.get_model(payload.model):
            raise HTTPException(status_code=400, detail=f"Modèle d'IA inconnu : {payload.model}")
        try:
            data, _ct = await storage.get_object(piece["storage_path"])
        except Exception as exc:  # noqa: BLE001
            logger.exception("[ocr_pieces] lecture impossible pour %s", piece_id)
            raise HTTPException(status_code=502, detail=f"Pièce introuvable dans le stockage : {exc}") from exc
        await db.ocr_pieces.update_one({"id": piece_id}, {"$set": {"status": "en_analyse"}})
        asyncio.create_task(_analyze_and_store(
            piece_id, data, piece.get("content_type") or "application/octet-stream",
            piece.get("original_filename") or "", piece["tenant_id"], payload.model, user["id"],
        ))
        return {"status": "en_analyse", "model": payload.model}

    @api.get("/ocr-pieces/{piece_id}/download", tags=[TAG])
    async def download_piece(piece_id: str, user: dict = Depends(allowed_user)):
        piece = await _get_piece(piece_id, user)
        data, ct = await storage.get_object(piece["storage_path"])
        filename = (piece.get("original_filename") or "piece").replace('"', "")
        return Response(content=data, media_type=ct or piece.get("content_type") or "application/octet-stream",
                        headers={"Content-Disposition": f'inline; filename="{filename}"'})

    @api.delete("/ocr-pieces/{piece_id}", tags=[TAG])
    async def delete_piece(piece_id: str, user: dict = Depends(allowed_user)):
        piece = await _get_piece(piece_id, user)   # admin, ou pharmacie propriétaire
        # Le stockage n'a pas d'API de suppression : on marque le fichier supprimé.
        await storage.soft_delete(db, piece["storage_path"])
        await db.ocr_pieces.delete_one({"id": piece_id})
        await db.ocr_piece_runs.delete_many({"document_id": piece_id})
        return {"ok": True, "id": piece_id}
