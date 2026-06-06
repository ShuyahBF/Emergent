"""Iter41 Phase 2 (2026-02) — Commandes WhatsApp VIDAL pour Liluvine.

Détecte et traite les commandes `!vidal*` envoyées via WhatsApp à Liluvine.

Sous-commandes supportées :
  !vidal?                              — Aide (liste des commandes)
  !vidal fiche <nom>                   — Fiche médicament + RCP extrait + AMM
  !vidal amm <nom>                     — Numéro AMM uniquement
  !vidal interactions <id1> <id2>      — Vérifie l'interaction entre 2 produits
  !vidal allergie <substance>          — Liste les médicaments contenant cet allergène

Toutes les commandes respectent :
  - L'accès tenant (`features.vidal_enabled`) du tenant résolu par le téléphone.
  - Le quota journalier (incrémente `vidal_usage_daily`).
  - Le mode (test / production) — peut être forcé par le tenant.

Le routage WhatsApp est branché dans `server.py` (whatsapp_webhook_receive)
AVANT l'auto-reply Liluvine.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("sawali.liluvine_vidal_wa")


HELP_TEXT = (
    "📚 *Commandes VIDAL France disponibles*\n\n"
    "🔹 `!vidal?` — Affiche cette aide\n\n"
    "🔹 `!vidal fiche <nom>`\n"
    "   _Exemple :_ `!vidal fiche doliprane`\n"
    "   Renvoie la fiche médicament (nom, substance, laboratoire, AMM, RCP).\n\n"
    "🔹 `!vidal amm <nom>`\n"
    "   _Exemple :_ `!vidal amm efferalgan`\n"
    "   Renvoie uniquement le numéro AMM.\n\n"
    "🔹 `!vidal interactions <id1> <id2>`\n"
    "   _Exemple :_ `!vidal interactions 11064 12345`\n"
    "   Vérifie l'interaction entre 2 médicaments (IDs VIDAL).\n\n"
    "🔹 `!vidal allergie <substance>`\n"
    "   _Exemple :_ `!vidal allergie pénicilline`\n"
    "   Liste les produits contenant l'allergène.\n\n"
    "_Toutes les requêtes consomment votre quota VIDAL journalier._"
)


def detect_vidal_command(text: str) -> Optional[Dict[str, Any]]:
    """Detect `!vidal*` commands and parse the sub-command + arguments.

    Returns dict {cmd, args} or None when no VIDAL command was found.
    """
    if not text:
        return None
    t = text.strip()
    lower = t.lower()
    if not lower.startswith("!vidal"):
        return None
    if lower in ("!vidal?", "!vidal ?", "!vidal", "!vidal help", "!vidal aide"):
        return {"cmd": "help", "args": []}
    # Remove the leading `!vidal ` then split
    rest = t[len("!vidal"):].strip()
    if not rest:
        return {"cmd": "help", "args": []}
    parts = rest.split(maxsplit=1)
    sub = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if sub in ("fiche", "details", "détails"):
        return {"cmd": "fiche", "args": [arg]} if arg else {"cmd": "missing_arg", "args": ["fiche <nom>"]}
    if sub == "amm":
        return {"cmd": "amm", "args": [arg]} if arg else {"cmd": "missing_arg", "args": ["amm <nom>"]}
    if sub in ("interactions", "interaction"):
        ids = re.findall(r"\d+", arg)
        if len(ids) < 2:
            return {"cmd": "missing_arg", "args": ["interactions <id1> <id2>"]}
        return {"cmd": "interactions", "args": ids[:5]}
    if sub in ("allergie", "allergies", "allergy"):
        return {"cmd": "allergie", "args": [arg]} if arg else {"cmd": "missing_arg", "args": ["allergie <substance>"]}
    return {"cmd": "unknown", "args": [sub]}


def _digits(phone: str) -> str:
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


async def _resolve_user_by_phone(db, phone_digits: str) -> Optional[Dict[str, Any]]:
    """Find a user matching the last 9 digits of the phone (same algo as HR/business RAG)."""
    if not phone_digits or len(phone_digits) < 6:
        return None
    suffix = phone_digits[-9:] if len(phone_digits) >= 9 else phone_digits
    cursor = db.users.find({"phone": {"$regex": f"{re.escape(suffix)}$"}}, {"_id": 0}).limit(5)
    async for u in cursor:
        return u
    return None


def _first_entry(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    entries = (data or {}).get("entries") or (data or {}).get("items") or []
    if entries and isinstance(entries, list):
        return entries[0] if isinstance(entries[0], dict) else None
    return None


def _extract_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(_extract_text(x) for x in node)[:2000]
    if isinstance(node, dict):
        # Common RCP text containers
        for k in ("content", "text", "body", "value"):
            if k in node:
                return _extract_text(node[k])
        return str(node)[:2000]
    return ""


async def _format_fiche(db, vidal_call, cfg, name: str) -> str:
    """Format the `!vidal fiche` reply by calling search + product + RCP + AMM."""
    # 1. Search for the product
    try:
        search = await vidal_call(cfg, "GET", "/products/search", params={"q": name, "filter": "product"})
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erreur lors de la recherche VIDAL : {str(exc)[:200]}"
    first = _first_entry(search)
    if not first:
        return f"❌ Aucun médicament trouvé pour « {name} »."
    pid = first.get("id") or first.get("product_id") or first.get("vidal_id")
    try:
        pid_int = int(pid) if pid else None
    except (TypeError, ValueError):
        pid_int = None
    title = first.get("title") or first.get("name") or name

    # 2. Product details
    detail = None
    if pid_int:
        try:
            detail = await vidal_call(cfg, "GET", f"/product/{pid_int}")
        except Exception:  # noqa: BLE001
            pass

    # 3. RCP excerpt
    rcp_text = ""
    if pid_int:
        try:
            rcp = await vidal_call(cfg, "GET", f"/product/{pid_int}/documents", params={"type": "RCP"})
            rcp_text = _extract_text(rcp)[:600]
        except Exception:  # noqa: BLE001
            rcp_text = "(RCP indisponible)"

    # 4. Local AMM lookup
    amm_block = ""
    try:
        from routes.amm import lookup_amm_for_product
        amm = await lookup_amm_for_product(db, pid_int, title)
        if amm:
            amm_block = f"\n📋 *Numéro AMM* : `{amm.get('amm_number')}`"
            if amm.get("status") != "active":
                amm_block += f" ⚠️ ({amm.get('status')})"
            if amm.get("granted_at"):
                amm_block += f"\n   Délivrée le {amm['granted_at'][:10]}"
        else:
            amm_block = "\n📋 *Numéro AMM* : _non répertorié dans la base régulateur_"
    except Exception:  # noqa: BLE001
        pass

    # 5. Build the reply
    lines = [f"💊 *{title}*"]
    if pid_int:
        lines.append(f"🆔 ID VIDAL : `{pid_int}`")
    inner = (detail or {}).get("product") if detail else None
    for k_label, keys in [
        ("Substance", ("substance", "active_substance", "molecule", "dci")),
        ("Laboratoire", ("laboratory", "company", "manufacturer")),
        ("Classe ATC", ("atc_class", "atc")),
    ]:
        if inner:
            for k in keys:
                if inner.get(k):
                    lines.append(f"⚕️ {k_label} : {inner[k]}")
                    break
    lines.append(amm_block.strip())
    if rcp_text:
        lines.append(f"\n📄 *RCP (extrait)* :\n{rcp_text}…")
    lines.append("\n_Source : VIDAL France via SAWALI_")
    return "\n".join(line for line in lines if line)


async def _format_amm(db, vidal_call, cfg, name: str) -> str:
    """Format the `!vidal amm` short reply — local first, then VIDAL fallback."""
    # Local table first
    try:
        from routes.amm import lookup_amm_for_product
        local = await lookup_amm_for_product(db, None, name)
        if local:
            return (
                f"📋 *{local.get('product_name')}*\n"
                f"AMM : `{local.get('amm_number')}`\n"
                f"Statut : {local.get('status')}\n"
                f"Source : base régulateur SAWALI"
            )
    except Exception:  # noqa: BLE001
        pass
    # Fallback: VIDAL search + check if VIDAL returns the AMM in product details
    try:
        search = await vidal_call(cfg, "GET", "/products/search", params={"q": name, "filter": "product"})
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erreur recherche VIDAL : {str(exc)[:200]}"
    first = _first_entry(search)
    if not first:
        return f"❌ Aucun médicament trouvé pour « {name} »."
    pid = first.get("id") or first.get("product_id")
    try:
        detail = await vidal_call(cfg, "GET", f"/product/{int(pid)}")
    except Exception:  # noqa: BLE001
        detail = None
    amm = (
        (detail or {}).get("amm") or
        ((detail or {}).get("product") or {}).get("amm") or
        first.get("amm")
    )
    if amm:
        return (
            f"📋 *{first.get('title') or name}*\n"
            f"AMM (VIDAL) : `{amm}`\n"
            f"_Numéro non encore validé par un régulateur SAWALI._"
        )
    return f"⚠️ Numéro AMM non trouvé pour « {name} » ni dans VIDAL ni dans la base SAWALI."


async def _format_interactions(vidal_call, cfg, ids: list[str]) -> str:
    """Use VIDAL /alerts/full to check interactions between the IDs."""
    if len(ids) < 2:
        return "❌ Au moins 2 IDs VIDAL nécessaires."
    body = {
        "patient": {},
        "prescriptions": [{"vidal_id": int(i)} for i in ids[:5]],
        "allergies": [],
        "pathologies": [],
    }
    try:
        result = await vidal_call(cfg, "POST", "/alerts/full", body=body)
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erreur analyse interactions : {str(exc)[:200]}"
    alerts = (
        (result or {}).get("alerts")
        or (result or {}).get("interactions")
        or []
    )
    if not alerts:
        return f"✅ Aucune interaction détectée entre les IDs {', '.join(ids)}."
    lines = [f"⚠️ *Interactions détectées* ({len(alerts)} alerte(s))"]
    for a in alerts[:6]:
        sev = a.get("severity") or a.get("level") or "?"
        msg = a.get("message") or a.get("description") or str(a)[:200]
        lines.append(f"• [{sev}] {msg}")
    return "\n".join(lines)


async def _format_allergie(vidal_call, cfg, substance: str) -> str:
    """Search products containing the allergen substance."""
    try:
        data = await vidal_call(cfg, "GET", "/allergies", params={"q": substance})
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erreur recherche allergies : {str(exc)[:200]}"
    entries = (data or {}).get("entries") or (data or {}).get("items") or []
    if not entries:
        return f"❌ Aucune allergie « {substance} » référencée dans VIDAL."
    lines = [f"🚨 *Allergène : {substance}*", f"Produits référencés ({len(entries)} résultats) :"]
    for e in entries[:8]:
        if isinstance(e, dict):
            lines.append(f"• {e.get('title') or e.get('name') or str(e)[:80]}")
    return "\n".join(lines)


async def try_handle_vidal_wa_command(
    db,
    *,
    from_phone: str,
    message_text: str,
) -> Optional[Dict[str, Any]]:
    """Top-level entry point. Returns None if no !vidal command, otherwise
    returns {ok, command, user_reply, ...}."""
    parsed = detect_vidal_command(message_text)
    if not parsed:
        return None

    cmd = parsed["cmd"]
    args = parsed.get("args") or []

    if cmd == "help":
        return {"ok": True, "command": "help", "user_reply": HELP_TEXT}
    if cmd == "missing_arg":
        return {"ok": False, "command": "missing_arg", "user_reply": f"❌ Syntaxe : `!vidal {args[0]}`\n\nTapez `!vidal?` pour l'aide."}
    if cmd == "unknown":
        return {"ok": False, "command": "unknown", "user_reply": f"❌ Sous-commande inconnue : « {args[0] if args else ''} ».\n\nTapez `!vidal?` pour la liste."}

    # All remaining commands need to call VIDAL → check tenant access
    phone_digits = _digits(from_phone)
    user = await _resolve_user_by_phone(db, phone_digits)
    if not user:
        return {
            "ok": False, "command": cmd,
            "user_reply": "❌ Numéro non reconnu. Cette fonction est réservée aux utilisateurs SAWALI enregistrés.",
        }

    from routes.vidal import _ensure_tenant_can_access, _ensure_active, _quota_check_and_increment, _vidal_call
    try:
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False, "command": cmd,
            "user_reply": f"❌ {str(exc)[:200]}",
        }

    # Increment quota (counts toward the same daily budget as web UI)
    try:
        await _quota_check_and_increment(db, user["id"], cfg)
    except Exception:  # noqa: BLE001
        return {
            "ok": False, "command": cmd,
            "user_reply": "❌ Quota VIDAL journalier dépassé pour votre compte.",
        }

    if cmd == "fiche":
        reply = await _format_fiche(db, _vidal_call, cfg, args[0])
    elif cmd == "amm":
        reply = await _format_amm(db, _vidal_call, cfg, args[0])
    elif cmd == "interactions":
        reply = await _format_interactions(_vidal_call, cfg, args)
    elif cmd == "allergie":
        reply = await _format_allergie(_vidal_call, cfg, args[0])
    else:
        return None

    return {"ok": True, "command": cmd, "user_reply": reply, "mode": cfg.get("mode")}
