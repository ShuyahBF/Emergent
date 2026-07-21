"""Iter43-fix24az-o (2026-07-21) + Iter43-fix24az-p (2026-07-22) — Liluvine Reactions.

Features exposées :
  1. **Fuzzy command matching** : détecte les intentions même avec fautes/
     espaces (`! garde`, `pharmacies de garde`, `garde pharmacie`) et envoie
     un message de correction + exécute la commande.
  2. **Ad reply templates** : liste extensible de messages type + réponses
     préconfigurées (texte + image/vidéo optionnelle). Compte les messages
     reçus et répondus par template.
  3. **Auto-add new contacts** : ajoute automatiquement les nouveaux
     numéros WhatsApp au groupe par défaut configuré dans AdminSettings.
  4. **Native WA media** (fix24az-p) : les templates avec `media_url` envoient
     une pièce jointe native (image/vidéo/audio/doc) au lieu de coller l'URL
     dans le corps du texte — rendu pro dans WhatsApp mobile.
  5. **Contact interactions history** (fix24az-p) : chaque match (template ou
     fuzzy) est journalisé dans `liluvine_contact_interactions` avec
     `phone_digits` pour retrouver la timeline par contact.
  6. **CSV bulk upload** (fix24az-p) : création de multiples templates en une
     seule opération à partir d'un fichier CSV.
  7. **Unmatched message suggestions** (fix24az-p) : collecte les messages
     entrants non-traités, les regroupe par similarité, et propose à l'admin
     de les convertir en nouveaux templates.

Collections Mongo :
  - `liluvine_ad_templates`  { id, tenant_id, name, trigger_text,
    trigger_variations[], response_text, response_media_url,
    response_media_kind, active, received_count, replied_count,
    last_received_at, created_at, updated_at }
  - `liluvine_contact_interactions` { id, phone_digits, contact_id,
    contact_name, tenant_id, kind ("ad_template" | "fuzzy_cmd"),
    template_id, template_name, matched_command, matched_score,
    inbound_text, response_text, response_media_url, response_media_kind,
    wa_message_id, wa_out_message_id, created_at }
  - `liluvine_unmatched_messages` { id, tenant_id, phone_digits,
    body, normalized_body, count, first_seen_at, last_seen_at,
    contact_name, converted_template_id, dismissed }
  - Settings.global :
      liluvine_reactions_config = {
        fuzzy_match_enabled: bool,
        fuzzy_threshold: int (60-95),
        auto_add_new_contacts: bool,
        default_new_contact_group_id: Optional[str],
        correction_prefix_text: str,
        unmatched_capture_enabled: bool (fix24az-p, default true),
      }
"""
from __future__ import annotations

import csv
import io
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
    unmatched_capture_enabled: Optional[bool] = None


class BulkCsvPayload(BaseModel):
    csv: str = Field(..., min_length=1, max_length=200000)
    dry_run: Optional[bool] = False


def attach_liluvine_reactions_routes(
    *,
    api,
    db,
    get_current_user,
    get_current_admin,
    _is_super_admin,
    _resolve_visible_client_ids,
    wa_send_media=None,  # Iter43-fix24az-p — coroutine (to, kind, *, public_url, caption=None)
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
            "unmatched_capture_enabled": bool(cfg.get("unmatched_capture_enabled", True)),
        }

    async def _list_templates(tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q: Dict[str, Any] = {}
        if tenant_id:
            q["$or"] = [{"tenant_id": tenant_id}, {"tenant_id": None}, {"shared": True}]
        out: List[Dict[str, Any]] = []
        async for t in db.liluvine_ad_templates.find(q, {"_id": 0}):
            out.append(t)
        return out

    async def _lookup_contact_by_digits(digits: str) -> Optional[Dict[str, Any]]:
        if not digits:
            return None
        return await db.directory_contacts.find_one(
            {"$or": [
                {"phone_digits": digits},
                {"whatsapp": f"+{digits}"},
                {"phone": f"+{digits}"},
            ]},
            {"_id": 0, "id": 1, "name": 1, "client_id": 1, "phone_digits": 1, "whatsapp": 1, "phone": 1},
        )

    async def _log_interaction(
        *,
        phone_digits: str,
        contact: Optional[Dict[str, Any]],
        tenant_id: Optional[str],
        kind: str,
        template: Optional[Dict[str, Any]],
        matched_command: Optional[str],
        matched_score: Optional[float],
        inbound_text: str,
        response_text: str,
        response_media_url: Optional[str],
        response_media_kind: Optional[str],
        wa_inbound_id: Optional[str],
        wa_out_message_id: Optional[str],
    ) -> None:
        try:
            doc = {
                "id": str(uuid.uuid4()),
                "phone_digits": phone_digits or "",
                "contact_id": (contact or {}).get("id"),
                "contact_name": (contact or {}).get("name"),
                "tenant_id": tenant_id,
                "kind": kind,
                "template_id": (template or {}).get("id"),
                "template_name": (template or {}).get("name") or (template or {}).get("trigger_text"),
                "matched_command": matched_command,
                "matched_score": round(float(matched_score), 1) if matched_score is not None else None,
                "inbound_text": (inbound_text or "")[:2000],
                "response_text": (response_text or "")[:2000],
                "response_media_url": response_media_url,
                "response_media_kind": response_media_kind,
                "wa_inbound_id": wa_inbound_id,
                "wa_out_message_id": wa_out_message_id,
                "created_at": _now_iso(),
            }
            await db.liluvine_contact_interactions.insert_one(doc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[liluvine_reactions] log_interaction failed: %s", exc)

    # -----------------------------------------------------------------
    # ADMIN CONFIG
    # -----------------------------------------------------------------
    @api.get("/admin/liluvine/reactions-config", tags=["Admin — Liluvine Reactions"])
    async def get_config(user: dict = Depends(get_current_admin)):
        cfg = await _get_config()
        client_id = user.get("id")
        groups = []
        async for g in db.contact_groups.find({"client_id": client_id}, {"_id": 0, "id": 1, "name": 1}):
            groups.append(g)
        return {"config": cfg, "contact_groups": groups}

    @api.put("/admin/liluvine/reactions-config", tags=["Admin — Liluvine Reactions"])
    async def put_config(payload: ReactionsConfigUpdate, user: dict = Depends(get_current_admin)):
        set_doc: Dict[str, Any] = {}
        for f in ("fuzzy_match_enabled", "fuzzy_threshold", "auto_add_new_contacts",
                  "default_new_contact_group_id", "correction_prefix_text",
                  "unmatched_capture_enabled"):
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

    # -----------------------------------------------------------------
    # Iter43-fix24az-p — CSV bulk upload
    # -----------------------------------------------------------------
    @api.post("/admin/liluvine/reactions-templates/bulk-csv", tags=["Admin — Liluvine Reactions"])
    async def bulk_upload_csv(payload: BulkCsvPayload, user: dict = Depends(get_current_admin)):
        """Import CSV. Colonnes attendues (première ligne = header, séparateur `,` ou `;`) :
        `name,trigger_text,response_text,trigger_variations,response_media_url,response_media_kind,active`

        - `trigger_variations` : séparé par `|` (pipe).
        - `active` : "true"/"1"/"oui" → True, sinon False. Défaut True.
        - `response_media_url` + `response_media_kind` optionnels.
        """
        raw = payload.csv.strip()
        if not raw:
            raise HTTPException(status_code=400, detail="CSV vide")

        # Détection du séparateur (, ou ;)
        sniff_line = raw.split("\n", 1)[0]
        delim = ";" if sniff_line.count(";") > sniff_line.count(",") else ","

        reader = csv.DictReader(io.StringIO(raw), delimiter=delim)
        expected_cols = {"name", "trigger_text", "response_text"}
        header = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
        missing = expected_cols - set(header.keys())
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Colonnes manquantes : {sorted(missing)}. Attendues au minimum: name, trigger_text, response_text.",
            )

        def _pick(row: Dict[str, str], key: str) -> str:
            src = header.get(key)
            if not src:
                return ""
            return (row.get(src) or "").strip()

        results = {"created": 0, "errors": [], "dry_run": bool(payload.dry_run), "rows": []}
        for idx, row in enumerate(reader, start=2):
            name = _pick(row, "name")
            trigger = _pick(row, "trigger_text")
            response = _pick(row, "response_text")
            if not name or not trigger or not response:
                results["errors"].append({"line": idx, "error": "Champs obligatoires manquants (name/trigger_text/response_text)"})
                continue
            variations_raw = _pick(row, "trigger_variations")
            variations = [v.strip() for v in re.split(r"[|\n]", variations_raw) if v.strip()] if variations_raw else []
            media_url = _pick(row, "response_media_url") or None
            media_kind = _pick(row, "response_media_kind") or None
            active_raw = _pick(row, "active").lower()
            active = True if not active_raw else active_raw in ("true", "1", "oui", "yes", "on")

            doc = {
                "id": str(uuid.uuid4()),
                "tenant_id": user.get("id"),
                "name": name[:120],
                "trigger_text": trigger[:500],
                "trigger_variations": variations[:20],
                "response_text": response[:4000],
                "response_media_url": media_url,
                "response_media_kind": media_kind,
                "active": active,
                "received_count": 0,
                "replied_count": 0,
                "last_received_at": None,
                "created_by": user.get("email"),
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "source": "csv_bulk",
            }
            if payload.dry_run:
                results["rows"].append({"line": idx, "name": name, "trigger_text": trigger[:60]})
            else:
                try:
                    await db.liluvine_ad_templates.insert_one(doc)
                    results["created"] += 1
                    results["rows"].append({"line": idx, "id": doc["id"], "name": name})
                except Exception as exc:  # noqa: BLE001
                    results["errors"].append({"line": idx, "error": str(exc)[:200]})

        return results

    # -----------------------------------------------------------------
    # STATS
    # -----------------------------------------------------------------
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
    # Iter43-fix24az-p — Contact interaction history
    # -----------------------------------------------------------------
    @api.get("/me/contacts/{cid}/liluvine-history", tags=["Contacts — Liluvine"])
    async def contact_history(cid: str, user: dict = Depends(get_current_user)):
        """Timeline des matches Liluvine pour un contact précis."""
        contact = await db.directory_contacts.find_one({"id": cid}, {"_id": 0, "id": 1, "name": 1, "phone_digits": 1, "whatsapp": 1, "phone": 1, "client_id": 1})
        if not contact:
            raise HTTPException(status_code=404, detail="Contact introuvable")
        # Scope check
        try:
            visible = await _resolve_visible_client_ids(user)
        except Exception:  # noqa: BLE001
            visible = [user.get("id")]
        if not _is_super_admin(user) and contact.get("client_id") and contact.get("client_id") not in visible:
            raise HTTPException(status_code=403, detail="Non autorisé")
        digits = contact.get("phone_digits") or re.sub(r"\D", "", contact.get("whatsapp") or contact.get("phone") or "")
        or_clauses: List[Dict[str, Any]] = []
        if digits:
            or_clauses.append({"phone_digits": digits})
        or_clauses.append({"contact_id": cid})
        items: List[Dict[str, Any]] = []
        async for it in db.liluvine_contact_interactions.find(
            {"$or": or_clauses}, {"_id": 0},
        ).sort("created_at", -1).limit(200):
            items.append(it)
        return {"contact_id": cid, "phone_digits": digits, "count": len(items), "items": items}

    # -----------------------------------------------------------------
    # Iter43-fix24az-p — Unmatched messages / suggestions
    # -----------------------------------------------------------------
    @api.get("/admin/liluvine/unmatched-suggestions", tags=["Admin — Liluvine Reactions"])
    async def list_unmatched(user: dict = Depends(get_current_admin), limit: int = Query(30, ge=1, le=100)):
        """Retourne les groupes de messages non-traités (par similarité), triés par volume."""
        items: List[Dict[str, Any]] = []
        async for it in db.liluvine_unmatched_messages.find(
            {"dismissed": {"$ne": True}, "converted_template_id": None},
            {"_id": 0},
        ).sort([("count", -1), ("last_seen_at", -1)]).limit(limit):
            items.append(it)
        # Compteur total
        total = await db.liluvine_unmatched_messages.count_documents({
            "dismissed": {"$ne": True}, "converted_template_id": None,
        })
        return {"total": total, "items": items}

    @api.post("/admin/liluvine/unmatched-suggestions/{sid}/convert", tags=["Admin — Liluvine Reactions"])
    async def convert_suggestion_to_template(
        sid: str,
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        """Convertit une suggestion en template Ad."""
        sugg = await db.liluvine_unmatched_messages.find_one({"id": sid}, {"_id": 0})
        if not sugg:
            raise HTTPException(status_code=404, detail="Suggestion introuvable")
        name = (payload.get("name") or sugg.get("body", "")[:60] or "Nouveau modèle").strip()
        response_text = (payload.get("response_text") or "").strip()
        if not response_text:
            raise HTTPException(status_code=400, detail="response_text requis")
        variations = payload.get("trigger_variations") or []
        media_url = (payload.get("response_media_url") or "").strip() or None
        media_kind = (payload.get("response_media_kind") or "").strip() or None
        doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": user.get("id"),
            "name": name[:120],
            "trigger_text": (sugg.get("body") or "")[:500],
            "trigger_variations": [str(v).strip() for v in variations if str(v).strip()][:20],
            "response_text": response_text[:4000],
            "response_media_url": media_url,
            "response_media_kind": media_kind,
            "active": True,
            "received_count": 0,
            "replied_count": 0,
            "last_received_at": None,
            "created_by": user.get("email"),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "source": "suggestion",
            "from_suggestion_id": sid,
        }
        await db.liluvine_ad_templates.insert_one(doc)
        await db.liluvine_unmatched_messages.update_one(
            {"id": sid},
            {"$set": {"converted_template_id": doc["id"], "converted_at": _now_iso()}},
        )
        return {"ok": True, "template_id": doc["id"]}

    @api.delete("/admin/liluvine/unmatched-suggestions/{sid}", tags=["Admin — Liluvine Reactions"])
    async def dismiss_suggestion(sid: str, user: dict = Depends(get_current_admin)):
        r = await db.liluvine_unmatched_messages.update_one(
            {"id": sid}, {"$set": {"dismissed": True, "dismissed_at": _now_iso()}},
        )
        return {"ok": True, "modified": r.modified_count}

    # -----------------------------------------------------------------
    # HELPERS (utilisés par liluvine_wa_autoreply)
    # -----------------------------------------------------------------
    async def try_reply_ad_template(
        inbound_text: str,
        wa_send_text,
        from_num: str,
        *,
        phone_digits: Optional[str] = None,
        contact: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
        wa_inbound_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Cherche un template qui matche le texte. Si oui, envoie la réponse
        (texte + media éventuel via `_wa_send_media` natif) et incrémente les
        compteurs + journalise l'interaction. Retourne le template matché ou
        None."""
        cfg = await _get_config()
        templates = await _list_templates()
        if not templates:
            return None
        threshold = int(cfg.get("fuzzy_threshold") or 70)
        matched = _match_ad_template(inbound_text, templates, threshold)
        if not matched:
            return None
        # Increment received_count
        await db.liluvine_ad_templates.update_one(
            {"id": matched["id"]},
            {"$inc": {"received_count": 1}, "$set": {"last_received_at": _now_iso()}},
        )
        # Envoi de la réponse
        reply_text = (matched.get("response_text") or "").strip()
        media_url = (matched.get("response_media_url") or "").strip() or None
        media_kind = (matched.get("response_media_kind") or "image").strip() or "image"
        # Iter43-fix24az-p — Native WA media : envoie via _wa_send_media si dispo
        result_text: Dict[str, Any] = {}
        result_media: Dict[str, Any] = {}
        try:
            if media_url and wa_send_media and media_kind in ("image", "video", "audio", "document", "doc"):
                # Envoi natif image/vidéo/doc avec caption
                kind_normalized = "document" if media_kind == "doc" else media_kind
                # Pour audio, WhatsApp ne supporte pas la caption — envoyer texte séparé
                if kind_normalized == "audio":
                    if reply_text:
                        result_text = await wa_send_text(from_num, reply_text)
                    result_media = await wa_send_media(from_num, "audio", public_url=media_url)
                else:
                    # image/video/document : embed la caption
                    result_media = await wa_send_media(
                        from_num, kind_normalized,
                        public_url=media_url,
                        caption=reply_text or None,
                    )
                    # Si l'envoi natif a échoué, fallback texte + URL
                    if not result_media.get("ok"):
                        logger.warning(
                            "[liluvine_reactions] native media failed (%s), fallback to text+url: %s",
                            media_kind, result_media.get("error"),
                        )
                        combined = f"{reply_text}\n\n{media_url}" if reply_text else media_url
                        result_text = await wa_send_text(from_num, combined)
            elif media_url and not wa_send_media:
                # wa_send_media non fourni : legacy fallback
                combined = f"{reply_text}\n\n{media_url}" if reply_text else media_url
                result_text = await wa_send_text(from_num, combined)
            else:
                result_text = await wa_send_text(from_num, reply_text)

            sent_ok = bool(result_media.get("ok") or result_text.get("ok"))
            out_mid = result_media.get("message_id") or result_text.get("message_id")
            if sent_ok:
                await db.liluvine_ad_templates.update_one(
                    {"id": matched["id"]},
                    {"$inc": {"replied_count": 1}},
                )
                # Log l'interaction
                await _log_interaction(
                    phone_digits=phone_digits or "",
                    contact=contact,
                    tenant_id=tenant_id,
                    kind="ad_template",
                    template=matched,
                    matched_command=None,
                    matched_score=None,
                    inbound_text=inbound_text,
                    response_text=reply_text,
                    response_media_url=media_url,
                    response_media_kind=media_kind if media_url else None,
                    wa_inbound_id=wa_inbound_id,
                    wa_out_message_id=out_mid,
                )
            return {"template": matched, "sent": sent_ok, "wa_out_message_id": out_mid}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[liluvine_reactions] send template reply failed: %s", exc)
            return {"template": matched, "sent": False, "error": str(exc)}

    async def try_fuzzy_command_correction(inbound_text: str) -> Optional[Dict[str, Any]]:
        """Si le texte n'a pas de `!` ou est mal formaté, cherche s'il ressemble
        à une commande connue et retourne (cmd, correction_prefix)."""
        cfg = await _get_config()
        if not cfg.get("fuzzy_match_enabled"):
            return None
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

    async def log_fuzzy_correction(
        *,
        phone_digits: str,
        contact: Optional[Dict[str, Any]],
        tenant_id: Optional[str],
        cmd: str,
        score: float,
        inbound_text: str,
        correction_prefix: str,
        wa_inbound_id: Optional[str],
    ) -> None:
        """Journalise un match fuzzy dans la timeline du contact."""
        await _log_interaction(
            phone_digits=phone_digits,
            contact=contact,
            tenant_id=tenant_id,
            kind="fuzzy_cmd",
            template=None,
            matched_command=cmd,
            matched_score=score,
            inbound_text=inbound_text,
            response_text=correction_prefix,
            response_media_url=None,
            response_media_kind=None,
            wa_inbound_id=wa_inbound_id,
            wa_out_message_id=None,
        )

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

    async def record_unmatched_message(
        *,
        inbound_text: str,
        phone_digits: str,
        contact_name: Optional[str],
        tenant_id: Optional[str],
    ) -> None:
        """Iter43-fix24az-p — Capture un message entrant non-traité, dédupliqué
        par texte normalisé. Utile pour proposer de nouveaux templates."""
        cfg = await _get_config()
        if not cfg.get("unmatched_capture_enabled"):
            return
        text = (inbound_text or "").strip()
        if not text or len(text) > 500:
            return
        # Ne pas capturer les commandes explicites `!xxx`
        if text.startswith("!"):
            return
        normalized = _norm(text)
        if len(normalized) < 4:
            return
        # Ne pas capturer les acks numériques (OK, FAIT, 1,2)
        if re.match(r"^(ok|fait|oui|non|merci|thanks|thx)\s*\d*\s*$", normalized):
            return
        try:
            existing = await db.liluvine_unmatched_messages.find_one(
                {"normalized_body": normalized}, {"_id": 0, "id": 1, "count": 1},
            )
            if existing:
                await db.liluvine_unmatched_messages.update_one(
                    {"id": existing["id"]},
                    {
                        "$inc": {"count": 1},
                        "$set": {"last_seen_at": _now_iso(), "contact_name": contact_name},
                    },
                )
            else:
                await db.liluvine_unmatched_messages.insert_one({
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "phone_digits": phone_digits,
                    "contact_name": contact_name,
                    "body": text[:500],
                    "normalized_body": normalized,
                    "count": 1,
                    "first_seen_at": _now_iso(),
                    "last_seen_at": _now_iso(),
                    "converted_template_id": None,
                    "dismissed": False,
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("[liluvine_reactions] record_unmatched failed: %s", exc)

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

    logger.info("[liluvine_reactions] routes mounted (fix24az-p) — media=%s", "on" if wa_send_media else "off")
    return {
        "try_reply_ad_template": try_reply_ad_template,
        "try_fuzzy_command_correction": try_fuzzy_command_correction,
        "log_fuzzy_correction": log_fuzzy_correction,
        "auto_add_new_contact_if_enabled": auto_add_new_contact_if_enabled,
        "build_reactions_summary_reply": build_reactions_summary_reply,
        "record_unmatched_message": record_unmatched_message,
        "lookup_contact_by_digits": _lookup_contact_by_digits,
    }
