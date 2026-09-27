# server_parts/p13_whatsapp_supervision.py — Détecteur de silence WhatsApp, santé des intégrations, simulation de message entrant.
# Morceau de l'ancien server.py (lignes 18301 à 19343), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ============================================================
# Iter35b — WhatsApp inbound silence detector.
#
# Why: when Meta stops calling our webhook (token mismatch, ad-account
# review, regional outage, …) the symptom is invisible to the user — they
# see their outbound bulk sends succeed but never get the replies. The
# CRM looks empty even though customers ARE replying.
#
# How: every 4 hours we count outbound WA messages sent in the trailing
# `window_hours` (default 24) and webhook hits received in the same
# window. If outbound >= `threshold` AND inbound == 0, we fire an alert
# (email + optional Discord) and stamp `wa_silence_alert_last_fired_at`
# to avoid spamming. The check is also exposed as a manual admin endpoint.
# ============================================================
async def _run_wa_silence_check(triggered_by: str = "cron") -> dict:
    s = await db.settings.find_one({"_id": "global"}) or {}
    enabled = bool(s.get("wa_silence_alert_enabled"))
    threshold = int(s.get("wa_silence_alert_threshold") or 3)
    window_hours = max(1, min(int(s.get("wa_silence_alert_window_hours") or 24), 168))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    cutoff_iso = cutoff.isoformat()

    # Count outbound WA messages sent in the window (direction != inbound).
    # The schema mixes legacy {to, template_name} rows and new {direction: 'outbound'}
    # rows, so we count any message that isn't explicitly marked inbound.
    outbound_n = await db.whatsapp_messages.count_documents({
        "$and": [
            {"created_at": {"$gte": cutoff_iso}},
            {"direction": {"$ne": "inbound"}},
        ],
    })
    inbound_webhook_n = await db.wa_webhook_logs.count_documents({
        "received_at": {"$gte": cutoff_iso},
    })
    # Optional: also count inbound messages persisted (catches the case where
    # webhook IS firing but logs got purged).
    inbound_msg_n = await db.whatsapp_messages.count_documents({
        "$and": [
            {"created_at": {"$gte": cutoff_iso}},
            {"direction": "inbound"},
        ],
    })

    silent = (outbound_n >= threshold) and (inbound_webhook_n == 0) and (inbound_msg_n == 0)

    result = {
        "ok": True,
        "enabled": enabled,
        "window_hours": window_hours,
        "threshold": threshold,
        "outbound_count": outbound_n,
        "inbound_webhook_count": inbound_webhook_n,
        "inbound_message_count": inbound_msg_n,
        "silent": silent,
        "fired": False,
        "triggered_by": triggered_by,
        "checked_at": _now(),
    }

    if not (enabled and silent):
        return result

    # Throttle — only fire once per window_hours
    last_fired = s.get("wa_silence_alert_last_fired_at")
    if last_fired:
        try:
            last_dt = datetime.fromisoformat(last_fired.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - last_dt).total_seconds() < window_hours * 3600:
                result["fired"] = False
                result["throttled_until"] = (last_dt + timedelta(hours=window_hours)).isoformat()
                return result
        except Exception:  # noqa: BLE001
            pass

    # ----- Fire the alert -----
    recipient = (s.get("wa_silence_alert_email_to") or s.get("health_email_to") or SUPER_ADMIN_EMAIL).strip().lower()
    discord_url = (s.get("wa_silence_alert_discord_webhook") or "").strip()

    subject = f"[SAWALI ALERT] WhatsApp silence ({window_hours}h)"
    html = (
        f"<div style='font-family:Arial,sans-serif;'>"
        f"<h3 style='color:#EF4444'>🚨 Aucun webhook WhatsApp reçu depuis {window_hours} h</h3>"
        f"<p>Votre instance a envoyé <b>{outbound_n}</b> message(s) WhatsApp ces dernières <b>{window_hours}</b> heures, "
        f"mais Meta n'a appelé votre webhook <code>/api/whatsapp/webhook</code> <b>0 fois</b>.</p>"
        f"<p>Symptômes probables :</p>"
        f"<ul>"
        f"<li>Verify Token modifié côté Meta sans mise à jour ici (ou vice-versa)</li>"
        f"<li>URL du webhook expirée / fermée côté Meta Business Suite</li>"
        f"<li>Numéro de téléphone WABA temporairement suspendu</li>"
        f"<li>Incident régional côté Meta (vérifier <a href='https://metastatus.com/'>metastatus.com</a>)</li>"
        f"</ul>"
        f"<p><b>Action recommandée :</b> ouvrez <a href='https://business.facebook.com/wa/manage/home/'>Meta Business Suite → WhatsApp → Configuration</a> "
        f"et cliquez « Tester » sur la ligne du webhook. Puis ouvrez votre panneau d'admin → Paramètres → "
        f"« Inspecter les payloads Meta entrants » pour confirmer.</p>"
        f"<hr/><p style='color:#64748B;font-size:12px;'>Détection automatique — {result['checked_at']}.</p>"
        f"</div>"
    )
    text = (
        f"WA SILENCE — {outbound_n} outbound, 0 inbound on the last {window_hours}h.\n"
        f"Check Meta Business Suite → WhatsApp → Configuration."
    )

    sent_email = False
    try:
        from email_service import send_email
        sent_email = bool(await send_email(recipient, subject, html, text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("WA silence alert email failed: %s", exc)

    sent_discord = False
    if discord_url and discord_url.startswith("http"):
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                disc_payload = {
                    "content": (
                        f"🚨 **WhatsApp silence** — {outbound_n} message(s) envoyé(s) en {window_hours} h, "
                        f"0 webhook reçu. Vérifiez Meta Business Suite → WhatsApp → Configuration."
                    ),
                }
                r = await http.post(discord_url, json=disc_payload)
                sent_discord = r.status_code < 300
        except Exception as exc:  # noqa: BLE001
            logger.warning("WA silence discord alert failed: %s", exc)

    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {"wa_silence_alert_last_fired_at": _now(), "updated_at": _now()}},
        upsert=True,
    )
    # Audit trail
    try:
        await db.wa_silence_alerts.insert_one({
            "id": _uuid(),
            "fired_at": _now(),
            "window_hours": window_hours,
            "outbound_count": outbound_n,
            "inbound_webhook_count": inbound_webhook_n,
            "inbound_message_count": inbound_msg_n,
            "email_to": recipient if sent_email else None,
            "email_sent": sent_email,
            "discord_sent": sent_discord,
            "triggered_by": triggered_by,
        })
    except Exception:  # noqa: BLE001
        pass

    result.update({"fired": True, "email_sent": sent_email, "discord_sent": sent_discord, "email_to": recipient})
    return result


@api.post("/admin/whatsapp/silence-check", tags=["Admin"])
async def admin_run_wa_silence_check(_: dict = Depends(get_current_admin)):
    """Manually run the WhatsApp silence detector (also runs every 4h via cron).
    Returns the counts and whether an alert was fired. Useful for testing
    your email/Discord webhook configuration."""
    return await _run_wa_silence_check(triggered_by="manual")


@api.get("/admin/whatsapp/silence-alerts", tags=["Admin"])
async def admin_list_wa_silence_alerts(
    limit: int = Query(default=50, ge=1, le=200),
    _: dict = Depends(get_current_admin),
):
    """Liste les alertes de silence passées (piste d'audit)."""
    items = await db.wa_silence_alerts.find({}, {"_id": 0}).sort("fired_at", -1).to_list(limit)
    return {"items": items, "count": len(items)}


# ============================================================================
# Iter43-fix24ap (2026-06-17) — Integration health monitor (Google Calendar
# + Meta WA Webhook). Periodically tests both connections and sends a
# WhatsApp message to the configured admin number if either fails. Also
# persists each run in `db.integration_health_checks` for audit.
# ============================================================================
async def _run_integration_health_check(triggered_by: str = "cron") -> dict:
    """Verifies that Google Calendar refresh_token AND Meta Webhook
    subscription are both healthy. Alerts the admin via WhatsApp on the
    very first failure detected after a healthy state (no spam — only
    when state changes from OK→FAIL or after a 24h re-confirm window)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    enabled = bool(s.get("integration_health_alerts_enabled", True))
    alert_wa_phone = (s.get("integration_health_alert_wa_phone") or s.get("super_admin_phone") or "").strip()

    # ----- 1) Google Calendar -----
    gcal_status = {"ok": False, "reason": None, "message": None}
    try:
        if await gcal.is_configured():
            events = await gcal.list_upcoming_events(max_results=1)
            gcal_status = {"ok": True, "events_count": len(events), "message": "Refresh token valide, API OK."}
        else:
            gcal_status = {"ok": False, "reason": "not_connected", "message": "Non connecté."}
    except Exception as exc:  # noqa: BLE001
        gcal_status = {
            "ok": False, "reason": "api_error",
            "message": str(exc)[:300],
            "error_type": type(exc).__name__,
        }

    # ----- 2) Meta WA Webhook subscription -----
    meta_status = {"ok": False, "reason": None, "message": None}
    access_token = (s.get("wa_access_token") or "").strip()
    waba_id = (s.get("wa_business_account_id") or "").strip()
    if not access_token or not waba_id:
        meta_status = {"ok": False, "reason": "missing_config", "message": "wa_access_token ou waba_id absent."}
    else:
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.get(
                    f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}/subscribed_apps",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if r.status_code >= 300:
                    err = (r.json() or {}).get("error") or {}
                    meta_status = {
                        "ok": False, "reason": "api_error",
                        "message": err.get("message") or f"HTTP {r.status_code}",
                        "error_code": err.get("code"),
                    }
                else:
                    apps = (r.json() or {}).get("data") or []
                    if not apps:
                        meta_status = {"ok": False, "reason": "no_subscription",
                                       "message": "Aucune app abonnée au WABA — webhook entrant cassé."}
                    else:
                        meta_status = {"ok": True, "subscribed_apps": len(apps), "message": "Souscription présente."}
        except Exception as exc:  # noqa: BLE001
            meta_status = {"ok": False, "reason": "exception",
                           "message": str(exc)[:300], "error_type": type(exc).__name__}

    overall_ok = gcal_status["ok"] and meta_status["ok"]
    result = {
        "ok": overall_ok,
        "google_calendar": gcal_status,
        "meta_webhook": meta_status,
        "triggered_by": triggered_by,
        "checked_at": _now(),
        "alert_sent": False,
    }

    # Persist every run for audit / dashboard
    try:
        await db.integration_health_checks.insert_one({
            "id": _uuid(), **result,
        })
    except Exception:  # noqa: BLE001
        pass

    if overall_ok or not enabled:
        return result

    # Throttle: don't re-alert if same failures already sent in the last 12h
    last_alert = s.get("integration_health_last_alert") or {}
    try:
        last_at = last_alert.get("fired_at")
        if last_at:
            last_dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            # Only re-alert if either status FLIPPED (new failure) or 12h passed
            same_failures = (
                last_alert.get("gcal_ok") == gcal_status["ok"]
                and last_alert.get("meta_ok") == meta_status["ok"]
            )
            if same_failures and (datetime.now(timezone.utc) - last_dt).total_seconds() < 12 * 3600:
                result["alert_throttled"] = True
                return result
    except Exception:  # noqa: BLE001
        pass

    # ----- Fire WhatsApp alert -----
    if alert_wa_phone:
        problems: list[str] = []
        if not gcal_status["ok"]:
            problems.append(f"🟥 *Google Calendar* : {gcal_status.get('message', '?')}")
        if not meta_status["ok"]:
            problems.append(f"🟥 *Meta WA Webhook* : {meta_status.get('message', '?')}")
        text = (
            "🚨 *SAWALI — Alerte intégrations*\n\n"
            + "\n".join(problems)
            + "\n\nVérifiez Admin Settings → respectivement Google Calendar / WhatsApp."
            + f"\n\n_Détecté à {result['checked_at'][:19]}Z — Liluvine PRO 🤖_"
        )
        try:
            send_res = await _wa_send_text(alert_wa_phone, text)
            result["alert_sent"] = bool(send_res.get("ok"))
            result["alert_to"] = alert_wa_phone
            result["alert_error"] = send_res.get("error") if not send_res.get("ok") else None
        except Exception as exc:  # noqa: BLE001
            result["alert_sent"] = False
            result["alert_error"] = str(exc)[:200]
    else:
        result["alert_skipped"] = "no_admin_wa_phone_configured"

    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {"integration_health_last_alert": {
            "fired_at": _now(),
            "gcal_ok": gcal_status["ok"],
            "meta_ok": meta_status["ok"],
        }}},
        upsert=True,
    )
    return result


@api.get("/admin/integrations/health-check", tags=["Admin"])
async def admin_integration_health_check(_: dict = Depends(get_current_admin)):
    """Run the integration health check manually (also runs every 4h via cron).
    Returns the live status of Google Calendar + Meta Webhook + whether an
    alert was fired/throttled."""
    return await _run_integration_health_check(triggered_by="manual")


@api.get("/admin/integrations/health-history", tags=["Admin"])
async def admin_integration_health_history(
    limit: int = Query(default=30, ge=1, le=200),
    _: dict = Depends(get_current_admin),
):
    """Historique des contrôles de santé (audit / monitoring)."""
    items = await db.integration_health_checks.find({}, {"_id": 0}).sort("checked_at", -1).to_list(limit)
    return {"items": items, "count": len(items)}





@api.get("/admin/whatsapp/templates", tags=["Admin"])
async def admin_list_wa_templates(_: dict = Depends(get_current_admin)):
    """Liste tous les modèles du WABA configuré + fusionne les notes admin (description + disponibilité)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token")
    waba_id = s.get("wa_business_account_id")
    if not access_token or not waba_id:
        return {"configured": False, "items": []}
    url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}/message_templates?limit=100"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(url, headers={"Authorization": f"Bearer {access_token}"})
            if r.status_code >= 300:
                return {"configured": True, "items": [], "error": f"HTTP {r.status_code}"}
            d = r.json()
            notes_map = await _load_template_notes_map()
            items = []
            for t in (d.get("data") or []):
                note = notes_map.get(t["name"]) or {}
                t["note_description"] = note.get("description") or ""
                # Default TRUE when not explicitly set
                t["is_available_for_users"] = note.get("is_available_for_users", True)
                items.append(t)
            return {"configured": True, "items": items}
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "items": [], "error": str(exc)[:200]}


@api.get("/admin/whatsapp/token-health", tags=["Admin"])
async def admin_wa_token_health(_: dict = Depends(get_current_admin)):
    """Iter43-fix3 (2026-03) — Diagnostic du token WhatsApp Cloud API.

    Le pattern « marche 2 jours puis brusquement plus rien » est typique des
    tokens **utilisateur courts** (24 h) générés depuis le dashboard Meta.
    Cet endpoint appelle `/debug_token` pour révéler :
      - validité actuelle (`is_valid`)
      - date d'expiration (`expires_at`, `data_access_expires_at`)
      - type (USER vs SYSTEM_USER → seul SYSTEM_USER ne peut pas expirer)
      - scopes accordés
      - app id propriétaire
    Plus un test fonctionnel sur le `phone_number_id` configuré.

    Réponse :
      {
        "ok": bool, "token_type": "USER"|"SYSTEM_USER", "is_valid": bool,
        "expires_at": "2026-03-31T...Z" | null,
        "days_to_expiry": float | null,
        "scopes": [...], "app_id": str | null,
        "phone_check": {"ok": bool, "display_phone_number": "...", "verified_name": "..."}
      }
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = (s.get("wa_access_token") or "").strip()
    phone_number_id = (s.get("wa_phone_number_id") or "").strip()
    app_secret = (s.get("meta_app_secret") or "").strip()
    if not access_token:
        return {"ok": False, "reason": "no_token", "message": "wa_access_token vide dans Settings"}
    out: Dict[str, Any] = {"ok": False, "token_type": None, "is_valid": None,
                            "expires_at": None, "days_to_expiry": None,
                            "scopes": [], "app_id": None, "phone_check": None,
                            "message": None}
    # 1) Diagnostic du token via /debug_token (requiert app_token: app_id|app_secret)
    try:
        async with httpx.AsyncClient(timeout=8) as http:
            # Meta accepte access_token=<user_token> en input_token + le même user
            # comme caller (introspection self) si pas d'app_secret configuré.
            params = {"input_token": access_token}
            app_id = (s.get("meta_app_id") or "").strip()
            if app_id and app_secret:
                params["access_token"] = f"{app_id}|{app_secret}"
            else:
                # Auto-introspection (Meta autorise un user token à s'inspecter lui-même)
                params["access_token"] = access_token
            r = await http.get(f"https://graph.facebook.com/{WA_GRAPH_VERSION}/debug_token", params=params)
            d = r.json() if r.status_code < 500 else {}
            data = (d or {}).get("data") or {}
            if r.status_code >= 300 or not data:
                out["message"] = (d.get("error") or {}).get("message") or f"HTTP {r.status_code}"
            else:
                out["is_valid"] = bool(data.get("is_valid"))
                out["token_type"] = data.get("type")  # USER | SYSTEM_USER | PAGE
                out["app_id"] = data.get("app_id")
                out["scopes"] = data.get("scopes") or []
                exp = data.get("expires_at")  # epoch seconds, 0 = never
                if exp and exp > 0:
                    from datetime import datetime as _dt, timezone as _tz
                    dt = _dt.fromtimestamp(exp, tz=_tz.utc)
                    out["expires_at"] = dt.isoformat()
                    delta = (dt - _dt.now(_tz.utc)).total_seconds() / 86400
                    out["days_to_expiry"] = round(delta, 2)
                else:
                    out["expires_at"] = None
                    out["days_to_expiry"] = None  # never expires
    except Exception as exc:  # noqa: BLE001
        out["message"] = f"debug_token exception: {exc}"

    # 2) Test fonctionnel sur le phone_number_id
    if phone_number_id and access_token:
        try:
            async with httpx.AsyncClient(timeout=8) as http:
                r = await http.get(
                    f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{phone_number_id}",
                    params={"fields": "display_phone_number,verified_name,quality_rating,name_status"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if r.status_code < 300:
                    out["phone_check"] = {"ok": True, **r.json()}
                else:
                    err = (r.json().get("error") or {}) if r.headers.get("content-type", "").startswith("application/json") else {}
                    out["phone_check"] = {"ok": False, "error": err.get("message") or f"HTTP {r.status_code}", "error_code": err.get("code")}
        except Exception as exc:  # noqa: BLE001
            out["phone_check"] = {"ok": False, "error": str(exc)[:200]}

    # Verdict global
    out["ok"] = bool(out.get("is_valid")) and (out.get("phone_check") or {}).get("ok") in (True, None)
    if out["token_type"] == "USER" and out.get("days_to_expiry") is not None:
        # Avertir avant expiration (typique : 24-60 jours)
        if out["days_to_expiry"] < 7:
            out["warning"] = f"⚠️ Token utilisateur expire dans {out['days_to_expiry']} jour(s) — passez à un token SYSTEM_USER permanent."
    elif out["token_type"] == "USER":
        out["warning"] = "⚠️ Token de type USER : risque d'expiration inopinée. Utilisez un token SYSTEM_USER permanent pour la production."
    return out


@api.get("/admin/whatsapp/webhook-subscription", tags=["Admin"])
async def admin_wa_webhook_subscription(_: dict = Depends(get_current_admin)):
    """Iter43-fix16 (2026-06) — Diagnostic de la souscription du webhook Meta.

    Symptôme couvert : « les messages sortants partent bien mais plus aucun
    message entrant n'arrive depuis X jours ». Cause type : Meta a retiré
    l'application du WABA (révision en cours, app paused, expiration de la
    permission, etc.) → la souscription `messages` est perdue côté Meta.

    Appelle GET /{waba_id}/subscribed_apps pour lister les apps actuellement
    abonnées + leurs `subscribed_fields`. Vérifie qu'au moins une app contient
    le champ `messages`. Retourne aussi le `messaging_product` et le statut
    du numéro.
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = (s.get("wa_access_token") or "").strip()
    waba_id = (s.get("wa_business_account_id") or "").strip()
    phone_number_id = (s.get("wa_phone_number_id") or "").strip()
    if not access_token or not waba_id:
        return {
            "ok": False,
            "reason": "missing_config",
            "message": "wa_access_token ou wa_business_account_id vide dans Settings.",
            "configured": {
                "access_token": bool(access_token),
                "waba_id": bool(waba_id),
                "phone_number_id": bool(phone_number_id),
            },
        }
    out: Dict[str, Any] = {
        "ok": False,
        "waba_id": waba_id,
        "phone_number_id": phone_number_id or None,
        "subscribed_apps": [],
        "messages_subscribed": False,
        "message": None,
        # Iter43-fix24ar (2026-02) — Token health probe (debug-info shown in UI
        # whenever `subscribed_apps` fails so the admin can self-diagnose
        # WITHOUT needing server logs).
        "token_probe": None,
    }
    # ----- 1) Probe the token first via /me (cheap, always returns) -----
    try:
        async with httpx.AsyncClient(timeout=8) as http:
            r0 = await http.get(
                f"https://graph.facebook.com/{WA_GRAPH_VERSION}/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            try:
                me_json = r0.json()
            except Exception:  # noqa: BLE001
                me_json = {"_raw_text": (r0.text or "")[:300]}
            out["token_probe"] = {
                "status": r0.status_code,
                "ok": r0.status_code < 300,
                "id": me_json.get("id") if isinstance(me_json, dict) else None,
                "name": me_json.get("name") if isinstance(me_json, dict) else None,
                "error": (
                    ((me_json or {}).get("error") or {}).get("message")
                    if isinstance(me_json, dict) else None
                ),
                "error_code": (
                    ((me_json or {}).get("error") or {}).get("code")
                    if isinstance(me_json, dict) else None
                ),
            }
            if r0.status_code >= 300:
                # Surface a clear "token expired/revoked" message early so the
                # admin knows to refresh the System User token before clicking
                # « Re-souscrire » (which would also fail with the same cause).
                err_obj = (me_json or {}).get("error") if isinstance(me_json, dict) else {}
                err_code = (err_obj or {}).get("code")
                # 190 = OAuthException token expired/invalid
                if err_code == 190:
                    out["message"] = (
                        "🔑 *Token Meta expiré ou invalide* (code 190). "
                        "Régénérez un System User Token permanent dans "
                        "Meta Business Manager → Paramètres business → Utilisateurs système "
                        "→ Générer un nouveau token, puis collez-le dans Admin Settings → WhatsApp."
                    )
                    out["error_code"] = err_code
                    out["error_type"] = (err_obj or {}).get("type") or "OAuthException"
                    return out
    except Exception as exc:  # noqa: BLE001
        out["token_probe"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }

    # ----- 2) Now the actual subscribed_apps call -----
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(
                f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}/subscribed_apps",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            # Always expose the HTTP status + raw preview so the UI can render
            # a helpful diagnostic even when the body isn't a dict.
            out["http_status"] = r.status_code
            try:
                data = r.json()
            except Exception as je:  # noqa: BLE001
                out["raw_response_preview"] = (r.text or "")[:500]
                out["message"] = (
                    f"⚠️ Réponse non-JSON de Meta ({type(je).__name__}). "
                    f"HTTP {r.status_code}. Aperçu : "
                    f"{(r.text or '')[:160]!r}"
                )
                return out
            if r.status_code >= 300:
                err = (data or {}).get("error") or {} if isinstance(data, dict) else {}
                out["message"] = err.get("message") or f"HTTP {r.status_code}"
                out["error_code"] = err.get("code")
                out["error_type"] = err.get("type")
                out["raw_response_preview"] = str(data)[:500]
                return out
            apps = (data or {}).get("data") or [] if isinstance(data, dict) else []
            out["subscribed_apps"] = apps
            has_messages = False
            for a in apps:
                fields = a.get("subscribed_fields") or []
                if isinstance(fields, list) and any(
                    (f.get("name") if isinstance(f, dict) else str(f)) == "messages"
                    for f in fields
                ):
                    has_messages = True
                    break
            # Si l'API ne renvoie pas `subscribed_fields` (token sans scope),
            # on se contente de la présence d'une app abonnée.
            if not has_messages and apps:
                has_messages = True
                out["note"] = (
                    "Souscription présente mais Meta n'a pas renvoyé `subscribed_fields` "
                    "(token sans scope `whatsapp_business_management` étendu). "
                    "Le compte est probablement OK."
                )
            out["messages_subscribed"] = has_messages
            out["ok"] = has_messages
            if not apps:
                out["message"] = (
                    "❌ Aucune app abonnée à ce WABA — Meta n'enverra plus jamais "
                    "de webhook tant que vous n'aurez pas re-souscrit l'app. "
                    "Cliquez sur « 🔁 Re-souscrire le webhook » ci-dessous."
                )
    except Exception as exc:  # noqa: BLE001
        out["message"] = (
            f"⚠️ Erreur réseau lors de l'appel Meta : "
            f"{type(exc).__name__}: {str(exc)[:200] or '(message vide)'}"
        )
        out["error_type"] = type(exc).__name__
    return out


@api.post("/admin/whatsapp/webhook-subscribe", tags=["Admin"])
async def admin_wa_webhook_subscribe(_: dict = Depends(get_current_admin)):
    """Iter43-fix16 — Re-souscrire l'app Meta au WABA pour rétablir le
    flux des webhooks entrants. Equivalent à POST /{waba_id}/subscribed_apps.

    À utiliser quand le diagnostic `webhook-subscription` renvoie
    `subscribed_apps: []`. Requiert que le token actuel ait au moins
    `whatsapp_business_management` (ce qui est le cas pour un token capable
    d'envoyer des messages).
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = (s.get("wa_access_token") or "").strip()
    waba_id = (s.get("wa_business_account_id") or "").strip()
    if not access_token or not waba_id:
        raise HTTPException(status_code=400, detail="wa_access_token ou wa_business_account_id manquant")
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(
                f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}/subscribed_apps",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code >= 300:
                err = {}
                try:
                    err = (r.json() or {}).get("error") or {}
                except Exception:  # noqa: BLE001
                    pass
                return {
                    "ok": False,
                    "status": r.status_code,
                    "message": err.get("message") or f"HTTP {r.status_code}",
                    "error_code": err.get("code"),
                    "error_type": err.get("type"),
                    "fbtrace_id": err.get("fbtrace_id"),
                    "hint": (
                        "Si l'erreur dit 'permission denied' ou 'app does not have permission', "
                        "ouvrez Meta Business Suite → Paramètres → Comptes WhatsApp → "
                        "votre WABA → Apps connectées, et vérifiez que l'app est bien associée."
                    ),
                }
            body = r.json() or {}
            return {
                "ok": True,
                "status": r.status_code,
                "response": body,
                "message": (
                    "✅ Souscription re-créée. Meta devrait recommencer à appeler "
                    "votre webhook dans les prochaines secondes. Envoyez un message WA "
                    "depuis un téléphone vers votre numéro Business pour confirmer."
                ),
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "message": (
                f"⚠️ Erreur réseau : {type(exc).__name__}: "
                f"{str(exc)[:200] or '(message vide)'}"
            ),
            "error_type": type(exc).__name__,
        }


# ============================================================================
# Iter43-fix24ar (2026-02) — Simulate an inbound WhatsApp message END-TO-END.
#
# Use case : the admin wants to verify that incoming messages reach the
# Unified Inbox + trigger AI auto-reply + show up in notifications, WITHOUT
# depending on Meta actually calling our webhook (Meta side may be broken,
# or we just want to debug the local pipeline in isolation).
#
# This endpoint synthesizes the exact JSON payload Meta would send and
# routes it through the same `whatsapp_webhook_incoming` handler. The
# admin gets back the inserted message id + the webhook_log id so they
# can trace what happened.
# ============================================================================
class _SimulateInboundPayload(BaseModel):
    from_phone: str = Field(..., min_length=4, max_length=30)  # E.164 (e.g. +22670112233)
    text: str = Field(..., min_length=1, max_length=2000)
    profile_name: Optional[str] = None


@api.post("/admin/whatsapp/simulate-inbound", tags=["Admin"])
async def admin_wa_simulate_inbound(
    payload: _SimulateInboundPayload,
    request: Request,
    _: dict = Depends(get_current_admin),
):
    """Synthétise un payload Meta WhatsApp inbound et le route à travers
    le vrai handler. Permet de valider le pipeline message_center +
    notifications + Liluvine SANS dépendre de Meta. Renvoie un résumé
    (msg id inséré, AI reply, etc.)."""
    from_phone = payload.from_phone.strip().lstrip("+")
    if not from_phone.isdigit() or len(from_phone) < 6:
        raise HTTPException(status_code=400, detail="Format E.164 invalide (ex: +22670112233)")

    sim_id = f"wamid.SIM_{uuid.uuid4().hex[:24]}"
    ts = int(datetime.now(timezone.utc).timestamp())
    s = await db.settings.find_one({"_id": "global"}) or {}
    phone_number_id = (s.get("wa_phone_number_id") or "_test_pnid_").strip()

    meta_payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": (s.get("wa_business_account_id") or "_test_waba_").strip(),
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "+225 00 00 00 00",
                        "phone_number_id": phone_number_id,
                    },
                    "contacts": [{
                        "profile": {"name": (payload.profile_name or f"Sim {from_phone[-4:]}")},
                        "wa_id": from_phone,
                    }],
                    "messages": [{
                        "from": from_phone,
                        "id": sim_id,
                        "timestamp": str(ts),
                        "type": "text",
                        "text": {"body": payload.text},
                    }],
                },
            }],
        }],
    }

    # Send the payload through the SAME entrypoint Meta would call.
    raw_bytes = json.dumps(meta_payload).encode("utf-8")
    # Mock a minimal Request with the synthesized body.
    sim_request = Request(scope=request.scope.copy())
    sim_request._body = raw_bytes  # type: ignore[attr-defined]

    # Call the handler directly. It returns {"ok": True} or raises.
    try:
        await whatsapp_webhook_incoming(sim_request)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "stage": "handler_crash",
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }

    # Read back to confirm persistence
    inserted = await db.whatsapp_messages.find_one(
        {"wa_message_id": sim_id},
        {"_id": 0, "id": 1, "client_id": 1, "body": 1, "contact_id": 1, "contact_name": 1,
         "from_profile_name": 1, "from": 1, "phone_digits": 1, "received_at": 1},
    )
    # Also fetch the most recent webhook log entry tied to this run
    log_entry = await db.wa_webhook_logs.find_one(
        {"body.entry.changes.value.messages.id": sim_id},
        {"_id": 0, "id": 1, "extracted_messages": 1, "inserted_messages": 1, "errors": 1},
    )
    # Outbound AI reply (if any) - last outbound to that phone in the last 60s
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    ai_reply = await db.whatsapp_messages.find_one(
        {"phone_digits": from_phone, "direction": {"$ne": "inbound"}, "created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "body": 1, "wa_message_id": 1, "auto_reply": 1, "command": 1,
         "ai_generated": 1},
        sort=[("created_at", -1)],
    )

    return {
        "ok": bool(inserted),
        "inserted": inserted,
        "webhook_log": log_entry,
        "ai_reply": ai_reply,
        "hint": (
            "Si `inserted` est null, le pipeline est cassé (consulter les logs Liluvine). "
            "Si `inserted.client_id` ne correspond pas à votre tenant, le scope par défaut "
            "(superviseur → admin → super-admin) doit être revu."
        ),
    }






# ---------- Admin-managed template notes (index by name) ----------
async def _load_template_notes_map() -> Dict[str, Dict[str, Any]]:
    docs = await db.wa_template_notes.find({}, {"_id": 0}).to_list(1000)
    return {d["name"]: d for d in docs if d.get("name")}


@api.get("/admin/whatsapp/template-notes", tags=["Admin"])
async def admin_list_template_notes(_: dict = Depends(get_current_admin)):
    docs = await db.wa_template_notes.find({}, {"_id": 0}).sort("name", 1).to_list(1000)
    return docs


class WaTemplateNoteUpsert(BaseModel):
    description: Optional[str] = None
    is_available_for_users: Optional[bool] = None


@api.put("/admin/whatsapp/template-notes/{name}", tags=["Admin"])
async def admin_upsert_template_note(
    name: str, payload: WaTemplateNoteUpsert, _: dict = Depends(get_current_admin),
):
    name = (name or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Nom de template manquant")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    update["name"] = name
    await db.wa_template_notes.update_one({"name": name}, {"$set": update}, upsert=True)
    doc = await db.wa_template_notes.find_one({"name": name}, {"_id": 0})
    return doc


@api.delete("/admin/whatsapp/template-notes/{name}", tags=["Admin"])
async def admin_delete_template_note(name: str, _: dict = Depends(get_current_admin)):
    await db.wa_template_notes.delete_one({"name": (name or "").strip().lower()})
    return {"ok": True}


# ---------- Templates: create / delete (Meta submission flow) ----------
WA_TEMPLATE_CATEGORIES = {"UTILITY", "MARKETING", "AUTHENTICATION"}
_TEMPLATE_NAME_RE = re.compile(r"^[a-z0-9_]{2,512}$")


class WaTemplateCreate(BaseModel):
    name: str
    language: str = "fr"
    category: str = "UTILITY"
    body_text: str  # Required by Meta. May contain {{1}}, {{2}}…
    body_examples: Optional[List[str]] = None  # Required when body has variables, len must match max({{N}})
    header_text: Optional[str] = None  # Optional plain-text header
    footer_text: Optional[str] = None  # Optional footer (max 60 chars per Meta)


def _count_body_vars(body: str) -> int:
    matches = [int(m.group(1)) for m in re.finditer(r"\{\{\s*(\d+)\s*\}\}", body or "")]
    return max(matches) if matches else 0


@api.post("/admin/whatsapp/templates", tags=["Admin"])
async def admin_create_wa_template(payload: WaTemplateCreate, _: dict = Depends(get_current_admin)):
    """Submit a new template to Meta for approval.
    Per Meta: name must be lowercase letters/digits/underscores, body is mandatory,
    {{1}}…{{N}} placeholders need example values."""
    name = (payload.name or "").strip().lower()
    if not _TEMPLATE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Nom invalide : minuscules, chiffres et _ uniquement (2-512 caractères)")
    category = (payload.category or "UTILITY").upper()
    if category not in WA_TEMPLATE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Catégorie invalide. Valeurs : {sorted(WA_TEMPLATE_CATEGORIES)}")
    body = (payload.body_text or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Le corps du template est requis")
    if len(body) > 1024:
        raise HTTPException(status_code=400, detail="Corps trop long (1024 caractères max)")
    n_vars = _count_body_vars(body)
    examples = payload.body_examples or []
    if n_vars > 0 and len(examples) < n_vars:
        raise HTTPException(status_code=400, detail=f"Exemples manquants : {n_vars} variable(s) détectée(s), {len(examples)} fournie(s)")
    if payload.header_text and len(payload.header_text.strip()) > 60:
        raise HTTPException(status_code=400, detail="Header trop long (60 caractères max)")
    if payload.footer_text and len(payload.footer_text.strip()) > 60:
        raise HTTPException(status_code=400, detail="Footer trop long (60 caractères max)")

    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token")
    waba_id = s.get("wa_business_account_id")
    if not access_token or not waba_id:
        raise HTTPException(status_code=400, detail="WhatsApp non configuré (renseignez WABA ID et Access Token dans Paramètres)")

    components: List[Dict[str, Any]] = []
    if payload.header_text:
        components.append({"type": "HEADER", "format": "TEXT", "text": payload.header_text.strip()})
    body_comp: Dict[str, Any] = {"type": "BODY", "text": body}
    if n_vars > 0:
        body_comp["example"] = {"body_text": [examples[:n_vars]]}
    components.append(body_comp)
    if payload.footer_text:
        components.append({"type": "FOOTER", "text": payload.footer_text.strip()})

    url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}/message_templates"
    body_payload = {
        "name": name,
        "language": payload.language or "fr",
        "category": category,
        "components": components,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(
                url,
                json=body_payload,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            )
            try:
                raw = r.json()
            except Exception:
                raw = {"text": r.text[:2000]}
            if r.status_code >= 300:
                err = (raw.get("error") or {}).get("message") if isinstance(raw, dict) else None
                # Never forward Meta 401/403 verbatim — the client axios interceptor
                # would log the admin out. Return 502 (Bad Gateway) so we surface
                # the Meta error without affecting our own auth session.
                raise HTTPException(status_code=502, detail=f"Meta API {r.status_code}: {err or f'Échec HTTP {r.status_code}'}")
            return {
                "ok": True,
                "name": name,
                "language": body_payload["language"],
                "category": category,
                "id": raw.get("id"),
                "status": raw.get("status") or "PENDING",
                "raw": raw,
            }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout Meta")


@api.delete("/admin/whatsapp/templates/{name}", tags=["Admin"])
async def admin_delete_wa_template(name: str, _: dict = Depends(get_current_admin)):
    """Supprime un modèle par nom (supprime TOUTES les langues de ce nom sur le WABA)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token")
    waba_id = s.get("wa_business_account_id")
    if not access_token or not waba_id:
        raise HTTPException(status_code=400, detail="WhatsApp non configuré")
    url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}/message_templates"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.delete(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"name": name},
            )
            try:
                raw = r.json()
            except Exception:
                raw = {"text": r.text[:1000]}
            if r.status_code >= 300:
                err = (raw.get("error") or {}).get("message") if isinstance(raw, dict) else None
                raise HTTPException(status_code=502, detail=f"Meta API {r.status_code}: {err or f'Échec HTTP {r.status_code}'}")
            return {"ok": True, "name": name, "raw": raw}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout Meta")


# ---------- Config validator ----------
@api.post("/admin/whatsapp/test-config", tags=["Admin"])
async def admin_test_wa_config(_: dict = Depends(get_current_admin)):
    """Validate Meta credentials by probing Graph API for WABA + phone number.
    Returns {ok, checks:[{key,label,ok,detail}], summary}."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token") or ""
    waba_id = s.get("wa_business_account_id") or ""
    phone_id = s.get("wa_phone_number_id") or ""
    app_id = s.get("wa_app_id") or ""

    checks: List[Dict[str, Any]] = []
    def add(key, label, ok, detail):
        checks.append({"key": key, "label": label, "ok": bool(ok), "detail": detail})

    # 1) Required fields
    add("access_token", "Access Token renseigné", bool(access_token), "Token présent" if access_token else "Manquant")
    add("waba_id", "WABA ID renseigné", bool(waba_id), waba_id or "Manquant")
    add("phone_id", "Phone Number ID renseigné", bool(phone_id), phone_id or "Manquant")
    add("app_id", "App ID renseigné (optionnel)", bool(app_id), app_id or "Non fourni (facultatif)")

    if not access_token or not waba_id or not phone_id:
        return {"ok": False, "checks": checks, "summary": "Informations requises manquantes — impossible de contacter Meta."}

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            # 2) WABA lookup
            r1 = await http.get(
                f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}",
                params={"fields": "id,name,message_template_namespace"},
                headers=headers,
            )
            try:
                d1 = r1.json()
            except Exception:
                d1 = {"text": r1.text[:500]}
            if r1.status_code < 300:
                name = d1.get("name") or "(sans nom)"
                add("waba_check", "WABA accessible", True, f"{name} (id={d1.get('id')})")
            else:
                err = (d1.get("error") or {}).get("message") if isinstance(d1, dict) else None
                add("waba_check", "WABA accessible", False, f"HTTP {r1.status_code} — {err or 'erreur Meta'}")

            # 3) Phone Number lookup
            r2 = await http.get(
                f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{phone_id}",
                params={"fields": "display_phone_number,verified_name,quality_rating,code_verification_status"},
                headers=headers,
            )
            try:
                d2 = r2.json()
            except Exception:
                d2 = {"text": r2.text[:500]}
            if r2.status_code < 300:
                display = d2.get("display_phone_number") or "?"
                verified = d2.get("verified_name") or "?"
                quality = d2.get("quality_rating") or "?"
                add("phone_check", "Numéro WhatsApp Business validé", True, f"{display} — {verified} — Qualité {quality}")
            else:
                err = (d2.get("error") or {}).get("message") if isinstance(d2, dict) else None
                add("phone_check", "Numéro WhatsApp Business validé", False, f"HTTP {r2.status_code} — {err or 'erreur Meta'}")

            # 4) Templates fetch probe
            r3 = await http.get(
                f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}/message_templates",
                params={"limit": 1},
                headers=headers,
            )
            if r3.status_code < 300:
                try:
                    total = len((r3.json() or {}).get("data") or [])
                except Exception:
                    total = 0
                add("templates_check", "Lecture des templates", True, f"Réponse Meta OK ({total} template(s) trouvé(s) dans la 1ère page)")
            else:
                try:
                    d3 = r3.json()
                    err = (d3.get("error") or {}).get("message") if isinstance(d3, dict) else None
                except Exception:
                    err = None
                add("templates_check", "Lecture des templates", False, f"HTTP {r3.status_code} — {err or 'erreur Meta'}")
    except httpx.TimeoutException:
        add("network", "Connexion Meta Graph API", False, "Timeout 10s — vérifiez la connectivité sortante du serveur")
    except Exception as exc:  # noqa: BLE001
        add("network", "Connexion Meta Graph API", False, f"Erreur : {str(exc)[:200]}")

    ok = all(c["ok"] for c in checks if c["key"] not in ("app_id",))  # app_id is optional
    summary = "Tous les paramètres sont valides — prêt à envoyer." if ok else "Un ou plusieurs paramètres sont invalides. Voir détail."
    return {"ok": ok, "checks": checks, "summary": summary}
