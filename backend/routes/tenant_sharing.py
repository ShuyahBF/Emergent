"""Iter43 (2026-02) — Helper centralisé pour le partage tenant.

Permet aux utilisateurs ayant la même « société et rattachement » (champs
`company` + `parent_client_id` sur le profil) de partager leurs documents.

CHOIX UTILISATEUR :
  - Mode de partage paramétrable au niveau TENANT (sur la fiche du client
    parent, alias « tenant ») via `tenant_sharing_mode` (AND ou OR).
      * AND : il faut que les DEUX champs correspondent
      * OR  : un seul des deux suffit (utile pour les multi-succursales)
  - Opt-in à la création : champ `shared_with_tenant: bool` sur chaque doc
  - Édition collaborative optionnelle : `editable_by_tenant: bool`
  - Suppression : réservée à l'auteur (owner_id)

CHAMPS STANDARD À AJOUTER SUR CHAQUE DOCUMENT PARTAGEABLE :
  owner_id (= créateur, sub utilisateur)
  owner_company (snapshot au moment de la création)
  owner_parent_client_id (snapshot au moment de la création)
  shared_with_tenant: bool (par défaut False — l'auteur doit cocher)
  editable_by_tenant: bool (par défaut False)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _norm(v: Optional[str]) -> Optional[str]:
    """Normalise une chaîne pour comparaison (trim + lower-case + None si vide)."""
    if not v:
        return None
    v = str(v).strip()
    if not v:
        return None
    return v.lower()


async def get_tenant_sharing_mode(db, user: Dict[str, Any]) -> str:
    """Retourne 'AND' ou 'OR' selon la fiche du tenant (admin client parent).

    Logique :
      - Si l'utilisateur a un parent_client_id, on lit la fiche du parent
        dans db.users et on récupère `tenant_sharing_mode`.
      - Si l'utilisateur est lui-même un admin client (pas de parent), on
        lit sa propre fiche.
      - Défaut : 'AND' (plus restrictif).
    """
    tenant_id = user.get("parent_client_id") or user.get("id")
    if not tenant_id:
        return "AND"
    doc = await db.users.find_one({"id": tenant_id}, {"tenant_sharing_mode": 1})
    if not doc:
        return "AND"
    mode = str(doc.get("tenant_sharing_mode") or "AND").upper()
    if mode not in ("AND", "OR"):
        mode = "AND"
    return mode


async def resolve_visible_owner_ids(db, user: Dict[str, Any]) -> List[str]:
    """Retourne la liste des `owner_id` dont les documents partagés (`shared_with_tenant=True`)
    sont visibles par `user`.

    Cette liste INCLUT user.id lui-même (un user voit toujours ses propres docs).
    """
    uid = user.get("id")
    if not uid:
        return []
    own_company = _norm(user.get("company"))
    own_parent = user.get("parent_client_id")
    mode = await get_tenant_sharing_mode(db, user)

    # Construit le filtre des « collègues »
    conds = []
    if own_company:
        conds.append({"company": {"$regex": f"^{own_company}$", "$options": "i"}})
    if own_parent:
        conds.append({"parent_client_id": own_parent})

    if not conds:
        # Pas de société ni rattachement → seul son propre user
        return [uid]

    if mode == "AND":
        query = {"$and": conds, "id": {"$ne": uid}}
    else:
        query = {"$or": conds, "id": {"$ne": uid}}

    colleagues = await db.users.find(query, {"id": 1}).to_list(500)
    ids = [uid] + [c["id"] for c in colleagues if c.get("id")]
    return list(dict.fromkeys(ids))  # dedupe en préservant l'ordre


async def build_shared_filter(db, user: Dict[str, Any]) -> Dict[str, Any]:
    """Construit un filtre MongoDB qui retourne :
      - Les docs dont je suis l'auteur (owner_id == moi)
      - + les docs `shared_with_tenant=True` créés par mes collègues
        (selon la règle AND/OR du tenant)

    Exemple d'utilisation :
        flt = await build_shared_filter(db, user)
        cursor = db.client_notes.find(flt, {"_id": 0})
    """
    uid = user.get("id")
    if not uid:
        return {"_id": "__never__"}  # filtre stérile

    visible_ids = await resolve_visible_owner_ids(db, user)
    colleagues_only = [i for i in visible_ids if i != uid]

    base_or = [{"owner_id": uid}]
    if colleagues_only:
        base_or.append({
            "owner_id": {"$in": colleagues_only},
            "shared_with_tenant": True,
        })
    return {"$or": base_or}


def stamp_ownership(doc: Dict[str, Any], user: Dict[str, Any],
                    *, shared: bool = False, editable: bool = False) -> Dict[str, Any]:
    """Stamp les champs ownership standards sur un document avant insert.

    Renvoie le doc enrichi (in-place).
    """
    doc["owner_id"] = user.get("id")
    doc["owner_email"] = user.get("email")
    doc["owner_company"] = (user.get("company") or "").strip() or None
    doc["owner_parent_client_id"] = user.get("parent_client_id")
    doc["shared_with_tenant"] = bool(shared)
    doc["editable_by_tenant"] = bool(editable)
    return doc


def can_edit(doc: Dict[str, Any], user: Dict[str, Any], *, visible_ids: Optional[List[str]] = None) -> bool:
    """Détermine si `user` peut éditer ce document.

    Règles :
      - L'auteur peut toujours.
      - Si `editable_by_tenant=True` ET le document est partagé ET l'auteur
        est dans `visible_ids` (collègue) → édition autorisée.
    """
    uid = user.get("id")
    if not uid:
        return False
    if doc.get("owner_id") == uid:
        return True
    if doc.get("shared_with_tenant") and doc.get("editable_by_tenant"):
        if visible_ids and doc.get("owner_id") in visible_ids:
            return True
    # Admin/superviseur du tenant peuvent toujours éditer
    if user.get("role") in ("admin", "superviseur"):
        if doc.get("owner_parent_client_id") == (user.get("parent_client_id") or user.get("id")):
            return True
    return False


def can_delete(doc: Dict[str, Any], user: Dict[str, Any]) -> bool:
    """Suppression réservée à l'auteur uniquement (choix utilisateur)."""
    uid = user.get("id")
    if not uid:
        return False
    if doc.get("owner_id") == uid:
        return True
    # Admin/superviseur du tenant : peut supprimer (escape hatch)
    if user.get("role") in ("admin", "superviseur"):
        if doc.get("owner_parent_client_id") == (user.get("parent_client_id") or user.get("id")):
            return True
    return False
