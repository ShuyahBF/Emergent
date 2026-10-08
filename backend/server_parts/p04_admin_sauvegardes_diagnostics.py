# server_parts/p04_admin_sauvegardes_diagnostics.py — Instantanés de base, sauvegarde auto, feuille de route, coffre de secrets, diagnostics clients, efficacité des campagnes.
# Morceau de l'ancien server.py (lignes 5228 à 7712), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ============================================================
# iter34 — DB Snapshots (Production → Preview safe restore)
#
# Admin can export the current MongoDB state to a gzipped JSON file,
# download it, and import it on another environment (typically: prod → preview)
# without ever touching binary uploads on disk. All snapshots are listed
# with their author, date, size and a free-text comment that can be edited.
#
# Sensitive credentials (API tokens, SMTP password, webhook secrets) are
# masked at export time so the file can be safely shared. User password
# hashes are PRESERVED (admins want to log in with their prod password
# on preview); only API/3rd-party secrets are masked.
# ============================================================
# Lot 49 — dossier portable (variable SNAPSHOTS_DIR, sinon /app/backend/snapshots, sinon le
# dossier du projet) ; déjà créé par backend/chemins.py, sans erreur possible au démarrage.
from chemins import SNAPSHOTS_DIR, MEMORY_DIR as _MEMORY_DIR  # noqa: E402

SNAPSHOT_COLLECTIONS = [
    "users", "directory_contacts", "contacts", "appointments", "interventions",
    "documents", "tracked_users", "contents", "client_notes", "client_tasks",
    "user_notes", "user_reports", "user_suivis", "user_notes_personal",
    "user_tasks_personal",  # Iter35g — personal portal notes & tasks
    "document_categories",
    "client_categories", "subscription_categories", "subscription_plans",
    "subscription_orders", "formations", "formation_modules",
    "formation_enrollments", "blog_posts", "case_studies", "testimonials",
    "deployments", "newsletter", "incidents", "settings", "automations",
    "payments", "payment_links", "sms_schedules", "whatsapp_schedules",
    "forms", "form_submissions", "media_library", "roadmap_actions",
]

SENSITIVE_SETTINGS_KEYS = {
    "smtp_password", "google_client_secret", "recaptcha_secret_key",
    "tracking_auth_header", "webhook_token", "webhook_basic_pass",
    "notes_webhook_token", "notes_webhook_basic_pass",
    "health_webhook_token", "health_webhook_basic_pass",
    "wa_access_token", "wa_verify_token", "openai_api_key", "openai_chat_api_key",
    "n8n_webhook_token", "n8n_webhook_basic_pass",
    "sms_orange_token", "sms_orange_basic_pass", "sms_orange_header_value",
    "sms_orange_client_secret",  # Iter35i — Orange OAuth client_credentials
    "sms_moov_token", "sms_moov_basic_pass", "sms_moov_header_value",
    "sms_moov_client_secret",
    "sms_telecel_token", "sms_telecel_basic_pass", "sms_telecel_header_value",
    "sms_telecel_client_secret",
    "sms_ovh_application_secret", "sms_ovh_consumer_key",
    "pawapay_api_token",
    # Iter38h — Meta App secrets (Pages + Messenger + Ads)
    "meta_app_secret", "meta_webhook_verify_token",
}
SNAPSHOT_MASK = "***MASKED***"


def _mask_settings_doc(doc: dict) -> dict:
    out = dict(doc)
    for k in SENSITIVE_SETTINGS_KEYS:
        if k in out and out[k]:
            out[k] = SNAPSHOT_MASK
    return out


def _json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    try:
        return str(obj)
    except Exception:
        return None


async def _build_snapshot_payload(mask_secrets: bool = True) -> tuple[dict, dict]:
    """Returns (payload, stats). payload is the full snapshot dict ready to be
    serialized to JSON. stats is a {collection: count} mapping."""
    collections: Dict[str, List[Dict[str, Any]]] = {}
    stats: Dict[str, int] = {}
    for name in SNAPSHOT_COLLECTIONS:
        cursor = db[name].find({}, {"_id": 0})
        rows = [r async for r in cursor]
        if name == "settings" and mask_secrets:
            rows = [_mask_settings_doc(r) for r in rows]
        collections[name] = rows
        stats[name] = len(rows)
    payload = {
        "version": 1,
        "exported_at": _now(),
        "mask_secrets": bool(mask_secrets),
        "collections": collections,
        "stats": stats,
    }
    return payload, stats


async def _apply_snapshot(payload: dict, mode: str, dry_run: bool = False) -> dict:
    """Restore a snapshot. mode='replace' wipes each collection before insert.
    mode='merge' upserts by `id` field (or by `email` for users). Returns a
    summary dict {collection: {before, after, action, error?}}.

    Hardened (iter35a): per-collection try/except so one bad collection
    doesn't 500 the whole import; insert_many uses ordered=False to skip
    duplicate-key rows; settings is special-cased to preserve the
    `_id='global'` singleton anchor.
    """
    collections = payload.get("collections") or {}
    summary: Dict[str, Dict[str, Any]] = {}
    if mode not in ("replace", "merge"):
        raise HTTPException(status_code=400, detail=f"mode invalide: {mode}")

    INSERT_CHUNK = 500
    # Settings docs are singletons keyed by string _id (e.g., 'global'). The
    # snapshot strips _id on export → we must restore it for these docs.
    SETTINGS_SINGLETON_COLLECTIONS = {"settings"}

    def _strip_id(r: dict) -> dict:
        return {k: v for k, v in r.items() if k != "_id"}

    def _settings_anchor_id(r: dict) -> str:
        # If we ever export with _id preserved use it; otherwise default to 'global'.
        return r.get("_id_anchor") or r.get("settings_key") or "global"

    for name in SNAPSHOT_COLLECTIONS:
        # Only act on collections that are actually present in the snapshot.
        # A partial snapshot must NOT cascade-wipe unrelated collections.
        if name not in collections:
            continue
        rows = collections.get(name) or []
        try:
            before = await db[name].count_documents({})
        except Exception as exc:  # noqa: BLE001
            summary[name] = {"before": None, "incoming": len(rows), "action": "error", "error": f"count failed: {exc}"}
            continue

        if dry_run:
            summary[name] = {"before": before, "incoming": len(rows), "action": "dry-run"}
            continue

        try:
            if mode == "replace":
                await db[name].delete_many({})
                inserted_n = 0
                errors: List[str] = []
                if rows:
                    if name in SETTINGS_SINGLETON_COLLECTIONS:
                        # Singleton(s) with string _id — insert one-by-one and
                        # re-anchor the `_id` to its canonical value so future
                        # `find_one({"_id": "global"})` still resolves.
                        for r in rows:
                            doc = _strip_id(r)
                            doc["_id"] = _settings_anchor_id(r)
                            try:
                                await db[name].replace_one({"_id": doc["_id"]}, doc, upsert=True)
                                inserted_n += 1
                            except Exception as exc:  # noqa: BLE001
                                errors.append(str(exc)[:150])
                    else:
                        clean = [_strip_id(r) for r in rows]
                        # Chunked, unordered: keep going on duplicate-key / validation errors
                        for i in range(0, len(clean), INSERT_CHUNK):
                            batch = clean[i:i + INSERT_CHUNK]
                            try:
                                res = await db[name].insert_many(batch, ordered=False)
                                inserted_n += len(res.inserted_ids)
                            except Exception as exc:  # noqa: BLE001
                                # BulkWriteError still inserts the non-conflicting docs
                                details = getattr(exc, "details", None) or {}
                                ok_n = (details.get("nInserted") if isinstance(details, dict) else None)
                                if isinstance(ok_n, int):
                                    inserted_n += ok_n
                                errors.append(f"batch {i // INSERT_CHUNK}: {str(exc)[:200]}")
                after = await db[name].count_documents({})
                entry = {"before": before, "after": after, "incoming": len(rows),
                         "inserted": inserted_n, "action": "replaced"}
                if errors:
                    entry["errors"] = errors[:5]
                    entry["error_count"] = len(errors)
                summary[name] = entry

            else:  # merge
                merged = 0
                inserted_n = 0
                errors: List[str] = []
                for r in rows:
                    try:
                        key = None
                        if name == "users" and r.get("email"):
                            key = {"email": r["email"]}
                        elif name in SETTINGS_SINGLETON_COLLECTIONS:
                            key = {"_id": _settings_anchor_id(r)}
                        elif r.get("id"):
                            key = {"id": r["id"]}
                        doc = _strip_id(r)
                        if name in SETTINGS_SINGLETON_COLLECTIONS:
                            doc["_id"] = _settings_anchor_id(r)
                        if not key:
                            await db[name].insert_one(doc)
                            inserted_n += 1
                            continue
                        res = await db[name].update_one(key, {"$set": doc}, upsert=True)
                        if res.upserted_id is not None:
                            inserted_n += 1
                        else:
                            merged += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(str(exc)[:200])
                after = await db[name].count_documents({})
                entry = {"before": before, "after": after, "incoming": len(rows),
                         "merged": merged, "inserted": inserted_n, "action": "merged"}
                if errors:
                    entry["errors"] = errors[:5]
                    entry["error_count"] = len(errors)
                summary[name] = entry

        except Exception as exc:  # noqa: BLE001
            logger.exception("snapshot apply collection=%s failed", name)
            summary[name] = {"before": before, "incoming": len(rows), "action": "error",
                             "error": str(exc)[:300]}
            continue

    return summary


@api.get("/admin/snapshots", tags=["Admin"])
async def admin_list_snapshots(_: dict = Depends(get_current_admin)):
    """Liste tous les instantanés triés par created_at décroissant."""
    docs = [r async for r in db.db_snapshots.find({}, {"_id": 0}).sort("created_at", -1)]
    return {"snapshots": docs, "count": len(docs)}


async def _create_snapshot_record(comment: str, mask_secrets: bool, author_id: Optional[str], author_email: Optional[str], kind: str = "manual") -> dict:
    """Build a snapshot file on disk + insert metadata into db.db_snapshots.
    Reusable from the HTTP endpoint and the weekly cron. Returns the metadata
    dict (already _id-stripped via serialize)."""
    snap_id = _uuid()
    file_name = f"snapshot_{snap_id}.json.gz"
    file_path = SNAPSHOTS_DIR / file_name
    snap_payload, stats = await _build_snapshot_payload(mask_secrets=mask_secrets)
    # Lot 27 : conversion, compression et écriture (lourdes, toute la base)
    # exécutées dans un thread — la sauvegarde ne fige plus le serveur.
    def _dump_and_write() -> tuple:
        raw_bytes = json.dumps(snap_payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        packed = gzip.compress(raw_bytes, compresslevel=6)
        file_path.write_bytes(packed)
        return packed, len(raw_bytes)
    compressed, raw_size = await asyncio.to_thread(_dump_and_write)
    meta = {
        "id": snap_id,
        "created_at": _now(),
        "author_id": author_id,
        "author_email": author_email,
        "comment": (comment or "").strip()[:500],
        "size_bytes": len(compressed),
        "raw_size_bytes": raw_size,
        "collections_count": len([k for k, v in stats.items() if v > 0]),
        "total_documents": sum(stats.values()),
        "stats": stats,
        "mask_secrets": mask_secrets,
        "file_name": file_name,
        "kind": kind,  # "manual" | "auto"
    }
    await db.db_snapshots.insert_one(dict(meta))
    return serialize(meta)


@api.post("/admin/snapshots", tags=["Admin"])
async def admin_create_snapshot(payload: Dict[str, Any] = Body(default={}), user: dict = Depends(get_current_admin)):
    """Crée un nouvel instantané de toutes les collections métier.
    Body: {comment?: str, mask_secrets?: bool=True}
    """
    comment = (payload.get("comment") or "").strip()[:500]
    mask_secrets = bool(payload.get("mask_secrets", True))
    return await _create_snapshot_record(
        comment=comment,
        mask_secrets=mask_secrets,
        author_id=user.get("id"),
        author_email=user.get("email"),
        kind="manual",
    )


@api.get("/admin/snapshots/{snap_id}/download", tags=["Admin"])
async def admin_download_snapshot(snap_id: str, _: dict = Depends(get_current_admin)):
    meta = await db.db_snapshots.find_one({"id": snap_id}, {"_id": 0})
    if not meta:
        raise HTTPException(status_code=404, detail="Snapshot introuvable")
    file_path = SNAPSHOTS_DIR / meta["file_name"]
    if not file_path.exists():
        raise HTTPException(status_code=410, detail="Fichier physique manquant")
    return FileResponse(str(file_path), media_type="application/gzip", filename=meta["file_name"])


@api.patch("/admin/snapshots/{snap_id}", tags=["Admin"])
async def admin_update_snapshot(snap_id: str, payload: Dict[str, Any] = Body(...), _: dict = Depends(get_current_admin)):
    update: Dict[str, Any] = {}
    if "comment" in payload:
        update["comment"] = (payload.get("comment") or "").strip()[:500]
    if not update:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    update["updated_at"] = _now()
    res = await db.db_snapshots.update_one({"id": snap_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Snapshot introuvable")
    meta = await db.db_snapshots.find_one({"id": snap_id}, {"_id": 0})
    return serialize(meta)


@api.delete("/admin/snapshots/{snap_id}", tags=["Admin"])
async def admin_delete_snapshot(snap_id: str, _: dict = Depends(get_current_admin)):
    meta = await db.db_snapshots.find_one({"id": snap_id}, {"_id": 0})
    if not meta:
        raise HTTPException(status_code=404, detail="Snapshot introuvable")
    file_path = SNAPSHOTS_DIR / meta["file_name"]
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Snapshot %s file delete failed: %s", snap_id, exc)
    await db.db_snapshots.delete_one({"id": snap_id})
    return {"ok": True, "id": snap_id}


# ============================================================
# Auto-snapshot — weekly cron + admin-controlled toggle/run-now.
# Keeps only the last N (default 4) auto snapshots; manual ones never rotate.
# Driven by settings.auto_snapshot_enabled, .auto_snapshot_keep (int) and
# logged into db.db_snapshots with kind='auto'.
# ============================================================
AUTO_SNAPSHOT_DEFAULT_KEEP = 4


async def _run_auto_snapshot(triggered_by: str = "cron:weekly") -> dict:
    """Create an auto snapshot then prune older auto snapshots beyond the
    rotation window. Idempotent (safe to call manually too). If
    settings.auto_snapshot_email_enabled and a recipient is configured, the
    .json.gz file is sent as an SMTP attachment to that address."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    keep = int(s.get("auto_snapshot_keep") or AUTO_SNAPSHOT_DEFAULT_KEEP)
    keep = max(1, min(keep, 52))  # clamp 1..52 weeks
    meta = await _create_snapshot_record(
        comment=f"Sauvegarde automatique — {triggered_by}",
        mask_secrets=True,
        author_id=None,
        author_email="(système)",
        kind="auto",
    )
    # Rotation: delete older auto snapshots beyond `keep`
    autos_cursor = db.db_snapshots.find(
        {"kind": "auto"}, {"_id": 0, "id": 1, "file_name": 1, "created_at": 1}
    ).sort("created_at", -1)
    autos = [a async for a in autos_cursor]
    to_delete = autos[keep:]
    deleted = 0
    for a in to_delete:
        fp = SNAPSHOTS_DIR / (a.get("file_name") or "")
        try:
            if fp.exists():
                fp.unlink()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auto-snapshot %s file delete failed: %s", a.get("id"), exc)
        await db.db_snapshots.delete_one({"id": a["id"]})
        deleted += 1
    # Email delivery (best-effort, never blocks rotation)
    email_status: Dict[str, Any] = {"enabled": bool(s.get("auto_snapshot_email_enabled")), "sent": False, "to": None}
    if s.get("auto_snapshot_email_enabled"):
        recipient = (s.get("auto_snapshot_email_to") or "").strip()
        if recipient and "@" in recipient:
            email_status["to"] = recipient
            try:
                file_path = SNAPSHOTS_DIR / meta["file_name"]
                if file_path.exists():
                    content = await asyncio.to_thread(file_path.read_bytes)  # lot 27 : lecture hors du serveur principal
                    pretty_size = f"{len(content)/1024:.1f} kB"
                    # Build the companion weekly health report PDF
                    pdf_bytes = b""
                    pdf_attached = False
                    try:
                        from health_report import build_weekly_health_pdf
                        pdf_bytes = await build_weekly_health_pdf(snapshot_meta=meta)
                        pdf_attached = bool(pdf_bytes)
                    except Exception as pdf_exc:  # noqa: BLE001
                        logger.warning("Weekly PDF generation failed: %s", pdf_exc)
                    subject = f"[SAWALI] Sauvegarde DB + Rapport hebdomadaire — {meta['file_name']}"
                    html = (
                        f"<div style=\"font-family:Arial,sans-serif;line-height:1.5\">"
                        f"<h2 style=\"color:#0E1F3D\">SAWALI — Sauvegarde DB &amp; Rapport hebdomadaire</h2>"
                        f"<p>Bonjour,</p>"
                        f"<p>Voici votre sauvegarde automatique accompagnée du rapport de santé de la plateforme.</p>"
                        f"<ul>"
                        f"<li><strong>Date</strong> : {meta['created_at']}</li>"
                        f"<li><strong>Déclencheur</strong> : <code>{triggered_by}</code></li>"
                        f"<li><strong>Documents</strong> : {meta['total_documents']} sur {meta['collections_count']} collections</li>"
                        f"<li><strong>Taille snapshot</strong> : {pretty_size}</li>"
                        f"<li><strong>Secrets masqués</strong> : {'oui' if meta.get('mask_secrets') else 'non'}</li>"
                        f"<li><strong>Rapport PDF</strong> : {'joint' if pdf_attached else 'non disponible'}</li>"
                        f"</ul>"
                        f"<p>Pièces jointes : <code>{meta['file_name']}</code>"
                        f"{' + <code>rapport-hebdomadaire.pdf</code>' if pdf_attached else ''}</p>"
                        f"<p style=\"color:#64748B;font-size:12px\">Pour désactiver l'envoi par email, "
                        f"rendez-vous dans Paramètres → Sauvegarde de la base.</p>"
                        f"</div>"
                    )
                    text = (
                        f"Sauvegarde DB SAWALI — {meta['file_name']}\n"
                        f"Date: {meta['created_at']}\n"
                        f"Déclencheur: {triggered_by}\n"
                        f"Documents: {meta['total_documents']} ({meta['collections_count']} collections)\n"
                        f"Taille snapshot: {pretty_size}\n"
                        f"Rapport PDF joint: {'oui' if pdf_attached else 'non'}\n"
                    )
                    atts = [{
                        "filename": meta["file_name"],
                        "content": content,
                        "mime_type": "application/gzip",
                    }]
                    if pdf_attached:
                        atts.append({
                            "filename": f"rapport-hebdomadaire-{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf",
                            "content": pdf_bytes,
                            "mime_type": "application/pdf",
                        })
                    sent = await send_email(
                        recipient, subject, html, text,
                        attachments=atts,
                    )
                    email_status["sent"] = bool(sent)
                    email_status["pdf_attached"] = pdf_attached
                else:
                    email_status["error"] = "fichier introuvable"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Auto-snapshot email failed: %s", exc)
                email_status["error"] = str(exc)
        else:
            email_status["error"] = "auto_snapshot_email_to non configuré"
    # Persist last_run marker on settings for the UI
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "auto_snapshot_last_run_at": _now(),
            "auto_snapshot_last_run_id": meta["id"],
            "auto_snapshot_last_run_trigger": triggered_by,
            "auto_snapshot_last_email_sent": email_status.get("sent", False),
            "auto_snapshot_last_email_to": email_status.get("to"),
        }},
        upsert=True,
    )
    return {"snapshot": meta, "deleted": deleted, "kept": min(len(autos) + 1 - deleted, keep), "email": email_status}


@api.post("/admin/snapshots/auto-run", tags=["Admin"])
async def admin_run_auto_snapshot(user: dict = Depends(get_current_admin)):
    """Trigger the weekly auto-snapshot logic immediately (manual)."""
    return await _run_auto_snapshot(triggered_by=f"manual:{user.get('email','admin')}")


@api.get("/admin/snapshots/weekly-report-preview", tags=["Admin"])
async def admin_preview_weekly_report(_: dict = Depends(get_current_admin)):
    """Render the weekly health-report PDF on-demand. Useful for the admin
    to verify what gets attached to the snapshot email."""
    try:
        from health_report import build_weekly_health_pdf
        pdf_bytes = await build_weekly_health_pdf(snapshot_meta=None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Génération PDF échouée: {exc}")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="rapport-hebdomadaire-preview.pdf"'},
    )


# ============================================================
# Iter34h — Roadmap actions tracker
# Auto-numbered log of every dev iteration (manual seed below). Admins can
# edit only the `observations` column from the UI. All other fields are
# auto-populated by the developer when each task lands.
# ============================================================
DEFAULT_ROADMAP_HOURLY_RATE_XOF = 25000  # ~50 USD/h dev rate, adjustable below

# Seed list — chronological ordering preserved. `code` is the human-readable
# auto number ("ACT-0001"…) and is the canonical ID on disk. Done items have
# `done_at` set; pending items keep it null.
ROADMAP_SEED: List[Dict[str, Any]] = [
    {"code": "ACT-0001", "created_at": "2026-05-09T00:00:00+00:00", "done_at": "2026-05-09T18:30:00+00:00",
     "title": "Diagnostic des données orphelines", "backlog_ref": "Iter28",
     "duration_h": 2.0, "done": True,
     "details": "Endpoint /api/admin/migrate-orphan-data + UI bouton dans /admin/settings pour réaligner contacts/RDV/interventions sans client_id valide."},
    {"code": "ACT-0002", "created_at": "2026-05-10T00:00:00+00:00", "done_at": "2026-05-10T08:00:00+00:00",
     "title": "Contact Collaborative Model (shared by default)", "backlog_ref": "Iter29",
     "duration_h": 1.5, "done": True,
     "details": "Le champ `shared=true` est désormais le défaut sur les nouveaux contacts."},
    {"code": "ACT-0003", "created_at": "2026-05-10T08:00:00+00:00", "done_at": "2026-05-10T11:30:00+00:00",
     "title": "Cohérence multi-utilisateurs (canary + UI Realignment)", "backlog_ref": "Iter30+31",
     "duration_h": 3.0, "done": True,
     "details": "Diagnostic visibilité par utilisateur + bouton 'Résoudre' qui réaligne automatiquement client_id."},
    {"code": "ACT-0004", "created_at": "2026-05-10T11:30:00+00:00", "done_at": "2026-05-10T13:00:00+00:00",
     "title": "Auto-link user→company à la création", "backlog_ref": "Iter32",
     "duration_h": 1.0, "done": True,
     "details": "Au moment de la création d'un user tracked, son client_id est lié automatiquement au parent de la même `company`."},
    {"code": "ACT-0005", "created_at": "2026-05-10T13:00:00+00:00", "done_at": "2026-05-10T15:00:00+00:00",
     "title": "Recherche/filtre + bulles NOUVEAU dans /admin/settings", "backlog_ref": "Iter33",
     "duration_h": 2.0, "done": True,
     "details": "Toolbar sticky avec input de recherche, dropdown 'Aller à', 9 sections marquées NOUVEAU avec fade automatique après 3 jours."},
    {"code": "ACT-0006", "created_at": "2026-05-10T15:00:00+00:00", "done_at": "2026-05-10T17:00:00+00:00",
     "title": "DB Snapshots — Export/Import depuis /admin/settings", "backlog_ref": "Iter34",
     "duration_h": 2.0, "done": True,
     "details": "6 endpoints /api/admin/snapshots* : create/list/download/patch/delete/import. Masquage automatique des secrets. Modes replace/merge + dry-run."},
    {"code": "ACT-0007", "created_at": "2026-05-10T17:00:00+00:00", "done_at": "2026-05-10T17:30:00+00:00",
     "title": "Société autocomplete (datalist) dans Contacts.jsx", "backlog_ref": "Iter34",
     "duration_h": 0.5, "done": True,
     "details": "Champ Société → <input list> HTML5 avec datalist (filtrage natif + saisie libre)."},
    {"code": "ACT-0008", "created_at": "2026-05-10T17:30:00+00:00", "done_at": "2026-05-10T18:00:00+00:00",
     "title": "Visibilité partagée des contacts entre utilisateurs même société", "backlog_ref": "Iter34/Issue 3",
     "duration_h": 0.5, "done": True,
     "details": "Helper _resolve_visible_client_ids() bridge contacts entre users du même `company` (case-insensitive)."},
    {"code": "ACT-0009", "created_at": "2026-05-10T18:00:00+00:00", "done_at": "2026-05-10T18:30:00+00:00",
     "title": "Auto-snapshot hebdomadaire (cron dimanche 03:00)", "backlog_ref": "Iter34b",
     "duration_h": 0.5, "done": True,
     "details": "APScheduler `db_auto_snapshot_weekly` + endpoint /api/admin/snapshots/auto-run + UI toggle + rotation configurable (1..52)."},
    {"code": "ACT-0010", "created_at": "2026-05-10T18:30:00+00:00", "done_at": "2026-05-10T19:00:00+00:00",
     "title": "Envoi email du snapshot + Rapport PDF hebdomadaire", "backlog_ref": "Iter34c+d",
     "duration_h": 0.5, "done": True,
     "details": "send_email() étendu pour pièces jointes multiples. Module health_report.py génère un PDF reportlab (charte SAWALI). Bouton 'Aperçu PDF' dans /admin/settings."},
    {"code": "ACT-0011", "created_at": "2026-05-10T19:00:00+00:00", "done_at": "2026-05-10T19:30:00+00:00",
     "title": "Tendance 30 jours + WoW arrows dans le rapport PDF", "backlog_ref": "Iter34e+f",
     "duration_h": 0.5, "done": True,
     "details": "3 sparklines (contacts/RDV/WA) via reportlab LinePlot. Comparaison Semaine vs S-1 avec arrows ↑↓= colorés sur 7 KPIs."},
    {"code": "ACT-0012", "created_at": "2026-05-10T19:30:00+00:00", "done_at": "2026-05-10T20:00:00+00:00",
     "title": "KPI 'Connexions & pages visitées' dans /admin/usage", "backlog_ref": "Iter34f",
     "duration_h": 0.5, "done": True,
     "details": "GET /api/admin/user-activity avec filtres période + société. UserActivityCard avec 3 mini-KPIs + 2 tables (derniers logins, top pages)."},
    {"code": "ACT-0013", "created_at": "2026-05-10T20:00:00+00:00", "done_at": "2026-05-10T20:30:00+00:00",
     "title": "Carte de chaleur 7×24 (Lun-Dim × 0h-23h)", "backlog_ref": "Iter34g",
     "duration_h": 0.5, "done": True,
     "details": "GET /api/admin/user-activity/heatmap. Frontend ActivityHeatmap (cellules cliquables, tooltips). Rendu PDF avec coloration RGB pré-mélangée."},
    {"code": "ACT-0014", "created_at": "2026-05-10T20:30:00+00:00", "done_at": "2026-05-10T20:45:00+00:00",
     "title": "Bug fix: Jauge support invisible sur mobile", "backlog_ref": "Iter34g",
     "duration_h": 0.25, "done": True,
     "details": "Cause: `hidden md:block` dans MarketingNav.jsx. Fix: gauge inline compacte sur mobile avec label tronqué."},
    {"code": "ACT-0015", "created_at": "2026-05-10T21:00:00+00:00", "done_at": "2026-05-10T21:30:00+00:00",
     "title": "Suivi des actions (Roadmap tracker) dans /admin/settings", "backlog_ref": "Iter34h",
     "duration_h": 0.5, "done": True,
     "details": "Nouvelle collection db.roadmap_actions + 2 endpoints (GET liste, PATCH observations). UI tableau dans /admin/settings filtrable avec numéro auto, dates, durée, coût estimé, observations éditables admin."},
    {"code": "ACT-0016", "created_at": "2026-05-10T21:30:00+00:00", "done_at": "2026-05-10T21:45:00+00:00",
     "title": "Bug fix RGPD: SMS/WhatsApp envoyaient le numéro masqué", "backlog_ref": "Iter34h",
     "duration_h": 0.25, "done": True,
     "details": "Helper _resolve_real_phone(contact_id, field) restaure le numéro réel depuis la DB au moment de l'envoi. Appliqué à /me/whatsapp/send, /me/whatsapp/send-text, /me/sms/send."},
    {"code": "ACT-0017", "created_at": "2026-05-10T22:00:00+00:00", "done_at": "2026-05-10T22:10:00+00:00",
     "title": "Export CSV du Suivi des actions", "backlog_ref": "Iter34i",
     "duration_h": 0.2, "done": True,
     "details": "Bouton 'Exporter CSV' avec séparateur `;` + BOM UTF-8 (Excel-FR friendly). Échappement RFC 4180. Filename auto-daté."},
    {"code": "ACT-0018", "created_at": "2026-05-10T22:10:00+00:00", "done_at": "2026-05-10T22:25:00+00:00",
     "title": "Création/Toggle/Suppression d'actions depuis l'UI admin", "backlog_ref": "Iter34i",
     "duration_h": 0.4, "done": True,
     "details": "POST /api/admin/roadmap-actions (création auto-numérotée). PATCH étendu pour toggler `done` (auto-rempli `done_at`). DELETE protège les 16 entrées du seed historique."},
    {"code": "ACT-0019", "created_at": "2026-05-10T22:25:00+00:00", "done_at": "2026-05-10T22:30:00+00:00",
     "title": "Version auto-bumpée depuis le compteur d'actions livrées", "backlog_ref": "Iter34i",
     "duration_h": 0.15, "done": True,
     "details": "Endpoint /api/version calcule désormais `1.<N>` où N = nombre d'actions roadmap réalisées. Visible en bas-gauche de chaque page via VersionStamp."},
    {"code": "ACT-0020", "created_at": "2026-05-10T22:30:00+00:00", "done_at": "2026-05-10T22:40:00+00:00",
     "title": "Bouton 'Réinitialiser' dans Usage & Facturation", "backlog_ref": "Iter34i",
     "duration_h": 0.2, "done": True,
     "details": "Bouton avec panneau de confirmation : mode 'Mettre à 0' (offset, données conservées) ou 'Purge complète' (suppression définitive des visits + access_logs). Confirm fort en cas de purge."},
    {"code": "ACT-0021", "created_at": "2026-05-10T22:45:00+00:00", "done_at": "2026-05-10T23:10:00+00:00",
     "title": "Vue Kanban (À faire / En cours / Réalisée)", "backlog_ref": "Iter34j",
     "duration_h": 0.5, "done": True,
     "details": "Nouveau champ `status` (todo|in_progress|done) sur roadmap_actions, backfill auto. Vue Kanban click-to-move 3 colonnes. Switcher Tableau/Kanban. Cartes avec code+titre+backlog+durée+coût+boutons déplacer."},
    {"code": "ACT-0022", "created_at": "2026-05-10T23:15:00+00:00", "done_at": "2026-05-10T23:35:00+00:00",
     "title": "Page 'Mon compte' (informations utilisateur lecture seule)", "backlog_ref": "Iter34k",
     "duration_h": 0.5, "done": True,
     "details": "Endpoints /me/account-detail (identity+parent_client+last_seen+counters Rapports/Suivis/Contacts) + /me/profile-update-request. Page /portal/my-account cliquable depuis le profil dans la sidebar. Lecture seule avec icône cadenas + formulaire de demande de modification à l'admin (checkboxes des champs + message)."},
    {"code": "ACT-0024", "created_at": "2026-05-10T23:45:00+00:00", "done_at": "2026-05-11T00:30:00+00:00",
     "title": "Admin UI — Demandes de modification de profil (utilisateurs)", "backlog_ref": "Iter34l",
     "duration_h": 0.75, "done": True,
     "details": "Endpoints GET/PATCH /admin/profile-requests (filtres pending/processed/all, note interne, marquer traitée/rouvrir). Section dédiée dans /admin/settings avec badge 'X en attente' + filtres + note admin. Compteur `admin_profile_requests` ajouté à /me/notifications/counts → badge sur le lien Paramètres du sidebar (clear automatique quand pending=0). 7 tests pytest verts."},
    {"code": "ACT-0025", "created_at": "2026-05-11T00:30:00+00:00", "done_at": "2026-05-11T01:15:00+00:00",
     "title": "Bug fix — Détection & réparation du pointeur parent_client_id périmé", "backlog_ref": "Iter34m",
     "duration_h": 0.75, "done": True,
     "details": "Cas rabo.f@sawalismartsystems.com : `company` typé 'SAWALI SMART SYSTEMS' mais `parent_client_id` pointait encore vers 'Clinique CMCO'. Le diagnostic disait 'Aucun désalignement' car il faisait confiance au parent_client_id. Fix: cross-check de la company du parent vs typed company → bascule sur la company typée si admin canonical trouvé, nouvelle action `relink_parent`, exposé en UI dans /admin/settings (alert rose + ligne dans le plan de réalignement). 2 tests E2E pytest verts."},
    {"code": "ACT-0026", "created_at": "2026-05-11T01:20:00+00:00", "done_at": "2026-05-11T02:00:00+00:00",
     "title": "Garde-fou auto-realign quand `company` change dans /admin/clients", "backlog_ref": "Iter34n",
     "duration_h": 0.5, "done": True,
     "details": "PUT /admin/clients/{id} détecte les changements de `company` et déclenche en arrière-plan la même logique que /admin/realign-user-to-client (relink_parent + retag rows + set client_id). Le payload de réponse expose `auto_realign: {applied, to_company, to_canonical_id, actions_count}` ou `{applied:false, reason:'no_canonical_for_company'}` quand la société typée ne matche aucun admin/primaire. Frontend AdminClients.jsx affiche un toast vert succès ou un toast warning explicite. 3 tests pytest verts (auto-fix, typo unresolvable, no-change-no-action)."},
    {"code": "ACT-0027", "created_at": "2026-05-11T08:30:00+00:00", "done_at": "2026-05-11T09:30:00+00:00",
     "title": "Bug fix critique — Retag trop large + endpoint de restauration + auto-scroll chat", "backlog_ref": "Iter34o",
     "duration_h": 1.0, "done": True,
     "details": "ROOT CAUSE: le retag de iter34m/n bougeait toutes les rows partageant client_id=old_scope (ex: tous les contacts CMCO migraient vers SAWALI quand on alignait rabo.f). FIX prospectif: filtrage owner_id/sender_id/created_by/author_id/user_id → seules les rows démontrablement appartenant à l'utilisateur réaligné bougent. FIX rétroactif: nouvel endpoint POST /admin/contacts/revert-retag (dry-run + apply, idempotent, filtres from/to/collections, restaure users.parent_client_id_legacy aussi). UI: section dédiée dans /admin/settings (cases à cocher par collection, aperçu avant action). BONUS UX: la fenêtre de discussion WhatsApp dans /portal/contacts auto-scrolle désormais sur le dernier message (initial 'auto', suivants 'smooth'). 4 tests pytest verts (retag owner-scoped, dry-run, apply+idempotent, from-filter)."},
    {"code": "ACT-0028", "created_at": "2026-05-11T10:00:00+00:00", "done_at": "2026-05-11T13:30:00+00:00",
     "title": "Visibilité cross-scope + Héritage RGPD + UI Centre Messagerie/Clients", "backlog_ref": "Iter34p",
     "duration_h": 2.5, "done": True,
     "details": "7 fixes en un seul shot. (1) Bug 'Contact introuvable' : /me/contacts/{cid}/messages, /me/contacts/{cid}/messages/mark-read, /me/whatsapp/unread et /me/sms/messages utilisent désormais _resolve_visible_client_ids (au lieu de client_scope seul). (2) Héritage RGPD : /me/features et _resolve_anon_flags utilisent désormais parent_client_id en priorité sur client_id. (3) Centre Messagerie: header affiche société + client lié dans des pills sky/emerald. (4) Centre Messagerie: colonne email réduite à 140px, mobile-only context phone passé en bleu. (5) Module Clients: endpoint /admin/clients inclut admin + moderateur (sauf SAWALI seed), UI groupée par rôle avec en-tête coloré. (6) Hover highlight (hover:bg-sky-50 + hover:ring-1 hover:ring-sky-200) sur lignes contacts, lignes clients et bulles de message. (7) Numéros de contact en text-sky-600 (téléphone + whatsapp). 3 tests pytest verts (admin_clients roles, cross-scope messages, RGPD inheritance via JWT forge)."},
    {"code": "ACT-0029", "created_at": "2026-05-11T14:00:00+00:00", "done_at": "2026-05-11T14:30:00+00:00",
     "title": "Filtres rapides par rôle avec compteurs dans le module Clients", "backlog_ref": "Iter34q",
     "duration_h": 0.5, "done": True,
     "details": "Pills cliquables au-dessus du tableau (Tous / Admins clients / Superviseurs / Clients / Modérateurs / Autres) avec compteurs en direct. Filtrage actif via useMemo + roleFilter state. Pills colorées (sky/amber/fuchsia/slate) selon le rôle, état actif distinct, hover. Compteurs respectent le scope visible (admin SAWALI seed exclu). Empty-state contextualisé quand filtre vide. UX inspirée des filtres GitHub Issues."},
    {"code": "ACT-0030", "created_at": "2026-05-11T15:00:00+00:00", "done_at": "2026-05-11T15:20:00+00:00",
     "title": "Filtres rapides 'Partagés/Privés/Non-lus' au Centre de Messagerie", "backlog_ref": "Iter34r",
     "duration_h": 0.3, "done": True,
     "details": "4 pills cliquables au-dessus du tableau Centre de Messagerie (Tous / Partagés équipe / Privés / Non-lus) avec compteurs vivants qui respectent les autres filtres (search + société). Couleurs slate/emerald/amber/rose par catégorie, état actif distinct (background fort), inactif (hover coloré subtil). Toggle 100% client-side via useMemo."},
    {"code": "ACT-0031", "created_at": "2026-05-11T16:00:00+00:00", "done_at": "2026-05-11T16:20:00+00:00",
     "title": "Raccourci SMART Communications sur 'Mon compte' + titres bleus des groupes Clients", "backlog_ref": "Iter34s",
     "duration_h": 0.3, "done": True,
     "details": "1) /portal/my-account : nouvelle carte 'SMART Communications' (admin/superviseur only) avec gradient fuchsia/sky, badge ADMIN, mène vers /admin/clients/{user.id}/features. Permet à l'admin SAWALI de paramétrer RGPD/WA/SMS/IA/paiements depuis sa propre fiche — réglages hérités par tous les utilisateurs liés (logique iter34p). 2) /admin/clients : les en-têtes de groupe (ADMINS CLIENTS, CLIENTS, etc.) passent en text-sawali-blue avec gradient sky-100 — bien plus visibles que le slate précédent."},
    {"code": "ACT-0032", "created_at": "2026-05-12T22:00:00+00:00", "done_at": "2026-05-12T23:00:00+00:00",
     "title": "Anonymisation des contenus + Exports contacts + Toasts live + Anti-doublon formulaires + Code en bleu", "backlog_ref": "Iter34tuvwx",
     "duration_h": 3.5, "done": True,
     "details": "6 demandes utilisateur livrées en parallèle. (#1) 3 nouveaux flags anon_rapports / anon_suivis / anon_communications avec helper _resolve_content_restrictions + enforcement sur me_list_notes, me_contact_messages, me_sms_messages. UI dans SMART Communications. (#2) Code unique contacts en font-bold + text-sky-600. (#3) Endpoints /me/contacts/export.{csv,json,pdf} + dropdown UI dans Contacts.jsx (ContactsExportMenu). (#4) Activity feed via polling : table activity_events + endpoint /me/recent-activity + hook useActivityFeedNotifier.js (toasts Sonner toutes les 8s pour Contact/Rapport/Suivi/SMS/WhatsApp, suppression auto des actions du viewer). (#5) Endpoint /me/forms/{form_id}/submissions-table + composant SubmissionsTable dans FormAnalyticsDetail (tableau brut visible + ligne hover sky). (#6) Endpoint /me/forms/title-suggestions + check 409 sur POST /me/forms et PUT /me/forms/{id} si nom dupliqué. UI : modal de création avec datalist autocomplete + détection live du conflit (bordure rose + message + bouton Créer désactivé). 31/31 tests iter34 verts."},
    {"code": "ACT-0033", "created_at": "2026-05-13T00:00:00+00:00", "done_at": "2026-05-13T00:30:00+00:00",
     "title": "Activity feed élargi (rdv/intervention/paiement) + Interventions UI (Client picker + voice note + filtre) + Filtre client Suivis", "backlog_ref": "Iter34y",
     "duration_h": 1.5, "done": True,
     "details": "Élargissement de l'activity feed iter34x: _log_activity wired aussi sur appointments.insert, interventions.insert/delete, payment_links.insert (kinds = appointment / intervention / payment), 3 nouveaux labels FR dans useActivityFeedNotifier. Page Interventions entièrement refondue: dropdown filtre dans l'en-tête de colonne Client lié (compteurs par client), colonne 'Note vocale' avec audio player inline, modal de création avec select Client lié (chargé depuis /me/clients) et nouveau composant VoiceNoteRecorder (MediaRecorder → /me/upload → voice_note_url). Models InterventionCreate/Update + UserNoteCreate/Update enrichis du champ voice_note_url. Page Suivis (UserNotes.jsx) reçoit un select 'Tous les clients liés' avec compteurs par client, useMemo filtré côté front. 31/31 tests iter34 verts maintenus."},
    {"code": "ACT-0034", "created_at": "2026-05-13T00:30:00+00:00", "done_at": "2026-05-13T00:45:00+00:00",
     "title": "Transcription automatique des notes vocales (Whisper)", "backlog_ref": "Iter34z",
     "duration_h": 0.25, "done": True,
     "details": "VoiceNoteRecorder appelle /transcribe (Whisper) automatiquement après l'upload réussi. Affiche un textarea éditable sous le lecteur audio + bouton 'Re-transcrire' (réutilise le blob en mémoire). Stockage du texte dans voice_note_transcript (ajouté aux models InterventionCreate/Update + UserNoteCreate/Update). Toast Info dégradé quand OpenAI non configuré (503) — la note vocale est sauvegardée quand même. Affichage du transcript en italique sur la liste des interventions sous le player (line-clamp-2 + tooltip)."},
]


async def _seed_roadmap_actions() -> int:
    """Insert any missing seed entries into db.roadmap_actions. Idempotent."""
    inserted = 0
    for entry in ROADMAP_SEED:
        existing = await db.roadmap_actions.find_one({"code": entry["code"]}, {"_id": 0, "code": 1})
        if existing:
            continue
        doc = {
            "id": _uuid(),
            "code": entry["code"],
            "created_at": entry["created_at"],
            "done_at": entry.get("done_at"),
            "title": entry["title"],
            "backlog_ref": entry.get("backlog_ref") or "",
            "details": entry.get("details") or "",
            "duration_h": float(entry.get("duration_h") or 0),
            "cost_xof": int(round(float(entry.get("duration_h") or 0) * DEFAULT_ROADMAP_HOURLY_RATE_XOF)),
            "done": bool(entry.get("done")),
            "status": "done" if entry.get("done") else "todo",
            "observations": "",
        }
        await db.roadmap_actions.insert_one(doc)
        inserted += 1
    return inserted


# ====================================================================
# Iter38f — Auto-sync of memory/CHANGELOG.md (MEMORY_DIR, lot 49) → db.roadmap_actions
# Each `## IterXXX (YYYY-MM-DD) — Title` block is scanned for `### …` h3
# headers. Substantive headers (skipping Tests/Frontend/Backend/etc.) are
# auto-inserted as roadmap actions with code `ACT-CL-<IterXXX>-<NN>`.
# Edits to titles/details propagate on next call. Manual ACT-XXXX entries
# from ROADMAP_SEED remain untouched.
# ====================================================================
_CHANGELOG_PATH = _MEMORY_DIR / "CHANGELOG.md"
_ITER_HEADER_RE = re.compile(
    r"^##\s+(Iter\S+)\s*\(([0-9]{4}-[0-9]{2}-[0-9]{2})\)\s*—\s*(.+)$",
    re.MULTILINE,
)
_H3_RE = re.compile(r"^###\s+(.+?)$", re.MULTILINE)
# H3 titles whose first significant word matches one of these are NOT real actions.
_SKIP_KEYWORDS = {
    "tests", "test", "frontend", "backend", "prochaine", "prochaines",
    "résumé", "summary", "note",
}
# H3 titles starting with one of these (after emoji removal) are noise.
_SKIP_PREFIXES = (
    "action utilisateur", "action requise",
    "p0", "p1", "p2", "p3",
    "🚨", "🟧", "🟨", "🟦",
)


def _strip_leading_emoji(s: str) -> str:
    """Remove leading non-word chars (emojis, bullets, etc.) so we can match the title text."""
    return re.sub(r"^[\W_]+", "", s, flags=re.UNICODE).strip()


def _should_skip_h3(title: str) -> bool:
    """Decide whether an h3 header is a real roadmap action or just a section header."""
    stripped = _strip_leading_emoji(title).lower()
    if not stripped or len(stripped) < 6:
        return True
    # Match first word against skip vocabulary (handles bare 'Frontend', 'Tests :', etc.)
    first_word = re.split(r"[\s:.,;—-]", stripped, 1)[0]
    if first_word in _SKIP_KEYWORDS:
        return True
    for prefix in _SKIP_PREFIXES:
        if stripped.startswith(prefix):
            return True
    return False


def _estimate_duration_h(details: str) -> float:
    """Iter38f — Estimate `duration_h` for auto-synced CHANGELOG entries.
    Heuristic based on details size (proxy for scope). Bounded 0.25..3.0h.
    Users can override via PATCH /admin/roadmap-actions/{code}.
    """
    n = len((details or "").strip())
    if n < 150:
        return 0.25
    if n < 350:
        return 0.5
    if n < 700:
        return 0.75
    if n < 1200:
        return 1.25
    if n < 1800:
        return 2.0
    return 3.0


async def _sync_roadmap_from_changelog() -> Dict[str, int]:
    """Parse CHANGELOG.md and upsert `ACT-CL-<iter>-<NN>` rows.
    Returns counts: {parsed, inserted, updated, deleted}. Idempotent — safe to call
    on every GET. Manual ACT-XXXX entries are never touched.
    """
    if not _CHANGELOG_PATH.exists():
        return {"parsed": 0, "inserted": 0, "updated": 0, "deleted": 0}
    try:
        content = _CHANGELOG_PATH.read_text(encoding="utf-8")
    except Exception:
        return {"parsed": 0, "inserted": 0, "updated": 0, "deleted": 0}

    iter_matches = list(_ITER_HEADER_RE.finditer(content))
    parsed = inserted = updated = deleted = 0
    seen_codes: set = set()

    for idx, m in enumerate(iter_matches):
        iter_name = m.group(1)            # "Iter38e"
        date_iso = m.group(2)             # "2026-05-27"
        block_start = m.end()
        block_end = iter_matches[idx + 1].start() if idx + 1 < len(iter_matches) else len(content)
        block = content[block_start:block_end]

        h3_matches = list(_H3_RE.finditer(block))
        action_num = 0
        for h_idx, h in enumerate(h3_matches):
            raw_title = h.group(1).strip()
            if _should_skip_h3(raw_title):
                continue
            action_num += 1
            parsed += 1
            clean_title = _strip_leading_emoji(raw_title)[:280]
            code = f"ACT-CL-{iter_name}-{action_num:02d}"
            seen_codes.add(code)
            d_start = h.end()
            d_end = h3_matches[h_idx + 1].start() if h_idx + 1 < len(h3_matches) else len(block)
            details_raw = block[d_start:d_end].strip()
            details = details_raw[:2000] + ("…" if len(details_raw) > 2000 else "")
            ts = f"{date_iso}T00:00:00+00:00"
            existing = await db.roadmap_actions.find_one(
                {"code": code},
                {"_id": 0, "title": 1, "details": 1, "backlog_ref": 1, "duration_h": 1, "cost_xof": 1},
            )
            est_h = _estimate_duration_h(details)
            est_xof = int(round(est_h * DEFAULT_ROADMAP_HOURLY_RATE_XOF))
            if existing:
                diffs: Dict[str, Any] = {}
                if existing.get("title") != clean_title:
                    diffs["title"] = clean_title
                if existing.get("details") != details:
                    diffs["details"] = details
                if existing.get("backlog_ref") != iter_name:
                    diffs["backlog_ref"] = iter_name
                # Backfill duration/cost when missing (or still 0 from earlier sync)
                if not existing.get("duration_h"):
                    diffs["duration_h"] = est_h
                    diffs["cost_xof"] = est_xof
                if diffs:
                    await db.roadmap_actions.update_one({"code": code}, {"$set": diffs})
                    updated += 1
                continue
            doc = {
                "id": _uuid(),
                "code": code,
                "created_at": ts,
                "done_at": ts,
                "title": clean_title,
                "backlog_ref": iter_name,
                "details": details,
                "duration_h": est_h,
                "cost_xof": est_xof,
                "done": True,
                "status": "done",
                "observations": "",
                "source": "changelog_auto",
            }
            await db.roadmap_actions.insert_one(doc)
            inserted += 1

    # Clean up orphan ACT-CL-* rows whose CHANGELOG block no longer produces them
    # (only when we successfully parsed something, to avoid wiping on transient parse errors)
    if parsed > 0:
        cursor = db.roadmap_actions.find(
            {"code": {"$regex": r"^ACT-CL-"}, "source": "changelog_auto"},
            {"_id": 0, "code": 1},
        )
        existing_codes = [r["code"] async for r in cursor]
        orphans = [c for c in existing_codes if c not in seen_codes]
        if orphans:
            res = await db.roadmap_actions.delete_many({"code": {"$in": orphans}})
            deleted = res.deleted_count
    return {"parsed": parsed, "inserted": inserted, "updated": updated, "deleted": deleted}



# Lot 72 — synchronisation de la roadmap déjà faite pour cette version de CHANGELOG.md (voir ci-dessous)
_ROADMAP_SYNCHRO: Dict[str, Any] = {}


@api.get("/admin/roadmap-actions", tags=["Admin"])
async def admin_list_roadmap_actions(_: dict = Depends(get_current_admin)):
    """Liste toutes les actions de la roadmap triées par code croissant. Initialisée au 1er appel.
    Iter34j: One-shot backfill of `status` for rows that pre-date the field.
    Iter38f: Auto-syncs CHANGELOG.md entries on every call (idempotent)."""
    # Lot 72 — la liste initiale et CHANGELOG.md ne changent qu'avec un déploiement : leur synchronisation
    # (des centaines de lectures une par une, ~6 s) n'est faite qu'une fois par démarrage du serveur, ou quand
    # CHANGELOG.md a changé (date de modification). Avant, elle était refaite à CHAQUE ouverture de la page.
    try:
        empreinte = _CHANGELOG_PATH.stat().st_mtime if _CHANGELOG_PATH.exists() else 0
    except OSError:
        empreinte = 0
    if _ROADMAP_SYNCHRO.get("empreinte") != empreinte:
        await _seed_roadmap_actions()
        # Iter38f — Auto-sync from /app/memory/CHANGELOG.md (best-effort, never blocks)
        try:
            await _sync_roadmap_from_changelog()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[roadmap] CHANGELOG auto-sync failed: %s", exc)
        # Iter34j backfill: rows without `status` get inferred from `done`
        try:
            await db.roadmap_actions.update_many({"status": {"$exists": False}, "done": True}, {"$set": {"status": "done"}})
            await db.roadmap_actions.update_many({"status": {"$exists": False}}, {"$set": {"status": "todo"}})
        except Exception:
            pass
        _ROADMAP_SYNCHRO["empreinte"] = empreinte
    items = [r async for r in db.roadmap_actions.find({}, {"_id": 0}).sort("code", 1)]
    total_h = sum(float(r.get("duration_h") or 0) for r in items if r.get("done"))
    total_xof = sum(int(r.get("cost_xof") or 0) for r in items if r.get("done"))
    return {
        "items": items,
        "totals": {
            "count": len(items),
            "done": sum(1 for r in items if r.get("status") == "done" or r.get("done")),
            "in_progress": sum(1 for r in items if r.get("status") == "in_progress"),
            "pending": sum(1 for r in items if (r.get("status") or "todo") == "todo" and not r.get("done")),
            "duration_h": round(total_h, 2),
            "cost_xof": total_xof,
            "hourly_rate_xof": DEFAULT_ROADMAP_HOURLY_RATE_XOF,
        },
    }


@api.patch("/admin/roadmap-actions/{code}", tags=["Admin"])
async def admin_patch_roadmap_action(code: str, payload: Dict[str, Any] = Body(...), _: dict = Depends(get_current_admin)):
    """Admins can edit `observations`, `done`/`status`, and (for their own
    pending actions) `title`, `backlog_ref`, `details`, `duration_h`.

    Iter34j: `status` field supports the Kanban view: "todo" | "in_progress"
    | "done". `done` boolean is kept in sync for backward compat. Setting
    `status=done` flips `done=true` and stamps `done_at`."""
    update: Dict[str, Any] = {}
    if "observations" in payload:
        update["observations"] = (payload.get("observations") or "")[:2000]
    if "title" in payload:
        update["title"] = (payload.get("title") or "").strip()[:200]
    if "backlog_ref" in payload:
        update["backlog_ref"] = (payload.get("backlog_ref") or "").strip()[:100]
    if "details" in payload:
        update["details"] = (payload.get("details") or "").strip()[:1000]
    if "duration_h" in payload:
        try:
            duration_h = max(0.0, float(payload["duration_h"]))
        except Exception:
            raise HTTPException(status_code=400, detail="duration_h invalide")
        update["duration_h"] = duration_h
        update["cost_xof"] = int(round(duration_h * DEFAULT_ROADMAP_HOURLY_RATE_XOF))
    existing = await db.roadmap_actions.find_one({"code": code}, {"_id": 0, "done": 1, "done_at": 1, "status": 1})
    if "status" in payload:
        status = (payload.get("status") or "").strip().lower()
        if status not in ("todo", "in_progress", "done"):
            raise HTTPException(status_code=400, detail="status invalide (todo|in_progress|done)")
        update["status"] = status
        if status == "done":
            update["done"] = True
            if not existing or not existing.get("done_at"):
                update["done_at"] = _now()
        else:
            update["done"] = False
            update["done_at"] = None
    elif "done" in payload:
        new_done = bool(payload["done"])
        update["done"] = new_done
        update["status"] = "done" if new_done else "todo"
        if new_done and (not existing or not existing.get("done_at")):
            update["done_at"] = _now()
        elif not new_done:
            update["done_at"] = None
    if not update:
        raise HTTPException(status_code=400, detail="Aucun champ modifiable fourni")
    update["updated_at"] = _now()
    res = await db.roadmap_actions.update_one({"code": code}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Action introuvable")
    item = await db.roadmap_actions.find_one({"code": code}, {"_id": 0})
    return item


def _next_roadmap_code(existing_codes: List[str]) -> str:
    """Compute the next sequential `ACT-####` based on the maximum existing
    numeric suffix. New entries always start with 'ACT-' to remain sortable
    alphabetically with the seed."""
    max_n = 0
    for c in existing_codes:
        try:
            n = int((c or "").split("-")[-1])
            if n > max_n:
                max_n = n
        except Exception:
            continue
    return f"ACT-{max_n + 1:04d}"


@api.post("/admin/roadmap-actions", tags=["Admin"])
async def admin_create_roadmap_action(payload: Dict[str, Any] = Body(...), _: dict = Depends(get_current_admin)):
    """Admin-driven creation of a pending action. Auto-numbered. Default
    `done=False`; can be flipped via the existing PATCH endpoint when
    delivered."""
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Le titre est obligatoire")
    await _seed_roadmap_actions()
    existing_codes = await db.roadmap_actions.distinct("code")
    code = _next_roadmap_code(existing_codes)
    duration_h = 0.0
    try:
        duration_h = max(0.0, float(payload.get("duration_h") or 0))
    except Exception:
        duration_h = 0.0
    done = bool(payload.get("done"))
    status = (payload.get("status") or ("done" if done else "todo")).lower()
    if status not in ("todo", "in_progress", "done"):
        status = "todo"
    if status == "done":
        done = True
    doc = {
        "id": _uuid(),
        "code": code,
        "created_at": _now(),
        "done_at": _now() if done else None,
        "title": title[:200],
        "backlog_ref": (payload.get("backlog_ref") or "").strip()[:100],
        "details": (payload.get("details") or "").strip()[:1000],
        "duration_h": duration_h,
        "cost_xof": int(round(duration_h * DEFAULT_ROADMAP_HOURLY_RATE_XOF)),
        "done": done,
        "status": status,
        "observations": "",
    }
    await db.roadmap_actions.insert_one(doc)
    out = dict(doc)
    out.pop("_id", None)
    return out


@api.delete("/admin/roadmap-actions/{code}", tags=["Admin"])
async def admin_delete_roadmap_action(code: str, _: dict = Depends(get_current_admin)):
    """Only admin-created (non-seed) entries can be deleted to keep the
    historical log intact. Seed entries start with ACT-0001..ACT-0016 and are
    protected — admins can edit them but not delete."""
    seed_codes = {e["code"] for e in ROADMAP_SEED}
    if code in seed_codes:
        raise HTTPException(status_code=403, detail="Les actions du seed historique ne peuvent pas être supprimées")
    res = await db.roadmap_actions.delete_one({"code": code})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Action introuvable")
    return {"ok": True, "code": code}




async def _dispatch_snapshot_import_recap(
    summary: dict,
    *,
    mode: str,
    comment: str,
    source_filename: Optional[str],
    size_bytes: int,
    user: dict,
) -> dict:
    """Iter35c — Send a recap of a snapshot import to the admin by email
    and (best-effort) WhatsApp. Returns {email: {...}, whatsapp: {...}}.

    Email is mandatory if SMTP is configured. WhatsApp uses `_wa_send_text`,
    which only works inside Meta's 24h customer service window — we attempt
    it anyway and capture the error in the result so the UI can show
    "WA non disponible (fenêtre 24h)" instead of failing the whole call.
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    # Build the summary table -- ignore unchanged collections (incoming=0 and before=0)
    rows = []
    total_after = 0
    total_before = 0
    total_incoming = 0
    has_error = False
    error_lines: List[str] = []
    for name, info in (summary or {}).items():
        before = info.get("before") if info.get("before") is not None else 0
        after = info.get("after") if info.get("after") is not None else before
        incoming = info.get("incoming") or 0
        action = info.get("action") or "?"
        if action == "error":
            has_error = True
            error_lines.append(f"{name}: {info.get('error', 'erreur')}")
        if incoming == 0 and (before or 0) == 0 and action not in ("error",):
            continue
        rows.append({"name": name, "before": before, "after": after, "incoming": incoming, "action": action})
        total_after += (after or 0)
        total_before += (before or 0)
        total_incoming += incoming
    rows.sort(key=lambda r: r["name"])

    when_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    actor = user.get("email") or user.get("full_name") or "Admin"
    headline = (
        "✅ Import de snapshot appliqué"
        if not has_error
        else "⚠️ Import de snapshot terminé AVEC ERREURS"
    )

    # ---------- Email body ----------
    table_rows = "".join(
        f"<tr><td style='padding:4px 8px;border:1px solid #E2E8F0;font-family:monospace;'>{r['name']}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>{r['before']}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>{r['after']}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>{r['incoming']}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;'>{r['action']}</td></tr>"
        for r in rows
    ) or "<tr><td colspan='5' style='padding:8px;color:#94A3B8;text-align:center;'>Aucune collection impactée</td></tr>"
    errors_html = ""
    if error_lines:
        errors_html = (
            "<p style='color:#B91C1C;font-weight:600;margin-top:12px;'>Erreurs rencontrées :</p>"
            f"<ul style='color:#7F1D1D;'>{''.join(f'<li><code>{e}</code></li>' for e in error_lines[:10])}</ul>"
        )
    html = (
        f"<div style='font-family:Arial,sans-serif;max-width:720px;'>"
        f"<h3 style='color:{'#16A34A' if not has_error else '#D97706'};margin-bottom:8px;'>{headline}</h3>"
        f"<p style='margin:4px 0;color:#475569;'>Effectué le <b>{when_str}</b> par <b>{actor}</b>.</p>"
        f"<p style='margin:4px 0;color:#475569;'>Fichier : <code>{source_filename or '—'}</code> "
        f"({(size_bytes / 1024):.1f} Ko) · Mode : <b>{mode}</b>" +
        (f" · Commentaire : <i>{comment}</i>" if (comment or '').strip() else "") +
        f"</p>"
        f"<table style='border-collapse:collapse;margin-top:8px;font-size:13px;'>"
        f"<thead style='background:#F1F5F9;'><tr>"
        f"<th style='padding:4px 8px;border:1px solid #E2E8F0;text-align:left;'>Collection</th>"
        f"<th style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>Avant</th>"
        f"<th style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>Après</th>"
        f"<th style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>Entrants</th>"
        f"<th style='padding:4px 8px;border:1px solid #E2E8F0;text-align:left;'>Action</th>"
        f"</tr></thead><tbody>{table_rows}</tbody>"
        f"<tfoot style='background:#F8FAFC;font-weight:bold;'>"
        f"<tr><td style='padding:4px 8px;border:1px solid #E2E8F0;'>TOTAL</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>{total_before}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>{total_after}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>{total_incoming}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;'>—</td></tr></tfoot>"
        f"</table>"
        f"{errors_html}"
        f"<p style='color:#64748B;font-size:12px;margin-top:16px;'>Notification automatique — SAWALI Smart Systems CRM.</p>"
        f"</div>"
    )
    text = (
        f"{headline}\n"
        f"Effectué le {when_str} par {actor}.\n"
        f"Fichier {source_filename or '—'} ({(size_bytes / 1024):.1f} Ko) · mode={mode}"
        + (f" · commentaire={comment}" if (comment or '').strip() else "")
        + f"\n\nCollections impactées ({len(rows)}):\n"
        + "\n".join(f"  • {r['name']}: {r['before']}→{r['after']} (entrants {r['incoming']}, {r['action']})" for r in rows[:20])
        + (f"\n\nErreurs:\n" + "\n".join(f"  ! {e}" for e in error_lines[:10]) if error_lines else "")
    )

    # ---------- Send email ----------
    email_recipient = (s.get("auto_snapshot_email_to") or s.get("health_email_to") or SUPER_ADMIN_EMAIL or "").strip().lower()
    email_status: Dict[str, Any] = {"to": email_recipient, "sent": False, "error": None}
    if email_recipient and "@" in email_recipient:
        try:
            from email_service import send_email
            sent = await send_email(
                email_recipient,
                f"[SAWALI] {headline} ({len(rows)} collection(s))",
                html,
                text,
            )
            email_status["sent"] = bool(sent)
            if not sent:
                email_status["error"] = "send_email retourne False (SMTP non configuré ?)"
        except Exception as exc:  # noqa: BLE001
            email_status["error"] = str(exc)[:200]
            logger.warning("snapshot import recap email failed: %s", exc)
    else:
        email_status["error"] = "Aucune adresse destinataire configurée"

    # ---------- Send WhatsApp recap (best effort) ----------
    wa_status: Dict[str, Any] = {"attempts": [], "any_sent": False}
    wa_recipients_raw = s.get("liluvine_remote_admin_phones") or []
    if not wa_recipients_raw and s.get("company_whatsapp"):
        wa_recipients_raw = [s.get("company_whatsapp")]
    # Dedup & normalize
    seen_set = set()
    wa_recipients: List[str] = []
    for p in wa_recipients_raw:
        digits = "".join(ch for ch in (p or "") if ch.isdigit())
        if digits and digits not in seen_set:
            seen_set.add(digits)
            wa_recipients.append(digits)

    if wa_recipients:
        wa_text = (
            f"{headline}\n"
            f"{when_str} · par {actor}\n"
            f"Fichier: {source_filename or '—'} ({(size_bytes / 1024):.0f} Ko)\n"
            f"Mode: {mode} · {len(rows)} collection(s) impactée(s)\n"
            f"Total: {total_before} → {total_after} (entrants {total_incoming})"
            + (f"\n⚠️ {len(error_lines)} erreur(s)" if error_lines else "")
        )
        for phone in wa_recipients[:5]:  # cap at 5 admins
            try:
                wr = await _wa_send_text(phone, wa_text)
                wa_status["attempts"].append({
                    "to": phone,
                    "ok": bool(wr.get("ok")),
                    "error": wr.get("error") if not wr.get("ok") else None,
                })
                if wr.get("ok"):
                    wa_status["any_sent"] = True
            except Exception as exc:  # noqa: BLE001
                wa_status["attempts"].append({"to": phone, "ok": False, "error": str(exc)[:200]})
    else:
        wa_status["error"] = "Aucun numéro admin WhatsApp configuré (Paramètres → Liluvine)"

    return {"email": email_status, "whatsapp": wa_status, "has_error": has_error, "rows_count": len(rows)}



@api.post("/admin/snapshots/import", tags=["Admin"])
async def admin_import_snapshot(
    file: UploadFile = File(...),
    mode: str = Form("replace"),
    dry_run: str = Form("false"),
    comment: str = Form(""),
    user: dict = Depends(get_current_admin),
):
    """Importe un fichier instantané. mode = 'replace' | 'merge'. dry_run='true' pour
    preview what would happen. Always logs into db.db_snapshots with
    kind='import'.

    Iter35c — on a non-dry-run import, also dispatches a recap notification
    by email and (best-effort) WhatsApp to the admin, with the per-collection
    summary table and a global success/error headline."""
    if mode not in ("replace", "merge"):
        raise HTTPException(status_code=400, detail="mode doit être 'replace' ou 'merge'")
    is_dry = str(dry_run).lower() in ("1", "true", "yes", "on")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Fichier vide")
    # Try gzip then plain JSON
    try:
        if file.filename and file.filename.endswith(".gz"):
            data = gzip.decompress(raw)
        else:
            try:
                data = gzip.decompress(raw)
            except Exception:
                data = raw
        payload = json.loads(data.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Fichier invalide: {e}")
    if not isinstance(payload, dict) or "collections" not in payload:
        raise HTTPException(status_code=400, detail="Format de snapshot non reconnu")
    try:
        summary = await _apply_snapshot(payload, mode=mode, dry_run=is_dry)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("snapshot import crashed (dry_run=%s, mode=%s)", is_dry, mode)
        raise HTTPException(
            status_code=500,
            detail=f"Échec de l'importation: {str(exc)[:300]}",
        )
    # Persist an import log entry
    log = {
        "id": _uuid(),
        "kind": "import",
        "created_at": _now(),
        "author_id": user.get("id"),
        "author_email": user.get("email"),
        "comment": (comment or "").strip()[:500],
        "mode": mode,
        "dry_run": is_dry,
        "source_filename": file.filename,
        "size_bytes": len(raw),
        "summary": summary,
        "exported_at": payload.get("exported_at"),
    }
    await db.db_snapshot_imports.insert_one(dict(log))

    # Iter35c — on real imports only (not dry-run), notify admin by email + WA.
    notifications: Optional[Dict[str, Any]] = None
    if not is_dry:
        try:
            notifications = await _dispatch_snapshot_import_recap(
                summary,
                mode=mode,
                comment=(comment or "").strip(),
                source_filename=file.filename,
                size_bytes=len(raw),
                user=user,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("snapshot import recap dispatch failed: %s", exc)
            notifications = {"error": str(exc)[:200]}

    return {
        "ok": True,
        "dry_run": is_dry,
        "mode": mode,
        "summary": summary,
        "import_id": log["id"],
        "notifications": notifications,
    }


@api.get("/admin/snapshots/imports", tags=["Admin"])
async def admin_list_snapshot_imports(_: dict = Depends(get_current_admin)):
    docs = [r async for r in db.db_snapshot_imports.find({}, {"_id": 0}).sort("created_at", -1).limit(50)]
    return {"imports": docs, "count": len(docs)}


# ============================================================
# Iter35e — Secrets Vault.
#
# Why: when production has an incident (snapshot wipe, env reset, fresh
# install), the admin currently has to re-enter every API token by hand
# (WA, SMTP, SMS providers, PawaPay, OpenAI, Google…). The Vault solves
# this with an offline, password-encrypted bundle the admin can keep on
# their own device and restore in one click.
#
# Crypto: PBKDF2-HMAC-SHA256 (200k iterations) → AES-256-GCM. The output
# file is a JSON envelope:
#   { "v": 1, "alg": "AES-256-GCM/PBKDF2-SHA256-200k", "salt": b64, "nonce": b64, "ct": b64 }
# We never persist the password. We never persist the bundle on the server.
# ============================================================
# Allow-list of settings keys (a superset of SENSITIVE_SETTINGS_KEYS adds
# every other field that is awkward/painful to re-enter — Google client_id,
# Whatsapp WABA id, SMTP host, etc).
VAULT_KEYS = sorted(SENSITIVE_SETTINGS_KEYS | {
    # Iter35u — Public base URL (DB-backed override of the env var)
    "public_base_url",
    # WhatsApp Business (non-secret but needed)
    "wa_business_account_id", "wa_phone_number_id", "wa_app_id", "wa_default_language",
    # Iter38h — Meta App config (non-secret keys)
    "meta_app_id", "meta_graph_version", "meta_redirect_uri",
    # SMTP (smtp_password is already in sensitive, add the rest)
    "smtp_host", "smtp_port", "smtp_user", "smtp_from_email", "smtp_from_name", "smtp_use_tls",
    # Iter38r-fix9k — KB OCR cost controls
    "kb_ocr_xof_per_page", "kb_ocr_xof_monthly_cap", "kb_ocr_pdf_max_pages",
    "notes_strict_tasks_only",
    # Iter38r-fix9l — Bonus pack settings (WA tasks, Liluvine digest, GDPR)
    "wa_tasks_digest_enabled",
    "liluvine_weekly_digest_enabled",
    "gdpr_auto_anonymize_enabled",
    "gdpr_contact_inactive_months",
    "gdpr_msg_retention_months",
    "gdpr_log_retention_days",
    "public_base_url",
    # Google OAuth & calendar (non-secret IDs)
    "google_client_id", "google_calendar_email", "google_calendar_password_hint",
    # reCAPTCHA site key
    "recaptcha_site_key", "recaptcha_enabled",
    # Webhook urls (the secret is the token/pass)
    "webhook_base_url", "webhook_auth_type", "webhook_basic_user",
    "notes_webhook_url", "notes_webhook_auth_type", "notes_webhook_basic_user",
    "health_webhook_url", "health_webhook_auth_type", "health_webhook_basic_user",
    "n8n_webhook_url", "n8n_webhook_auth_type", "n8n_webhook_basic_user",
    # SMS providers — URLs + auth types + senders
    "sms_orange_enabled", "sms_orange_url", "sms_orange_method", "sms_orange_auth_type",
    "sms_orange_basic_user", "sms_orange_header_name", "sms_orange_sender",
    "sms_orange_oauth_url", "sms_orange_client_id", "sms_orange_sender_msisdn",  # Iter35i
    "sms_moov_enabled", "sms_moov_url", "sms_moov_method", "sms_moov_auth_type",
    "sms_moov_basic_user", "sms_moov_header_name", "sms_moov_sender",
    "sms_moov_oauth_url", "sms_moov_client_id", "sms_moov_sender_msisdn",
    "sms_telecel_enabled", "sms_telecel_url", "sms_telecel_method", "sms_telecel_auth_type",
    "sms_telecel_basic_user", "sms_telecel_header_name", "sms_telecel_sender",
    "sms_telecel_oauth_url", "sms_telecel_client_id", "sms_telecel_sender_msisdn",
    "sms_ovh_enabled", "sms_ovh_application_key", "sms_ovh_service_name", "sms_ovh_sender",
    # Iter43-fix23b — Bird.com (non-sensitive metadata)
    "bird_enabled", "bird_api_base_url", "bird_workspace_id", "bird_channel_id",
    "bird_default_sender", "bird_signature", "bird_use_liluvine",
    "bird_cost_per_sms_xof", "bird_cost_currency",
    "public_base_url",
    # PawaPay
    "pawapay_environment", "pawapay_api_token_sandbox", "pawapay_api_token_production",
    "pawapay_callback_secret", "pawapay_default_country",
    # OpenAI
    "openai_whisper_model", "openai_chat_model", "ai_summary_provider",
    # Tracking
    "tracking_base_url", "tracking_endpoint",
    # Agenda / Liluvine
    "agenda_n8n_outbound_token", "agenda_n8n_outbound_basic_pass", "agenda_n8n_inbound_secret",
    "support_load_webhook_secret", "liluvine_remote_secret", "liluvine_remote_admin_phones",
    # Iter38r-fix7 — Liluvine PRO branding (per-tenant theming)
    "liluvine_pro_name", "liluvine_pro_avatar_url", "liluvine_pro_color",
    "liluvine_pro_n8n_outbound_url", "liluvine_pro_n8n_outbound_token",
    "liluvine_pro_inbound_secret",
})


def _vault_encrypt(plaintext: bytes, password: str) -> dict:
    """Encrypt the plaintext bundle with a user-chosen password.
    Uses PBKDF2-HMAC-SHA256 (200k iterations) for key derivation, then
    AES-256-GCM for authenticated encryption."""
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import base64
    import os as _os

    if not password or len(password) < 8:
        raise HTTPException(status_code=400, detail="Le mot de passe doit faire au moins 8 caractères")
    salt = _os.urandom(16)
    nonce = _os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    key = kdf.derive(password.encode("utf-8"))
    aes = AESGCM(key)
    ct = aes.encrypt(nonce, plaintext, associated_data=b"sawali-vault-v1")
    return {
        "v": 1,
        "alg": "AES-256-GCM/PBKDF2-SHA256-200k",
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ct).decode("ascii"),
        "created_at": _now(),
    }


def _vault_decrypt(envelope: dict, password: str) -> bytes:
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
    import base64

    if not isinstance(envelope, dict) or "ct" not in envelope or envelope.get("v") != 1:
        raise HTTPException(status_code=400, detail="Format de coffre-fort non reconnu")
    try:
        salt = base64.b64decode(envelope["salt"])
        nonce = base64.b64decode(envelope["nonce"])
        ct = base64.b64decode(envelope["ct"])
    except Exception:
        raise HTTPException(status_code=400, detail="Format de coffre-fort corrompu")
    if not password:
        raise HTTPException(status_code=400, detail="Mot de passe requis")
    # AES-GCM requires nonce=12 bytes; validate up-front to give a clean
    # 400 instead of leaking a ValueError from the crypto lib.
    if len(nonce) != 12 or len(salt) < 8:
        raise HTTPException(status_code=400, detail="Coffre-fort altéré (champ salt/nonce invalide)")
    try:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
        key = kdf.derive(password.encode("utf-8"))
        aes = AESGCM(key)
        return aes.decrypt(nonce, ct, associated_data=b"sawali-vault-v1")
    except InvalidTag:
        raise HTTPException(status_code=400, detail="Mot de passe incorrect ou fichier altéré")
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Coffre-fort illisible: {exc}")


@api.get("/admin/secrets/keys", tags=["Admin"])
async def admin_list_vault_keys(_: dict = Depends(get_current_admin)):
    """Liste les clés de paramètres sauvegardées par le coffre, et lesquelles sont
    currently populated (without revealing values)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    out = []
    for k in VAULT_KEYS:
        v = s.get(k)
        if isinstance(v, bool):
            populated = True  # toggles are always meaningful
        elif isinstance(v, (int, float)):
            populated = v != 0
        elif isinstance(v, list):
            populated = len(v) > 0
        else:
            populated = bool((v or "").strip()) if isinstance(v, str) else (v is not None)
        out.append({"key": k, "populated": populated, "is_secret": k in SENSITIVE_SETTINGS_KEYS})
    out.sort(key=lambda x: (not x["populated"], x["key"]))
    return {"keys": out, "total": len(out), "populated": sum(1 for x in out if x["populated"])}


@api.post("/admin/secrets/export", tags=["Admin"])
async def admin_vault_export(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
    """Export an AES-256-GCM encrypted bundle of every vaultable setting.
    Body: {"password": str, "comment": str?}. Returns a JSON envelope the
    admin must download and store offline. Never persisted on the server."""
    password = (payload.get("password") or "").strip()
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (8 caractères minimum)")
    s = await db.settings.find_one({"_id": "global"}) or {}
    bundle = {k: s.get(k) for k in VAULT_KEYS if k in s}
    plaintext = json.dumps({
        "kind": "sawali-secrets-vault",
        "version": 1,
        "exported_at": _now(),
        "exported_by": user.get("email"),
        "comment": (payload.get("comment") or "").strip()[:200],
        "settings": bundle,
    }, ensure_ascii=False, default=_json_default).encode("utf-8")
    envelope = _vault_encrypt(plaintext, password)
    # Audit log (no secrets!)
    try:
        await db.vault_audit.insert_one({
            "id": _uuid(),
            "action": "export",
            "created_at": _now(),
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "keys_count": len(bundle),
            "comment": (payload.get("comment") or "").strip()[:200],
        })
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "envelope": envelope,
        "filename": f"sawali-vault-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json",
        "keys_count": len(bundle),
    }


@api.post("/admin/secrets/import", tags=["Admin"])
async def admin_vault_import(
    file: UploadFile = File(...),
    password: str = Form(...),
    dry_run: str = Form("false"),
    overwrite_filled: str = Form("false"),
    user: dict = Depends(get_current_admin),
):
    """Restore a previously-exported vault.
    - dry_run=true : decrypt + return the list of keys that would be
      restored (without applying them).
    - dry_run=false : apply.
    - overwrite_filled=false : only restore keys that are EMPTY in the
      current settings doc (safe default — never clobber a freshly typed
      value with an older one).
    - overwrite_filled=true : restore every key from the bundle."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Fichier vide")
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Fichier non parsable: {exc}")
    is_dry = str(dry_run).lower() in ("1", "true", "yes", "on")
    overwrite = str(overwrite_filled).lower() in ("1", "true", "yes", "on")
    plaintext = _vault_decrypt(envelope, password)
    try:
        bundle_doc = json.loads(plaintext.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Contenu déchiffré invalide")
    if bundle_doc.get("kind") != "sawali-secrets-vault":
        raise HTTPException(status_code=400, detail="Ce fichier ne semble pas être un coffre-fort SAWALI")
    incoming = bundle_doc.get("settings") or {}
    current = await db.settings.find_one({"_id": "global"}) or {}

    plan: List[Dict[str, Any]] = []
    update: Dict[str, Any] = {}
    for k in VAULT_KEYS:
        if k not in incoming:
            continue
        new_v = incoming[k]
        if new_v is None or new_v == "":
            continue
        old_v = current.get(k)
        was_filled = bool(old_v) if not isinstance(old_v, bool) else True
        will_apply = (not was_filled) or overwrite
        plan.append({
            "key": k,
            "was_filled": was_filled,
            "will_apply": will_apply,
            "is_secret": k in SENSITIVE_SETTINGS_KEYS,
        })
        if will_apply and not is_dry:
            update[k] = new_v

    if not is_dry and update:
        update["updated_at"] = _now()
        await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)

    try:
        await db.vault_audit.insert_one({
            "id": _uuid(),
            "action": "import_dry" if is_dry else "import",
            "created_at": _now(),
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "incoming_count": len(incoming),
            "applied_count": len(update),
            "overwrite_filled": overwrite,
            "bundle_exported_at": bundle_doc.get("exported_at"),
            "bundle_exported_by": bundle_doc.get("exported_by"),
        })
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": True,
        "dry_run": is_dry,
        "overwrite_filled": overwrite,
        "bundle_exported_at": bundle_doc.get("exported_at"),
        "bundle_exported_by": bundle_doc.get("exported_by"),
        "bundle_comment": bundle_doc.get("comment"),
        "incoming_count": len(incoming),
        "applied_count": len(update),
        "plan": plan,
    }


@api.get("/admin/secrets/audit", tags=["Admin"])
async def admin_vault_audit(_: dict = Depends(get_current_admin)):
    """Audit trail of every vault export/import action."""
    items = await db.vault_audit.find({}, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    return {"items": items, "count": len(items)}



# ============================================================
# iter30 — Per-user client-scope diagnostic & realignment.
#
# When two users belong to the same business client but see different sets of
# contacts, the root cause is almost always one of these:
#
#   1. Their `users.client_id` fields point to different values (mis-bridged)
#   2. Their contacts/messages were created under different `client_id` scopes
#   3. One user has no `parent_client_id` so iter28's auto-mirror didn't fire
#
# This endpoint accepts an email and returns:
#   • The user's full identity chain (id, role, parent_client_id, client_id,
#     tracked_user_id)
#   • The canonical client_id for that user (resolved via parent_client_id, or
#     by looking up another user with the same company name & admin role)
#   • A peer list (other users sharing the same canonical client_id)
#   • Per-user contact counts (each peer's visible scope)
#   • A realign plan: which fields/rows need to be retagged to put this user
#     in sync with the canonical scope
#
# Together with the POST sibling (`/admin/realign-user-to-client`) the admin
# can repair production without ad-hoc SQL.
# ============================================================
def _compte_demo(u: Dict[str, Any]) -> bool:
    """Lot 79.3 — compte de démonstration : jamais rattaché aux données d'une vraie entreprise."""
    email = str((u or {}).get("email") or "").lower()
    return (u or {}).get("role") == "demo" or bool((u or {}).get("is_demo")) or email.startswith("demo@") or email.startswith("demo.")


async def _premier_admin_entreprise(company: str) -> Optional[Dict[str, Any]]:
    """Lot 79.3 — premier compte admin/superviseur (hors démo) d'une entreprise, dans l'ordre de la base :
    c'est la racine commune utilisée à la fois par la détection et par le réalignement."""
    async for u in db.users.find(
        {"company": {"$regex": f"^\\s*{re.escape(company)}\\s*$", "$options": "i"},
         "role": {"$in": ["admin", "superviseur"]},
         "account_status": {"$nin": ["disabled", "deleted", "blocked"]}},
        {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1, "role": 1, "is_demo": 1},
    ):
        if not _compte_demo(u):
            return u
    return None


@api.get("/admin/client-data-diagnostic", tags=["Admin"])
async def admin_client_data_diagnostic(email: str, _: dict = Depends(get_current_admin)):
    email_norm = (email or "").strip().lower()
    if not email_norm:
        raise HTTPException(status_code=400, detail="Email requis")
    user = await db.users.find_one(
        {"email": {"$regex": f"^{re.escape(email_norm)}$", "$options": "i"}},
        {"_id": 0, "password_hash": 0},
    )
    if not user:
        raise HTTPException(status_code=404, detail=f"Utilisateur introuvable : {email_norm}")

    uid = user["id"]
    declared_client_id = user.get("client_id")
    parent_client_id = user.get("parent_client_id")
    company = (user.get("company") or "").strip()
    role = user.get("role")

    # Canonical client_id resolution priority:
    #   1) parent_client_id (set when this user was created via tracked-user bridge)
    #   2) For admin/superviseur users: their OWN id (they ARE the client root)
    #   3) Otherwise: look up another admin/superviseur with the same company name
    canonical: Optional[str] = None
    canonical_source = None
    canonical_user: Optional[dict] = None
    if parent_client_id:
        canonical = parent_client_id
        canonical_source = "parent_client_id"
    elif role in ("admin", "superviseur"):
        # Lot 79.3 — même règle que la détection (« Cohérence multi-utilisateurs ») : dans une entreprise qui a
        # plusieurs admins/superviseurs, la racine est le PREMIER d'entre eux ; les autres s'y rattachent.
        # Avant, chaque admin/superviseur était sa propre racine : « Tout réaligner » les ignorait.
        premier = await _premier_admin_entreprise(company) if company else None
        if premier and premier["id"] != uid:
            canonical = premier["id"]
            canonical_source = f"premier admin/superviseur de l'entreprise → {premier.get('email')}"
            canonical_user = premier
        else:
            canonical = uid
            canonical_source = "self (admin/superviseur)"
    elif company:
        # Find an admin or superviseur with the same company; case-insensitive trim
        same_company = await db.users.find_one(
            {
                "company": {"$regex": f"^\\s*{re.escape(company)}\\s*$", "$options": "i"},
                "role": {"$in": ["admin", "superviseur"]},
            },
            {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1},
        )
        if same_company:
            canonical = same_company["id"]
            canonical_source = f"company match → {same_company.get('email')}"
            canonical_user = same_company
    # Hydrate the canonical user if we have an id but didn't already fetch it
    if canonical and not canonical_user:
        canonical_user = await db.users.find_one(
            {"id": canonical},
            {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1, "role": 1},
        )

    # Iter34m — Stale-parent detection.
    # When an admin edits a user's `company` text without updating
    # `parent_client_id`, the pointer keeps anchoring them to the old client
    # (e.g. rabo.f@sawalismartsystems.com had company="SAWALI SMART SYSTEMS"
    # typed but parent_client_id still pointed to "Clinique CMCO"). The
    # original diagnostic trusted parent_client_id and reported "Aucun
    # désalignement détecté". Now we cross-check the canonical's company
    # against the user's typed company; if they differ, we try to recompute
    # the canonical via the typed company, override it, and emit a new
    # `relink_parent` action so the realign endpoint can patch
    # `parent_client_id` in addition to retagging rows.
    parent_company_mismatch = False
    parent_company_observed: Optional[str] = None
    typed_company_norm = company.lower().strip()
    if (
        canonical_source == "parent_client_id"
        and typed_company_norm
        and canonical_user
    ):
        parent_company_observed = (canonical_user.get("company") or "").strip() or None
        canonical_company_norm = (parent_company_observed or "").lower().strip()
        if canonical_company_norm and typed_company_norm != canonical_company_norm:
            # The typed company and the parent's company disagree — find a
            # better canonical anchor from the typed company (admin first,
            # then any user marked as primary client for that company).
            better = await db.users.find_one(
                {
                    "company": {"$regex": f"^\\s*{re.escape(company)}\\s*$", "$options": "i"},
                    "role": {"$in": ["admin", "superviseur"]},
                },
                {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1, "role": 1},
            )
            if not better:
                better = await db.users.find_one(
                    {
                        "company": {"$regex": f"^\\s*{re.escape(company)}\\s*$", "$options": "i"},
                        "is_primary_client": True,
                    },
                    {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1, "role": 1},
                )
            if better and better["id"] != canonical:
                parent_company_mismatch = True
                canonical = better["id"]
                canonical_source = f"company match (parent_client_id obsolète) → {better.get('email')}"
                canonical_user = better
                # Recompute peers under the corrected canonical
                # (the next block already walks db.users with the new canonical)
            else:
                # Surface the mismatch even when we cannot auto-fix it.
                parent_company_mismatch = True

    # Lot 79.4 — un compte rattaché (parent_client_id) à un AUTRE membre de la même entreprise suit lui aussi la
    # règle commune : la racine est le premier admin/superviseur de l'entreprise (comme dans la détection).
    # Sinon le réalignement s'arrêtait au parent (ex. un ancien compte de l'entreprise) et le compte restait
    # signalé « désaligné » indéfiniment. Le lien parent est alors corrigé (action relink_parent).
    if canonical_source == "parent_client_id" and company and not parent_company_mismatch:
        premier = await _premier_admin_entreprise(company)
        parent_meme_entreprise = (
            not canonical_user
            or (canonical_user.get("company") or "").strip().lower() == company.strip().lower()
        )
        if premier and premier["id"] != canonical and premier["id"] != uid and parent_meme_entreprise:
            parent_company_mismatch = True
            canonical = premier["id"]
            canonical_source = f"premier admin/superviseur de l'entreprise (parent mis à jour) → {premier.get('email')}"
            canonical_user = premier

    effective_scope = declared_client_id or uid

    # Peers — users that the canonical client_id should encompass
    peers: List[dict] = []
    if canonical:
        async for p in db.users.find(
            {
                "$or": [
                    {"id": canonical},
                    {"client_id": canonical},
                    {"parent_client_id": canonical},
                ],
            },
            {"_id": 0, "id": 1, "email": 1, "full_name": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
        ):
            # For each peer, count contacts they currently see (apply the
            # iter29 read rule: filter on their effective scope).
            peer_scope = p.get("client_id") or p["id"]
            peer_contacts = await db.directory_contacts.count_documents({"client_id": peer_scope})
            p["effective_scope"] = peer_scope
            p["scope_matches_canonical"] = (peer_scope == canonical)
            p["visible_contacts"] = peer_contacts
            peers.append(p)

    # Realign plan — what needs to change to put this user in sync
    realign_plan: Dict[str, Any] = {"needed": False, "actions": []}
    # Iter34m — first emit the relink_parent action when a stale parent
    # pointer was detected AND auto-resolved to a new canonical.
    if parent_company_mismatch and canonical and parent_client_id and parent_client_id != canonical:
        realign_plan["needed"] = True
        realign_plan["actions"].append({
            "type": "relink_parent",
            "user_id": uid,
            "from_parent": parent_client_id,
            "to_parent": canonical,
        })
    if canonical and canonical != effective_scope:
        realign_plan["needed"] = True
        # Action 1 — fix the user's own client_id field
        if declared_client_id != canonical:
            realign_plan["actions"].append({
                "type": "set_user_client_id",
                "from": declared_client_id,
                "to": canonical,
                "user_id": uid,
            })
        # Action 2 — count rows tagged under the wrong client_id that should be retagged.
        # Iter34o — CRITICAL: filter by owner_id/sender_id/etc. so we ONLY
        # move rows demonstrably owned by THIS user. Before this fix the
        # retag moved ALL rows at wrong_scope (e.g. all CMCO contacts when
        # realigning rabo.f), breaking the legitimate users of the source
        # client. The visible-scope bridge in _resolve_visible_client_ids
        # already handles cross-client visibility via company matching, so
        # we no longer need a wholesale retag.
        wrong_scope = effective_scope
        owner_filter: Dict[str, Any] = {"$or": [
            {"owner_id": uid},
            {"sender_id": uid},
            {"created_by": uid},
            {"author_id": uid},
            {"user_id": uid},
        ]}
        for coll in ["directory_contacts", "whatsapp_messages", "sms_messages",
                     "whatsapp_schedules", "payment_links"]:
            q: Dict[str, Any] = {"client_id": wrong_scope, **owner_filter}
            cnt = await db[coll].count_documents(q)
            if cnt > 0:
                realign_plan["actions"].append({
                    "type": "retag_rows",
                    "collection": coll,
                    "from": wrong_scope,
                    "to": canonical,
                    "count": cnt,
                    "owner_uid": uid,  # remembered so the apply step uses the same filter
                })

    return {
        "user": {
            "id": uid,
            "email": user.get("email"),
            "full_name": user.get("full_name"),
            "company": company,
            "role": role,
            "client_id": declared_client_id,
            "parent_client_id": parent_client_id,
            "tracked_user_id": user.get("tracked_user_id"),
            "effective_scope": effective_scope,
        },
        "canonical": {
            "client_id": canonical,
            "source": canonical_source,
            "user": canonical_user,
        },
        "parent_company_mismatch": parent_company_mismatch,
        "parent_company_observed": parent_company_observed,
        "peers": peers,
        "realign_plan": realign_plan,
    }


@api.post("/admin/realign-user-to-client", tags=["Admin"])
async def admin_realign_user_to_client(
    payload: Dict[str, Any] = Body(...),
    _: dict = Depends(get_current_admin),
):
    """Applique le realign_plan renvoyé par /admin/client-data-diagnostic.

    Body: ``{"email": "user@example.com", "dry_run": false}``.
    The endpoint re-runs the diagnostic, then applies the proposed actions
    atomically per collection: stamps `client_id` to the canonical value and
    keeps the previous one in `client_id_legacy` (for traceability).
    Idempotent.
    """
    email = (payload.get("email") or "").strip().lower()
    dry_run = bool(payload.get("dry_run"))
    if not email:
        raise HTTPException(status_code=400, detail="Email requis")
    diag = await admin_client_data_diagnostic(email=email, _={"role": "admin"})
    plan = diag["realign_plan"]
    if not plan["needed"]:
        return {"ok": True, "applied": False, "reason": "Aucun désalignement détecté"}
    if dry_run:
        return {"ok": True, "applied": False, "diagnostic": diag, "dry_run": True}

    applied: List[Dict[str, Any]] = []
    for action in plan["actions"]:
        if action["type"] == "set_user_client_id":
            await db.users.update_one(
                {"id": action["user_id"]},
                {"$set": {"client_id": action["to"], "client_id_legacy": action.get("from"),
                          "updated_at": _now()}},
            )
            applied.append(action)
        elif action["type"] == "relink_parent":
            # Iter34m — Stale-parent fix. Update parent_client_id and mirror
            # client_id to the new canonical so subsequent queries scope
            # correctly. Preserve the old value in *_legacy fields.
            await db.users.update_one(
                {"id": action["user_id"]},
                {"$set": {
                    "parent_client_id": action["to_parent"],
                    "parent_client_id_legacy": action.get("from_parent"),
                    "client_id": action["to_parent"],
                    "updated_at": _now(),
                }},
            )
            applied.append(action)
        elif action["type"] == "retag_rows":
            # Iter34o — Use the same owner_uid filter to scope the retag.
            owner_uid = action.get("owner_uid")
            base_q: Dict[str, Any] = {"client_id": action["from"], "client_id_legacy": {"$exists": False}}
            if owner_uid:
                base_q["$or"] = [
                    {"owner_id": owner_uid},
                    {"sender_id": owner_uid},
                    {"created_by": owner_uid},
                    {"author_id": owner_uid},
                    {"user_id": owner_uid},
                ]
            res = await db[action["collection"]].update_many(
                base_q,
                {"$set": {"client_id": action["to"], "client_id_legacy": action["from"]}},
            )
            applied.append({**action, "modified_count": int(getattr(res, "modified_count", 0) or 0)})

    return {"ok": True, "applied": True, "actions": applied, "diagnostic_after": await admin_client_data_diagnostic(email=email, _={"role": "admin"})}


# ============================================================
# Iter34o — Recovery endpoint for the over-broad retag bug.
# ----------------------------------------------------------
# Before iter34o the retag step moved every row at `client_id == old_scope`
# regardless of ownership. When the admin realigned rabo.f@SAWALI the
# entire CMCO contact base ended up tagged SAWALI. The original values are
# safely preserved in `client_id_legacy` — this endpoint restores them.
# ============================================================
@api.post("/admin/contacts/revert-retag", tags=["Admin"])
async def admin_revert_retag(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    _: dict = Depends(get_current_admin),
):
    """Restore `client_id ← client_id_legacy` on every row where the legacy
    field is set across all retag-affected collections.

    Body (all optional):
      • ``dry_run`` (bool, default true) — preview the counts without writing.
      • ``collections`` (list[str]) — limit to a specific subset (e.g. only
        ``directory_contacts``). Default: all five.
      • ``from_client_id`` (str) — restrict to rows previously tagged with this
        ``client_id_legacy`` value (case: only revert one client's data).
      • ``to_client_id`` (str) — restrict to rows currently tagged with this
        ``client_id`` (case: only revert what was moved into this canonical).

    Idempotent: once a row is reverted, the legacy field is deleted so a
    second run is a no-op.
    """
    payload = payload or {}
    dry_run = bool(payload.get("dry_run", True))
    requested = payload.get("collections")
    all_colls = ["directory_contacts", "whatsapp_messages", "sms_messages",
                 "whatsapp_schedules", "payment_links"]
    if requested:
        colls = [c for c in requested if c in all_colls]
        if not colls:
            raise HTTPException(status_code=400, detail=f"Aucune collection valide. Options: {all_colls}")
    else:
        colls = all_colls
    base_filter: Dict[str, Any] = {"client_id_legacy": {"$exists": True, "$nin": [None, ""]}}
    if payload.get("from_client_id"):
        base_filter["client_id_legacy"] = payload["from_client_id"]
    if payload.get("to_client_id"):
        base_filter["client_id"] = payload["to_client_id"]

    results: List[Dict[str, Any]] = []
    for coll in colls:
        cnt = await db[coll].count_documents(base_filter)
        action: Dict[str, Any] = {"collection": coll, "count": cnt}
        if not dry_run and cnt > 0:
            # Use the aggregation pipeline update form so we can use $unset
            # and copy a field value into another in a single pass.
            res = await db[coll].update_many(
                base_filter,
                [
                    {"$set": {"client_id": "$client_id_legacy"}},
                    {"$unset": "client_id_legacy"},
                ],
            )
            action["modified_count"] = int(getattr(res, "modified_count", 0) or 0)
        results.append(action)

    # Also revert users.parent_client_id_legacy + users.client_id_legacy when
    # present, so the user-pointer side of iter34m is also undone.
    user_filter: Dict[str, Any] = {"parent_client_id_legacy": {"$exists": True, "$nin": [None, ""]}}
    user_count = await db.users.count_documents(user_filter)
    user_action: Dict[str, Any] = {"collection": "users", "count": user_count}
    if not dry_run and user_count > 0:
        res = await db.users.update_many(
            user_filter,
            [
                {"$set": {"parent_client_id": "$parent_client_id_legacy"}},
                {"$unset": ["parent_client_id_legacy", "client_id_legacy"]},
            ],
        )
        user_action["modified_count"] = int(getattr(res, "modified_count", 0) or 0)
    results.append(user_action)

    return {
        "ok": True,
        "dry_run": dry_run,
        "filter": {k: str(v) if not isinstance(v, dict) else v for k, v in base_filter.items()},
        "results": results,
        "total_rows": sum(r["count"] for r in results),
    }


# ============================================================
# iter31 — Client-consistency canary
# ----------------------------------------------------------
# Scans every user grouped by their normalized `company` name and detects
# whether all members of a company share the same canonical client_id.
# A canonical client_id is determined as:
#   1) The id of an admin/superviseur in the group (if any), else
#   2) The most common non-null client_id in the group, else
#   3) None (signal: company has no canonical anchor — admin must intervene)
#
# This runs at boot time (logs WARNING summary if any group is misaligned)
# and is also exposed via the /admin/clients-consistency endpoint that the
# settings UI panoramic section consumes.
# ============================================================
async def _scan_clients_consistency() -> Dict[str, Any]:
    groups: Dict[str, Dict[str, Any]] = {}
    demos_rattaches: List[Dict[str, Any]] = []   # lot 79.3
    async for u in db.users.find(
        {"company": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "id": 1, "email": 1, "full_name": 1, "role": 1, "is_demo": 1,
         "company": 1, "client_id": 1, "parent_client_id": 1, "account_status": 1},
    ):
        # Skip disabled/deleted accounts so we don't flag old data
        if u.get("account_status") in ("disabled", "deleted", "blocked"):
            continue
        # Lot 79.3 — un compte de démonstration reste isolé : jamais réaligné sur une entreprise réelle.
        # S'il pointe vers le périmètre de quelqu'un d'autre, il est signalé pour être ISOLÉ.
        if _compte_demo(u):
            if (u.get("client_id") and u["client_id"] != u["id"]) or u.get("parent_client_id"):
                demos_rattaches.append({"id": u["id"], "email": u.get("email"), "client_id": u.get("client_id"),
                                        "parent_client_id": u.get("parent_client_id")})
            continue
        key = (u.get("company") or "").strip().lower()
        if not key:
            continue
        g = groups.setdefault(key, {"company": (u.get("company") or "").strip(), "members": []})
        g["members"].append(u)

    # Iter38r-fix9g — Also include tracked_users (mirror sub-users that share
    # an admin's tenant). They inherit the admin's `company` via parent_client_id.
    # Build an admin -> company index first, then join tracked_users by client_id.
    admin_by_id: Dict[str, Dict[str, Any]] = {}
    for g in groups.values():
        for m in g["members"]:
            if m.get("role") in ("admin", "superviseur"):
                admin_by_id[m["id"]] = {
                    "company_key": (m.get("company") or "").strip().lower(),
                    "company": m.get("company"),
                }
    async for tu in db.users.find(
        {"parent_client_id": {"$exists": True, "$nin": [None, ""]}, "tracked_role": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "id": 1, "email": 1, "full_name": 1, "role": 1, "tracked_role": 1,
         "client_id": 1, "parent_client_id": 1, "account_status": 1},
    ):
        if tu.get("account_status") in ("disabled", "deleted", "blocked"):
            continue
        parent_admin = admin_by_id.get(tu.get("parent_client_id"))
        if not parent_admin:
            continue
        # Attach the inherited company so the rest of the logic works seamlessly
        tu["company"] = parent_admin["company"]
        # Mark visually as tracked for the UI
        tu["role"] = tu.get("role") or f"tracked:{tu.get('tracked_role')}"
        key = parent_admin["company_key"]
        if not key:
            continue
        g = groups.setdefault(key, {"company": parent_admin["company"], "members": []})
        # Avoid duplicate insertion
        if not any(m.get("id") == tu["id"] for m in g["members"]):
            g["members"].append(tu)

    misaligned_groups: List[Dict[str, Any]] = []
    aligned_groups = 0
    total_misaligned_users = 0

    for key, g in groups.items():
        members = g["members"]
        if len(members) < 2:
            # Solo accounts cannot be inconsistent with peers
            aligned_groups += 1
            continue
        # Resolve canonical:
        admins = [m for m in members if m.get("role") in ("admin", "superviseur")]
        canonical: Optional[str] = None
        canonical_via = None
        if admins:
            canonical = admins[0]["id"]
            canonical_via = f"admin/superviseur ({admins[0].get('email')})"
        else:
            # Fallback: most common non-null client_id
            counts: Dict[str, int] = {}
            for m in members:
                cid = m.get("client_id")
                if cid:
                    counts[cid] = counts.get(cid, 0) + 1
            if counts:
                canonical = max(counts.items(), key=lambda x: x[1])[0]
                canonical_via = "most common client_id"

        # Compare each member's effective scope to the canonical
        misaligned: List[Dict[str, Any]] = []
        for m in members:
            # Iter38r-fix9i — For tracked users, the per-user diagnostic uses
            # their own `parent_client_id` as canonical (each tracked user is
            # attached to a specific admin, not the whole company group).
            # Mirror that here so the scan and the realign endpoint agree.
            if str(m.get("role", "")).startswith("tracked:") and m.get("parent_client_id"):
                target = m.get("parent_client_id")
                scope = m.get("client_id") or target or m["id"]
            else:
                target = canonical
                scope = m.get("client_id") or m["id"]
            if target and scope != target:
                misaligned.append({
                    "id": m["id"],
                    "email": m.get("email"),
                    "full_name": m.get("full_name"),
                    "role": m.get("role"),
                    "client_id": m.get("client_id"),
                    "parent_client_id": m.get("parent_client_id"),
                    "effective_scope": scope,
                    "canonical_for_user": target,
                })
        if misaligned:
            misaligned_groups.append({
                "company": g["company"],
                "canonical_client_id": canonical,
                "canonical_via": canonical_via,
                "members_total": len(members),
                "misaligned_count": len(misaligned),
                "misaligned": misaligned,
            })
            total_misaligned_users += len(misaligned)
        else:
            aligned_groups += 1

    return {
        "demos_rattaches": demos_rattaches,   # lot 79.3 : comptes démo à isoler
        "scanned_groups": len(groups),
        "aligned_groups": aligned_groups,
        "misaligned_groups": len(misaligned_groups),
        "misaligned_users_total": total_misaligned_users,
        "groups": misaligned_groups,
    }


@api.get("/admin/clients-consistency", tags=["Admin"])
async def admin_clients_consistency(_: dict = Depends(get_current_admin)):
    """Vue panoramique de chaque entreprise multi-utilisateur et indique si tous ses membres
    share the same canonical client_id. Read-only; pair with
    /admin/realign-user-to-client to fix outliers."""
    return await _scan_clients_consistency()


# Iter38r-fix9h — Batch realign every misaligned user in one click.
class _RealignAllPayload(BaseModel):
    confirm: bool = False
    dry_run: bool = False


@api.post("/admin/clients-consistency/realign-all", tags=["Admin"])
async def admin_realign_all(payload: _RealignAllPayload = Body(...), admin: dict = Depends(get_current_admin)):
    """Iter38r-fix9h — Réaligne d'un seul clic tous les utilisateurs détectés
    comme désalignés par `_scan_clients_consistency`. Nécessite `confirm=true`."""
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm=true requis pour exécuter l'opération en lot")
    scan = await _scan_clients_consistency()
    results: List[Dict[str, Any]] = []
    users_done = 0
    for grp in scan.get("groups", []):
        for m in grp.get("misaligned", []):
            email = m.get("email")
            if not email:
                continue
            entry: Dict[str, Any] = {
                "user_id": m.get("id"), "email": email,
                "company": grp.get("company"),
                "from_client_id": m.get("client_id"),
                "to_client_id": grp.get("canonical_client_id"),
                "applied": False, "actions": 0, "error": None,
            }
            try:
                res = await admin_realign_user_to_client(
                    payload={"email": email, "dry_run": payload.dry_run},
                    _={"role": "admin"},
                )
                entry["applied"] = bool(res.get("applied"))
                # Iter38r-fix9i — count actual actions (response uses "actions" key)
                entry["actions"] = len(res.get("actions", []) or [])
                if payload.dry_run:
                    entry["dry_run"] = True
                    # Mark as "would-apply" so the UI can show a real count in dry-run
                    entry["would_apply"] = bool(((res.get("diagnostic") or {}).get("realign_plan") or {}).get("needed"))
                if res.get("reason"):
                    entry["reason"] = res.get("reason")
                users_done += int(entry["applied"]) if not payload.dry_run else int(entry.get("would_apply", False))
            except HTTPException as exc:
                entry["error"] = exc.detail
            except Exception as exc:
                entry["error"] = str(exc)[:200]
            results.append(entry)
    # Lot 79.3 — comptes de démonstration rattachés au périmètre d'une entreprise : remis sur leur propre périmètre
    for d in scan.get("demos_rattaches", []):
        entry = {"user_id": d["id"], "email": d.get("email"), "company": "(compte de démonstration)",
                 "from_client_id": d.get("client_id"), "to_client_id": d["id"], "applied": False,
                 "actions": 1, "error": None, "reason": "compte de démonstration isolé"}
        if not payload.dry_run:
            await db.users.update_one({"id": d["id"]}, {
                "$set": {"client_id": d["id"], "client_id_legacy": d.get("client_id"),
                         "parent_client_id_legacy": d.get("parent_client_id"), "updated_at": _now()},
                "$unset": {"parent_client_id": ""}})
            entry["applied"] = True
            users_done += 1
        else:
            entry["would_apply"] = True
            users_done += 1
        results.append(entry)
    return {
        "ok": True, "dry_run": payload.dry_run,
        "groups_scanned": scan.get("misaligned_groups", 0),
        "users_realigned": users_done,
        "results": results,
    }


# ============================================================
# iter32 — Auto-suggest canonical client when admin types a company name
# in the "create user" form. The frontend calls this endpoint on blur and
# offers to auto-link the new user to the existing canonical client.
# ============================================================
@api.get("/admin/resolve-company", tags=["Admin"])
async def admin_resolve_company(company: str, _: dict = Depends(get_current_admin)):
    """Résout le client canonique pour un nom d'entreprise donné.

    Returns ``{found: bool, canonical_user, member_count}``. The frontend uses
    this to offer auto-link when creating a new user with a known company.
    Match is case-insensitive and trim-tolerant.
    """
    name = (company or "").strip()
    if not name:
        return {"found": False, "company_input": ""}
    pattern = f"^\\s*{re.escape(name)}\\s*$"
    members = await db.users.find(
        {
            "company": {"$regex": pattern, "$options": "i"},
            "account_status": {"$nin": ["disabled", "deleted", "blocked"]},
        },
        {"_id": 0, "id": 1, "email": 1, "full_name": 1, "role": 1, "company": 1},
    ).to_list(50)
    if not members:
        return {"found": False, "company_input": name}
    # Canonical = first admin/superviseur, else first member
    admins = [m for m in members if m.get("role") in ("admin", "superviseur")]
    canonical = admins[0] if admins else members[0]
    return {
        "found": True,
        "company_input": name,
        "canonical_user": {
            "id": canonical["id"],
            "email": canonical.get("email"),
            "full_name": canonical.get("full_name"),
            "role": canonical.get("role"),
            "company": canonical.get("company"),
        },
        "member_count": len(members),
    }


# ============================================================
# Campaign Efficiency dashboard — quantifies the WhatsApp-first
# strategy versus SMS:
#   • WA delivery rate (sent_ok / total)
#   • SMS delivery rate (sent_ok / total, all-time and as fallback only)
#   • Fallback rate (% of WA failures that triggered an SMS retry, and the
#     success rate of those retries)
#   • Estimated cost savings (each successful WA = one SMS not sent → save
#     `sms_unit_cost`). Helps justify the WA-first strategy to clients.
# Admin-only; aggregates across all clients (no per-client breakdown here —
# that already exists in /admin/usage/summary). Daily series capped at 30 days.
# ============================================================
@api.get("/admin/campaign-efficiency", tags=["Admin"])
async def admin_campaign_efficiency(days: int = 30, _: dict = Depends(get_current_admin)):
    days = max(1, min(days, 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()

    # Helper to extract a YYYY-MM-DD bucket from a string created_at field.
    day_expr = {"$substr": ["$created_at", 0, 10]}

    # 1) WA stats — outbound only (inbound is excluded from delivery rate).
    wa_pipeline = [
        {"$match": {"created_at": {"$gte": since_iso}, "direction": {"$ne": "inbound"}}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "sent_ok": {"$sum": {"$cond": [{"$or": [{"$eq": ["$ok", True]}, {"$eq": ["$wa_status", "sent"]}]}, 1, 0]}},
            "sent_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$ok", False]}, {"$eq": ["$wa_status", "failed"]}]}, 1, 0]}},
        }},
    ]
    wa_doc = await db.whatsapp_messages.aggregate(wa_pipeline).to_list(1)
    wa = (wa_doc[0] if wa_doc else {"total": 0, "sent_ok": 0, "sent_ko": 0})
    wa_delivery_rate = (wa["sent_ok"] / wa["total"] * 100.0) if wa["total"] else 0.0

    # 2) SMS stats — all SMS sent, and fallback-only subset.
    sms_pipeline = [
        {"$match": {"created_at": {"$gte": since_iso}}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "sent_ok": {"$sum": {"$cond": [{"$eq": ["$status", "sent"]}, 1, 0]}},
            "sent_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$status", "failed"]}, {"$eq": ["$status", "error"]}]}, 1, 0]}},
            "fallback_total": {"$sum": {"$cond": [{"$eq": ["$wa_fallback", True]}, 1, 0]}},
            "fallback_ok": {"$sum": {"$cond": [{"$and": [{"$eq": ["$wa_fallback", True]}, {"$eq": ["$status", "sent"]}]}, 1, 0]}},
        }},
    ]
    sms_doc = await db.sms_messages.aggregate(sms_pipeline).to_list(1)
    sms = (sms_doc[0] if sms_doc else {"total": 0, "sent_ok": 0, "sent_ko": 0, "fallback_total": 0, "fallback_ok": 0})
    sms_delivery_rate = (sms["sent_ok"] / sms["total"] * 100.0) if sms["total"] else 0.0
    fallback_success_rate = (sms["fallback_ok"] / sms["fallback_total"] * 100.0) if sms["fallback_total"] else 0.0
    # % of WA failures that triggered an SMS retry
    fallback_trigger_rate = (sms["fallback_total"] / wa["sent_ko"] * 100.0) if wa["sent_ko"] else 0.0

    # 3) Cost savings — average sms_unit_cost across configured clients.
    cost_pipeline = [
        {"$match": {"sms_unit_cost": {"$gt": 0}}},
        {"$group": {"_id": None, "avg": {"$avg": "$sms_unit_cost"}, "count": {"$sum": 1}}},
    ]
    cost_doc = await db.users.aggregate(cost_pipeline).to_list(1)
    sms_unit_cost_avg = float((cost_doc[0] if cost_doc else {}).get("avg") or 0.0)
    estimated_savings = round(wa["sent_ok"] * sms_unit_cost_avg, 2)

    # 4) Daily series — WA OK, WA KO, SMS OK, SMS KO, fallback OK per day.
    daily_wa = {}
    async for d in db.whatsapp_messages.aggregate([
        {"$match": {"created_at": {"$gte": since_iso}, "direction": {"$ne": "inbound"}}},
        {"$group": {
            "_id": day_expr,
            "wa_ok": {"$sum": {"$cond": [{"$or": [{"$eq": ["$ok", True]}, {"$eq": ["$wa_status", "sent"]}]}, 1, 0]}},
            "wa_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$ok", False]}, {"$eq": ["$wa_status", "failed"]}]}, 1, 0]}},
        }},
    ]):
        daily_wa[d["_id"]] = {"wa_ok": int(d.get("wa_ok") or 0), "wa_ko": int(d.get("wa_ko") or 0)}

    daily_sms = {}
    async for d in db.sms_messages.aggregate([
        {"$match": {"created_at": {"$gte": since_iso}}},
        {"$group": {
            "_id": day_expr,
            "sms_ok": {"$sum": {"$cond": [{"$eq": ["$status", "sent"]}, 1, 0]}},
            "sms_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$status", "failed"]}, {"$eq": ["$status", "error"]}]}, 1, 0]}},
            "fallback_ok": {"$sum": {"$cond": [{"$and": [{"$eq": ["$wa_fallback", True]}, {"$eq": ["$status", "sent"]}]}, 1, 0]}},
        }},
    ]):
        daily_sms[d["_id"]] = {
            "sms_ok": int(d.get("sms_ok") or 0),
            "sms_ko": int(d.get("sms_ko") or 0),
            "fallback_ok": int(d.get("fallback_ok") or 0),
        }

    daily = []
    end_day = datetime.now(timezone.utc).date()
    # Strict `days` consecutive buckets ending today (inclusive). Earlier we
    # used `since.date()` which could yield days+1 buckets across the UTC
    # midnight boundary — the testing agent flagged this; tighten it here.
    cur_day = end_day - timedelta(days=days - 1)
    while cur_day <= end_day:
        key = cur_day.isoformat()
        wa_row = daily_wa.get(key, {"wa_ok": 0, "wa_ko": 0})
        sms_row = daily_sms.get(key, {"sms_ok": 0, "sms_ko": 0, "fallback_ok": 0})
        daily.append({"day": key, **wa_row, **sms_row})
        cur_day += timedelta(days=1)

    return {
        "period_days": days,
        "wa": {
            "total": int(wa["total"]),
            "sent_ok": int(wa["sent_ok"]),
            "sent_ko": int(wa["sent_ko"]),
            "delivery_rate": round(wa_delivery_rate, 2),
        },
        "sms": {
            "total": int(sms["total"]),
            "sent_ok": int(sms["sent_ok"]),
            "sent_ko": int(sms["sent_ko"]),
            "delivery_rate": round(sms_delivery_rate, 2),
        },
        "fallback": {
            "triggered": int(sms["fallback_total"]),
            "succeeded": int(sms["fallback_ok"]),
            "success_rate": round(fallback_success_rate, 2),
            "trigger_rate_on_wa_failures": round(fallback_trigger_rate, 2),
        },
        "cost_savings": {
            "sms_unit_cost_avg": round(sms_unit_cost_avg, 4),
            "wa_success_count": int(wa["sent_ok"]),
            "estimated_savings_xof": estimated_savings,
        },
        "daily": daily,
    }


@api.put("/admin/clients/{client_id}/whatsapp-cost", tags=["Admin"])
async def admin_set_client_wa_cost(
    client_id: str,
    payload: Dict[str, Any],
    _: dict = Depends(get_current_admin),
):
    """Met à jour le coût WhatsApp unitaire (par message sortant) pour un client.
    Accepts {wa_unit_cost: number, wa_currency: str}."""
    update: Dict[str, Any] = {}
    if "wa_unit_cost" in payload:
        try:
            v = float(payload.get("wa_unit_cost") or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Coût invalide")
        if v < 0:
            raise HTTPException(status_code=400, detail="Le coût ne peut être négatif")
        update["wa_unit_cost"] = v
    if "wa_currency" in payload:
        cur = (payload.get("wa_currency") or "").strip().upper()[:6]
        update["wa_currency"] = cur or "XOF"
    if not update:
        return {"ok": True}
    res = await db.users.update_one({"id": client_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return {"ok": True, **update}


@api.get("/admin/clients/{client_id}/timeline", tags=["Admin"])
async def admin_client_timeline(
    client_id: str,
    limit: int = 200,
    types: Optional[str] = None,  # CSV of: appointment,intervention,whatsapp,form,document,note,task
    _: dict = Depends(get_current_admin),
):
    """Unified CRM timeline for a client — aggregates events from 7 collections.

    Each event has shape: {id, type, ts, title, summary, status?, link?, payload}
    Sorted by ts DESC. Optional `types` filter (CSV)."""
    user = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Client introuvable")

    wanted = {t.strip() for t in (types or "appointment,intervention,whatsapp,form,document,note,task").split(",") if t.strip()}
    events: List[Dict[str, Any]] = []

    # 1) Appointments
    if "appointment" in wanted:
        appts = await db.appointments.find(
            {"client_id": client_id},
            {"_id": 0, "id": 1, "scheduled_at": 1, "subject": 1, "status": 1, "duration_minutes": 1, "created_at": 1},
        ).sort("scheduled_at", -1).limit(limit).to_list(limit)
        for ap in appts:
            events.append({
                "id": ap["id"],
                "type": "appointment",
                "ts": ap.get("scheduled_at") or ap.get("created_at"),
                "title": ap.get("subject") or "Rendez-vous",
                "summary": f"Statut: {ap.get('status') or 'planifié'} · Durée: {ap.get('duration_minutes') or 30} min",
                "status": ap.get("status"),
                "payload": ap,
            })

    # 2) Interventions
    if "intervention" in wanted:
        ints = await db.interventions.find(
            {"client_id": client_id},
            {"_id": 0, "id": 1, "intervention_date": 1, "intervention_number": 1, "title": 1,
             "subject": 1, "type": 1, "status": 1, "created_at": 1},
        ).sort("created_at", -1).limit(limit).to_list(limit)
        for it in ints:
            events.append({
                "id": it["id"],
                "type": "intervention",
                "ts": it.get("intervention_date") or it.get("created_at"),
                "title": f"{it.get('intervention_number') or ''} — {it.get('subject') or it.get('title') or 'Intervention'}".strip(" —"),
                "summary": f"Type: {it.get('type') or '—'} · Statut: {it.get('status') or '—'}",
                "status": it.get("status"),
                "payload": it,
            })

    # 3) WhatsApp messages (sent + received logs already use client_id)
    if "whatsapp" in wanted:
        msgs = await db.whatsapp_messages.find(
            {"client_id": client_id},
            {"_id": 0, "id": 1, "to": 1, "template_name": 1, "ok": 1, "status": 1,
             "error": 1, "recipient_label": 1, "automation_event": 1, "bulk": 1, "created_at": 1},
        ).sort("created_at", -1).limit(limit).to_list(limit)
        for m in msgs:
            kind_label = "Auto" if m.get("automation_event") else ("Groupé" if m.get("bulk") else "Manuel")
            events.append({
                "id": m["id"],
                "type": "whatsapp",
                "ts": m.get("created_at"),
                "title": f"WhatsApp · {m.get('template_name') or '—'}",
                "summary": f"{kind_label} · {('OK' if m.get('ok') else (m.get('error') or 'KO'))[:80]}",
                "status": "ok" if m.get("ok") else "ko",
                "payload": m,
            })

    # 4) Form submissions
    if "form" in wanted:
        subs = await db.form_submissions.find(
            {"client_id": client_id},
            {"_id": 0, "id": 1, "form_id": 1, "user_label": 1, "anonymous": 1, "respondent_email": 1, "created_at": 1},
        ).sort("created_at", -1).limit(limit).to_list(limit)
        # Resolve form titles in batch
        form_ids = list({s.get("form_id") for s in subs if s.get("form_id")})
        forms_by_id: Dict[str, str] = {}
        if form_ids:
            f_docs = await db.forms.find(
                {"id": {"$in": form_ids}}, {"_id": 0, "id": 1, "title": 1, "number": 1}
            ).to_list(len(form_ids))
            forms_by_id = {f["id"]: f"{f.get('number') or ''} — {f.get('title') or '—'}".strip(" —") for f in f_docs}
        for s in subs:
            events.append({
                "id": s["id"],
                "type": "form",
                "ts": s.get("created_at"),
                "title": forms_by_id.get(s.get("form_id") or "") or "Soumission formulaire",
                "summary": f"Auteur: {s.get('user_label') or '—'}{' · anonyme' if s.get('anonymous') else ''}",
                "status": "submitted",
                "payload": s,
            })

    # 5) Documents (uploaded by client or shared with client)
    if "document" in wanted:
        try:
            docs = await db.documents.find(
                {"$or": [{"client_id": client_id}, {"owner_id": client_id}, {"uploaded_by": client_id}]},
                {"_id": 0, "id": 1, "name": 1, "category": 1, "size": 1, "created_at": 1, "uploaded_by_label": 1},
            ).sort("created_at", -1).limit(limit).to_list(limit)
            for d in docs:
                size_kb = round((d.get("size") or 0) / 1024)
                events.append({
                    "id": d["id"],
                    "type": "document",
                    "ts": d.get("created_at"),
                    "title": d.get("name") or "Document",
                    "summary": f"{d.get('category') or 'Document'} · {size_kb} Ko · par {d.get('uploaded_by_label') or '—'}",
                    "status": "uploaded",
                    "payload": d,
                })
        except Exception:
            pass

    # 6) Notes (free-text by admin/commercial)
    if "note" in wanted:
        notes = await db.client_notes.find(
            {"client_id": client_id},
            {"_id": 0},
        ).sort("created_at", -1).limit(limit).to_list(limit)
        for n in notes:
            preview = (n.get("text") or "").strip()
            events.append({
                "id": n["id"],
                "type": "note",
                "ts": n.get("created_at"),
                "title": f"Note de {n.get('author_label') or 'Admin'}",
                "summary": preview[:160] + ("…" if len(preview) > 160 else ""),
                "status": "note",
                "payload": n,
            })

    # 7) Tasks (todos with optional due date + WhatsApp reminder)
    if "task" in wanted:
        tasks = await db.client_tasks.find(
            {"client_id": client_id},
            {"_id": 0},
        ).sort("due_at", -1).limit(limit).to_list(limit)
        for t in tasks:
            due = t.get("due_at")
            events.append({
                "id": t["id"],
                "type": "task",
                "ts": due or t.get("created_at"),
                "title": t.get("title") or "Tâche",
                "summary": (
                    f"Échéance: {due or 'aucune'} · "
                    f"{'Terminée' if t.get('status') == 'done' else 'À faire'}"
                    + (" · 🔔 rappel WhatsApp" if t.get("remind_via_whatsapp") else "")
                ),
                "status": "completed" if t.get("status") == "done" else "open",
                "payload": t,
            })

    # Sort DESC by ts (string ISO sorts naturally)
    events.sort(key=lambda x: (x.get("ts") or ""), reverse=True)
    events = events[:limit]

    counts = {"appointment": 0, "intervention": 0, "whatsapp": 0, "form": 0, "document": 0, "note": 0, "task": 0}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1

    return {
        "client": {
            "id": user["id"],
            "full_name": user.get("full_name"),
            "company": user.get("company"),
            "email": user.get("email"),
            "phone": user.get("phone"),
            "client_code": user.get("client_code"),
            "country": user.get("country"),
            "city": user.get("city"),
            "account_status": user.get("account_status"),
            "created_at": user.get("created_at"),
        },
        "events": events,
        "counts": counts,
        "total": len(events),
    }
