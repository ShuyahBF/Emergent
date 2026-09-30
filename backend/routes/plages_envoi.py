"""Lot 42 — Plages horaires d'envoi (sondages et formulaires).

Pour ne pas déranger les contacts, l'Admin fixe dans les Paramètres les jours et les
plages horaires pendant lesquels les envois de sondages et de liens de formulaires
sont autorisés (heure de Ouagadougou par défaut). En dehors :
  - un envoi lancé attend la prochaine plage ;
  - un envoi en cours s'interrompt à la fin de la plage et reprend automatiquement à
    l'ouverture de la plage suivante (le lendemain, par exemple).

Réglage enregistré dans `parametres_plateforme` (document id = "plages_envoi") :
  {actif, fuseau, jours: [0..6] (0 = lundi), plages: [{de: "08:00", a: "12:00"}, …]}

  GET /api/admin/plages-envoi      réglage (Admin)
  PUT /api/admin/plages-envoi      enregistrement (Admin)
  GET /api/me/plages-envoi         réglage en lecture (pages d'envoi du portail)
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

DOC_ID = "plages_envoi"
JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
DEFAUT: Dict[str, Any] = {
    "actif": False, "fuseau": "Africa/Ouagadougou", "jours": [0, 1, 2, 3, 4, 5],
    "plages": [{"de": "08:00", "a": "12:00"}, {"de": "15:00", "a": "19:00"}],
}
RE_HEURE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class PlageIn(BaseModel):
    de: str
    a: str


class PlagesIn(BaseModel):
    actif: bool = False
    fuseau: str = "Africa/Ouagadougou"
    jours: List[int] = Field(default_factory=list)
    plages: List[PlageIn] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Fonctions pures (testées sans base)
# ---------------------------------------------------------------------------
def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def normaliser(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Contrôle le réglage ; lève ValueError avec un message clair.
    Les plages sont triées et ne doivent pas se chevaucher."""
    cfg = {**DEFAUT, **(cfg or {})}
    try:
        ZoneInfo(cfg["fuseau"])
    except Exception:  # noqa: BLE001 — fuseau inconnu
        raise ValueError(f"Fuseau horaire inconnu : « {cfg['fuseau']} »")
    jours = sorted({int(j) for j in cfg.get("jours") or [] if 0 <= int(j) <= 6})
    plages = []
    for p in cfg.get("plages") or []:
        p = p if isinstance(p, dict) else p.model_dump()
        de, a = str(p.get("de") or "").strip(), str(p.get("a") or "").strip()
        if not RE_HEURE.match(de) or not RE_HEURE.match(a):
            raise ValueError("Heures au format HH:MM (ex. 08:00)")
        if _minutes(a) <= _minutes(de):
            raise ValueError(f"Plage {de} – {a} : l'heure de fin doit suivre l'heure de début")
        plages.append({"de": de, "a": a})
    plages.sort(key=lambda p: p["de"])
    for p1, p2 in zip(plages, plages[1:]):
        if _minutes(p2["de"]) < _minutes(p1["a"]):
            raise ValueError(f"Les plages {p1['de']} – {p1['a']} et {p2['de']} – {p2['a']} se chevauchent")
    if cfg.get("actif") and (not jours or not plages):
        raise ValueError("Choisissez au moins un jour et une plage horaire (ou désactivez les plages)")
    return {"actif": bool(cfg.get("actif")), "fuseau": cfg["fuseau"], "jours": jours, "plages": plages}


def dans_plage(cfg: Dict[str, Any], instant: datetime) -> bool:
    """`instant` (UTC) tombe-t-il dans une plage autorisée ? Toujours vrai si les plages sont désactivées."""
    if not cfg.get("actif"):
        return True
    local = instant.astimezone(ZoneInfo(cfg["fuseau"]))
    if local.weekday() not in cfg["jours"]:
        return False
    m = local.hour * 60 + local.minute
    return any(_minutes(p["de"]) <= m < _minutes(p["a"]) for p in cfg["plages"])


def prochaine_ouverture(cfg: Dict[str, Any], instant: datetime) -> Optional[datetime]:
    """None si l'envoi est permis à `instant` ; sinon l'instant (UTC) de la prochaine
    ouverture de plage (au plus tard 8 jours après)."""
    if dans_plage(cfg, instant):
        return None
    tz = ZoneInfo(cfg["fuseau"])
    local = instant.astimezone(tz)
    for d in range(0, 8):
        jour = (local + timedelta(days=d)).date()
        if jour.weekday() not in cfg["jours"]:
            continue
        for p in cfg["plages"]:
            h, m = (int(x) for x in p["de"].split(":"))
            debut = datetime(jour.year, jour.month, jour.day, h, m, tzinfo=tz)
            if debut > local:
                return debut.astimezone(timezone.utc)
    return None                     # réglage incohérent : on ne bloque pas indéfiniment


def instant_programme(texte: Optional[str], cfg: Dict[str, Any]) -> Optional[datetime]:
    """Date d'envoi programmée saisie dans le portail (« 2026-10-01T09:00 », heure locale
    de la plateforme, ou ISO avec fuseau) -> instant UTC ; None si vide."""
    if not (texte or "").strip():
        return None
    try:
        d = datetime.fromisoformat(texte.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Date d'envoi programmée invalide")
    if d.tzinfo is None:
        d = d.replace(tzinfo=ZoneInfo(cfg.get("fuseau") or DEFAUT["fuseau"]))
    return d.astimezone(timezone.utc)


def resume_texte(cfg: Dict[str, Any]) -> str:
    """« Lun, Mar, … · 08:00–12:00, 15:00–19:00 » (affiché sur les pages d'envoi)."""
    if not cfg.get("actif"):
        return "Aucune restriction horaire"
    jours = ", ".join(JOURS[j][:3] for j in cfg["jours"])
    return f"{jours} · " + ", ".join(f"{p['de']}–{p['a']}" for p in cfg["plages"])


# ---------------------------------------------------------------------------
# Routes et accès au réglage
# ---------------------------------------------------------------------------
def attach_plages_envoi_routes(*, api, db, get_current_admin, get_current_user) -> Dict[str, Any]:
    """Branche les routes ; renvoie {config, attente, programme} pour les moteurs d'envoi."""
    cache: Dict[str, Any] = {"cfg": None, "t": 0.0}

    async def config() -> Dict[str, Any]:
        # Relu au plus toutes les 30 s : un envoi en cours voit vite un changement de l'Admin
        if cache["cfg"] is None or time.monotonic() - cache["t"] > 30:
            doc = await db.parametres_plateforme.find_one({"id": DOC_ID}, {"_id": 0}) or {}
            try:
                cache["cfg"] = normaliser(doc.get("valeur"))
            except ValueError:
                cache["cfg"] = normaliser(None)
            cache["t"] = time.monotonic()
        return cache["cfg"]

    async def attente(maintenant: Optional[datetime] = None) -> Optional[datetime]:
        """None si l'envoi est permis maintenant ; sinon la prochaine ouverture (UTC)."""
        return prochaine_ouverture(await config(), maintenant or datetime.now(timezone.utc))

    async def programme(texte: Optional[str]) -> Optional[datetime]:
        """Date programmée saisie -> UTC ; refuse une date passée de plus de 5 minutes."""
        try:
            d = instant_programme(texte, await config())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if d and d < datetime.now(timezone.utc) - timedelta(minutes=5):
            raise HTTPException(status_code=400, detail="La date d'envoi programmée est déjà passée")
        return d

    def _vue(cfg: Dict[str, Any]) -> Dict[str, Any]:
        return {**cfg, "resume": resume_texte(cfg), "jours_libelles": JOURS}

    @api.get("/admin/plages-envoi", tags=["Admin"])
    async def lire(_: dict = Depends(get_current_admin)):
        return _vue(await config())

    @api.put("/admin/plages-envoi", tags=["Admin"])
    async def enregistrer(data: PlagesIn, admin: dict = Depends(get_current_admin)):
        try:
            cfg = normaliser(data.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        await db.parametres_plateforme.update_one(
            {"id": DOC_ID},
            {"$set": {"id": DOC_ID, "valeur": cfg, "maj_le": datetime.now(timezone.utc).isoformat(),
                      "maj_par": admin.get("full_name") or admin.get("email")}},
            upsert=True)
        cache["cfg"] = None                          # relu au prochain appel
        return _vue(cfg)

    @api.get("/me/plages-envoi", tags=["Sondages WhatsApp"])
    async def lire_portail(_: dict = Depends(get_current_user)):
        cfg = await config()
        ouverture = prochaine_ouverture(cfg, datetime.now(timezone.utc))
        return {**_vue(cfg), "ouvert_maintenant": ouverture is None,
                "prochaine_ouverture": ouverture.isoformat() if ouverture else None}

    return {"config": config, "attente": attente, "programme": programme}
