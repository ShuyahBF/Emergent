"""Lot 54 — Tickets Liluvine partagés par client, clôture vers l'historique d'intervention,
validité des tickets (clients non contractuels), facturation et sessions WhatsApp minutées.

1. TICKET VALABLE POUR TOUT LE CLIENT
   Un ticket généré, ou en cours et non clôturé (statuts open / in_progress / suspended, non
   archivé), couvre TOUS les contacts du client lié (`support_tickets.client_id`). Les contacts
   d'un client sont :
     - les fiches `directory_contacts` / `contacts` dont `client_id` ou `linked_client_id` est
       ce client (sauf si ce compte est celui de la plateforme ou d'un Superviseur : le carnet
       d'adresses de l'opérateur contient les contacts de tous les clients ; et sauf si ce client
       est le compte qui reçoit la conversation : les propres contacts d'un client sur SON numéro
       WhatsApp, ses patients par exemple, ne sont pas couverts par le ticket de support de ce
       client) ;
     - les contacts déjà rattachés à un ticket de ce client (`contact_id`, `contact_ids`).
   Tant que le ticket est ouvert, aucun nouveau ticket n'est créé pour ce client : le contact est
   rattaché au ticket existant (`contact_ids`) et Liluvine agit sous ce ticket dans la
   conversation de n'importe lequel de ces contacts (actions notées dans `liluvine_actions`).

2. CLÔTURE → HISTORIQUE D'INTERVENTION
   À la clôture (manuelle, fin de session WhatsApp ou fin de validité), une intervention est
   créée avec `date_heure_debut` = création du ticket (`opened_at`, choix retenu : c'est aussi le
   point de départ de la validité et de la durée facturée), `date_heure_fin` = clôture, et un lien
   vers le ticket (`source_ticket_id`, `source_ticket_number`, `ticket_url`).

3. VALIDITÉ (clients non contractuels = sans numéro de contrat sur la fiche)
   `users.ticket_validite_heures` (0 ou vide = illimitée), comptée depuis la création du ticket.
   À l'échéance, le planificateur clôture le ticket (« validite_expiree ») et journalise.

4. FACTURATION (à la clôture)
   Durée active (hors suspensions) < seuil → coût horaire × durée ; durée ≥ seuil → coût
   forfaitaire de la fiche. Seuil `users.ticket_seuil_forfait_heures` (défaut 5 h). Champs de tarif
   existants réutilisés : `hourly_rate` et `flat_rate`. Sans forfait renseigné (0), le coût
   horaire s'applique au-delà du seuil (mode « hourly_sans_forfait »).

5. SESSION WHATSAPP PAR TICKET
   Durée `users.ticket_session_wa_minutes` (défaut du client, 0 = pas de limite), modifiable par
   ticket (`support_tickets.session_wa_minutes`). La session commence à la création du ticket.
   Rappels dans la conversation à T-10 et T-5 minutes (un seul envoi chacun, garanti par une
   mise à jour conditionnelle), puis fermeture automatique avec un message de clôture.
   Modèle du rappel : `users.ticket_message_rappel` ({X} minutes restantes, {Y} n° du ticket,
   {Z} durée de session) ; message de clôture : `users.ticket_message_fermeture`.
   Envoi par la fonction d'envoi WhatsApp existante, seulement si la fenêtre de 24 h du contact
   est ouverte ; sinon (ou en cas d'échec) l'événement est journalisé (`tickets_wa_journal`).
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import quote

from db import db

logger = logging.getLogger("sawali.tickets_clients")

STATUTS_OUVERTS = ["open", "in_progress", "suspended"]
STATUTS_CLOS = {"done", "cancelled"}
SEUIL_FORFAIT_H_DEFAUT = 5.0
RAPPELS_MIN = (10, 5)                 # rappels avant la fermeture automatique (minutes)
FENETRE_WA_S = 24 * 3600              # fenêtre de service client de Meta
JOURNAL = "tickets_wa_journal"
COMPTE_PLATEFORME = "admin@sawalismartsystems.com"

MESSAGE_RAPPEL_DEFAUT = ("Il vous reste {X} mn avant la fermeture automatique de ce ticket n°{Y}. "
                         "Parce que d'autres interventions nous attendent, nos sessions sont limitées à {Z} mn.")
MESSAGE_FERMETURE_DEFAUT = ("Le ticket n°{Y} est maintenant fermé : la durée de session de {Z} mn est écoulée. "
                            "Merci de votre compréhension.")

EnvoiFn = Callable[..., Awaitable[Any]]
_index_ok = {"fait": False}


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------
def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _date(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _nombre(v: Any, defaut: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else defaut
    except (TypeError, ValueError):
        return defaut


def _chiffres(v: Any) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def _est_compte_operateur(u: Optional[dict]) -> bool:
    """Compte de la plateforme ou Superviseur : son carnet contient les contacts de tous les clients."""
    if not u:
        return False
    email = (u.get("email") or "").strip().lower()
    plateforme = (os.environ.get("SUPER_ADMIN_EMAIL") or COMPTE_PLATEFORME).strip().lower()
    return email in {plateforme, COMPTE_PLATEFORME} or u.get("role") == "superviseur"


def remplir_modele(modele: str, *, x: Any = "", y: Any = "", z: Any = "") -> str:
    """Remplace {X}, {Y}, {Z} (casse indifférente) ; les autres accolades restent telles quelles."""
    valeurs = {"X": x, "Y": y, "Z": z}
    return re.sub(r"\{([XYZxyz])\}", lambda m: str(valeurs[m.group(1).upper()]), modele or "")


async def assurer_index() -> None:
    if _index_ok["fait"]:
        return
    try:
        await db.support_tickets.create_index([("client_id", 1), ("status", 1)])
        await db.support_tickets.create_index("contact_ids")
        await db.support_tickets.create_index("contact_id")
        await db.support_tickets.create_index([("status", 1), ("session_wa_fin", 1)])
        await db.support_tickets.create_index([("status", 1), ("validite_expire_le", 1)])
        await db[JOURNAL].create_index([("ticket_id", 1), ("date", -1)])
        await db.interventions.create_index("source_ticket_id")
    except Exception:  # noqa: BLE001 — base simulée ou droits insuffisants : non bloquant
        logger.debug("[tickets_clients] index non créés", exc_info=True)
    _index_ok["fait"] = True


# ---------------------------------------------------------------------------
# Réglages de la fiche client / tenant
# ---------------------------------------------------------------------------
def client_contractuel(client_doc: Optional[dict]) -> bool:
    """Client sous contrat = un numéro de contrat est renseigné sur sa fiche."""
    return bool(((client_doc or {}).get("contract_number") or "").strip())


def reglages_client(client_doc: Optional[dict]) -> Dict[str, Any]:
    c = client_doc or {}
    seuil = _nombre(c.get("ticket_seuil_forfait_heures"), SEUIL_FORFAIT_H_DEFAUT)
    return {
        "taux_horaire": _nombre(c.get("hourly_rate")),
        "forfait": _nombre(c.get("flat_rate")),
        "seuil_forfait_heures": seuil if seuil > 0 else SEUIL_FORFAIT_H_DEFAUT,
        "validite_heures": max(0.0, _nombre(c.get("ticket_validite_heures"))),
        "session_wa_minutes": max(0, int(_nombre(c.get("ticket_session_wa_minutes")))),
        "message_rappel": (c.get("ticket_message_rappel") or "").strip() or MESSAGE_RAPPEL_DEFAUT,
        "message_fermeture": (c.get("ticket_message_fermeture") or "").strip() or MESSAGE_FERMETURE_DEFAUT,
        "contractuel": client_contractuel(c),
    }


async def lire_client(client_id: Optional[str]) -> dict:
    if not client_id:
        return {}
    return await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0}) or {}


def champs_creation(client_doc: dict, opened_at: str) -> Dict[str, Any]:
    """Champs lot 54 posés sur un ticket à sa création (session WhatsApp, validité)."""
    r = reglages_client(client_doc)
    debut = _date(opened_at) or maintenant()
    champs: Dict[str, Any] = {
        "client_contractuel": r["contractuel"],
        "session_wa_minutes": r["session_wa_minutes"] or None,
        "session_wa_debut": _iso(debut),
        "session_wa_fin": _iso(debut + timedelta(minutes=r["session_wa_minutes"])) if r["session_wa_minutes"] else None,
        "rappels_envoyes": [],
        "validite_heures": None,
        "validite_expire_le": None,
    }
    if not r["contractuel"] and r["validite_heures"] > 0:
        champs["validite_heures"] = r["validite_heures"]
        champs["validite_expire_le"] = _iso(debut + timedelta(hours=r["validite_heures"]))
    return champs


# ---------------------------------------------------------------------------
# 1. Ticket partagé par tous les contacts du client
# ---------------------------------------------------------------------------
async def clients_du_contact(contact_id: Optional[str], contact: Optional[dict] = None,
                             scope_conversation: Optional[str] = None) -> List[str]:
    """Clients liés à un contact : sa fiche (hors carnet de l'opérateur et hors compte qui reçoit la
    conversation, `scope_conversation`) + ses tickets passés."""
    if not contact_id and not contact:
        return []
    if contact is None:
        contact = (await db.directory_contacts.find_one({"id": contact_id}, {"_id": 0})
                   or await db.contacts.find_one({"id": contact_id}, {"_id": 0}) or {})
    contact_id = contact_id or contact.get("id")
    ids: List[str] = []
    for cle in ("linked_client_id", "client_id"):
        cid = contact.get(cle)
        if cid and cid not in ids and cid != scope_conversation:
            compte = await db.users.find_one({"id": cid}, {"_id": 0, "id": 1, "email": 1, "role": 1})
            if compte and not _est_compte_operateur(compte):
                ids.append(cid)
    if contact_id:
        async for t in db.support_tickets.find(
                {"$or": [{"contact_id": contact_id}, {"contact_ids": contact_id}]}, {"_id": 0, "client_id": 1}):
            if t.get("client_id") and t["client_id"] not in ids:
                ids.append(t["client_id"])
    return ids


def _filtre_ouvert() -> Dict[str, Any]:
    return {"status": {"$in": STATUTS_OUVERTS}, "archived_at": {"$in": [None, ""]}}


async def ticket_ouvert_du_client(client_id: Optional[str]) -> Optional[dict]:
    if not client_id:
        return None
    return await db.support_tickets.find_one({**_filtre_ouvert(), "client_id": client_id}, {"_id": 0},
                                             sort=[("opened_at", -1)])


async def ticket_ouvert_pour_contact(contact_id: Optional[str], contact: Optional[dict] = None,
                                     client_id: Optional[str] = None,
                                     scope_conversation: Optional[str] = None) -> Optional[dict]:
    """Ticket ouvert qui couvre ce contact : rattaché directement, ou ouvert pour l'un de ses clients
    (ou pour `client_id` si l'appelant le connaît déjà)."""
    ou: List[Dict[str, Any]] = []
    if contact_id:
        ou += [{"contact_id": contact_id}, {"contact_ids": contact_id}]
    clients = await clients_du_contact(contact_id, contact, scope_conversation)
    if client_id and client_id not in clients:
        clients.append(client_id)
    if clients:
        ou.append({"client_id": {"$in": clients}})
    if not ou:
        return None
    return await db.support_tickets.find_one({**_filtre_ouvert(), "$or": ou}, {"_id": 0},
                                             sort=[("opened_at", -1)])


async def rattacher_contact(ticket: dict, contact_id: Optional[str], *, par: Optional[dict] = None) -> dict:
    """Ajoute le contact au ticket partagé (idempotent) et journalise la première fois."""
    if not contact_id:
        return ticket
    deja = contact_id == ticket.get("contact_id") or contact_id in (ticket.get("contact_ids") or [])
    maj: Dict[str, Any] = {"$addToSet": {"contact_ids": {"$each": [c for c in (ticket.get("contact_id"), contact_id) if c]}}}
    await db.support_tickets.update_one({"id": ticket["id"]}, maj)
    if not deja:
        await journaliser(ticket, "contact_rattache", contact_id=contact_id,
                          detail=f"Contact rattaché au ticket partagé par {(par or {}).get('full_name') or (par or {}).get('email') or 'Liluvine'}")
    return await db.support_tickets.find_one({"id": ticket["id"]}, {"_id": 0}) or ticket


async def noter_action_liluvine(*, inbound: dict, contact: Optional[dict], resultat: Optional[dict]) -> Optional[str]:
    """Appelé par le webhook WhatsApp après la décision de Liluvine : si un ticket ouvert couvre ce
    contact (ou l'un des contacts de son client), le message et l'action sont rattachés au ticket.
    Renvoie l'identifiant du ticket, ou None."""
    contact_id = (contact or {}).get("id") or inbound.get("contact_id")
    if not contact_id:
        return None
    ticket = await ticket_ouvert_pour_contact(contact_id, contact, scope_conversation=inbound.get("client_id"))
    if not ticket:
        return None
    ticket = await rattacher_contact(ticket, contact_id)
    action = {"le": _iso(maintenant()), "contact_id": contact_id,
              "message_id": inbound.get("id"), "repondu": bool((resultat or {}).get("ok")),
              "commande": (resultat or {}).get("command"),
              "motif": str((resultat or {}).get("reason") or "")[:120] or None}
    await db.support_tickets.update_one({"id": ticket["id"]}, {
        "$push": {"liluvine_actions": {"$each": [action], "$slice": -100}},
        "$inc": {"liluvine_actions_total": 1},
        "$set": {"derniere_activite_wa": action["le"]}})
    if inbound.get("id"):
        await db.whatsapp_messages.update_one({"id": inbound["id"]}, {"$set": {
            "ticket_id": ticket["id"], "ticket_number": ticket.get("number")}})
    return ticket["id"]


# ---------------------------------------------------------------------------
# 4. Facturation
# ---------------------------------------------------------------------------
def calculer_facturation(heures: float, client_doc: Optional[dict]) -> Dict[str, Any]:
    """Durée < seuil → horaire × durée ; durée ≥ seuil → forfait de la fiche (s'il est renseigné)."""
    r = reglages_client(client_doc)
    heures = max(0.0, float(heures or 0))
    if heures >= r["seuil_forfait_heures"] and r["forfait"] > 0:
        cout, mode = round(r["forfait"], 2), "flat"
    elif heures >= r["seuil_forfait_heures"]:
        cout, mode = round(heures * r["taux_horaire"], 2), "hourly_sans_forfait"
    else:
        cout, mode = round(heures * r["taux_horaire"], 2), "hourly"
    return {"cost_amount": cout, "cost_mode": mode, "cost_hourly_rate": r["taux_horaire"],
            "cost_flat_rate": r["forfait"], "cost_threshold_hours": r["seuil_forfait_heures"],
            "cost_currency": (client_doc or {}).get("contract_currency") or "XOF", "active_hours": round(heures, 2)}


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------
async def journaliser(ticket: dict, evenement: str, **extra) -> None:
    try:
        await db[JOURNAL].insert_one({
            "id": uuid.uuid4().hex, "date": _iso(maintenant()), "evenement": evenement,
            "ticket_id": ticket.get("id"), "ticket_number": ticket.get("number"),
            "client_id": ticket.get("client_id"), **extra})
    except Exception:  # noqa: BLE001 — le journal ne bloque jamais l'action
        logger.warning("[tickets_clients] journal impossible (%s)", evenement, exc_info=True)


async def _activite(ticket: dict, *, kind: str, action: str, label: str, acteur: dict,
                    target_id: Optional[str] = None) -> None:
    """Fil d'activité (même forme que server._log_activity)."""
    try:
        await db.activity_events.insert_one({
            "id": uuid.uuid4().hex, "client_id": ticket.get("client_id"), "kind": kind, "action": action,
            "label": (label or "")[:160], "target_id": target_id or ticket.get("id"),
            "actor_id": acteur.get("id"), "actor_label": acteur.get("full_name") or acteur.get("email") or "—",
            "ts": _iso(maintenant())})
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 2. Clôture → historique d'intervention
# ---------------------------------------------------------------------------
def _code_slug(valeur: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", valeur or "").upper()
    return (cleaned or "X")[:8]


async def numero_intervention(client_doc: dict) -> str:
    """INT-AAAA-CODE-NNNN, même compteur que server._next_intervention_number."""
    annee = maintenant().year
    code = (client_doc.get("client_code") or "").strip() or _code_slug(
        client_doc.get("company") or client_doc.get("full_name") or "X")
    compteur = f"intervention:{client_doc.get('id')}:{annee}"
    res = await db.counters.find_one_and_update({"_id": compteur}, {"$inc": {"seq": 1}},
                                                upsert=True, return_document=True)
    if res is None:
        res = await db.counters.find_one({"_id": compteur})
    return f"INT-{annee}-{code}-{int((res or {}).get('seq', 1)):04d}"


async def cloturer_ticket(ticket: dict, *, outcome: str, acteur: dict, note: Optional[str] = None,
                          cloture_auto: Optional[str] = None, quand: Optional[datetime] = None,
                          numeroteur: Optional[Callable[[dict], Awaitable[str]]] = None) -> Dict[str, Any]:
    """Clôt le ticket (statut `outcome`), calcule le coût et crée l'intervention de l'historique.
    `cloture_auto` : « session_wa_expiree » ou « validite_expiree » pour les clôtures du planificateur."""
    quand = quand or maintenant()
    fin_iso = _iso(quand)
    maj: Dict[str, Any] = {
        "status": outcome, "outcome": outcome, "resolution_note": note,
        "closed_at": fin_iso, "closed_by_id": acteur.get("id"),
        "closed_by_label": acteur.get("full_name") or acteur.get("email"), "updated_at": fin_iso,
    }
    if cloture_auto:
        maj["cloture_auto"] = cloture_auto
    suspendu = int(ticket.get("suspended_total_seconds") or 0)
    if ticket.get("status") == "suspended" and ticket.get("suspended_started_at"):
        debut_susp = _date(ticket["suspended_started_at"])
        if debut_susp:
            suspendu += max(0, int((quand - debut_susp).total_seconds()))
            maj["suspended_total_seconds"] = suspendu
        maj["suspended_started_at"] = None
    debut = _date(ticket.get("opened_at")) or quand
    actives = max(0, int((quand - debut).total_seconds()) - suspendu)
    heures = round(actives / 3600.0, 2)
    client_doc = await lire_client(ticket.get("client_id"))
    maj.update(calculer_facturation(actives / 3600.0, client_doc))
    # Clôture atomique : un ticket ne peut être clôturé qu'une fois (planificateur et humain en même temps)
    res = await db.support_tickets.update_one({"id": ticket["id"], "status": {"$in": STATUTS_OUVERTS}}, {"$set": maj})
    if not res.modified_count:
        return {"ok": False, "raison": "deja_cloture", "ticket": ticket, "intervention": None}
    ticket = {**ticket, **maj}

    intervention = None
    try:
        numero = await (numeroteur or numero_intervention)({**client_doc, "id": ticket.get("client_id")})
        lignes = [
            f"Origine : Ticket {ticket.get('number') or ''} (id={ticket['id']})".strip(),
            f"Contact : {ticket.get('contact_name') or ticket.get('contact_phone') or '—'}",
            f"Début (création du ticket) : {ticket.get('opened_at')}",
            f"Fin (clôture) : {fin_iso}",
            f"Issue : {outcome}" + (f" — clôture automatique ({cloture_auto})" if cloture_auto else ""),
        ]
        if len(ticket.get("contact_ids") or []) > 1:
            lignes.append(f"Contacts du client couverts par ce ticket : {len(ticket['contact_ids'])}")
        if suspendu:
            lignes.append(f"Temps suspendu : {suspendu // 60} min")
        if note:
            lignes.append(f"Résolution :\n{note}")
        if ticket.get("notes"):
            lignes.append(f"Notes du ticket :\n{ticket['notes']}")
        doc = {
            "id": uuid.uuid4().hex, "client_id": ticket.get("client_id"),
            "title": f"Ticket {ticket.get('number') or ticket['id'][:8]} — {ticket.get('motif') or 'Sans motif'}"[:200],
            "description": "\n\n".join(lignes),
            "status": "completed" if outcome == "done" else "cancelled",
            "intervention_date": fin_iso[:10],
            "technician": ticket.get("closed_by_label"),
            "duration_hours": heures,
            # Lot 54 — date/heure de début et de fin reportées depuis le ticket
            "date_heure_debut": ticket.get("opened_at"), "date_heure_fin": fin_iso,
            "attachments": [], "images": [], "intervention_number": numero,
            "owner_id": acteur.get("id"), "owner_email": acteur.get("email"), "owner_role": acteur.get("role"),
            "source_ticket_id": ticket["id"], "source_ticket_number": ticket.get("number"),
            "ticket_url": "/portal/tickets?numero=" + quote(str(ticket.get("number") or ticket["id"])),
            "cost_amount": maj.get("cost_amount"), "cost_mode": maj.get("cost_mode"),
            "cost_currency": maj.get("cost_currency"),
            "created_at": _iso(maintenant()), "updated_at": _iso(maintenant()),
        }
        await db.interventions.insert_one(dict(doc))
        await db.support_tickets.update_one({"id": ticket["id"]}, {"$set": {"intervention_id": doc["id"],
                                                                           "intervention_number": numero}})
        intervention = {"id": doc["id"], "intervention_number": numero, "duration_hours": heures,
                        "date_heure_debut": doc["date_heure_debut"], "date_heure_fin": fin_iso}
        await _activite(ticket, kind="intervention", action="auto_created",
                        label=f"{numero} (depuis ticket {ticket.get('number') or ''})", acteur=acteur,
                        target_id=doc["id"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[tickets_clients] intervention non créée pour %s : %s", ticket.get("id"), exc)
    await _activite(ticket, kind="ticket", action="closed",
                    label=f"{ticket.get('number')} → {outcome}" + (f" ({cloture_auto})" if cloture_auto else ""),
                    acteur=acteur)
    await journaliser(ticket, "cloture", outcome=outcome, cloture_auto=cloture_auto,
                      intervention_id=(intervention or {}).get("id"))
    return {"ok": True, "ticket": ticket, "intervention": intervention}


# ---------------------------------------------------------------------------
# 5. Session WhatsApp : rappels T-10 / T-5 et fermeture automatique
# ---------------------------------------------------------------------------
async def _dernier_entrant(chiffres: str) -> Optional[dict]:
    if len(chiffres) < 6:
        return None
    return await db.whatsapp_messages.find_one(
        {"direction": "inbound", "phone_digits": {"$regex": re.escape(chiffres[-9:]) + "$"}},
        {"_id": 0, "received_at": 1, "created_at": 1, "client_id": 1}, sort=[("created_at", -1)])


async def destinataires(ticket: dict, quand: datetime) -> List[Dict[str, Any]]:
    """Contacts du ticket avec un numéro WhatsApp et l'état de leur fenêtre de 24 h."""
    ids = [c for c in [ticket.get("contact_id"), *(ticket.get("contact_ids") or [])] if c]
    vus, out = set(), []
    fiches = {}
    for cid in dict.fromkeys(ids):
        f = (await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
             or await db.contacts.find_one({"id": cid}, {"_id": 0}) or {})
        fiches[cid] = f
    candidats = [(cid, f.get("whatsapp") or f.get("phone") or (ticket.get("contact_phone") if cid == ticket.get("contact_id") else None))
                 for cid, f in fiches.items()]
    if not candidats and ticket.get("contact_phone"):
        candidats = [(None, ticket["contact_phone"])]
    for cid, tel in candidats:
        chiffres = _chiffres(tel)
        if not chiffres or chiffres[-9:] in vus:
            continue
        vus.add(chiffres[-9:])
        entrant = await _dernier_entrant(chiffres)
        dernier = _date((entrant or {}).get("received_at") or (entrant or {}).get("created_at"))
        out.append({"contact_id": cid, "telephone": f"+{chiffres}", "chiffres": chiffres,
                    "fenetre_ouverte": bool(dernier and (quand - dernier).total_seconds() < FENETRE_WA_S),
                    "tenant_id": (entrant or {}).get("client_id")})
    return out


async def _envoyer(ticket: dict, texte: str, evenement: str, envoyer: Optional[EnvoiFn], quand: datetime) -> Dict[str, Any]:
    """Envoie `texte` à chaque contact du ticket dont la fenêtre de 24 h est ouverte ; journalise tout."""
    bilan = {"envoyes": 0, "non_envoyes": 0}
    dests = await destinataires(ticket, quand)
    if not dests:
        bilan["non_envoyes"] += 1
        await journaliser(ticket, f"{evenement}_non_envoye", raison="aucun_numero_whatsapp", texte=texte)
        return bilan
    for d in dests:
        if not d["fenetre_ouverte"]:
            bilan["non_envoyes"] += 1
            await journaliser(ticket, f"{evenement}_non_envoye", raison="fenetre_24h_fermee",
                              contact_id=d["contact_id"], telephone=d["telephone"], texte=texte)
            continue
        if envoyer is None:
            bilan["non_envoyes"] += 1
            await journaliser(ticket, f"{evenement}_non_envoye", raison="envoi_indisponible",
                              contact_id=d["contact_id"], telephone=d["telephone"], texte=texte)
            continue
        try:
            res = await envoyer(d["telephone"], texte, tenant_id=d.get("tenant_id"))
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "error": str(exc)[:200]}
        ok = bool((res or {}).get("ok"))
        if ok:
            bilan["envoyes"] += 1
            # Copie dans le fil de la conversation (comme les réponses de Liluvine)
            try:
                await db.whatsapp_messages.insert_one({
                    "id": uuid.uuid4().hex, "direction": "outbound", "to": d["telephone"],
                    "phone_digits": d["chiffres"], "body": texte, "client_id": d.get("tenant_id"),
                    "contact_id": d["contact_id"], "wa_message_id": (res or {}).get("message_id"),
                    "auto_reply": True, "ai_source": "ticket_session_wa", "ticket_id": ticket["id"],
                    "ticket_number": ticket.get("number"), "status": "sent", "wa_status": "sent",
                    "sent_at": _iso(quand), "created_at": _iso(quand)})
            except Exception:  # noqa: BLE001
                pass
        else:
            bilan["non_envoyes"] += 1
        await journaliser(ticket, evenement if ok else f"{evenement}_non_envoye",
                          raison=None if ok else "erreur_envoi", erreur=None if ok else (res or {}).get("error"),
                          contact_id=d["contact_id"], telephone=d["telephone"], texte=texte)
    return bilan


SYSTEME = {"id": "system", "full_name": "Système (planificateur des tickets)", "email": None, "role": "system"}


async def executer_echeances(*, envoyer: Optional[EnvoiFn] = None, quand: Optional[datetime] = None) -> Dict[str, Any]:
    """Passage du planificateur (chaque minute) : rappels T-10/T-5, fin de session WhatsApp,
    fin de validité. Idempotent : chaque rappel et chaque clôture ne se fait qu'une fois."""
    await assurer_index()
    quand = quand or maintenant()
    bilan = {"rappels": 0, "fermetures_session": 0, "expirations": 0, "non_envoyes": 0}

    # Fin de validité (clients non contractuels)
    for t in await db.support_tickets.find({**_filtre_ouvert(), "validite_expire_le": {"$nin": [None, ""], "$lte": _iso(quand)}},
                                           {"_id": 0}).to_list(500):
        r = await cloturer_ticket(t, outcome="done", acteur=SYSTEME, cloture_auto="validite_expiree", quand=quand,
                                  note=f"Clôture automatique : validité de {t.get('validite_heures')} h écoulée "
                                       f"(depuis la création le {t.get('opened_at')}).")
        if r["ok"]:
            bilan["expirations"] += 1
            await journaliser(t, "validite_expiree", validite_heures=t.get("validite_heures"))

    # Sessions WhatsApp minutées
    for t in await db.support_tickets.find({**_filtre_ouvert(), "session_wa_fin": {"$nin": [None, ""]}},
                                           {"_id": 0}).to_list(2000):
        fin = _date(t.get("session_wa_fin"))
        duree = int(t.get("session_wa_minutes") or 0)
        if not fin or duree <= 0:
            continue
        client_doc = await lire_client(t.get("client_id"))
        reg = reglages_client(client_doc)
        restant_s = (fin - quand).total_seconds()
        if restant_s <= 0:
            r = await cloturer_ticket(t, outcome="done", acteur=SYSTEME, cloture_auto="session_wa_expiree", quand=quand,
                                      note=f"Fermeture automatique : durée de session WhatsApp de {duree} mn écoulée.")
            if r["ok"]:
                bilan["fermetures_session"] += 1
                texte = remplir_modele(reg["message_fermeture"], x=0, y=t.get("number"), z=duree)
                b = await _envoyer(t, texte, "message_fermeture", envoyer, quand)
                bilan["non_envoyes"] += b["non_envoyes"]
            continue
        # Rappels dus : le plus proche de l'échéance seulement (un rappel T-10 manqué n'est pas
        # envoyé après le T-5) ; chaque palier n'est réservé qu'une fois (mise à jour conditionnelle).
        dus = [m for m in RAPPELS_MIN if m < duree and restant_s <= m * 60 and m not in (t.get("rappels_envoyes") or [])]
        if not dus:
            continue
        palier = min(dus)
        res = await db.support_tickets.update_one(
            {"id": t["id"], "status": {"$in": STATUTS_OUVERTS}, "rappels_envoyes": {"$nin": dus}},
            {"$addToSet": {"rappels_envoyes": {"$each": dus}}})
        if not res.modified_count:
            continue
        for saute in [m for m in dus if m != palier]:
            await journaliser(t, "rappel_saute", palier_minutes=saute, raison="echeance_deja_plus_proche")
        restant_min = max(1, int(-(-restant_s // 60)))   # arrondi à la minute supérieure
        texte = remplir_modele(reg["message_rappel"], x=restant_min, y=t.get("number"), z=duree)
        b = await _envoyer(t, texte, f"rappel_t{palier}", envoyer, quand)
        bilan["rappels"] += 1
        bilan["non_envoyes"] += b["non_envoyes"]
    return bilan


async def regler_session(ticket: dict, minutes: int, *, par: dict) -> dict:
    """Durée de session WhatsApp propre à ce ticket (0 = pas de limite) ; les rappels repartent."""
    minutes = max(0, min(int(minutes or 0), 24 * 60))
    debut = _date(ticket.get("session_wa_debut") or ticket.get("opened_at")) or maintenant()
    maj = {"session_wa_minutes": minutes or None, "session_wa_debut": _iso(debut),
           "session_wa_fin": _iso(debut + timedelta(minutes=minutes)) if minutes else None,
           "rappels_envoyes": [], "updated_at": _iso(maintenant())}
    await db.support_tickets.update_one({"id": ticket["id"]}, {"$set": maj})
    await journaliser(ticket, "session_wa_reglee", minutes=minutes,
                      par=(par or {}).get("email") or (par or {}).get("id"))
    return {**ticket, **maj}


async def etat_session(ticket: dict, quand: Optional[datetime] = None) -> Dict[str, Any]:
    quand = quand or maintenant()
    fin = _date(ticket.get("session_wa_fin"))
    journal = await db[JOURNAL].find({"ticket_id": ticket["id"]}, {"_id": 0}).sort("date", -1).to_list(50)
    return {"ticket_id": ticket["id"], "number": ticket.get("number"), "status": ticket.get("status"),
            "session_wa_minutes": ticket.get("session_wa_minutes"), "session_wa_debut": ticket.get("session_wa_debut"),
            "session_wa_fin": ticket.get("session_wa_fin"),
            "restant_minutes": max(0, int((fin - quand).total_seconds() // 60)) if fin else None,
            "rappels_envoyes": ticket.get("rappels_envoyes") or [],
            "validite_expire_le": ticket.get("validite_expire_le"), "client_contractuel": ticket.get("client_contractuel"),
            "contact_ids": ticket.get("contact_ids") or [], "liluvine_actions_total": ticket.get("liluvine_actions_total") or 0,
            "journal": journal}
