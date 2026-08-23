"""Iter43-fix24az-q (2026-07-22) — WhatsApp helpers extraction (Phase A refactor).

Extracts pure/near-pure WhatsApp helpers from server.py (~24k lines → alléger).
Zero behaviour change — factory injects db, logger, and constants.

Helpers exposed :
  - _normalize_wa_phone(raw)                                          [pure]
  - _wa_kind_for_mime(mime)                                           [pure]
  - _wa_window_open(iso, window_seconds=24*3600)                      [pure]
  - _wa_apply_image_watermark_qr(path, watermark_text, qr_payload)    [pure PIL]
  - _wa_send_template(to, name, lang, components)                     [db.settings]
  - _wa_send_text(to, text, reply_to_message_id)                      [db.settings]
  - _wa_send_media(to, kind, public_url, caption, filename, reply_to) [db.settings]
  - _wa_download_inbound_media(media_id)                              [db.settings + db.files]
  - _wa_transcribe_audio_file(path, language)                         [db.settings]
  - _wa_compute_reply_window(scope, contact_id, phone_digits, now)    [db.whatsapp_messages]
  - _wa_last_inbound_iso(scope, contact_id, phone_digits)             [db.whatsapp_messages]
"""
from __future__ import annotations

import json
import logging
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("sawali.whatsapp_helpers")

# MIME → WhatsApp Cloud API media kind mapping.
WA_MEDIA_KIND_BY_MIME = {
    "image/jpeg": "image", "image/jpg": "image", "image/png": "image", "image/webp": "image",
    "audio/aac": "audio", "audio/mp4": "audio", "audio/mpeg": "audio", "audio/amr": "audio",
    "audio/ogg": "audio", "audio/opus": "audio", "audio/webm": "audio",
    "video/mp4": "video", "video/3gpp": "video",
    "application/pdf": "document",
}

_EXT_BY_MIME = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "audio/aac": ".aac", "audio/mp4": ".m4a", "audio/mpeg": ".mp3",
    "audio/amr": ".amr", "audio/ogg": ".ogg", "audio/opus": ".opus", "audio/webm": ".webm",
    "video/mp4": ".mp4", "video/3gpp": ".3gp",
    "application/pdf": ".pdf",
}


# ---------------------------------------------------------------------------
# PURE HELPERS (no injected deps needed)
# ---------------------------------------------------------------------------
def _normalize_wa_phone(raw: Optional[str]) -> str:
    """Sanitize a WhatsApp/phone number into the format Meta Cloud API expects:
    digits-only with country code, no leading +.
    Strips all non-digit characters (spaces, parens, dots, dashes, plus).
    Returns "" when nothing usable was provided so callers can short-circuit cleanly."""
    if not raw:
        return ""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits


def _wa_kind_for_mime(mime: str) -> str:
    """Map a MIME type to one of (image|audio|video|document)."""
    base = (mime or "").split(";", 1)[0].strip().lower()
    if base in WA_MEDIA_KIND_BY_MIME:
        return WA_MEDIA_KIND_BY_MIME[base]
    if base.startswith("image/"):
        return "image"
    if base.startswith("audio/"):
        return "audio"
    if base.startswith("video/"):
        return "video"
    return "document"


def _wa_window_open(last_inbound_iso: Optional[str], window_seconds: int = 24 * 3600) -> bool:
    """Return True when the last inbound is within the 24h Meta customer service window."""
    if not last_inbound_iso:
        return False
    try:
        ts = datetime.fromisoformat(last_inbound_iso.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return (datetime.now(timezone.utc) - ts).total_seconds() < window_seconds


# Iter43-fix24az-u (2026-07-22) — WhatsApp text formatting safety.
# --------------------------------------------------------------------
# WhatsApp Cloud API accepts text messages that contain underscores freely,
# but the WhatsApp mobile CLIENT parser tries to interpret `_..._` as italic.
# When a message contains identifiers like `Off_07f24ab4` or
# `Officine_test_20ee07dfa1` (multi-underscore words), the client's italic
# parser gets confused and can render the whole message BLANK on the phone
# (only subsequent messages arrive).
#
# Fix : insert a zero-width space (\u200B) immediately after every underscore
# that sits BETWEEN two word characters. Standalone underscores at word
# boundaries (`_hello_` = intended italic) are left untouched.
#
# Result:
#   - `Off_07f24ab4`  →  `Off_\u200B07f24ab4`  (visually identical, parser skips)
#   - `_hello world_` →  `_hello world_`       (italic still works)
#   - `_hello_world_` →  `_hello_\u200Bworld_` (nested `_` neutralised)
#
# The insertion is idempotent : running it twice produces the same output
# (the ZWSP breaks the `\w_\w` pattern for subsequent runs).
_WA_UNDERSCORE_PATTERN = None  # lazy-compiled regex


def _wa_neutralize_underscores(text: str) -> str:
    """Neutralise multi-underscore words that break the WhatsApp italic parser.

    Public helper — exported for callers that build text via templates and
    want to sanitize before splitting/joining. `_wa_send_text` already applies
    this automatically to every outbound text, so most callers don't need
    to invoke it explicitly.
    """
    if not text or "_" not in text:
        return text
    global _WA_UNDERSCORE_PATTERN
    if _WA_UNDERSCORE_PATTERN is None:
        import re as _re
        _WA_UNDERSCORE_PATTERN = _re.compile(r"(\w)_(\w)")
    # ZWSP inserted after every underscore between word chars. Loop until
    # stable so overlapping groups like `a_b_c` are fully sanitised.
    _ZWSP = "\u200B"
    prev = None
    out = text
    while out != prev:
        prev = out
        out = _WA_UNDERSCORE_PATTERN.sub(lambda m: f"{m.group(1)}_{_ZWSP}{m.group(2)}", out)
    return out


# ---------------------------------------------------------------------------
# Iter43-fix24az-v (2026-07-22) — WhatsApp text length safety net.
#
# The WhatsApp Cloud API hard-caps text body at 4096 characters. Payloads
# larger than that are silently rejected (the API returns 200 OK but the
# user's phone shows a blank message). This has caused the `!garde` command
# to fail in production when the on-duty list grew past ~30 officines.
#
# Fix : split any outbound text > _WA_TEXT_MAX (3800, safe margin under 4096)
# into multiple sequential messages. Split preferentially at :
#   1) explicit hint markers `_WA_SPLIT_HINT` inserted by the caller (semantic)
#   2) paragraph breaks `\n\n`
#   3) line breaks `\n`
#   4) hard cut at max_len (last resort)
# ---------------------------------------------------------------------------
_WA_TEXT_MAX = 3800  # keep safe margin under Meta's 4096 hard limit
# Invisible unicode separator used as a "prefer split here" hint. Callers
# that build long lists (garde, produits, ...) can insert this between
# semantic sections so the auto-splitter breaks at the right place.
_WA_SPLIT_HINT = "\u2063\u2063"  # U+2063 = INVISIBLE SEPARATOR


def _wa_split_long_text(text: str, max_len: int = _WA_TEXT_MAX) -> List[str]:
    """Split a long WhatsApp text into safe chunks (<= max_len chars each).

    Returns a list with a single element when the text already fits. Splits
    are attempted at semantic boundaries (explicit hint > `\\n\\n` > `\\n`)
    before falling back to a hard character cut.
    """
    if not text:
        return [""]
    if len(text) <= max_len:
        return [text]
    # 1) Explicit semantic hint (preferred)
    if _WA_SPLIT_HINT in text:
        pieces = text.split(_WA_SPLIT_HINT)
        out: List[str] = []
        for p in pieces:
            out.extend(_wa_split_long_text(p, max_len))
        return [c for c in out if c.strip()]
    # 2 → 4) Iterative split at natural boundaries.
    chunks: List[str] = []
    remaining = text
    while len(remaining) > max_len:
        # Try paragraph break first.
        cut = remaining.rfind("\n\n", 0, max_len)
        if cut < max_len // 3:
            # Try single newline.
            cut = remaining.rfind("\n", 0, max_len)
        if cut < max_len // 4:
            # Last resort — hard cut at max_len.
            cut = max_len
        chunk = remaining[:cut].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _wa_apply_image_watermark_qr(
    src_path: Path,
    *,
    watermark_text: Optional[str],
    qr_payload: Optional[str],
) -> Path:
    """Burn a discrete watermark (bottom-right) + optional QR code on the source
    image and write the result to a new file alongside the original. Returns the
    new Path. If both inputs are falsy or processing fails, returns the original.
    """
    if not (watermark_text or qr_payload):
        return src_path
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return src_path
    try:
        img = Image.open(src_path).convert("RGBA")
    except Exception:
        return src_path
    W, H = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # ----- Watermark text (bottom-right, semi-transparent white on dark pill) -----
    if (watermark_text or "").strip():
        text = watermark_text.strip()[:120]
        # Pick a font scale ~ 2.2% of the image height (min 14, max 36)
        font_size = max(14, min(36, int(H * 0.022)))
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = font_size * len(text) // 2, font_size
        pad = max(6, font_size // 3)
        x = W - tw - pad * 2 - 12
        y = H - th - pad * 2 - 12
        # Dark pill background
        draw.rounded_rectangle((x, y, x + tw + pad * 2, y + th + pad * 2), radius=pad, fill=(0, 0, 0, 140))
        draw.text((x + pad, y + pad - 2), text, font=font, fill=(255, 255, 255, 235))
    # ----- QR code (top-left, ~10% of width, slight white border) -----
    if (qr_payload or "").strip():
        try:
            import qrcode  # local import — heavy
            qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=1)
            qr.add_data(qr_payload.strip())
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
            qr_size = max(72, min(220, int(W * 0.12)))
            qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
            qx, qy = 16, 16
            # White rounded backdrop for contrast
            draw.rounded_rectangle((qx - 6, qy - 6, qx + qr_size + 6, qy + qr_size + 6), radius=8, fill=(255, 255, 255, 235))
            overlay.alpha_composite(qr_img, (qx, qy))
        except Exception:
            pass
    out = Image.alpha_composite(img, overlay).convert("RGB")
    dst = src_path.with_name(src_path.stem + "_wm.jpg")
    try:
        out.save(dst, format="JPEG", quality=88, optimize=True)
    except Exception:
        return src_path
    return dst


# ---------------------------------------------------------------------------
# FACTORY — DB-BOUND HELPERS
# ---------------------------------------------------------------------------
def attach_whatsapp_helpers(
    *,
    db,
    wa_graph_version: str,
    wa_media_max_bytes: int,
    upload_dir: Path,
    uuid_fn,
    now_fn,
    on_silent_drop=None,  # Iter43-fix24az-w — optional callable(dict) called
                          # when Meta returns 2xx with null message_id (silent
                          # drop). Fire-and-forget: exceptions are swallowed.
) -> Dict[str, Any]:
    """Factory that returns db-bound helper coroutines. Called once at server startup."""

    # 2026-02 fork (P0.5) — Per-tenant Smart Comm credentials resolver. When a
    # tenant has configured `tenant_smart_comm.wa_access_token +
    # wa_phone_number_id`, we use THOSE (strict override, no fallback merge).
    # Otherwise we fall back to the global `db.settings` config used by the
    # legacy senders. This makes every sender tenant-aware without touching
    # 30+ call sites.
    async def _resolve_wa_credentials(tenant_id: Optional[str]) -> Dict[str, Any]:
        tid = (tenant_id or "").strip()
        if tid:
            try:
                smart = await db.tenant_smart_comm.find_one({"tenant_id": tid}, {"_id": 0}) or {}
            except Exception:  # noqa: BLE001
                smart = {}
            token = (smart.get("wa_access_token") or "").strip()
            phone_id = (smart.get("wa_phone_number_id") or "").strip()
            if token and phone_id:
                return {
                    "access_token": token,
                    "phone_number_id": phone_id,
                    "source": "tenant",
                    "tenant_id": tid,
                }
        g = await db.settings.find_one({"_id": "global"}) or {}
        return {
            "access_token": (g.get("wa_access_token") or "").strip(),
            "phone_number_id": (g.get("wa_phone_number_id") or "").strip(),
            "source": "global",
            "tenant_id": None,
        }

    async def _wa_send_template(
        to_e164: str,
        template_name: str,
        language_code: str = "fr",
        components: Optional[list] = None,
        tenant_id: Optional[str] = None,
    ) -> dict:
        """Send a WhatsApp template message. Returns {ok, status, message_id, error, raw}.

        2026-02 fork (P0.5) — When `tenant_id` is provided, uses that tenant's
        Smart Comm WA credentials instead of the global ones.
        """
        creds = await _resolve_wa_credentials(tenant_id)
        access_token = creds["access_token"]
        phone_number_id = creds["phone_number_id"]
        if not access_token or not phone_number_id:
            return {"ok": False, "error": "WhatsApp non configuré (token ou phone_number_id manquant)", "status": None, "message_id": None, "raw": None}
        to_clean = _normalize_wa_phone(to_e164)
        if len(to_clean) < 6:
            return {
                "ok": False, "status": None, "message_id": None,
                "error": f"Numéro invalide « {to_e164} » — il doit contenir un indicatif pays (ex: 225XXXXXXXX)",
                "raw": None,
            }
        url = f"https://graph.facebook.com/{wa_graph_version}/{phone_number_id}/messages"
        body = {
            "messaging_product": "whatsapp",
            "to": to_clean,
            "type": "template",
            "template": {"name": template_name, "language": {"code": language_code}},
        }
        if components:
            body["template"]["components"] = components
        try:
            async with httpx.AsyncClient(timeout=12) as http:
                r = await http.post(url, json=body, headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})
                try:
                    raw = r.json()
                except Exception:
                    raw = {"text": r.text[:2000]}
                if r.status_code >= 300:
                    logger.warning(
                        "[wa-send] FAIL template=%s lang=%s status=%s body=%s meta_response=%s",
                        template_name, language_code, r.status_code,
                        json.dumps(body)[:1500], json.dumps(raw)[:1500],
                    )
                if r.status_code < 300:
                    mid = None
                    if isinstance(raw, dict) and raw.get("messages"):
                        mid = raw["messages"][0].get("id")
                    return {"ok": True, "status": r.status_code, "message_id": mid, "error": None, "raw": raw}
                err_msg = None
                err_details = None
                err_code = None
                if isinstance(raw, dict):
                    err_obj = raw.get("error") or {}
                    err_msg = err_obj.get("message") or str(raw)[:500]
                    err_code = err_obj.get("code")
                    err_details = (err_obj.get("error_data") or {}).get("details")
                    if err_details:
                        err_msg = f"{err_msg} — {err_details}"
                return {"ok": False, "status": r.status_code, "message_id": None,
                        "error": err_msg or f"HTTP {r.status_code}", "error_code": err_code,
                        "error_details": err_details, "raw": raw}
        except httpx.TimeoutException:
            return {"ok": False, "status": None, "message_id": None, "error": "Timeout", "raw": None}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": None, "message_id": None, "error": str(exc)[:500], "raw": None}

    async def _wa_send_text(
        to_e164: str,
        text: str,
        reply_to_message_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> dict:
        """Send a free-form WhatsApp text message (Cloud API type=text).
        Caller must verify the 24h customer-service window before invocation.

        Iter43-fix24az-v (2026-07-22) — Auto-splits texts longer than
        `_WA_TEXT_MAX` (3800 chars) into multiple sequential messages so
        Meta's 4096-char cap never silently drops the payload. Only the FIRST
        chunk carries `reply_to_message_id` (context.message_id). Logs an
        explicit warning if the API returns `null` for `messages[0].id`
        (typical symptom of a length/format rejection).

        2026-02 fork (P0.5) — When `tenant_id` is provided, uses that tenant's
        Smart Comm WA credentials instead of the global ones.
        """
        creds = await _resolve_wa_credentials(tenant_id)
        access_token = creds["access_token"]
        phone_number_id = creds["phone_number_id"]
        if not access_token or not phone_number_id:
            return {"ok": False, "error": "WhatsApp non configuré (token ou phone_number_id manquant)", "status": None, "message_id": None, "raw": None}
        to_clean = _normalize_wa_phone(to_e164)
        if len(to_clean) < 6:
            return {"ok": False, "status": None, "message_id": None,
                    "error": f"Numéro invalide « {to_e164} » — il doit contenir un indicatif pays", "raw": None}
        # Neutralise underscores once (before splitting so ZWSP is preserved).
        neutralised = _wa_neutralize_underscores(text or "")
        chunks = _wa_split_long_text(neutralised)
        total = len(chunks)
        if total > 1:
            logger.info(
                "[wa_send_text] auto-splitting long text (%d chars) into %d chunks for %s",
                len(neutralised), total, to_clean,
            )
        url = f"https://graph.facebook.com/{wa_graph_version}/{phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        message_ids: List[Optional[str]] = []
        last_raw: Any = None
        last_status: Optional[int] = None
        first_error: Optional[str] = None
        first_error_code: Any = None
        parts_failed = 0
        for idx, chunk in enumerate(chunks, start=1):
            body: Dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": to_clean,
                "type": "text",
                "text": {"body": chunk, "preview_url": True},
            }
            # Only the first chunk carries the reply-to context.
            if idx == 1 and reply_to_message_id:
                body["context"] = {"message_id": reply_to_message_id}
            try:
                async with httpx.AsyncClient(timeout=12) as http:
                    r = await http.post(url, json=body, headers=headers)
                    try:
                        raw = r.json()
                    except Exception:
                        raw = {"text": r.text[:2000]}
                    last_raw = raw
                    last_status = r.status_code
                    if r.status_code < 300:
                        mid = None
                        if isinstance(raw, dict) and raw.get("messages"):
                            mid = raw["messages"][0].get("id")
                        message_ids.append(mid)
                        if mid is None:
                            # Guardrail : Meta returned 2xx but no message id →
                            # likely a length/format rejection (silent drop).
                            logger.warning(
                                "[wa_send_text] WhatsApp API returned 2xx but no message_id "
                                "(chunk %d/%d, %d chars, to=%s) — possible length/format rejection. Raw=%s",
                                idx, total, len(chunk), to_clean, str(raw)[:400],
                            )
                            # Fire-and-forget observer callback (see routes/wa_silent_drops.py).
                            if on_silent_drop is not None:
                                try:
                                    import asyncio as _aio
                                    _aio.create_task(on_silent_drop({
                                        "to": to_clean,
                                        "chunk_index": idx,
                                        "chunk_total": total,
                                        "chunk_length": len(chunk),
                                        "chunk_preview": chunk[:200],
                                        "http_status": r.status_code,
                                        "raw": raw,
                                        "kind": "silent_drop_no_message_id",
                                        "at": datetime.now(timezone.utc).isoformat(),
                                    }))
                                except Exception:  # noqa: BLE001
                                    logger.exception("[wa_send_text] on_silent_drop callback failed")
                    else:
                        parts_failed += 1
                        message_ids.append(None)
                        err_msg = None
                        err_code = None
                        if isinstance(raw, dict):
                            err_obj = raw.get("error") or {}
                            err_msg = err_obj.get("message") or str(raw)[:500]
                            err_code = err_obj.get("code")
                            details = (err_obj.get("error_data") or {}).get("details")
                            if details:
                                err_msg = f"{err_msg} — {details}"
                        logger.warning(
                            "[wa_send_text] HTTP %s on chunk %d/%d (to=%s): %s",
                            r.status_code, idx, total, to_clean, err_msg,
                        )
                        if first_error is None:
                            first_error = err_msg or f"HTTP {r.status_code}"
                            first_error_code = err_code
            except httpx.TimeoutException:
                parts_failed += 1
                message_ids.append(None)
                if first_error is None:
                    first_error = "Timeout"
                logger.warning("[wa_send_text] timeout on chunk %d/%d (to=%s)", idx, total, to_clean)
            except Exception as exc:  # noqa: BLE001
                parts_failed += 1
                message_ids.append(None)
                if first_error is None:
                    first_error = str(exc)[:500]
                logger.warning("[wa_send_text] exception on chunk %d/%d (to=%s): %s", idx, total, to_clean, exc)
        # Aggregate result. `message_id` = first non-null id (back-compat with
        # single-message callers). `message_ids` = full list including nulls.
        first_mid = next((m for m in message_ids if m), None)
        all_ok = parts_failed == 0 and first_mid is not None
        return {
            "ok": all_ok,
            "status": last_status,
            "message_id": first_mid,
            "message_ids": message_ids,
            "parts_sent": total - parts_failed,
            "parts_failed": parts_failed,
            "parts_total": total,
            "error": first_error,
            "error_code": first_error_code,
            "raw": last_raw,
        }

    async def _wa_send_media(
        to_e164: str,
        kind: str,
        *,
        public_url: str,
        caption: Optional[str] = None,
        filename: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
    ) -> dict:
        """Send a free-form WhatsApp media message (image/document/audio/video)."""
        s = await db.settings.find_one({"_id": "global"}) or {}
        access_token = s.get("wa_access_token")
        phone_number_id = s.get("wa_phone_number_id")
        if not access_token or not phone_number_id:
            return {"ok": False, "error": "WhatsApp non configuré", "status": None, "message_id": None, "raw": None}
        to_clean = _normalize_wa_phone(to_e164)
        if len(to_clean) < 6:
            return {"ok": False, "status": None, "message_id": None,
                    "error": f"Numéro invalide « {to_e164} »", "raw": None}
        if kind not in ("image", "document", "audio", "video"):
            return {"ok": False, "status": None, "message_id": None, "error": f"Type média non géré: {kind}", "raw": None}
        media_obj: Dict[str, Any] = {"link": public_url}
        if caption and kind in ("image", "document", "video"):
            # Iter43-fix24az-u — neutralize underscores in caption too
            media_obj["caption"] = _wa_neutralize_underscores(caption[:1024])
        if kind == "document" and filename:
            media_obj["filename"] = filename
        body: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to_clean,
            "type": kind,
            kind: media_obj,
        }
        if reply_to_message_id:
            body["context"] = {"message_id": reply_to_message_id}
        url = f"https://graph.facebook.com/{wa_graph_version}/{phone_number_id}/messages"
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.post(url, json=body, headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})
                try:
                    raw = r.json()
                except Exception:
                    raw = {"text": r.text[:2000]}
                if r.status_code < 300:
                    mid = None
                    if isinstance(raw, dict) and raw.get("messages"):
                        mid = raw["messages"][0].get("id")
                    return {"ok": True, "status": r.status_code, "message_id": mid, "error": None, "raw": raw}
                err_msg = None
                err_code = None
                if isinstance(raw, dict):
                    err_obj = raw.get("error") or {}
                    err_msg = err_obj.get("message") or str(raw)[:500]
                    err_code = err_obj.get("code")
                return {"ok": False, "status": r.status_code, "message_id": None,
                        "error": err_msg or f"HTTP {r.status_code}", "error_code": err_code, "raw": raw}
        except httpx.TimeoutException:
            return {"ok": False, "status": None, "message_id": None, "error": "Timeout", "raw": None}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": None, "message_id": None, "error": str(exc)[:500], "raw": None}

    async def _wa_download_inbound_media(media_id: str) -> dict:
        """Download a Meta WhatsApp inbound media binary using its media_id.
        1) GET media metadata → short-lived url + mime.
        2) GET the binary with the same Bearer token.
        Persist to UPLOAD_DIR + mirror to storage + insert files doc."""
        s = await db.settings.find_one({"_id": "global"}) or {}
        access_token = s.get("wa_access_token")
        if not access_token:
            return {"ok": False, "error": "WhatsApp non configuré (token manquant)"}
        if not media_id:
            return {"ok": False, "error": "media_id manquant"}
        meta_url = f"https://graph.facebook.com/{wa_graph_version}/{media_id}"
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                r = await http.get(meta_url, headers={"Authorization": f"Bearer {access_token}"})
                if r.status_code >= 300:
                    return {"ok": False, "error": f"HTTP {r.status_code} sur Graph media metadata"}
                meta = r.json() or {}
                bin_url = meta.get("url")
                mime = (meta.get("mime_type") or "application/octet-stream").split(";", 1)[0].strip()
                declared_size = int(meta.get("file_size") or 0)
                if not bin_url:
                    return {"ok": False, "error": "URL binaire manquante dans la réponse Meta"}
                if declared_size and declared_size > wa_media_max_bytes:
                    return {"ok": False, "error": f"Média trop volumineux ({declared_size} octets)"}
                r2 = await http.get(bin_url, headers={"Authorization": f"Bearer {access_token}"}, timeout=60)
                if r2.status_code >= 300:
                    return {"ok": False, "error": f"HTTP {r2.status_code} lors du téléchargement"}
                raw = r2.content
                if len(raw) > wa_media_max_bytes:
                    return {"ok": False, "error": "Média trop volumineux"}
                ext = _EXT_BY_MIME.get(mime) or mimetypes.guess_extension(mime) or ".bin"
                file_id = uuid_fn()
                stored_name = f"{file_id}{ext}"
                target = upload_dir / stored_name
                try:
                    target.write_bytes(raw)
                except Exception as exc:  # noqa: BLE001
                    return {"ok": False, "error": f"Écriture disque échouée: {exc!r}"}
                display_name = f"wa-inbound{ext}"
                # Mirror to Emergent Object Storage (best-effort)
                storage_path = None
                storage_error = None
                try:
                    from storage import upload_bytes, storage_available
                    if storage_available():
                        storage_path = upload_bytes(f"files/{stored_name}", raw, mime)
                except Exception as exc:  # noqa: BLE001
                    storage_error = str(exc)[:300]
                    logger.warning("[wa_inbound_media] storage mirror failed: %s", storage_error)
                file_doc = {
                    "id": file_id,
                    "filename": display_name,
                    "stored_name": stored_name,
                    "extension": ext.lstrip(".") if ext else None,
                    "content_type": mime,
                    "size": len(raw),
                    "url": f"/api/files/{file_id}{ext}",
                    "uploaded_at": now_fn(),
                    "uploaded_by_id": "_wa_webhook_",
                    "uploaded_by_email": "whatsapp-webhook",
                    "uploaded_from_ip": None,
                    "wa_media_id": media_id,
                    "storage_path": storage_path,
                    "storage_error": storage_error,
                }
                try:
                    await db.files.insert_one(file_doc.copy())
                except Exception:
                    pass
                return {
                    "ok": True,
                    "file_id": file_id,
                    "stored_name": stored_name,
                    "public_url": f"/api/files/{file_id}{ext}",
                    "mime_type": mime,
                    "size_bytes": len(raw),
                    "filename": display_name,
                    "kind": _wa_kind_for_mime(mime),
                }
        except httpx.TimeoutException:
            return {"ok": False, "error": "Timeout"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:300]}

    async def _wa_transcribe_audio_file(path: Path, language: str = "fr") -> Optional[str]:
        """Best-effort Whisper transcription. Returns None on failure."""
        try:
            s = await db.settings.find_one({"_id": "global"}) or {}
            api_key = (s.get("openai_api_key") or "").strip()
            model = (s.get("openai_whisper_model") or "whisper-1").strip()
            if not api_key:
                return None
            if not path.exists() or path.stat().st_size < 200:
                return None
            if path.stat().st_size > 25 * 1024 * 1024:
                return None
            raw = path.read_bytes()
            async with httpx.AsyncClient(timeout=60) as http:
                files = {"file": (path.name, raw, mimetypes.guess_type(path.name)[0] or "audio/ogg")}
                data = {"model": model, "language": (language or "fr")[:5]}
                r = await http.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files=files,
                    data=data,
                )
                if r.status_code >= 300:
                    return None
                payload = r.json()
                return (payload.get("text") or "").strip() or None
        except Exception:
            return None

    async def _wa_compute_reply_window(
        client_scope: Any,
        *,
        contact_id: Optional[str] = None,
        phone_digits: Optional[str] = None,
        now_iso: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolve {inbound_id, inbound_received_at, reply_seconds} for the most
        recent unanswered inbound from the given contact, or None."""
        or_clauses: List[Dict[str, Any]] = []
        if contact_id:
            or_clauses.append({"contact_id": contact_id})
        if phone_digits:
            or_clauses.append({"phone_digits": phone_digits})
        if not or_clauses:
            return None
        scope_q: Dict[str, Any]
        if isinstance(client_scope, (list, set, tuple)):
            scope_list = [s for s in client_scope if s]
            scope_q = {"client_id": {"$in": scope_list}} if scope_list else {}
        elif client_scope:
            scope_q = {"client_id": client_scope}
        else:
            scope_q = {}
        last_msg = await db.whatsapp_messages.find_one(
            {**scope_q, "$or": or_clauses},
            {"_id": 0, "id": 1, "direction": 1, "received_at": 1, "created_at": 1},
            sort=[("created_at", -1)],
        )
        if not last_msg or last_msg.get("direction") != "inbound":
            return None
        inbound_id = last_msg.get("id")
        inbound_at = last_msg.get("received_at") or last_msg.get("created_at")
        if not inbound_at:
            return None
        try:
            ts = datetime.fromisoformat(inbound_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            return None
        now_dt = datetime.now(timezone.utc)
        if now_iso:
            try:
                now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
                if now_dt.tzinfo is None:
                    now_dt = now_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        delta = (now_dt - ts).total_seconds()
        if delta < 0 or delta > 7 * 24 * 3600:
            return None
        return {
            "inbound_id": inbound_id,
            "inbound_received_at": inbound_at,
            "reply_seconds": int(delta),
        }

    async def _wa_last_inbound_iso(
        client_scope: Any,
        *,
        contact_id: Optional[str] = None,
        phone_digits: Optional[str] = None,
    ) -> Optional[str]:
        """Return the ISO timestamp of the most recent inbound WA message in the user's scope."""
        or_clauses: List[Dict[str, Any]] = []
        if contact_id:
            or_clauses.append({"contact_id": contact_id})
        if phone_digits:
            or_clauses.append({"phone_digits": phone_digits})
        if not or_clauses:
            return None
        scope_q: Dict[str, Any]
        if isinstance(client_scope, (list, set, tuple)):
            scope_list = [s for s in client_scope if s]
            scope_q = {"client_id": {"$in": scope_list}} if scope_list else {}
        elif client_scope:
            scope_q = {"client_id": client_scope}
        else:
            scope_q = {}
        q = {**scope_q, "direction": "inbound", "$or": or_clauses}
        doc = await db.whatsapp_messages.find_one(q, {"_id": 0, "received_at": 1, "created_at": 1}, sort=[("created_at", -1)])
        if not doc:
            return None
        return doc.get("received_at") or doc.get("created_at")

    logger.info("[whatsapp_helpers] attached (fix24az-q + fix24az-u underscore-safe + fix24az-v auto-split + 2026-02 tenant smart-comm)")
    return {
        "_wa_send_template": _wa_send_template,
        "_wa_send_text": _wa_send_text,
        "_wa_send_media": _wa_send_media,
        "_wa_download_inbound_media": _wa_download_inbound_media,
        "_wa_transcribe_audio_file": _wa_transcribe_audio_file,
        "_wa_compute_reply_window": _wa_compute_reply_window,
        "_wa_last_inbound_iso": _wa_last_inbound_iso,
        "_wa_neutralize_underscores": _wa_neutralize_underscores,
        "_wa_split_long_text": _wa_split_long_text,
        "_WA_SPLIT_HINT": _WA_SPLIT_HINT,
        "_WA_TEXT_MAX": _WA_TEXT_MAX,
        # 2026-02 fork (P0.5) — Exposé pour permettre aux endpoints d'observer
        # quels credentials sont utilisés + pour les tests de diagnostic.
        "_resolve_wa_credentials": _resolve_wa_credentials,
    }
