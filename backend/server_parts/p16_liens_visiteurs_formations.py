# server_parts/p16_liens_visiteurs_formations.py — Liens cryptés, suivi des visiteurs, formations.
# Morceau de l'ancien server.py (lignes 21181 à 21843), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ====================================================================
# PHASE 2 — Deep-links cryptés pour intégrations externes (Windows apps)
# URL pattern : {PUBLIC_BASE_URL}/launch?t=<jwt>
# Token claims : {action, client_code, username, target_id?, iat, exp}
# Signed with LINK_JWT_SECRET (separate from auth JWT to avoid token confusion).
# ====================================================================
import jwt as _pyjwt_links

LINK_JWT_SECRET = os.environ.get("LINK_JWT_SECRET") or (os.environ.get("JWT_SECRET", "fallback-insecure") + "-link")
LINK_JWT_ALGO = "HS256"
LINK_DEFAULT_TTL_SECONDS = 15 * 60  # 15 minutes
LINK_ACTIONS = {
    "login": "Connexion au portail",
    "rdv": "Demande / prise de RDV",
    "appointments": "Liste des RDV",
    "document": "Espace documents",
    "intervention": "Espace interventions",
    "contact": "Formulaire de contact",
    "dashboard": "Tableau de bord portail",
    "formations": "Formations spécialisées",
    "note": "Rapports et suivis",
    "status": "Page d'état /uptime",
}


class BuildLinkRequest(BaseModel):
    action: str
    client_code: Optional[str] = None
    username: Optional[str] = None
    target_id: Optional[str] = None
    ttl_seconds: Optional[int] = None


@api.get("/integrations/link-actions", tags=["Admin"])
async def integrations_link_actions(_: dict = Depends(get_current_admin)):
    """Liste les actions deep-link supportées pour le dropdown admin UI."""
    return [{"value": k, "label": v} for k, v in LINK_ACTIONS.items()]


@api.post("/integrations/build-link", tags=["Admin"])
async def integrations_build_link(request: Request, payload: BuildLinkRequest, user: dict = Depends(get_current_admin)):
    # Lot 25 — L'écran « Liens cryptés » est réservé au super-admin SAWALI
    # (SUPER_ADMIN_EMAIL) : un simple compte admin ne peut plus fabriquer de lien.
    if not _is_super_admin(user):
        raise HTTPException(status_code=403, detail="Création de liens cryptés réservée au super-administrateur SAWALI")
    action = (payload.action or "").strip().lower()
    if action not in LINK_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Action inconnue. Options : {', '.join(LINK_ACTIONS.keys())}")
    ttl = payload.ttl_seconds if payload.ttl_seconds and payload.ttl_seconds > 0 else LINK_DEFAULT_TTL_SECONDS
    ttl = min(ttl, 24 * 3600)  # hard cap 24h to prevent abuse
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "action": action,
        "client_code": (payload.client_code or "").strip() or None,
        "username": (payload.username or "").strip() or None,
        "target_id": (payload.target_id or "").strip() or None,
        "iat": now,
        "exp": now + ttl,
    }
    token = _pyjwt_links.encode(claims, LINK_JWT_SECRET, algorithm=LINK_JWT_ALGO)
    # Use the host the admin is actually browsing from (production vs preview)
    # rather than the static PUBLIC_BASE_URL env value.
    base = _public_base_url(request) or (PUBLIC_BASE_URL or "").rstrip("/")
    url = f"{base}/launch?t={token}" if base else f"/launch?t={token}"
    return {
        "token": token,
        "url": url,
        "expires_at": datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat(),
        "ttl_seconds": ttl,
        "action": action,
        "action_label": LINK_ACTIONS[action],
    }


@api.get("/integrations/resolve-link", tags=["Public"])
async def integrations_resolve_link(t: str):
    """Endpoint public — décode un jeton de lien, renvoie ses claims pour que la SPA
    can redirect the user to the right route. Never raises on bad tokens;
    returns {valid: false, reason}."""
    try:
        claims = _pyjwt_links.decode(t, LINK_JWT_SECRET, algorithms=[LINK_JWT_ALGO])
    except _pyjwt_links.ExpiredSignatureError:
        return {"valid": False, "reason": "expired"}
    except Exception:
        return {"valid": False, "reason": "invalid"}
    action = claims.get("action")
    if action not in LINK_ACTIONS:
        return {"valid": False, "reason": "invalid_action"}
    return {
        "valid": True,
        "action": action,
        "action_label": LINK_ACTIONS[action],
        "client_code": claims.get("client_code"),
        "username": claims.get("username"),
        "target_id": claims.get("target_id"),
        "expires_at": datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat() if claims.get("exp") else None,
    }


# ====================================================================
# VISITOR TRACKING (with optional forward to external REST endpoint)
# ====================================================================
# In-memory cache for geo lookups — avoids hitting ip-api.com on every
# request and surviving short outages.
_GEO_CACHE: dict[str, dict] = {}
_GEO_CACHE_MAX = 5000


async def _resolve_geo(ip: str) -> dict:
    """Resolve country/city from IP via free ip-api.com (rate-limited but no key)."""
    if not ip or ip.startswith(("127.", "10.", "192.168.", "172.")) or ip == "::1":
        return {"country": "", "city": "", "region": ""}
    if ip in _GEO_CACHE:
        return _GEO_CACHE[ip]
    try:
        import httpx
        # Aggressive 1.5 s timeout — ip-api.com is best-effort, we never want it
        # to block the request pipeline.
        async with httpx.AsyncClient(timeout=1.5) as cli:
            r = await cli.get(f"http://ip-api.com/json/{ip}?fields=country,regionName,city,status")
            d = r.json()
            if d.get("status") == "success":
                geo = {"country": d.get("country", ""), "city": d.get("city", ""), "region": d.get("regionName", "")}
                # Trivial LRU-ish: drop a random entry if cache is full
                if len(_GEO_CACHE) >= _GEO_CACHE_MAX:
                    try:
                        _GEO_CACHE.pop(next(iter(_GEO_CACHE)))
                    except StopIteration:
                        pass
                _GEO_CACHE[ip] = geo
                return geo
    except Exception as e:
        logger.warning("GeoIP lookup failed for %s: %s", ip, e)
    fallback = {"country": "", "city": "", "region": ""}
    _GEO_CACHE[ip] = fallback  # cache miss too — avoid retrying broken IPs
    return fallback


async def _enrich_visit_geo(visit_id: str, ip: str) -> None:
    """Resolve geo info AFTER the response has been sent and patch the visit document."""
    geo = await _resolve_geo(ip)
    if geo.get("country") or geo.get("city"):
        try:
            await db.visits.update_one({"id": visit_id}, {"$set": geo})
        except Exception as e:
            logger.warning("Geo enrichment write failed for %s: %s", visit_id, e)


@api.post("/track", tags=["Public"])
async def track_visit(request: Request, payload: dict):
    """Enregistre une visite et la transmet (si configuré) à l'API REST externe.
    Geo enrichment is performed in the background so /track always returns instantly.
    """
    # Resolve client IP
    # Lot 55 — fonction unique (ip_client.py) ; X-Real-IP gardé en dernier recours
    from ip_client import ip_reelle
    ip = ip_reelle(request) if request.headers.get("x-forwarded-for") else ""
    if not ip:
        ip = request.headers.get("x-real-ip", "") or ip_reelle(request)

    # Use cached geo if known, otherwise blank — we'll fill in async.
    geo = _GEO_CACHE.get(ip) or {"country": "", "city": "", "region": ""}
    event = {
        "id": _uuid(),
        "datetime": _now(),
        "ip": ip,
        "country": geo["country"],
        "city": geo["city"],
        "region": geo["region"],
        "page": payload.get("page") or "/",
        "referrer": payload.get("referrer") or "",
        "user_agent": request.headers.get("user-agent", ""),
        "session_id": payload.get("session_id") or "",
    }
    # Store locally (capped)
    await db.visits.insert_one(event.copy())
    event.pop("_id", None)

    # Schedule geo enrichment in background only when needed (fire-and-forget)
    if ip and not (geo.get("country") or geo.get("city")):
        asyncio.create_task(_enrich_visit_geo(event["id"], ip))

    # Optional forward to external REST endpoint — fire-and-forget so a slow
    # third-party never blocks /track from returning.
    s = await db.settings.find_one({"_id": "global"}) or {}
    if s.get("tracking_enabled") and s.get("tracking_base_url"):
        forward_url = s["tracking_base_url"].rstrip("/") + "/" + (s.get("tracking_endpoint") or "").lstrip("/")
        async def _fwd():
            try:
                import httpx
                headers = {"Content-Type": "application/json"}
                if s.get("tracking_auth_header"):
                    headers["Authorization"] = s["tracking_auth_header"]
                async with httpx.AsyncClient(timeout=3) as cli:
                    await cli.post(forward_url, json=event, headers=headers)
            except Exception as e:
                logger.warning("Tracking forward failed: %s", e)
        asyncio.create_task(_fwd())
    return {"ok": True, "id": event["id"], "geo": geo}


@api.get("/admin/visits", tags=["Admin"])
async def admin_list_visits(limit: int = 200, _: dict = Depends(get_current_admin)):
    items = await db.visits.find({}, {"_id": 0}).to_list(limit)
    return sorted(items, key=lambda x: x["datetime"], reverse=True)


@api.get("/admin/visits/stats", tags=["Admin"])
async def admin_visits_stats(_: dict = Depends(get_current_admin)):
    # Use Mongo aggregation instead of loading 50k docs into Python.
    pipeline_country = [
        {"$group": {"_id": {"$ifNull": ["$country", "Inconnu"]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    pipeline_pages = [
        {"$group": {"_id": {"$ifNull": ["$page", "/"]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    total_doc = await db.visits.estimated_document_count()
    countries = await db.visits.aggregate(pipeline_country).to_list(20)
    pages = await db.visits.aggregate(pipeline_pages).to_list(20)
    unique_countries = await db.visits.distinct("country", {"country": {"$nin": [None, ""]}})
    return {
        "total": total_doc,
        "unique_countries": len([c for c in unique_countries if c]),
        "top_countries": [{"country": c["_id"] or "Inconnu", "count": c["count"]} for c in countries],
        "top_pages": [{"page": p["_id"] or "/", "count": p["count"]} for p in pages],
    }


@api.get("/visits/count", tags=["Public"])
async def public_visit_count():
    """Total visit counter for the public homepage. Includes admin-tunable offset."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    if s.get("visits_counter_enabled") is False:
        return {"enabled": False, "count": 0}
    real = await db.visits.count_documents({})
    offset = int(s.get("visits_counter_offset") or 0)
    return {"enabled": True, "count": max(0, real + offset)}


@api.get("/visits/trend", tags=["Public"])
async def public_visit_trend(days: int = 7):
    """Daily visit counts for the last N days (default 7), oldest first.
    Used by the homepage ticker sparkline.
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    if s.get("visits_counter_enabled") is False:
        return {"enabled": False, "days": []}
    days = max(2, min(days, 30))
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    cursor = db.visits.find(
        {"datetime": {"$gte": start.isoformat()}},
        {"_id": 0, "datetime": 1},
    )
    items = await cursor.to_list(50000)
    buckets = {(start + timedelta(days=i)).isoformat(): 0 for i in range(days)}
    for v in items:
        dt = (v.get("datetime") or "")[:10]
        if dt in buckets:
            buckets[dt] += 1
    series = [{"date": k, "count": v} for k, v in sorted(buckets.items())]
    return {"enabled": True, "days": series, "total": sum(b["count"] for b in series)}


@api.post("/admin/visits/reset", tags=["Admin"])
async def admin_reset_visit_counter(payload: Dict[str, Any] = Body(default={}), _: dict = Depends(get_current_admin)):
    """Resets the publicly displayed visits counter to zero (real visits
    remain in DB by default — only the offset moves).

    Iter34i: When `purge_access_logs=true`, also wipes `db.access_logs` and
    `db.visits` so the platform restarts from a clean analytics slate. The
    setting `usage_reset_at` is recorded so the UI can show "Compteur réinitialisé
    le …" rather than confusing the admin with stale histograms."""
    purge = bool(payload.get("purge_access_logs"))
    real = await db.visits.count_documents({})
    access_log_count = 0
    if purge:
        access_log_count = await db.access_logs.count_documents({})
        await db.access_logs.delete_many({})
        await db.visits.delete_many({})
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"visits_counter_offset": 0, "usage_reset_at": _now(), "updated_at": _now()}},
            upsert=True,
        )
        return {"ok": True, "displayed_count": 0, "real_count": 0, "purged_visits": real, "purged_access_logs": access_log_count}
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {"visits_counter_offset": -real, "updated_at": _now()}},
        upsert=True,
    )
    return {"ok": True, "displayed_count": 0, "real_count": real, "purged_visits": 0, "purged_access_logs": 0}


# ====================================================================
# FORMATIONS — admin CRUD + tracked-user portal access
# ====================================================================
def _is_tracked_user(user: dict) -> bool:
    return bool(user.get("tracked_user_id"))


def _formation_state_from_progress(modules_total: int, modules_seen: int, last_access_iso: Optional[str], current_state: Optional[str]) -> str:
    """Compute the formation state from the user's progress.

    Rules :
    - "annulée" set by admin → never auto-changed back.
    - 0 module seen → "inscription".
    - 1 ≤ seen < total/2 → "commencée".
    - total/2 ≤ seen < total → "en_cours".
    - seen >= total → "terminée".
    - 7+ days since last_access → "suspendue" (unless terminée or annulée).
    """
    if current_state == "annulée":
        return "annulée"
    if modules_total <= 0:
        return current_state or "inscription"
    if modules_seen <= 0:
        new = "inscription"
    elif modules_seen >= modules_total:
        new = "terminée"
    elif modules_seen < max(1, modules_total // 2):
        new = "commencée"
    else:
        new = "en_cours"
    if new not in ("terminée", "annulée") and last_access_iso:
        try:
            last = datetime.fromisoformat(last_access_iso)
            if (datetime.now(timezone.utc) - last).total_seconds() > 7 * 24 * 3600:
                new = "suspendue"
        except Exception:
            pass
    return new


async def _refresh_enrollment_state(enr: dict) -> dict:
    """Recompute state + counts; returns enrollment with refreshed values (without DB write)."""
    modules_total = await db.formation_modules.count_documents({"formation_id": enr["formation_id"]})
    seen = set(enr.get("modules_seen") or [])
    modules_seen = len(seen)
    new_state = _formation_state_from_progress(modules_total, modules_seen, enr.get("last_access"), enr.get("state"))
    enr["modules_total"] = modules_total
    enr["modules_seen_count"] = modules_seen
    enr["state"] = new_state
    return enr


@api.get("/admin/formations", tags=["Admin"])
async def admin_list_formations(_: dict = Depends(get_current_admin)):
    items = await db.formations.find({}, {"_id": 0}).sort("created_at", -1).to_list(2000)
    for it in items:
        it["modules_count"] = await db.formation_modules.count_documents({"formation_id": it["id"]})
        it["enrolled_count"] = await db.formation_enrollments.count_documents({"formation_id": it["id"]})
    return items


@api.post("/admin/formations", tags=["Admin"])
async def admin_create_formation(payload: FormationCreate, user: dict = Depends(get_current_admin)):
    doc = {"id": _uuid(), **payload.model_dump(), "created_by_id": user["id"], "created_at": _now(), "updated_at": _now()}
    await db.formations.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/formations/{fid}", tags=["Admin"])
async def admin_update_formation(fid: str, payload: FormationUpdate, _: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    res = await db.formations.update_one({"id": fid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Formation introuvable")
    return {"ok": True}


@api.delete("/admin/formations/{fid}", tags=["Admin"])
async def admin_delete_formation(fid: str, _: dict = Depends(get_current_admin)):
    await db.formations.delete_one({"id": fid})
    await db.formation_modules.delete_many({"formation_id": fid})
    await db.formation_enrollments.delete_many({"formation_id": fid})
    await db.formation_visits.delete_many({"formation_id": fid})
    return {"ok": True}


# Modules
@api.get("/admin/formations/{fid}/modules", tags=["Admin"])
async def admin_list_modules(fid: str, _: dict = Depends(get_current_admin)):
    items = await db.formation_modules.find({"formation_id": fid}, {"_id": 0}).sort("order", 1).to_list(500)
    return items


@api.post("/admin/formations/{fid}/modules", tags=["Admin"])
async def admin_create_module(fid: str, payload: FormationModuleCreate, _: dict = Depends(get_current_admin)):
    formation = await db.formations.find_one({"id": fid}, {"_id": 0})
    if not formation:
        raise HTTPException(status_code=404, detail="Formation introuvable")
    doc = {"id": _uuid(), "formation_id": fid, **payload.model_dump(), "created_at": _now(), "updated_at": _now()}
    await db.formation_modules.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/formations/{fid}/modules/{mid}", tags=["Admin"])
async def admin_update_module(fid: str, mid: str, payload: FormationModuleUpdate, _: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    res = await db.formation_modules.update_one({"id": mid, "formation_id": fid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Module introuvable")
    return {"ok": True}


@api.delete("/admin/formations/{fid}/modules/{mid}", tags=["Admin"])
async def admin_delete_module(fid: str, mid: str, _: dict = Depends(get_current_admin)):
    await db.formation_modules.delete_one({"id": mid, "formation_id": fid})
    return {"ok": True}


@api.get("/admin/formations/{fid}/enrollments", tags=["Admin"])
async def admin_list_enrollments(fid: str, _: dict = Depends(get_current_admin)):
    items = await db.formation_enrollments.find({"formation_id": fid}, {"_id": 0}).to_list(5000)
    for it in items:
        await _refresh_enrollment_state(it)
    return items


@api.post("/admin/formations/{fid}/enrollments/{user_id}/credits", tags=["Admin"])
async def admin_adjust_credits(fid: str, user_id: str, payload: FormationCreditsUpdate, _: dict = Depends(get_current_admin)):
    enr = await db.formation_enrollments.find_one({"formation_id": fid, "user_id": user_id}, {"_id": 0})
    if not enr:
        raise HTTPException(status_code=404, detail="Inscription introuvable")
    delta = int(payload.credits_delta)
    new_purchased = max(0, int(enr.get("credits_purchased") or 0) + max(delta, 0))
    new_consumed = int(enr.get("credits_consumed") or 0)
    if delta < 0:
        new_consumed = max(0, new_consumed + abs(delta))  # interpret negative as "consume"
    await db.formation_enrollments.update_one(
        {"id": enr["id"]},
        {"$set": {
            "credits_purchased": new_purchased,
            "credits_consumed": new_consumed,
            "credits_available": max(0, new_purchased - new_consumed),
            "updated_at": _now(),
        }},
    )
    return {"ok": True}


@api.post("/admin/formations/{fid}/enrollments/{user_id}/state", tags=["Admin"])
async def admin_set_enrollment_state(fid: str, user_id: str, payload: FormationStateUpdate, _: dict = Depends(get_current_admin)):
    if payload.state not in ("annulée", "en_cours", "suspendue"):
        raise HTTPException(status_code=400, detail="État manuel autorisé : annulée, en_cours, suspendue")
    res = await db.formation_enrollments.update_one(
        {"formation_id": fid, "user_id": user_id},
        {"$set": {"state": payload.state, "updated_at": _now()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Inscription introuvable")
    return {"ok": True}


# ====================================================================
# PORTAL — Formations (tracked users, plus elevated cross-view)
# ====================================================================
@api.get("/me/formations", tags=["Portail Client"])
async def me_list_formations(user: dict = Depends(get_current_user)):
    if not (_is_tracked_user(user) or _is_elevated_creator(user)):
        raise HTTPException(status_code=403, detail="Accès réservé aux utilisateurs suivis")
    formations = await db.formations.find({}, {"_id": 0}).sort("name", 1).to_list(500)
    out = []
    for f in formations:
        if not f.get("available") and not _is_elevated_creator(user):
            continue
        # 2026-02 fork (P5) — enforce access_client_ids gate (admin bypass)
        if not _item_accessible_by_tenant(f, user):
            continue
        modules_total = await db.formation_modules.count_documents({"formation_id": f["id"]})
        enr = await db.formation_enrollments.find_one({"formation_id": f["id"], "user_id": user["id"]}, {"_id": 0})
        if enr:
            enr = await _refresh_enrollment_state(enr)
        rating = await db.ratings.find_one(
            {"kind": "formations", "target_id": f["id"], "rated_by_user_id": user["id"]}, {"_id": 0}
        )
        out.append({
            **f,
            "modules_total": modules_total,
            "enrollment": enr,
            "my_rating": ({"stars": rating["stars"], "comment": rating.get("comment")} if rating else None),
        })
    return out


@api.post("/me/formations/{fid}/enroll", tags=["Portail Client"])
async def me_enroll_formation(fid: str, user: dict = Depends(get_current_user)):
    if not _is_tracked_user(user):
        raise HTTPException(status_code=403, detail="Inscription réservée aux utilisateurs suivis")
    formation = await db.formations.find_one({"id": fid}, {"_id": 0})
    if not formation or not formation.get("available", True):
        raise HTTPException(status_code=404, detail="Formation indisponible")
    # 2026-02 fork (P5) — enforce access_client_ids gate on enroll
    if not _item_accessible_by_tenant(formation, user):
        raise HTTPException(status_code=403, detail="Formation non accessible pour votre organisation")
    existing = await db.formation_enrollments.find_one({"formation_id": fid, "user_id": user["id"]}, {"_id": 0})
    if existing:
        return existing
    doc = {
        "id": _uuid(),
        "formation_id": fid,
        "user_id": user["id"],
        "user_email": user["email"],
        "user_name": user.get("full_name"),
        "state": "inscription",
        "credits_purchased": int(formation.get("default_credits") or 0),
        "credits_consumed": 0,
        "credits_available": int(formation.get("default_credits") or 0),
        "modules_seen": [],
        "total_time_ms": 0,
        "last_access": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.formation_enrollments.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.get("/me/formations/{fid}", tags=["Portail Client"])
async def me_get_formation(fid: str, user: dict = Depends(get_current_user)):
    formation = await db.formations.find_one({"id": fid}, {"_id": 0})
    if not formation:
        raise HTTPException(status_code=404, detail="Formation introuvable")
    if not (_is_tracked_user(user) or _is_elevated_creator(user)):
        raise HTTPException(status_code=403, detail="Accès réservé")
    # 2026-02 fork (P5) — enforce access_client_ids gate (admin bypass inside helper)
    if not _item_accessible_by_tenant(formation, user):
        raise HTTPException(status_code=403, detail="Formation non accessible pour votre organisation")
    modules = await db.formation_modules.find({"formation_id": fid}, {"_id": 0}).sort("order", 1).to_list(500)
    enr = await db.formation_enrollments.find_one({"formation_id": fid, "user_id": user["id"]}, {"_id": 0})
    if enr:
        enr = await _refresh_enrollment_state(enr)
    return {"formation": formation, "modules": modules, "enrollment": enr}


@api.post("/me/formations/{fid}/modules/{mid}/visit", tags=["Portail Client"])
async def me_visit_module(fid: str, mid: str, request: Request, user: dict = Depends(get_current_user)):
    """Mark a module as visited (call when the page is OPENED)."""
    if not _is_tracked_user(user):
        raise HTTPException(status_code=403, detail="Réservé aux utilisateurs suivis")
    enr = await db.formation_enrollments.find_one({"formation_id": fid, "user_id": user["id"]}, {"_id": 0})
    if not enr:
        raise HTTPException(status_code=404, detail="Inscription requise")
    visit_id = _uuid()
    await db.formation_visits.insert_one({
        "id": visit_id,
        "enrollment_id": enr["id"],
        "user_id": user["id"],
        "formation_id": fid,
        "module_id": mid,
        "opened_at": _now(),
        "closed_at": None,
        "duration_ms": 0,
        "ip": _client_ip_from_request(request),
    })
    seen = set(enr.get("modules_seen") or [])
    seen.add(mid)
    await db.formation_enrollments.update_one(
        {"id": enr["id"]},
        {"$set": {
            "modules_seen": list(seen),
            "last_access": _now(),
            "updated_at": _now(),
        }},
    )
    return {"visit_id": visit_id}


@api.post("/me/formations/{fid}/modules/{mid}/visit/{visit_id}/close", tags=["Portail Client"])
async def me_close_visit(fid: str, mid: str, visit_id: str, user: dict = Depends(get_current_user)):
    """Enregistre la durée une fois que l'utilisateur quitte le module."""
    visit = await db.formation_visits.find_one({"id": visit_id, "user_id": user["id"]}, {"_id": 0})
    if not visit:
        return {"ok": True}  # silently ignore
    if visit.get("closed_at"):
        return {"ok": True}
    try:
        opened = datetime.fromisoformat(visit["opened_at"])
        duration_ms = int((datetime.now(timezone.utc) - opened).total_seconds() * 1000)
    except Exception:
        duration_ms = 0
    duration_ms = max(0, min(duration_ms, 4 * 3600 * 1000))  # cap at 4h to avoid runaway tabs
    await db.formation_visits.update_one(
        {"id": visit_id},
        {"$set": {"closed_at": _now(), "duration_ms": duration_ms}},
    )
    await db.formation_enrollments.update_one(
        {"formation_id": fid, "user_id": user["id"]},
        {"$inc": {"total_time_ms": duration_ms}, "$set": {"updated_at": _now()}},
    )
    return {"ok": True, "duration_ms": duration_ms}


@api.post("/me/formations/{fid}/modules/{mid}/ask", tags=["Portail Client"])
async def me_module_ask(fid: str, mid: str, payload: FormationModuleQuestion, user: dict = Depends(get_current_user)):
    """Transmet la question de l'utilisateur à l'API REST externe du module configurée par l'admin."""
    if not _is_tracked_user(user):
        raise HTTPException(status_code=403, detail="Réservé aux utilisateurs suivis")
    module = await db.formation_modules.find_one({"id": mid, "formation_id": fid}, {"_id": 0})
    if not module:
        raise HTTPException(status_code=404, detail="Module introuvable")
    api_url = (module.get("api_url") or "").strip()
    if not api_url:
        raise HTTPException(status_code=400, detail="Aucune API configurée pour ce module")

    headers = {"Content-Type": "application/json", "User-Agent": "SawaliFormationsClient/1.0"}
    auth = None
    atype = (module.get("api_auth_type") or "none").lower()
    if atype == "bearer" and module.get("api_token"):
        headers["Authorization"] = f"Bearer {module['api_token']}"
    elif atype == "basic":
        auth = (module.get("api_basic_user") or "", module.get("api_basic_pass") or "")

    body = {
        "question": (payload.question or "").strip(),
        "user_id": user["id"],
        "user_email": user["email"],
        "formation_id": fid,
        "module_id": mid,
        **(payload.payload or {}),
    }
    response_text = None
    status = 0
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.post(api_url, json=body, headers=headers, auth=auth)
            status = r.status_code
            response_text = r.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("Formation module ask failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Appel API distant échoué : {exc}") from exc

    qa_doc = {
        "id": _uuid(),
        "formation_id": fid,
        "module_id": mid,
        "user_id": user["id"],
        "user_email": user["email"],
        "question": body["question"],
        "response_text": response_text,
        "response_status": status,
        "created_at": _now(),
    }
    await db.formation_qa.insert_one(qa_doc.copy())
    qa_doc.pop("_id", None)

    # Try to interpret JSON
    try:
        return {"status": status, "response": json.loads(response_text), "id": qa_doc["id"]}
    except Exception:
        return {"status": status, "response": response_text, "id": qa_doc["id"]}
