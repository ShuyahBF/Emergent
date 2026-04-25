"""Google reCAPTCHA verification using admin-configurable secret key."""
import logging
import httpx

from db import db

logger = logging.getLogger(__name__)


async def verify_recaptcha(token: str | None) -> dict:
    """Returns dict with keys: success (bool), enabled (bool), reason (str)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    enabled = bool(s.get("recaptcha_enabled")) and bool(s.get("recaptcha_secret_key"))
    if not enabled:
        return {"success": True, "enabled": False, "reason": "reCAPTCHA désactivé"}

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
