"""Lot 41 — Calendrier dans la fenêtre de discussion WhatsApp.

Une modale réduite affiche la semaine (comme Google Calendar) avec les moments OCCUPÉS en
grisé, puis permet de partager ses disponibilités avec le contact de la conversation par un
lien public (sans aucun détail : seulement « occupé »).

Moments occupés (réunis) :
  - RENDEZ-VOUS du portail (collection appointments, en attente ou confirmés) du client ;
  - PLANNING des médecins (planning_appointments) du client ;
  - GOOGLE CALENDAR de la plateforme (agenda Google connecté par l'Admin) : pour l'Admin
    et le Superviseur, qui partagent cet agenda ;
  - CRÉNEAUX BLOQUÉS À LA MAIN par l'utilisateur dans la modale.

  GET    /api/me/calendrier/occupations?debut=AAAA-MM-JJ&jours=7   blocs occupés (avec détails)
  POST   /api/me/calendrier/creneaux                               {debut, fin, libelle}
  DELETE /api/me/calendrier/creneaux/{id}
  POST   /api/me/calendrier/partages                               {debut, jours} -> lien public
  GET    /api/public/calendrier/{jeton}                            blocs occupés SANS détails

Collections : creneaux_bloques, calendrier_partages.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

JOURS_MAX = 31
DUREE_PARTAGE = timedelta(days=14)
STATUTS_OCCUPES = ["pending", "confirmed"]


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v: Any) -> Optional[str]:
    """Date ISO normalisée en UTC (les dates sans fuseau sont considérées en UTC, comme au Burkina)."""
    if not v:
        return None
    try:
        d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def fusionner(blocs: List[dict]) -> List[dict]:
    """Blocs qui se chevauchent réunis (vue publique : on ne montre que « occupé »)."""
    tries = sorted((b for b in blocs if b.get("debut") and b.get("fin")), key=lambda b: b["debut"])
    sortie: List[dict] = []
    for b in tries:
        if sortie and b["debut"] <= sortie[-1]["fin"]:
            sortie[-1]["fin"] = max(sortie[-1]["fin"], b["fin"])
        else:
            sortie.append({"debut": b["debut"], "fin": b["fin"]})
    return sortie


class CreneauIn(BaseModel):
    debut: str
    fin: str
    libelle: Optional[str] = Field(None, max_length=120)


class PartageIn(BaseModel):
    debut: Optional[str] = None               # AAAA-MM-JJ, par défaut aujourd'hui
    jours: int = Field(7, ge=1, le=JOURS_MAX)


def attach_calendrier_partage_routes(
    *, api, db, get_current_user, public_base_url: Callable[[], str],
    google_freebusy: Optional[Callable[[str, str], Awaitable[List[dict]]]] = None,
    is_admin_like: Callable[[dict], bool] = lambda u: u.get("role") in ("admin", "superviseur"),
) -> Dict[str, Any]:

    def _tenant(user: dict) -> str:
        return user.get("parent_client_id") or user.get("client_id") or user["id"]

    def _periode(debut: Optional[str], jours: int) -> tuple:
        try:
            d0 = date.fromisoformat((debut or "")[:10]) if debut else _maintenant().date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Date de début invalide (AAAA-MM-JJ)")
        jours = max(1, min(JOURS_MAX, int(jours or 7)))
        t0 = datetime(d0.year, d0.month, d0.day, tzinfo=timezone.utc)
        return t0, t0 + timedelta(days=jours)

    async def _horaires() -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "business_open_time": 1,
                                                           "business_close_time": 1, "business_days": 1}) or {}
        return {"ouverture": s.get("business_open_time") or "07:00", "fermeture": s.get("business_close_time") or "19:00",
                "jours_ouvres": s.get("business_days") or [1, 2, 3, 4, 5, 6]}

    async def occupations(user: dict, t0: datetime, t1: datetime, avec_google: bool) -> List[dict]:
        """Blocs occupés {debut, fin, source, libelle} entre t0 et t1."""
        tid, a, b = _tenant(user), t0.isoformat(), t1.isoformat()
        blocs: List[dict] = []
        # 1. Rendez-vous du portail (scheduled_at + durée)
        async for r in db.appointments.find(
                {"client_id": tid, "status": {"$in": STATUTS_OCCUPES},
                 "scheduled_at": {"$gte": (t0 - timedelta(days=1)).isoformat(), "$lt": b}},
                {"_id": 0, "scheduled_at": 1, "duration_min": 1, "subject": 1}):
            debut = _iso(r.get("scheduled_at"))
            if not debut:
                continue
            fin = (datetime.fromisoformat(debut) + timedelta(minutes=int(r.get("duration_min") or 30))).isoformat()
            if fin > a:
                blocs.append({"debut": debut, "fin": fin, "source": "rdv", "libelle": r.get("subject") or "Rendez-vous"})
        # 2. Planning des médecins du client
        async for p in db.planning_appointments.find(
                {"tenant_id": tid, "start_at": {"$lt": b}, "end_at": {"$gt": a},
                 "status": {"$nin": ["cancelled", "annule", "annulé"]}},
                {"_id": 0, "start_at": 1, "end_at": 1, "patient": 1, "medecin": 1}):
            debut, fin = _iso(p.get("start_at")), _iso(p.get("end_at"))
            if debut and fin:
                blocs.append({"debut": debut, "fin": fin, "source": "planning",
                              "libelle": " · ".join(x for x in (p.get("medecin"), p.get("patient")) if x) or "Planning"})
        # 3. Google Calendar de la plateforme (Admin / Superviseur)
        if avec_google and google_freebusy is not None:
            try:
                for g in await google_freebusy(a, b) or []:
                    debut, fin = _iso(g.get("start")), _iso(g.get("end"))
                    if debut and fin:
                        blocs.append({"debut": debut, "fin": fin, "source": "google", "libelle": "Google Calendar"})
            except Exception:  # noqa: BLE001 — Google indisponible : le reste s'affiche
                pass
        # 4. Créneaux bloqués à la main
        async for c in db.creneaux_bloques.find({"user_id": user["id"], "debut": {"$lt": b}, "fin": {"$gt": a}},
                                               {"_id": 0}):
            blocs.append({"id": c["id"], "debut": c["debut"], "fin": c["fin"], "source": "manuel",
                          "libelle": c.get("libelle") or "Occupé"})
        blocs.sort(key=lambda x: x["debut"])
        return blocs

    @api.get("/me/calendrier/occupations", tags=["Calendrier"])
    async def lire(debut: Optional[str] = None, jours: int = 7, user: dict = Depends(get_current_user)):
        t0, t1 = _periode(debut, jours)
        return {"debut": t0.isoformat(), "fin": t1.isoformat(), "horaires": await _horaires(),
                "google": bool(is_admin_like(user) and google_freebusy is not None),
                "occupations": await occupations(user, t0, t1, is_admin_like(user))}

    @api.post("/me/calendrier/creneaux", tags=["Calendrier"])
    async def bloquer(data: CreneauIn, user: dict = Depends(get_current_user)):
        debut, fin = _iso(data.debut), _iso(data.fin)
        if not debut or not fin or fin <= debut:
            raise HTTPException(status_code=400, detail="Créneau invalide : la fin doit suivre le début")
        if datetime.fromisoformat(fin) - datetime.fromisoformat(debut) > timedelta(days=7):
            raise HTTPException(status_code=400, detail="Un créneau bloqué dure 7 jours au plus")
        doc = {"id": secrets.token_hex(8), "user_id": user["id"], "tenant_id": _tenant(user), "debut": debut,
               "fin": fin, "libelle": (data.libelle or "").strip() or None, "cree_le": _maintenant().isoformat()}
        await db.creneaux_bloques.insert_one(dict(doc))
        return doc

    @api.delete("/me/calendrier/creneaux/{cid}", tags=["Calendrier"])
    async def debloquer(cid: str, user: dict = Depends(get_current_user)):
        r = await db.creneaux_bloques.delete_one({"id": cid, "user_id": user["id"]})
        if not r.deleted_count:
            raise HTTPException(status_code=404, detail="Créneau introuvable")
        return {"ok": True}

    @api.post("/me/calendrier/partages", tags=["Calendrier"])
    async def partager(data: PartageIn, user: dict = Depends(get_current_user)):
        """Lien public de disponibilités, valable 14 jours : seulement « occupé », sans détail."""
        t0, _ = _periode(data.debut, data.jours)
        compte = await db.users.find_one({"id": _tenant(user)}, {"_id": 0, "company": 1, "full_name": 1}) or {}
        jeton = secrets.token_urlsafe(12)
        await db.calendrier_partages.insert_one({
            "jeton": jeton, "user_id": user["id"], "tenant_id": _tenant(user), "debut": t0.date().isoformat(),
            "jours": data.jours, "avec_google": bool(is_admin_like(user)),
            "titre": user.get("full_name") or compte.get("company") or compte.get("full_name") or "SAWALI",
            "cree_le": _maintenant().isoformat(), "expire_le": (_maintenant() + DUREE_PARTAGE).isoformat()})
        url = f"{(public_base_url() or '').rstrip('/')}/disponibilites/{jeton}"
        return {"url": url, "expire_le": (_maintenant() + DUREE_PARTAGE).isoformat(),
                "texte": f"📅 Mes disponibilités (créneaux libres en blanc) : {url}"}

    @api.get("/public/calendrier/{jeton}", tags=["Public"])
    async def public(jeton: str, debut: Optional[str] = None):
        p = await db.calendrier_partages.find_one({"jeton": jeton[:40]}, {"_id": 0})
        if not p or p["expire_le"] < _maintenant().isoformat():
            raise HTTPException(status_code=404, detail="Lien expiré ou inconnu")
        t0, t1 = _periode(debut or p["debut"], p["jours"])
        proprietaire = {"id": p["user_id"], "client_id": p["tenant_id"]}
        blocs = await occupations(proprietaire, t0, t1, p.get("avec_google"))
        return {"titre": p.get("titre"), "debut": t0.isoformat(), "fin": t1.isoformat(),
                "horaires": await _horaires(), "occupations": fusionner(blocs), "expire_le": p["expire_le"]}

    return {"occupations": occupations}
