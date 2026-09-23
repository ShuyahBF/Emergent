"""Lot "Gestion Stocks" (2026-09) — espace documentaire des Pharmaciens
suivis (tracked_role == "Pharmacien"), nouveau lien de sidebar.

Deux blocs prévus au schéma fourni par l'utilisateur :
  1. "Explorateur BD MongoDB Atlas" (inventaires/base produits/historique
     ventes, importés par un outil externe — partie technique à discuter
     plus tard). PAS implémenté dans ce module — le frontend affiche un
     bloc "Bientôt disponible" en attendant.
  2. "Explorateur Stockage R2" (PDFs, Excel, Word, Images — inventaires,
     contrôle d'analyse qualité, etc). C'est l'objet de ce module.

Organisation des documents dans R2 (voir r2_stocks_client.py) : un préfixe
par client/tenant (`client_code`, ex "PMT"), avec des sous-dossiers fixes
communs à tous les clients (DEFAULT_FOLDERS ci-dessous) — décision
explicite de l'utilisateur ("par Code du Client/Tenant... plusieurs
sous-dossiers: Inventaires, Rapports, Analyses, etc").

Cloisonnement : un pharmacien suivi ne voit jamais que son propre
`client_code` (résolu côté serveur depuis sa session, jamais depuis un
paramètre client) ; l'admin peut choisir n'importe quel client_code.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, File, HTTPException, Query, UploadFile

logger = logging.getLogger("sawali.gestion_stocks")

# Sous-dossiers fixes, identiques pour chaque client — correspond aux 6
# dossiers du schéma fourni par l'utilisateur.
DEFAULT_FOLDERS: List[str] = [
    "Inventaires",
    "Rapports",
    "Analyses",
    "Controle qualite",
    "Factures",
    "Autres",
]

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 Mo par fichier


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _can_access_own_stocks(user: dict) -> bool:
    """Un pharmacien suivi voit son propre espace. Admin/superviseur voient
    tout (utile pour vérifier/dépanner un client)."""
    if (user.get("role") or "") in ("admin", "superviseur"):
        return True
    return (user.get("tracked_role") or "") == "Pharmacien"


async def _resolve_own_client_code(db, user: dict) -> Optional[str]:
    """Résout le `client_code` du tenant du pharmacien suivi courant.

    Même ordre de résolution que `_resolve_client_lie` (routes/cashier.py) :
    parent_client_id puis client_id pointent vers le tenant canonique
    (db.users). On ne retombe jamais sur `user` lui-même comme tenant ici —
    un compte suivi n'a pas vocation à porter son propre client_code.
    """
    for key in ("parent_client_id", "client_id"):
        ref_id = user.get(key)
        if ref_id and ref_id != user.get("id"):
            doc = await db.users.find_one({"id": ref_id}, {"_id": 0, "client_code": 1})
            if doc:
                code = (doc.get("client_code") or "").strip().upper()
                return code or None
    return None


def _safe_filename(name: str) -> str:
    base = os.path.basename((name or "").strip()) or "fichier"
    return "".join(c for c in base if c.isalnum() or c in (" ", ".", "-", "_")).strip() or "fichier"


def attach_gestion_stocks_routes(*, api, db, get_current_user, get_current_admin):

    @api.get("/gestion-stocks/context", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_context(user: dict = Depends(get_current_user)):
        """Renvoie le client_code résolu + la liste des dossiers — le
        frontend s'en sert pour savoir quoi afficher avant tout listing."""
        if not _can_access_own_stocks(user):
            raise HTTPException(status_code=403, detail="Accès réservé aux comptes Pharmacien suivis (et admin/superviseur).")
        from r2_stocks_client import is_configured
        client_code = None
        if (user.get("role") or "") in ("admin", "superviseur"):
            client_code = None  # l'admin choisit un client_code explicitement (voir endpoints /admin/*)
        else:
            client_code = await _resolve_own_client_code(db, user)
        return {
            "client_code": client_code,
            "folders": DEFAULT_FOLDERS,
            "r2_configured": is_configured(),
            "is_admin": (user.get("role") or "") in ("admin", "superviseur"),
        }

    @api.get("/gestion-stocks/folders/{folder}/files", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_list_files(
        folder: str,
        client_code: Optional[str] = Query(None, description="Admin uniquement — ignoré pour un pharmacien suivi."),
        user: dict = Depends(get_current_user),
    ):
        if not _can_access_own_stocks(user):
            raise HTTPException(status_code=403, detail="Accès réservé aux comptes Pharmacien suivis (et admin/superviseur).")
        if folder not in DEFAULT_FOLDERS:
            raise HTTPException(status_code=404, detail="Dossier inconnu.")
        is_admin = (user.get("role") or "") in ("admin", "superviseur")
        code = (client_code or "").strip().upper() if is_admin else await _resolve_own_client_code(db, user)
        if not code:
            raise HTTPException(status_code=409, detail="Aucun code client (client_code) configuré pour ce tenant — voir AdminClients.")
        from r2_stocks_client import is_configured, list_objects
        import asyncio
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré (variables R2_STOCKS_* manquantes).")
        prefix = f"{code}/{folder}/"
        try:
            objects = await asyncio.to_thread(list_objects, prefix)
        except Exception:
            logger.exception("[gestion_stocks] list_objects failed prefix=%s", prefix)
            raise HTTPException(status_code=502, detail="Erreur de lecture du stockage R2.")
        files = [
            {
                "key": o["key"],
                "name": o["key"][len(prefix):],
                "size": o["size"],
                "last_modified": o["last_modified"],
            }
            for o in objects
        ]
        files.sort(key=lambda f: f["last_modified"], reverse=True)
        return {"client_code": code, "folder": folder, "files": files}

    @api.get("/gestion-stocks/files/view-url", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_view_url(
        key: str = Query(...),
        user: dict = Depends(get_current_user),
    ):
        """URL de lecture temporaire (5 min) pour un fichier — le frontend
        l'ouvre dans un nouvel onglet au double-clic."""
        if not _can_access_own_stocks(user):
            raise HTTPException(status_code=403, detail="Accès réservé aux comptes Pharmacien suivis (et admin/superviseur).")
        is_admin = (user.get("role") or "") in ("admin", "superviseur")
        if not is_admin:
            code = await _resolve_own_client_code(db, user)
            if not code or not key.startswith(f"{code}/"):
                # Un pharmacien suivi ne peut jamais obtenir d'URL en dehors
                # de son propre préfixe, même en devinant une clé.
                raise HTTPException(status_code=403, detail="Ce document n'appartient pas à votre espace.")
        from r2_stocks_client import is_configured, get_presigned_url
        import asyncio
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré.")
        try:
            url = await asyncio.to_thread(get_presigned_url, key, 300)
        except Exception:
            logger.exception("[gestion_stocks] get_presigned_url failed key=%s", key)
            raise HTTPException(status_code=502, detail="Erreur de génération du lien de lecture.")
        return {"url": url, "expires_in": 300}

    # ------------------------------------------------------------------
    # Admin — alimentation des dossiers (l'outil externe n'a pas encore été
    # discuté ; en attendant, l'admin peut déposer des documents à la main).
    # ------------------------------------------------------------------
    @api.get("/admin/gestion-stocks/clients", tags=["Admin — Gestion Stocks"])
    async def admin_gestion_stocks_clients(_: dict = Depends(get_current_admin)):
        cursor = db.users.find(
            {"client_code": {"$exists": True, "$nin": [None, ""]}},
            {"_id": 0, "id": 1, "client_code": 1, "company": 1, "full_name": 1},
        )
        items = await cursor.to_list(length=500)
        return [
            {
                "client_code": (it.get("client_code") or "").upper(),
                "label": it.get("company") or it.get("full_name") or it.get("client_code"),
            }
            for it in items
        ]

    @api.post("/admin/gestion-stocks/{client_code}/{folder}/upload", tags=["Admin — Gestion Stocks"])
    async def admin_gestion_stocks_upload(
        client_code: str,
        folder: str,
        file: UploadFile = File(...),
        _: dict = Depends(get_current_admin),
    ):
        if folder not in DEFAULT_FOLDERS:
            raise HTTPException(status_code=404, detail="Dossier inconnu.")
        code = (client_code or "").strip().upper()
        if not code:
            raise HTTPException(status_code=400, detail="client_code manquant.")
        from r2_stocks_client import is_configured, put_bytes
        import asyncio
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré.")
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {MAX_UPLOAD_BYTES // (1024*1024)} Mo).")
        filename = _safe_filename(file.filename or "fichier")
        key = f"{code}/{folder}/{filename}"
        try:
            await asyncio.to_thread(put_bytes, key, data, file.content_type or "application/octet-stream")
        except Exception:
            logger.exception("[gestion_stocks] upload failed key=%s", key)
            raise HTTPException(status_code=502, detail="Échec de l'envoi vers R2.")
        return {"ok": True, "key": key, "size": len(data)}

    @api.delete("/admin/gestion-stocks/file", tags=["Admin — Gestion Stocks"])
    async def admin_gestion_stocks_delete(
        key: str = Query(...),
        _: dict = Depends(get_current_admin),
    ):
        from r2_stocks_client import is_configured, delete_object
        import asyncio
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré.")
        try:
            await asyncio.to_thread(delete_object, key)
        except Exception:
            logger.exception("[gestion_stocks] delete failed key=%s", key)
            raise HTTPException(status_code=502, detail="Échec de la suppression.")
        return {"ok": True}

    logger.info("[gestion_stocks] routes mounted under /api/gestion-stocks and /api/admin/gestion-stocks")


__all__ = ["attach_gestion_stocks_routes", "DEFAULT_FOLDERS"]
