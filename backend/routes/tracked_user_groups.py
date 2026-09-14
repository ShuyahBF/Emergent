"""Rattachement automatique des utilisateurs suivis "Médecin"/"Pharmacien" à un
groupe de contacts de même nom (demande explicite de l'utilisateur) — pour
faciliter l'envoi de messages WhatsApp/SMS groupés à tous les médecins ou
tous les pharmaciens d'un client, sans étape manuelle.

Réutilise le modèle existant `contact_groups`/`contacts` (voir
routes/contact_groups.py, routes/liluvine_wa_requests.py::import_wa_numbers
pour le même pattern find-or-create groupe + contact). L'admin crée/gère les
groupes lui-même depuis "Groupes de contacts" — ce module se contente d'y
ajouter automatiquement le bon contact quand un utilisateur suivi est créé
ou passe en rôle Médecin/Pharmacien.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("sawali.tracked_user_groups")

# Rôles utilisateur suivi synchronisés vers un groupe de contacts du même nom.
AUTO_GROUP_ROLES = {"Médecin", "Pharmacien"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digits(phone: Optional[str]) -> str:
    return re.sub(r"[^0-9]", "", phone or "")


async def sync_tracked_role_group(db, tu_doc: Dict[str, Any]) -> None:
    """Ajoute (ou crée) le contact correspondant au groupe nommé d'après le
    rôle de l'utilisateur suivi. No-op silencieux si le rôle n'est pas
    concerné, ou si aucun numéro de téléphone n'est disponible — jamais
    bloquant pour la création/mise à jour de l'utilisateur suivi elle-même.
    """
    role = (tu_doc.get("role") or "").strip()
    if role not in AUTO_GROUP_ROLES:
        return
    client_id = tu_doc.get("client_id")
    phone_digits = _digits(tu_doc.get("whatsapp_number") or tu_doc.get("phone"))
    if not client_id or len(phone_digits) < 6:
        return

    try:
        group = await db.contact_groups.find_one({"client_id": client_id, "name": role}, {"_id": 0})
        if not group:
            group = {
                "id": str(uuid.uuid4()), "client_id": client_id, "name": role,
                "created_at": _now_iso(), "created_by": "system:tracked_user_role",
                "auto_generated": True,
            }
            await db.contact_groups.insert_one(group.copy())
        gid = group["id"]

        contact = await db.contacts.find_one(
            {"client_id": client_id, "$or": [{"phone_digits": phone_digits}, {"whatsapp_digits": phone_digits}]},
            {"_id": 0},
        )
        if contact:
            group_ids = contact.get("group_ids") or []
            if gid not in group_ids:
                group_ids.append(gid)
                await db.contacts.update_one(
                    {"id": contact["id"]},
                    {"$set": {"group_ids": group_ids, "updated_at": _now_iso()}},
                )
        else:
            await db.contacts.insert_one({
                "id": str(uuid.uuid4()), "client_id": client_id,
                "name": tu_doc.get("name") or f"+{phone_digits}",
                "phone": f"+{phone_digits}", "phone_digits": phone_digits,
                "whatsapp": f"+{phone_digits}", "whatsapp_digits": phone_digits,
                "email": tu_doc.get("email"), "company": tu_doc.get("company"),
                "group_ids": [gid],
                "source": "tracked_user_role_sync",
                "created_at": _now_iso(), "created_by": "system:tracked_user_role",
            })
    except Exception:  # noqa: BLE001 — jamais bloquant pour la création/MAJ de l'utilisateur suivi
        logger.exception("[tracked_user_groups] sync failed for tracked_user id=%s", tu_doc.get("id"))
