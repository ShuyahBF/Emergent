"""Actions VIDAL riches — `!doc` / `!rech` : documentation + DCI + équivalences.

Contexte métier (demande explicite du client) :
  - `!doc` et `!rech` sont deux synonymes de la MÊME commande (ex: `!doc
    doliprane 1000` ou `!rech doliprane 1000`) — recherche la documentation
    d'un produit et surtout son principe actif (DCI). Prescription par DCI
    courante au Burkina Faso.
  - Si le principe actif n'est pas trouvé tel quel (nom de marque inconnu),
    on retombe sur une recherche par DCI et on affiche tous les produits
    équivalents (même composition en principes actifs ET dosages).
  - Sur WhatsApp, un bouton interactif "Équivalences" est proposé en retour
    quand des équivalents existent (voir `liluvine_wa_autoreply.py` +
    `whatsapp_helpers._wa_send_interactive_button` + le handler du clic dans
    `server.py`, branche `mtype == "interactive"`).
  - Deux niveaux d'accès par contact (nouveau champ dédié `vidal_riche` sur
    `directory_contacts`, PAS une réutilisation des tags existants) :
      * riche (vidal_riche=true)  → requêtes illimitées (ex: médecins abonnés)
      * simple (vidal_riche=false/absent) → quota quotidien non cumulatif,
        remis à 0 chaque jour (ex: infirmiers, étudiants) — valeur par défaut
        10/jour, réglable par l'admin.

Équivalence VIDAL : le "VMP" (Virtual Medicinal Product) est le regroupement
officiel VIDAL par DCI + dosage + forme galénique + voie d'administration —
c'est le même mécanisme que celui utilisé côté `/portal/vidal` (bouton "Voir
les équivalences" sur la fiche produit), confirmé par tests réels sur l'API
VIDAL comme plus fiable et moins coûteux qu'un rapprochement manuel par nom
de molécule.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends
from pydantic import BaseModel

logger = logging.getLogger("sawali.vidal.riche")

DEFAULT_DAILY_QUOTA_SIMPLE = 10
# `!doc` et `!rech` sont acceptés comme synonymes stricts de la même commande.
RICHE_COMMAND_ALIASES = ("doc", "rech")

# Mêmes regex que `_format_vidal_data_for_wa` (liluvine_wa_autoreply.py) pour
# rester cohérent avec le seul autre endroit du code qui parse déjà l'Atom/XML
# VIDAL côté WhatsApp — pas besoin d'un parseur DOM complet.
_ENTRY_RE = re.compile(r"<entry\b[^>]*>(.*?)</entry>", re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)
_ID_RE = re.compile(r"<(?:[a-z][a-z0-9]*:)?id>\s*(\d+)\s*</(?:[a-z][a-z0-9]*:)?id>", re.IGNORECASE)
_ATOM_ID_RE = re.compile(r"<id[^>]*>([^<]+)</id>", re.IGNORECASE)
# VMP = regroupement VIDAL par DCI+dosage+forme+voie, porté en attribut sur
# l'entrée produit (ex: <vidal:vmp vidalId="12345"/>).
_VMP_RE = re.compile(r'<(?:[a-z][a-z0-9]*:)?vmp\b[^>]*\bvidalId="(\d+)"', re.IGNORECASE)


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _parse_atom_entries(raw: Optional[str]) -> List[Dict[str, Any]]:
    """Extrait {title, vidal_id, vmp_id} de chaque `<entry>` d'une réponse Atom
    VIDAL. Best-effort par regex — dégrade proprement (listes vides) si le
    format XML diffère, plutôt que de lever une exception."""
    items: List[Dict[str, Any]] = []
    if not isinstance(raw, str) or "<entry" not in raw:
        return items
    for block in _ENTRY_RE.findall(raw):
        title_m = _TITLE_RE.search(block)
        title = (title_m.group(1) if title_m else "").strip()
        if not title:
            continue
        id_m = _ID_RE.search(block)
        if not id_m:
            atom_id_m = _ATOM_ID_RE.search(block)
            if atom_id_m:
                id_m = re.search(r"(\d+)\s*$", atom_id_m.group(1))
        vmp_m = _VMP_RE.search(block)
        items.append({
            "title": title,
            "vidal_id": id_m.group(1) if id_m else None,
            "vmp_id": vmp_m.group(1) if vmp_m else None,
        })
    return items


# ---------------------------------------------------------------------------
# Réglages admin (rubrique "Actions VIDAL riches")
# ---------------------------------------------------------------------------
class VidalRicheSettingsPayload(BaseModel):
    enabled: Optional[bool] = None
    daily_quota_simple: Optional[int] = None


async def get_riche_settings(db) -> Dict[str, Any]:
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "vidal_riche_settings": 1}) or {}
    settings = s.get("vidal_riche_settings") or {}
    return {
        "enabled": bool(settings.get("enabled", True)),
        "daily_quota_simple": int(settings.get("daily_quota_simple") or DEFAULT_DAILY_QUOTA_SIMPLE),
    }


async def save_riche_settings(db, enabled: Optional[bool], daily_quota_simple: Optional[int]) -> Dict[str, Any]:
    current = await get_riche_settings(db)
    if enabled is not None:
        current["enabled"] = bool(enabled)
    if daily_quota_simple is not None:
        current["daily_quota_simple"] = max(int(daily_quota_simple), 0)
    await db.settings.update_one(
        {"_id": "global"}, {"$set": {"vidal_riche_settings": current}}, upsert=True,
    )
    return current


def contact_is_riche(contact: Optional[Dict[str, Any]]) -> bool:
    """Niveau VIDAL riche du contact (nouveau champ dédié `vidal_riche`,
    distinct du tag "Abonné VIDAL" existant). Absent/False = accès simple
    (quota) — c'est le défaut le plus sûr tant que l'admin n'a pas activé
    explicitement l'accès riche pour ce contact."""
    return bool((contact or {}).get("vidal_riche"))


async def check_and_increment_simple_quota(db, phone_digits: str, daily_quota: int) -> Dict[str, Any]:
    """Quota journalier NON cumulatif : remis à 0 chaque jour (aucun report
    des requêtes non utilisées la veille). Même schéma que
    `vidal._quota_check_and_increment` mais dans sa propre collection pour ne
    pas interférer avec le quota VIDAL "portail" existant."""
    if daily_quota <= 0:  # 0 = illimité, réglage admin
        return {"blocked": False, "used": 0, "limit": 0}
    today = _today_str()
    doc = await db.vidal_riche_usage_daily.find_one_and_update(
        {"phone_digits": phone_digits, "day": today},
        {"$inc": {"count": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        upsert=True,
        return_document=True,
    ) or {}
    used = int(doc.get("count") or 1)
    return {"blocked": used > daily_quota, "used": used, "limit": daily_quota}


# ---------------------------------------------------------------------------
# Recherche riche (DCI-aware) + équivalences
# ---------------------------------------------------------------------------
async def _vmp_equivalents_raw(vidal_call_fn, cfg, vmp_id: str) -> str:
    data = await vidal_call_fn(cfg, "GET", f"/vmp/{vmp_id}/products", params={"page-size": 20})
    return (data or {}).get("raw") or ""


async def build_doc_reply(db, vidal_call_fn, cfg, query: str) -> Dict[str, Any]:
    """`!doc` / `!rech` <nom> — fiche + principe actif (DCI). Si le nom exact
    n'est pas trouvé, retombe sur une recherche par DCI (VMP) et propose les
    équivalents.

    Retourne {text, vmp_id, product_id} — `vmp_id` n'est renseigné que quand
    des équivalents existent réellement (déclenche le bouton WA
    "Équivalences" côté appelant).
    """
    query_clean = (query or "").strip()
    if not query_clean:
        return {
            "text": "Précisez un nom de médicament après la commande, ex : `!doc doliprane 1000`.",
            "vmp_id": None, "product_id": None,
        }

    search_data = await vidal_call_fn(cfg, "GET", "/products", params={"q": query_clean})
    entries = _parse_atom_entries((search_data or {}).get("raw"))

    if entries:
        # Trouvé par nom de marque — fiche + DCI du premier résultat.
        best = entries[0]
        product_id = best.get("vidal_id")
        vmp_id = best.get("vmp_id")
        dci_line = ""
        if product_id:
            mol_data = await vidal_call_fn(cfg, "GET", f"/product/{product_id}/molecules")
            dci_names = re.findall(r"<title[^>]*>([^<]+)</title>", (mol_data or {}).get("raw") or "")
            if dci_names:
                dci_line = "\n💊 *Principe(s) actif(s) (DCI)* : " + ", ".join(dci_names[:4])
        text = f"📋 *{best.get('title')}*" + (f" (*{product_id}*)" if product_id else "") + dci_line
        if vmp_id:
            text += "\n\n_Des produits équivalents (même DCI + dosage) sont disponibles — bouton ci-dessous._"
        return {"text": text, "vmp_id": vmp_id, "product_id": product_id}

    # Rien trouvé par marque → on tente une recherche par DCI (filter=vmp,
    # déjà un filtre reconnu par ce backend — voir routes/vidal.py::search).
    dci_search = await vidal_call_fn(cfg, "GET", "/products", params={"q": query_clean, "filter": "vmp"})
    vmp_entries = _parse_atom_entries((dci_search or {}).get("raw"))
    if not vmp_entries:
        return {
            "text": f"❌ Aucun résultat VIDAL pour « {query_clean} » (ni par nom, ni par principe actif).",
            "vmp_id": None, "product_id": None,
        }
    vmp = vmp_entries[0]
    vmp_id = vmp.get("vidal_id")
    equiv_entries = _parse_atom_entries(await _vmp_equivalents_raw(vidal_call_fn, cfg, vmp_id)) if vmp_id else []
    if not equiv_entries:
        return {
            "text": f"🔎 Principe actif reconnu : *{vmp.get('title')}* — mais aucun produit équivalent listé par VIDAL pour le moment.",
            "vmp_id": None, "product_id": None,
        }
    lines = [
        f"🔎 *{query_clean}* non trouvé tel quel — principe actif reconnu : *{vmp.get('title')}*",
        "", "Produits équivalents (même DCI + dosage) :",
    ]
    for i, e in enumerate(equiv_entries[:8], 1):
        code = f" (*{e['vidal_id']}*)" if e.get("vidal_id") else ""
        lines.append(f"{i}. {e['title']}{code}")
    return {"text": "\n".join(lines), "vmp_id": None, "product_id": None}


async def build_equivalents_reply(vidal_call_fn, cfg, vmp_id: str, exclude_product_id: Optional[str] = None) -> str:
    """Formate la liste des produits équivalents — utilisé pour la réponse au
    clic sur le bouton WhatsApp "Équivalences"."""
    entries = _parse_atom_entries(await _vmp_equivalents_raw(vidal_call_fn, cfg, vmp_id))
    if exclude_product_id:
        entries = [e for e in entries if e.get("vidal_id") != exclude_product_id]
    if not entries:
        return "Aucun produit équivalent trouvé pour ce principe actif."
    lines = ["💊 *Produits équivalents (même DCI + dosage)*", ""]
    for i, e in enumerate(entries[:8], 1):
        code = f" (*{e['vidal_id']}*)" if e.get("vidal_id") else ""
        lines.append(f"{i}. {e['title']}{code}")
    return "\n".join(lines)


async def build_riche_command_reply(
    db, command_args: str, phone_digits: str, contact: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Point d'entrée appelé par `liluvine_wa_autoreply.py` pour `!doc`/`!rech`.

    Retourne None si la rubrique "Actions VIDAL riches" est désactivée par
    l'admin (l'appelant peut alors laisser le message suivre son cours
    normal), sinon un dict `{text, action_id, denied, vmp_id, product_id}`
    au même format que `_build_vidal_reply` (actions VIDAL génériques).
    """
    settings = await get_riche_settings(db)
    if not settings["enabled"]:
        return None
    try:
        from routes.vidal import _load_config, _ensure_active
    except Exception:  # noqa: BLE001
        logger.exception("[vidal_riche] failed to import VIDAL core module")
        return None
    try:
        cfg = await _load_config(db)
        _ensure_active(cfg)
    except Exception as exc:  # noqa: BLE001
        return {
            "text": f"⚠️ Module VIDAL indisponible actuellement.\n_Erreur : {str(exc)[:120]}_",
            "action_id": "doc_rech", "denied": False, "vmp_id": None, "product_id": None,
        }

    if not contact_is_riche(contact):
        quota = await check_and_increment_simple_quota(db, phone_digits, settings["daily_quota_simple"])
        if quota["blocked"]:
            return {
                "text": (
                    f"🔒 Quota quotidien atteint ({quota['limit']} recherches/jour en accès simple).\n"
                    "Réessayez demain, ou demandez le passage en accès VIDAL riche (illimité)."
                ),
                "action_id": "doc_rech", "denied": True, "vmp_id": None, "product_id": None,
            }

    from routes.vidal import _vidal_call
    result = await build_doc_reply(db, _vidal_call, cfg, command_args)
    result["action_id"] = "doc_rech"
    result["denied"] = False
    return result


# ---------------------------------------------------------------------------
# Route attachment
# ---------------------------------------------------------------------------
def attach_vidal_riche_routes(api, db, get_current_admin):
    """Mount `/api/admin/vidal/riche/settings` (GET + PUT)."""

    @api.get("/admin/vidal/riche/settings", tags=["Admin — VIDAL"])
    async def get_settings(_: dict = Depends(get_current_admin)):
        return await get_riche_settings(db)

    @api.put("/admin/vidal/riche/settings", tags=["Admin — VIDAL"])
    async def set_settings(payload: VidalRicheSettingsPayload = Body(...), _: dict = Depends(get_current_admin)):
        return await save_riche_settings(db, payload.enabled, payload.daily_quota_simple)

    logger.info("[vidal_riche] routes mounted under /api/admin/vidal/riche/*")
