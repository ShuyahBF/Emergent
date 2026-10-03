# server_parts/p01_sante_auth_public.py — Santé, authentification, pages publiques (catalogue, RDV, contact), jauge support, redirection Liluvine.
# Morceau de l'ancien server.py (lignes 1033 à 1838), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ====================================================================
# Health
# ====================================================================
@api.get("/", tags=["Santé"])
async def root():
    return {"service": "SAWALI SMART SYSTEMS API", "status": "ok", "time": _now()}


@api.get("/health", tags=["Santé"])
async def health():
    return {"status": "ok"}


@api.get("/version", tags=["Santé"])
async def version():
    """Iter43-fix24x (2026-06-16) — Version sequence auto-bumped on each deploy.

    The minor number after the dot is a sequential counter incremented every
    time the git HEAD commit changes (= a new deploy). Previously this was
    tied to `roadmap_actions` which rarely changed, so the UI always showed
    `v1.0`. The major number stays `1` (or whatever `APP_VERSION` env var
    overrides it to). The `git_sha` field is exposed for support / debug.
    Always returns 200, contains no secrets.
    """
    snap = await _bump_deployment_counter_if_needed()
    seq = int(snap.get("seq") or 0)
    env_ver = (os.environ.get("APP_VERSION") or "").strip()
    base = env_ver if env_ver else "1"
    return {
        "version": f"{base}.{seq}",
        "git_sha": (snap.get("git_head") or APP_GIT_SHA)[:7],
        "built_at": APP_BUILT_AT,
        "started_at": snap.get("deployed_at") or APP_STARTED_AT,
        "deploy_seq": seq,
    }


# ====================================================================
# AUTH — S045 Phase 1 (2026-02) : extracted to routes/auth.py for
# maintainability. The implementation is byte-for-byte identical — only
# the location changed. See /app/backend/routes/auth.py.
# ====================================================================
from routes.auth import attach_auth_routes  # noqa: E402
import maintenance_plateforme as _maintenance_plateforme  # noqa: E402  (lot 50)
import cycle_vie_abonnements as _cycle_vie_abonnements  # noqa: E402  (lot 51)
from auth import create_session_token  # noqa: E402  (lot 50)


async def _fermer_session_jeton(jeton: str) -> None:
    """Lot 50 — Déconnexion : ferme la session du compte portée par le jeton (s'il en a une)."""
    import sessions_comptes
    from auth import decode_token
    try:
        charge = decode_token(jeton)
    except Exception:  # noqa: BLE001 — jeton expiré ou invalide : rien à fermer
        return
    if charge.get("sid") and not charge.get("imp"):
        await sessions_comptes.fermer(charge["sid"], sessions_comptes.MOTIF_DECONNEXION)


async def _emit_login_event(user: dict, request) -> None:
    """2026-02 fork (P3a) — Fire the `user.login` automation event.
    Called from auth.verify-otp after a successful OTP validation. Kept as a
    thin wrapper so we can reference `_emit_event` at call time (it's defined
    later in this module) and centralise the context extraction.
    """
    try:
        ip = _client_ip_from_request(request) if request is not None else ""
        # 2026-02 fork iter106 — Etendre les tokens disponibles :
        # `identity` = full_name (ou fallback), `tracked_role` = rôle métier,
        # `linked_client` = société du tenant parent, `login_time` formaté FR.
        parent_id = user.get("parent_client_id") or ""
        linked_client = ""
        if parent_id:
            try:
                p = await db.users.find_one({"id": parent_id}, {"_id": 0, "company": 1, "full_name": 1, "email": 1}) or {}
                linked_client = (p.get("company") or p.get("full_name") or p.get("email") or "").strip()
            except Exception:  # noqa: BLE001
                linked_client = ""
        try:
            login_time_fmt = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
        except Exception:  # noqa: BLE001
            login_time_fmt = _now()
        extra_ctx = {
            "login_email": (user.get("email") or "").lower(),
            "login_full_name": user.get("full_name") or "",
            "login_role": user.get("role") or "",
            "login_tracked_role": user.get("tracked_role") or "",
            "login_ip": ip or "",
            "login_time": login_time_fmt,
            # 2026-02 fork iter106 — Alias / nouveaux tokens
            "identity": (user.get("full_name") or user.get("email") or "").strip(),
            "tracked_role": (user.get("tracked_role") or user.get("role") or "").strip(),
            "linked_client": linked_client,
        }
        # No client_id — automations for login events are typically
        # `target=fixed` (admin phone). We still pass the user's id so
        # `target_phone` fallbacks and audit tracking rows have context.
        target = {
            "client_id": user.get("parent_client_id") or None,
            "phone": (user.get("phone") or "").strip() or None,
            "extra_ctx": extra_ctx,
        }
        await _emit_event("user.login", target)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[user.login automation] emit failed: %s", exc)


attach_auth_routes(
    api,
    db=db,
    helpers={
        "verify_password": verify_password,
        "hash_password": hash_password,
        "verify_recaptcha": verify_recaptcha,
        "generate_otp": generate_otp,
        "generate_session_token": generate_session_token,
        "send_otp_email": send_otp_email,
        "create_access_token": create_access_token,
        "get_current_user": get_current_user,
        "_to_user_public": _to_user_public,
        "_uuid": _uuid,
        "_now": _now,
        # 2026-02 fork (P3a) — Login automation hook
        "emit_login_event": _emit_login_event,
        # Lot 50 — maintenance de la plateforme et sessions des comptes (limite d'appareils)
        "refuser_si_maintenance": _maintenance_plateforme.refuser_si_maintenance,
        "create_session_token": create_session_token,
        "fermer_session_jeton": _fermer_session_jeton,
        # Lot 51 — client suspendu (J+110) ou archivé (J+113) : connexion refusée
        "refuser_si_cycle_vie": _cycle_vie_abonnements.refuser_connexion,
    },
)

# S046 (2026-02) — i18n translations management.
from routes.i18n import attach_i18n_routes  # noqa: E402

attach_i18n_routes(api, db=db, get_current_user=get_current_user)


# ====================================================================
# PUBLIC - Content / Catalog / Contact / RDV
# ====================================================================
def _apply_content_lang(doc: dict, lang: Optional[str]) -> dict:
    """Iter40-content-i18n — Overlay per-language fields onto the default
    content document. When `lang` is falsy or no override exists for it,
    returns the document unchanged.

    Override shape (stored in `translations`):
      { "en": {"title": "...", "body_html": "...", "metadata": {...}}, ... }
    """
    if not lang:
        return doc
    translations = (doc or {}).get("translations") or {}
    override = translations.get(lang)
    if not override:
        return doc
    merged = dict(doc)
    if isinstance(override, dict):
        if override.get("title"):
            merged["title"] = override["title"]
        if "body_html" in override and override["body_html"] is not None:
            merged["body_html"] = override["body_html"]
        if isinstance(override.get("metadata"), dict):
            # Deep-merge for metadata so partial overrides (e.g. only `metrics`)
            # still inherit other admin-set fields.
            base_meta = dict(doc.get("metadata") or {})
            base_meta.update(override["metadata"])
            merged["metadata"] = base_meta
    merged["lang_applied"] = lang
    return merged


@api.get("/content", tags=["Public"])
async def list_content(lang: Optional[str] = None):
    items = await db.contents.find({}, {"_id": 0}).to_list(500)
    if lang:
        return [_apply_content_lang(it, lang) for it in items]
    return items


@api.get("/content/{slug}", tags=["Public"])
async def get_content(slug: str, lang: Optional[str] = None):
    item = await db.contents.find_one({"slug": slug}, {"_id": 0})
    if item is None:
        raise HTTPException(status_code=404, detail="Contenu introuvable")
    return _apply_content_lang(item, lang)


@api.get("/catalog", tags=["Public"])
async def public_catalog():
    items = await db.documents.find(
        {"category": "catalog", "is_public": True}, {"_id": 0}
    ).to_list(200)
    return items


@api.get("/public/documents", tags=["Public"])
async def public_documents():
    items = await db.documents.find({"is_public": True}, {"_id": 0}).to_list(500)
    return items


# ============================================================
# Iter38f — Public catalogue: list products flagged is_public=true.
# No auth required. Returns only safe display fields (no internal SKU
# notes, costs, stock, tenant_id). Grouped by category.
# ============================================================
_CATALOG_ANALYTICS: Optional[Dict[str, Any]] = None  # Iter38n — wired at the bottom of this file

@api.get("/public/products", tags=["Public"])
async def public_products(request: Request):
    cursor = db.products.find(
        {"is_public": True, "active": True, "deleted_at": None},
        {
            "_id": 0,
            "id": 1, "sku": 1, "name": 1, "description": 1, "category": 1,
            "unit": 1, "unit_price_ht": 1, "tva_pct": 1, "image_url": 1,
        },
    ).sort([("category", 1), ("name", 1)])
    items = [p async for p in cursor]
    # Group by category for the public UI (preserves alphabetical order)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for p in items:
        cat = (p.get("category") or "Autres").strip() or "Autres"
        groups.setdefault(cat, []).append(p)
    # Iter38n — Track anonymous catalog view (best-effort, never blocks)
    try:
        if _CATALOG_ANALYTICS:
            await _CATALOG_ANALYTICS["log_event"](
                "catalog_view", request=request,
            )
    except Exception:
        pass
    return {
        "count": len(items),
        "categories": [{"label": k, "items": v} for k, v in groups.items()],
    }


# ============================================================
# Iter38g — Open Graph share landing for a public product.
# When a customer shares https://sawalismartsystems.com/api/public/og/product/{id}
# on WhatsApp / Facebook / LinkedIn, the social bot gets a static HTML with
# rich Open Graph tags. A human browser auto-redirects to /catalogue.
# ============================================================
def _escape_html(s: Optional[str]) -> str:
    s = str(s or "")
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
         .replace('"', "&quot;").replace("'", "&#39;")
    )


@api.get("/public/og/product/{product_id}", tags=["Public"], response_class=HTMLResponse)
async def public_og_product(product_id: str, request: Request):
    p = await db.products.find_one(
        {"id": product_id, "is_public": True, "active": True, "deleted_at": None},
        {"_id": 0, "name": 1, "description": 1, "unit_price_ht": 1, "unit": 1, "image_url": 1, "sku": 1, "tenant_id": 1, "client_id": 1},
    )
    base = _public_base_url(request) or str(request.base_url).rstrip("/")
    target = f"{base}/catalogue"
    if not p:
        # Unknown product → redirect to the generic catalogue
        return HTMLResponse(
            f'<!doctype html><meta http-equiv="refresh" content="0;url={target}"><title>Catalogue</title>',
            status_code=200,
        )
    name = _escape_html(p.get("name"))
    desc = _escape_html(p.get("description") or "")
    price = int(round(float(p.get("unit_price_ht") or 0)))
    unit = _escape_html(p.get("unit") or "pièce")
    sku = _escape_html(p.get("sku") or "")
    img = p.get("image_url") or ""
    if img and not img.startswith("http"):
        img = f"{base}{'' if img.startswith('/') else '/'}{img}"
    if not img:
        # Lot 53 : logo servi par le site (l'ancienne image hébergée chez Emergent n'existe plus)
        img = f"{base}/logo.png"
    title = f"{name} — SAWALI SMART SYSTEMS"
    teaser = f"{price:,} FCFA HT / {unit}".replace(",", " ") + (f" — {desc[:140]}" if desc else "")
    quote_url = f"{base}/rdv?product={_escape_html(p.get('name'))}&sku={sku}"
    html = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta property="og:type" content="product">
<meta property="og:site_name" content="SAWALI SMART SYSTEMS">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{teaser}">
<meta property="og:image" content="{img}">
<meta property="og:url" content="{base}/api/public/og/product/{product_id}">
<meta property="og:locale" content="fr_FR">
<meta property="product:price:amount" content="{price}">
<meta property="product:price:currency" content="XOF">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{teaser}">
<meta name="twitter:image" content="{img}">
<meta http-equiv="refresh" content="0;url={target}">
<style>body{{font-family:system-ui;max-width:600px;margin:40px auto;padding:0 20px;text-align:center}}</style>
</head>
<body>
<h1>{name}</h1>
<p>{teaser}</p>
<p><a href="{target}">Voir le catalogue</a> · <a href="{quote_url}">Demander un devis</a></p>
</body>
</html>
"""
    # Iter38n — Track OG fetch event (best-effort)
    try:
        if _CATALOG_ANALYTICS:
            await _CATALOG_ANALYTICS["log_event"](
                "product_og_fetch",
                product_id=product_id,
                product_sku=p.get("sku"),
                product_name=p.get("name"),
                tenant_id=p.get("tenant_id") or p.get("client_id"),
                request=request,
            )
    except Exception:
        pass
    return HTMLResponse(html, status_code=200)



# ============================================================
# Support Technique — Load Gauge (0..7) — public + admin + webhook
# Mirrors the "cellular signal bars" UX so users instantly grasp the
# current support team load. Set via Admin UI or POST webhook.
# ============================================================
def _clamp_load(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return max(0, min(7, n))


@api.get("/public/support-load", tags=["Public"])
async def public_support_load():
    s = await db.settings.find_one({"_id": "global"}) or {}
    level = _clamp_load(s.get("support_load_level"))
    threshold = _clamp_load(s.get("liluvine_alert_threshold") or 6)
    liluvine_alert_enabled = bool(s.get("liluvine_alert_enabled"))
    alert_active = liluvine_alert_enabled and bool(s.get("support_load_enabled")) and level >= threshold and threshold > 0
    return {
        "enabled": bool(s.get("support_load_enabled")),
        "level": level,
        "label": s.get("support_load_label") or "",
        "updated_at": s.get("support_load_updated_at"),
        "liluvine": {
            "alert_enabled": liluvine_alert_enabled,
            "threshold": threshold,
            "alert_active": alert_active,
            "label": (s.get("liluvine_alert_label") or "").strip() if alert_active else None,
            "message": (s.get("liluvine_alert_message") or "").strip() if alert_active else None,
        },
    }


class AdminSupportLoadUpdate(BaseModel):
    level: int
    label: Optional[str] = None
    enabled: Optional[bool] = None


@api.post("/admin/support-load", tags=["Admin"])
async def admin_set_support_load(payload: AdminSupportLoadUpdate, user: dict = Depends(get_current_admin)):
    update: Dict[str, Any] = {
        "support_load_level": _clamp_load(payload.level),
        "support_load_updated_at": _now(),
        "support_load_updated_by": user.get("email"),
    }
    if payload.label is not None:
        update["support_load_label"] = (payload.label or "")[:140]
    if payload.enabled is not None:
        update["support_load_enabled"] = bool(payload.enabled)
    await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
    # Iter35x — Alexa voice notification when level reaches critical (>=6)
    new_level = update["support_load_level"]
    if new_level is not None and new_level >= 6:
        _alexa_notify_async(
            "support_load_critical",
            f"Niveau de support critique : {new_level} sur 7. {update.get('support_load_label') or ''}".strip(),
        )
    return {"ok": True, **update}


@api.api_route("/webhooks/support-load/{secret}", methods=["GET", "POST"], tags=["Webhooks"])
async def webhook_support_load(secret: str, request: Request):
    """External webhook to push the current support load (0..7).
    GET ?level=N[&label=...]  OR  POST JSON {level, label}.
    Useful from monitoring (Zabbix/Grafana/Freshdesk/Zendesk/n8n)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    expected = (s.get("support_load_webhook_secret") or "").strip()
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Secret invalide")
    level = None
    label = None
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        level = body.get("level") if isinstance(body, dict) else None
        label = body.get("label") if isinstance(body, dict) else None
    if level is None:
        level = request.query_params.get("level")
    if label is None:
        label = request.query_params.get("label")
    if level is None:
        raise HTTPException(status_code=400, detail="Paramètre 'level' requis (0..7)")
    update: Dict[str, Any] = {
        "support_load_level": _clamp_load(level),
        "support_load_updated_at": _now(),
        "support_load_updated_by": "webhook",
        "support_load_enabled": True,
    }
    if label is not None:
        update["support_load_label"] = (str(label) or "")[:140]
    await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
    # Iter35x — Alexa voice notification when level reaches critical (>=6)
    if update["support_load_level"] >= 6:
        _alexa_notify_async(
            "support_load_critical",
            f"Niveau de support critique : {update['support_load_level']} sur 7. {update.get('support_load_label') or ''}".strip(),
        )
    return {"ok": True, "level": update["support_load_level"], "label": update.get("support_load_label")}




# ============================================================
# Liluvine smart redirect — remote control via signed link or
# WhatsApp command. Generates short-lived HMAC tokens that can be
# bookmarked from the admin's mobile to flip the threshold/level
# without going through the login screen.
# ============================================================
def _liluvine_secret(s: Dict[str, Any]) -> str:
    """Return the per-install HMAC secret. Auto-generates one on first use."""
    sec = (s.get("liluvine_remote_secret") or "").strip()
    return sec


def _liluvine_sign(secret: str, payload: Dict[str, Any]) -> str:
    """Sign a JSON payload with HMAC-SHA256 → returns urlsafe base64 token."""
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{body}|{sig}".encode("utf-8")).decode("utf-8").rstrip("=")


def _liluvine_verify(secret: str, token: str) -> Optional[Dict[str, Any]]:
    if not token or not secret:
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        body, sig = raw.rsplit("|", 1)
        expected = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        data = json.loads(body)
        # Expiry check
        exp = data.get("exp")
        if exp and datetime.now(timezone.utc) > datetime.fromisoformat(str(exp).replace("Z", "+00:00")):
            return None
        return data
    except Exception:  # noqa: BLE001
        return None


class AdminRemoteLinkRequest(BaseModel):
    ttl_hours: Optional[int] = 720  # default 30 days


@api.post("/admin/liluvine/remote-link", tags=["Admin"])
async def admin_liluvine_remote_link(payload: AdminRemoteLinkRequest, request: Request, user: dict = Depends(get_current_admin)):
    """Génère un lien signé longue durée pour contrôler le seuil et le niveau Liluvine
    from a phone bookmark — without going through the login screen."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    secret = _liluvine_secret(s)
    if not secret:
        secret = secrets.token_urlsafe(32)
        await db.settings.update_one({"_id": "global"}, {"$set": {"liluvine_remote_secret": secret}}, upsert=True)
    ttl = max(1, min(int(payload.ttl_hours or 720), 24 * 365))
    exp = (datetime.now(timezone.utc) + timedelta(hours=ttl)).isoformat()
    token = _liluvine_sign(secret, {
        "scope": "liluvine",
        "issued_at": _now(),
        "issued_by": user.get("email"),
        "exp": exp,
    })
    base_url = str(request.base_url).rstrip("/")
    # The remote console is a public React route → use frontend base
    public_origin = request.headers.get("origin") or request.headers.get("referer") or base_url
    if "://" in public_origin:
        public_origin = "://".join(public_origin.split("://")[:1] + [public_origin.split("://")[1].split("/")[0]])
    url = f"{public_origin}/remote/support/{token}"
    return {"ok": True, "url": url, "token": token, "expires_at": exp}


class RemoteSupportUpdate(BaseModel):
    level: Optional[int] = None  # 0..7
    threshold: Optional[int] = None  # 0..7
    label: Optional[str] = None  # support_load_label (the "main gauge" label)


@api.get("/public/remote/support/{token}", tags=["Public"])
async def public_remote_support_state(token: str):
    """Inspecte la charge support actuelle + la config Liluvine — protégé par jeton HMAC."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    secret = _liluvine_secret(s)
    if not _liluvine_verify(secret, token):
        raise HTTPException(status_code=403, detail="Lien invalide ou expiré")
    return {
        "support_load_enabled": bool(s.get("support_load_enabled")),
        "support_load_level": _clamp_load(s.get("support_load_level")),
        "support_load_label": s.get("support_load_label") or "",
        "liluvine_alert_threshold": _clamp_load(s.get("liluvine_alert_threshold") or 6),
        "liluvine_alert_enabled": bool(s.get("liluvine_alert_enabled")),
        "alert_active": (
            bool(s.get("liluvine_alert_enabled"))
            and bool(s.get("support_load_enabled"))
            and _clamp_load(s.get("support_load_level")) >= _clamp_load(s.get("liluvine_alert_threshold") or 6)
        ),
        "updated_at": s.get("support_load_updated_at"),
    }


@api.post("/public/remote/support/{token}", tags=["Public"])
async def public_remote_support_update(token: str, payload: RemoteSupportUpdate, request: Request):
    s = await db.settings.find_one({"_id": "global"}) or {}
    secret = _liluvine_secret(s)
    verified = _liluvine_verify(secret, token)
    if not verified:
        raise HTTPException(status_code=403, detail="Lien invalide ou expiré")
    update: Dict[str, Any] = {"support_load_updated_at": _now(), "support_load_updated_by": f"remote-link({verified.get('issued_by') or 'admin'})"}
    if payload.level is not None:
        update["support_load_level"] = _clamp_load(payload.level)
        update["support_load_enabled"] = True
    if payload.threshold is not None:
        update["liluvine_alert_threshold"] = _clamp_load(payload.threshold)
    if payload.label is not None:
        update["support_load_label"] = (payload.label or "")[:140]
    if not any(k in update for k in ("support_load_level", "liluvine_alert_threshold", "support_load_label")):
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
    # Audit trail
    await db.api_traces.insert_one({
        "id": _uuid(), "method": "REMOTE_LILUVINE", "url": "/public/remote/support",
        "module": "liluvine-remote", "status": 200, "ip": _client_ip_from_request(request),
        "request_body": {**payload.model_dump(), "issued_by": verified.get("issued_by")},
        "created_at": _now(),
    })
    return {"ok": True, **{k: v for k, v in update.items() if not k.startswith("support_load_updated")}}


async def _try_handle_liluvine_wa_command(from_phone: str, message_text: str) -> Optional[str]:
    """When a WhatsApp message comes from an allow-listed admin phone and
    starts with `!seuil` or `!niveau` (or `!load`), tweak the gauge live.
    Returns a status string for logging or None if no command was found."""
    if not message_text:
        return None
    text = message_text.strip()
    m = re.match(r"^[!/](?:seuil|niveau|level|threshold|load)\s+(-?\d+)\b\s*(.*)$", text, re.IGNORECASE)
    if not m:
        return None
    s = await db.settings.find_one({"_id": "global"}) or {}
    allowed = s.get("liluvine_remote_admin_phones") or []
    digits = "".join(ch for ch in (from_phone or "") if ch.isdigit())
    allowed_norm = {"".join(ch for ch in str(p) if ch.isdigit()) for p in allowed if p}
    if digits not in allowed_norm:
        return f"refused:{digits}"
    n = _clamp_load(m.group(1))
    extra = (m.group(2) or "").strip()
    cmd = re.match(r"^[!/](\w+)", text).group(1).lower()
    update: Dict[str, Any] = {"support_load_updated_at": _now(), "support_load_updated_by": f"wa({digits})"}
    if cmd in ("seuil", "threshold"):
        update["liluvine_alert_threshold"] = n
    else:
        update["support_load_level"] = n
        update["support_load_enabled"] = True
        if extra:
            update["support_load_label"] = extra[:140]
    await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
    await db.api_traces.insert_one({
        "id": _uuid(), "method": "WA_LILUVINE", "url": "/whatsapp/webhook",
        "module": "liluvine-wa-cmd", "status": 200,
        "request_body": {"cmd": cmd, "value": n, "from": digits, "extra": extra},
        "created_at": _now(),
    })
    return f"ok:{cmd}={n}"





@api.get("/company-info", tags=["Public"])
async def company_info():
    s = await db.settings.find_one({"_id": "global"}) or {}
    return {
        "name": "SAWALI SMART SYSTEMS",
        "tagline": "Software Engineering",
        "email": s.get("company_email") or "contact@sawalismartsystems.com",
        "phone": s.get("company_phone") or "+228 00 00 00 00",
        "whatsapp": s.get("company_whatsapp") or "",
        "address": s.get("company_address") or "",
        "city": s.get("company_city") or "",
        "country": s.get("company_country") or "",
        "business_open_time": s.get("business_open_time", "09:00"),
        "business_close_time": s.get("business_close_time", "18:00"),
        "business_days": s.get("business_days", [0, 1, 2, 3, 4]),
        "slot_duration_min": s.get("slot_duration_min", 30),
        "hero_video": {
            "enabled": bool(s.get("hero_video_enabled", False)),
            "url": s.get("hero_video_url"),
            "title": s.get("hero_video_title"),
            "description": s.get("hero_video_description"),
            "autoplay": bool(s.get("hero_video_autoplay", True)),
            "loop": bool(s.get("hero_video_loop", True)),
            "muted": bool(s.get("hero_video_muted", True)),
            "poster_url": s.get("hero_video_poster_url"),
        },
        "assistant": {
            "enabled": bool(s.get("assistant_enabled", False)),
            "url": s.get("assistant_url"),
            "label": s.get("assistant_label") or "Assistant Support",
            "color": s.get("assistant_color") or "#0075E3",
        },
        "portal_features": {
            "show_reports_button": bool(s.get("show_reports_button", True)),
            "show_suivis_button": bool(s.get("show_suivis_button", True)),
        },
        "incident_banner": {
            "enabled": bool(s.get("incident_banner_enabled", False)),
            "severity": s.get("incident_banner_severity") or "warning",
            "message": s.get("incident_banner_message") or "",
            "link_url": s.get("incident_banner_link_url") or "",
            "link_label": s.get("incident_banner_link_label") or "",
            "updated_at": s.get("incident_banner_updated_at"),
        },
        "version_stamp": {
            "color": s.get("version_stamp_color") or "",
            "size": s.get("version_stamp_size") or "xs",
            "opacity": int(s.get("version_stamp_opacity") or 70),
            "style": s.get("version_stamp_style") or "normal",
        },
        "policy": {
            "contacts_require_tag": bool(s.get("contacts_require_tag", False)),
        },
    }


@api.post("/contact", tags=["Public"])
async def submit_contact(payload: ContactCreate):
    doc = {
        "id": _uuid(),
        **payload.model_dump(),
        "status": "new",
        "created_at": _now(),
    }
    await db.contacts.insert_one(doc.copy())
    doc.pop("_id", None)
    return {"ok": True, "id": doc["id"]}


# ----- RDV availability + booking ------
async def _check_slot_available(scheduled_at: str, duration_min: int, exclude_id: Optional[str] = None) -> tuple[bool, str]:
    """Verify the requested slot is within business hours and not taken.
    If exclude_id is provided, that appointment is excluded from the overlap check
    (used when rescheduling an existing appointment)."""
    try:
        start_dt = datetime.fromisoformat(scheduled_at)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return False, "Format de date/heure invalide"

    if start_dt < datetime.now(timezone.utc):
        return False, "Le créneau est dans le passé"

    s = await db.settings.find_one({"_id": "global"}) or {}
    open_t = s.get("business_open_time", "09:00")
    close_t = s.get("business_close_time", "18:00")
    days = s.get("business_days", [0, 1, 2, 3, 4])

    if start_dt.weekday() not in days:
        return False, "Jour non ouvré"
    open_h, open_m = (int(x) for x in open_t.split(":"))
    close_h, close_m = (int(x) for x in close_t.split(":"))
    local = start_dt
    minutes_in_day = local.hour * 60 + local.minute
    open_min = open_h * 60 + open_m
    close_min = close_h * 60 + close_m
    if minutes_in_day < open_min or (minutes_in_day + duration_min) > close_min:
        return False, "Hors des heures ouvrables"

    end_dt = start_dt + timedelta(minutes=duration_min)
    # Look for overlapping non-cancelled appointments within a 24h window
    window_start = (start_dt - timedelta(days=1)).isoformat()
    window_end = (end_dt + timedelta(days=1)).isoformat()
    existing = await db.appointments.find(
        {
            "status": {"$in": ["pending", "confirmed"]},
            "scheduled_at": {"$gte": window_start, "$lte": window_end},
            **({"id": {"$ne": exclude_id}} if exclude_id else {}),
        },
        {"_id": 0, "scheduled_at": 1, "duration_min": 1},
    ).to_list(500)
    for a in existing:
        a_start = datetime.fromisoformat(a["scheduled_at"])
        if a_start.tzinfo is None:
            a_start = a_start.replace(tzinfo=timezone.utc)
        a_end = a_start + timedelta(minutes=int(a.get("duration_min", 30)))
        if a_start < end_dt and a_end > start_dt:
            return False, "Créneau déjà réservé"

    # Optional GCal busy check
    try:
        busy = await gcal.freebusy(start_dt.isoformat(), end_dt.isoformat())
        for b in busy:
            b_start = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
            b_end = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
            if b_start < end_dt and b_end > start_dt:
                return False, "Créneau occupé sur le calendrier Google"
    except Exception:
        pass

    return True, "ok"


@api.get("/availability", tags=["Public"])
async def availability(date: str = Query(..., description="YYYY-MM-DD")):
    """Renvoie la liste des créneaux libres/occupés pour une date donnée."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    open_t = s.get("business_open_time", "09:00")
    close_t = s.get("business_close_time", "18:00")
    days = s.get("business_days", [0, 1, 2, 3, 4])
    slot_min = int(s.get("slot_duration_min", 30))

    try:
        day = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="Format date invalide")
    if day.weekday() not in days:
        return {"date": date, "slots": [], "is_business_day": False}

    oh, om = (int(x) for x in open_t.split(":"))
    ch, cm = (int(x) for x in close_t.split(":"))
    start = day.replace(hour=oh, minute=om, second=0, microsecond=0)
    end = day.replace(hour=ch, minute=cm, second=0, microsecond=0)

    # Pre-load taken intervals for the requested day only
    appts = await db.appointments.find(
        {
            "status": {"$in": ["pending", "confirmed"]},
            "scheduled_at": {"$gte": start.isoformat(), "$lte": end.isoformat()},
        },
        {"_id": 0, "scheduled_at": 1, "duration_min": 1},
    ).to_list(500)
    intervals: list[tuple[datetime, datetime]] = []
    for a in appts:
        a_start = datetime.fromisoformat(a["scheduled_at"])
        if a_start.tzinfo is None:
            a_start = a_start.replace(tzinfo=timezone.utc)
        a_end = a_start + timedelta(minutes=int(a.get("duration_min", 30)))
        intervals.append((a_start, a_end))

    try:
        busy = await gcal.freebusy(start.isoformat(), end.isoformat())
        for b in busy:
            b_s = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
            b_e = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
            intervals.append((b_s, b_e))
    except Exception:
        pass

    slots = []
    cur = start
    now = datetime.now(timezone.utc)
    while cur + timedelta(minutes=slot_min) <= end:
        slot_end = cur + timedelta(minutes=slot_min)
        taken = cur < now or any(s_ < slot_end and e_ > cur for s_, e_ in intervals)
        slots.append(
            {
                "start": cur.isoformat(),
                "end": slot_end.isoformat(),
                "available": not taken,
            }
        )
        cur = slot_end
    return {"date": date, "slots": slots, "is_business_day": True, "slot_duration_min": slot_min}


@api.post("/appointments/public", tags=["Public"])
async def create_public_appointment(payload: PublicAppointmentRequest):
    ok, reason = await _check_slot_available(payload.scheduled_at, payload.duration_min)
    if not ok:
        raise HTTPException(status_code=409, detail=reason)
    doc = {
        "id": _uuid(),
        "client_id": None,
        **payload.model_dump(),
        "status": "pending",
        "notes": None,
        "gcal_event_id": None,
        "created_at": _now(),
    }
    # GCal sync
    end_iso = (
        datetime.fromisoformat(payload.scheduled_at).replace(tzinfo=timezone.utc)
        + timedelta(minutes=payload.duration_min)
    ).isoformat()
    event_id = await gcal.create_event(
        summary=f"RDV (public) : {payload.subject}",
        description=f"Demandé par {payload.name} <{payload.email}>\n{payload.message or ''}",
        start_iso=payload.scheduled_at,
        end_iso=end_iso,
        attendee_email=payload.email,
    )
    doc["gcal_event_id"] = event_id
    await db.appointments.insert_one(doc.copy())
    doc.pop("_id", None)
    return {"ok": True, "appointment": doc}
