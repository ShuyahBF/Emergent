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


def _saturday_noon_week_year(now: datetime) -> tuple[int, int]:
    """Iter43-fix24az-d (2026-02-26) — Compute the « guard week » using a
    rotation that flips every Saturday at 12:00 (noon) Africa/Abidjan time
    (UTC ≅ Africa/Abidjan since both are UTC+00:00).

    A *guard period* spans Saturday 12:00 → next Saturday 12:00 (7 days).
    The associated ISO week is the one containing the Saturday that *starts*
    the period.

    Examples (assuming UTC):
      - Tuesday  → most recent Sat was last week's Sat → uses last week's ISO week
      - Friday   → idem
      - Saturday 11:59 → most recent Sat 12:00 was 6d 23h ago → previous ISO week
      - Saturday 12:00 → new period starts → uses this week's ISO week
      - Sunday  → most recent Sat 12:00 was yesterday → uses this week's ISO week
    """
    today = now.date()
    weekday = now.weekday()  # Mon=0, …, Sat=5, Sun=6
    if weekday == 5:  # Saturday
        days_back = 0 if now.hour >= 12 else 7
    elif weekday == 6:  # Sunday
        days_back = 1
    else:  # Mon..Fri
        # Last Saturday = today - (weekday + 2) days
        # Mon=0→2 ; Tue=1→3 ; … ; Fri=4→6
        days_back = weekday + 2
    from datetime import timedelta as _td
    ref_date = today - _td(days=days_back)
    iso = ref_date.isocalendar()
    return iso[0], iso[1]


async def _current_garde_week(db, *, now: Optional[datetime] = None) -> tuple[int, int, str]:
    """Returns (year, week, mode_used) according to `settings.garde_rotation_mode`.

    Modes:
      - "saturday_noon" (default, new) → rotation Saturday 12:00
      - "monday_midnight" (legacy) → rotation Monday 00:00 (pure ISO week)
    """
    if now is None:
        now = _now_utc()
    try:
        s = await db.settings.find_one(
            {"_id": "global"}, {"_id": 0, "garde_rotation_mode": 1},
        ) or {}
        mode = (s.get("garde_rotation_mode") or "saturday_noon").strip().lower()
    except Exception:  # noqa: BLE001
        mode = "saturday_noon"
    if mode == "monday_midnight":
        y, w = _iso_week_year(now.date())
    else:
        mode = "saturday_noon"
        y, w = _saturday_noon_week_year(now)
    return y, w, mode


def _period_dates_for_week(year: int, week: int, mode: str) -> tuple[date, date]:
    """Iter43-fix24az-e (2026-02-26) — Returns the (start, end) dates of the
    *guard period* labelled by (year, week) under the given rotation mode.

    - monday_midnight : period = Mon → Sun of ISO week (legacy)
    - saturday_noon   : period = Saturday of ISO week W → Saturday of week W+1
                        (i.e. the SATURDAY-to-SATURDAY window)

    User reported (28/06/2026 = Sun, week 26):
      → period_start = Sat 27/06 (start), period_end = Sat 04/07 (end)
    """
    if mode == "monday_midnight":
        return date.fromisocalendar(year, week, 1), date.fromisocalendar(year, week, 7)
    # saturday_noon
    try:
        start = date.fromisocalendar(year, week, 6)  # Saturday of ISO week W
    except ValueError:
        # Edge case: week number invalid for the year — fall back
        return date.fromisocalendar(year, week, 1), date.fromisocalendar(year, week, 7)
    from datetime import timedelta as _td
    end = start + _td(days=7)  # Saturday of ISO week W+1 (12:00, but date-only here)
    return start, end


async def _current_garde_period(db, *, now: Optional[datetime] = None) -> dict:
    """Convenience wrapper used by API + Liluvine !Garde to render correct
    period boundaries."""
    if now is None:
        now = _now_utc()
    y, w, mode = await _current_garde_week(db, now=now)
    ps, pe = _period_dates_for_week(y, w, mode)
    return {"year": y, "week": w, "mode": mode, "period_start": ps, "period_end": pe}


def _next_rotation_iso(now: datetime, mode: str) -> str:
    """Return ISO timestamp of the next group rotation moment."""
    from datetime import timedelta as _td
    if mode == "monday_midnight":
        # Next Monday 00:00 UTC
        weekday = now.weekday()  # Mon=0
        days_ahead = (7 - weekday) % 7 or 7
        next_dt = (now + _td(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
        return next_dt.isoformat()
    # saturday_noon
    weekday = now.weekday()  # Sat=5
    if weekday == 5 and now.hour < 12:
        # Today Saturday morning → next rotation is today at 12:00
        next_dt = now.replace(hour=12, minute=0, second=0, microsecond=0)
    else:
        # Days ahead to NEXT Saturday (strictly after now)
        days_ahead = (5 - weekday) % 7
        if days_ahead == 0:  # Saturday and we're past noon → next week's Saturday
            days_ahead = 7
        next_dt = (now + _td(days=days_ahead)).replace(hour=12, minute=0, second=0, microsecond=0)
    return next_dt.isoformat()


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
        # Iter43-fix24az-e — Read rotation mode ONCE for the whole listing so
        # the "monday/sunday" boundary dates reflect the actual guard period
        # under saturday_noon (Sat → Sat) vs monday_midnight (Mon → Sun).
        s_doc = await db.settings.find_one({"_id": "global"}, {"_id": 0, "garde_rotation_mode": 1}) or {}
        mode_label = (s_doc.get("garde_rotation_mode") or "saturday_noon").strip().lower()
        if mode_label not in ("saturday_noon", "monday_midnight"):
            mode_label = "saturday_noon"
        weeks: List[Dict[str, Any]] = []
        for w in range(1, last_week + 1):
            entry = existing.get(w)
            # Dates de la PÉRIODE de garde (Sat→Sat ou Mon→Sun selon le mode)
            try:
                period_start, period_end = _period_dates_for_week(year, w, mode_label)
            except ValueError:
                continue
            if entry:
                weeks.append({
                    "year": year,
                    "week_number": w,
                    "groupe_garde": entry.get("groupe_garde"),
                    # Iter43-fix24az-r (2026-07-22) — Groupe d'assistance hebdo
                    "assist_group": entry.get("assist_group"),
                    "manual_override": bool(entry.get("manual_override")),
                    "auto_generated": bool(entry.get("auto_generated")),
                    "monday": period_start.isoformat(),
                    "sunday": period_end.isoformat(),
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
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
                    "groupe_garde": suggested,
                    "assist_group": None,  # Iter43-fix24az-r
                    "manual_override": False,
                    "auto_generated": False, "is_suggestion": True,
                    "monday": period_start.isoformat(), "sunday": period_end.isoformat(),
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                })
        # Semaine ISO en cours
        cur_year, cur_week, _mode = await _current_garde_week(db, now=_now_utc())
        return {
            "year": year,
            "weeks": weeks,
            "groups": sorted_groups,
            "groups_with_count": [{"groupe_garde": g, "count": groups[g]} for g in sorted_groups],
            "current_iso_year": cur_year,
            "current_iso_week": cur_week,
            # Iter43-fix24az-d — surfaced rotation mode for the admin UI
            "current_rotation_mode": _mode,
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
        """Override manuel d'une semaine spécifique.

        Body accepte :
          - `groupe_garde` (int) : groupe standard (obligatoire si assist_group absent)
          - `assist_group` (int|null) : Iter43-fix24az-r — groupe d'assistance
            qui vient en appui au groupe standard cette semaine. `null` ou
            `0` désactive l'appui.
        """
        if year < 2024 or year > 2100:
            raise HTTPException(status_code=400, detail="year hors bornes")
        if week < 1 or week > 53:
            raise HTTPException(status_code=400, detail="week doit être entre 1 et 53")

        set_doc: Dict[str, Any] = {
            "year": year, "week_number": week,
            "manual_override": True, "auto_generated": False,
            "updated_by": user.get("email"), "updated_at": _now_utc(),
        }
        # Iter43-fix24az-r — On peut MAJ soit groupe_garde, soit assist_group,
        # soit les deux. Au moins un des deux doit être fourni.
        has_gg = "groupe_garde" in payload and payload.get("groupe_garde") is not None
        has_assist = "assist_group" in payload
        if not has_gg and not has_assist:
            raise HTTPException(
                status_code=400,
                detail="Fournir au moins `groupe_garde` ou `assist_group` dans le body",
            )
        # Charge d'abord l'entrée existante (pour préserver le champ non fourni)
        existing_doc = await db.garde_planning.find_one(
            {"year": year, "week_number": week},
            {"_id": 0, "groupe_garde": 1, "assist_group": 1},
        ) or {}
        if has_gg:
            try:
                gg = int(payload.get("groupe_garde"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="groupe_garde requis (entier)")
            if gg < 1 or gg > 100:
                raise HTTPException(status_code=400, detail="groupe_garde doit être entre 1 et 100")
            set_doc["groupe_garde"] = gg
        elif has_assist and existing_doc.get("groupe_garde") is None:
            # Iter43-fix24az-r — Cas UX : l'admin veut définir un assist sur
            # une semaine qui n'a pas encore de doc persistant (rotation auto).
            # On calcule le groupe standard suggéré et on le persiste pour
            # ne pas afficher un vide dans la colonne « Groupe ».
            groups_set: set = set()
            async for o in db.officines.find({"groupe_garde": {"$nin": [None, ""]}}, {"groupe_garde": 1, "_id": 0}):
                try:
                    groups_set.add(int(o["groupe_garde"]))
                except (TypeError, ValueError):
                    continue
            if groups_set:
                sorted_g = sorted(groups_set)
                # rotation séquentielle basique (week - 1) % n
                set_doc["groupe_garde"] = sorted_g[(week - 1) % len(sorted_g)]
                set_doc["auto_generated"] = True  # groupe standard = auto, seul assist est manuel
                set_doc["manual_override"] = False
        if has_assist:
            assist_raw = payload.get("assist_group")
            if assist_raw is None or assist_raw == "" or assist_raw == 0:
                set_doc["assist_group"] = None
            else:
                try:
                    ag = int(assist_raw)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="assist_group doit être un entier ou null")
                if ag < 1 or ag > 100:
                    raise HTTPException(status_code=400, detail="assist_group doit être entre 1 et 100")
                # Sanity check : l'assist ne doit pas être le même que le groupe standard
                gg_current = set_doc.get("groupe_garde", existing_doc.get("groupe_garde"))
                if gg_current is not None and ag == gg_current:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Le groupe d'assistance ({ag}) ne peut pas être identique au groupe standard ({gg_current})",
                    )
                set_doc["assist_group"] = ag
        await db.garde_planning.update_one(
            {"year": year, "week_number": week},
            {"$set": set_doc},
            upsert=True,
        )
        # Renvoie l'entrée complète (pour que le front puisse rafraîchir la ligne)
        doc = await db.garde_planning.find_one({"year": year, "week_number": week}, {"_id": 0})
        return {"ok": True, "year": year, "week_number": week,
                "groupe_garde": doc.get("groupe_garde") if doc else None,
                "assist_group": doc.get("assist_group") if doc else None,
                "manual_override": True}

    @api.delete("/admin/officines-registry/garde-planning/year/{year}", tags=["Admin — Officines Registry"])
    async def reset_garde_year(
        year: int,
        user: dict = Depends(get_current_admin),
    ):
        """Iter43-fix24az-e (2026-02-26) — Réinitialise TOUTES les semaines
        d'une année (= supprime tous les documents `garde_planning` de cette
        année). Le planning retombera sur la rotation séquentielle calculée.

        IMPORTANT — cette route DOIT être déclarée AVANT la route plus
        générique `/garde-planning/{year}/{week}` car FastAPI matche les
        routes dans l'ordre de déclaration. Si on inverse, l'URL
        `/garde-planning/year/2026` est matchée comme `{year}='year'` →
        HTTP 422 int_parsing.
        """
        if year < 2024 or year > 2100:
            raise HTTPException(status_code=400, detail="year hors bornes")
        res = await db.garde_planning.delete_many({"year": year})
        logger.info(
            "[garde] reset year %s — %d weeks deleted by %s",
            year, res.deleted_count, user.get("email"),
        )
        return {"ok": True, "year": year, "weeks_deleted": res.deleted_count}

    @api.delete("/admin/officines-registry/garde-planning/{year}/{week}", tags=["Admin — Officines Registry"])
    async def reset_garde_week(
        year: int, week: int,
        user: dict = Depends(get_current_admin),
    ):
        """Supprime l'override d'une semaine (retombe sur la rotation auto)."""
        await db.garde_planning.delete_one({"year": year, "week_number": week})
        return {"ok": True, "year": year, "week_number": week, "reset": True}

    @api.delete("/admin/officines-registry/garde-groups/{group_number}", tags=["Admin — Officines Registry"])
    async def delete_empty_garde_group(
        group_number: int,
        user: dict = Depends(get_current_admin),
    ):
        """Iter43-fix24az-e — Supprime un groupe de garde S'IL EST VIDE
        (aucune officine assignée). Refus si au moins 1 officine porte
        encore `groupe_garde == group_number`."""
        if group_number < 1 or group_number > 100:
            raise HTTPException(status_code=400, detail="group_number doit être entre 1 et 100")
        count = await db.officines.count_documents({"groupe_garde": group_number})
        if count > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Groupe {group_number} non vide ({count} officine(s)). Réaffectez-les avant suppression.",
            )
        # Aussi : nettoie le planning où ce groupe était référencé
        cleaned = await db.garde_planning.update_many(
            {"groupe_garde": group_number},
            {"$set": {"groupe_garde": None, "manual_override": False, "auto_generated": False,
                      "updated_by": user.get("email"), "updated_at": _now_utc()}},
        )
        logger.info(
            "[garde] empty group %d removed (planning rows cleaned: %d) by %s",
            group_number, cleaned.modified_count, user.get("email"),
        )
        return {"ok": True, "group_number": group_number, "planning_rows_cleaned": cleaned.modified_count}

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
        year, week, _mode = await _current_garde_week(db, now=_now_utc())
        entry = await db.garde_planning.find_one({"year": year, "week_number": week}, {"_id": 0})
        assist_group: Optional[int] = None
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
            assist_group = entry.get("assist_group")  # Iter43-fix24az-r
        # Officines de ce groupe (status != suspended)
        officines: List[Dict[str, Any]] = []
        async for o in db.officines.find(
            {"groupe_garde": gg, "status": {"$ne": "suspended"}},
            {"_id": 0, "id": 1, "name": 1, "intitule": 1, "phone": 1,
             "whatsapp": 1, "address": 1, "city": 1, "location_hint": 1,
             "latitude": 1, "longitude": 1},
        ).sort("name", 1):
            officines.append(o)
        # Iter43-fix24az-r — Officines du groupe d'assistance (si défini)
        assist_officines: List[Dict[str, Any]] = []
        if assist_group is not None and assist_group != gg:
            async for o in db.officines.find(
                {"groupe_garde": assist_group, "status": {"$ne": "suspended"}},
                {"_id": 0, "id": 1, "name": 1, "intitule": 1, "phone": 1,
                 "whatsapp": 1, "address": 1, "city": 1, "location_hint": 1,
                 "latitude": 1, "longitude": 1},
            ).sort("name", 1):
                assist_officines.append(o)
        # Iter43-fix24az-e — Use ACTUAL guard period boundaries (Sat→Sat in
        # saturday_noon mode), not ISO Monday/Sunday — fixes the !Garde dates.
        period_start, period_end = _period_dates_for_week(year, week, _mode)
        monday = period_start.isoformat()
        sunday = period_end.isoformat()
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
            # Iter43-fix24az-r — Groupe d'assistance hebdomadaire (nullable)
            "assist_group": assist_group,
            "assist_officines": assist_officines,
            "assist_count": len(assist_officines),
            "monday": monday, "sunday": sunday,
            # Iter43-fix24az-e — Explicit period boundaries (Sat→Sat under
            # saturday_noon, Mon→Sun under monday_midnight). Same values as
            # monday/sunday but with unambiguous names for API consumers.
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "officines": officines,
            "count": len(officines),
            # Iter43-fix24az-d — surface rotation mode + next rotation timestamp
            "rotation_mode": _mode,
            "next_rotation_at": _next_rotation_iso(_now_utc(), _mode),
            "cms_header": s.get("garde_page_header") or "",
            "cms_footer": s.get("garde_page_footer") or "",
            "cms_image_url": s.get("garde_page_image_url") or "",
            "cms_image_caption": s.get("garde_page_image_caption") or "",
        }
