"""SMTP email service using admin-configurable settings."""
import asyncio
import smtplib
import ssl
import logging
from email.message import EmailMessage

from db import db

logger = logging.getLogger(__name__)


async def get_smtp_settings() -> dict:
    s = await db.settings.find_one({"_id": "global"}) or {}
    return {
        "host": s.get("smtp_host"),
        "port": int(s.get("smtp_port") or 587),
        "user": s.get("smtp_user"),
        "password": s.get("smtp_password"),
        "from_email": s.get("smtp_from_email") or s.get("smtp_user"),
        "from_name": s.get("smtp_from_name") or "",
        "use_tls": s.get("smtp_use_tls", True),
    }


def _send_email_sync(cfg: dict, to_email: str, subject: str, html_body: str, text_body: str, attachments: list[dict] | None = None) -> bool:
    """Blocking SMTP send. Always called via asyncio.to_thread + wait_for.
    `attachments` is a list of dicts {filename, content (bytes), mime_type}."""
    msg = EmailMessage()
    msg["Subject"] = subject
    # RFC 5322 "Name <email>" header when from_name configured
    from_name = (cfg.get("from_name") or "").strip()
    if from_name:
        # email.message.EmailMessage handles encoding automatically
        msg["From"] = f"{from_name} <{cfg['from_email']}>"
    else:
        msg["From"] = cfg["from_email"]
    msg["To"] = to_email
    msg.set_content(text_body or "Veuillez activer HTML pour voir ce message.")
    msg.add_alternative(html_body, subtype="html")
    for att in (attachments or []):
        if not att or att.get("content") is None:
            continue
        maintype, _, subtype = (att.get("mime_type") or "application/octet-stream").partition("/")
        msg.add_attachment(
            att["content"],
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=att.get("filename") or "attachment.bin",
        )
    if cfg["use_tls"]:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
            server.starttls(context=ctx)
            server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15) as server:
            server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
    return True


async def send_email(to_email: str, subject: str, html_body: str, text_body: str = "", attachment: dict | None = None, attachments: list[dict] | None = None, timeout_s: float = 6.0) -> bool:
    """Returns True if email was sent successfully, False otherwise (e.g. SMTP not configured).
    Optional `attachment` dict OR list `attachments` of {filename, content, mime_type}.
    `timeout_s` is increased automatically when any attachment is present."""
    cfg = await get_smtp_settings()
    if not cfg["host"] or not cfg["user"] or not cfg["password"] or not cfg["from_email"]:
        logger.warning("SMTP not configured. Skipping email to %s.", to_email)
        return False
    if "@" not in (cfg["from_email"] or ""):
        logger.warning("SMTP from_email looks invalid (%s). Skipping send.", cfg["from_email"])
        return False
    # Normalize attachments list
    atts: list[dict] = []
    if attachment:
        atts.append(attachment)
    if attachments:
        atts.extend(attachments)
    try:
        effective_timeout = max(timeout_s, 45.0) if atts else timeout_s
        return await asyncio.wait_for(
            asyncio.to_thread(_send_email_sync, cfg, to_email, subject, html_body, text_body, atts),
            timeout=effective_timeout,
        )
    except asyncio.TimeoutError:
        logger.error("SMTP send timed out for %s — skipping.", to_email)
        return False
    except Exception as e:  # noqa: BLE001
        logger.error("SMTP send failed: %s", e)
        return False


async def send_otp_email(to_email: str, full_name: str, code: str) -> bool:
    subject = f"Votre code de connexion SAWALI – {code}"
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#081226;padding:32px;color:#fff;">
      <div style="max-width:480px;margin:auto;background:#0E1F3D;border:1px solid rgba(30,144,255,.3);border-radius:12px;padding:32px;">
        <h2 style="color:#1E90FF;margin:0 0 8px 0;">SAWALI SMART SYSTEMS</h2>
        <p style="color:#94A3B8;margin:0 0 24px 0;font-size:14px;">Software Engineering</p>
        <p>Bonjour <strong>{full_name}</strong>,</p>
        <p>Voici votre code de vérification à usage unique :</p>
        <div style="font-size:36px;letter-spacing:12px;font-weight:bold;color:#2BA4FF;background:#081226;border:1px solid #1E90FF;padding:16px;text-align:center;border-radius:8px;margin:16px 0;">
          {code}
        </div>
        <p style="color:#94A3B8;font-size:13px;">Ce code expire dans 10 minutes. Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.</p>
        <hr style="border:none;border-top:1px solid rgba(255,255,255,.1);margin:24px 0;">
        <p style="color:#64748B;font-size:12px;margin:0;">© SAWALI SMART SYSTEMS</p>
      </div>
    </div>
    """
    text = f"Votre code de connexion SAWALI: {code}\nIl expire dans 10 minutes."
    return await send_email(to_email, subject, html, text)
