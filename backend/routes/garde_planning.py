"""Iter43-fix22 (2026-06) — Planning hebdomadaire des Groupes de Garde.

Architecture :
  - Collection MongoDB `garde_planning` : un document par {year, week_number}
    avec le groupe_garde affecté et un flag `manual_override`.
  - Génération séquentielle : prend le 1er groupe en garde semaine 1 +
    nombre de groupes existants → cycle G1→G2→…→GN→G1.
  - Override manuel : l'admin peut forcer une semaine sur un autre groupe
    (échange, garde spéciale fête, etc.).

Endpoints :
  GET  /api/admin/officines-registry/garde-planning?year=YYYY
  POST /api/admin/officines-registry/garde-planning/generate
       Body: { year, start_group, num_groups (opt, défaut=auto) }
  PUT  /api/admin/officines-registry/garde-planning/{year}/{week}
       Body: { groupe_garde: int }
  DELETE /api/admin/officines-registry/garde-planning/{year}/{week}
       Réinitialise une semaine au calcul séquentiel automatique.

  Endpoint public (utilisé par `!Garde` plus tard) :
  GET  /api/public/officines/garde/current
       → renvoie la semaine ISO actuelle + groupe + liste des officines de ce groupe.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Query

logger = logging.getLogger("sawali.garde_planning")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_week_year(d: date) -> tuple[int, int]:
    """ISO 8601 week year + week number (1-53)."""
    iso = d.isocalendar()
    return iso[0], iso[1]


def setup_garde_planning_routes(*, db, api, get_current_admin):
    """Wire les routes garde planning. À insérer AVANT les catch-all /{officine_id}."""

    @api.get("/admin/officines-registry/garde-planning", tags=["Admin — Officines Registry"])
    async def list_garde_planning(
        year: int = Query(..., ge=2024, le=2100),
        _: dict = Depends(get_current_admin),
    ):
        """Retourne le planning complet pour une année + la liste des groupes
        existants (officines comptés par groupe)."""
        # Toutes les semaines avec entrée existante
        existing: Dict[int, Dict[str, Any]] = {}
        async for d in db.garde_planning.find({"year": year}, {"_id": 0}):
            existing[d["week_number"]] = d
        # Récupère la liste des groupes
        groups: Dict[int, int] = {}
        async for o in db.officines.find(
            {"groupe_garde": {"$nin": [None, ""]}},
            {"groupe_garde": 1, "_id": 0},
        ):
            try:
                g = int(o["groupe_garde"])
                groups[g] = groups.get(g, 0) + 1
            except (TypeError, ValueError):
                continue
        sorted_groups = sorted(groups.keys())
        # Combien de semaines dans l'année ISO ?
        last_week = date(year, 12, 28).isocalendar()[1]  # toujours dans la dernière semaine
        # Pour chaque semaine, on calcule l'auto (si pas d'override)
        # On va déterminer start_group via la première semaine si présente, sinon = min(groups)
        first = existing.get(1)
        auto_start = first["groupe_garde"] if (first and first.get("auto_generated")) else (
            sorted_groups[0] if sorted_groups else 1
        )
        weeks: List[Dict[str, Any]] = []
        for w in range(1, last_week + 1):
            entry = existing.get(w)
            # Date du lundi de cette semaine ISO
            try:
                monday = date.fromisocalendar(year, w, 1)
                sunday = date.fromisocalendar(year, w, 7)
            except ValueError:
                continue
            if entry:
                weeks.append({
                    "year": year,
                    "week_number": w,
                    "groupe_garde": entry.get("groupe_garde"),
                    "manual_override": bool(entry.get("manual_override")),
                    "auto_generated": bool(entry.get("auto_generated")),
                    "monday": monday.isoformat(),
                    "sunday": sunday.isoformat(),
                    "updated_by": entry.get("updated_by"),
                    "updated_at": entry.get("updated_at").isoformat() if isinstance(entry.get("updated_at"), datetime) else entry.get("updated_at"),
                })
            else:
                # Suggestion auto (non persistée) : rotation séquentielle depuis start_group
                if sorted_groups:
                    idx = (w - 1) % len(sorted_groups)
                    suggested = sorted_groups[idx]
                    # Si start_group n'est pas le premier, on shifte
                    if auto_start in sorted_groups:
                        offset = sorted_groups.index(auto_start)
                        idx = (offset + (w - 1)) % len(sorted_groups)
                        suggested = sorted_groups[idx]
                else:
                    suggested = None
                weeks.append({
                    "year": year, "week_number": w,
                    "groupe_garde": suggested, "manual_override": False,
                    "auto_generated": False, "is_suggestion": True,
                    "monday": monday.isoformat(), "sunday": sunday.isoformat(),
                })
        # Semaine ISO en cours
        today = _now_utc().date()
        cur_year, cur_week = _iso_week_year(today)
        return {
            "year": year,
            "weeks": weeks,
            "groups": sorted_groups,
            "groups_with_count": [{"groupe_garde": g, "count": groups[g]} for g in sorted_groups],
            "current_iso_year": cur_year,
            "current_iso_week": cur_week,
        }

    @api.post("/admin/officines-registry/garde-planning/generate", tags=["Admin — Officines Registry"])
    async def generate_garde_planning(
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        """Génère un planning séquentiel complet pour une année.

        Body :
          - year : entier (ex. 2026)
          - start_group : groupe en garde semaine 1
          - groups (optionnel) : liste explicite de l'ordre de rotation,
            sinon utilise les groupes existants triés.
          - overwrite_manual (optionnel, défaut False) : si True, écrase aussi
            les semaines marquées en override manuel.
        """
        try:
            year = int(payload.get("year"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="year requis")
        if year < 2024 or year > 2100:
            raise HTTPException(status_code=400, detail="year hors bornes (2024-2100)")
        # Liste des groupes
        groups_param = payload.get("groups")
        if groups_param and isinstance(groups_param, list):
            try:
                groups = sorted(set(int(g) for g in groups_param))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="`groups` doit être une liste d'entiers")
        else:
            groups_set: set = set()
            async for o in db.officines.find({"groupe_garde": {"$nin": [None, ""]}}, {"groupe_garde": 1, "_id": 0}):
                try:
                    groups_set.add(int(o["groupe_garde"]))
                except (TypeError, ValueError):
                    continue
            groups = sorted(groups_set)
        if not groups:
            raise HTTPException(status_code=400, detail="Aucun groupe de garde défini sur les officines. Affectez-les d'abord.")
        # Start group
        try:
            start_group = int(payload.get("start_group") or groups[0])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="start_group doit être un entier")
        if start_group not in groups:
            raise HTTPException(status_code=400, detail=f"start_group {start_group} n'est pas dans la liste {groups}")
        overwrite_manual = bool(payload.get("overwrite_manual"))
        # Last ISO week of the year
        last_week = date(year, 12, 28).isocalendar()[1]
        start_idx = groups.index(start_group)
        n = len(groups)
        upserts = 0
        kept_manual = 0
        for w in range(1, last_week + 1):
            existing = await db.garde_planning.find_one({"year": year, "week_number": w}, {"_id": 0})
            if existing and existing.get("manual_override") and not overwrite_manual:
                kept_manual += 1
                continue
            gg = groups[(start_idx + (w - 1)) % n]
            await db.garde_planning.update_one(
                {"year": year, "week_number": w},
                {"$set": {
                    "year": year, "week_number": w, "groupe_garde": gg,
                    "manual_override": False, "auto_generated": True,
                    "updated_by": user.get("email"), "updated_at": _now_utc(),
                }},
                upsert=True,
            )
            upserts += 1
        return {
            "ok": True,
            "year": year,
            "groups_rotation": groups,
            "start_group": start_group,
            "weeks_generated": upserts,
            "weeks_kept_manual": kept_manual,
        }

    @api.put("/admin/officines-registry/garde-planning/{year}/{week}", tags=["Admin — Officines Registry"])
    async def override_garde_week(
        year: int,
        week: int,
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        """Override manuel d'une semaine spécifique."""
        if year < 2024 or year > 2100:
            raise HTTPException(status_code=400, detail="year hors bornes")
        if week < 1 or week > 53:
            raise HTTPException(status_code=400, detail="week doit être entre 1 et 53")
        try:
            gg = int(payload.get("groupe_garde"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="groupe_garde requis (entier)")
        if gg < 1 or gg > 100:
            raise HTTPException(status_code=400, detail="groupe_garde doit être entre 1 et 100")
        await db.garde_planning.update_one(
            {"year": year, "week_number": week},
            {"$set": {
                "year": year, "week_number": week, "groupe_garde": gg,
                "manual_override": True, "auto_generated": False,
                "updated_by": user.get("email"), "updated_at": _now_utc(),
            }},
            upsert=True,
        )
        return {"ok": True, "year": year, "week_number": week, "groupe_garde": gg, "manual_override": True}

    @api.delete("/admin/officines-registry/garde-planning/{year}/{week}", tags=["Admin — Officines Registry"])
    async def reset_garde_week(
        year: int, week: int,
        user: dict = Depends(get_current_admin),
    ):
        """Supprime l'override d'une semaine (retombe sur la rotation auto)."""
        await db.garde_planning.delete_one({"year": year, "week_number": week})
        return {"ok": True, "year": year, "week_number": week, "reset": True}

    @api.get("/public/officines/garde/current", tags=["Public — Officines"])
    async def current_garde():
        """Endpoint public : groupe en garde cette semaine + liste des officines.

        Utilisé par la commande `!Garde` de Liluvine sur WhatsApp et peut être
        appelé depuis la page publique pour afficher les pharmacies de garde.

        Iter43-fix24ak (2026-06-17) — Le filtre `status="active"` est retiré
        (alignement avec `_build_garde_reply`) : seules les officines
        `suspended` sont exclues. Inclut aussi `cms_header`, `cms_footer`,
        `cms_image_url` configurés via Admin Settings pour personnaliser
        la page publique sans redéployer.
        """
        today = _now_utc().date()
        year, week = _iso_week_year(today)
        entry = await db.garde_planning.find_one({"year": year, "week_number": week}, {"_id": 0})
        if not entry:
            # Pas de planning → on calcule la rotation automatique
            groups_set: set = set()
            async for o in db.officines.find({"groupe_garde": {"$nin": [None, ""]}}, {"groupe_garde": 1, "_id": 0}):
                try:
                    groups_set.add(int(o["groupe_garde"]))
                except (TypeError, ValueError):
                    continue
            if not groups_set:
                return {"ok": False, "reason": "no_groups_defined", "year": year, "week_number": week}
            groups = sorted(groups_set)
            gg = groups[(week - 1) % len(groups)]
        else:
            gg = entry.get("groupe_garde")
        # Officines de ce groupe (status != suspended)
        officines: List[Dict[str, Any]] = []
        async for o in db.officines.find(
            {"groupe_garde": gg, "status": {"$ne": "suspended"}},
            {"_id": 0, "id": 1, "name": 1, "intitule": 1, "phone": 1,
             "whatsapp": 1, "address": 1, "city": 1, "location_hint": 1,
             "latitude": 1, "longitude": 1},
        ).sort("name", 1):
            officines.append(o)
        monday = date.fromisocalendar(year, week, 1).isoformat()
        sunday = date.fromisocalendar(year, week, 7).isoformat()
        # Iter43-fix24ak — CMS overrides (admin-editable) for the public page
        s = await db.settings.find_one(
            {"_id": "global"},
            {"_id": 0, "garde_page_header": 1, "garde_page_footer": 1,
             "garde_page_image_url": 1, "garde_page_image_caption": 1},
        ) or {}
        return {
            "ok": True,
            "year": year, "week_number": week,
            "groupe_garde": gg,
            "monday": monday, "sunday": sunday,
            "officines": officines,
            "count": len(officines),
            "cms_header": s.get("garde_page_header") or "",
            "cms_footer": s.get("garde_page_footer") or "",
            "cms_image_url": s.get("garde_page_image_url") or "",
            "cms_image_caption": s.get("garde_page_image_caption") or "",
        }
