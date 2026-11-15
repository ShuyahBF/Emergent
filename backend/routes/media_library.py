"""S-iter39p — Media Library : admin can upload PDFs, videos and images
to enrich the « Brochures & Guides » portal page. Videos and images get
internal viewers (HTML5 video + zoomable img) and social share buttons.
PDFs reuse the existing internal viewer (S025 download-approval gate).

Storage : object_storage.save_and_log() (S3/local via existing helper).
Metadata : `media_library` collection (id, kind, title, description,
filename, content_type, size, url, created_at, created_by_id, public,
sort_order).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile

import object_storage as _stockage_objet   # lot 415 : envoi par morceaux des vidéos

logger = logging.getLogger("sawali.media_library")

# Allowed kinds with their MIME / extension whitelists
ALLOWED_MIME = {
    "pdf": {"application/pdf"},
    "video": {"video/mp4", "video/webm", "video/quicktime", "video/x-matroska"},
    "image": {"image/jpeg", "image/png", "image/webp", "image/gif"},
}

MAX_BYTES = {
    "pdf": 50 * 1024 * 1024,    # 50 MB
    "video": 300 * 1024 * 1024,  # 300 MB (lot 415 : envoyées vers R2 par morceaux, sans les charger en mémoire)
    "image": 15 * 1024 * 1024,   # 15 MB
}


# Lot 417 : espace total réservé aux vidéos (affiché « 120 Mo / 2 Go »). Modifiable par la variable d'environnement TV_VIDEOS_QUOTA_MO (en Mo).
def quota_videos_octets() -> int:
    try:
        mo = int(os.environ.get("TV_VIDEOS_QUOTA_MO") or 2048)
    except ValueError:
        mo = 2048
    return max(1, mo) * 1024 * 1024


async def espace_videos_utilise(db) -> int:
    """Octets occupés par les vidéos non supprimées (somme des tailles enregistrées)."""
    cur = db.media_library.aggregate([{"$match": {"kind": "video", "is_deleted": {"$ne": True}}}, {"$group": {"_id": None, "t": {"$sum": "$size"}}}])
    r = await cur.to_list(length=1)
    return int(r[0]["t"]) if r else 0


def libelle_taille(octets: int) -> str:
    """« 120 Mo », « 1,5 Go » : en Mo jusqu'à 1 Go, ensuite en Go (une décimale utile)."""
    mo = octets / (1024 * 1024)
    if mo < 1024:
        return f"{mo:.0f} Mo" if mo >= 10 or mo == int(mo) else f"{mo:.1f} Mo".replace(".", ",")
    go = mo / 1024
    return (f"{go:.0f}" if go == int(go) else f"{go:.1f}".replace(".", ",")) + " Go"


def _ext_from_mime_or_name(content_type: str, filename: str) -> str:
    name = (filename or "").lower()
    for e in (".mp4", ".webm", ".mov", ".mkv", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf"):
        if name.endswith(e):
            return e[1:]
    ct = (content_type or "").lower()
    mapping = {
        "application/pdf": "pdf",
        "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov", "video/x-matroska": "mkv",
        "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
    }
    return mapping.get(ct, "bin")


def _kind_from_mime(content_type: str) -> Optional[str]:
    ct = (content_type or "").lower()
    if ct == "application/pdf":
        return "pdf"
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("image/"):
        return "image"
    return None


def setup_media_library_routes(*, db, api, get_current_user, save_and_log):
    def _gate(user: dict):
        is_admin = user.get("role") in ("admin", "superviseur") \
            or user.get("tracked_role") in ("Administrateur", "Superviseur")
        if not is_admin:
            raise HTTPException(status_code=403, detail="Accès refusé")

    @api.get("/public/media-library", tags=["Public — Media Library"])
    async def list_public():
        """All `public=True` media, sorted by sort_order asc then created_at desc."""
        items = []
        try:
            cur = db.media_library.find(
                {"public": True, "is_deleted": {"$ne": True}},
                {"_id": 0, "id": 1, "kind": 1, "title": 1, "description": 1,
                 "filename": 1, "content_type": 1, "size": 1, "url": 1,
                 "thumbnail_url": 1, "sort_order": 1, "created_at": 1,
                 "tags": 1},
            ).sort([("sort_order", 1), ("created_at", -1)]).limit(200)
            items = await cur.to_list(length=200)
        except Exception:  # noqa: BLE001
            logger.exception("[media_library] public list failed")
        return {"items": items}

    @api.get("/admin/media-library", tags=["Admin — Media Library"])
    async def list_admin(user: dict = Depends(get_current_user)):
        _gate(user)
        cur = db.media_library.find(
            {"is_deleted": {"$ne": True}},
            {"_id": 0},
        ).sort([("sort_order", 1), ("created_at", -1)]).limit(500)
        items = await cur.to_list(length=500)
        return {"items": items}

    @api.post("/admin/media-library", tags=["Admin — Media Library"])
    async def upload(
        file: UploadFile = File(...),
        title: str = Form(...),
        description: str = Form(""),
        kind: Optional[str] = Form(None),
        public: bool = Form(True),
        sort_order: int = Form(0),
        tags: str = Form(""),
        user: dict = Depends(get_current_user),
    ):
        _gate(user)
        if not file.filename:
            raise HTTPException(status_code=400, detail="Fichier requis.")
        ct = (file.content_type or "").lower()
        detected_kind = kind or _kind_from_mime(ct)
        if detected_kind not in ALLOWED_MIME:
            raise HTTPException(status_code=400, detail=f"Type de fichier non supporté ({ct}). PDF, vidéo ou image attendu.")
        if ct and ct not in ALLOWED_MIME[detected_kind]:
            raise HTTPException(status_code=400, detail=f"MIME {ct} non autorisé pour {detected_kind}.")
        cap = MAX_BYTES[detected_kind]
        # Lot 415 : une vidéo (jusqu'à 300 Mo) n'est JAMAIS lue d'un bloc en mémoire (le serveur n'a que 512 Mo) : elle est envoyée vers R2 par morceaux.
        # Les autres fichiers (PDF, images : petits) gardent le chemin d'origine.
        par_morceaux = detected_kind == "video" and _stockage_objet.is_enabled()
        content = b""
        if par_morceaux:
            file.file.seek(0, 2); taille = file.file.tell(); file.file.seek(0)
        else:
            content = await file.read()
            taille = len(content)
        if taille == 0:
            raise HTTPException(status_code=400, detail="Fichier vide.")
        if taille > cap:
            raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (>{cap // (1024 * 1024)} Mo).")
        if detected_kind == "video":                                   # lot 417 : espace total des vidéos plafonné
            utilise, maximum = await espace_videos_utilise(db), quota_videos_octets()
            if utilise + taille > maximum:
                raise HTTPException(status_code=413, detail=f"Espace vidéos insuffisant : {libelle_taille(utilise)} / {libelle_taille(maximum)} utilisés, "
                                                            f"cette vidéo fait {libelle_taille(taille)}. Supprimez des vidéos pour libérer de la place.")
        title = (title or "").strip()[:200]
        if not title:
            raise HTTPException(status_code=400, detail="Titre requis.")
        description = (description or "").strip()[:1000]
        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()][:10]
        ext = _ext_from_mime_or_name(ct, file.filename)

        try:
            stored = await (_stockage_objet.save_fileobj_and_log(db, fileobj=file.file, size=taille, kind=f"media_library/{detected_kind}", tenant_id="sawali_global",
                                                                  ext=ext, content_type=ct or "application/octet-stream", original_filename=file.filename,
                                                                  user_id=user.get("id"), metadata={"title": title, "media_kind": detected_kind})
                            if par_morceaux else save_and_log(
                db,
                data=content,
                kind=f"media_library/{detected_kind}",
                tenant_id="sawali_global",
                ext=ext,
                content_type=ct or "application/octet-stream",
                original_filename=file.filename,
                user_id=user.get("id"),
                metadata={"title": title, "media_kind": detected_kind},
            ))
        except Exception as exc:  # noqa: BLE001
            logger.exception("[media_library] upload failed")
            raise HTTPException(status_code=500, detail=f"Échec stockage : {exc}") from exc

        import secrets
        rec_id = secrets.token_urlsafe(10)
        doc = {
            "id": rec_id,
            "kind": detected_kind,
            "title": title,
            "description": description,
            "filename": file.filename,
            "content_type": ct,
            "size": stored.get("size") or taille,
            "url": stored.get("url"),
            "storage_id": stored.get("id"),
            "storage_path": stored.get("path"),
            "thumbnail_url": None,
            "tags": tag_list,
            "public": bool(public),
            "sort_order": int(sort_order or 0),
            "is_deleted": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by_id": user.get("id"),
            "created_by_name": user.get("full_name") or user.get("email"),
        }
        await db.media_library.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @api.patch("/admin/media-library/{mid}", tags=["Admin — Media Library"])
    async def patch_media(mid: str, payload: dict = Body(...), user: dict = Depends(get_current_user)):
        _gate(user)
        allowed = {"title", "description", "public", "sort_order", "tags"}
        update = {}
        for k in allowed:
            if k in payload:
                v = payload[k]
                if k == "title":
                    v = (v or "").strip()[:200]
                    if not v:
                        raise HTTPException(status_code=400, detail="Titre requis.")
                elif k == "description":
                    v = (v or "").strip()[:1000]
                elif k == "sort_order":
                    v = int(v or 0)
                elif k == "public":
                    v = bool(v)
                elif k == "tags":
                    if isinstance(v, str):
                        v = [t.strip() for t in v.split(",") if t.strip()][:10]
                    elif isinstance(v, list):
                        v = [str(t).strip() for t in v if str(t).strip()][:10]
                    else:
                        v = []
                update[k] = v
        if not update:
            raise HTTPException(status_code=400, detail="Aucune modification fournie.")
        update["updated_at"] = datetime.now(timezone.utc).isoformat()
        r = await db.media_library.update_one({"id": mid, "is_deleted": {"$ne": True}}, {"$set": update})
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Média introuvable.")
        return {"ok": True, "updated": list(update.keys())}

    @api.delete("/admin/media-library/{mid}", tags=["Admin — Media Library"])
    async def delete_media(mid: str, user: dict = Depends(get_current_user)):
        _gate(user)
        r = await db.media_library.update_one(
            {"id": mid, "is_deleted": {"$ne": True}},
            {"$set": {"is_deleted": True, "deleted_at": datetime.now(timezone.utc).isoformat(),
                      "deleted_by_id": user.get("id")}},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Média introuvable.")
        return {"ok": True}

    return api
