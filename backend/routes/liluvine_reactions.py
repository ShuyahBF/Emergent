"""Iter43-fix24az-o (2026-07-21) — Liluvine Reactions & Ad Auto-Replies.

3 features en 1 :
  1. **Fuzzy command matching** : détecte les intentions même avec fautes/
     espaces (`! garde`, `pharmacies de garde`, `garde pharmacie`) et envoie
     un message de correction + exécute la commande.
  2. **Ad reply templates** : liste extensible de messages type + réponses
     préconfigurées (texte + image/vidéo optionnelle). Compte les messages
     reçus et répondus par template.
  3. **Auto-add new contacts** : ajoute automatiquement les nouveaux
     numéros WhatsApp au groupe par défaut configuré dans AdminSettings.

Collections Mongo :
  - `liluvine_ad_templates`  { id, tenant_id, name, trigger_text,
    trigger_variations[], response_text, response_media_url,
    response_media_kind, active, received_count, replied_count,
    last_received_at, created_at, updated_at }
  - Settings.global :
      liluvine_reactions_config = {
        fuzzy_match_enabled: bool,
        fuzzy_threshold: int (60-95),
        auto_add_new_contacts: bool,
        default_new_contact_group_id: Optional[str],
      }
"""
from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from fastapi import Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.liluvine_reactions")

# Known public commands + their synonyms (used by fuzzy matcher).
KNOWN_COMMANDS: Dict[str, List[str]] = {
    "garde": [
        "garde", "pharmacie de garde", "pharmacies de garde", "pharmacie garde",
        "pharma garde", "de garde", "quelle pharmacie de garde", "pharmacies de nuit",
    ],
    "meteo": ["meteo", "météo", "temps", "temperature", "température", "prevision", "prévisions"],
    "adresse": ["adresse", "ou etes vous", "où êtes vous", "localisation", "situation", "coordonnees"],
    "contact": ["contact", "contacts", "coordonnees", "coordonnées", "vos contacts"],
    "horaires": ["horaires", "horaire", "heures", "ouverture", "heures d'ouverture", "quand ouvre"],
    "stock": ["stock", "disponibilite", "disponibilité", "dispo", "disponible"],
    "reactions": ["reactions", "réactions", "stats", "statistiques", "compteur"],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(s: str) -> str:
    """Normalise pour la comparaison fuzzy : lowercase, sans accent, sans ponctuation."""
    if not s:
        return ""
    s = s.lower().strip()
    # Enlève les accents
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # Enlève ponctuation courante (garde les lettres, chiffres, espaces)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _similarity(a: str, b: str) -> float:
    """Renvoie le ratio de similarité 0..100 entre 2 chaînes normalisées."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio() * 100.0


def _fuzzy_match_command(text: str, threshold: int) -> Optional[Tuple[str, float]]:
    """Détecte si `text` ressemble à une commande connue. Returns (cmd_key, score)."""
    if not text:
        return None
    normalized = _norm(text)
    if len(normalized) < 3:
        return None
    best_cmd = None
    best_score = 0.0
    for cmd, synonyms in KNOWN_COMMANDS.items():
        for syn in synonyms:
            # Si le synonyme est contenu dans le texte, match direct fort
            if syn in normalized:
                score = 90.0 + len(syn) / max(len(normalized), 1) * 10.0
                if score > best_score:
                    best_cmd, best_score = cmd, score
                continue
            # Sinon, similarité globale
            score = _similarity(text, syn)
            if score > best_score:
                best_cmd, best_score = cmd, score
    if best_score >= threshold:
        return (best_cmd, best_score)
    return None


def _match_ad_template(text: str, templates: List[Dict[str, Any]], threshold: int) -> Optional[Dict[str, Any]]:
    """Match le texte contre les templates configurés. Match exact prioritaire,
    puis fuzzy si `fuzzy_threshold` dépassé."""
    if not text or not templates:
        return None
    normalized_text = _norm(text)
    # Match exact d'abord
    for t in templates:
        if not t.get("active", True):
            continue
        candidates = [t.get("trigger_text") or ""] + (t.get("trigger_variations") or [])
        for cand in candidates:
            if not cand:
                continue
            if _norm(cand) == normalized_text:
                return t
    # Fuzzy match ensuite
    best_t = None
    best_score = 0.0
    for t in templates:
        if not t.get("active", True):
            continue
        candidates = [t.get("trigger_text") or ""] + (t.get("trigger_variations") or [])
        for cand in candidates:
            if not cand:
                continue
            score = _similarity(text, cand)
            if score > best_score:
                best_t, best_score = t, score
    if best_score >= threshold:
        return best_t
    return None


class AdTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    trigger_text: str = Field(..., min_length=1, max_length=500)
    trigger_variations: Optional[List[str]] = Field(default_factory=list)
    response_text: str = Field(..., min_length=1, max_length=4000)
    response_media_url: Optional[str] = None
    response_media_kind: Optional[str] = Field(None, description="image | video | audio | doc")
    active: Optional[bool] = True


class AdTemplateUpdate(BaseModel):
    name: Optional[str] = None
    trigger_text: Optional[str] = None
    trigger_variations: Optional[List[str]] = None
    response_text: Optional[str] = None
    response_media_url: Optional[str] = None
    response_media_kind: Optional[str] = None
    active: Optional[bool] = None


class ReactionsConfigUpdate(BaseModel):
    fuzzy_match_enabled: Optional[bool] = None
    fuzzy_threshold: Optional[int] = Field(None, ge=50, le=95)
    auto_add_new_contacts: Optional[bool] = None
    default_new_contact_group_id: Optional[str] = None
    correction_prefix_text: Optional[str] = Field(None, max_length=500)


def attach_liluvine_reactions_routes(
    *,
    api,
    db,
    get_current_user,
    get_current_admin,
    _is_super_admin,
    _resolve_visible_client_ids,
):
    """Monte les endpoints AdminSettings + expose les helpers pour autoreply."""

    async def _get_config() -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        cfg = s.get("liluvine_reactions_config") or {}
        return {
            "fuzzy_match_enabled": bool(cfg.get("fuzzy_match_enabled", True)),
            "fuzzy_threshold": int(cfg.get("fuzzy_threshold") or 70),
            "auto_add_new_contacts": bool(cfg.get("auto_add_new_contacts", False)),
            "default_new_contact_group_id": cfg.get("default_new_contact_group_id"),
            "correction_prefix_text": (cfg.get("correction_prefix_text") or "").strip() or (
                "Je crois comprendre que vous cherchez « {intent} ». Voici la réponse ; "
                "pour la prochaine fois, envoyez simplement « !{cmd} »."
            ),
        }

    async def _list_templates(tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q: Dict[str, Any] = {}
        if tenant_id:
            q["$or"] = [{"tenant_id": tenant_id}, {"tenant_id": None}, {"shared": True}]
        out: List[Dict[str, Any]] = []
        async for t in db.liluvine_ad_templates.find(q, {"_id": 0}):
            out.append(t)
        return out

    # -----------------------------------------------------------------
    # ADMIN CONFIG
    # -----------------------------------------------------------------
    @api.get("/admin/liluvine/reactions-config", tags=["Admin — Liluvine Reactions"])
    async def get_config(user: dict = Depends(get_current_admin)):
        cfg = await _get_config()
        # Contact groups list (pour le sélecteur)
        s_admin = user
        client_id = user.get("id")
        groups = []
        async for g in db.contact_groups.find({"client_id": client_id}, {"_id": 0, "id": 1, "name": 1}):
            groups.append(g)
        return {"config": cfg, "contact_groups": groups}

    @api.put("/admin/liluvine/reactions-config", tags=["Admin — Liluvine Reactions"])
    async def put_config(payload: ReactionsConfigUpdate, user: dict = Depends(get_current_admin)):
        set_doc: Dict[str, Any] = {}
        for f in ("fuzzy_match_enabled", "fuzzy_threshold", "auto_add_new_contacts",
                  "default_new_contact_group_id", "correction_prefix_text"):
            v = getattr(payload, f, None)
            if v is not None:
                set_doc[f"liluvine_reactions_config.{f}"] = v
        if set_doc:
            set_doc["liluvine_reactions_config.updated_by"] = user.get("email")
            set_doc["liluvine_reactions_config.updated_at"] = _now_iso()
            await db.settings.update_one({"_id": "global"}, {"$set": set_doc}, upsert=True)
        cfg = await _get_config()
        return {"ok": True, "config": cfg}

    # -----------------------------------------------------------------
    # AD TEMPLATES CRUD
    # -----------------------------------------------------------------
    @api.get("/admin/liluvine/reactions-templates", tags=["Admin — Liluvine Reactions"])
    async def list_templates(user: dict = Depends(get_current_admin)):
        return {"templates": await _list_templates()}

    @api.post("/admin/liluvine/reactions-templates", tags=["Admin — Liluvine Reactions"])
    async def create_template(payload: AdTemplateCreate, user: dict = Depends(get_current_admin)):
        doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": user.get("id"),
            "name": payload.name.strip(),
            "trigger_text": payload.trigger_text.strip(),
            "trigger_variations": [(v or "").strip() for v in (payload.trigger_variations or []) if (v or "").strip()],
            "response_text": payload.response_text.strip(),
            "response_media_url": (payload.response_media_url or "").strip() or None,
            "response_media_kind": (payload.response_media_kind or "").strip() or None,
            "active": bool(payload.active) if payload.active is not None else True,
            "received_count": 0,
            "replied_count": 0,
            "last_received_at": None,
            "created_by": user.get("email"),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await db.liluvine_ad_templates.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @api.put("/admin/liluvine/reactions-templates/{tid}", tags=["Admin — Liluvine Reactions"])
    async def update_template(tid: str, payload: AdTemplateUpdate, user: dict = Depends(get_current_admin)):
        existing = await db.liluvine_ad_templates.find_one({"id": tid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Template introuvable")
        set_doc: Dict[str, Any] = {"updated_at": _now_iso()}
        for f in ("name", "trigger_text", "response_text", "response_media_url", "response_media_kind"):
            v = getattr(payload, f, None)
            if v is not None:
                set_doc[f] = (v or "").strip() or None
        if payload.trigger_variations is not None:
            set_doc["trigger_variations"] = [(v or "").strip() for v in payload.trigger_variations if (v or "").strip()]
        if payload.active is not None:
            set_doc["active"] = bool(payload.active)
        await db.liluvine_ad_templates.update_one({"id": tid}, {"$set": set_doc})
        return await db.liluvine_ad_templates.find_one({"id": tid}, {"_id": 0})

    @api.delete("/admin/liluvine/reactions-templates/{tid}", tags=["Admin — Liluvine Reactions"])
    async def delete_template(tid: str, user: dict = Depends(get_current_admin)):
        r = await db.liluvine_ad_templates.delete_one({"id": tid})
        return {"ok": True, "deleted": r.deleted_count}

    @api.get("/admin/liluvine/reactions-stats", tags=["Admin — Liluvine Reactions"])
    async def get_stats(user: dict = Depends(get_current_admin)):
        templates = await _list_templates()
        stats = []
        totals = {"received": 0, "replied": 0}
        for t in templates:
            r = int(t.get("received_count") or 0)
            s = int(t.get("replied_count") or 0)
            stats.append({
                "id": t.get("id"),
                "name": t.get("name"),
                "trigger_text": t.get("trigger_text"),
                "received": r,
                "replied": s,
                "reply_rate": round((s / r * 100.0) if r else 0.0, 1),
                "last_received_at": t.get("last_received_at"),
                "active": t.get("active", True),
            })
        totals["received"] = sum(s["received"] for s in stats)
        totals["replied"] = sum(s["replied"] for s in stats)
        totals["reply_rate"] = round((totals["replied"] / totals["received"] * 100.0) if totals["received"] else 0.0, 1)
        return {"templates": stats, "totals": totals}

    # -----------------------------------------------------------------
    # HELPERS (utilisés par liluvine_wa_autoreply)
    # -----------------------------------------------------------------
    async def try_reply_ad_template(inbound_text: str, wa_send_text, from_num: str) -> Optional[Dict[str, Any]]:
        """Cherche un template qui matche le texte. Si oui, envoie la réponse
        (texte + media éventuel) et incrémente les compteurs. Retourne le
        template matché ou None."""
        cfg = await _get_config()
        templates = await _list_templates()
        if not templates:
            return None
        threshold = int(cfg.get("fuzzy_threshold") or 70)
        matched = _match_ad_template(inbound_text, templates, threshold)
        if not matched:
            return None
        # Increment received_count (le message est match, on ne sait pas encore s'il aura une réponse valide)
        await db.liluvine_ad_templates.update_one(
            {"id": matched["id"]},
            {"$inc": {"received_count": 1}, "$set": {"last_received_at": _now_iso()}},
        )
        # Send response
        try:
            reply_text = matched.get("response_text") or ""
            media_url = matched.get("response_media_url")
            media_kind = matched.get("response_media_kind") or "image"
            result = None
            if media_url:
                # For now we send the text with media_url appended (real media send would use _wa_send_media)
                combined = f"{reply_text}\n\n{media_url}" if reply_text else media_url
                result = await wa_send_text(from_num, combined)
            else:
                result = await wa_send_text(from_num, reply_text)
            if result and result.get("ok"):
                await db.liluvine_ad_templates.update_one(
                    {"id": matched["id"]},
                    {"$inc": {"replied_count": 1}},
                )
            return {"template": matched, "sent": bool(result and result.get("ok"))}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[liluvine_reactions] send template reply failed: %s", exc)
            return {"template": matched, "sent": False, "error": str(exc)}

    async def try_fuzzy_command_correction(inbound_text: str) -> Optional[Dict[str, Any]]:
        """Si le texte n'a pas de `!` ou est mal formaté, cherche s'il ressemble
        à une commande connue et retourne (cmd, correction_prefix)."""
        cfg = await _get_config()
        if not cfg.get("fuzzy_match_enabled"):
            return None
        # Ignore les vrais `!commandes` bien formées (déjà traitées par autoreply)
        text = (inbound_text or "").strip()
        if re.match(r"^!\s*\w", text):
            return None
        match = _fuzzy_match_command(text, int(cfg.get("fuzzy_threshold") or 70))
        if not match:
            return None
        cmd, score = match
        prefix_tpl = cfg.get("correction_prefix_text") or ""
        try:
            prefix = prefix_tpl.format(intent=text[:60], cmd=cmd)
        except Exception:  # noqa: BLE001
            prefix = f"Je crois comprendre « {text[:60]} ». Envoyez « !{cmd} » pour un accès direct."
        return {"cmd": cmd, "score": score, "correction_prefix": prefix}

    async def auto_add_new_contact_if_enabled(
        digits: str,
        wa_profile_name: Optional[str],
        tenant_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Si `auto_add_new_contacts` est ON et le numéro n'existe pas encore,
        crée un contact et l'ajoute au groupe par défaut configuré."""
        cfg = await _get_config()
        if not cfg.get("auto_add_new_contacts"):
            return None
        # Vérifie si déjà existant
        existing = await db.directory_contacts.find_one(
            {"$or": [
                {"whatsapp": f"+{digits}"},
                {"phone": f"+{digits}"},
                {"phone_digits": digits},
            ]},
            {"_id": 0, "id": 1},
        )
        if existing:
            return None
        default_group_id = cfg.get("default_new_contact_group_id")
        group_ids = [default_group_id] if default_group_id else []
        new_contact = {
            "id": str(uuid.uuid4()),
            "client_id": tenant_id,
            "name": wa_profile_name or f"+{digits}",
            "phone": f"+{digits}",
            "whatsapp": f"+{digits}",
            "phone_digits": digits,
            "wa_profile_name": wa_profile_name,
            "tags": ["auto-liluvine"],
            "group_ids": group_ids,
            "shared": False,
            "source": "liluvine_auto",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        try:
            await db.directory_contacts.insert_one(new_contact.copy())
            logger.info("[liluvine_reactions] auto-added contact +%s -> group=%s", digits, default_group_id or "-")
            return {"id": new_contact["id"], "group_id": default_group_id}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[liluvine_reactions] auto-add contact failed: %s", exc)
            return None

    async def build_reactions_summary_reply() -> str:
        """Renvoie le message texte pour `!reactions` — compteurs par template."""
        templates = await _list_templates()
        if not templates:
            return "🤖 Aucun modèle Liluvine configuré pour l'instant. Ajoutez-en depuis /admin/settings → Liluvine Reactions."
        lines = ["📊 *Statistiques Liluvine Reactions* :", ""]
        total_r = total_s = 0
        for t in sorted(templates, key=lambda x: -(x.get("received_count") or 0)):
            r = int(t.get("received_count") or 0)
            s = int(t.get("replied_count") or 0)
            total_r += r
            total_s += s
            active = "✓" if t.get("active", True) else "✗"
            lines.append(f"{active} *{t.get('name') or t.get('trigger_text','')[:40]}* : {s} répondus / {r} reçus")
        rate = f"{(total_s/total_r*100):.1f}%" if total_r else "n/a"
        lines.append("")
        lines.append(f"*TOTAL* : {total_s}/{total_r} messages ({rate})")
        return "\n".join(lines)

    logger.info("[liluvine_reactions] routes mounted under /api/admin/liluvine/reactions-*")
    return {
        "try_reply_ad_template": try_reply_ad_template,
        "try_fuzzy_command_correction": try_fuzzy_command_correction,
        "auto_add_new_contact_if_enabled": auto_add_new_contact_if_enabled,
        "build_reactions_summary_reply": build_reactions_summary_reply,
    }
