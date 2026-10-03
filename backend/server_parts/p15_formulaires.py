# server_parts/p15_formulaires.py — Formulaires dynamiques et leurs statistiques.
# Morceau de l'ancien server.py (lignes 20411 à 21180), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# Lot 34 — routes /me/forms* réservées aux comptes dont la fonction « Formulaires et
# Sondages » est activée (SMART Communications) : dépendance _utilisateur_formulaires
# (p03) ; Admin et Superviseur y ont toujours accès. Liens publics : même contrôle
# sur le compte propriétaire.
# ====================================================================
# PHASE 4 — Dynamic Forms (Google Forms-like)
# Structure :
#   forms : {id, client_id, number, title, description, is_public, pages, created_by_id, created_by_label, created_at, updated_at, uses_count, revisions_count}
#     pages : [{id, title, fields:[{id, type, label, required, options?, placeholder?, col_start, col_span, row}]}]
#   form_submissions : {id, form_id, client_id, user_id, user_label, data, geo, created_at, updated_at, revisions_count}
# ====================================================================
FIELD_TYPES = {"text", "textarea", "number", "boolean", "select", "multiselect", "date", "datetime", "email", "tel", "url", "location"}


class FormField(BaseModel):
    id: str
    type: str  # text | textarea | number | boolean | select | multiselect | date |
               # datetime | email | tel | url | location | table | file | signature
    label: str
    required: bool = False
    options: Optional[List[str]] = None
    placeholder: Optional[str] = None
    default_value: Optional[Any] = None
    # Position inside a 12-column responsive grid
    col_start: int = 1      # 1..12
    col_span: int = 12      # 1..12 (col_start + col_span <= 13)
    row: int = 0
    # Type-specific extras
    columns: Optional[List[Dict[str, Any]]] = None  # for type=table : [{key,label,type:text|number|date}]
    accept: Optional[str] = None  # for type=file : MIME / extensions filter


class FormPage(BaseModel):
    id: str
    title: str = "Page"
    fields: List[FormField] = []


class FormCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    is_public: bool = False
    pages: Optional[List[FormPage]] = None
    category_id: Optional[str] = None  # Iter40 (2026-02)
    # 2026-02 fork (P5) — Liste d'accessibilité stricte par tenant. Si
    # non-vide, seuls les utilisateurs suivis rattachés à un client_id
    # figurant dans la liste peuvent voir/importer le formulaire. Vide →
    # comportement historique (own client + is_public).
    access_client_ids: Optional[List[str]] = None


class FormUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None
    pages: Optional[List[FormPage]] = None
    category_id: Optional[str] = None  # Iter40 (2026-02)
    access_client_ids: Optional[List[str]] = None


async def _next_form_number(client_code: str) -> int:
    res = await db.counters.find_one_and_update(
        {"_id": f"form_{client_code}"},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=True,
    )
    return (res or {}).get("value", 1)


def _form_serialize(doc: dict) -> dict:
    if not doc:
        return doc
    doc.pop("_id", None)
    return doc


async def _require_owner_or_admin(form: dict, user: dict) -> None:
    if user.get("role") == "admin":
        return
    if form.get("client_id") != (user.get("client_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Formulaire non accessible")


@api.get("/me/forms", tags=["Formulaires"])
async def me_list_forms(user: dict = Depends(_utilisateur_formulaires)):
    """Liste les formulaires : tous ceux du client de l'utilisateur + tous les formulaires publics d'autres clients.

    2026-02 fork (P5) — filtre supplémentaire `access_client_ids` : quand
    non-vide, restreint aux tenants explicitement autorisés (admin bypass).
    """
    client_scope = (user.get("client_id") or user.get("id")) if user.get("role") != "admin" else None
    if user.get("role") == "admin":
        query = {}
    else:
        query = {"$or": [{"client_id": client_scope}, {"is_public": True}]}
    items = await db.forms.find(query, {"_id": 0, "pages": 0}).sort("created_at", -1).to_list(500)
    # Tag each form so the UI can distinguish mine vs public-imported
    for it in items:
        if user.get("role") == "admin":
            # Admin sees everything as "mine" (full edit/stats/share/delete rights)
            it["is_mine"] = True
        else:
            it["is_mine"] = it.get("client_id") == client_scope
    # 2026-02 fork (P5) — enforce access_client_ids gate for non-admin
    items = [it for it in items if _item_accessible_by_tenant(it, user)]
    return items


@api.post("/me/forms", tags=["Formulaires"])
async def me_create_form(payload: FormCreate, user: dict = Depends(_utilisateur_formulaires)):
    client_scope = (user.get("client_id") or user.get("id")) if user.get("role") != "admin" else user["id"]
    # Iter34t — Reject duplicate form titles within the same client scope
    # (case-insensitive, trimmed). The frontend exposes /me/forms/title-suggestions
    # so users can autocomplete + check before submitting.
    title_norm = (payload.title or "").strip()
    if not title_norm:
        raise HTTPException(status_code=400, detail="Titre requis")
    existing = await db.forms.find_one(
        {"client_id": client_scope, "title": {"$regex": f"^\\s*{re.escape(title_norm)}\\s*$", "$options": "i"}},
        {"_id": 0, "id": 1, "title": 1, "number": 1},
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Un formulaire portant le titre « {existing.get('title')} » existe déjà ({existing.get('number')}). Choisissez un autre titre.",
        )
    client = await db.users.find_one({"id": client_scope}, {"_id": 0, "client_code": 1, "company": 1, "full_name": 1})
    code = (client or {}).get("client_code") or _slugify_code((client or {}).get("company") or (client or {}).get("full_name") or "X")
    number = await _next_form_number(code)
    doc = {
        "id": _uuid(),
        "client_id": client_scope,
        "client_code": code,
        "number": f"FORM-{code}-{number:04d}",
        "title": title_norm,
        "description": payload.description or "",
        "is_public": payload.is_public,
        "category_id": payload.category_id or None,  # Iter40 (2026-02)
        "access_client_ids": list(payload.access_client_ids or []),  # 2026-02 fork P5
        "pages": [p.model_dump() for p in (payload.pages or [FormPage(id=_uuid(), title="Page 1", fields=[])])],
        "created_by_id": user["id"],
        "created_by_label": user.get("full_name") or user.get("email"),
        "created_at": _now(),
        "updated_at": _now(),
        "uses_count": 0,
    }
    await db.forms.insert_one(doc.copy())
    return _form_serialize(doc)


# Iter34t — Expose existing form titles for the same client scope so the
# create form UI can suggest them as a datalist (prevents typo duplicates).
@api.get("/me/forms/title-suggestions", tags=["Formulaires"])
async def me_forms_title_suggestions(user: dict = Depends(_utilisateur_formulaires)):
    client_scope = (user.get("client_id") or user.get("id")) if user.get("role") != "admin" else user["id"]
    items = await db.forms.find({"client_id": client_scope}, {"_id": 0, "title": 1, "number": 1}).sort("created_at", -1).to_list(500)
    seen = set()
    out: List[Dict[str, str]] = []
    for it in items:
        t = (it.get("title") or "").strip()
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": t, "number": it.get("number")})
    return {"items": out}


@api.get("/me/forms/{form_id}", tags=["Formulaires"])
async def me_get_form(form_id: str, user: dict = Depends(_utilisateur_formulaires)):
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    client_scope = (user.get("client_id") or user.get("id"))
    is_public = form.get("is_public")
    is_mine = form.get("client_id") == client_scope
    if user.get("role") != "admin" and not is_public and not is_mine:
        raise HTTPException(status_code=403, detail="Formulaire non accessible")
    # 2026-02 fork (P5) — enforce access_client_ids gate
    if not _item_accessible_by_tenant(form, user):
        raise HTTPException(status_code=403, detail="Formulaire non accessible pour votre organisation")
    form["is_mine"] = is_mine
    return form


@api.put("/me/forms/{form_id}", tags=["Formulaires"])
async def me_update_form(form_id: str, payload: FormUpdate, user: dict = Depends(_utilisateur_formulaires)):
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    await _require_owner_or_admin(form, user)
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Iter34t — block rename to a name already in use by another form of the
    # same client scope.
    if "title" in update:
        new_title = (update["title"] or "").strip()
        if not new_title:
            raise HTTPException(status_code=400, detail="Titre requis")
        dup = await db.forms.find_one(
            {
                "client_id": form.get("client_id"),
                "id": {"$ne": form_id},
                "title": {"$regex": f"^\\s*{re.escape(new_title)}\\s*$", "$options": "i"},
            },
            {"_id": 0, "id": 1, "title": 1, "number": 1},
        )
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"Un autre formulaire porte déjà ce titre ({dup.get('number')}).",
            )
        update["title"] = new_title
    if "pages" in update:
        update["pages"] = [p if isinstance(p, dict) else p.model_dump() for p in update["pages"]]
    update["updated_at"] = _now()
    await db.forms.update_one({"id": form_id}, {"$set": update})
    refreshed = await db.forms.find_one({"id": form_id}, {"_id": 0})
    return _form_serialize(refreshed)


@api.delete("/me/forms/{form_id}", tags=["Formulaires"])
async def me_delete_form(form_id: str, user: dict = Depends(_utilisateur_formulaires)):
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        return {"ok": True}
    await _require_owner_or_admin(form, user)
    await db.forms.delete_one({"id": form_id})
    await db.form_submissions.delete_many({"form_id": form_id})
    return {"ok": True}


@api.post("/me/forms/{form_id}/import", tags=["Formulaires"])
async def me_import_form(form_id: str, user: dict = Depends(_utilisateur_formulaires)):
    """Duplicate a public form into the current client's scope (numbered & owned by them)."""
    src = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not src:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    if not src.get("is_public") and src.get("client_id") != (user.get("client_id") or user.get("id")) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Ce formulaire n'est pas public")
    client_scope = (user.get("client_id") or user.get("id")) if user.get("role") != "admin" else user["id"]
    client = await db.users.find_one({"id": client_scope}, {"_id": 0, "client_code": 1, "company": 1, "full_name": 1})
    code = (client or {}).get("client_code") or _slugify_code((client or {}).get("company") or (client or {}).get("full_name") or "X")
    number = await _next_form_number(code)
    dup = {
        "id": _uuid(),
        "client_id": client_scope,
        "client_code": code,
        "number": f"FORM-{code}-{number:04d}",
        "title": f"{src['title']} (importé)",
        "description": src.get("description") or "",
        "is_public": False,
        "pages": src.get("pages") or [],
        "created_by_id": user["id"],
        "created_by_label": user.get("full_name") or user.get("email"),
        "imported_from": src["id"],
        "created_at": _now(),
        "updated_at": _now(),
        "uses_count": 0,
    }
    await db.forms.insert_one(dup.copy())
    return _form_serialize(dup)


# ----- Form submissions (one per user per form — auto-alimentation on reopen) -----
class SubmissionSave(BaseModel):
    data: Dict[str, Any]
    geo: Optional[Dict[str, Any]] = None


@api.get("/me/forms/{form_id}/submission", tags=["Formulaires"])
async def me_get_my_submission(form_id: str, user: dict = Depends(_utilisateur_formulaires)):
    """Renvoie la soumission de l'utilisateur courant pour le formulaire (ou un stub vide)."""
    sub = await db.form_submissions.find_one(
        {"form_id": form_id, "user_id": user["id"]}, {"_id": 0}
    )
    return sub or {"form_id": form_id, "user_id": user["id"], "data": {}, "revisions_count": 0}


@api.post("/me/forms/{form_id}/upload", tags=["Formulaires"])
async def me_form_upload_file(
    form_id: str,
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(_utilisateur_formulaires),
):
    """Per-form file attachment uploader (max 1 Mo). Used by the new "file" field
    type. Returns a stable public URL stored on the submission's data dict."""
    raw = await file.read()
    if len(raw) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 1 Mo)")
    if len(raw) < 1:
        raise HTTPException(status_code=400, detail="Fichier vide")
    form = await db.forms.find_one({"id": form_id}, {"_id": 0, "client_id": 1})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    file_id = _uuid()
    suffix = Path(file.filename or "").suffix.lower()
    safe_name = f"{file_id}{suffix}"
    ext = (suffix.lstrip(".") or "").lower()
    public_path = f"/api/files/{file_id}{('.' + ext) if ext else ''}"
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    public_url = f"{(_public_base_url(request) or str(request.base_url).rstrip('/'))}{public_path}"
    # 2026-02 fork iter108 — Deploy-safe upload helper (storage-first, local cache).
    from storage import asave_upload_and_cache  # lot 26 : dans un thread, sans figer le serveur
    target, storage_path, storage_error = await asave_upload_and_cache(
        upload_dir=UPLOAD_DIR, filename=safe_name, data=raw, content_type=content_type,
    )
    if storage_error:
        logger.warning("[form_attachment] storage mirror failed: %s", storage_error)
    file_doc = {
        "id": file_id, "filename": file.filename, "stored_name": safe_name,
        "extension": ext, "content_type": content_type, "size": len(raw),
        "url": public_path, "public_url": public_url, "uploaded_at": _now(),
        "uploaded_by_id": user.get("id"), "uploaded_by_email": user.get("email"),
        "uploaded_from_ip": _client_ip_from_request(request),
        "context": "form_attachment",
        "form_id": form_id,
        "storage_path": storage_path, "storage_error": storage_error,
    }
    await db.files.insert_one(file_doc)
    return {
        "ok": True,
        "file_id": file_id,
        "filename": file.filename,
        "size": len(raw),
        "content_type": content_type,
        "public_url": public_url,
    }


async def _signaler_soumission(form_id: str, repondant: Optional[str]) -> None:
    """Lot 41 — automatisation « Nouvelle soumission de formulaire » (au mieux, en tâche de fond :
    la réponse du répondant n'attend jamais l'envoi WhatsApp)."""
    async def _go():
        try:
            f = await db.forms.find_one({"id": form_id}, {"_id": 0, "client_id": 1, "title": 1, "number": 1,
                                                        "uses_count": 1})
            if f and f.get("client_id"):
                await _emit_event("form.submitted", {"client_id": f["client_id"], "extra_ctx": {
                    "formulaire": f.get("title") or "", "formulaire_numero": f.get("number") or "",
                    "repondant": repondant or "Anonyme", "nb_reponses": str(f.get("uses_count") or 0)}})
        except Exception:  # noqa: BLE001
            logger.warning("[automations] form.submitted non émis", exc_info=True)
    asyncio.create_task(_go())


@api.post("/me/forms/{form_id}/submission", tags=["Formulaires"])
async def me_save_submission(form_id: str, payload: SubmissionSave, user: dict = Depends(_utilisateur_formulaires)):
    form = await db.forms.find_one({"id": form_id}, {"_id": 0, "client_id": 1, "uses_count": 1})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    existing = await db.form_submissions.find_one({"form_id": form_id, "user_id": user["id"]}, {"_id": 0})
    if existing:
        update = {
            "data": payload.data,
            "geo": payload.geo,
            "updated_at": _now(),
            "revisions_count": (existing.get("revisions_count") or 0) + 1,
            "user_label": user.get("full_name") or user.get("email"),
        }
        await db.form_submissions.update_one({"id": existing["id"]}, {"$set": update})
        refreshed = await db.form_submissions.find_one({"id": existing["id"]}, {"_id": 0})
        return refreshed
    doc = {
        "id": _uuid(),
        "form_id": form_id,
        "client_id": form.get("client_id"),
        "user_id": user["id"],
        "user_label": user.get("full_name") or user.get("email"),
        "data": payload.data,
        "geo": payload.geo,
        "created_at": _now(),
        "updated_at": _now(),
        "revisions_count": 1,
    }
    await db.form_submissions.insert_one(doc.copy())
    await db.forms.update_one({"id": form_id}, {"$inc": {"uses_count": 1}})
    await _signaler_soumission(form_id, doc["user_label"])          # lot 41
    doc.pop("_id", None)
    return doc


@api.get("/me/forms/{form_id}/submissions", tags=["Formulaires"])
async def me_list_form_submissions(form_id: str, user: dict = Depends(_utilisateur_formulaires)):
    """Liste toutes les soumissions d'un formulaire — propriétaire/admin uniquement."""
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    await _require_owner_or_admin(form, user)
    items = await db.form_submissions.find({"form_id": form_id}, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return {"form": {"id": form["id"], "title": form.get("title"), "pages": form.get("pages") or []}, "items": items}


# ----- Public (anonymous) form fill — only for is_public forms -----
class PublicSubmissionRequest(BaseModel):
    data: Dict[str, Any]
    geo: Optional[Dict[str, Any]] = None
    respondent_name: Optional[str] = None
    respondent_email: Optional[str] = None


@api.get("/public/forms/{form_id}", tags=["Public"])
async def public_get_form(form_id: str):
    """Récupère un formulaire public en anonyme — fonctionne uniquement si `is_public=True`."""
    form = await db.forms.find_one(
        {"id": form_id, "is_public": True},
        {"_id": 0, "id": 1, "number": 1, "title": 1, "description": 1, "pages": 1, "client_code": 1, "client_id": 1},
    )
    # Lot 34 — lien public : le compte propriétaire doit avoir « Formulaires et Sondages » activé.
    if not form or not await _fonction_active_pour_compte(form.get("client_id"), "forms_surveys"):
        raise HTTPException(status_code=404, detail="Formulaire introuvable ou non public")
    form.pop("client_id", None)
    return form


@api.post("/public/forms/{form_id}/submission", tags=["Public"])
async def public_submit_form(form_id: str, payload: PublicSubmissionRequest, request: Request):
    form = await db.forms.find_one({"id": form_id, "is_public": True}, {"_id": 0, "client_id": 1})
    if not form or not await _fonction_active_pour_compte(form.get("client_id"), "forms_surveys"):   # lot 34
        raise HTTPException(status_code=404, detail="Formulaire introuvable ou non public")
    from ip_client import ip_reelle   # lot 55 : fonction unique
    ip = ip_reelle(request)
    doc = {
        "id": _uuid(),
        "form_id": form_id,
        "client_id": form.get("client_id"),
        "user_id": f"anon-{_uuid()[:8]}",  # unique per submission so we bypass the (form_id,user_id) unique index
        "user_label": (payload.respondent_name or payload.respondent_email or f"Anonyme · {ip}")[:120],
        "data": payload.data,
        "geo": payload.geo,
        "respondent_email": payload.respondent_email,
        "anonymous": True,
        "source_ip": ip,
        "created_at": _now(),
        "updated_at": _now(),
        "revisions_count": 1,
    }
    await db.form_submissions.insert_one(doc.copy())
    await db.forms.update_one({"id": form_id}, {"$inc": {"uses_count": 1}})
    await _signaler_soumission(form_id, doc["user_label"])          # lot 41
    return {"ok": True, "id": doc["id"]}


# ====================================================================
# PHASE 4b — Form Analytics Dashboard (global + per-form)
# ====================================================================
def _parse_date(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        # Accept YYYY-MM-DD or full ISO
        if len(v) == 10:
            return datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        return None


def _analytics_scope_query(user: dict, admin_all: bool = True) -> dict:
    """Scope forms/submissions to current client unless admin asks for global."""
    if user.get("role") == "admin" and admin_all:
        return {}
    cid = user.get("client_id") or user.get("id")
    return {"client_id": cid}


async def _submissions_analytics(match: dict, date_from: Optional[datetime], date_to: Optional[datetime]) -> dict:
    """Common aggregation pipeline used by global + per-form analytics."""
    range_q = {}
    if date_from:
        range_q["$gte"] = date_from.isoformat()
    if date_to:
        range_q["$lte"] = date_to.isoformat()
    if range_q:
        match = {**match, "created_at": range_q}

    subs = await db.form_submissions.find(
        match,
        {"_id": 0, "id": 1, "form_id": 1, "user_id": 1, "user_label": 1,
         "anonymous": 1, "created_at": 1, "geo": 1, "source_ip": 1, "respondent_email": 1},
    ).to_list(10000)

    # Time-series: group per day (UTC)
    by_day: Dict[str, int] = {}
    auth_count = 0
    anon_count = 0
    by_country: Dict[str, int] = {}
    by_author: Dict[str, Dict[str, Any]] = {}

    for s in subs:
        ts = s.get("created_at")
        if isinstance(ts, datetime):
            day_key = ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
        else:
            day_key = (str(ts) or "")[:10] or "unknown"
        by_day[day_key] = by_day.get(day_key, 0) + 1

        if s.get("anonymous"):
            anon_count += 1
        else:
            auth_count += 1
            label = s.get("user_label") or s.get("user_id") or "—"
            node = by_author.setdefault(label, {"label": label, "count": 0})
            node["count"] += 1

        geo = s.get("geo") or {}
        country = (geo.get("country") or geo.get("country_name") or "").strip() or "Inconnu"
        by_country[country] = by_country.get(country, 0) + 1

    # Sort series by date ascending
    series = [{"date": d, "count": by_day[d]} for d in sorted(by_day.keys())]
    top_authors = sorted(by_author.values(), key=lambda x: x["count"], reverse=True)[:10]
    country_list = sorted(
        [{"country": k, "count": v} for k, v in by_country.items()],
        key=lambda x: x["count"], reverse=True,
    )

    return {
        "total_submissions": len(subs),
        "auth_count": auth_count,
        "anon_count": anon_count,
        "series": series,
        "top_authors": top_authors,
        "by_country": country_list,
    }


@api.get("/me/forms-analytics", tags=["Formulaires"])
async def me_forms_analytics_global(
    user: dict = Depends(_utilisateur_formulaires),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Analyses globales sur tous les formulaires visibles par l'utilisateur.
    - Admin : tous les formulaires.
    - Client : tous ses formulaires.
    """
    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    forms_scope = _analytics_scope_query(user)
    forms = await db.forms.find(
        forms_scope,
        {"_id": 0, "id": 1, "number": 1, "title": 1, "is_public": 1, "uses_count": 1, "created_at": 1, "client_code": 1},
    ).to_list(5000)
    form_ids = [f["id"] for f in forms]

    if not form_ids:
        return {
            "scope": "global",
            "total_forms": 0,
            "total_views": 0,
            "public_count": 0,
            "private_count": 0,
            "submissions": await _submissions_analytics({"form_id": {"$in": []}}, df, dt),
            "top_forms": [],
        }

    agg = await _submissions_analytics({"form_id": {"$in": form_ids}}, df, dt)

    # Top forms by submissions
    sub_counts: Dict[str, int] = {}
    per_form_match: Dict[str, Any] = {"form_id": {"$in": form_ids}}
    if df or dt:
        rng: Dict[str, Any] = {}
        if df: rng["$gte"] = df.isoformat()
        if dt: rng["$lte"] = dt.isoformat()
        per_form_match["created_at"] = rng
    cursor = db.form_submissions.aggregate([
        {"$match": per_form_match},
        {"$group": {"_id": "$form_id", "count": {"$sum": 1}}},
    ])
    async for r in cursor:
        sub_counts[r["_id"]] = r["count"]

    top_forms = sorted(
        [{
            "id": f["id"],
            "number": f.get("number"),
            "title": f.get("title"),
            "is_public": bool(f.get("is_public")),
            "views": int(f.get("uses_count") or 0),
            "submissions": int(sub_counts.get(f["id"], 0)),
        } for f in forms],
        key=lambda x: x["submissions"], reverse=True,
    )[:10]

    return {
        "scope": "global",
        "total_forms": len(forms),
        "total_views": sum(int(f.get("uses_count") or 0) for f in forms),
        "public_count": sum(1 for f in forms if f.get("is_public")),
        "private_count": sum(1 for f in forms if not f.get("is_public")),
        "submissions": agg,
        "top_forms": top_forms,
    }


@api.get("/me/forms/{form_id}/analytics", tags=["Formulaires"])
async def me_form_analytics_detail(
    form_id: str,
    user: dict = Depends(_utilisateur_formulaires),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    await _require_owner_or_admin(form, user)

    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    agg = await _submissions_analytics({"form_id": form_id}, df, dt)
    views = int(form.get("uses_count") or 0)
    submissions = agg["total_submissions"]
    completion_rate = round((submissions / views) * 100, 1) if views > 0 else (100.0 if submissions > 0 else 0.0)

    # Most recent 10 submissions (trimmed)
    recent = await db.form_submissions.find(
        {"form_id": form_id},
        {"_id": 0, "id": 1, "user_label": 1, "anonymous": 1, "created_at": 1, "geo": 1, "respondent_email": 1},
    ).sort("created_at", -1).limit(10).to_list(10)

    return {
        "scope": "form",
        "form": {
            "id": form["id"],
            "number": form.get("number"),
            "title": form.get("title"),
            "is_public": bool(form.get("is_public")),
            "created_at": form.get("created_at"),
        },
        "views": views,
        "submissions": submissions,
        "completion_rate": completion_rate,
        "auth_count": agg["auth_count"],
        "anon_count": agg["anon_count"],
        "series": agg["series"],
        "by_country": agg["by_country"],
        "top_authors": agg["top_authors"],
        "recent": recent,
    }


# Iter34v — Tabular view of submissions for a form.
# Used by the UI to render submissions inline (instead of relying solely on
# the aggregated analytics) so the admin can confirm the data BEFORE exporting.
@api.get("/me/forms/{form_id}/submissions-table", tags=["Formulaires"])
async def me_form_submissions_table(
    form_id: str,
    user: dict = Depends(_utilisateur_formulaires),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    await _require_owner_or_admin(form, user)
    df = _parse_date(date_from); dt = _parse_date(date_to)
    match: Dict[str, Any] = {"form_id": form_id}
    rng: Dict[str, Any] = {}
    if df: rng["$gte"] = df.isoformat()
    if dt: rng["$lte"] = dt.isoformat()
    if rng:
        match["created_at"] = rng
    # Flatten the form pages into ordered (id, label) tuples for the columns
    columns: List[Dict[str, str]] = []
    seen = set()
    for page in (form.get("pages") or []):
        for field in (page.get("fields") or []):
            fid = field.get("id")
            if fid and fid not in seen:
                seen.add(fid)
                columns.append({"id": fid, "label": field.get("label") or fid, "type": field.get("type") or "text"})
    subs = await db.form_submissions.find(match, {"_id": 0}).sort("created_at", -1).to_list(limit)
    rows: List[Dict[str, Any]] = []
    for s in subs:
        ts = s.get("created_at")
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts or "")
        row: Dict[str, Any] = {
            "id": s.get("id"),
            "created_at": ts_str,
            "user_label": s.get("user_label") or "—",
            "anonymous": bool(s.get("anonymous")),
            "respondent_email": s.get("respondent_email") or "",
            "geo": s.get("geo") or {},
            "source_ip": s.get("source_ip") or "",
        }
        data = s.get("data") or {}
        for col in columns:
            v = data.get(col["id"])
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            row[col["id"]] = v
        rows.append(row)
    return {
        "form": {"id": form["id"], "number": form.get("number"), "title": form.get("title")},
        "columns": columns,
        "rows": rows,
        "total": len(rows),
    }


@api.get("/me/forms/{form_id}/analytics/export.csv", tags=["Formulaires"])
async def me_form_analytics_csv(
    form_id: str,
    user: dict = Depends(_utilisateur_formulaires),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """CSV export of all submissions for a form (flat answers + metadata)."""
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    await _require_owner_or_admin(form, user)

    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    match: Dict[str, Any] = {"form_id": form_id}
    rng: Dict[str, Any] = {}
    if df: rng["$gte"] = df.isoformat()
    if dt: rng["$lte"] = dt.isoformat()
    if rng:
        match["created_at"] = rng

    # Collect all field labels from pages
    labels: List[tuple] = []  # (field_id, label)
    seen = set()
    for page in (form.get("pages") or []):
        for field in (page.get("fields") or []):
            fid = field.get("id")
            if fid and fid not in seen:
                seen.add(fid)
                labels.append((fid, field.get("label") or fid))

    subs = await db.form_submissions.find(match, {"_id": 0}).sort("created_at", 1).to_list(10000)

    import csv, io
    buf = io.StringIO()
    writer = csv.writer(buf)
    header = ["id", "date", "auteur", "type", "email", "pays", "ville", "ip"] + [lab for _, lab in labels]
    writer.writerow(header)
    for s in subs:
        data = s.get("data") or {}
        geo = s.get("geo") or {}
        ts = s.get("created_at")
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts or "")
        row = [
            s.get("id", ""),
            ts_str,
            s.get("user_label", ""),
            "Anonyme" if s.get("anonymous") else "Authentifié",
            s.get("respondent_email") or "",
            geo.get("country") or geo.get("country_name") or "",
            geo.get("city") or "",
            s.get("source_ip") or "",
        ]
        for fid, _ in labels:
            v = data.get(fid, "")
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            row.append(v)
        writer.writerow(row)

    csv_bytes = buf.getvalue().encode("utf-8-sig")  # BOM for Excel
    filename = f"{(form.get('number') or form_id)}-submissions.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ====================================================================
# PHASE 5 — Notification badges on menu links


@api.post("/me/notifications/mark-seen", tags=["Portail Client"])
async def me_notifications_mark_seen(payload: MarkSeenRequest, user: dict = Depends(get_current_user)):
    """Mark a module as visited (resets its badge counter to 0)."""
    if payload.module not in MODULE_COUNT_QUERIES:
        raise HTTPException(status_code=400, detail=f"Module inconnu : {payload.module}")
    await db.user_module_visits.update_one(
        {"user_id": user["id"], "module": payload.module},
        {"$set": {"last_visited_at": _now()}},
        upsert=True,
    )
    return {"ok": True}
