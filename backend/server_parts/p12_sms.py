# server_parts/p12_sms.py — Passerelle SMS multi-opérateurs, Orange, envois groupés et planifiés.
# Morceau de l'ancien server.py (lignes 15994 à 18300), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ============================================================
# SMS multi-provider gateway (Orange BFA / Moov BFA / Telecel BFA / OVH)
# Each Burkina provider is a configurable HTTP webhook (URL + method +
# auth + payload template). OVH uses its official HMAC-SHA1 signed API.
# Outbound usage is recorded in db.sms_messages for audit + analytics.
# ============================================================
SMS_BFA_PROVIDERS = ("orange", "moov", "telecel")


def _sms_substitute(template: str, mapping: Dict[str, str]) -> str:
    """Replace {phone}, {message}, {sender} (and any custom key) inside a string."""
    out = template or ""
    for k, v in (mapping or {}).items():
        out = out.replace("{" + k + "}", str(v if v is not None else ""))
    return out


def _sms_provider_cfg(s: Dict[str, Any], provider: str) -> Optional[Dict[str, Any]]:
    p = (provider or "").lower().strip()
    if p in SMS_BFA_PROVIDERS:
        if not s.get(f"sms_{p}_enabled"):
            return None
        return {
            "kind": "generic",
            "name": p,
            "url": s.get(f"sms_{p}_url"),
            "method": (s.get(f"sms_{p}_method") or "POST").upper(),
            "auth_type": (s.get(f"sms_{p}_auth_type") or "none").lower(),
            "token": s.get(f"sms_{p}_token"),
            "basic_user": s.get(f"sms_{p}_basic_user"),
            "basic_pass": s.get(f"sms_{p}_basic_pass"),
            "header_name": s.get(f"sms_{p}_header_name"),
            "header_value": s.get(f"sms_{p}_header_value"),
            "sender": s.get(f"sms_{p}_sender"),
            "payload_template": s.get(f"sms_{p}_payload_template"),
            "content_type": (s.get(f"sms_{p}_content_type") or "json").lower(),
            # Iter35i — Orange Developer OAuth2 client_credentials flow
            "oauth_url": s.get(f"sms_{p}_oauth_url"),
            "client_id": s.get(f"sms_{p}_client_id"),
            "client_secret": s.get(f"sms_{p}_client_secret"),
            "sender_msisdn": s.get(f"sms_{p}_sender_msisdn"),
        }
    if p == "ovh":
        if not s.get("sms_ovh_enabled"):
            return None
        return {
            "kind": "ovh",
            "name": "ovh",
            "endpoint": (s.get("sms_ovh_endpoint") or "ovh-eu").lower(),
            "application_key": s.get("sms_ovh_application_key"),
            "application_secret": s.get("sms_ovh_application_secret"),
            "consumer_key": s.get("sms_ovh_consumer_key"),
            "service_name": s.get("sms_ovh_service_name"),
            "sender": s.get("sms_ovh_sender") or "OVHSMS",
        }
    # Iter43-fix24g — Bird.com Channels API (remplace Africa's Talking)
    if p == "bird":
        if not s.get("bird_enabled"):
            return None
        # Validation minimale : Bird nécessite workspace_id, channel_id et access_key
        if not (s.get("bird_workspace_id") and s.get("bird_channel_id") and s.get("bird_access_key")):
            return None
        return {
            "kind": "bird",
            "name": "bird",
            "api_base_url": (s.get("bird_api_base_url") or "https://api.bird.com").rstrip("/"),
            "workspace_id": (s.get("bird_workspace_id") or "").strip(),
            "channel_id": (s.get("bird_channel_id") or "").strip(),
            "access_key": (s.get("bird_access_key") or "").strip(),
            "sender": (s.get("bird_default_sender") or "").strip() or None,
        }
    return None


def _sms_active_providers(s: Dict[str, Any]) -> List[str]:
    out = [p for p in SMS_BFA_PROVIDERS if s.get(f"sms_{p}_enabled")]
    if s.get("sms_ovh_enabled"):
        out.append("ovh")
    # Iter43-fix24g — Expose Bird.com comme provider sélectionnable dans les UI
    # (Portail SMS, Contacts, etc.). Apparaît seulement quand la config Bird
    # est complète : workspace_id + channel_id + access_key + toggle activé.
    if (
        s.get("bird_enabled")
        and s.get("bird_workspace_id")
        and s.get("bird_channel_id")
        and s.get("bird_access_key")
    ):
        out.append("bird")
    return out


def _sms_pick_default(s: Dict[str, Any], msisdn: str) -> Optional[str]:
    """Pick a default provider when caller passes 'auto' or omits provider."""
    explicit = (s.get("sms_default_provider") or "auto").lower()
    if explicit and explicit != "auto":
        return explicit if _sms_provider_cfg(s, explicit) else None
    actives = _sms_active_providers(s)
    if not actives:
        return None
    digits = "".join(ch for ch in (msisdn or "") if ch.isdigit())
    if digits.startswith("226"):
        for c in ("orange", "moov", "telecel"):
            if c in actives:
                return c
    if "ovh" in actives:
        return "ovh"
    return actives[0]


def _ovh_host(endpoint: str) -> str:
    e = (endpoint or "ovh-eu").lower()
    if e == "ovh-ca":
        return "https://ca.api.ovh.com/1.0"
    return "https://eu.api.ovh.com/1.0"


async def _sms_send_ovh(cfg: Dict[str, Any], msisdn_e164: str, message: str, sender: Optional[str]) -> Dict[str, Any]:
    """Send an SMS via OVH official API. Uses HMAC-SHA1 signing scheme."""
    if not all([cfg.get("application_key"), cfg.get("application_secret"), cfg.get("consumer_key"), cfg.get("service_name")]):
        return {"ok": False, "status": "failed", "api_message": "OVH credentials incomplete"}
    host = _ovh_host(cfg.get("endpoint"))
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            tr = await http.get(f"{host}/auth/time")
            ts = str(int(tr.text.strip())) if tr.status_code == 200 else str(int(datetime.now(timezone.utc).timestamp()))
    except Exception:  # noqa: BLE001
        ts = str(int(datetime.now(timezone.utc).timestamp()))
    url = f"{host}/sms/{cfg['service_name']}/jobs"
    body = {
        "charset": "UTF-8",
        "class": "phoneDisplay",
        "coding": "8bit",
        "message": message,
        "noStopClause": False,
        "priority": "high",
        "receivers": [msisdn_e164 if msisdn_e164.startswith("+") else f"+{msisdn_e164}"],
        "senderForResponse": False,
        "sender": sender or cfg.get("sender") or "OVHSMS",
        "validityPeriod": 2880,
    }
    body_str = json.dumps(body)
    to_sign = "+".join([cfg["application_secret"], cfg["consumer_key"], "POST", url, body_str, ts])
    signature = "$1$" + hashlib.sha1(to_sign.encode("utf-8")).hexdigest()
    headers = {
        "X-Ovh-Application": cfg["application_key"],
        "X-Ovh-Consumer": cfg["consumer_key"],
        "X-Ovh-Timestamp": ts,
        "X-Ovh-Signature": signature,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post(url, headers=headers, content=body_str)
            try:
                resp = r.json()
            except Exception:  # noqa: BLE001
                resp = {"raw": r.text[:500]}
            if r.status_code >= 300:
                return {"ok": False, "status": "failed", "http_status": r.status_code, "api_message": _safe_text(resp.get("message") if isinstance(resp, dict) else None) or f"HTTP {r.status_code}", "raw_response": resp}
            invalid = (resp.get("invalidReceivers") or []) if isinstance(resp, dict) else []
            valid = (resp.get("validReceivers") or []) if isinstance(resp, dict) else []
            if invalid and not valid:
                return {"ok": False, "status": "failed", "api_message": f"Numéro rejeté : {', '.join(invalid)}", "raw_response": resp}
            return {"ok": True, "status": "sent", "http_status": r.status_code, "api_message": _safe_text(resp.get("message") if isinstance(resp, dict) else None), "raw_response": resp}
    except httpx.TimeoutException:
        return {"ok": False, "status": "failed", "api_message": "OVH timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "failed", "api_message": str(exc)[:300]}


# ============================================================
# Iter35i — Orange Developer SMS API (OAuth2 client_credentials).
#
# Orange's official SMS API at https://api.orange.com/smsmessaging/v1 needs:
#  1. POST {oauth_url} with `Authorization: Basic base64(client_id:client_secret)`
#     and body `grant_type=client_credentials` ENCODED AS form-urlencoded.
#     This was the failing step — the generic flow sent JSON / no body, so
#     Orange answered: {"error":"invalid_request","error_description":"Missing grant_type in body"}
#  2. POST {url}/outbound/tel%3A%2B<sender>/requests with the OAuth Bearer
#     and a specific JSON envelope `outboundSMSMessageRequest`.
#
# We cache the access_token in memory for `expires_in - 60s` to avoid
# pestering the token endpoint on every send.
# ============================================================
_ORANGE_TOKEN_CACHE: Dict[str, Dict[str, Any]] = {}


async def _orange_get_token(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch (and cache) the OAuth2 client_credentials access token.

    Returns the parsed token document on success or {"error": ...} otherwise.
    The cache key combines the OAuth URL + client_id so re-configuring
    credentials invalidates the cached token.
    """
    oauth_url = (cfg.get("oauth_url") or "https://api.orange.com/oauth/v3/token").strip()
    client_id = (cfg.get("client_id") or "").strip()
    client_secret = (cfg.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        return {"error": "Identifiants OAuth Orange manquants (client_id ou client_secret)"}
    cache_key = f"{oauth_url}|{client_id}"
    cached = _ORANGE_TOKEN_CACHE.get(cache_key)
    now_ts = datetime.now(timezone.utc).timestamp()
    if cached and cached.get("expires_at", 0) > now_ts + 5:
        return {"access_token": cached["access_token"], "cached": True}
    import base64 as _b64
    basic = _b64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    # Iter35i-fix2 — belt-and-suspenders : send `data=dict` (httpx encodes
    # AND sets Content-Type) AND also explicit Content-Type header (some
    # corporate proxies strip auto-headers). + verbose logging on failure.
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    data = {"grant_type": "client_credentials"}
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(oauth_url, headers=headers, data=data)
            try:
                doc = r.json()
            except Exception:
                doc = {"raw": r.text[:300]}
            if r.status_code >= 300:
                logger.warning(
                    "Orange OAuth fail %s url=%s req_ct=%s req_body=%s resp=%s",
                    r.status_code, oauth_url,
                    r.request.headers.get("Content-Type"),
                    r.request.content[:200] if r.request.content else b"",
                    str(doc)[:300],
                )
                err_msg = doc.get("error_description") or doc.get("error") or str(doc)[:300]
                return {"error": f"OAuth Orange {r.status_code}: {err_msg}"}
            access_token = (doc or {}).get("access_token")
            expires_in = int((doc or {}).get("expires_in") or 3600)
            if not access_token:
                return {"error": f"OAuth Orange: pas d'access_token dans la réponse ({doc})"}
            _ORANGE_TOKEN_CACHE[cache_key] = {
                "access_token": access_token,
                "expires_at": now_ts + max(60, expires_in - 60),
            }
            return {"access_token": access_token, "expires_in": expires_in, "cached": False}
    except httpx.TimeoutException:
        return {"error": "OAuth Orange: timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"OAuth Orange: {exc!r}"[:300]}


async def _sms_send_orange_oauth(cfg: Dict[str, Any], msisdn_digits: str, message: str, sender: Optional[str]) -> Dict[str, Any]:
    """Send via Orange Developer SMS API using the cached OAuth bearer."""
    tok = await _orange_get_token(cfg)
    if "error" in tok:
        return {"ok": False, "status": "failed", "api_message": tok["error"]}
    access_token = tok["access_token"]

    # Sender: Orange expects the registered MSISDN in international format,
    # URL-encoded inside the path (tel:+22507..., where + → %2B).
    sender_msisdn = (sender or cfg.get("sender_msisdn") or cfg.get("sender") or "").strip()
    if not sender_msisdn:
        return {"ok": False, "status": "failed", "api_message": "Numéro émetteur (sender_msisdn) requis pour Orange OAuth"}
    sender_clean = sender_msisdn if sender_msisdn.startswith("+") else f"+{sender_msisdn}"

    # Build endpoint URL — allow the admin's configured URL to be either:
    #   - the bare base (https://api.orange.com/smsmessaging/v1) → we append
    #     /outbound/tel%3A%2B<sender>/requests
    #   - the fully-resolved one with tel placeholder
    import urllib.parse as _urlp
    base_url = (cfg.get("url") or "https://api.orange.com/smsmessaging/v1").strip().rstrip("/")
    encoded_sender = _urlp.quote(f"tel:{sender_clean}", safe="")
    if "/outbound/" not in base_url:
        endpoint = f"{base_url}/outbound/{encoded_sender}/requests"
    else:
        endpoint = base_url  # admin gave the full URL

    dest = msisdn_digits if msisdn_digits.startswith("+") else f"+{msisdn_digits}"
    body = {
        "outboundSMSMessageRequest": {
            "address": f"tel:{dest}",
            "senderAddress": f"tel:{sender_clean}",
            "outboundSMSTextMessage": {"message": message},
        }
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post(endpoint, headers=headers, json=body)
            try:
                resp = r.json()
            except Exception:
                resp = {"raw": r.text[:500]}
            if r.status_code == 401:
                # Token may have just expired between cache check and request:
                # purge cache and retry ONCE.
                cache_key = f"{(cfg.get('oauth_url') or 'https://api.orange.com/oauth/v3/token').strip()}|{(cfg.get('client_id') or '').strip()}"
                _ORANGE_TOKEN_CACHE.pop(cache_key, None)
                tok2 = await _orange_get_token(cfg)
                if "access_token" in tok2:
                    headers["Authorization"] = f"Bearer {tok2['access_token']}"
                    r = await http.post(endpoint, headers=headers, json=body)
                    try:
                        resp = r.json()
                    except Exception:
                        resp = {"raw": r.text[:500]}
            ok = 200 <= r.status_code < 300
            api_msg = None
            if isinstance(resp, dict):
                # Orange's error shape varies; surface the most useful field
                fault = (resp.get("requestError") or {}).get("serviceException") or (resp.get("requestError") or {}).get("policyException")
                if fault:
                    api_msg = f"{fault.get('messageId', '')}: {fault.get('text', '')}"
                else:
                    api_msg = resp.get("message") or None
            return {
                "ok": ok,
                "status": "sent" if ok else "failed",
                "http_status": r.status_code,
                "api_message": _safe_text(api_msg) or (None if ok else f"HTTP {r.status_code}"),
                "raw_response": resp,
            }
    except httpx.TimeoutException:
        return {"ok": False, "status": "failed", "api_message": "Orange OAuth send timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "failed", "api_message": str(exc)[:300]}


async def _sms_send_via_webhook(cfg: Dict[str, Any], msisdn: str, message: str, sender: Optional[str]) -> Dict[str, Any]:
    """Iter35k — Bridge mode: POST a simple JSON payload to a user-controlled
    webhook (typically an n8n / Make / Zapier workflow). The webhook does
    the heavy lifting (OAuth, retries, provider-specific format) and returns
    a response that we surface to the admin UI.

    Outbound payload sent to the webhook:
        {
            "provider": "orange|moov|telecel",
            "phone": "+22607332313",
            "message": "Hello",
            "sender": "+22677000155"   # may be None
        }

    Expected webhook response shape (anything else is best-effort parsed):
        {
            "status": "sent" | "failed",         # OR
            "ok": true | false,                  # OR
            "success": true | false,
            "api_message": "Optional human readable message",
            "raw": { ...provider raw response... }
        }
    Webhook may also include `Authorization: Bearer <token>` if
    `auth_type=webhook` AND `token` (in sms_*_token) is set — used to
    secure your n8n endpoint.
    """
    url = (cfg.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "status": "failed", "api_message": "URL webhook invalide (vide ou non http(s))"}
    payload = {
        "provider": cfg.get("name") or "unknown",
        "phone": msisdn if msisdn.startswith("+") else f"+{msisdn}",
        "message": message,
        "sender": (sender or cfg.get("sender") or cfg.get("sender_msisdn")),
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = (cfg.get("token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(url, headers=headers, json=payload)
            try:
                resp = r.json()
            except Exception:
                resp = {"raw": r.text[:500]}
            # Tolerant success detection
            ok_http = 200 <= r.status_code < 300
            ok_body = False
            api_msg = None
            if isinstance(resp, dict):
                status_val = (resp.get("status") or "").lower()
                ok_body = (
                    resp.get("ok") is True
                    or resp.get("success") is True
                    or status_val in ("sent", "ok", "success", "delivered")
                )
                # n8n's $json.error.* shape from your workflow
                err = resp.get("error") or {}
                if isinstance(err, dict) and (err.get("status") not in (None, 200, "200")):
                    ok_body = False
                    api_msg = f"{err.get('status')} {err.get('code', '')}: {err.get('message', '')}".strip()
                else:
                    api_msg = (
                        resp.get("api_message")
                        or resp.get("message")
                        or resp.get("maReponse")
                        or None
                    )
                # If the webhook responds 200 with NO explicit ok/status field,
                # consider it a success (your workflow does this).
                if ok_http and not ok_body and "ok" not in resp and "status" not in resp and "success" not in resp and not (isinstance(err, dict) and err):
                    ok_body = True
            ok = ok_http and ok_body
            return {
                "ok": ok,
                "status": "sent" if ok else "failed",
                "http_status": r.status_code,
                "api_message": _safe_text(api_msg) or (None if ok else f"HTTP {r.status_code}"),
                "raw_response": resp,
            }
    except httpx.TimeoutException:
        return {"ok": False, "status": "failed", "api_message": "Webhook timeout (>30s)"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "failed", "api_message": str(exc)[:300]}



async def _sms_send_generic(cfg: Dict[str, Any], msisdn: str, message: str, sender: Optional[str]) -> Dict[str, Any]:
    """Send via a generic configurable HTTP webhook (Orange/Moov/Telecel BFA)."""
    # Iter35i — branch off to the dedicated Orange Developer OAuth2 flow.
    if (cfg.get("auth_type") or "").lower() == "orange_oauth":
        return await _sms_send_orange_oauth(cfg, msisdn, message, sender)
    # Iter35k — branch off to the n8n-style webhook bridge: we just POST
    # {phone, message, sender, provider} as JSON to the configured URL
    # (the user's workflow handles all the provider-specific OAuth/SMS calls)
    # and we parse whatever the webhook returns.
    if (cfg.get("auth_type") or "").lower() == "webhook":
        return await _sms_send_via_webhook(cfg, msisdn, message, sender)
    url = (cfg.get("url") or "").strip()
    if not url:
        return {"ok": False, "status": "failed", "api_message": f"URL non configurée pour {cfg.get('name')}"}
    method = (cfg.get("method") or "POST").upper()
    final_sender = sender or cfg.get("sender") or "SAWALI"
    mapping = {"phone": msisdn, "message": message, "sender": final_sender}
    final_url = _sms_substitute(url, mapping)
    headers: Dict[str, str] = {}
    auth = (cfg.get("auth_type") or "none").lower()
    httpx_auth = None
    if auth == "bearer" and cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    elif auth == "basic" and cfg.get("basic_user"):
        httpx_auth = (cfg.get("basic_user") or "", cfg.get("basic_pass") or "")
    elif auth == "header" and cfg.get("header_name"):
        headers[cfg["header_name"]] = _sms_substitute(cfg.get("header_value") or "", mapping)
    payload_tpl = cfg.get("payload_template")
    body_obj: Any = None
    body_str: Optional[str] = None
    content_type = (cfg.get("content_type") or "json").lower()
    if method != "GET" and payload_tpl:
        rendered = _sms_substitute(payload_tpl, mapping)
        if content_type == "form":
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
            body_str = rendered
        else:
            headers.setdefault("Content-Type", "application/json")
            try:
                body_obj = json.loads(rendered)
            except Exception:  # noqa: BLE001
                body_str = rendered
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            req_kwargs: Dict[str, Any] = {"headers": headers}
            if httpx_auth:
                req_kwargs["auth"] = httpx_auth
            if body_obj is not None:
                req_kwargs["json"] = body_obj
            elif body_str is not None:
                req_kwargs["content"] = body_str
            r = await http.request(method, final_url, **req_kwargs)
            try:
                resp = r.json()
            except Exception:  # noqa: BLE001
                resp = {"raw": r.text[:500]}
            ok = 200 <= r.status_code < 300
            return {
                "ok": ok,
                "status": "sent" if ok else "failed",
                "http_status": r.status_code,
                "api_message": _safe_text(resp.get("message") if isinstance(resp, dict) else None) or (None if ok else f"HTTP {r.status_code}"),
                "raw_response": resp,
            }
    except httpx.TimeoutException:
        return {"ok": False, "status": "failed", "api_message": "Timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "failed", "api_message": str(exc)[:300]}


async def _sms_dispatch(provider: str, msisdn: str, message: str, sender: Optional[str] = None) -> Dict[str, Any]:
    s = await db.settings.find_one({"_id": "global"}) or {}
    actual_provider = provider
    if not actual_provider or actual_provider == "auto":
        actual_provider = _sms_pick_default(s, msisdn)
    if not actual_provider:
        return {"ok": False, "status": "failed", "api_message": "Aucun fournisseur SMS disponible", "provider": None}
    cfg = _sms_provider_cfg(s, actual_provider)
    if not cfg:
        return {"ok": False, "status": "failed", "api_message": f"Fournisseur '{actual_provider}' non activé", "provider": actual_provider}
    msisdn_clean = "".join(ch for ch in (msisdn or "") if ch.isdigit() or ch == "+")
    if cfg["kind"] == "ovh":
        result = await _sms_send_ovh(cfg, msisdn_clean if msisdn_clean.startswith("+") else f"+{msisdn_clean}", message, sender)
    elif cfg["kind"] == "bird":
        # Iter43-fix24g — Délègue à routes/bird_sms.send_bird_sms (réutilise
        # la config + httpx déjà en place, gère l'auth AccessKey).
        try:
            from routes.bird_sms import send_bird_sms as _send_bird_sms  # local import (évite circulaire)
            bird_to = msisdn_clean if msisdn_clean.startswith("+") else f"+{msisdn_clean}"
            bird_res = await _send_bird_sms(
                db,
                to=bird_to,
                text=message,
                sender=sender or cfg.get("sender"),
            )
            # Persist dans bird_sms_messages pour cohérence avec l'inbox unifiée
            try:
                await db.bird_sms_messages.insert_one({
                    "id": _uuid(),
                    "direction": "outbound",
                    "from": sender or cfg.get("sender") or "liluvine",
                    "to": bird_to,
                    "phone_digits": "".join(c for c in bird_to if c.isdigit()),
                    "text": message,
                    "bird_response": bird_res,
                    "provider": "bird",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:  # noqa: BLE001
                logger.warning("[sms_dispatch] bird persistence failed", exc_info=True)
            result = {
                "ok": True,
                "status": "sent",
                "api_message": "Bird Channels API accepted",
                "http_status": 200,
                "raw_response": bird_res,
            }
        except HTTPException as he:
            result = {
                "ok": False,
                "status": "failed",
                "api_message": str(he.detail)[:300],
                "http_status": he.status_code,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("[sms_dispatch] bird send failed")
            result = {
                "ok": False,
                "status": "failed",
                "api_message": str(exc)[:300],
            }
    else:
        result = await _sms_send_generic(cfg, msisdn_clean.lstrip("+"), message, sender)
    result["provider"] = actual_provider
    return result


class MeSmsSendRequest(BaseModel):
    to: str
    message: str
    provider: Optional[str] = None
    sender: Optional[str] = None
    contact_id: Optional[str] = None


@api.get("/me/sms/providers", tags=["Portail Client"])
async def me_sms_providers(user: dict = Depends(get_current_user)):
    """Tell the portal which SMS providers are configured + the default one."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    return {
        "default": (s.get("sms_default_provider") or "auto").lower(),
        "active": _sms_active_providers(s),
        "ovh_enabled": bool(s.get("sms_ovh_enabled")),
        # Iter43-fix24g — Permet aux pages de personnaliser le label "Bird.com"
        # quand le provider apparaît dans la liste `active`.
        "bird_enabled": bool(
            s.get("bird_enabled")
            and s.get("bird_workspace_id")
            and s.get("bird_channel_id")
            and s.get("bird_access_key")
        ),
    }


@api.post("/me/sms/send", tags=["Portail Client"])
async def me_sms_send(payload: MeSmsSendRequest, request: Request, user: dict = Depends(get_current_user)):
    parent_id = user.get("client_id") or user["id"]
    if user.get("role") not in ("admin", "superviseur"):
        parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1})
        feats = _normalize_features((parent or {}).get("features"))
        if not feats.get("sms") and user.get("role") != "demo":
            raise HTTPException(status_code=403, detail="SMS non autorisé pour votre compte")
    await _enforce_demo_quota(user, QUOTA_KEY_SMS)  # Iter35h
    if not (payload.message or "").strip():
        raise HTTPException(status_code=400, detail="Message vide")
    if len(payload.message) > 800:
        raise HTTPException(status_code=400, detail="Message trop long (>800 caractères)")
    # Iter34h — RGPD: resolve real phone number from contact_id if available
    real_to = await _resolve_real_phone(payload.contact_id, "phone", payload.to or "")
    if not real_to:
        raise HTTPException(status_code=400, detail="Destinataire requis")
    result = await _sms_dispatch(payload.provider or "auto", real_to, payload.message, payload.sender)
    pay_slug = _extract_pay_slug(payload.message)
    doc = {
        "id": _uuid(),
        "client_id": parent_id,
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_label": user.get("full_name") or user.get("email"),
        "contact_id": payload.contact_id,
        "provider": result.get("provider"),
        "sender": payload.sender,
        "msisdn": real_to,
        "msisdn_digits": "".join(ch for ch in real_to if ch.isdigit()),
        "message": payload.message,
        "length": len(payload.message),
        "status": result.get("status"),
        "api_message": result.get("api_message"),
        "http_status": result.get("http_status"),
        "raw_response": result.get("raw_response"),
        "payment_link_slug": pay_slug,
        "ip": _client_ip_from_request(request),
        "created_at": _now(),
    }
    await db.sms_messages.insert_one(doc.copy())
    doc.pop("_id", None)
    if result.get("ok"):
        await _log_activity(client_id=parent_id, kind="sms", action="sent", label=f"→ {real_to}", actor=user, target_id=doc["id"])
    return {"ok": result.get("ok"), "provider": result.get("provider"), "status": result.get("status"),
            "error": None if result.get("ok") else _safe_text(result.get("api_message")),
            "http_status": result.get("http_status"), "id": doc["id"]}


@api.get("/me/sms/messages", tags=["Portail Client"])
async def me_sms_messages(limit: int = 100, contact_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    # Iter34p — Resolve full visible scope so SMS stays visible after a
    # realignment/migration (same fix as me_contact_messages).
    if user.get("role") == "admin":
        query: Dict[str, Any] = {}
    else:
        visible_scope = await _resolve_visible_client_ids(user)
        query = {"client_id": {"$in": visible_scope}}
    if contact_id:
        query["contact_id"] = contact_id
    items = await db.sms_messages.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 500))
    # Iter34u — When anon_communications is ON, restrict to SMS exchanged by
    # the current user only.
    restrictions = await _resolve_content_restrictions(user)
    if restrictions.get("anon_communications"):
        items = [m for m in items if (m.get("sender_id") == user["id"] or m.get("owner_id") == user["id"])]
    return items


class AdminSmsTestRequest(BaseModel):
    provider: str
    to: str
    message: Optional[str] = None
    sender: Optional[str] = None


@api.post("/admin/sms/test", tags=["Admin"])
async def admin_sms_test(payload: AdminSmsTestRequest, request: Request, user: dict = Depends(get_current_admin)):
    """Send a test SMS using a chosen provider — surfaces the full HTTP response
    so the admin can debug the credentials / payload template quickly."""
    msg = (payload.message or "Test SMS depuis SAWALI Admin — il s'agit d'un message de validation.").strip()
    if len(msg) > 600:
        raise HTTPException(status_code=400, detail="Message trop long")
    result = await _sms_dispatch(payload.provider or "auto", payload.to, msg, payload.sender)
    doc = {
        "id": _uuid(),
        "client_id": "admin-test",
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_label": user.get("full_name") or user.get("email"),
        "provider": result.get("provider"),
        "sender": payload.sender,
        "msisdn": payload.to,
        "msisdn_digits": "".join(ch for ch in (payload.to or "") if ch.isdigit()),
        "message": msg,
        "length": len(msg),
        "status": result.get("status"),
        "api_message": result.get("api_message"),
        "http_status": result.get("http_status"),
        "raw_response": result.get("raw_response"),
        "ip": _client_ip_from_request(request),
        "kind": "admin_test",
        "created_at": _now(),
    }
    await db.sms_messages.insert_one(doc.copy())
    doc.pop("_id", None)
    return {
        "ok": result.get("ok"),
        "provider": result.get("provider"),
        "status": result.get("status"),
        "http_status": result.get("http_status"),
        "api_message": result.get("api_message"),
        "raw_response": result.get("raw_response"),
        "id": doc["id"],
    }



# ============================================================
# SMS Phase 2 — Bulk send + Scheduled sends
# ============================================================
def _personalize_sms(template: str, ctx: Dict[str, Any]) -> str:
    """Replace {{name}}/{{company}}/{{phone}}/{{whatsapp}}/{{email}} tokens
    inside an SMS body using the recipient's contact attributes."""
    out = template or ""
    for k, v in (ctx or {}).items():
        out = out.replace("{{" + k + "}}", str(v if v is not None else ""))
    return out


def _build_sms_ctx(contact: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": contact.get("name") or "",
        "company": contact.get("company") or "",
        "phone": contact.get("phone") or "",
        "whatsapp": contact.get("whatsapp") or "",
        "email": contact.get("email") or "",
        "tag": ", ".join(contact.get("tags") or []),
    }


def _extract_pay_slug(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"/pay/([a-z0-9]{4,16})", text)
    return m.group(1) if m else None


class MeSmsBulkRequest(BaseModel):
    contact_ids: List[str]
    message: str
    provider: Optional[str] = None
    sender: Optional[str] = None
    scheduled_at: Optional[str] = None  # ISO8601 — if set, schedule instead of send


@api.post("/me/sms/bulk", tags=["Portail Client"])
async def me_sms_bulk(payload: MeSmsBulkRequest, request: Request, user: dict = Depends(get_current_user)):
    parent_id = user.get("client_id") or user["id"]
    if user.get("role") not in ("admin", "superviseur"):
        parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1})
        feats = _normalize_features((parent or {}).get("features"))
        if not feats.get("sms"):
            raise HTTPException(status_code=403, detail="SMS non autorisé pour votre compte")
    if not (payload.message or "").strip():
        raise HTTPException(status_code=400, detail="Message vide")
    if len(payload.message) > 800:
        raise HTTPException(status_code=400, detail="Message trop long (>800 caractères)")
    if not payload.contact_ids:
        raise HTTPException(status_code=400, detail="Aucun destinataire sélectionné")
    if len(payload.contact_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 destinataires par envoi")
    contacts = await db.directory_contacts.find(
        {"id": {"$in": payload.contact_ids}, "client_id": parent_id}, {"_id": 0}
    ).to_list(len(payload.contact_ids))

    # Schedule for later if requested
    if payload.scheduled_at:
        try:
            sched_dt = datetime.fromisoformat(str(payload.scheduled_at).replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(status_code=400, detail="Date de planification invalide")
        if sched_dt < datetime.now(timezone.utc) + timedelta(seconds=30):
            raise HTTPException(status_code=400, detail="La date de planification doit être au moins +30 secondes")
        sched_doc = {
            "id": _uuid(),
            "kind": "sms",
            "client_id": parent_id,
            "created_by_id": user["id"],
            "created_by_label": user.get("full_name") or user.get("email"),
            "provider": payload.provider or "auto",
            "sender": payload.sender,
            "message_template": payload.message,
            "contact_ids": payload.contact_ids,
            "scheduled_at": sched_dt.astimezone(timezone.utc).isoformat(),
            "status": "pending",
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.sms_schedules.insert_one(sched_doc.copy())
        sched_doc.pop("_id", None)
        return {"ok": True, "scheduled": True, "id": sched_doc["id"], "scheduled_at": sched_doc["scheduled_at"], "recipients": len(payload.contact_ids)}

    # Live bulk send (synchronous, capped at 500 to keep request <30s)
    results = []
    skipped = []
    pay_slug = _extract_pay_slug(payload.message)
    for c in contacts:
        target = c.get("phone") or c.get("whatsapp")
        if not target:
            skipped.append({"label": c.get("name"), "reason": "Pas de numéro"})
            continue
        ctx = _build_sms_ctx(c)
        body = _personalize_sms(payload.message, ctx)
        result = await _sms_dispatch(payload.provider or "auto", target, body, payload.sender)
        doc = {
            "id": _uuid(), "client_id": parent_id, "user_id": user["id"],
            "user_email": user.get("email"), "user_label": user.get("full_name") or user.get("email"),
            "contact_id": c.get("id"),
            "provider": result.get("provider"), "sender": payload.sender,
            "msisdn": target, "msisdn_digits": "".join(ch for ch in target if ch.isdigit()),
            "message": body, "length": len(body),
            "status": result.get("status"), "api_message": result.get("api_message"),
            "http_status": result.get("http_status"), "raw_response": result.get("raw_response"),
            "bulk": True,
            "payment_link_slug": pay_slug,
            "ip": _client_ip_from_request(request),
            "created_at": _now(),
        }
        await db.sms_messages.insert_one(doc.copy())
        doc.pop("_id", None)
        results.append({"label": c.get("name"), "phone": target, "ok": result.get("ok"),
                        "status": result.get("status"), "error": None if result.get("ok") else result.get("api_message")})
    return {"ok": True, "scheduled": False, "sent_ok": sum(1 for r in results if r["ok"]),
            "sent_ko": len([r for r in results if not r["ok"]]), "skipped": skipped, "results": results}


@api.get("/me/sms/schedules", tags=["Portail Client"])
async def me_sms_schedules(user: dict = Depends(get_current_user)):
    is_admin = user.get("role") in ("admin", "superviseur")
    q: Dict[str, Any] = {} if is_admin else {"client_id": user.get("client_id") or user["id"]}
    items = await db.sms_schedules.find(q, {"_id": 0}).sort("scheduled_at", -1).to_list(200)
    return items


@api.delete("/me/sms/schedules/{sid}", tags=["Portail Client"])
async def me_sms_schedule_cancel(sid: str, user: dict = Depends(get_current_user)):
    sched = await db.sms_schedules.find_one({"id": sid}, {"_id": 0})
    if not sched:
        raise HTTPException(status_code=404, detail="Planification introuvable")
    is_admin = user.get("role") in ("admin", "superviseur")
    if not is_admin and sched.get("client_id") != (user.get("client_id") or user["id"]):
        raise HTTPException(status_code=403, detail="Accès refusé")
    if sched.get("status") == "running":
        raise HTTPException(status_code=409, detail="Envoi déjà en cours")
    if sched.get("status") in ("done", "failed"):
        await db.sms_schedules.delete_one({"id": sid})
        return {"ok": True, "status": "deleted"}
    await db.sms_schedules.update_one({"id": sid}, {"$set": {"status": "cancelled", "updated_at": _now()}})
    return {"ok": True, "status": "cancelled"}


async def _run_scheduled_sms():
    """APScheduler tick (every minute) — drain pending SMS schedules."""
    try:
        await _expire_stale_schedules(db.sms_schedules, "sms")  # lot 27 : pas de rattrapage massif
        now_iso = datetime.now(timezone.utc).isoformat()
        due = await db.sms_schedules.find(
            {"status": "pending", "scheduled_at": {"$lte": now_iso}}, {"_id": 0},
        ).to_list(50)
        for sc in due:
            claimed = await db.sms_schedules.update_one(
                {"id": sc["id"], "status": "pending"},
                {"$set": {"status": "running", "started_at": _now(), "updated_at": _now()}},
            )
            if claimed.modified_count == 0:
                continue
            cids = sc.get("contact_ids") or []
            contacts = await db.directory_contacts.find(
                {"id": {"$in": cids}, "client_id": sc["client_id"]}, {"_id": 0}
            ).to_list(len(cids))
            tpl = sc.get("message_template") or ""
            pay_slug = _extract_pay_slug(tpl)
            results = []
            skipped = []
            for c in contacts:
                target = c.get("phone") or c.get("whatsapp")
                if not target:
                    skipped.append({"label": c.get("name"), "reason": "Pas de numéro"})
                    continue
                ctx = _build_sms_ctx(c)
                body = _personalize_sms(tpl, ctx)
                try:
                    result = await _sms_dispatch(sc.get("provider") or "auto", target, body, sc.get("sender"))
                except Exception as exc:  # noqa: BLE001
                    result = {"ok": False, "status": "failed", "api_message": str(exc)[:200]}
                doc = {
                    "id": _uuid(), "client_id": sc["client_id"],
                    "user_id": sc.get("created_by_id"), "user_label": sc.get("created_by_label"),
                    "contact_id": c.get("id"),
                    "provider": result.get("provider"), "sender": sc.get("sender"),
                    "msisdn": target, "msisdn_digits": "".join(ch for ch in target if ch.isdigit()),
                    "message": body, "length": len(body),
                    "status": result.get("status"), "api_message": result.get("api_message"),
                    "http_status": result.get("http_status"), "raw_response": result.get("raw_response"),
                    "bulk": True, "scheduled": True, "schedule_id": sc["id"],
                    "payment_link_slug": pay_slug, "created_at": _now(),
                }
                try:
                    await db.sms_messages.insert_one(doc.copy())
                except Exception:  # noqa: BLE001
                    pass
                results.append({"label": c.get("name"), "phone": target, "ok": result.get("ok"),
                                "status": result.get("status"), "error": None if result.get("ok") else result.get("api_message")})
            sent_ok = sum(1 for r in results if r["ok"])
            final_status = "done" if (sent_ok > 0 or not results) else "failed"
            await db.sms_schedules.update_one(
                {"id": sc["id"]},
                {"$set": {"status": final_status, "result_summary": {
                    "requested": len(cids), "sent_ok": sent_ok, "sent_ko": len(results) - sent_ok,
                    "skipped_count": len(skipped), "skipped": skipped, "results": results,
                }, "finished_at": _now(), "updated_at": _now()}},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduled_sms runner failed: %s", exc)








# ---------- Portal WhatsApp scheduling (mirrors admin endpoints, scoped by client) ----------
class MeScheduleCreate(BaseModel):
    title: Optional[str] = None
    recipients: List[Dict[str, Any]]
    template_name: str
    language_code: Optional[str] = "fr"
    components: Optional[list] = None
    variables: Optional[List[str]] = None
    header_text: Optional[str] = None
    header_media: Optional[Dict[str, Any]] = None
    button_vars: Optional[List[List[str]]] = None
    button_specs: Optional[List[Dict[str, Any]]] = None  # Iter43-fix24aj
    scheduled_at: str  # ISO-8601 UTC


def _can_send_wa(user: dict) -> bool:
    if user.get("role") in ("admin", "client", "superviseur"):
        return True
    return _is_elevated_creator(user)


@api.get("/me/messaging/schedules", tags=["Portail Client"])
async def me_list_schedules(user: dict = Depends(get_current_user)):
    """Liste les envois WhatsApp programmés de l'utilisateur. Les admins voient tout ; les utilisateurs portail
    see schedules they created (created_by_id=user.id)."""
    if not _can_send_wa(user):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
    query = {} if user.get("role") == "admin" else {"created_by_id": user["id"]}
    items = await db.whatsapp_schedules.find(query, {"_id": 0}).sort("scheduled_at", -1).to_list(500)
    return items


@api.post("/me/messaging/schedules", tags=["Portail Client"])
async def me_create_schedule(payload: MeScheduleCreate, user: dict = Depends(get_current_user)):
    if not _can_send_wa(user):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
    if not payload.recipients:
        raise HTTPException(status_code=400, detail="Aucun destinataire")
    if not payload.template_name:
        raise HTTPException(status_code=400, detail="Template requis")
    try:
        sched = datetime.fromisoformat(payload.scheduled_at.replace("Z", "+00:00"))
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="Date invalide (ISO-8601 attendu)")
    if sched <= datetime.now(timezone.utc) - timedelta(minutes=1):
        raise HTTPException(status_code=400, detail="La date planifiée doit être dans le futur")

    doc = {
        "id": _uuid(),
        "title": (payload.title or "").strip() or f"Envoi {payload.template_name}",
        "recipients": payload.recipients,
        "template_name": payload.template_name,
        "language_code": payload.language_code or "fr",
        "components": payload.components,
        "variables": payload.variables,
        "header_text": payload.header_text,
        "header_media": payload.header_media,
        "button_vars": payload.button_vars,
        "button_specs": payload.button_specs,
        "scheduled_at": sched.isoformat(),
        "status": "pending",
        "result_summary": None,
        # Capture the user origin (used by /me/messaging/schedules to filter)
        "created_by_id": user["id"],
        "created_by_label": user.get("full_name") or user.get("email"),
        "created_by_role": user.get("role"),
        "client_id": user.get("client_id") or user.get("id"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.whatsapp_schedules.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


# ----- WhatsApp Bulk send (mirrors SMS bulk; supports per-contact personalization) -----
class MeWaBulkRequest(BaseModel):
    contact_ids: List[str]
    template_name: str
    language_code: Optional[str] = "fr"
    variables: Optional[List[str]] = None  # Body positional vars, may contain {{name}} tokens
    header_text: Optional[str] = None
    header_media: Optional[Dict[str, Any]] = None
    button_vars: Optional[List[List[str]]] = None
    # Iter43-fix24aj (2026-06-17) — Preferred over `button_vars`: explicit
    # per-button {sub_type, index, parameters} so QUICK_REPLY / URL / FLOW
    # templates send with the correct Meta structure.
    button_specs: Optional[List[Dict[str, Any]]] = None
    scheduled_at: Optional[str] = None  # ISO-8601 — if set, schedule instead of live send
    title: Optional[str] = None  # Friendly label for the schedule row
    # SMS fallback: when WhatsApp delivery fails for a contact (no number, not on WA,
    # outside 24h window, Meta error…), automatically retry as SMS using
    # `sms_fallback_message` (which supports the same {{name}}/{{company}}/etc. tokens).
    sms_fallback: bool = False
    sms_fallback_message: Optional[str] = None
    sms_fallback_provider: Optional[str] = None  # "auto" / "orange" / "moov" / "telecel" / "ovh"
    sms_fallback_sender: Optional[str] = None


@api.post("/me/whatsapp/bulk", tags=["Portail Client"])
async def me_whatsapp_bulk(payload: MeWaBulkRequest, user: dict = Depends(get_current_user)):
    """Envoie un modèle WhatsApp approuvé par Meta à plusieurs contacts CRM en une fois,
    with per-contact variable personalization (`{{name}}`, `{{company}}`,
    `{{phone}}`, `{{email}}`, `{{client_code}}` = contact's unique_code, etc).
    Optional `scheduled_at` defers execution to the cron runner.
    Caps at 500 recipients per call (same as SMS bulk)."""
    if not _can_send_wa(user):
        raise HTTPException(status_code=403, detail="Rôle non autorisé à envoyer des messages WhatsApp")
    parent_id = user.get("client_id") or user["id"]
    # Feature gate: tracked/regular users must have whatsapp enabled by their parent client
    if user.get("role") not in ("admin", "superviseur"):
        parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1})
        feats = _normalize_features((parent or {}).get("features"))
        if not feats.get("whatsapp"):
            raise HTTPException(status_code=403, detail="WhatsApp non autorisé pour votre compte")
    if not (payload.template_name or "").strip():
        raise HTTPException(status_code=400, detail="Template requis")
    if not payload.contact_ids:
        raise HTTPException(status_code=400, detail="Aucun destinataire sélectionné")
    if len(payload.contact_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 destinataires par envoi")

    # Iter35h — demo: each recipient counts as one send (pre-resolve check).
    await _enforce_demo_quota(user, QUOTA_KEY_WA, increment=len(payload.contact_ids))

    # Iter35f — widen lookup to every visible client_id (so contacts that
    # were retagged to a peer/legacy client_id remain reachable). Before
    # this fix, a strict {client_id: parent_id} filter returned 0 contacts
    # after an admin retag → bulk send silently reported "0 message envoyé".
    visible_scope = await _resolve_visible_client_ids(user)
    contacts = await db.directory_contacts.find(
        {"id": {"$in": payload.contact_ids}, "client_id": {"$in": visible_scope}},
        {"_id": 0},
    ).to_list(len(payload.contact_ids))

    # Iter35f — fail fast with a clear error when NO contact resolves
    # (was silently returning sent_ok=0 → frontend toast "0 message envoyé"
    # which looked like a delivery problem rather than a scope mismatch).
    if not contacts:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Aucun contact retrouvé parmi les {len(payload.contact_ids)} ID(s) sélectionné(s). "
                "Vos contacts ont peut-être été réassignés à un autre client — actualisez la liste."
            ),
        )

    # Schedule-for-later branch: persist recipients and let the cron pick it up.
    if payload.scheduled_at:
        try:
            sched_dt = datetime.fromisoformat(str(payload.scheduled_at).replace("Z", "+00:00"))
            if sched_dt.tzinfo is None:
                sched_dt = sched_dt.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(status_code=400, detail="Date de planification invalide (ISO-8601 attendu)")
        if sched_dt < datetime.now(timezone.utc) + timedelta(seconds=30):
            raise HTTPException(status_code=400, detail="La date de planification doit être au moins +30 secondes")
        recipients = []
        for c in contacts:
            phone = (c.get("whatsapp") or c.get("phone") or "").strip()
            recipients.append({
                "kind": "contact",
                "id": c.get("id"),
                "phone": phone,
                "label": c.get("name") or c.get("company") or phone,
            })
        sched_doc = {
            "id": _uuid(),
            "title": (payload.title or "").strip() or f"WA bulk {payload.template_name}",
            "recipients": recipients,
            "template_name": payload.template_name,
            "language_code": payload.language_code or "fr",
            "components": None,
            "variables": payload.variables,
            "header_text": payload.header_text,
            "header_media": payload.header_media,
            "button_vars": payload.button_vars,
            "scheduled_at": sched_dt.astimezone(timezone.utc).isoformat(),
            "status": "pending",
            "result_summary": None,
            "created_by_id": user["id"],
            "created_by_label": user.get("full_name") or user.get("email"),
            "created_by_role": user.get("role"),
            "client_id": parent_id,
            "bulk": True,
            # SMS fallback config (cron runner will apply per-recipient on failure)
            "sms_fallback": bool(payload.sms_fallback),
            "sms_fallback_message": payload.sms_fallback_message,
            "sms_fallback_provider": payload.sms_fallback_provider,
            "sms_fallback_sender": payload.sms_fallback_sender,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.whatsapp_schedules.insert_one(sched_doc.copy())
        sched_doc.pop("_id", None)
        return {
            "ok": True,
            "scheduled": True,
            "id": sched_doc["id"],
            "scheduled_at": sched_doc["scheduled_at"],
            "recipients": len(recipients),
        }

    # Live-send branch: iterate contacts, build per-contact ctx, send template now.
    results = []
    skipped = []
    fallback_results = []  # SMS fallback attempts (when sms_fallback=True)
    for c in contacts:
        phone = (c.get("whatsapp") or c.get("phone") or "").strip()
        label = c.get("name") or c.get("company") or phone or "—"
        if not phone:
            skipped.append({"label": label, "reason": "Pas de numéro WhatsApp"})
            continue
        # Re-use _build_recipient_ctx with a contact-shaped doc so {{name}},
        # {{company}}, {{client_code}} (= unique_code) etc. resolve naturally.
        user_doc = {
            "full_name": c.get("name"),
            "company": c.get("company"),
            "email": c.get("email"),
            "phone": c.get("phone") or c.get("whatsapp"),
            "client_code": c.get("unique_code"),
        }
        ctx = _build_recipient_ctx("contact", user_doc, phone, label)
        components = _build_components(
            payload.variables, ctx,
            header_text=payload.header_text,
            header_media=payload.header_media,
            button_vars=payload.button_vars,
            button_specs=payload.button_specs,
        )
        try:
            wr = await _wa_send_template(
                phone, payload.template_name, payload.language_code or "fr", components,
            )
        except Exception as exc:  # noqa: BLE001
            wr = {"ok": False, "status": 0, "message_id": None, "error": str(exc)[:200]}
        # Capture any /pay/{slug} URL embedded for analytics attribution
        pay_slug = None
        try:
            pay_slug = _extract_pay_slug(json.dumps((payload.variables or []) + [(payload.header_text or "")], ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass
        log = {
            "id": _uuid(),
            "client_id": parent_id,
            "direction": "outbound",
            "sender_id": user["id"],
            "sender_label": user.get("full_name") or user.get("email"),
            "to": phone,
            "phone_digits": "".join(ch for ch in phone if ch.isdigit()),
            "template_name": payload.template_name,
            "language_code": payload.language_code or "fr",
            "contact_id": c.get("id"),
            "recipient_kind": "contact",
            "recipient_label": label,
            "bulk": True,
            "ok": wr["ok"],
            "status": wr["status"],
            "message_id": wr["message_id"],
            "error": wr.get("error"),
            "wa_status": "sent" if wr["ok"] else "failed",
            "sent_at": _now() if wr["ok"] else None,
            "failed_at": None if wr["ok"] else _now(),
            "payment_link_slug": pay_slug,
            "created_at": _now(),
        }
        try:
            await db.whatsapp_messages.insert_one(log.copy())
        except Exception:  # noqa: BLE001
            pass
        results.append({
            "label": label, "phone": phone, "ok": wr["ok"],
            "status": wr["status"], "message_id": wr["message_id"],
            "error": None if wr["ok"] else (wr.get("error") or "Échec"),
        })
        # ---- SMS fallback on failure ----
        if not wr["ok"] and payload.sms_fallback and (payload.sms_fallback_message or "").strip():
            sms_target = (c.get("phone") or c.get("whatsapp") or "").strip()
            if sms_target:
                try:
                    sms_ctx = _build_sms_ctx(c)
                    sms_body = _personalize_sms(payload.sms_fallback_message, sms_ctx)
                    sms_res = await _sms_dispatch(
                        payload.sms_fallback_provider or "auto",
                        sms_target, sms_body, payload.sms_fallback_sender,
                    )
                    sms_doc = {
                        "id": _uuid(), "client_id": parent_id, "user_id": user["id"],
                        "user_email": user.get("email"),
                        "user_label": user.get("full_name") or user.get("email"),
                        "contact_id": c.get("id"),
                        "provider": sms_res.get("provider"),
                        "sender": payload.sms_fallback_sender,
                        "msisdn": sms_target,
                        "msisdn_digits": "".join(ch for ch in sms_target if ch.isdigit()),
                        "message": sms_body, "length": len(sms_body),
                        "status": sms_res.get("status"),
                        "api_message": sms_res.get("api_message"),
                        "http_status": sms_res.get("http_status"),
                        "raw_response": sms_res.get("raw_response"),
                        "bulk": True,
                        "wa_fallback": True,  # marks this row as the SMS fallback of a WA failure
                        "payment_link_slug": _extract_pay_slug(payload.sms_fallback_message),
                        "created_at": _now(),
                    }
                    await db.sms_messages.insert_one(sms_doc.copy())
                    fallback_results.append({
                        "label": label, "phone": sms_target,
                        "ok": bool(sms_res.get("ok")),
                        "status": sms_res.get("status"),
                        "error": None if sms_res.get("ok") else (sms_res.get("api_message") or "Échec SMS"),
                    })
                except Exception as exc:  # noqa: BLE001
                    fallback_results.append({"label": label, "phone": sms_target, "ok": False, "status": "failed", "error": str(exc)[:200]})
            else:
                fallback_results.append({"label": label, "phone": "", "ok": False, "status": "no_phone", "error": "Pas de numéro de téléphone pour le repli SMS"})
    return {
        "ok": True,
        "scheduled": False,
        "sent_ok": sum(1 for r in results if r["ok"]),
        "sent_ko": sum(1 for r in results if not r["ok"]),
        "skipped": skipped,
        "results": results,
        "fallback_used": bool(payload.sms_fallback),
        "fallback_results": fallback_results,
        "fallback_ok": sum(1 for r in fallback_results if r["ok"]),
    }


@api.delete("/me/messaging/schedules/{sid}", tags=["Portail Client"])
async def me_delete_schedule(sid: str, user: dict = Depends(get_current_user)):
    if not _can_send_wa(user):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
    existing = await db.whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Planification introuvable")
    # Portal users can only cancel their own schedules
    if user.get("role") != "admin" and existing.get("created_by_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Suppression non autorisée")
    if existing.get("status") in ("running", "done"):
        await db.whatsapp_schedules.update_one(
            {"id": sid},
            {"$set": {"status": "cancelled", "updated_at": _now()}},
        )
        return {"ok": True, "status": "cancelled"}
    await db.whatsapp_schedules.delete_one({"id": sid})
    return {"ok": True, "status": "deleted"}


@api.get("/me/whatsapp/templates", tags=["Portail Client"])
async def me_list_wa_templates(user: dict = Depends(get_current_user)):
    """Utilisateurs portail : liste les modèles APPROUVÉS + uniquement ceux marqués disponibles.
    Attaches the admin-maintained description note."""
    if user.get("role") not in ("client", "admin") and not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
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
            approved = []
            for t in (d.get("data") or []):
                if (t.get("status") or "").upper() != "APPROVED":
                    continue
                note = notes_map.get(t["name"]) or {}
                # Hide if explicitly marked unavailable to users (default = available)
                if note.get("is_available_for_users") is False:
                    continue
                t["note_description"] = note.get("description") or ""
                approved.append(t)
            return {"configured": True, "items": approved}
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "items": [], "error": str(exc)[:200]}


@api.get("/me/contacts/{cid}/messages", tags=["Portail Client"])
async def me_contact_messages(cid: str, user: dict = Depends(get_current_user)):
    """Renvoie la conversation WhatsApp complète pour un contact de l'annuaire.
    Includes outbound messages (sent via /me/whatsapp/send), inbound messages
    captured by the Meta webhook, and the status-update timeline
    (sent/delivered/read/failed) with timestamps.

    Iter34p — Uses _resolve_visible_client_ids so the contact stays
    accessible after a realignment/migration even if its client_id matches
    a peer/legacy value rather than the viewer's own client_id."""
    visible_scope = await _resolve_visible_client_ids(user)
    contact = await db.directory_contacts.find_one(
        {"id": cid, "client_id": {"$in": visible_scope}}, {"_id": 0},
    )
    if not contact:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    # Match by contact_id OR by phone number (covers inbound messages from unknown senders).
    # Lot 23 — numéro reconnu sur ses 8 derniers chiffres (comme le comptage des non-lus).
    or_clauses = _contact_phone_clauses(contact)
    # Lot 23 — les 1000 messages les PLUS RÉCENTS, remis dans l'ordre chronologique
    # (avant : les 1000 plus anciens, donc les nouveaux disparaissaient d'une longue conversation).
    items = await db.whatsapp_messages.find(
        {"client_id": {"$in": visible_scope}, "$or": or_clauses},
        {"_id": 0},
    ).sort("created_at", -1).limit(1000).to_list(1000)
    items.reverse()
    # Iter34u — When anon_communications is ON, restrict to messages
    # exchanged by the current user only (sender_id or owner_id match).
    restrictions = await _resolve_content_restrictions(user)
    if restrictions.get("anon_communications"):
        items = [m for m in items if (m.get("sender_id") == user["id"] or m.get("owner_id") == user["id"])]
    # Compute the 24h Meta customer service window from the latest inbound
    last_inbound_at: Optional[str] = None
    for m in reversed(items):
        if m.get("direction") == "inbound":
            last_inbound_at = m.get("received_at") or m.get("created_at")
            break
    can_send_text = _wa_window_open(last_inbound_at)
    window_expires_at: Optional[str] = None
    if last_inbound_at:
        try:
            ts = datetime.fromisoformat(last_inbound_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            window_expires_at = (ts + timedelta(seconds=WA_24H_WINDOW_SECONDS)).isoformat()
        except Exception:
            window_expires_at = None
    return {
        "contact": contact,
        "messages": items,
        "can_send_text": can_send_text,
        "last_inbound_at": last_inbound_at,
        "window_expires_at": window_expires_at,
    }


# ---------- Meta Cloud API webhook ----------
@api.get("/whatsapp/webhook", tags=["Webhook"])
async def whatsapp_webhook_verify(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    """Meta verifies the webhook via GET with hub.mode=subscribe, hub.verify_token, hub.challenge.
    We must echo hub.challenge as plain text when the verify token matches."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    expected = s.get("wa_verify_token") or ""
    if not expected:
        raise HTTPException(status_code=400, detail="Verify token non configuré")
    if hub_mode == "subscribe" and hub_verify_token == expected and hub_challenge:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Invalid verify token")


import re as _re_masked_reply


async def _generate_reply_code() -> str:
    """2026-02 fork (P3b) — Short unique code for the admin WA reply router.
    Format: 4 uppercase alphanumerics (~1.6M combos, > enough for concurrent
    unresolved messages). Includes a collision check against active tokens
    younger than 30 min.
    """
    import secrets
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # skip 0/O/1/I for readability
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(4))
        exists = await db.wa_reply_tokens.find_one({"code": code, "used": False}, {"_id": 1})
        if not exists:
            return code


async def _try_handle_masked_reply(*, from_num: str, digits_only: str, text_body: str) -> Optional[dict]:
    """Return truthy handled-info dict if `text_body` is a `#R<code> <reply>`
    pattern coming from an authorised admin phone. Otherwise return None so
    the caller keeps processing the message as regular inbound.

    Authorisation policy:
      - The sender's E.164 (or digits) matches a user with role in
        ("admin", "superviseur") — case-insensitive phone match.
    """
    m = _re_masked_reply.match(r"^\s*#R([A-Za-z0-9]{3,8})\s+(.+)$", text_body.strip(), _re_masked_reply.DOTALL)
    if not m:
        return None
    code = m.group(1).upper()
    reply_text = m.group(2).strip()
    # Verify sender is admin/superviseur (phone match, case-insensitive digits)
    if not digits_only:
        return None
    admin_user = await db.users.find_one(
        {"role": {"$in": ["admin", "superviseur"]}, "phone": {"$regex": digits_only}},
        {"_id": 0, "id": 1, "role": 1, "email": 1, "phone": 1},
    )
    if not admin_user:
        return None
    token = await db.wa_reply_tokens.find_one({"code": code, "used": False}, {"_id": 0})
    if not token:
        # Politely tell the admin the code is unknown/expired
        try:
            await _wa_send_text(from_num, f"⚠️ Code #R{code} inconnu ou expiré — impossible de router votre réponse.")
        except Exception:  # noqa: BLE001
            pass
        return {"code": code, "routed_to": None, "ok": False, "error": "unknown_code"}
    original_sender = token.get("original_sender")
    if not original_sender:
        return {"code": code, "routed_to": None, "ok": False, "error": "no_sender"}
    # Fire the outbound message on behalf of Liluvine
    try:
        res = await _wa_send_text(original_sender, reply_text)
    except Exception as exc:  # noqa: BLE001
        return {"code": code, "routed_to": original_sender, "ok": False, "error": str(exc)[:200]}
    ok = bool(res.get("ok"))
    # La réponse #R part bien vers l'expéditeur d'origine via _wa_send_text,
    # mais celui-ci ne fait qu'appeler l'API Graph — rien n'était jusqu'ici
    # enregistré dans `whatsapp_messages`, donc la réponse relayée
    # n'apparaissait jamais dans la fenêtre de conversation du contact
    # (GET /me/contacts/{cid}/messages matche par client_id + phone_digits).
    # On journalise ici avec le même format que /me/whatsapp/send-text, plus
    # un marqueur `via_masked_reply` pour que le frontend affiche un badge
    # "relayé" distinct d'un envoi normal depuis le portail.
    try:
        dest_digits = "".join(ch for ch in (original_sender or "") if ch.isdigit())
        relay_log = {
            "id": _uuid(),
            "client_id": token.get("tenant_id"),
            "direction": "outbound",
            "sender_id": admin_user.get("id"),
            "sender_label": admin_user.get("full_name") or admin_user.get("email"),
            "to": original_sender,
            "phone_digits": dest_digits,
            "template_name": None,
            "language_code": None,
            "message_type": "text",
            "body": reply_text,
            "contact_id": None,
            "tracked_user_id": None,
            "ok": ok,
            "status": res.get("status"),
            "message_id": res.get("message_id"),
            "error": None if ok else res.get("error"),
            "wa_status": "sent" if ok else "failed",
            "sent_at": _now() if ok else None,
            "failed_at": None if ok else _now(),
            "created_at": _now(),
            "reply_to_message_id": token.get("original_message_id"),
            "via_masked_reply": True,
            "masked_reply_code": code,
        }
        await db.whatsapp_messages.insert_one(relay_log)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[masked reply] whatsapp_messages log failed: %s", exc)
    # Mark token used regardless (avoid replay). Save last error if any.
    await db.wa_reply_tokens.update_one(
        {"code": code},
        {"$set": {
            "used": True,
            "used_at": _now(),
            "used_by_admin_id": admin_user.get("id"),
            "routed_to": original_sender,
            "reply_text": reply_text[:2000],
            "wa_send_ok": ok,
            "wa_send_error": None if ok else (res.get("error") or "unknown")[:200],
        }},
    )
    # Send a discreet ACK back to the admin
    try:
        if ok:
            await _wa_send_text(from_num, f"✅ #R{code} → réponse relayée à {original_sender}")
        else:
            await _wa_send_text(from_num, f"❌ #R{code} — envoi échoué : {(res.get('error') or 'inconnu')[:120]}")
    except Exception:  # noqa: BLE001
        pass
    return {"code": code, "routed_to": original_sender, "ok": ok, "error": None if ok else res.get("error")}


@api.post("/whatsapp/webhook", tags=["Webhook"])
async def whatsapp_webhook_incoming(request: Request):
    """Receive Meta Cloud API events: new inbound messages + outbound status updates.
    Shape: {object:'whatsapp_business_account', entry:[{changes:[{value:{...}}]}]}

    Hardened (iter35a): every webhook hit is persisted to
    `db.wa_webhook_logs` (capped to ~200 entries) with the raw payload + an
    extraction summary so production issues can be diagnosed without server
    access. Lookup via GET /api/admin/whatsapp/webhook-logs.
    """
    raw_bytes = b""
    try:
        raw_bytes = await request.body()
    except Exception:  # noqa: BLE001
        pass

    body: Dict[str, Any] = {}
    parse_error = None
    try:
        body = json.loads(raw_bytes.decode("utf-8")) if raw_bytes else {}
    except Exception as exc:  # noqa: BLE001
        parse_error = str(exc)[:200]

    # ------------------------------------------------------------------
    # Persist a debug log entry (best-effort, never blocks Meta).
    # We keep only the last ~200 entries via a periodic prune.
    # ------------------------------------------------------------------
    extracted_messages = 0
    extracted_statuses = 0
    inserted_messages = 0
    errors: List[str] = []

    client_scope = None  # our app uses per-install WABA, so scope = primary client/superviseur
    try:
        # Iter Bugfix (2026-02 — rabo.f case) — fallback chain: first
        # `superviseur` → first `admin` excluding the platform super-admin →
        # finally the super-admin himself. Without this, installs that only
        # have an `admin` role (typical for a fresh Sawali tenant) couldn't
        # match inbound WhatsApp messages to any tenant scope, breaking the
        # Liluvine WA auto-reply (it would skip with `liluvine_pro_not_enabled`
        # or, worse, fire without a tenant context).
        primary = await db.users.find_one({"role": "superviseur"}, {"_id": 0, "id": 1})
        if not primary:
            primary = await db.users.find_one(
                {"role": "admin", "email": {"$ne": "admin@sawalismartsystems.com"}},
                {"_id": 0, "id": 1},
            )
        if not primary:
            primary = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"}, {"_id": 0, "id": 1},
            )
        client_scope = (primary or {}).get("id")
    except Exception:
        pass

    for entry in body.get("entry") or []:
        for change in entry.get("changes") or []:
            val = change.get("value") or {}
            # Build a wa_id → profile.name map from the contacts array (Meta
            # always includes it alongside inbound messages). Used to:
            #  1. fill `from_profile_name` on inbound messages
            #  2. suggest a name when an unknown contact writes for the first time
            profile_by_wa: Dict[str, Optional[str]] = {}
            for c in val.get("contacts") or []:
                wa_id = c.get("wa_id") or ""
                pname = ((c.get("profile") or {}).get("name") or "").strip() or None
                if wa_id:
                    profile_by_wa[wa_id] = pname
            # --- Inbound messages ---
            for msg in val.get("messages") or []:
                extracted_messages += 1
                try:
                    # Iter43-fix24az-l (2026-02-26) — WhatsApp message deduplication.
                    # Meta occasionally retries the same webhook payload (network glitches
                    # or missing 200 ACK). Without a guard, this creates duplicate
                    # rows in `db.whatsapp_messages` and re-triggers Liluvine's AI
                    # auto-reply → the user sees the same message twice + Liluvine
                    # replies twice. We short-circuit here : if we've already
                    # persisted this `wa_message_id`, skip the entire pipeline.
                    wa_msg_id = msg.get("id")
                    if wa_msg_id:
                        existing_dup = await db.whatsapp_messages.find_one(
                            {"wa_message_id": wa_msg_id, "direction": "inbound"},
                            {"_id": 1},
                        )
                        if existing_dup:
                            errors.append(f"dedup_skip:{wa_msg_id}")
                            continue
                    from_num = msg.get("from") or ""
                    digits_only = "".join(ch for ch in from_num if ch.isdigit())
                    profile_name = profile_by_wa.get(from_num) or profile_by_wa.get(digits_only)
                    mtype = msg.get("type") or "text"
                    text_body = None
                    flow_reply = None  # Lot 27 : réponse d'un formulaire WhatsApp (Flow)
                    media_info: Optional[Dict[str, Any]] = None  # populated when we download a binary
                    media_caption: Optional[str] = None
                    if mtype == "text":
                        text_body = (msg.get("text") or {}).get("body")
                        # S034 — Intercept WhatsApp Admin Cockpit commands
                        # (SOLDE / STATS / INCIDENTS / AIDE). If the message
                        # matches an authorized command, reply immediately
                        # and skip persisting + auto-reply.
                        try:
                            from routes.wa_admin_cockpit import handle_wa_admin_command
                            from routes.llm_health import build_budget_summary_text
                            async def _balance():
                                return await build_budget_summary_text(db)
                            if await handle_wa_admin_command(
                                db,
                                text=text_body or "",
                                from_digits=digits_only,
                                send_wa=_wa_send_text,
                                build_balance_text=_balance,
                            ):
                                continue
                        except Exception:  # noqa: BLE001
                            logger.warning("[wa_admin_cockpit] hook failed", exc_info=True)
                        # Iter43-fix24av (2026-02-26) — LinkedIn auto-post WA approval.
                        # Intercepts OK / STOP / REGEN sent by the configured
                        # validation phone when a pending LinkedIn draft exists.
                        try:
                            reply_text = await _handle_linkedin_autopost_wa_reply(
                                db, phone=from_num, text=text_body or "",
                            )
                            if reply_text:
                                await _wa_send_text(from_num, reply_text)
                                continue
                        except Exception:  # noqa: BLE001
                            logger.warning("[linkedin.autopost] WA reply hook failed", exc_info=True)
                    elif mtype in ("image", "document", "audio", "video", "sticker"):
                        # Iter35l — Try to download the binary from Meta Graph
                        # (URL expires ~5min) and persist it locally so the chat
                        # UI can render the actual media (image/audio/PDF/etc.).
                        media_obj = msg.get(mtype) or {}
                        media_caption = (media_obj.get("caption") or "").strip() or None
                        media_id_in = media_obj.get("id")
                        if media_id_in:
                            try:
                                dl = await _wa_download_inbound_media(media_id_in)
                            except Exception as exc:  # noqa: BLE001
                                dl = {"ok": False, "error": f"download crash: {exc!r}"}
                            if dl.get("ok"):
                                media_info = dl
                                text_body = media_caption or f"[{mtype} reçu]"
                            else:
                                text_body = f"[{mtype} reçu — téléchargement échoué: {dl.get('error') or 'inconnu'}]"
                        else:
                            text_body = f"[{mtype} reçu]"
                    elif mtype == "button":
                        # Quick-reply button on a template — `button.text` is
                        # the visible label, `button.payload` the data.
                        btn = msg.get("button") or {}
                        text_body = btn.get("text") or btn.get("payload")
                        # S025 — Intercept download-approval button payloads
                        try:
                            if await _dl_handle_button_payload(db=db, payload=btn.get("payload") or "", from_phone=digits_only):
                                continue  # don't store this as a regular message
                        except Exception:  # noqa: BLE001
                            pass
                        # Lot Liluvine (2026-09, point 5) — "Souscrire temporairement"
                        try:
                            if await _liluvine_handle_temp_subscribe_button_payload(db=db, payload=btn.get("payload") or "", from_phone=digits_only):
                                continue
                        except Exception:  # noqa: BLE001
                            pass
                    elif mtype == "interactive":
                        interactive = msg.get("interactive") or {}
                        # Lot 27 : formulaire WhatsApp (Flow) complété par le client.
                        # Avant, cette réponse était perdue (seuls les boutons et listes étaient lus).
                        flow_reply = _wa_parse_flow_reply(interactive)
                        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
                        text_body = (flow_reply or {}).get("summary") or reply.get("title") or reply.get("id")
                        # VIDAL riche — clic sur le bouton "Équivalences" affiché
                        # après une réponse `!doc`/`!rech` (voir vidal_riche.py).
                        btn_id = reply.get("id") or ""
                        if btn_id.startswith("vidal_equiv:"):
                            try:
                                parts = btn_id.split(":", 2)
                                vmp_id = parts[1] if len(parts) > 1 else ""
                                exclude_id = parts[2] if len(parts) > 2 else ""
                                from routes.vidal_riche import build_equivalents_reply
                                from routes.vidal import _load_config, _vidal_call, _ensure_active
                                cfg_eq = await _load_config(db)
                                _ensure_active(cfg_eq)
                                eq_text = await build_equivalents_reply(_vidal_call, cfg_eq, vmp_id, exclude_id or None)
                                await _wa_send_text(from_num, eq_text)
                            except Exception:  # noqa: BLE001
                                logger.warning("[wa_inbound][vidal_riche] equivalents button handling failed", exc_info=True)
                            continue
                        # S025 — Intercept button_reply id (carries the payload)
                        try:
                            if await _dl_handle_button_payload(db=db, payload=reply.get("id") or "", from_phone=digits_only):
                                continue
                        except Exception:  # noqa: BLE001
                            pass
                        # Lot Liluvine (2026-09, point 5) — "Souscrire temporairement"
                        try:
                            if await _liluvine_handle_temp_subscribe_button_payload(db=db, payload=reply.get("id") or "", from_phone=digits_only):
                                continue
                        except Exception:  # noqa: BLE001
                            pass
                    elif mtype == "reaction":
                        text_body = f"[réaction {((msg.get('reaction') or {}).get('emoji') or '')}]"
                    elif mtype == "location":
                        loc = msg.get("location") or {}
                        text_body = f"[position {loc.get('latitude')},{loc.get('longitude')}]"
                    elif mtype == "contacts":
                        text_body = "[carte de contact reçue]"
                    else:
                        text_body = f"[{mtype} non géré]"
                    ts_raw = int(msg.get("timestamp") or 0)
                    ts_iso = datetime.fromtimestamp(ts_raw, tz=timezone.utc).isoformat() if ts_raw else _now()
                    # 2026-02 fork (P3b) — Masked reply router.
                    # If the inbound message comes from an admin phone AND
                    # starts with `#R<code> <reply text>`, relay it to the
                    # original sender via _wa_send_text (no admin number
                    # exposure). The token is consumed once.
                    if mtype == "text" and isinstance(text_body, str) and text_body.strip().startswith("#R"):
                        handled = await _try_handle_masked_reply(
                            from_num=from_num,
                            digits_only=digits_only,
                            text_body=text_body,
                        )
                        if handled:
                            # Store an audit row so admins can trace routings
                            try:
                                await db.wa_reply_router_audit.insert_one({
                                    "id": _uuid(),
                                    "admin_from": from_num,
                                    "code": handled.get("code"),
                                    "routed_to": handled.get("routed_to"),
                                    "ok": handled.get("ok"),
                                    "error": handled.get("error"),
                                    "created_at": _now(),
                                })
                            except Exception:  # noqa: BLE001
                                pass
                            # Skip further processing — this message is not a
                            # real inbound from a contact but an admin router action.
                            continue
                    # Find contact by phone within the scope
                    # Bug #3 (2026-02 — rabo.f) — When multiple contacts match
                    # the phone across tenants, PREFER the one in our resolved
                    # `client_scope`. Otherwise, the first cross-tenant row wins
                    # arbitrarily and messages get routed to a tenant the
                    # legitimate viewer can't see (→ "name disappeared" bug).
                    contact = None
                    if digits_only:
                        phone_match = {"$or": [
                            {"whatsapp": {"$regex": digits_only}},
                            {"phone": {"$regex": digits_only}},
                        ]}
                        if client_scope:
                            contact = await db.directory_contacts.find_one(
                                {"$and": [phone_match, {"client_id": client_scope}]},
                                {"_id": 0, "id": 1, "client_id": 1, "name": 1, "wa_profile_name": 1, "vidal_riche": 1},
                            )
                        if not contact:
                            contact = await db.directory_contacts.find_one(
                                phone_match,
                                {"_id": 0, "id": 1, "client_id": 1, "name": 1, "wa_profile_name": 1, "vidal_riche": 1},
                            )
                        # Lot 24 — contact enregistré sans indicatif ou avec des espaces
                        # (« 70 11 11 11 ») : reconnu sur les 8 derniers chiffres, sinon le
                        # numéro partait en « contact inconnu » et son enregistrement créait un doublon.
                        if not contact:
                            found = (await _find_contact_by_phone([client_scope], digits_only) if client_scope else None) \
                                or await _find_contact_by_phone(None, digits_only)
                            if found:
                                contact = {k: found.get(k) for k in ("id", "client_id", "name", "wa_profile_name", "vidal_riche")}
                    # Bug #3 — If the inbound sender is a REGISTERED system user
                    # (e.g. a moderator writing to the WA bot), auto-create their
                    # contact in their canonical tenant scope so they appear in
                    # /portal/contacts. Without this, system users land in
                    # `wa_pending_imports` and stay nameless until manually imported.
                    if not contact and digits_only:
                        try:
                            sys_user = await db.users.find_one(
                                {"phone": {"$regex": digits_only}},
                                {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1,
                                 "phone": 1, "client_id": 1, "parent_client_id": 1, "company": 1},
                            )
                        except Exception:
                            sys_user = None
                        if sys_user:
                            # Resolve canonical tenant scope for this user
                            if (sys_user.get("role") or "") in ("admin", "superviseur"):
                                sys_scope = sys_user["id"]
                            else:
                                sys_scope = (
                                    sys_user.get("parent_client_id")
                                    or sys_user.get("client_id")
                                    or client_scope
                                    or sys_user["id"]
                                )
                            sys_full_name = (
                                (sys_user.get("full_name") or "").strip()
                                or sys_user.get("email") or "—"
                            )
                            new_contact = {
                                "id": _uuid(),
                                "client_id": sys_scope,
                                "owner_id": sys_user.get("id"),
                                "owner_label": sys_full_name,
                                "name": sys_full_name,
                                "phone": sys_user.get("phone") or f"+{digits_only}",
                                "whatsapp": sys_user.get("phone") or f"+{digits_only}",
                                "email": sys_user.get("email"),
                                "company": sys_user.get("company"),
                                "tags": ["utilisateur-système"],
                                "shared": True,
                                "wa_profile_name": profile_name or sys_full_name,
                                "wa_user_link": sys_user.get("id"),
                                "created_at": _now(),
                                "updated_at": _now(),
                            }
                            try:
                                await db.directory_contacts.insert_one(new_contact.copy())
                                contact = {
                                    "id": new_contact["id"],
                                    "client_id": sys_scope,
                                    "name": sys_full_name,
                                    "wa_profile_name": new_contact["wa_profile_name"],
                                }
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("auto-create contact for system user failed: %s", exc)
                    scope_for_msg = (contact or {}).get("client_id") or client_scope
                    doc = {
                        "id": _uuid(),
                        "client_id": scope_for_msg,
                        "direction": "inbound",
                        "contact_id": (contact or {}).get("id"),
                        "contact_name": (contact or {}).get("name"),
                        "from": from_num,
                        "from_profile_name": profile_name,
                        "phone_digits": digits_only,
                        "body": text_body,
                        "message_type": mtype,
                        "wa_message_id": msg.get("id"),
                        "received_at": ts_iso,
                        "created_at": _now(),
                        "read_by_us_at": None,
                    }
                    if media_info:
                        doc["media_id"] = media_info.get("file_id")
                        doc["media_wa_id"] = (msg.get(mtype) or {}).get("id")
                        doc["media_url"] = media_info.get("public_url")
                        doc["media_mime_type"] = media_info.get("mime_type")
                        doc["media_filename"] = media_info.get("filename")
                        doc["media_size_bytes"] = media_info.get("size_bytes")
                        doc["media_kind"] = media_info.get("kind")
                        if media_caption:
                            doc["media_caption"] = media_caption
                    # Iter37h — Capture quote context (when user replies to one of our messages)
                    ctx = (msg.get("context") or {})
                    quoted_mid = ctx.get("id") or ctx.get("message_id")
                    if quoted_mid:
                        doc["reply_to_message_id"] = quoted_mid
                    if media_info and media_info.get("kind") == "audio":
                        # Iter35l — auto-transcribe voice notes when toggle ON
                        try:
                            s_root = await db.settings.find_one({"_id": "global"}) or {}
                            if bool(s_root.get("wa_voice_transcribe_enabled", True)):
                                stored = UPLOAD_DIR / media_info["stored_name"]
                                transcript = await _wa_transcribe_audio_file(stored, language="fr")
                                if transcript:
                                    doc["voice_note_transcript"] = transcript
                                    # Prepend a hint so the bubble's primary text shows the transcript
                                    doc["body"] = transcript if not media_caption else f"{media_caption}\n— {transcript}"
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("WA voice transcribe failed: %s", exc)
                    await db.whatsapp_messages.insert_one(doc)
                    inserted_messages += 1
                    # 2026-02 fork (P3b) — Emit `whatsapp.received` automation
                    # event. Create a short-lived reply-router token so an admin
                    # can respond via WhatsApp using `#R<code> <reply>` and
                    # Liluvine relays without exposing their number.
                    try:
                        reply_code = await _generate_reply_code()
                        await db.wa_reply_tokens.insert_one({
                            "id": _uuid(),
                            "code": reply_code,
                            "original_sender": from_num,
                            "original_sender_name": profile_name or (contact or {}).get("name") or "",
                            "original_message_id": msg.get("id"),
                            "original_body": (text_body or "")[:2000],
                            "tenant_id": scope_for_msg,
                            "created_at": _now(),
                            "used": False,
                        })
                        wa_extra_ctx = {
                            "wa_from": from_num,
                            "wa_sender_name": profile_name or (contact or {}).get("name") or from_num,
                            "wa_message": (text_body or "")[:500],
                            "wa_reply_code": reply_code,
                        }
                        # Fire the automation (fire-and-forget, non-blocking)
                        import asyncio
                        asyncio.create_task(_emit_event("whatsapp.received", {
                            "client_id": scope_for_msg,
                            "extra_ctx": wa_extra_ctx,
                        }))
                    except Exception as _exc:  # noqa: BLE001
                        logger.warning("[whatsapp.received automation] emit failed: %s", _exc)
                    # Lot 27 : réponse d'un formulaire WhatsApp (Flow) -> enregistrée et
                    # événement d'automation « whatsapp.flow_completed ».
                    if flow_reply:
                        try:
                            sent = None
                            if flow_reply.get("flow_token"):
                                sent = await db.whatsapp_flow_sends.find_one(
                                    {"flow_token": flow_reply["flow_token"]}, {"_id": 0})
                            await db.whatsapp_flow_responses.insert_one({
                                "id": _uuid(),
                                "flow_token": flow_reply.get("flow_token") or None,
                                "template": (sent or {}).get("template"),
                                "from": from_num,
                                "sender_name": profile_name or (contact or {}).get("name") or "",
                                "contact_id": (contact or {}).get("id"),
                                "tenant_id": scope_for_msg,
                                "fields": flow_reply.get("fields") or {},
                                "summary": flow_reply.get("summary") or "",
                                "message_id": msg.get("id"),
                                "created_at": _now(),
                            })
                            import asyncio
                            asyncio.create_task(_emit_event("whatsapp.flow_completed", {
                                "client_id": scope_for_msg,
                                "extra_ctx": {
                                    "wa_from": from_num,
                                    "wa_sender_name": profile_name or (contact or {}).get("name") or from_num,
                                    "wa_flow_template": (sent or {}).get("template") or "",
                                    # Une seule ligne (les modèles Meta refusent les retours à la ligne)
                                    "wa_flow_summary": " · ".join(
                                        (flow_reply.get("summary") or "").split("\n")[1:])[:900],
                                },
                            }))
                        except Exception as _exc:  # noqa: BLE001
                            logger.warning("[whatsapp.flow_completed] enregistrement échoué : %s", _exc)
                    # Iter34x — activity log for inbound WA
                    await _log_activity(
                        client_id=scope_for_msg,
                        kind="whatsapp",
                        action="received",
                        label=f"← {profile_name or (contact or {}).get('name') or from_num}",
                        actor={"id": "_system_", "full_name": "WhatsApp webhook"},
                        target_id=doc.get("id"),
                    )
                    # Iter35x — Alexa voice notification (best-effort, fire-and-forget)
                    _alexa_notify_async(
                        "wa_inbound",
                        f"Nouveau WhatsApp reçu de {profile_name or from_num}",
                    )
                    # Persist the latest profile name on the contact (or create a
                    # "wa_unmapped" record so the admin can review and import it).
                    if profile_name:
                        if contact:
                            # Auto-fill the contact's main `name` field if it is
                            # empty OR still equal to the bare phone number (a
                            # common state for contacts created from inbound WA
                            # before any human review). We only overwrite blank-
                            # ish names — never a real, user-entered name.
                            existing_name = (contact.get("name") or "").strip()
                            phone_only = bool(re.fullmatch(r"\+?\d[\d\s().-]*", existing_name)) if existing_name else False
                            patch = {
                                "wa_profile_name": profile_name,
                                "wa_profile_synced_at": _now(),
                            }
                            if not existing_name or phone_only:
                                patch["name"] = profile_name
                                patch["updated_at"] = _now()
                            await db.directory_contacts.update_one(
                                {"id": contact["id"]},
                                {"$set": patch},
                            )
                        else:
                            # Unknown sender — upsert a `wa_pending_imports` record
                            # so the admin can decide to create a contact or ignore.
                            await db.wa_pending_imports.update_one(
                                {"phone_digits": digits_only, "client_id": client_scope},
                                {
                                    "$setOnInsert": {
                                        "id": _uuid(),
                                        "phone_digits": digits_only,
                                        "from": from_num,
                                        "client_id": client_scope,
                                        "first_seen_at": _now(),
                                    },
                                    "$set": {
                                        "wa_profile_name": profile_name,
                                        "last_seen_at": _now(),
                                        "last_message": (text_body or "")[:200],
                                    },
                                    "$inc": {"messages_count": 1},
                                },
                                upsert=True,
                            )
                    # Lot 36 — « !formulaire » : document (Word, Excel, PDF) ou photo en pièce
                    # jointe avec cette légende (ou texte seul → mode d'emploi). Traité ici,
                    # avant les autres commandes (elles n'acceptent que du texte).
                    if re.match(r"^[!/]\s*formulaires?\b", (text_body or "").strip(), re.IGNORECASE) \
                            and mtype in ("text", "document", "image") and "_liluvine_formulaire" in globals():
                        try:
                            await _liluvine_formulaire["commande"](
                                from_num=from_num, profile_name=profile_name, mtype=mtype,
                                media_info=media_info if mtype != "text" else None,
                                nom_fichier=(msg.get("document") or {}).get("filename"),
                                compte_par_defaut=client_scope)
                        except Exception:  # noqa: BLE001
                            logger.warning("[!formulaire] commande en échec", exc_info=True)
                        continue

                    # Liluvine remote command? (only on plain text messages)
                    if mtype == "text" and text_body and (text_body.strip().startswith("!") or text_body.strip().startswith("/")):
                        try:
                            await _try_handle_liluvine_wa_command(from_num, text_body)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("liluvine cmd parse failed: %s", exc)

                    # Iter40 (2026-02) — HR WhatsApp commands (!absence, !avance)
                    # + ticket WA command (!ticket). Handled BEFORE the
                    # auto-reply so the same message is not processed twice.
                    hr_handled = False
                    if mtype == "text" and text_body and (text_body.strip().startswith("!") or text_body.strip().startswith("/")):
                        # !aide / !help / !commandes — list all available WA commands.
                        if re.match(r"^[!/]\s*(aide|help|commandes?|cmd)\s*$", text_body.strip(), re.IGNORECASE):
                            help_msg = (
                                "*Liluvine PRO — Commandes WhatsApp disponibles*\n\n"
                                "🆘 `!aide` — Affiche cette liste\n\n"
                                "📅 `!absence YYYY-MM-DD [au YYYY-MM-DD] [motif]`\n"
                                "    Demande d'absence (désactive le portail jusqu'à validation).\n"
                                "    Ex : `!absence 2026-03-12 au 2026-03-14 maladie`\n\n"
                                "💰 `!avance MONTANT [motif]`\n"
                                "    Demande d'avance sur salaire.\n"
                                "    Ex : `!avance 50000 mariage`\n\n"
                                "🎫 `!ticket <description>`\n"
                                "    Ouvre un ticket support. (Réservé aux numéros autorisés.)\n"
                                "    Ex : `!ticket Imprimante en panne bureau 3`\n\n"
                                "📝 `!formulaire` — envoyez un questionnaire (Word, Excel, PDF ou photo) avec\n"
                                "    cette légende : je le transforme en formulaire en ligne à faire remplir.\n\n"
                                "⚙️ `!seuil N` / `!niveau N` — (Admin uniquement) ajuste le seuil/niveau Liluvine.\n\n"
                                "ℹ️ Vous pouvez aussi me poser des questions en langage naturel : "
                                "RDV à venir, tickets actifs, congés restants, contacts, etc. "
                                "Les modules accessibles dépendent de vos autorisations."
                            )
                            try:
                                await _wa_send_text(from_num, help_msg)
                                hr_handled = True
                            except Exception:  # noqa: BLE001
                                pass
                        if not hr_handled:
                            try:
                                from routes.liluvine_hr_wa import try_handle_hr_wa_command
                                hr_res = await try_handle_hr_wa_command(
                                    db,
                                    from_phone=from_num,
                                    message_text=text_body,
                                    wa_send_text=_wa_send_text,
                                )
                                if hr_res is not None:
                                    hr_handled = True
                                    reply = (hr_res or {}).get("user_reply")
                                    if reply:
                                        try:
                                            await _wa_send_text(from_num, reply)
                                        except Exception:  # noqa: BLE001
                                            pass
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("[hr_wa_cmd] handler crashed: %s", exc)
                        # !ticket command (business RAG action)
                        if not hr_handled:
                            try:
                                from routes.liluvine_business_rag import (
                                    detect_ticket_command,
                                    handle_ticket_command,
                                )
                                if detect_ticket_command(text_body):
                                    tk_res = await handle_ticket_command(
                                        db,
                                        phone_digits=digits_only,
                                        text=text_body,
                                        wa_send_text=_wa_send_text,
                                    )
                                    hr_handled = True
                                    reply = (tk_res or {}).get("user_reply")
                                    if reply:
                                        try:
                                            await _wa_send_text(from_num, reply)
                                        except Exception:  # noqa: BLE001
                                            pass
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("[ticket_wa_cmd] handler crashed: %s", exc)
                        # Iter41 Phase 2 — !vidal* commands (médicament, AMM, interactions, allergie)
                        if not hr_handled:
                            try:
                                from routes.liluvine_vidal_wa import try_handle_vidal_wa_command
                                vd_res = await try_handle_vidal_wa_command(
                                    db,
                                    from_phone=from_num,
                                    message_text=text_body,
                                )
                                if vd_res is not None:
                                    hr_handled = True
                                    reply = (vd_res or {}).get("user_reply")
                                    if reply:
                                        try:
                                            await _wa_send_text(from_num, reply)
                                        except Exception:  # noqa: BLE001
                                            pass
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("[vidal_wa_cmd] handler crashed: %s", exc)
                        # Iter41 Phase 3 — !aizenta <produit> (officines, public)
                        if not hr_handled:
                            try:
                                from routes.officines_wa import try_handle_aizenta_command
                                az_res = await try_handle_aizenta_command(
                                    db,
                                    from_phone=from_num,
                                    message_text=text_body,
                                )
                                if az_res is not None:
                                    hr_handled = True
                                    reply = (az_res or {}).get("user_reply")
                                    if reply:
                                        try:
                                            await _wa_send_text(from_num, reply)
                                        except Exception:  # noqa: BLE001
                                            pass
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("[aizenta_wa_cmd] handler crashed: %s", exc)
                        # Iter41 Phase 3 — !synthese [début] [fin] (Liluvine)
                        if not hr_handled:
                            try:
                                from routes.synthese import detect_and_handle_synthese_command
                                sy_res = await detect_and_handle_synthese_command(
                                    db,
                                    from_phone=from_num,
                                    message_text=text_body,
                                )
                                if sy_res is not None:
                                    hr_handled = True
                                    reply = (sy_res or {}).get("user_reply")
                                    if reply:
                                        try:
                                            await _wa_send_text(from_num, reply)
                                        except Exception:  # noqa: BLE001
                                            pass
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("[synthese_wa_cmd] handler crashed: %s", exc)

                    # Iter38r-fix9l — WA Tasks bidirectional sync. Check if
                    # this inbound is a task acknowledgement (OK 1,3 / FAIT 2)
                    # by an opted-in user, BEFORE Liluvine auto-reply so it
                    # doesn't double-process.
                    skip_autoreply = False
                    if mtype == "text" and text_body:
                        indexes = _parse_task_ack(text_body)
                        if indexes:
                            try:
                                # Find a user whose WA matches the sender
                                u_match = await db.users.find_one(
                                    {"$or": [{"whatsapp": {"$regex": digits_only + "$"}},
                                             {"phone": {"$regex": digits_only + "$"}}]},
                                    {"_id": 0, "id": 1, "email": 1},
                                )
                                if u_match:
                                    ack = await _apply_task_ack_for_user(db, u_match["id"], indexes)
                                    if ack.get("matched", 0) > 0:
                                        confirmation = f"✅ {ack['matched']} tâche(s) marquée(s) comme faite(s). Bonne journée !"
                                        try:
                                            await _wa_send_text(from_num, confirmation)
                                        except Exception:
                                            pass
                                        skip_autoreply = True
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("[wa_task_ack] failed: %s", exc)

                    # Iter38r-fix9a — Liluvine PRO native WhatsApp auto-reply.
                    # No n8n needed: when the toggle is on AND the message
                    # passes the configured rules, Liluvine generates a reply
                    # via Claude and ships it back through Meta Graph API.
                    # Iter43-fix24l (2026-06) — Les `!commandes` non HR (ex. !garde,
                    # !meteo, !adresse, !horaires, !stock, !Aizenta) doivent AUSSI
                    # passer par `autoreply_to_inbound` qui contient maintenant
                    # le dispatcher des commandes publiques + le catch-all `…`.
                    # On ne skip QUE quand `hr_handled` a déjà traité le message.
                    # Lot 24 — chaque message reçu laisse une trace de la décision de
                    # Liluvine (répondu, ou pourquoi pas) : Paramètres → Auto-réponse
                    # WhatsApp → « Pourquoi Liluvine n'a pas répondu ? ».
                    if skip_autoreply or hr_handled:
                        ar_result = {"ok": False, "reason": "task_ack" if skip_autoreply else "hr_command"}
                    elif mtype != "text" or not text_body:
                        ar_result = {"ok": False, "reason": "non_text_message", "message_type": mtype}
                    else:
                        ar_result = None
                    if ar_result is None:
                        try:
                            from routes.liluvine_wa_autoreply import autoreply_to_inbound
                            s_root = await db.settings.find_one({"_id": "global"}) or {}
                            ar_result = await autoreply_to_inbound(
                                db,
                                inbound_doc=doc,
                                contact=contact,
                                settings_doc=s_root,
                                wa_send_text=_wa_send_text,
                                wa_send_interactive_button=_wa_send_interactive_button,
                            )
                            if ar_result.get("ok"):
                                logger.info("[wa_autoreply] sent for %s (cmd=%s, msg_id=%s)",
                                            digits_only, ar_result.get("command"),
                                            ar_result.get("wa_out_message_id"))
                            else:
                                logger.debug("[wa_autoreply] skipped (%s)", ar_result.get("reason"))
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("[wa_autoreply] handler crashed: %s", exc)
                            ar_result = {"ok": False, "reason": f"crash: {str(exc)[:160]}"}
                    try:
                        await db.liluvine_wa_autoreply_log.insert_one({
                            "id": _uuid(), "at": _now(), "tenant_id": scope_for_msg,
                            "phone_digits": digits_only, "contact_id": (contact or {}).get("id"),
                            "contact_name": (contact or {}).get("name") or profile_name,
                            "message_type": mtype, "text": (text_body or "")[:160],
                            "ok": bool((ar_result or {}).get("ok")),
                            "reason": str((ar_result or {}).get("reason") or ("sent" if (ar_result or {}).get("ok") else "unknown"))[:200],
                            "command": (ar_result or {}).get("command"),
                            "prospect": (ar_result or {}).get("prospect"),
                        })
                    except Exception:  # noqa: BLE001
                        pass
                except Exception as exc:  # noqa: BLE001
                    err = f"inbound[{mtype if 'mtype' in locals() else '?'}]: {exc!r}"
                    errors.append(err[:250])
                    logger.warning("WA inbound parse failed: %s", exc)
            # --- Status updates for outbound ---
            for st in val.get("statuses") or []:
                extracted_statuses += 1
                try:
                    mid = st.get("id")
                    status_val = st.get("status") or ""  # sent | delivered | read | failed
                    ts_raw = int(st.get("timestamp") or 0)
                    ts_iso = datetime.fromtimestamp(ts_raw, tz=timezone.utc).isoformat() if ts_raw else _now()
                    if not mid:
                        continue
                    stamp_field = {
                        "sent": "sent_at",
                        "delivered": "delivered_at",
                        "read": "read_at",
                        "failed": "failed_at",
                    }.get(status_val)
                    update: Dict[str, Any] = {
                        "wa_status": status_val,
                        "wa_status_updated_at": _now(),
                    }
                    if stamp_field:
                        update[stamp_field] = ts_iso
                    if status_val == "failed":
                        errs = st.get("errors") or []
                        if errs:
                            update["wa_error_code"] = errs[0].get("code")
                            update["wa_error_message"] = errs[0].get("message") or errs[0].get("title")
                    # Match by both possible keys (legacy schema used `message_id`,
                    # new inbound schema uses `wa_message_id`). Try both.
                    res = await db.whatsapp_messages.update_one(
                        {"$or": [{"message_id": mid}, {"wa_message_id": mid}]},
                        {"$set": update},
                    )
                    if res.matched_count == 0:
                        # Stash so the matching outbound row can self-heal later
                        await db.wa_pending_statuses.update_one(
                            {"message_id": mid},
                            {"$set": {**update, "message_id": mid, "received_at": _now()}},
                            upsert=True,
                        )
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"status: {exc!r}"[:250])
                    logger.warning("WA status parse failed: %s", exc)

    # Persist the debug log entry (best-effort)
    try:
        log_entry = {
            "id": _uuid(),
            "received_at": _now(),
            "client_ip": (request.client.host if request.client else None),
            "headers": {k: v for k, v in request.headers.items() if k.lower() in (
                "user-agent", "x-hub-signature", "x-hub-signature-256", "content-type", "x-forwarded-for",
            )},
            "raw_bytes_len": len(raw_bytes),
            "parse_error": parse_error,
            "object": body.get("object"),
            "entry_count": len(body.get("entry") or []),
            "extracted_messages": extracted_messages,
            "extracted_statuses": extracted_statuses,
            "inserted_messages": inserted_messages,
            "errors": errors[:10],
            "body": body if len(raw_bytes) < 30000 else {"_truncated": True, "preview": (raw_bytes[:2000].decode("utf-8", errors="replace") if raw_bytes else "")},
        }
        await db.wa_webhook_logs.insert_one(log_entry)
        # Cap retention at 200 entries (delete oldest beyond)
        total = await db.wa_webhook_logs.count_documents({})
        if total > 220:
            cutoff = await db.wa_webhook_logs.find(
                {}, {"_id": 0, "received_at": 1}
            ).sort("received_at", -1).skip(200).limit(1).to_list(1)
            if cutoff:
                await db.wa_webhook_logs.delete_many({"received_at": {"$lt": cutoff[0]["received_at"]}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("wa_webhook_logs persist failed: %s", exc)

    return {"ok": True}


@api.get("/admin/whatsapp/webhook-logs", tags=["Admin"])
async def admin_list_wa_webhook_logs(
    limit: int = Query(default=50, ge=1, le=200),
    _: dict = Depends(get_current_admin),
):
    """Iter35a — Read the last `limit` raw webhook payloads received from
    Meta. Useful when inbound messages stop appearing in the UI: lets the
    admin verify Meta is actually hitting the endpoint and inspect the
    exact payload shape (button vs interactive vs text)."""
    items = await db.wa_webhook_logs.find({}, {"_id": 0}).sort("received_at", -1).to_list(limit)
    return {"items": items, "count": len(items)}


@api.delete("/admin/whatsapp/webhook-logs", tags=["Admin"])
async def admin_clear_wa_webhook_logs(_: dict = Depends(get_current_admin)):
    """Purge all stored webhook payloads."""
    res = await db.wa_webhook_logs.delete_many({})
    return {"ok": True, "deleted": res.deleted_count}
