# server_parts/p09_supervision_parametres.py — Supervision santé, contrôle d'authentification, disponibilité, Admin → Paramètres, audit des secrets, abonnés incidents, documentation API.
# Morceau de l'ancien server.py (lignes 11965 à 13224), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ====================================================================
# HEALTH MONITORING — real-time alerts + weekly digest + generic DB query
# ====================================================================
async def _fire_health_webhook(payload: dict) -> bool:
    s = await db.settings.find_one({"_id": "global"}) or {}
    url = (s.get("health_webhook_url") or "").strip()
    if not url:
        return False
    headers = {"Content-Type": "application/json", "User-Agent": "SawaliHealth/1.0"}
    auth = None
    atype = (s.get("health_webhook_auth_type") or "none").lower()
    if atype == "bearer" and s.get("health_webhook_token"):
        headers["Authorization"] = f"Bearer {s['health_webhook_token']}"
    elif atype == "basic":
        auth = (s.get("health_webhook_basic_user") or "", s.get("health_webhook_basic_pass") or "")
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            r = await http.post(url, json=payload, headers=headers, auth=auth)
            logger.info("Health webhook %s -> %s", url, r.status_code)
            return 200 <= r.status_code < 300
    except Exception as exc:  # noqa: BLE001
        logger.warning("Health webhook failed: %s", exc)
        return False


async def _fire_health_realtime(trace_doc: dict) -> None:
    async with _health_webhook_semaphore:
        try:
            s = await db.settings.find_one({"_id": "global"}) or {}
            if not s.get("health_realtime_enabled"):
                return
            recipient = (s.get("health_email_to") or SUPER_ADMIN_EMAIL).strip().lower()
            body = {
                "type": "api_trace_error",
                "fired_at": _now(),
                "trace": {k: trace_doc.get(k) for k in (
                    "id", "method", "url", "status", "user_email", "module",
                    "duration_ms", "error", "request_body", "response_body", "ip", "created_at",
                )},
            }
            await _fire_health_webhook(body)
            try:
                from email_service import send_email
                subject = f"[SAWALI ALERT] {trace_doc.get('method')} {trace_doc.get('url')} -> HTTP {trace_doc.get('status')}"
                html = (
                    f"<div style='font-family:Arial,sans-serif;'>"
                    f"<h3 style='color:#EF4444'>Erreur API détectée</h3>"
                    f"<p style='color:#475569;font-size:13px;'>{trace_doc.get('user_email')} · {trace_doc.get('created_at')}</p>"
                    f"<p><code>{trace_doc.get('method')} {trace_doc.get('url')}</code> → "
                    f"<strong style='color:#EF4444'>HTTP {trace_doc.get('status')}</strong> ({trace_doc.get('duration_ms')} ms)</p>"
                    f"<pre style='background:#0F172A;color:#7DD3FC;padding:10px;border-radius:6px;font-size:11px;'>{(trace_doc.get('request_body') or '')[:1500]}</pre>"
                    f"<pre style='background:#0F172A;color:#FCA5A5;padding:10px;border-radius:6px;font-size:11px;'>{(trace_doc.get('response_body') or '')[:1500]}</pre>"
                    f"</div>"
                )
                text = f"Erreur API: {trace_doc.get('method')} {trace_doc.get('url')} HTTP {trace_doc.get('status')} par {trace_doc.get('user_email')}"
                await send_email(recipient, subject, html, text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Health realtime email failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Health realtime alert failed: %s", exc)


async def _build_health_stats(window_hours: int = 24) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    base = {"created_at": {"$gte": cutoff}}
    total = await db.api_traces.count_documents(base)
    errors = await db.api_traces.count_documents({**base, "status": {"$gte": 400}})
    rate = (errors / total * 100) if total else 0.0
    top_errors = await db.api_traces.aggregate([
        {"$match": {**base, "status": {"$gte": 400}}},
        {"$group": {"_id": {"method": "$method", "url": "$url"}, "count": {"$sum": 1}, "last_status": {"$last": "$status"}}},
        {"$sort": {"count": -1}}, {"$limit": 10},
    ]).to_list(50)
    top_users = await db.api_traces.aggregate([
        {"$match": base},
        {"$group": {"_id": "$user_email", "count": {"$sum": 1}, "errors": {"$sum": {"$cond": [{"$gte": ["$status", 400]}, 1, 0]}}}},
        {"$sort": {"count": -1}}, {"$limit": 10},
    ]).to_list(50)
    hourly = await db.api_traces.aggregate([
        {"$match": base},
        {"$project": {"hour": {"$substr": ["$created_at", 0, 13]}, "is_err": {"$cond": [{"$gte": ["$status", 400]}, 1, 0]}}},
        {"$group": {"_id": "$hour", "total": {"$sum": 1}, "errors": {"$sum": "$is_err"}}},
        {"$sort": {"_id": 1}},
    ]).to_list(96)
    avg_duration = 0
    if total:
        agg = await db.api_traces.aggregate([
            {"$match": base}, {"$group": {"_id": None, "avg": {"$avg": "$duration_ms"}}},
        ]).to_list(1)
        avg_duration = int((agg[0]["avg"] if agg else 0) or 0)
    return {
        "window_hours": window_hours,
        "total": total,
        "errors": errors,
        "error_rate": round(rate, 2),
        "avg_duration_ms": avg_duration,
        "top_errors": [{"method": e["_id"]["method"], "url": e["_id"]["url"], "count": e["count"], "last_status": e.get("last_status")} for e in top_errors],
        "top_users": [{"email": u["_id"], "total": u["count"], "errors": u.get("errors", 0)} for u in top_users],
        "hourly": [{"hour": h["_id"], "total": h["total"], "errors": h["errors"]} for h in hourly],
    }


@api.get("/admin/health-stats", tags=["Admin"])
async def admin_health_stats(window_hours: int = 24, user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    window_hours = max(1, min(int(window_hours or 24), 24 * 14))
    return await _build_health_stats(window_hours)


@api.post("/admin/health/test-email", tags=["Admin"])
async def admin_health_test_email(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    s = await db.settings.find_one({"_id": "global"}) or {}
    recipient = (s.get("health_email_to") or SUPER_ADMIN_EMAIL).strip().lower()
    fake_trace = {
        "id": _uuid(), "method": "POST", "url": "/api/test", "status": 500,
        "user_email": user["email"], "module": "test",
        "duration_ms": 42, "error": "Test alert (manual trigger)",
        "request_body": "{}", "response_body": "{}", "ip": "127.0.0.1",
        "created_at": _now(),
    }
    asyncio.create_task(_fire_health_realtime(fake_trace))
    return {"ok": True, "recipient": recipient}


async def _send_weekly_digest():
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        if not s.get("health_weekly_enabled"):
            return
        # 0-2 (2026-02) — Don't blast preview-database digests to the admin.
        # When running in the PREVIEW environment, skip by default unless the
        # admin has explicitly opted to receive preview digests too. Use
        # PUBLIC_BASE_URL (always populated in backend/.env) to detect env.
        preview_url = (
            os.environ.get("PUBLIC_BASE_URL", "")
            or os.environ.get("preview_endpoint", "")
            or os.environ.get("REACT_APP_BACKEND_URL", "")
        )
        is_preview_env = ".preview." in preview_url
        if is_preview_env and not s.get("health_weekly_send_from_preview"):
            logger.info(
                "[weekly-digest] Skipping send — running in PREVIEW environment "
                "(set settings.health_weekly_send_from_preview=True to override).",
            )
            return
        stats = await _build_health_stats(window_hours=24 * 7)
        recipient = (s.get("health_email_to") or SUPER_ADMIN_EMAIL).strip().lower()
        await _fire_health_webhook({"type": "weekly_digest", "fired_at": _now(), "stats": stats})
        try:
            from email_service import send_email
            env_tag = "[PREVIEW] " if is_preview_env else ""
            subject = f"{env_tag}[SAWALI] Rapport hebdo santé — {datetime.now(timezone.utc).date().isoformat()}"
            top_err_html = "".join(
                f"<tr><td style='padding:4px 8px;font-family:monospace;'>{e['method']} {e['url']}</td><td style='padding:4px 8px;text-align:right;'>{e['count']}</td></tr>"
                for e in stats["top_errors"][:5]
            ) or "<tr><td colspan='2' style='padding:6px 8px;color:#64748B;'>Aucune erreur — bravo !</td></tr>"
            top_user_html = "".join(
                f"<tr><td style='padding:4px 8px;'>{u['email']}</td><td style='padding:4px 8px;text-align:right;'>{u['total']}</td><td style='padding:4px 8px;text-align:right;color:{'#EF4444' if u['errors'] else '#94A3B8'}'>{u['errors']}</td></tr>"
                for u in stats["top_users"][:5]
            )
            html = (
                f"<div style='font-family:Arial,sans-serif;max-width:640px;'>"
                f"<h2 style='color:#1E90FF;'>Rapport hebdo santé applicative — SAWALI</h2>"
                f"<p style='color:#475569;font-size:13px;'>Synthèse des 7 derniers jours.</p>"
                f"<p>Total: <strong>{stats['total']}</strong> · Erreurs: "
                f"<strong style='color:{'#EF4444' if stats['errors'] else '#10B981'}'>{stats['errors']}</strong> · "
                f"Taux: <strong>{stats['error_rate']}%</strong> · Durée moy.: {stats['avg_duration_ms']} ms</p>"
                f"<h3 style='font-size:14px;'>Top endpoints en erreur</h3>"
                f"<table style='border-collapse:collapse;width:100%;border:1px solid #E2E8F0;'>{top_err_html}</table>"
                f"<h3 style='font-size:14px;margin-top:18px;'>Top utilisateurs</h3>"
                f"<table style='border-collapse:collapse;width:100%;border:1px solid #E2E8F0;'>"
                f"<tr style='background:#F8FAFC;'><th style='padding:4px 8px;text-align:left;'>Email</th>"
                f"<th style='padding:4px 8px;text-align:right;'>Actions</th>"
                f"<th style='padding:4px 8px;text-align:right;'>Erreurs</th></tr>"
                f"{top_user_html}</table>"
                f"<p style='color:#94A3B8;font-size:11px;margin-top:24px;'>Généré automatiquement chaque vendredi à 05:00 (Africa/Abidjan).</p>"
                f"</div>"
            )
            text = f"Hebdo SAWALI — {stats['total']} actions, {stats['errors']} erreurs ({stats['error_rate']}%)."
            await send_email(recipient, subject, html, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weekly digest email failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Weekly digest failed: %s", exc)


@api.post("/admin/health/run-weekly-now", tags=["Admin"])
async def admin_health_run_weekly_now(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    await _send_weekly_digest()
    return {"ok": True}


# ====================================================================
# AUTH CHECKER — periodic end-to-end probe of the login flow.
# Catches regressions like JWT secret rotation, deleted admin user,
# corrupted password hash, broken /auth/me handler, etc.
# ====================================================================
async def _run_auth_check(triggered_by: str = "manual") -> dict:
    """Run a 4-step probe of the auth pipeline. Never raises — always returns a dict."""
    started = datetime.now(timezone.utc)
    steps: list[dict] = []
    overall_ok = True

    async def _step(name: str, coro):
        nonlocal overall_ok
        t0 = datetime.now(timezone.utc)
        try:
            result = await coro
            duration = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            steps.append({"name": name, "ok": True, "duration_ms": duration, "error": None, "info": result})
            return result
        except Exception as exc:  # noqa: BLE001
            duration = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            steps.append({"name": name, "ok": False, "duration_ms": duration, "error": str(exc)[:300], "info": None})
            overall_ok = False
            return None

    # Step 1 — admin user exists in DB
    async def _check_admin_exists():
        admin = await db.users.find_one({"email": SUPER_ADMIN_EMAIL}, {"_id": 0, "id": 1, "role": 1, "password_hash": 1})
        if not admin:
            raise RuntimeError(f"Super-admin '{SUPER_ADMIN_EMAIL}' introuvable en base")
        if admin.get("role") != "admin":
            raise RuntimeError(f"Super-admin a le mauvais role: {admin.get('role')}")
        if not admin.get("password_hash"):
            raise RuntimeError("Hash mot de passe vide")
        return {"id": admin["id"], "role": admin["role"]}

    admin_info = await _step("admin_user_exists", _check_admin_exists())

    # Step 2 — JWT mint + decode roundtrip
    async def _check_jwt_roundtrip():
        if not admin_info:
            raise RuntimeError("Étape précédente échouée")
        from auth import decode_token
        token = create_access_token(admin_info["id"], admin_info["role"])
        if not token or len(token) < 20:
            raise RuntimeError("Token vide ou trop court")
        payload = decode_token(token)
        if payload.get("sub") != admin_info["id"] or payload.get("role") != "admin":
            raise RuntimeError(f"Payload incorrect: {payload}")
        return {"token_len": len(token), "exp": payload.get("exp")}

    jwt_info = await _step("jwt_mint_decode", _check_jwt_roundtrip())

    # Step 3 — HTTP call to /api/auth/me (full middleware stack)
    async def _check_auth_me_http():
        if not admin_info:
            raise RuntimeError("Étape précédente échouée")
        token = create_access_token(admin_info["id"], admin_info["role"])
        async with httpx.AsyncClient(timeout=5.0, base_url=_url_locale_sondes()) as http:
            r = await http.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            if r.status_code != 200:
                raise RuntimeError(f"/auth/me HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            if (data.get("email") or "").lower() != SUPER_ADMIN_EMAIL:
                raise RuntimeError(f"/auth/me retourne le mauvais user: {data.get('email')}")
            return {"http": r.status_code, "email": data.get("email")}

    await _step("auth_me_http", _check_auth_me_http())

    # Step 4 — POST /api/auth/login with empty payload should return 4xx (proves wiring)
    async def _check_login_endpoint_responsive():
        async with httpx.AsyncClient(timeout=5.0, base_url=_url_locale_sondes()) as http:
            r = await http.post("/api/auth/login", json={})
            if r.status_code >= 500:
                raise RuntimeError(f"/auth/login HTTP {r.status_code}: {r.text[:200]}")
            return {"http": r.status_code}

    await _step("login_endpoint_responsive", _check_login_endpoint_responsive())

    finished = datetime.now(timezone.utc)
    total_duration = int((finished - started).total_seconds() * 1000)
    result = {
        "id": _uuid(),
        "ok": overall_ok,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "total_duration_ms": total_duration,
        "steps": steps,
        "triggered_by": triggered_by,
        "created_at": _now(),
    }
    # Persist (capped to last 200 results)
    try:
        await db.auth_checks.insert_one(result.copy())
        # Trim collection to keep it small
        count = await db.auth_checks.count_documents({})
        if count > 200:
            old = await db.auth_checks.find({}, {"_id": 0, "id": 1}).sort("created_at", 1).limit(count - 200).to_list(50)
            if old:
                await db.auth_checks.delete_many({"id": {"$in": [o["id"] for o in old]}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("auth_check persist failed: %s", exc)

    # Fire alert if failed and toggle is on
    if not overall_ok:
        try:
            s = await db.settings.find_one({"_id": "global"}) or {}
            if s.get("health_auth_check_enabled"):
                await _fire_health_webhook({"type": "auth_check_failed", "fired_at": _now(), "result": result})
                try:
                    from email_service import send_email
                    recipient = (s.get("health_email_to") or SUPER_ADMIN_EMAIL).strip().lower()
                    failed_steps = [s for s in steps if not s["ok"]]
                    rows = "".join(
                        f"<tr><td style='padding:4px 8px;font-family:monospace;'>{s['name']}</td>"
                        f"<td style='padding:4px 8px;color:#EF4444'>{s['error'] or '—'}</td></tr>"
                        for s in failed_steps
                    )
                    html = (
                        f"<div style='font-family:Arial,sans-serif;'>"
                        f"<h3 style='color:#EF4444'>🚨 Auth Checker — échec détecté</h3>"
                        f"<p style='color:#475569;font-size:13px;'>Déclenché : <strong>{triggered_by}</strong> · {finished.isoformat()}</p>"
                        f"<p>Durée totale : {total_duration} ms · {len(failed_steps)} étape(s) en erreur sur {len(steps)}.</p>"
                        f"<table style='border-collapse:collapse;width:100%;border:1px solid #E2E8F0;'>"
                        f"<tr style='background:#F8FAFC;'><th style='padding:4px 8px;text-align:left;'>Étape</th>"
                        f"<th style='padding:4px 8px;text-align:left;'>Erreur</th></tr>{rows}</table>"
                        f"<p style='color:#94A3B8;font-size:11px;margin-top:24px;'>Le flux de connexion est cassé. Vérifiez immédiatement /admin/health.</p>"
                        f"</div>"
                    )
                    text = f"AUTH FAIL — {len(failed_steps)} step(s): " + ", ".join(s["name"] for s in failed_steps)
                    await send_email(recipient, "[SAWALI ALERT] Auth Checker — échec détecté", html, text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Auth check email failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auth check alert pipeline failed: %s", exc)

    return result


@api.post("/admin/health/auth-check", tags=["Admin"])
async def admin_health_auth_check_now(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    return await _run_auth_check(triggered_by=f"manual:{user['email']}")


@api.get("/admin/health/auth-check/history", tags=["Admin"])
async def admin_health_auth_check_history(limit: int = 24, user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    items = await db.auth_checks.find({}, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 200))
    return items


@api.get("/admin/health/auth-check/latest", tags=["Admin"])
async def admin_health_auth_check_latest(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    item = await db.auth_checks.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
    return item or {"ok": None, "never_run": True}


# ====================================================================
# UPTIME MONITOR — multi-endpoint availability probes (hourly cron)
# Powers both the admin dashboard and the public /status page.
# ====================================================================
UPTIME_PROBES = [
    {"key": "db_ping", "label": "Base de données", "kind": "db", "public": True},
    {"key": "api_health", "label": "API publique", "kind": "http", "method": "GET", "path": "/api/health", "expect": 200, "public": True},
    {"key": "api_company_info", "label": "Contenu CMS", "kind": "http", "method": "GET", "path": "/api/company-info", "expect": 200, "public": True},
    {"key": "api_visits_count", "label": "Compteur de visites", "kind": "http", "method": "GET", "path": "/api/visits/count", "expect": 200, "public": True},
    {"key": "auth_login_endpoint", "label": "Endpoint /auth/login", "kind": "http", "method": "POST", "path": "/api/auth/login", "expect_max": 499, "public": False},
]


def _url_locale_sondes() -> str:
    """Adresse locale du serveur pour les sondes HTTP (lot 95) : port réel du processus."""
    return f"http://127.0.0.1:{os.environ.get('PORT') or '8001'}"


async def _probe_one(probe: dict) -> dict:
    """Execute a single probe. Returns {key, label, ok, duration_ms, error, status}."""
    started = datetime.now(timezone.utc)
    try:
        if probe["kind"] == "db":
            await asyncio.wait_for(db.users.find_one({}, {"_id": 1}), timeout=5.0)
            duration = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            return {"key": probe["key"], "label": probe["label"], "ok": True, "duration_ms": duration, "error": None, "status": "OK"}
        elif probe["kind"] == "http":
            # Lot 95 — le serveur s'interroge lui-même sur SON port réel : $PORT sur Render (10000 par défaut),
            # 8001 chez Emergent. L'ancien 8001 figé faisait échouer ces sondes depuis la bascule vers Render
            # (03/10/2026) : « All connection attempts failed », d'où 13 % et « Incident en cours » sur /uptime.
            async with httpx.AsyncClient(timeout=5.0, base_url=_url_locale_sondes()) as http:
                if probe["method"] == "GET":
                    r = await http.get(probe["path"])
                else:
                    r = await http.post(probe["path"], json={})
                duration = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
                expect = probe.get("expect")
                expect_max = probe.get("expect_max")
                ok = (r.status_code == expect) if expect else (r.status_code <= expect_max)
                return {
                    "key": probe["key"], "label": probe["label"], "ok": ok,
                    "duration_ms": duration, "error": None if ok else f"HTTP {r.status_code}",
                    "status": str(r.status_code),
                }
    except Exception as exc:  # noqa: BLE001
        duration = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        return {"key": probe["key"], "label": probe["label"], "ok": False, "duration_ms": duration, "error": str(exc)[:200], "status": "ERR"}


async def _run_uptime_probes(triggered_by: str = "manual") -> dict:
    """Run all configured probes, persist a single document, fire alert if any failed."""
    started = datetime.now(timezone.utc)
    probes = await asyncio.gather(*[_probe_one(p) for p in UPTIME_PROBES])
    finished = datetime.now(timezone.utc)
    overall_ok = all(p["ok"] for p in probes)
    doc = {
        "id": _uuid(),
        "ok": overall_ok,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "total_duration_ms": int((finished - started).total_seconds() * 1000),
        "probes": list(probes),
        "triggered_by": triggered_by,
        "created_at": _now(),
    }
    try:
        await db.uptime_checks.insert_one(doc.copy())
        # Trim — keep last 30 days × 24 = 720 max
        count = await db.uptime_checks.count_documents({})
        if count > 800:
            old = await db.uptime_checks.find({}, {"_id": 0, "id": 1}).sort("created_at", 1).limit(count - 720).to_list(200)
            if old:
                await db.uptime_checks.delete_many({"id": {"$in": [o["id"] for o in old]}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("uptime_check persist failed: %s", exc)

    # Fire alert if any probe failed and feature is enabled
    if not overall_ok:
        try:
            s = await db.settings.find_one({"_id": "global"}) or {}
            if s.get("health_uptime_alerts_enabled"):
                failed = [p for p in probes if not p["ok"]]
                payload = {"type": "uptime_failed", "fired_at": _now(), "result": doc}
                await _fire_health_webhook(payload)
                try:
                    from email_service import send_email
                    recipient = (s.get("health_email_to") or SUPER_ADMIN_EMAIL).strip().lower()
                    rows = "".join(
                        f"<tr><td style='padding:4px 8px;font-family:monospace;'>{p['label']}</td>"
                        f"<td style='padding:4px 8px;color:#EF4444'>{p['error'] or p['status']}</td>"
                        f"<td style='padding:4px 8px;text-align:right;'>{p['duration_ms']} ms</td></tr>"
                        for p in failed
                    )
                    html = (
                        f"<div style='font-family:Arial,sans-serif;'>"
                        f"<h3 style='color:#EF4444'>🚨 Uptime Monitor — services indisponibles</h3>"
                        f"<p>{len(failed)} sonde(s) en échec sur {len(probes)} à {finished.isoformat()}.</p>"
                        f"<table style='border-collapse:collapse;width:100%;border:1px solid #E2E8F0;'>"
                        f"<tr style='background:#F8FAFC;'><th style='padding:4px 8px;text-align:left;'>Service</th>"
                        f"<th style='padding:4px 8px;text-align:left;'>Erreur</th>"
                        f"<th style='padding:4px 8px;text-align:right;'>Latence</th></tr>{rows}</table>"
                        f"</div>"
                    )
                    text = f"UPTIME FAIL — {len(failed)} probe(s): " + ", ".join(p["key"] for p in failed)
                    await send_email(recipient, "[SAWALI ALERT] Uptime — services indisponibles", html, text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Uptime alert email failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Uptime alert pipeline failed: %s", exc)
    return doc


async def _build_uptime_stats(window_hours: int = 24 * 7, public_only: bool = False) -> dict:
    """Aggregate uptime per probe over the last `window_hours`."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    docs = await db.uptime_checks.find({"created_at": {"$gte": cutoff}}, {"_id": 0}).sort("created_at", 1).to_list(2000)
    visible_keys = {p["key"] for p in UPTIME_PROBES if (not public_only or p.get("public"))}
    per_probe: dict[str, dict] = {}
    for p in UPTIME_PROBES:
        if p["key"] not in visible_keys:
            continue
        per_probe[p["key"]] = {
            "key": p["key"], "label": p["label"], "total": 0, "ok": 0, "fail": 0,
            "avg_duration_ms": 0, "last_status": None, "last_error": None, "last_at": None,
            "timeline": [],  # [{ts, ok, duration_ms}]
        }
    durations: dict[str, list[int]] = {k: [] for k in per_probe}
    for d in docs:
        for p in d.get("probes", []):
            k = p.get("key")
            if k not in per_probe:
                continue
            per_probe[k]["total"] += 1
            if p.get("ok"):
                per_probe[k]["ok"] += 1
            else:
                per_probe[k]["fail"] += 1
            durations[k].append(p.get("duration_ms") or 0)
            per_probe[k]["last_status"] = p.get("status")
            per_probe[k]["last_error"] = p.get("error")
            per_probe[k]["last_at"] = d.get("created_at")
            per_probe[k]["timeline"].append({
                "ts": d.get("created_at"),
                "ok": bool(p.get("ok")),
                "duration_ms": p.get("duration_ms"),
            })
    for k, v in per_probe.items():
        v["avg_duration_ms"] = int(sum(durations[k]) / len(durations[k])) if durations[k] else 0
        v["uptime_pct"] = round((v["ok"] / v["total"] * 100) if v["total"] else 100.0, 2)
        # cap timeline to last 168 points (7d hourly) for payload size
        v["timeline"] = v["timeline"][-168:]
    overall_total = sum(v["total"] for v in per_probe.values())
    overall_ok = sum(v["ok"] for v in per_probe.values())
    overall_pct = round((overall_ok / overall_total * 100) if overall_total else 100.0, 2)
    return {
        "window_hours": window_hours,
        "overall_uptime_pct": overall_pct,
        "samples": len(docs),
        "probes": list(per_probe.values()),
        "generated_at": _now(),
    }


@api.post("/admin/health/uptime/run-now", tags=["Admin"])
async def admin_health_uptime_run_now(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    return await _run_uptime_probes(triggered_by=f"manual:{user['email']}")


@api.post("/admin/health/uptime/reset", tags=["Admin"])
async def admin_health_uptime_reset(payload: dict = Body(default={}), user: dict = Depends(get_current_user)):
    """Lot 95 — « remettre à zéro le journal pour que les anciens historiques ne soient plus présents ».
    Efface le journal des sondes (pourcentages et barres de /uptime) ; avec {"incidents": true}, efface aussi
    l'historique des incidents (sauf l'incident en cours si le bandeau d'incident est encore activé).
    Une nouvelle série de sondes est lancée aussitôt pour que la page ne reste pas vide. Super-admin seulement."""
    _ensure_super_admin(user)
    sondes = (await db.uptime_checks.delete_many({})).deleted_count
    incidents = 0
    if payload.get("incidents"):
        reglages = await db.settings.find_one({"_id": "global"}, {"incident_banner_enabled": 1}) or {}
        filtre = {"status": {"$ne": "ongoing"}} if reglages.get("incident_banner_enabled") else {}
        incidents = (await db.incidents.delete_many(filtre)).deleted_count
    await db.settings.update_one(
        {"_id": "global"}, {"$set": {"uptime_reset_at": _now(), "uptime_reset_by": user.get("email")}}, upsert=True
    )
    premiere = await _run_uptime_probes(triggered_by=f"remise_a_zero:{user.get('email')}")
    return {"ok": True, "sondes_effacees": sondes, "incidents_effaces": incidents,
            "remise_a_zero_le": _now(), "premiere_serie": premiere}


@api.get("/admin/health/uptime/stats", tags=["Admin"])
async def admin_health_uptime_stats(window_hours: int = 168, user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    window_hours = max(1, min(int(window_hours or 168), 24 * 30))
    stats = await _build_uptime_stats(window_hours, public_only=False)
    # Lot 95 — date de la dernière remise à zéro du journal (affichée dans l'admin)
    reglages = await db.settings.find_one({"_id": "global"}, {"uptime_reset_at": 1, "uptime_reset_by": 1}) or {}
    stats["remise_a_zero_le"] = reglages.get("uptime_reset_at")
    stats["remise_a_zero_par"] = reglages.get("uptime_reset_by")
    return stats


@api.get("/public/status", tags=["Public"])
async def public_status(window_hours: int = 168):
    """Données de la page de statut publique (accessible à tous). Uniquement les sondes flag public."""
    window_hours = max(1, min(int(window_hours or 168), 24 * 30))
    stats = await _build_uptime_stats(window_hours, public_only=True)
    s = await db.settings.find_one({"_id": "global"}) or {}
    return {
        "company": s.get("company_name") or "SAWALI SMART SYSTEMS",
        "logo_url": s.get("company_logo_url"),
        "stats": stats,
    }


# Generic DB query
ALLOWED_COLLECTIONS = {
    "users", "tracked_users", "appointments", "documents", "interventions",
    "contacts", "deployments", "blacklist", "client_categories", "document_categories",
    "case_studies", "blog_posts", "newsletter_subscribers", "testimonials",
    "settings", "user_reports", "user_suivis", "ratings",
    "access_logs", "api_traces", "visits", "document_logs", "files",
    "formations", "formation_modules", "formation_enrollments", "formation_visits", "formation_qa",
    "otps", "counters", "auth_checks", "uptime_checks", "incidents", "incident_subscribers",
    "user_module_visits", "forms", "form_submissions", "directory_contacts", "whatsapp_messages", "whatsapp_schedules", "automations", "client_notes", "client_tasks", "policies", "ai_summaries", "payments",
    "subscription_plans", "subscription_categories", "subscription_orders", "wa_pending_imports",
}


@api.get("/admin/db", tags=["Admin"])
async def admin_list_collections(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    out = []
    for c in sorted(ALLOWED_COLLECTIONS):
        try:
            count = await getattr(db, c).estimated_document_count()
        except Exception:
            count = None
        out.append({"name": c, "count": count})
    return out


@api.get("/admin/db/{collection}", tags=["Admin"])
async def admin_query_collection(
    collection: str,
    request: Request,
    limit: int = 200,
    sort_by: Optional[str] = None,
    sort_dir: int = -1,
    user: dict = Depends(get_current_user),
):
    """Generic JSON query over any whitelisted collection.

    Supports special suffixes on filter keys:
      - `key__regex=pattern` (case-insensitive)
      - `key__gte=...` `key__lte=...` `key__gt=...` `key__lt=...` `key__ne=...`
      - `key=value` (exact match; booleans and integers auto-coerced)
    Reserved query params: `limit`, `sort_by`, `sort_dir`.
    """
    _ensure_super_admin(user)
    if collection not in ALLOWED_COLLECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Collection non autorisée. Valeurs : {', '.join(sorted(ALLOWED_COLLECTIONS))}",
        )
    OP_MAP = {"gte": "$gte", "lte": "$lte", "gt": "$gt", "lt": "$lt", "ne": "$ne"}

    def _coerce(v: str):
        if v.lower() in ("true", "false"):
            return v.lower() == "true"
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return v

    query: dict = {}
    for key, value in request.query_params.items():
        if key in ("limit", "sort_by", "sort_dir"):
            continue
        if "__" in key:
            field, op = key.split("__", 1)
            if op == "regex":
                query.setdefault(field, {})["$regex"] = re.escape(value)
                query[field]["$options"] = "i"
            elif op in OP_MAP:
                query.setdefault(field, {})[OP_MAP[op]] = _coerce(value)
            else:
                query[field] = value
        else:
            query[key] = _coerce(value)
    coll = getattr(db, collection)
    cursor = coll.find(query, {"_id": 0})
    if sort_by:
        cursor = cursor.sort(sort_by, int(sort_dir))
    items = await cursor.to_list(min(max(int(limit), 1), 5000))
    items = [_redact_sensitive(it) for it in items]
    total = await coll.count_documents(query)
    return {
        "collection": collection,
        "total_matched": total,
        "returned": len(items),
        "limit": limit,
        "items": items,
    }



# ====================================================================
# ADMIN - Settings
# ====================================================================
@api.get("/public/ui-flags", tags=["Public"])
async def public_ui_flags():
    """Iter40-route-loader (S051) + Iter40-ui-flags — Tiny anonymous endpoint
    exposing only the UI display toggles and public branding fields needed by
    frontend components that mount BEFORE auth (e.g. GlobalRouteLoader, brand
    color CSS variable, public logo). NEVER expose secrets here."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    return {
        "global_route_loader_enabled": s.get("global_route_loader_enabled") is not False,
        "download_gauge_enabled": s.get("download_gauge_enabled") is not False,
        # 2026-02 fork iter108 — S164 (Emmy) — Browser Push Notifications global switch
        "browser_notifications_enabled": s.get("browser_notifications_enabled") is not False,
        # Iter40-ui-flags — Public branding (null/empty = use default)
        "public_brand_name": (s.get("public_brand_name") or "").strip() or None,
        "public_brand_color": (s.get("public_brand_color") or "").strip() or None,
        "public_brand_text_color": (s.get("public_brand_text_color") or "").strip() or None,
        "public_logo_url": (s.get("public_logo_url") or "").strip() or None,
        "public_hero_tagline": (s.get("public_hero_tagline") or "").strip() or None,
        # Iter40-ui-flags-bg (S057) — Event/client themed backgrounds
        "public_bg_mode": (s.get("public_bg_mode") or "default").strip() or "default",
        "public_bg_color": (s.get("public_bg_color") or "").strip() or None,
        "public_bg_image_url": (s.get("public_bg_image_url") or "").strip() or None,
        "public_bg_image_position": (s.get("public_bg_image_position") or "cover").strip() or "cover",
        "portal_bg_mode": (s.get("portal_bg_mode") or "default").strip() or "default",
        "portal_bg_color": (s.get("portal_bg_color") or "").strip() or None,
        "portal_bg_image_url": (s.get("portal_bg_image_url") or "").strip() or None,
        "portal_bg_image_position": (s.get("portal_bg_image_position") or "cover").strip() or "cover",
        # S057 Day 3+ — Habillage complet
        "sidebar_bg_color": (s.get("sidebar_bg_color") or "").strip() or None,
        "sidebar_text_color": (s.get("sidebar_text_color") or "").strip() or None,
        "sidebar_accent_color": (s.get("sidebar_accent_color") or "").strip() or None,
        "login_bg_mode": (s.get("login_bg_mode") or "default").strip() or "default",
        "login_bg_color": (s.get("login_bg_color") or "").strip() or None,
        "login_bg_image_url": (s.get("login_bg_image_url") or "").strip() or None,
        "login_text_color": (s.get("login_text_color") or "").strip() or None,
        "login_card_bg": (s.get("login_card_bg") or "").strip() or None,
        "login_card_text_color": (s.get("login_card_text_color") or "").strip() or None,
        "login_button_bg": (s.get("login_button_bg") or "").strip() or None,
        "login_button_text_color": (s.get("login_button_text_color") or "").strip() or None,
        "public_blocks_theme": s.get("public_blocks_theme") if isinstance(s.get("public_blocks_theme"), dict) else None,
        # Iter41 Phase 3 — Sidebar background image (overrides sidebar_bg_color when set)
        "sidebar_bg_image_url": (s.get("sidebar_bg_image_url") or "").strip() or None,
        "sidebar_bg_image_opacity": float(s.get("sidebar_bg_image_opacity")) if s.get("sidebar_bg_image_opacity") is not None else None,
    }


@api.put("/admin/settings", tags=["Admin"])
async def admin_update_settings(payload: SettingsUpdate, user: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Treat the masking placeholder as "no change" for sensitive fields
    SECRET_FIELDS = (
        "smtp_password", "google_client_secret", "recaptcha_secret_key",
        "tracking_auth_header", "webhook_token", "webhook_basic_pass",
        "notes_webhook_token", "notes_webhook_basic_pass",
        "health_webhook_token", "health_webhook_basic_pass",
        "wa_access_token", "wa_verify_token",
        "openai_api_key", "openai_chat_api_key",
        "n8n_webhook_token", "n8n_webhook_basic_pass",
        "sms_orange_token", "sms_orange_basic_pass", "sms_orange_header_value", "sms_orange_client_secret",
        "sms_moov_token", "sms_moov_basic_pass", "sms_moov_header_value", "sms_moov_client_secret",
        "sms_telecel_token", "sms_telecel_basic_pass", "sms_telecel_header_value", "sms_telecel_client_secret",
        "sms_ovh_application_secret", "sms_ovh_consumer_key",
        "pawapay_api_token", "pawapay_api_token_sandbox", "pawapay_api_token_production", "pawapay_callback_secret",
        "agenda_n8n_outbound_token", "agenda_n8n_outbound_basic_pass", "agenda_n8n_inbound_secret",
        "support_load_webhook_secret", "liluvine_remote_secret",
        "stripe_webhook_secret",
        "vidal_test_app_key", "vidal_prod_app_key",
        "officines_api_token",
        "officines_register_hmac_secret",
        # Iter43-fix23b — Bird.com (sensible) + officines inventory webhook
        "bird_access_key",
        "bird_webhook_secret",
        "officines_inventory_webhook_token",
    )
    for k in SECRET_FIELDS:
        if update.get(k) == "********":
            update.pop(k, None)
    # Lot 52 — l'envoi des e-mails est réservé au super-admin : champs smtp_* ignorés pour les autres
    # comptes, mot de passe SMTP chiffré (jamais enregistré en clair dans les réglages globaux).
    update = await _email_fournisseurs.filtrer_maj_parametres_generiques(update, user, _is_super_admin)
    # Iter37f — Validate welcome_unread_mode
    if "welcome_unread_mode" in update:
        mode = (update["welcome_unread_mode"] or "").strip().lower()
        if mode not in ("bounded", "lifetime"):
            raise HTTPException(status_code=400, detail="welcome_unread_mode doit être 'bounded' ou 'lifetime'")
        update["welcome_unread_mode"] = mode
    # Iter43-fix24az-d — Validate garde_rotation_mode
    if "garde_rotation_mode" in update:
        gm = (update["garde_rotation_mode"] or "saturday_noon").strip().lower()
        if gm not in ("saturday_noon", "monday_midnight"):
            raise HTTPException(status_code=400, detail="garde_rotation_mode doit être 'saturday_noon' ou 'monday_midnight'")
        update["garde_rotation_mode"] = gm
    # 2026-02 (#3) — Validate liluvine_takeover_default_minutes (5-10080)
    if "liluvine_takeover_default_minutes" in update and update["liluvine_takeover_default_minutes"] is not None:
        try:
            v = int(update["liluvine_takeover_default_minutes"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="liluvine_takeover_default_minutes doit être un entier") from exc
        if v < 5 or v > 10080:
            raise HTTPException(status_code=400, detail="liluvine_takeover_default_minutes doit être entre 5 et 10080 (7 jours)")
        update["liluvine_takeover_default_minutes"] = v
    # Iter38r-fix9z10 — Suggestion S009 — Validate auto_logout_minutes (0-120, 0 = disabled)
    if "auto_logout_minutes" in update:
        try:
            v = int(update["auto_logout_minutes"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="auto_logout_minutes doit être un entier") from exc
        if v < 0 or v > 120:
            raise HTTPException(status_code=400, detail="auto_logout_minutes doit être entre 0 et 120")
        update["auto_logout_minutes"] = v
    # Iter40-modal — Validate modal_global_cap_per_day (0-20, 0=unlimited)
    if "modal_global_cap_per_day" in update and update["modal_global_cap_per_day"] is not None:
        try:
            v = int(update["modal_global_cap_per_day"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="modal_global_cap_per_day doit être un entier") from exc
        if v < 0 or v > 20:
            raise HTTPException(status_code=400, detail="modal_global_cap_per_day doit être entre 0 et 20")
        update["modal_global_cap_per_day"] = v
    # S026 — Validate meeting_signers_notify_channel against allowed set
    if "meeting_signers_notify_channel" in update:
        allowed = {"none", "email", "wa", "both"}
        ch = (update["meeting_signers_notify_channel"] or "none").strip().lower()
        if ch not in allowed:
            raise HTTPException(status_code=400, detail=f"meeting_signers_notify_channel doit être l'un de {sorted(allowed)}")
        update["meeting_signers_notify_channel"] = ch
    # S032 — Validate LLM budget thresholds (50-99 / 60-99 / >0 / E.164 phone)
    if "llm_budget_warning_pct" in update and update["llm_budget_warning_pct"] is not None:
        try:
            v = int(update["llm_budget_warning_pct"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="llm_budget_warning_pct doit être un entier") from exc
        if v < 50 or v > 99:
            raise HTTPException(status_code=400, detail="llm_budget_warning_pct doit être entre 50 et 99")
        update["llm_budget_warning_pct"] = v
    if "llm_budget_critical_pct" in update and update["llm_budget_critical_pct"] is not None:
        try:
            v = int(update["llm_budget_critical_pct"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="llm_budget_critical_pct doit être un entier") from exc
        if v < 60 or v > 99:
            raise HTTPException(status_code=400, detail="llm_budget_critical_pct doit être entre 60 et 99")
        update["llm_budget_critical_pct"] = v
    if "llm_budget_max_usd" in update and update["llm_budget_max_usd"] is not None:
        try:
            v = float(update["llm_budget_max_usd"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="llm_budget_max_usd doit être un nombre") from exc
        if v <= 0:
            raise HTTPException(status_code=400, detail="llm_budget_max_usd doit être strictement positif")
        update["llm_budget_max_usd"] = v
    # Coherence check: warning < critical
    _w = update.get("llm_budget_warning_pct")
    _c = update.get("llm_budget_critical_pct")
    if _w is not None and _c is not None and _w >= _c:
        raise HTTPException(status_code=400, detail="llm_budget_warning_pct doit être strictement inférieur à llm_budget_critical_pct")
    if "llm_budget_notify_wa_phone" in update:
        update["llm_budget_notify_wa_phone"] = (update["llm_budget_notify_wa_phone"] or "").strip()
    # S033 — Normalize WA query keyword (uppercase, max 32 chars)
    if "llm_budget_wa_query_keyword" in update:
        kw = (update["llm_budget_wa_query_keyword"] or "SOLDE").strip().upper()
        if len(kw) > 32:
            raise HTTPException(status_code=400, detail="llm_budget_wa_query_keyword doit faire au plus 32 caractères")
        update["llm_budget_wa_query_keyword"] = kw or "SOLDE"
    # S036 — Validate Liluvine escalation settings
    if "liluvine_escalation_wa_phone" in update:
        update["liluvine_escalation_wa_phone"] = (update["liluvine_escalation_wa_phone"] or "").strip()
    if "liluvine_escalation_cooldown_minutes" in update and update["liluvine_escalation_cooldown_minutes"] is not None:
        try:
            v = int(update["liluvine_escalation_cooldown_minutes"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="liluvine_escalation_cooldown_minutes doit être un entier") from exc
        if v < 1 or v > 1440:
            raise HTTPException(status_code=400, detail="liluvine_escalation_cooldown_minutes doit être entre 1 et 1440 minutes")
        update["liluvine_escalation_cooldown_minutes"] = v
    # S025 — Strip whitespace on approval phone (E.164 expected)
    if "download_approval_whatsapp" in update:
        v = (update["download_approval_whatsapp"] or "").strip()
        update["download_approval_whatsapp"] = v
    # 2026-02 — Validate WA notification sound preset + volume (see wa_notification_sound.py)
    if "wa_notification_sound" in update:
        allowed_presets = ("bip", "ding", "chime", "alert", "subtle", "custom")
        ps = (update["wa_notification_sound"] or "bip").strip().lower()
        if ps not in allowed_presets:
            raise HTTPException(status_code=400, detail=f"wa_notification_sound doit être l'un de {list(allowed_presets)}")
        update["wa_notification_sound"] = ps
    if "wa_notification_volume" in update and update["wa_notification_volume"] is not None:
        try:
            v = float(update["wa_notification_volume"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="wa_notification_volume doit être un nombre") from exc
        if v < 0.0 or v > 1.0:
            raise HTTPException(status_code=400, detail="wa_notification_volume doit être entre 0.0 et 1.0")
        update["wa_notification_volume"] = v
    if not update:
        return {"ok": True}
    # Iter35x — Snapshot previous values BEFORE the update for audit comparison
    _prev_settings_for_audit = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    update["updated_at"] = _now()
    # Stamp incident_banner_updated_at whenever any banner field changes
    BANNER_FIELDS = ("incident_banner_enabled", "incident_banner_severity", "incident_banner_message", "incident_banner_link_url", "incident_banner_link_label")
    banner_touched = any(f in update for f in BANNER_FIELDS)
    if banner_touched:
        update["incident_banner_updated_at"] = _now()
        # Snapshot previous state to detect transitions
        prev = await db.settings.find_one({"_id": "global"}) or {}
        prev_enabled = bool(prev.get("incident_banner_enabled", False))
        next_enabled = bool(update.get("incident_banner_enabled", prev_enabled))
        editor = (user.get("email") or "").lower() or None
        # off → on : open a new incident
        if not prev_enabled and next_enabled:
            new_incident = {
                "id": _uuid(),
                "severity": update.get("incident_banner_severity") or prev.get("incident_banner_severity") or "warning",
                "message": update.get("incident_banner_message") or prev.get("incident_banner_message") or "",
                "link_url": update.get("incident_banner_link_url") or prev.get("incident_banner_link_url") or "",
                "link_label": update.get("incident_banner_link_label") or prev.get("incident_banner_link_label") or "",
                "status": "ongoing",
                "started_at": _now(),
                "resolved_at": None,
                "duration_minutes": None,
                "updates": [],
                "created_by": editor,
                "resolved_by": None,
            }
            await db.incidents.insert_one(new_incident.copy())
            asyncio.create_task(_broadcast_incident_to_subscribers("opened", new_incident))
        # on → off : resolve the latest open incident
        elif prev_enabled and not next_enabled:
            ongoing = await db.incidents.find_one({"status": "ongoing"}, sort=[("started_at", -1)])
            if ongoing:
                started = datetime.fromisoformat(ongoing["started_at"]) if isinstance(ongoing["started_at"], str) else ongoing["started_at"]
                resolved_at = datetime.now(timezone.utc)
                duration = int((resolved_at - started).total_seconds() / 60)
                resolved_doc = {**ongoing, "status": "resolved", "resolved_at": resolved_at.isoformat(), "duration_minutes": duration, "resolved_by": editor}
                await db.incidents.update_one(
                    {"id": ongoing["id"]},
                    {"$set": {"status": "resolved", "resolved_at": resolved_at.isoformat(), "duration_minutes": duration, "resolved_by": editor}},
                )
                resolved_doc.pop("_id", None)
                asyncio.create_task(_broadcast_incident_to_subscribers("resolved", resolved_doc))
        # ongoing edit : append an update entry to the latest open incident
        elif prev_enabled and next_enabled:
            content_changed = any(f in update for f in ("incident_banner_severity", "incident_banner_message", "incident_banner_link_url", "incident_banner_link_label"))
            if content_changed:
                ongoing = await db.incidents.find_one({"status": "ongoing"}, sort=[("started_at", -1)])
                if ongoing:
                    await db.incidents.update_one(
                        {"id": ongoing["id"]},
                        {"$push": {"updates": {
                            "ts": _now(),
                            "severity": update.get("incident_banner_severity") or ongoing.get("severity"),
                            "message": update.get("incident_banner_message") or ongoing.get("message"),
                            "by": editor,
                        }}},
                    )
    await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
    # Iter35u — Hot-reload the public_base_url cache so subsequent background
    # jobs (cron emails, webhooks, scheduled WA sends) use the new value.
    if "public_base_url" in update:
        await _refresh_public_base_url_cache()
    # Iter35x — Audit log + email notification for any vault-tracked key change
    try:
        await _audit_secret_changes(update, user, _prev_settings_for_audit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[secret-audit] failed: %s", exc)
    return {"ok": True}


# =====================================================================
# Iter35x — Secret change audit & email notification
# Tracks every modification of a vault-tracked key in db.secret_change_audit
# (qui/quand/quelle clé). Never stores the value — only a SHA-256 fingerprint
# and a populated flag. Best-effort email to the admin so they know
# something changed (never the value).
# =====================================================================
async def _audit_secret_changes(update: Dict[str, Any], actor: dict, prev_full: Dict[str, Any]) -> None:
    import hashlib
    tracked = [k for k in update.keys() if k in VAULT_KEYS]
    if not tracked:
        return
    actor_email = (actor or {}).get("email") or "system"
    settings_doc = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    entries = []
    for k in tracked:
        new_val = update.get(k)
        prev_val = prev_full.get(k)
        # Skip if value did not actually change (set called but same content)
        if prev_val == new_val:
            continue
        new_str = "" if new_val is None else (json.dumps(new_val, sort_keys=True) if not isinstance(new_val, str) else new_val)
        new_hash = hashlib.sha256(new_str.encode("utf-8")).hexdigest()[:16] if new_str else ""
        action = "created" if not prev_val and new_val else ("deleted" if prev_val and not new_val else "updated")
        entry = {
            "id": _uuid(),
            "key": k,
            "action": action,
            "actor_email": actor_email,
            "actor_id": (actor or {}).get("id"),
            "ts": _now(),
            "fingerprint": new_hash,
            "is_secret": k in SENSITIVE_SETTINGS_KEYS,
        }
        entries.append(entry)
    if not entries:
        return
    await db.secret_change_audit.insert_many([e.copy() for e in entries])
    # Best-effort email notification
    if settings_doc.get("secret_audit_email_enabled"):
        recipient = (settings_doc.get("secret_audit_email_to") or settings_doc.get("health_email_to") or "").strip()
        if recipient:
            asyncio.create_task(_send_secret_audit_email(recipient, entries, actor_email))


async def _send_secret_audit_email(recipient: str, entries: list, actor_email: str) -> None:
    try:
        from email_service import send_email
        rows = "".join(
            f"<tr><td style='padding:6px 10px;border:1px solid #e2e8f0;font-family:monospace;font-size:12px'>{e['key']}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0'>"
            f"<span style=\"font-weight:600;color:{'#059669' if e['action']=='created' else '#dc2626' if e['action']=='deleted' else '#0284c7'}\">{e['action']}</span></td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0;font-family:monospace;font-size:11px;color:#64748b'>{e['fingerprint'] or '—'}</td></tr>"
            for e in entries
        )
        html = f"""
        <div style='font-family:Arial,sans-serif;max-width:640px;margin:auto;padding:16px;border:1px solid #e2e8f0;border-radius:8px'>
          <h2 style='color:#1e293b;margin:0 0 8px'>🔐 Modification du Coffre-fort SAWALI</h2>
          <p style='color:#475569;margin:0 0 12px'>
            <strong>{actor_email}</strong> vient de modifier {len(entries)} clé(s) sensible(s) à {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.
          </p>
          <table style='border-collapse:collapse;width:100%;font-size:13px'>
            <thead><tr style='background:#f1f5f9'>
              <th style='padding:6px 10px;border:1px solid #e2e8f0;text-align:left'>Clé</th>
              <th style='padding:6px 10px;border:1px solid #e2e8f0;text-align:left'>Action</th>
              <th style='padding:6px 10px;border:1px solid #e2e8f0;text-align:left'>Empreinte SHA-256</th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
          <p style='color:#94a3b8;font-size:11px;margin-top:12px'>
            Aucune valeur n'est révélée dans cet email. Si vous n'êtes pas l'auteur de ce changement, connectez-vous immédiatement et révoquez les jetons.
          </p>
        </div>"""
        await send_email(
            to_email=recipient,
            subject=f"[SAWALI] {len(entries)} clé(s) modifiée(s) par {actor_email}",
            html_body=html,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[secret-audit] email failed: %s", exc)


# Iter35x — Vault-tracked key change audit endpoint moved to
# routes/admin_settings.py (S045 Phase 2 refactor). See attach_admin_settings_routes.


# ----- Incident history -----


# Iter35w — Test endpoint for critical URLs moved to routes/admin_settings.py
# (S045 Phase 2 refactor). The TESTABLE_URL_KEYS list lives over there.


@api.get("/public/incidents", tags=["Public"])
async def public_list_incidents(limit: int = 30):
    """Timeline publique des incidents (résolus + en cours). Utilisé par la page /uptime."""
    items = await db.incidents.find(
        {},
        {"_id": 0, "id": 1, "severity": 1, "message": 1, "link_url": 1, "link_label": 1,
         "status": 1, "started_at": 1, "resolved_at": 1, "duration_minutes": 1, "updates": 1},
    ).sort("started_at", -1).to_list(min(max(limit, 1), 100))
    return items


# ====================================================================
# INCIDENT SUBSCRIBERS — public can subscribe to email notifications.
# Double opt-in: subscription is only active after email confirmation.
# ====================================================================
class IncidentSubscribeRequest(BaseModel):
    email: EmailStr


def _public_url() -> str:
    """Best-effort base URL for confirmation/unsubscribe links in emails."""
    return (PUBLIC_BASE_URL or "").rstrip("/")


async def _send_subscriber_confirmation(email: str, confirm_token: str) -> None:
    try:
        from email_service import send_email
        link = f"{_public_url()}/api/public/incidents/confirm?token={confirm_token}"
        html = (
            f"<div style='font-family:Arial,sans-serif;max-width:480px;'>"
            f"<h2 style='color:#1E90FF;'>SAWALI — Confirmation d'abonnement</h2>"
            f"<p>Bonjour,</p>"
            f"<p>Vous recevrez les notifications d'incidents de SAWALI SMART SYSTEMS sur cet email "
            f"après avoir cliqué sur le lien ci-dessous :</p>"
            f"<p><a href='{link}' style='display:inline-block;background:#1E90FF;color:white;"
            f"padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:bold;'>"
            f"Confirmer mon abonnement</a></p>"
            f"<p style='color:#94A3B8;font-size:11px;margin-top:24px;'>"
            f"Si vous n'avez pas demandé cet abonnement, vous pouvez ignorer cet email.</p>"
            f"</div>"
        )
        text = f"Confirmez votre abonnement aux notifications SAWALI : {link}"
        await send_email(email, "[SAWALI] Confirmez votre abonnement aux notifications", html, text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Subscriber confirmation email failed: %s", exc)


async def _broadcast_incident_to_subscribers(action: str, incident: dict) -> None:
    """Send email to all confirmed subscribers when an incident is opened or resolved."""
    try:
        subs = await db.incident_subscribers.find({"confirmed": True}, {"_id": 0, "email": 1, "unsubscribe_token": 1}).to_list(2000)
        if not subs:
            return
        from email_service import send_email
        sev = (incident.get("severity") or "warning").lower()
        sev_label = {"info": "Info", "warning": "Avertissement", "critical": "Critique"}.get(sev, sev)
        sev_color = {"info": "#0EA5E9", "warning": "#F59E0B", "critical": "#EF4444"}.get(sev, "#F59E0B")
        if action == "opened":
            subject = f"[SAWALI] Incident en cours — {sev_label}"
            headline = "Un incident est en cours"
            timeline_html = f"<p><strong>Démarré :</strong> {incident.get('started_at')}</p>"
        else:  # resolved
            subject = f"[SAWALI] Incident résolu — {sev_label}"
            headline = "Incident résolu"
            duration = incident.get("duration_minutes")
            if duration is None:
                dur_str = "—"
            elif duration < 1:
                dur_str = "moins d'une minute"
            elif duration < 60:
                dur_str = f"{duration} min"
            else:
                dur_str = f"{duration // 60} h {duration % 60} min"
            timeline_html = (
                f"<p><strong>Durée totale :</strong> {dur_str}</p>"
                f"<p><strong>Résolu :</strong> {incident.get('resolved_at')}</p>"
            )
        # Send one personalized email per subscriber (so unsubscribe link is unique)
        sem = asyncio.Semaphore(10)
        async def _send_one(sub):
            async with sem:
                unsub = f"{_public_url()}/api/public/incidents/unsubscribe?token={sub.get('unsubscribe_token','')}"
                html = (
                    f"<div style='font-family:Arial,sans-serif;max-width:560px;'>"
                    f"<div style='background:{sev_color};color:white;padding:12px 16px;border-radius:6px 6px 0 0;'>"
                    f"<strong style='text-transform:uppercase;letter-spacing:.1em;font-size:11px;'>{sev_label}</strong>"
                    f"<h2 style='margin:6px 0 0 0;font-size:18px;'>{headline}</h2></div>"
                    f"<div style='border:1px solid #E2E8F0;border-top:0;padding:18px;border-radius:0 0 6px 6px;'>"
                    f"<p style='font-size:15px;color:#0F172A;'>{(incident.get('message') or '')[:1000]}</p>"
                    f"{timeline_html}"
                    f"<p style='margin-top:18px;'><a href='{_public_url()}/uptime' style='color:#1E90FF;'>Voir le détail sur la page de statut →</a></p>"
                    f"<p style='color:#94A3B8;font-size:11px;margin-top:32px;border-top:1px solid #E2E8F0;padding-top:12px;'>"
                    f"Vous recevez cet email car vous êtes abonné aux notifications d'incidents SAWALI."
                    f" <a href='{unsub}' style='color:#94A3B8;'>Se désabonner</a></p>"
                    f"</div></div>"
                )
                text = f"{headline} ({sev_label}): {(incident.get('message') or '')[:300]} — {_public_url()}/uptime"
                try:
                    await send_email(sub["email"], subject, html, text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Subscriber broadcast to %s failed: %s", sub.get("email"), exc)
        await asyncio.gather(*[_send_one(s) for s in subs])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Incident broadcast pipeline failed: %s", exc)


@api.post("/public/incidents/subscribe", tags=["Public"])
async def public_subscribe_to_incidents(payload: IncidentSubscribeRequest):
    email = payload.email.strip().lower()
    if not is_valid_email_syntax(email):
        raise HTTPException(status_code=400, detail="Email invalide")
    existing = await db.incident_subscribers.find_one({"email": email})
    if existing:
        if existing.get("confirmed"):
            return {"ok": True, "already_subscribed": True}
        # Resend confirmation
        token = existing.get("confirmation_token") or secrets.token_urlsafe(24)
        await db.incident_subscribers.update_one({"email": email}, {"$set": {"confirmation_token": token}})
        asyncio.create_task(_send_subscriber_confirmation(email, token))
        return {"ok": True, "confirmation_resent": True}
    confirm_token = secrets.token_urlsafe(24)
    unsubscribe_token = secrets.token_urlsafe(24)
    await db.incident_subscribers.insert_one({
        "id": _uuid(),
        "email": email,
        "confirmed": False,
        "confirmation_token": confirm_token,
        "unsubscribe_token": unsubscribe_token,
        "subscribed_at": _now(),
        "confirmed_at": None,
    })
    asyncio.create_task(_send_subscriber_confirmation(email, confirm_token))
    return {"ok": True}


@api.get("/public/incidents/confirm", tags=["Public"])
async def public_confirm_subscription(token: str):
    sub = await db.incident_subscribers.find_one({"confirmation_token": token})
    if not sub:
        return RedirectResponse(url=f"{_public_url()}/uptime?subscribe=invalid")
    if not sub.get("confirmed"):
        await db.incident_subscribers.update_one(
            {"id": sub["id"]},
            {"$set": {"confirmed": True, "confirmed_at": _now()}, "$unset": {"confirmation_token": ""}},
        )
    return RedirectResponse(url=f"{_public_url()}/uptime?subscribe=confirmed")


@api.get("/public/incidents/unsubscribe", tags=["Public"])
async def public_unsubscribe(token: str):
    res = await db.incident_subscribers.delete_one({"unsubscribe_token": token})
    suffix = "ok" if res.deleted_count else "invalid"
    return RedirectResponse(url=f"{_public_url()}/uptime?subscribe={suffix}")


@api.get("/admin/incident-subscribers", tags=["Admin"])
async def admin_list_subscribers(_: dict = Depends(get_current_admin)):
    items = await db.incident_subscribers.find(
        {},
        {"_id": 0, "id": 1, "email": 1, "confirmed": 1, "subscribed_at": 1, "confirmed_at": 1},
    ).sort("subscribed_at", -1).to_list(2000)
    confirmed = sum(1 for s in items if s.get("confirmed"))
    return {"total": len(items), "confirmed": confirmed, "items": items}


@api.delete("/admin/incident-subscribers/{sub_id}", tags=["Admin"])
async def admin_delete_subscriber(sub_id: str, _: dict = Depends(get_current_admin)):
    res = await db.incident_subscribers.delete_one({"id": sub_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Abonné introuvable")
    return {"ok": True}


# ----- Google Calendar OAuth admin endpoints -----
@api.get("/admin/google/auth-url", tags=["Admin"])
async def admin_google_auth_url(request: Request, _: dict = Depends(get_current_admin)):
    base = _public_base_url(request) or PUBLIC_BASE_URL
    redirect_uri = f"{base}/api/admin/google/callback"
    url = await gcal.get_auth_url(redirect_uri)
    if not url:
        raise HTTPException(
            status_code=400,
            detail="Veuillez configurer google_client_id et google_client_secret dans les paramètres",
        )
    return {"auth_url": url, "redirect_uri": redirect_uri}


@api.get("/admin/google/callback", tags=["Admin"])
async def admin_google_callback(request: Request, code: str):
    base = _public_base_url(request) or PUBLIC_BASE_URL
    redirect_uri = f"{base}/api/admin/google/callback"
    try:
        await gcal.exchange_code(code, redirect_uri)
        return RedirectResponse(url=f"{base}/admin/settings?gcal=ok")
    except Exception as e:
        return RedirectResponse(url=f"{base}/admin/settings?gcal=error&msg={e}")


@api.post("/admin/google/disconnect", tags=["Admin"])
async def admin_google_disconnect(_: dict = Depends(get_current_admin)):
    await db.settings.update_one(
        {"_id": "global"},
        {"$unset": {"google_refresh_token": "", "google_access_token": ""}},
    )
    return {"ok": True}


# Iter43-fix24ao (2026-06-17) — Diagnostic endpoint: verifies that the
# stored refresh_token still produces a valid access_token AND that the
# Google Calendar API responds. Returns the 3 next upcoming events so the
# admin can visually confirm everything works end-to-end.
@api.get("/admin/google/test-connection", tags=["Admin"])
async def admin_google_test_connection(_: dict = Depends(get_current_admin)):
    if not await gcal.is_configured():
        return {
            "ok": False,
            "reason": "not_connected",
            "message": "Google Calendar n'est pas connecté. Configurez Client ID + Secret puis cliquez sur « Connecter Google Calendar ».",
        }
    try:
        events = await gcal.list_upcoming_events(max_results=3)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "reason": "api_call_failed",
            "message": f"Erreur lors de l'appel Google Calendar API : {exc}",
            "error_type": type(exc).__name__,
        }
    return {
        "ok": True,
        "events_count": len(events),
        "events": events,
        "calendar_id": (await db.settings.find_one({"_id": "global"}) or {}).get("google_calendar_email") or "primary",
    }


# ====================================================================
# API DOCS METADATA (custom listing)
# ====================================================================
@api.get("/api-routes", tags=["Documentation"])
async def list_api_routes():
    """Liste tous les endpoints disponibles (pour la page /api-docs)."""
    routes = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api"):
            continue
        # Bug-fix iter43-fix12 (2026-03) : certaines routes (Mount, WebSocket) ont
        # `methods` en list, pas en set → `list - set` lève TypeError.
        raw_methods = getattr(r, "methods", None) or set()
        methods = sorted(list(set(raw_methods) - {"HEAD", "OPTIONS"}))
        if not methods:
            continue
        tags = list(getattr(r, "tags", []) or [])
        endpoint = getattr(r, "endpoint", None)
        doc = (endpoint.__doc__ or "") if endpoint else ""
        routes.append(
            {
                "path": path,
                "methods": methods,
                "name": getattr(r, "name", ""),
                "tags": tags,
                "summary": getattr(r, "summary", "") or doc.strip().split("\n")[0],
            }
        )
    routes.sort(key=lambda r: (r["tags"][0] if r["tags"] else "", r["path"]))
    return routes


# =====================================================================
# Lot 29 (performances) — temps de réponse par route depuis le dernier
# démarrage (mesures prises par request_timing_middleware dans server.py).
# Réservé à l'admin et au Superviseur ; affiché dans Santé applicative.
# =====================================================================
@api.get("/admin/perf/routes", tags=["Admin"])
async def admin_perf_routes(limit: int = 60, sort: str = "total", _: dict = Depends(get_admin_or_supervisor)):
    rows = []
    for key, (n, total, mx, slow) in list(_PERF_STATS.items()):
        method, _sp, path = key.partition(" ")
        rows.append({"method": method, "path": path, "count": int(n),
                     "avg_ms": round(total / n * 1000) if n else 0,
                     "max_ms": round(mx * 1000), "total_s": round(total, 1), "over_1s": int(slow)})
    # tri : temps cumulé (ce qui charge le plus le serveur), moyenne ou maximum
    keyf = {"avg": lambda r: r["avg_ms"], "max": lambda r: r["max_ms"], "count": lambda r: r["count"]}.get(
        sort, lambda r: r["total_s"])
    rows.sort(key=keyf, reverse=True)
    return {"since": _PERF_SINCE, "routes": rows[:max(1, min(limit, 500))], "tracked": len(rows)}
