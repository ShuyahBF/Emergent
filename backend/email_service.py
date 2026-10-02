"""Service d'envoi des e-mails (réglages de la plateforme).

Lot 52 : le super-admin choisit le service d'envoi parmi Resend, ZeptoMail (Zoho), Brevo et SMTP
(voir email_fournisseurs.py). La signature de `send_email` ne change pas : OTP par e-mail, rapports,
sauvegardes (lot 49), maintenance et abonnements (lots 50 et 51) l'utilisent tels quels.
"""
import asyncio
import smtplib
import ssl
import logging
from email.message import EmailMessage

import email_fournisseurs as ef
from db import db

logger = logging.getLogger(__name__)


async def get_smtp_settings() -> dict:
    """Réglages SMTP enregistrés (compatibilité) : mot de passe chiffré depuis le lot 52,
    ancien mot de passe en clair encore accepté tant qu'il n'a pas été migré."""
    doc = await db[ef.REGLAGES].find_one({"_id": ef.ID_PLATEFORME}) or {}
    s = await db.settings.find_one({"_id": "global"}) or {}
    cfg = ef._smtp_ecran(doc, s)
    cfg.pop("fournisseur", None)
    return cfg


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
    # Lot 52 — adresse de réponse facultative
    if cfg.get("reply_to"):
        msg["Reply-To"] = cfg["reply_to"]
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


async def envoyer_avec_config(cfg: dict, to_email: str, subject: str, html_body: str, text_body: str = "",
                              attachments: list[dict] | None = None, timeout_s: float = 6.0,
                              reply_to: str | None = None) -> dict:
    """Lot 52 — Envoi avec une configuration donnée (`ef.configuration_effective()`).
    Lève ef.ErreurEnvoi (« <Fournisseur> <code HTTP> : <message> ») en cas d'échec.
    Resend, Brevo, ZeptoMail : HTTPS (httpx, 20 s). SMTP : code existant (thread + délai)."""
    four = cfg.get("fournisseur")
    texte = text_body or ef.texte_depuis_html(html_body) or "Veuillez activer HTML pour voir ce message."
    if four in ef.FOURNISSEURS_HTTP:
        return await ef.envoyer_http(cfg, to_email, subject, texte, html_body or "", reply_to, attachments)
    if four != ef.SMTP:
        raise ef.ErreurEnvoi(cfg.get("raison") or "Aucun service d'envoi configuré")
    if "@" not in (cfg.get("from_email") or ""):
        raise ef.ErreurEnvoi(f"SMTP : adresse d'expéditeur invalide ({cfg.get('from_email')})")
    smtp_cfg = {**cfg, "reply_to": reply_to}
    effective_timeout = max(timeout_s, 45.0) if attachments else timeout_s
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_send_email_sync, smtp_cfg, to_email, subject, html_body, text_body, attachments or []),
            timeout=effective_timeout,
        )
    except asyncio.TimeoutError as exc:
        raise ef.ErreurEnvoi(f"SMTP : délai dépassé ({int(effective_timeout)} s)") from exc
    except ef.ErreurEnvoi:
        raise
    except Exception as exc:  # noqa: BLE001 — message SMTP (jamais le mot de passe)
        message = f"SMTP : {exc}"
        if cfg.get("password"):
            message = message.replace(cfg["password"], "***")
        raise ef.ErreurEnvoi(message[:ef.LONGUEUR_ERREUR]) from exc
    return {"ok": True, "fournisseur": ef.SMTP}


async def send_email(to_email: str, subject: str, html_body: str, text_body: str = "", attachment: dict | None = None, attachments: list[dict] | None = None, timeout_s: float = 6.0) -> bool:
    """Returns True if email was sent successfully, False otherwise (e.g. not configured).
    Optional `attachment` dict OR list `attachments` of {filename, content, mime_type}.
    `timeout_s` is increased automatically when any attachment is present (SMTP).
    Lot 52 : le service d'envoi est celui choisi par le super-admin (Resend, ZeptoMail, Brevo, SMTP),
    à défaut les anciens réglages SMTP, à défaut les variables d'environnement. Chaque envoi est
    journalisé (ENVOYE / ECHEC / NON_CONFIGURE) sans jamais bloquer l'action en cours."""
    try:
        cfg = await ef.configuration_effective()
    except Exception as e:  # noqa: BLE001 — base indisponible : l'action en cours continue
        logger.error("Email settings unavailable: %s", e)
        return False
    if not cfg.get("fournisseur"):
        logger.warning("Email not configured (%s). Skipping email to %s.", cfg.get("raison"), to_email)
        await ef.journaliser_envoi(ef.NON_CONFIGURE, None, to_email, subject, cfg.get("raison"))
        return False
    # Normalize attachments list
    atts: list[dict] = []
    if attachment:
        atts.append(attachment)
    if attachments:
        atts.extend(attachments)
    try:
        await envoyer_avec_config(cfg, to_email, subject, html_body, text_body, atts, timeout_s)
    except Exception as e:  # noqa: BLE001
        logger.error("Email send failed: %s", e)
        await ef.journaliser_envoi(ef.ECHEC, cfg["fournisseur"], to_email, subject, str(e))
        return False
    await ef.journaliser_envoi(ef.ENVOYE, cfg["fournisseur"], to_email, subject)
    return True


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
