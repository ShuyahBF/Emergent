"""Lots 374 / 375 — AUTOMATIONS VOCALES sur Alexa (Voice Monkey) : annonces programmées ou déclenchées par un événement.

Trois déclencheurs (page Automations, accessible aussi au Superviseur) :
  • « date »            : à une date et une heure (GMT) — une fois, chaque jour ou chaque semaine (lot 374) ;
  • « rendez_vous »     : N minutes AVANT l'heure d'un rendez-vous (collection `appointments`) ;
  • « message_whatsapp »: à l'arrivée d'un message WhatsApp.
La phrase peut contenir des variables entre accolades : {rdv_date}, {rdv_heure}, {rdv_objet} (rendez-vous) ; {expediteur}, {message}
(message WhatsApp). Chaque règle s'active / se désactive et se teste (annonce immédiate avec un exemple).
Un rappel « date » manqué de plus d'une heure (serveur arrêté) n'est pas annoncé en retard : il est marqué « manqué »
(ou, s'il se répète, reporté à la prochaine occurrence).

Stockage : UN SEUL document de la collection `settings` (`_id = "rappels_vocaux"`, champ `rappels`) — aucune nouvelle
collection (le cluster MongoDB est plein, règle permanente). Mises à jour par opérateurs atomiques ($push, $pull, $set positionnel).

Logique pure (validation, prochaine occurrence, rappels dus) séparée de l'accès à la base : testée sans base ni réseau.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sawali.rappels_vocaux")

DOC_ID = "rappels_vocaux"
REPETITIONS = {"aucune": "Une seule fois", "jour": "Chaque jour", "semaine": "Chaque semaine"}
DECLENCHEURS = {
    "date": "À une date et une heure",
    "rendez_vous": "Avant un rendez-vous",
    "message_whatsapp": "À l'arrivée d'un message WhatsApp",
}
# Variables utilisables dans la phrase, par déclencheur, avec un exemple (pour l'aide et le test)
JETONS = {
    "date": {},
    "rendez_vous": {"rdv_date": "13/11/2026", "rdv_heure": "09:30", "rdv_objet": "Consultation"},
    "message_whatsapp": {"expediteur": "Awa Badini", "message": "Bonjour, je voudrais un rendez-vous"},
}
MINUTES_AVANT_MAX = 1440             # un rendez-vous peut être annoncé jusqu'à 24 h avant
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


def rendre(phrase: str, contexte: Dict[str, Any]) -> str:
    """Remplace les {variables} de la phrase par le contexte ; une variable inconnue devient vide. Espaces normalisés."""
    sortie = re.sub(r"\{([a-z_]+)\}", lambda m: str(contexte.get(m.group(1), "") or ""), phrase or "")
    return " ".join(sortie.split())[:TEXTE_MAX]


def valider_rappel(donnees: Dict[str, Any], maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Vérifie une règle vocale et retourne {declencheur, texte, quand, repetition, minutes_avant} ; ValueError avec un message clair sinon."""
    maintenant = maintenant or maintenant_utc()
    declencheur = str(donnees.get("declencheur") or "date").strip().lower()
    if declencheur not in DECLENCHEURS:
        raise ValueError("Déclencheur inconnu (date, rendez_vous ou message_whatsapp).")
    texte = " ".join(str(donnees.get("texte") or "").split())
    if not texte:
        raise ValueError("Écrivez la phrase à annoncer.")
    if len(texte) > TEXTE_MAX:
        raise ValueError(f"Phrase trop longue ({len(texte)} caractères, maximum {TEXTE_MAX}).")
    resultat: Dict[str, Any] = {"declencheur": declencheur, "texte": texte, "quand": None, "repetition": "aucune", "minutes_avant": 0}
    if declencheur == "date":
        repetition = str(donnees.get("repetition") or "aucune").strip().lower()
        if repetition not in REPETITIONS:
            raise ValueError("Répétition inconnue (aucune, jour ou semaine).")
        quand = lire_date(donnees.get("quand"))
        if quand < maintenant - timedelta(minutes=1):
            raise ValueError("Cette date est déjà passée.")
        resultat.update({"quand": quand, "repetition": repetition})
    elif declencheur == "rendez_vous":
        try:
            minutes = int(donnees.get("minutes_avant"))
        except (TypeError, ValueError):
            raise ValueError("Indiquez combien de minutes avant le rendez-vous.")
        if not 1 <= minutes <= MINUTES_AVANT_MAX:
            raise ValueError(f"Les minutes avant le rendez-vous doivent être entre 1 et {MINUTES_AVANT_MAX}.")
        resultat["minutes_avant"] = minutes
    return resultat


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
        if r.get("statut") != "en_attente" or r.get("actif") is False or (r.get("declencheur") or "date") != "date":
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
    date = v["declencheur"] == "date"
    rappel = {"id": uuid.uuid4().hex[:12], "declencheur": v["declencheur"], "texte": v["texte"],
              "quand": _iso(v["quand"]) if v["quand"] else "", "repetition": v["repetition"], "minutes_avant": v["minutes_avant"],
              "actif": True, "statut": "en_attente" if date else "actif",     # « actif » = règle permanente (rendez-vous, message)
              "nb_declenchements": 0, "dernier_declenchement": "",
              "cree_par": auteur, "cree_le": _iso(maintenant_utc()), "motif": ""}
    await db.settings.update_one({"_id": DOC_ID}, {"$push": {"rappels": rappel}}, upsert=True)
    return rappel


async def basculer(db, rappel_id: str, actif: bool) -> bool:
    """Active ou désactive une règle (sans la supprimer)."""
    r = await db.settings.update_one({"_id": DOC_ID, "rappels.id": rappel_id}, {"$set": {"rappels.$.actif": bool(actif)}})
    return bool(r.matched_count)


async def _compter(db, rappel_id: str, ok: bool, motif: str, maintenant: datetime) -> None:
    maj: Dict[str, Any] = {"rappels.$.dernier_declenchement": _iso(maintenant), "rappels.$.motif": "" if ok else motif}
    await db.settings.update_one({"_id": DOC_ID, "rappels.id": rappel_id}, {"$set": maj, "$inc": {"rappels.$.nb_declenchements": 1 if ok else 0}})


async def tester(db, rappel_id: str, annoncer=None) -> Tuple[bool, str, str]:
    """Annonce MAINTENANT la phrase d'une règle, avec des exemples pour ses variables. Retourne (réussite, motif, phrase annoncée)."""
    if annoncer is None:
        from services.alexa import alexa_annoncer
        annoncer = lambda texte: alexa_annoncer(db, texte)  # noqa: E731
    regle = next((r for r in await lister(db) if r.get("id") == rappel_id), None)
    if regle is None:
        raise KeyError(rappel_id)
    phrase = rendre(regle.get("texte", ""), JETONS.get(regle.get("declencheur") or "date", {}))
    ok, motif = await annoncer(phrase)
    return ok, motif, phrase


async def declencher_evenement(db, declencheur: str, contexte: Dict[str, Any], annoncer=None) -> int:
    """Un événement vient de se produire (ex. message WhatsApp reçu) : annonce la phrase de chaque règle ACTIVE de ce déclencheur.
    Retourne le nombre de règles annoncées ; ne lève jamais d'exception."""
    nb = 0
    try:
        if annoncer is None:
            from services.alexa import alexa_annoncer
            annoncer = lambda texte: alexa_annoncer(db, texte)  # noqa: E731
        maintenant = maintenant_utc()
        for r in await lister(db):
            if (r.get("declencheur") or "date") != declencheur or r.get("actif") is False:
                continue
            ok, motif = await annoncer(rendre(r.get("texte", ""), contexte))
            await _compter(db, r["id"], ok, motif, maintenant)
            nb += 1 if ok else 0
    except Exception:  # noqa: BLE001
        logger.exception("[automations-vocales] déclenchement impossible")
    return nb


async def executer_rendez_vous(db, maintenant: Optional[datetime] = None, annoncer=None) -> int:
    """Rendez-vous qui approchent : pour chaque règle « rendez_vous » active (N minutes avant), annonce chaque rendez-vous non annulé dont
    l'heure tombe dans les N prochaines minutes, UNE SEULE fois par règle (mémorisé dans `appointments.alexa_regles`). Ne lève jamais d'exception."""
    maintenant = maintenant or maintenant_utc()
    nb = 0
    try:
        regles = [r for r in await lister(db) if (r.get("declencheur") or "date") == "rendez_vous" and r.get("actif") is not False]
        if not regles:
            return 0
        if annoncer is None:
            from services.alexa import alexa_annoncer
            annoncer = lambda texte: alexa_annoncer(db, texte)  # noqa: E731
        for r in regles:
            fin = _iso(maintenant + timedelta(minutes=int(r.get("minutes_avant") or 0)))
            rdvs = await db.appointments.find(
                {"scheduled_at": {"$gt": _iso(maintenant - timedelta(minutes=1)), "$lte": fin},
                 "status": {"$nin": ["cancelled", "rejected"]}, "alexa_regles": {"$ne": r["id"]}},
                {"_id": 0, "id": 1, "scheduled_at": 1, "subject": 1}).to_list(100)
            for rdv in rdvs:
                try:
                    quand = lire_date(rdv.get("scheduled_at"))
                except ValueError:
                    continue
                contexte = {"rdv_date": quand.strftime("%d/%m/%Y"), "rdv_heure": quand.strftime("%H:%M"), "rdv_objet": rdv.get("subject") or ""}
                await db.appointments.update_one({"id": rdv["id"]}, {"$addToSet": {"alexa_regles": r["id"]}})     # marqué AVANT : jamais deux annonces
                ok, motif = await annoncer(rendre(r.get("texte", ""), contexte))
                await _compter(db, r["id"], ok, motif, maintenant)
                nb += 1 if ok else 0
    except Exception:  # noqa: BLE001
        logger.exception("[automations-vocales] rendez-vous impossible")
    return nb


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
    await executer_rendez_vous(db, maintenant, annoncer)          # lot 375 : rendez-vous qui approchent
    return compte_rendu
