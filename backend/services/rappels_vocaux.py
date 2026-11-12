"""Lot 374 — RAPPELS VOCAUX PROGRAMMÉS sur Alexa (Voice Monkey).

Le propriétaire programme une phrase, une date et une heure (GMT) ; à l'heure dite, SAWALI la fait annoncer par Alexa.
Répétition possible : aucune, chaque jour, chaque semaine. Un rappel manqué de plus d'une heure (serveur arrêté) n'est pas
annoncé en retard : il est marqué « manqué » (ou, s'il se répète, reporté à la prochaine occurrence).

Stockage : UN SEUL document de la collection `settings` (`_id = "rappels_vocaux"`, champ `rappels`) — aucune nouvelle
collection (le cluster MongoDB est plein, règle permanente). Mises à jour par opérateurs atomiques ($push, $pull, $set positionnel).

Logique pure (validation, prochaine occurrence, rappels dus) séparée de l'accès à la base : testée sans base ni réseau.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sawali.rappels_vocaux")

DOC_ID = "rappels_vocaux"
REPETITIONS = {"aucune": "Une seule fois", "jour": "Chaque jour", "semaine": "Chaque semaine"}
TEXTE_MAX = 180                      # Voice Monkey / Alexa : annonce courte (le service coupe à 200 caractères)
RETARD_MAX_MIN = 60                  # au-delà, le rappel est « manqué » au lieu d'être annoncé en retard
CONSERVATION_JOURS = 7               # les rappels terminés restent visibles une semaine


def maintenant_utc() -> datetime:
    return datetime.now(timezone.utc)


def lire_date(valeur: Any) -> datetime:
    """Date ISO 8601 → datetime UTC ; sans fuseau, la date est considérée comme étant en GMT/UTC. ValueError si illisible."""
    if isinstance(valeur, datetime):
        d = valeur
    else:
        t = str(valeur or "").strip()
        if not t:
            raise ValueError("Date et heure obligatoires.")
        try:
            d = datetime.fromisoformat(t.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Date et heure illisibles (format attendu : AAAA-MM-JJTHH:MM).") from exc
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def valider_rappel(donnees: Dict[str, Any], maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Vérifie une demande de rappel et retourne {texte, quand (datetime UTC), repetition} ; ValueError avec un message clair sinon."""
    maintenant = maintenant or maintenant_utc()
    texte = " ".join(str(donnees.get("texte") or "").split())
    if not texte:
        raise ValueError("Écrivez la phrase à annoncer.")
    if len(texte) > TEXTE_MAX:
        raise ValueError(f"Phrase trop longue ({len(texte)} caractères, maximum {TEXTE_MAX}).")
    repetition = str(donnees.get("repetition") or "aucune").strip().lower()
    if repetition not in REPETITIONS:
        raise ValueError("Répétition inconnue (aucune, jour ou semaine).")
    quand = lire_date(donnees.get("quand"))
    if quand < maintenant - timedelta(minutes=1):
        raise ValueError("Cette date est déjà passée.")
    return {"texte": texte, "quand": quand, "repetition": repetition}


def prochaine_occurrence(quand: datetime, repetition: str, maintenant: datetime) -> Optional[datetime]:
    """Prochaine date STRICTEMENT après `maintenant` pour un rappel répété ; None pour « aucune »."""
    pas = {"jour": timedelta(days=1), "semaine": timedelta(weeks=1)}.get(repetition)
    if pas is None:
        return None
    prochaine = quand
    while prochaine <= maintenant:
        prochaine += pas
    return prochaine


def rappels_dus(rappels: List[Dict[str, Any]], maintenant: datetime) -> List[Dict[str, Any]]:
    """Rappels en attente dont l'heure est arrivée, du plus ancien au plus récent."""
    dus = []
    for r in rappels or []:
        if r.get("statut") != "en_attente":
            continue
        try:
            if lire_date(r.get("quand")) <= maintenant:
                dus.append(r)
        except ValueError:
            continue
    return sorted(dus, key=lambda r: str(r.get("quand")))


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


async def lister(db) -> List[Dict[str, Any]]:
    doc = await db.settings.find_one({"_id": DOC_ID}, {"_id": 0, "rappels": 1}) or {}
    return sorted(doc.get("rappels") or [], key=lambda r: (r.get("statut") != "en_attente", str(r.get("quand"))))


async def ajouter(db, donnees: Dict[str, Any], auteur: str = "") -> Dict[str, Any]:
    v = valider_rappel(donnees)
    rappel = {"id": uuid.uuid4().hex[:12], "texte": v["texte"], "quand": _iso(v["quand"]), "repetition": v["repetition"],
              "statut": "en_attente", "cree_par": auteur, "cree_le": _iso(maintenant_utc()), "motif": ""}
    await db.settings.update_one({"_id": DOC_ID}, {"$push": {"rappels": rappel}}, upsert=True)
    return rappel


async def supprimer(db, rappel_id: str) -> bool:
    r = await db.settings.update_one({"_id": DOC_ID}, {"$pull": {"rappels": {"id": rappel_id}}})
    return bool(r.modified_count)


async def purger(db, maintenant: Optional[datetime] = None) -> None:
    """Retire les rappels terminés depuis plus d'une semaine."""
    limite = _iso((maintenant or maintenant_utc()) - timedelta(days=CONSERVATION_JOURS))
    await db.settings.update_one({"_id": DOC_ID}, {"$pull": {"rappels": {"statut": {"$ne": "en_attente"}, "termine_le": {"$lt": limite}}}})


async def executer_rappels_dus(db, maintenant: Optional[datetime] = None, annoncer=None) -> List[Dict[str, Any]]:
    """Appelé chaque minute : annonce les rappels dus sur Alexa. Retourne le compte rendu [{id, statut, motif}]. Ne lève jamais d'exception."""
    maintenant = maintenant or maintenant_utc()
    if annoncer is None:
        from services.alexa import alexa_annoncer
        annoncer = lambda texte: alexa_annoncer(db, texte)  # noqa: E731
    compte_rendu: List[Dict[str, Any]] = []
    try:
        doc = await db.settings.find_one({"_id": DOC_ID}, {"_id": 0, "rappels": 1}) or {}
        for r in rappels_dus(doc.get("rappels") or [], maintenant):
            quand = lire_date(r["quand"])
            retard_min = (maintenant - quand).total_seconds() / 60
            manque = retard_min > RETARD_MAX_MIN
            ok, motif = (False, "Manqué : le serveur n'a pas pu l'annoncer à l'heure.") if manque else await annoncer(r["texte"])
            suite = prochaine_occurrence(quand, r.get("repetition", "aucune"), maintenant)
            maj: Dict[str, Any] = {"rappels.$.derniere_annonce": _iso(maintenant) if ok else r.get("derniere_annonce", "")}
            if suite is not None:                                   # rappel répété : reste en attente, prochaine occurrence
                maj.update({"rappels.$.quand": _iso(suite), "rappels.$.motif": "" if ok else motif})
                statut = "annonce" if ok else ("manque" if manque else "echec")
            else:
                statut = "annonce" if ok else ("manque" if manque else "echec")
                maj.update({"rappels.$.statut": statut, "rappels.$.motif": motif, "rappels.$.termine_le": _iso(maintenant)})
            await db.settings.update_one({"_id": DOC_ID, "rappels.id": r["id"]}, {"$set": maj})
            compte_rendu.append({"id": r["id"], "statut": statut, "motif": motif})
        if compte_rendu:
            await purger(db, maintenant)
    except Exception:  # noqa: BLE001
        logger.exception("[rappels-vocaux] exécution impossible")
    return compte_rendu
