# rdv_fictifs.py — Lot 211 : Liluvine prépare chaque matin, dès 6 h, un programme de rendez-vous FICTIFS pour la semaine.
#
# Demande du propriétaire (16/10/2026) : « Tous les matins dès 6 h Liluvine me génère un programme de RDV fictifs sur
# sup.alphasofti@gmail.com : réunions, formations, dépannages, suivis, assistances, etc. 2 à 4 max par jour. Elle le génère pour
# toute la semaine. »
#
# En résumé (pour un développeur WinDev) :
#   - AGENDA : le Google Agenda déjà relié à SAWALI (Paramètres → Google Agenda ; réglage google_calendar_email). GARDE-FOU : rien
#     n'est créé si l'agenda relié n'est pas celui de `rdv_fictifs_agenda` (sup.alphasofti@gmail.com par défaut) — jamais sur un autre.
#   - CHAQUE MATIN À 06 H 00 (Africa/Ouagadougou) : pour chacun des N prochains jours (7 par défaut, aujourd'hui compris) qui est un jour
#     OUVRÉ (réglage business_days) et n'a pas encore son programme, Liluvine crée 2 à 4 rendez-vous dans les horaires d'ouverture
#     (business_open_time / business_close_time). Un jour déjà généré n'est jamais refait : pas de doublon.
#   - CONTENU : réunions, formations, dépannages à distance, suivis, assistances, démonstrations… avec des noms de structures
#     INVENTÉS (aucun vrai client). Le programme d'un jour est reproductible (graine = date).
#   - AUCUN INVITÉ, AUCUNE NOTIFICATION : les rendez-vous n'ont pas de participants ; la description précise « rendez-vous fictif ».
#   - CRÉNEAUX DE RÉSERVATION : par défaut les rendez-vous fictifs sont « disponibles » pour Google (transparency = transparent) :
#     ils ne bloquent donc PAS les créneaux proposés aux vrais clients. `rdv_fictifs_bloquent` = vrai les rend « occupés ».
#   - SUIVI : db.settings {_id: "rdv_fictifs"} (identifiants des événements créés, par jour) — aucune nouvelle collection.
#     Le bouton « Supprimer les rendez-vous fictifs » n'efface QUE ces événements-là.
#   - RÉGLAGES (db.settings global, Paramètres → « 📅 Rendez-vous fictifs ») : rdv_fictifs_actif (DÉSACTIVÉ par défaut), _min (2), _max (4),
#     _jours (7), _bloquent (faux), _agenda.
# Routes (administrateur) : GET/PUT /api/admin/rdv-fictifs ; POST /api/admin/rdv-fictifs/generer ; POST /api/admin/rdv-fictifs/supprimer.
from __future__ import annotations

import asyncio
import logging
import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.rdv_fictifs")

DOC_ID = "rdv_fictifs"
FUSEAU = "Africa/Ouagadougou"
AGENDA_DEFAUT = "sup.alphasofti@gmail.com"
JOURS_OUVRES_DEFAUT = [0, 1, 2, 3, 4]
HEURE_OUVERTURE, HEURE_FERMETURE = "09:00", "18:00"
MARQUE = "Rendez-vous fictif généré par Liluvine (aucun invité, aucune notification)."

# Structures INVENTÉES (aucun vrai client) et intitulés par type : (type, durée en minutes, modèles de titre)
STRUCTURES = ["Pharmacie du Centre", "Clinique Les Acacias", "Cabinet Tapsoba & Associés", "Boutique Wend-Panga", "École Sainte-Marie",
              "Garage Nabaloum", "Centre de santé Rimkieta", "Quincaillerie Zongo", "Pharmacie de la Paix", "Dispensaire Koulouba",
              "Laboratoire Bonheur", "Supermarché Le Sahel"]
TYPES = [
    ("réunion", 60, ["Réunion d'équipe — point hebdomadaire", "Réunion — revue des tickets en cours", "Réunion de cadrage — {s}"]),
    ("formation", 90, ["Formation — prise en main du logiciel ({s})", "Formation — nouveautés de la version ({s})", "Formation — utilisateurs de {s}"]),
    ("dépannage", 45, ["Dépannage à distance — {s}", "Dépannage — poste bloqué chez {s}", "Dépannage — imprimante et réseau ({s})"]),
    ("suivi", 30, ["Suivi client — {s}", "Point de suivi — contrat {s}", "Suivi de déploiement — {s}"]),
    ("assistance", 30, ["Assistance — question de paramétrage ({s})", "Assistance téléphonique — {s}", "Assistance — export de données ({s})"]),
    ("démonstration", 60, ["Démonstration — solution de gestion ({s})", "Démonstration produit — prospect {s}"]),
]


# ---------------------------------------------------------------------------------------------------------------------
# Calcul (fonctions pures, testées sans base ni réseau)
# ---------------------------------------------------------------------------------------------------------------------
def _minutes(hhmm: str, defaut: str) -> int:
    """« 09:30 » → 570 (minutes depuis minuit) ; valeur illisible → défaut."""
    for texte in (hhmm, defaut):
        try:
            h, m = str(texte).split(":")[:2]
            return int(h) * 60 + int(m)
        except (ValueError, AttributeError):
            continue
    return 0


def generer_jour(jour: date, mini: int = 2, maxi: int = 4, ouverture: str = HEURE_OUVERTURE, fermeture: str = HEURE_FERMETURE) -> List[Dict[str, Any]]:
    """Programme fictif d'un jour : entre `mini` et `maxi` rendez-vous dans les horaires d'ouverture, sans chevauchement, avec au
    moins 15 minutes entre deux. Reproductible : la graine est la date (même jour → même programme). Heures locales (naïves)."""
    rng = random.Random(f"rdv-fictifs-{jour.isoformat()}")
    mini, maxi = max(1, min(int(mini), 6)), max(1, min(int(maxi), 6))
    maxi = max(mini, maxi)
    debut_j, fin_j = _minutes(ouverture, HEURE_OUVERTURE), _minutes(fermeture, HEURE_FERMETURE)
    n = rng.randint(mini, maxi)
    types = rng.sample(TYPES, k=min(n, len(TYPES))) + [rng.choice(TYPES) for _ in range(max(0, n - len(TYPES)))]
    structures = rng.sample(STRUCTURES, k=min(n, len(STRUCTURES)))
    # Les rendez-vous sont posés dans l'ordre de la journée : on tire des heures de début (pas de 15 min) et on les décale si besoin
    plages: List[tuple] = []
    for _ in range(40):                                              # tentatives pour trouver un placement sans chevauchement
        plages = []
        ok = True
        for t in types:
            duree = t[1]
            if fin_j - debut_j < duree:
                ok = False
                break
            debut = debut_j + 15 * rng.randint(0, (fin_j - debut_j - duree) // 15)
            if any(debut < e + 15 and debut + duree + 15 > b for b, e in plages):
                ok = False
                break
            plages.append((debut, debut + duree))
        if ok:
            break
    else:
        plages = plages[:1]                                          # journée trop courte : un seul rendez-vous plutôt qu'un chevauchement
        types = types[:1]
    evenements = []
    ordre = sorted(range(len(plages)), key=lambda i: plages[i][0])
    for i in ordre:
        type_, duree, titres = types[i]
        b, e = plages[i]
        evenements.append({
            "type": type_, "titre": rng.choice(titres).replace("{s}", structures[i % len(structures)]),
            "debut": datetime.combine(jour, time(b // 60, b % 60)), "fin": datetime.combine(jour, time(e // 60, e % 60))})
    return evenements


def jours_a_generer(aujourdhui: date, nb_jours: int, jours_ouvres: List[int], deja: Dict[str, Any]) -> List[date]:
    """Jours ouvrés des `nb_jours` prochains jours (aujourd'hui compris) qui n'ont pas encore leur programme."""
    ouvres = set(jours_ouvres or JOURS_OUVRES_DEFAUT)
    return [d for d in (aujourdhui + timedelta(days=k) for k in range(max(1, min(int(nb_jours), 14))))
            if d.weekday() in ouvres and d.isoformat() not in (deja or {})]


def reglages(s: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Réglages (désactivé par défaut), bornés."""
    s = s or {}

    def entier(cle: str, defaut: int, mini: int, maxi: int) -> int:
        try:
            return max(mini, min(maxi, int(s.get(cle) if s.get(cle) not in (None, "") else defaut)))
        except (TypeError, ValueError):
            return defaut
    mini = entier("rdv_fictifs_min", 2, 1, 6)
    return {"actif": bool(s.get("rdv_fictifs_actif")), "mini": mini, "maxi": max(mini, entier("rdv_fictifs_max", 4, 1, 6)),
            "jours": entier("rdv_fictifs_jours", 7, 1, 14), "bloquent": bool(s.get("rdv_fictifs_bloquent")),
            "agenda": str(s.get("rdv_fictifs_agenda") or AGENDA_DEFAUT).strip().lower()[:120],
            "jours_ouvres": [int(j) for j in (s.get("business_days") if isinstance(s.get("business_days"), list) else JOURS_OUVRES_DEFAUT)
                             if str(j).isdigit() and 0 <= int(j) <= 6] or JOURS_OUVRES_DEFAUT,
            "ouverture": str(s.get("business_open_time") or HEURE_OUVERTURE), "fermeture": str(s.get("business_close_time") or HEURE_FERMETURE)}


def corps_evenement(ev: Dict[str, Any], bloquent: bool) -> Dict[str, Any]:
    """Corps JSON envoyé à Google Agenda : sans invité, sans rappel, « disponible » sauf réglage contraire."""
    return {"summary": ev["titre"], "description": f"{MARQUE}\nType : {ev['type']}.",
            "start": {"dateTime": ev["debut"].isoformat(), "timeZone": FUSEAU},
            "end": {"dateTime": ev["fin"].isoformat(), "timeZone": FUSEAU},
            "transparency": "opaque" if bloquent else "transparent",
            "reminders": {"useDefault": False},
            "extendedProperties": {"private": {"sawali_fictif": "1"}}}


# ---------------------------------------------------------------------------------------------------------------------
# Google Agenda (injectable pour les tests)
# ---------------------------------------------------------------------------------------------------------------------
async def _agenda_relie(db) -> str:
    s = await db.settings.find_one({"_id": "global"}) or {}
    return str(s.get("google_calendar_email") or "primary").strip().lower()


async def creer_google(calendrier: str, corps: Dict[str, Any]) -> Dict[str, Any]:
    """Crée l'événement dans Google Agenda → {id} ou {erreur}. Ne lève jamais."""
    try:
        import google_calendar as gc
        service = await gc._build_service()
        if service is None:
            return {"erreur": "Google Agenda non configuré ou jeton expiré (Paramètres → Google Agenda)"}
        ev = await asyncio.to_thread(service.events().insert(calendarId=calendrier, body=corps).execute)
        return {"id": ev.get("id")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[rdv_fictifs] création impossible : %s", exc)
        return {"erreur": str(exc)[:200]}


async def supprimer_google(calendrier: str, event_id: str) -> bool:
    """Supprime un événement ; un événement déjà absent compte comme supprimé."""
    try:
        import google_calendar as gc
        service = await gc._build_service()
        if service is None:
            return False
        await asyncio.to_thread(service.events().delete(calendarId=calendrier, eventId=event_id).execute)
        return True
    except Exception as exc:  # noqa: BLE001
        texte = str(exc)
        return "404" in texte or "410" in texte or "notFound" in texte or "deleted" in texte.lower()


# ---------------------------------------------------------------------------------------------------------------------
# Passage du matin
# ---------------------------------------------------------------------------------------------------------------------
async def generer(db, maintenant: Optional[datetime] = None, creer: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
                  forcer: bool = False) -> Dict[str, Any]:
    """Prépare les rendez-vous fictifs des prochains jours qui n'ont pas encore de programme. Ne lève jamais.
    Désactivé → rien (sauf `forcer`, bouton manuel). Agenda relié ≠ agenda visé → rien, avec l'explication.
    → {actif, agenda, jours, evenements, erreur?, details[]}"""
    creer = creer or creer_google
    maintenant = maintenant or datetime.now(timezone.utc)
    rapport: Dict[str, Any] = {"le": maintenant.isoformat(), "actif": False, "jours": 0, "evenements": 0, "details": []}
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        r = reglages(s)
        rapport["actif"], rapport["agenda"] = r["actif"], r["agenda"]
        if not r["actif"] and not forcer:
            return rapport
        relie = await _agenda_relie(db)
        if relie != r["agenda"]:
            rapport["erreur"] = (f"L'agenda relié à SAWALI est « {relie} », pas « {r['agenda']} » : aucun rendez-vous créé. "
                                 "Reliez le bon compte Google (Paramètres → Google Agenda) ou changez l'agenda visé.")
            return rapport
        suivi = await db.settings.find_one({"_id": DOC_ID}) or {}
        evenements = dict(suivi.get("evenements") or {})
        aujourdhui = maintenant.astimezone(ZoneInfo(FUSEAU)).date()
        for jour in jours_a_generer(aujourdhui, r["jours"], r["jours_ouvres"], evenements):
            crees = []
            for ev in generer_jour(jour, r["mini"], r["maxi"], r["ouverture"], r["fermeture"]):
                res = await creer(relie, corps_evenement(ev, r["bloquent"]))
                if res.get("id"):
                    crees.append({"id": res["id"], "titre": ev["titre"], "type": ev["type"],
                                  "debut": ev["debut"].isoformat(), "fin": ev["fin"].isoformat()})
                else:
                    rapport["erreur"] = res.get("erreur") or "création refusée"
                    break
            if crees:
                evenements[jour.isoformat()] = crees
                rapport["jours"] += 1
                rapport["evenements"] += len(crees)
                rapport["details"].append({"jour": jour.isoformat(), "evenements": [e["titre"] for e in crees]})
            if rapport.get("erreur"):
                break                                                # inutile d'insister si Google refuse
        # On ne garde que les 14 derniers jours passés et les jours à venir
        limite = (aujourdhui - timedelta(days=14)).isoformat()
        evenements = {j: v for j, v in evenements.items() if j >= limite}
        await db.settings.update_one({"_id": DOC_ID}, {"$set": {"evenements": evenements, "dernier": rapport}}, upsert=True)
    except Exception as exc:  # noqa: BLE001 — la tâche du matin ne doit jamais s'arrêter sur une erreur
        logger.warning("[rdv_fictifs] passage en échec : %s", exc, exc_info=True)
        rapport["erreur"] = str(exc)[:200]
    return rapport


async def supprimer_tout(db, supprimer: Optional[Callable[..., Awaitable[bool]]] = None) -> Dict[str, Any]:
    """Supprime UNIQUEMENT les rendez-vous fictifs créés par ce module (identifiants gardés dans le document de suivi)."""
    supprimer = supprimer or supprimer_google
    suivi = await db.settings.find_one({"_id": DOC_ID}) or {}
    evenements = dict(suivi.get("evenements") or {})
    relie = await _agenda_relie(db)
    supprimes, restes = 0, {}
    for jour, liste in evenements.items():
        gardes = []
        for ev in liste:
            if await supprimer(relie, ev["id"]):
                supprimes += 1
            else:
                gardes.append(ev)
        if gardes:
            restes[jour] = gardes
    await db.settings.update_one({"_id": DOC_ID}, {"$set": {"evenements": restes}}, upsert=True)
    return {"supprimes": supprimes, "restants": sum(len(v) for v in restes.values())}


# ---------------------------------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------------------------------
class ReglagesIn(BaseModel):
    actif: bool = False
    mini: int = Field(default=2, ge=1, le=6)
    maxi: int = Field(default=4, ge=1, le=6)
    jours: int = Field(default=7, ge=1, le=14)
    bloquent: bool = False
    agenda: str = Field(default=AGENDA_DEFAUT, max_length=120)


def setup_rdv_fictifs_routes(*, db, api, get_current_admin) -> None:
    """Branche les routes du lot 211 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException

    async def _etat() -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        suivi = await db.settings.find_one({"_id": DOC_ID}) or {}
        r = reglages(s)
        aujourdhui = datetime.now(ZoneInfo(FUSEAU)).date().isoformat()
        a_venir = [{"jour": j, "evenements": v} for j, v in sorted((suivi.get("evenements") or {}).items()) if j >= aujourdhui]
        return {**r, "agenda_relie": await _agenda_relie(db), "a_venir": a_venir, "dernier": suivi.get("dernier")}

    @api.get("/admin/rdv-fictifs", tags=["Admin — Rendez-vous fictifs"])
    async def lire(_: dict = Depends(get_current_admin)):
        """Réglages, agenda relié, rendez-vous fictifs à venir et dernier passage de Liluvine."""
        return await _etat()

    @api.put("/admin/rdv-fictifs", tags=["Admin — Rendez-vous fictifs"])
    async def ecrire(data: ReglagesIn, _: dict = Depends(get_current_admin)):
        if data.maxi < data.mini:
            raise HTTPException(status_code=422, detail="Le maximum par jour doit être au moins égal au minimum.")
        await db.settings.update_one({"_id": "global"}, {"$set": {
            "rdv_fictifs_actif": bool(data.actif), "rdv_fictifs_min": data.mini, "rdv_fictifs_max": data.maxi,
            "rdv_fictifs_jours": data.jours, "rdv_fictifs_bloquent": bool(data.bloquent),
            "rdv_fictifs_agenda": data.agenda.strip().lower() or AGENDA_DEFAUT}}, upsert=True)
        return await _etat()

    @api.post("/admin/rdv-fictifs/generer", tags=["Admin — Rendez-vous fictifs"])
    async def generer_maintenant(_: dict = Depends(get_current_admin)):
        """Génère maintenant les jours qui n'ont pas encore de programme (même si la génération quotidienne est désactivée)."""
        return await generer(db, forcer=True)

    @api.post("/admin/rdv-fictifs/supprimer", tags=["Admin — Rendez-vous fictifs"])
    async def supprimer_les_fictifs(_: dict = Depends(get_current_admin)):
        """Supprime les rendez-vous fictifs créés par Liluvine (et eux seulement) de Google Agenda."""
        return await supprimer_tout(db)
