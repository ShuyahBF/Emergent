# server_parts/p06_medias_ia_version_cms.py — Médiathèque, transcription audio, synthèse IA, version de la plateforme, contenus du site (CMS).
# Morceau de l'ancien server.py (lignes 9207 à 10120), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ============================================================
# Media library (shared per-client bank for WhatsApp templates)
# ============================================================
@api.get("/me/media-library", tags=["Portail Client"])
async def me_media_library(
    request: Request,
    source: Optional[str] = None,  # Iter35n — filter by `source` (e.g. "whatsapp_inbound")
    user: dict = Depends(get_current_user),
):
    """Tous les médias téléversés par les utilisateurs du même client. Banque partagée.

    Iter35n — `source` query filter narrows the listing (typically
    `?source=whatsapp_inbound` to isolate WhatsApp re-saved media).

    Iter37g — Rebuild `public_url` from the CURRENT request host so that links
    stored at upload time on preview keep working from production (and vice
    versa). Falls back to the stored absolute URL if no relative `url` is
    available.
    """
    client_scope = user.get("client_id") or user.get("id")
    q: Dict[str, Any] = {"client_id": client_scope}
    if source:
        q["source"] = source
    items = await db.media_library.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    # Iter37g — Rewrite public_url with the current host
    base = _public_base_url(request).rstrip("/")
    for it in items:
        # Pull the file row to recover the relative path
        rel = None
        if it.get("file_id"):
            file_doc = await db.files.find_one({"id": it["file_id"]}, {"_id": 0, "url": 1})
            if file_doc and file_doc.get("url"):
                rel = file_doc["url"]
        if not rel:
            # Last-ditch: try to extract /api/files/... from the stored absolute URL
            stored = it.get("public_url") or ""
            idx = stored.find("/api/files/")
            if idx >= 0:
                rel = stored[idx:]
        if rel:
            it["public_url"] = f"{base}{rel}"
    return items


@api.post("/me/media-library", tags=["Portail Client"])
async def me_media_library_create(
    request: Request,
    file: UploadFile = File(...),
    label: str = Form(""),
    target_client_id: str = Form(""),  # Admin-only: attach the upload to a specific client's library
    user: dict = Depends(get_current_user),
):
    """Upload + register a media in the shared client library, returns a stable public URL
    (with the file extension, accepted by Meta WhatsApp Cloud API as a header media)."""
    if not (_is_tracked_user(user) or _is_elevated_creator(user) or user.get("role") in ("client", "admin")):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
    # Resolve client_id: admin can override via target_client_id, others always use their own
    client_scope = user.get("client_id") or user.get("id")
    if (target_client_id or "").strip() and user.get("role") == "admin":
        client_scope = target_client_id.strip()
    file_id = _uuid()
    suffix = Path(file.filename or "").suffix.lower()
    safe_name = f"{file_id}{suffix}"
    ext = (suffix.lstrip(".") or "").lower()
    public_path = f"/api/files/{file_id}{('.' + ext) if ext else ''}"
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    kind = "image" if content_type.startswith("image") else ("video" if content_type.startswith("video") else "document")
    public_url = f"{(_public_base_url(request) or str(request.base_url).rstrip('/'))}{public_path}"
    # 2026-02 fork iter108 — Deploy-safe upload helper (storage-first, local cache).
    from storage import asave_upload_and_cache  # lot 26 : dans un thread, sans figer le serveur
    data = file.file.read()
    size = len(data)
    target, storage_path, storage_error = await asave_upload_and_cache(
        upload_dir=UPLOAD_DIR, filename=safe_name, data=data, content_type=content_type,
    )
    if storage_error:
        logger.warning("[media_library_upload] storage mirror failed: %s", storage_error)
    # Register in the regular files collection (so /api/files/{id} can serve it)
    file_doc = {
        "id": file_id, "filename": file.filename, "stored_name": safe_name,
        "extension": ext, "content_type": content_type, "size": size,
        "url": public_path, "public_url": public_url, "uploaded_at": _now(),
        "uploaded_by_id": user.get("id"), "uploaded_by_email": user.get("email"),
        "uploaded_from_ip": _client_ip_from_request(request),
        "storage_path": storage_path, "storage_error": storage_error,
    }
    await db.files.insert_one(file_doc)
    # Register in the shared client library
    media = {
        "id": _uuid(),
        "file_id": file_id,
        "client_id": client_scope,
        "uploaded_by_id": user.get("id"),
        "uploaded_by_label": user.get("full_name") or user.get("email"),
        "label": (label or file.filename or "")[:200],
        "filename": file.filename,
        "kind": kind,
        "content_type": content_type,
        "extension": ext,
        "size": size,
        "public_url": public_url,
        "created_at": _now(),
    }
    await db.media_library.insert_one(media.copy())
    media.pop("_id", None)
    return media


@api.delete("/me/media-library/{media_id}", tags=["Portail Client"])
async def me_media_library_delete(media_id: str, user: dict = Depends(get_current_user)):
    client_scope = user.get("client_id") or user.get("id")
    media = await db.media_library.find_one({"id": media_id, "client_id": client_scope}, {"_id": 0})
    if not media:
        raise HTTPException(status_code=404, detail="Média introuvable")
    await db.media_library.delete_one({"id": media_id})
    # Best-effort: keep the underlying file in case other places reference it
    return {"ok": True}


# Iter35n — Cleanup unused WhatsApp media library entries. "Unused" means the
# underlying file_id is not referenced by any rapport/suivi/note image. Admin
# can dry-run first to preview what will be deleted.
@api.post("/me/media-library/wa-cleanup", tags=["Portail Client"])
async def me_media_library_wa_cleanup(
    dry_run: bool = Query(default=True),
    user: dict = Depends(get_current_user),
):
    """Delete WhatsApp-sourced media library entries whose underlying file is
    no longer referenced anywhere else. Admin/superviseur/admin-tracked only."""
    if not (user.get("role") in ("admin", "superviseur") or _is_elevated_creator(user)):
        raise HTTPException(status_code=403, detail="Réservé aux rôles élevés")
    client_scope = user.get("client_id") or user.get("id")
    candidates = await db.media_library.find(
        {"client_id": client_scope, "source": "whatsapp_inbound"},
        {"_id": 0, "id": 1, "file_id": 1, "label": 1, "public_url": 1, "kind": 1, "created_at": 1},
    ).to_list(2000)
    if not candidates:
        return {"ok": True, "dry_run": dry_run, "examined": 0, "to_delete": [], "deleted": 0}

    file_ids = [c.get("file_id") for c in candidates if c.get("file_id")]

    # Collect every file_id referenced anywhere else in user content. We look
    # at notes/reports/suivis images arrays + interventions attachments.
    referenced: set[str] = set()
    for coll_name, field in (
        ("user_reports", "images"),
        ("user_suivis", "images"),
        ("user_notes_personal", "images"),
        ("user_tasks_personal", "images"),
        ("interventions", "attachments"),
    ):
        try:
            cursor = db[coll_name].find({field: {"$exists": True, "$ne": []}}, {"_id": 0, field: 1})
            async for d in cursor:
                for img in d.get(field) or []:
                    fid = (img or {}).get("file_id") or (img or {}).get("id")
                    if fid:
                        referenced.add(fid)
                    url = (img or {}).get("url") or ""
                    # /api/files/{file_id}.ext — extract the bare id
                    if "/api/files/" in url:
                        bare = url.split("/api/files/", 1)[1].split(".", 1)[0].split("?", 1)[0]
                        if bare:
                            referenced.add(bare)
        except Exception as exc:  # noqa: BLE001
            logger.warning("wa-cleanup ref scan failed for %s: %s", coll_name, exc)

    to_delete = [c for c in candidates if c.get("file_id") and c["file_id"] not in referenced]
    deleted = 0
    if not dry_run and to_delete:
        ids_to_remove = [c["id"] for c in to_delete]
        res = await db.media_library.delete_many({"id": {"$in": ids_to_remove}, "client_id": client_scope})
        deleted = res.deleted_count or 0
    return {
        "ok": True,
        "dry_run": dry_run,
        "examined": len(candidates),
        "to_delete": [{"id": c["id"], "label": c.get("label"), "kind": c.get("kind")} for c in to_delete],
        "deleted": deleted,
    }


# ============================================================
# Audio transcription — used by Reports/Suivis to dictate the body.
# Calls OpenAI Whisper (whisper-1 by default) using the API key
# stored in admin settings (configurable from /admin/settings).
# ============================================================
@api.post("/transcribe", tags=["Portail Client"])
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = Form("fr"),
    user: dict = Depends(get_current_user),
):
    """Accepts a short audio file (webm/mp3/m4a/wav/ogg, ≤25 Mo) and returns
    the transcribed text using OpenAI Whisper."""
    await _enforce_demo_quota(user, QUOTA_KEY_TRANSCRIBE)  # Iter35h
    # Iter38r-fix5 — Estimate audio length (rough): we'll use file size as a
    # proxy for the pre-check, then log a more accurate minute count using
    # the actual upload size. ~24 KB/s for compressed audio → MB / 1.44 ≈ min.
    s = await db.settings.find_one({"_id": "global"}) or {}
    try:
        from routes.ai_quotas import track_ai_usage as _track_ai
    except ImportError:
        _track_ai = None
    api_key = (s.get("openai_api_key") or "").strip()
    model = (s.get("openai_whisper_model") or "whisper-1").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Transcription audio non configurée. Demandez à l'admin d'ajouter une clé OpenAI dans /admin/settings.",
        )
    # Stream the upload into memory (capped) — Whisper limit is 25 Mo
    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Fichier audio trop volumineux (max 25 Mo)")
    if len(raw) < 200:
        raise HTTPException(status_code=400, detail="Audio vide")
    fname = file.filename or "audio.webm"
    mime = file.content_type or "audio/webm"
    try:
        async with httpx.AsyncClient(timeout=60) as http:
            files = {"file": (fname, raw, mime)}
            data = {"model": model, "language": (language or "fr")[:5]}
            r = await http.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
            )
            if r.status_code >= 300:
                try:
                    err = r.json().get("error", {}).get("message") or r.text[:300]
                except Exception:
                    err = r.text[:300]
                raise HTTPException(status_code=502, detail=f"OpenAI Whisper a retourné HTTP {r.status_code} — {err}")
            payload = r.json()
            # Iter38r-fix5 — Log Whisper consumption (minutes estimated from
            # raw payload size). Doesn't fail the response if tracking errors.
            est_minutes = max(round(len(raw) / (24 * 1024 * 60), 2), 0.1)
            if _track_ai is not None:
                try:
                    chk = await _track_ai(
                        db, user=user, resource="transcription",
                        units=est_minutes, model=model,
                        metadata={"bytes": len(raw)},
                    )
                    if not chk.get("allowed"):
                        # Already over budget — return the result anyway (we
                        # already paid OpenAI) but flag it in the response.
                        pass
                except Exception:
                    pass
            return {
                "ok": True,
                "text": (payload.get("text") or "").strip(),
                "model": model,
                "language": data["language"],
                "duration_bytes": len(raw),
                "duration_minutes_est": est_minutes,
            }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Délai dépassé lors de l'appel à OpenAI Whisper")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("[transcribe] unexpected exception: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)[:300])


# ============================================================
# AI Summary — used by the dashboard "Synthèse IA" button.
# Two providers are supported (toggle by admin in /admin/settings):
#   • "openai" → POST https://api.openai.com/v1/chat/completions
#   • "n8n"    → POST <n8n_webhook_url> (AgentAI-style webhook)
# Body: { messages: [{role,content,…}], context: str?, target?: str }
# Returns: { ok, provider, model?, summary }
# ============================================================
class AiSummaryRequest(BaseModel):
    messages: List[Dict[str, Any]]  # arbitrary objects (WA history rows or plain texts)
    context: Optional[str] = None  # extra prose hint, e.g. "Conversations avec ACME du 1er au 5 mai"
    target: Optional[str] = None   # e.g. client name, displayed in the prompt


def _format_messages_for_prompt(rows: List[Dict[str, Any]]) -> str:
    """Render a compact human-readable text from a heterogeneous list of WA rows."""
    lines = []
    for r in rows[:200]:  # safety cap
        if not isinstance(r, dict):
            lines.append(str(r)[:400])
            continue
        ts = r.get("created_at") or r.get("ts") or ""
        if ts and isinstance(ts, str):
            ts = ts.split("T")[0] + " " + ts.split("T")[1][:5] if "T" in ts else ts
        direction = r.get("direction") or ("outbound" if r.get("to") else "inbound")
        who = r.get("to") if direction == "outbound" else (r.get("from") or "—")
        body = (r.get("body") or r.get("text") or "").strip()
        if not body and r.get("template_name"):
            body = f"[Template {r['template_name']}]"
        if not body:
            continue
        lines.append(f"[{ts}] {direction.upper()} {who}: {body[:600]}")
    return "\n".join(lines) or "(aucun contenu)"


async def _persist_ai_summary(user: dict, provider: str, model: Optional[str], payload: AiSummaryRequest, summary: str) -> str:
    """Insert the generated summary into db.ai_summaries so it shows up in the
    history tab. Best-effort: any DB failure is logged but never bubbles up to
    the caller (the AI call already succeeded — losing the audit row mustn't
    break the user-facing response)."""
    try:
        doc = {
            "id": _uuid(),
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "user_label": user.get("full_name") or user.get("email"),
            "client_id": user.get("client_id") or user.get("id"),
            "provider": provider,
            "model": model,
            "context": (payload.context or "")[:500],
            "target": (payload.target or "")[:200],
            "messages_count": len(payload.messages or []),
            "summary": (summary or "")[:8000],
            "created_at": _now(),
        }
        await db.ai_summaries.insert_one(doc.copy())
        return doc["id"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ai-summary persist] failed: %s", exc)
        return ""


@api.post("/me/ai/summarize", tags=["Portail Client"])
async def me_ai_summarize(payload: AiSummaryRequest, user: dict = Depends(get_current_user)):
    await _enforce_demo_quota(user, QUOTA_KEY_AI)  # Iter35h
    s = await db.settings.find_one({"_id": "global"}) or {}
    provider = (s.get("ai_summary_provider") or "openai").lower()
    if provider not in ("openai", "n8n"):
        provider = "openai"
    formatted = _format_messages_for_prompt(payload.messages or [])
    sys_prompt = (
        "Tu es un assistant qui rédige des synthèses concises et professionnelles "
        "en français. Analyse précisément le CONTENU des messages WhatsApp ci-dessous "
        "(et non pas seulement les métadonnées) en 5 à 10 lignes maximum, en mettant "
        "en évidence : (1) les sujets/thèmes abordés, (2) les décisions et accords, "
        "(3) les demandes ou questions clients, (4) les blocages ou points sensibles, "
        "(5) les prochaines étapes attendues. Reste factuel ; cite si pertinent une "
        "phrase courte entre guillemets. Utilise des puces si cela aide à la lisibilité."
    )
    target_line = f"\nClient/cible : {payload.target}" if payload.target else ""
    context_line = f"\nContexte : {payload.context}" if payload.context else ""
    user_prompt = f"{target_line}{context_line}\n\nMessages :\n{formatted}".strip()

    # ---------- OpenAI ChatGPT branch ----------
    if provider == "openai":
        api_key = (s.get("openai_chat_api_key") or "").strip()
        model = (s.get("openai_chat_model") or "gpt-4o-mini").strip()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="ChatGPT non configuré. Demandez à l'admin d'ajouter une clé OpenAI ChatGPT dans /admin/settings.",
            )
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }
        try:
            async with httpx.AsyncClient(timeout=45) as http:
                r = await http.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=body,
                )
                if r.status_code >= 300:
                    try:
                        err = r.json().get("error", {}).get("message") or r.text[:300]
                    except Exception:
                        err = r.text[:300]
                    raise HTTPException(status_code=502, detail=f"OpenAI a retourné HTTP {r.status_code} — {err}")
                data = r.json()
                summary = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                summary = summary.strip()
                await _persist_ai_summary(user, "openai", model, payload, summary)
                return {"ok": True, "provider": "openai", "model": model, "summary": summary}
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Délai dépassé lors de l'appel à OpenAI ChatGPT")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ai-summary openai] unexpected: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)[:300])

    # ---------- n8n webhook branch ----------
    url = (s.get("n8n_webhook_url") or "").strip()
    if not url:
        raise HTTPException(
            status_code=503,
            detail="Webhook n8n non configuré. Renseignez l'URL dans /admin/settings.",
        )
    auth_type = (s.get("n8n_webhook_auth_type") or "none").lower()
    headers = {"Content-Type": "application/json"}
    auth = None
    if auth_type == "bearer":
        tok = (s.get("n8n_webhook_token") or "").strip()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
    elif auth_type == "basic":
        bu = (s.get("n8n_webhook_basic_user") or "").strip()
        bp = (s.get("n8n_webhook_basic_pass") or "").strip()
        if bu and bp:
            auth = (bu, bp)
    payload_n8n = {
        "type": "ai_summary",
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "company": user.get("company"),
            "client_id": user.get("client_id"),
        },
        "context": payload.context,
        "target": payload.target,
        "system_prompt": sys_prompt,
        "user_prompt": user_prompt,
        "messages": payload.messages,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as http:
            r = await http.post(url, headers=headers, auth=auth, json=payload_n8n)
            if r.status_code >= 300:
                raise HTTPException(status_code=502, detail=f"n8n a retourné HTTP {r.status_code} — {r.text[:300]}")
            try:
                data = r.json()
            except Exception:
                data = {"summary": r.text}
            # n8n returns whatever the workflow defines — accept the most common shapes:
            summary = data.get("summary") or data.get("text") or data.get("output") or data.get("message") or ""
            if not summary and isinstance(data, list) and data:
                summary = data[0].get("summary") or data[0].get("text") or ""
            if not summary:
                summary = json.dumps(data)[:2000]
            summary = str(summary).strip()
            await _persist_ai_summary(user, "n8n", None, payload, summary)
            return {"ok": True, "provider": "n8n", "summary": summary}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Délai dépassé lors de l'appel au webhook n8n")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ai-summary n8n] unexpected: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)[:300])


@api.get("/me/ai/summaries", tags=["Portail Client"])
async def me_list_ai_summaries(limit: int = 50, user: dict = Depends(get_current_user)):
    """Liste les résumés IA sauvegardés de l'utilisateur appelant (les admins voient tout,
    sorted by created_at desc). Capped at 200 per request to keep UI snappy."""
    cap = min(max(limit, 1), 200)
    if user.get("role") == "admin":
        query = {}
    else:
        # Regular users see their own summaries — they shouldn't read other
        # users of the same client (privacy: a summary may contain free-text
        # context that the author considered private).
        query = {"user_id": user["id"]}
    items = await db.ai_summaries.find(query, {"_id": 0}).sort("created_at", -1).to_list(cap)
    return items


@api.delete("/me/ai/summaries/{sid}", tags=["Portail Client"])
async def me_delete_ai_summary(sid: str, user: dict = Depends(get_current_user)):
    existing = await db.ai_summaries.find_one({"id": sid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Synthèse introuvable")
    if user.get("role") != "admin" and existing.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Suppression non autorisée")
    await db.ai_summaries.delete_one({"id": sid})
    return {"ok": True}


class AiSummaryToReport(BaseModel):
    title: Optional[str] = None
    is_private: Optional[bool] = True  # default privé to err on the safe side
    client_id: Optional[str] = None  # if provided, creates a "suivi" instead of a "report"


@api.post("/me/ai/summaries/{sid}/to-report", tags=["Portail Client"])
async def me_summary_to_report(sid: str, payload: AiSummaryToReport, request: Request, user: dict = Depends(get_current_user)):
    """Convertit un résumé IA sauvegardé en Rapport (ou en Suivi si un client_id est
    provided alongside an event_date built from the summary date). The body of
    the report contains the rendered summary plus a tiny attribution footer."""
    if not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Rôle insuffisant")
    s = await db.ai_summaries.find_one({"id": sid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Synthèse introuvable")
    if user.get("role") != "admin" and s.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Conversion non autorisée")

    title = (payload.title or "").strip() or f"Synthèse IA — {s.get('target') or s.get('created_at', '')[:10]}"
    body = (s.get("summary") or "").strip()
    # Convert plain newlines into HTML paragraphs so the rich-text editor renders them well
    paragraphs = "".join(f"<p>{p.replace('<', '&lt;').replace('>', '&gt;')}</p>" for p in body.split("\n") if p.strip())
    footer = (
        f'<hr/><p style="font-size:11px;color:#64748b;">'
        f'Généré automatiquement le {s.get("created_at", "")[:16].replace("T", " ")} '
        f'via {s.get("provider", "—")}{" · " + s.get("model") if s.get("model") else ""}'
        f'{" · cible : " + s["target"] if s.get("target") else ""}'
        f"</p>"
    )
    content_html = paragraphs + footer

    is_suivi = bool(payload.client_id)
    kind = "suivis" if is_suivi else "reports"
    coll = _user_notes_collection(kind)
    prefix = "RPT" if kind == "reports" else "SUI"
    numero = await _next_simple_number(prefix)
    doc = {
        "id": _uuid(),
        "kind": kind,
        "numero": numero,
        "owner_id": user["id"],
        "owner_email": user["email"],
        "owner_name": user.get("full_name"),
        "owner_role": user.get("tracked_role") or user.get("role"),
        "title": title,
        "content_html": content_html,
        "tags": ["ia", s.get("provider") or "ia"],
        "client_id": payload.client_id if is_suivi else None,
        "event_date": s.get("created_at") if is_suivi else None,
        "images": [],
        "is_private": bool(payload.is_private),
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent"),
        "created_at": _now(),
        "updated_at": _now(),
        "source_summary_id": sid,
    }
    await coll.insert_one(doc.copy())
    doc.pop("_id", None)
    return {"ok": True, "kind": kind, "report": doc}


@api.get("/me/clients-roster", tags=["Portail Client"])
async def me_clients_roster(user: dict = Depends(get_current_user)):
    """Renvoie une liste publique-sûre de clients servant à peupler le dropdown entreprise
    when editing a contact. Includes id, full_name, company, and client_code (ACME)."""
    items = await db.users.find(
        {"role": {"$in": ["client", "superviseur", "admin"]}},
        {"_id": 0, "id": 1, "full_name": 1, "company": 1, "client_code": 1, "is_primary_client": 1},
    ).to_list(500)
    return [i for i in items if i.get("client_code") or i.get("company")]


# ============================================================
# Platform version / build info
# ============================================================
_BUILD_TIME_ISO = datetime.now(timezone.utc).isoformat()
_BUILD_VERSION = os.environ.get("APP_VERSION") or "1.0"


async def _bump_deployment_counter_if_needed() -> Dict[str, Any]:
    """Iter43-fix24x (2026-06-16) → fix24az-t (2026-07-22) — Increment a
    sequential deployment number whenever the running build "fingerprint"
    differs from the previously stored one.

    Iter43-fix24az-t (2026-07-22) — REFACTOR : la version précédente ne
    fingerprinttait QUE `server.py`, donc toute modification dans
    `routes/*.py` ou `models.py` ne triggait pas de bump — la version restait
    figée alors que le déploiement contenait bien du nouveau code.

    Nouvelle stratégie (priorité descendante) :
      1. **DEPLOY_ID** env var — si présente, source d'autorité absolue.
         Peut être injectée par la plateforme au build/run (via CI/CD).
      2. **Hash SHA-256** combiné de plusieurs fichiers backend clés
         (`server.py`, tous les `routes/*.py`, `models.py`, `requirements.txt`).
         Change dès qu'un fichier critique est modifié.
      3. **git HEAD** (best-effort) — parfois vide en prod car le `.git`
         n'est pas dans l'image, mais utile en dev.
      4. **APP_VERSION** env var — override manuel (garde la compat).

    Stored in `db.app_deployments` (single doc with `_id="current"`).
    Returns the current `{seq, fingerprint, git_head, deploy_id}` snapshot.
    """
    import os

    # Lot 26 — l'empreinte du code (lecture de ~1,5 Mo de fichiers + commande
    # git) était recalculée à CHAQUE appel de /api/version, c'est-à-dire à
    # chaque ouverture de page (connexion comprise) et toutes les 5 minutes
    # par onglet, en bloquant le serveur. Le code ne change pas sans
    # redémarrage : on la calcule une seule fois (dans un thread) et on la garde.
    global _DEPLOY_FP_CACHE
    if _DEPLOY_FP_CACHE is None:
        _DEPLOY_FP_CACHE = await asyncio.to_thread(_compute_deploy_fingerprint)
    deploy_id, files_hash, git_head, env_ver = _DEPLOY_FP_CACHE
    return await _store_deploy_fingerprint(deploy_id, files_hash, git_head, env_ver)


_DEPLOY_FP_CACHE: Optional[tuple] = None


def _compute_deploy_fingerprint() -> tuple:
    """(deploy_id, files_hash, git_head, env_ver) — calcul synchrone, lancé
    dans un thread une seule fois par démarrage du serveur."""
    import hashlib
    import subprocess
    import os
    from pathlib import Path

    # 1) DEPLOY_ID env var — highest priority, single source of truth.
    deploy_id = (os.environ.get("DEPLOY_ID") or "").strip()

    # 2) SHA-256 hash of multiple critical backend files. Sorted by relative
    # path for deterministic ordering. Missing files are skipped silently.
    files_hash: Optional[str] = None
    try:
        h = hashlib.sha256()
        backend_root = Path("/app/backend")
        critical_paths: List[Path] = [
            backend_root / "server.py",
            backend_root / "models.py",
            backend_root / "requirements.txt",
        ]
        # Include every routes/*.py in sorted order to avoid FS-order flakiness.
        routes_dir = backend_root / "routes"
        if routes_dir.is_dir():
            critical_paths.extend(sorted(routes_dir.glob("*.py")))
        # Lot 28 — server.py est découpé en server_parts/*.py : ils comptent aussi
        parts_dir = backend_root / "server_parts"
        if parts_dir.is_dir():
            critical_paths.extend(sorted(parts_dir.glob("*.py")))
        for p in critical_paths:
            try:
                # Feed relative path (deterministic) + content bytes.
                h.update(str(p.relative_to(backend_root)).encode())
                h.update(b"\0")
                h.update(p.read_bytes())
                h.update(b"\0")
            except OSError:
                continue
        files_hash = h.hexdigest()[:16]  # 16 hex chars ≈ 64 bits — plenty
    except Exception:  # noqa: BLE001
        files_hash = None

    # 3) git HEAD (best-effort; often unavailable in a stripped prod image).
    git_head: Optional[str] = None
    try:
        git_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd="/app",
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode().strip()
    except Exception:  # noqa: BLE001
        git_head = None

    # 4) APP_VERSION env var — manual override for the major version prefix.
    env_ver = (os.environ.get("APP_VERSION") or "").strip()
    return deploy_id, files_hash, git_head, env_ver


async def _store_deploy_fingerprint(deploy_id: str, files_hash: Optional[str], git_head: Optional[str],
                                    env_ver: str) -> Dict[str, Any]:
    """Compare l'empreinte à celle enregistrée et incrémente le numéro de déploiement."""
    # Compose the fingerprint (priority = DEPLOY_ID > files_hash > git > env).
    fingerprint_parts: List[str] = []
    if deploy_id:
        fingerprint_parts.append(f"deploy:{deploy_id}")
    if files_hash:
        fingerprint_parts.append(f"files:{files_hash}")
    if git_head:
        fingerprint_parts.append(f"git:{git_head[:12]}")
    if env_ver:
        fingerprint_parts.append(f"env:{env_ver}")
    fingerprint = "|".join(fingerprint_parts) if fingerprint_parts else None

    try:
        current = await db.app_deployments.find_one({"_id": "current"}) or {}
    except Exception:  # noqa: BLE001
        return {
            "seq": 0, "git_head": git_head, "fingerprint": fingerprint,
            "deploy_id": deploy_id or None, "files_hash": files_hash,
        }
    prev_fp = current.get("fingerprint") or current.get("git_head")  # bw-compat
    seq = int(current.get("seq") or 0)
    deployed_at = current.get("deployed_at")
    # Bump when the fingerprint changed (or first run).
    if fingerprint and fingerprint != prev_fp:
        seq += 1
        try:
            await db.app_deployments.update_one(
                {"_id": "current"},
                {"$set": {
                    "seq": seq,
                    "fingerprint": fingerprint,
                    "git_head": git_head,
                    "deploy_id": deploy_id or None,
                    "files_hash": files_hash,
                    "deployed_at": _BUILD_TIME_ISO,
                    "prev_fingerprint": prev_fp,
                }},
                upsert=True,
            )
            deployed_at = _BUILD_TIME_ISO
            logger.info(
                "[deploy-counter] bumped seq=%s files_hash=%s deploy_id=%s",
                seq, files_hash, deploy_id or "-",
            )
        except Exception:  # noqa: BLE001
            logger.warning("[deploy-counter] failed to bump", exc_info=True)
    return {
        "seq": seq, "git_head": git_head, "fingerprint": fingerprint,
        "deploy_id": deploy_id or None, "files_hash": files_hash,
        "deployed_at": deployed_at,
    }


@api.get("/version-detail", tags=["Public"])
async def get_version_detail():
    """Iter43-fix24x → fix24az-t (2026-07-22) — wrapper public détaillé pour
    le numéro de déploiement.

    Renvoie :
      - `version` : "{APP_VERSION}.{seq}" (ex: "1.21")
      - `started_at` : ISO timestamp du dernier bump
      - `deploy_seq` : compteur monotone (+1 à chaque déploiement détecté)
      - `git_head` : short hash (7 chars) — vide en prod sans .git
      - `files_hash` : hash SHA-256 court (16 chars) des fichiers critiques
        (server.py + routes/*.py + models.py + requirements.txt). Change dès
        qu'un fichier backend est modifié — le vrai signal de fraîcheur.
      - `deploy_id` : valeur brute de `DEPLOY_ID` env var (si injectée par le CI)
    """
    snap = await _bump_deployment_counter_if_needed()
    seq = int(snap.get("seq") or 0)
    env_ver = (os.environ.get("APP_VERSION") or "").strip()
    base = env_ver if env_ver else "1"
    version = f"{base}.{seq}"
    return {
        "version": version,
        "started_at": snap.get("deployed_at") or _BUILD_TIME_ISO,
        "deploy_seq": seq,
        "git_head": (snap.get("git_head") or "")[:7],  # short hash for UI
        # Iter43-fix24az-t — nouveaux champs pour debug/monitoring
        "files_hash": snap.get("files_hash"),
        "deploy_id": snap.get("deploy_id"),
    }


# ====================================================================
# ADMIN - Content (CMS)
# ====================================================================
@api.put("/admin/content/{slug}", tags=["Admin"])
async def admin_upsert_content(slug: str, payload: ContentUpsert, _: dict = Depends(get_current_admin)):
    doc = {**payload.model_dump(), "slug": slug, "updated_at": _now()}
    existing = await db.contents.find_one({"slug": slug})
    if existing:
        await db.contents.update_one({"slug": slug}, {"$set": doc})
    else:
        doc["id"] = _uuid()
        doc["created_at"] = _now()
        await db.contents.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.delete("/admin/content/{slug}", tags=["Admin"])
async def admin_delete_content(slug: str, _: dict = Depends(get_current_admin)):
    await db.contents.delete_one({"slug": slug})
    return {"ok": True}


# Iter40-content-i18n — Translate an entire content document (title, body_html,
# metadata.kicker, and metadata.metrics/items labels) in ONE LLM call. The
# JSON-in / JSON-out contract preserves HTML tags and content structure.
@api.post("/admin/content/{slug}/translate", tags=["Admin"])
async def admin_translate_content(slug: str, payload: dict = Body(...), user: dict = Depends(get_current_admin)):
    target_lang = (payload.get("target_lang") or "").strip().lower()
    model_id = (payload.get("model") or "claude-sonnet-4-5-20250929").strip()
    if target_lang not in {"en", "ar", "lg1", "lg2"}:
        raise HTTPException(status_code=400, detail="Langue cible non supportée.")
    # Whitelist of allowed models (same set as i18n)
    _ALLOWED = {
        "claude-sonnet-4-5-20250929": ("anthropic", "claude-sonnet-4-5-20250929"),
        "claude-haiku-4-5-20251001": ("anthropic", "claude-haiku-4-5-20251001"),
        "gpt-4o": ("openai", "gpt-4o"),
        "gpt-4o-mini": ("openai", "gpt-4o-mini"),
        "gemini-2.5-pro": ("gemini", "gemini-2.5-pro"),
        "gemini-2.5-flash": ("gemini", "gemini-2.5-flash"),
    }
    if model_id not in _ALLOWED:
        raise HTTPException(status_code=400, detail=f"Modèle non autorisé : {model_id}")
    emergent_key = os.environ.get("EMERGENT_LLM_KEY")
    if not emergent_key:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY non configurée.")
    doc = await db.contents.find_one({"slug": slug}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Contenu introuvable")

    # Build the payload to translate: extract translatable strings from the
    # DEFAULT fields (admin can override later from the UI).
    translatable = {
        "title": doc.get("title") or "",
        "body_html": doc.get("body_html") or "",
        "kicker": (doc.get("metadata") or {}).get("kicker") or "",
        "metrics": [
            {"label": m.get("label") or "", "value": m.get("value") or ""}
            for m in ((doc.get("metadata") or {}).get("metrics") or [])
        ],
        "items": [
            {"title": it.get("title") or "", "desc": it.get("desc") or ""}
            for it in ((doc.get("metadata") or {}).get("items") or [])
        ],
    }
    # Drop empty arrays to keep the prompt compact
    if not translatable["metrics"]:
        translatable.pop("metrics")
    if not translatable["items"]:
        translatable.pop("items")
    if not (translatable.get("title") or translatable.get("body_html") or translatable.get("kicker") or translatable.get("metrics") or translatable.get("items")):
        raise HTTPException(status_code=400, detail="Aucun texte à traduire.")

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"Bibliothèque IA absente : {exc}") from exc

    lang_labels = {
        "en": "English",
        "ar": "Modern Standard Arabic (formal, no transliteration)",
        "lg1": "Gulmancema (Burkina Faso national language)",
        "lg2": "Mooré (Burkina Faso national language)",
    }
    target_label = lang_labels[target_lang]
    import json as _json
    system_text = (
        "You are a professional website translator. Translate the JSON values "
        "from French to the requested target language. Preserve EXACTLY:\n"
        " - All HTML tags and attributes (<p>, <strong>, <a href=...>, …)\n"
        " - Placeholders like {name}, {{var}}, and HTML entities\n"
        " - Numbers (10+, 24/7, etc.) — do not translate digits\n"
        " - Brand names: SAWALI, Liluvine, WhatsApp, PawaPay, Stripe (keep unchanged)\n"
        "Return ONLY a valid JSON object with EXACTLY the same keys and structure "
        "as the input. NO markdown fences, NO commentary."
    )
    user_msg = (
        f"Target language: {target_label}\n\n"
        f"Input JSON (French):\n{_json.dumps(translatable, ensure_ascii=False, indent=2)}"
    )
    provider, model_name = _ALLOWED[model_id]
    try:
        chat = LlmChat(
            api_key=emergent_key,
            session_id=f"content-translate-{slug}-{user.get('id') or 'admin'}",
            system_message=system_text,
        ).with_model(provider, model_name)
        raw = (await chat.send_message(UserMessage(text=user_msg))) or ""
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Échec LLM : {str(exc)[:200]}") from exc

    # Parse the model response (strip optional ```json fences just in case)
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    parsed: dict = {}
    try:
        parsed = _json.loads(text)
    except Exception:  # noqa: BLE001
        import re as _re
        m = _re.search(r"\{.*\}", text, _re.S)
        if m:
            try:
                parsed = _json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                parsed = {}
    if not parsed:
        raise HTTPException(status_code=502, detail="Réponse IA non parsable")

    # Build the override dict in our translations[<lang>] shape
    override: dict = {}
    if parsed.get("title"):
        override["title"] = str(parsed["title"])
    if parsed.get("body_html") is not None:
        override["body_html"] = str(parsed["body_html"])
    meta: dict = {}
    if parsed.get("kicker"):
        meta["kicker"] = str(parsed["kicker"])
    if isinstance(parsed.get("metrics"), list):
        meta["metrics"] = [
            {"label": (m.get("label") or "") if isinstance(m, dict) else "",
             "value": (m.get("value") or "") if isinstance(m, dict) else ""}
            for m in parsed["metrics"]
        ]
    if isinstance(parsed.get("items"), list):
        # Preserve icons from the default doc (LLM doesn't know our icon names)
        base_items = ((doc.get("metadata") or {}).get("items") or [])
        meta["items"] = [
            {"title": (it.get("title") or "") if isinstance(it, dict) else "",
             "desc": (it.get("desc") or "") if isinstance(it, dict) else "",
             "icon": (base_items[i].get("icon") if i < len(base_items) else None) or "Code"}
            for i, it in enumerate(parsed["items"])
        ]
    if meta:
        override["metadata"] = meta

    # Persist to translations[<target_lang>]
    translations = dict(doc.get("translations") or {})
    translations[target_lang] = override
    await db.contents.update_one(
        {"slug": slug},
        {"$set": {"translations": translations, "updated_at": _now()}},
    )
    return {"ok": True, "slug": slug, "target_lang": target_lang, "model": model_id, "override": override}
