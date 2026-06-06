"""Iter41 Phase 3 (2026-02) — Commande WhatsApp publique `!aizenta <produit>`

Renvoie la liste des officines où le produit est disponible (prix moyen,
disponibilité) en interrogeant l'API officines configurée dans AdminSettings.

PUBLIQUE — pas de contrôle de tenant. Quota par numéro de jour (anti-abus).
Casse-insensitive (le regex porte le flag IGNORECASE).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("sawali.officines_wa")

AIZENTA_RE = re.compile(r"^[!/]\s*(aizenta|officine[s]?)\s+(.+?)\s*$", re.IGNORECASE)


def _digits(phone: str) -> str:
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


async def try_handle_aizenta_command(
    db, *, from_phone: str, message_text: str,
) -> Optional[Dict[str, Any]]:
    """Returns None if not an !aizenta command, otherwise {ok, user_reply}."""
    m = AIZENTA_RE.match(message_text or "")
    if not m:
        return None
    product = m.group(2).strip()
    if len(product) < 2:
        return {
            "ok": False, "command": "aizenta",
            "user_reply": "❌ Syntaxe : `!aizenta <nom du produit>` (au moins 2 caractères).",
        }
    phone_digits = _digits(from_phone)
    try:
        from routes.officines import lookup_for_wa_aizenta, format_officines_wa_reply
        data = await lookup_for_wa_aizenta(db, phone_digits=phone_digits, product_name=product)
    except Exception as exc:  # noqa: BLE001
        from fastapi import HTTPException
        if isinstance(exc, HTTPException):
            return {"ok": False, "command": "aizenta", "user_reply": f"❌ {exc.detail}"}
        return {"ok": False, "command": "aizenta", "user_reply": f"❌ Erreur : {str(exc)[:200]}"}
    reply = format_officines_wa_reply(product, data)
    return {"ok": True, "command": "aizenta", "user_reply": reply}
