"""Google reCAPTCHA verification using admin-configurable secret key."""
import logging
import os
import httpx

from db import db

logger = logging.getLogger(__name__)


def _is_preview_request(request) -> bool:
    """Iter35j — return True when the incoming request comes from the
    Emergent preview environment (host ends with .preview.emergentagent.com
    OR a custom DEV_HOSTS env override). Used to auto-bypass reCAPTCHA so
    developers can log in without registering the preview URL with Google.
    """
    if request is None:
        return False
    try:
        host = (request.headers.get("host") or "").lower()
        origin = (request.headers.get("origin") or "").lower()
        referer = (request.headers.get("referer") or "").lower()
        # The K8s ingress may rewrite Host → internal name, in which case
        # the original hostname is preserved in X-Forwarded-Host or referer.
        xfh = (request.headers.get("x-forwarded-host") or "").lower()
        xfor_h = (request.headers.get("x-original-host") or "").lower()
        candidates = " ".join([host, origin, referer, xfh, xfor_h])
        logger.info("recaptcha bypass check: host=%s origin=%s referer=%s xfh=%s",
                    host, origin, referer, xfh)
        if ".preview.emergentagent.com" in candidates:
            return True
        # Optional comma-separated override (e.g. for local dev or staging)
        dev_hosts = (os.environ.get("CAPTCHA_BYPASS_HOSTS") or "").lower()
        for h in [x.strip() for x in dev_hosts.split(",") if x.strip()]:
            if h in candidates:
                return True
    except Exception:
        pass
    return False


async def verify_recaptcha(token: str | None, request=None) -> dict:
    """Returns dict with keys: success (bool), enabled (bool), reason (str).

    Iter35j — automatically bypasses verification when the request comes
    from the Emergent preview host (so admins can log in without
    registering that URL with reCAPTCHA).
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    enabled = bool(s.get("recaptcha_enabled")) and bool(s.get("recaptcha_secret_key"))
    if not enabled:
        return {"success": True, "enabled": False, "reason": "reCAPTCHA désactivé"}

    if _is_preview_request(request):
        return {"success": True, "enabled": True, "reason": "preview-bypass"}

    if not token:
        return {"success": False, "enabled": True, "reason": "Captcha manquant"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://www.google.com/recaptcha/api/siteverify",
                data={"secret": s["recaptcha_secret_key"], "response": token},
            )
            data = r.json()
            return {
                "success": bool(data.get("success")),
                "enabled": True,
                "reason": ",".join(data.get("error-codes", [])) or "ok",
            }
    except Exception as e:
        logger.error("reCAPTCHA verify failed: %s", e)
        return {"success": False, "enabled": True, "reason": "Erreur de vérification captcha"}
