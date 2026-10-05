"""Lot 58 — Sessions d'assistance « Support Loois » : demande, acceptation, ticket, intervention, Liluvine.

Principe (pour un développeur WinDev)
-------------------------------------
Une SESSION d'assistance = une demande d'un poste Loois, du clic sur « Ecrire Support » jusqu'à la fin :

    attente  ──(un agent SAWALI accepte et choisit le client)──►  active  ──(Terminer / 30 min)──►  terminee
       │                                                                                           (ticket clôturé,
       └──(un agent refuse, avec un motif)──►  refusee                                              intervention créée)
       └──(le poste ferme sa fenêtre avant d'être pris en charge)──►  abandonnee

- À l'ACCEPTATION : un ticket est créé dans les tickets SAWALI (`support_tickets`, même numérotation
  « CLIENT-AAAA-NNNN » que les autres tickets du client) ; son numéro est annoncé dans la discussion et
  reste affiché dans l'en-tête de la fenêtre Loois. Le client choisi est retenu pour ce poste
  (`support_loois_postes.client_id`) et proposé la fois suivante.
- La durée maximale (30 min, `LOOIS_SUPPORT_SESSION_MINUTES`) court à partir de l'acceptation.
- À la FIN (bouton « Terminer la session » côté SAWALI, ou durée écoulée) : le ticket est clôturé par la
  fonction commune `tickets_clients.cloturer_ticket` (facturation, historique) qui crée l'intervention.
- LILUVINE (l'assistante IA de SAWALI) :
    * pendant l'attente, elle répond seule au poste (premier niveau, signée « 🤖 Liluvine ») ;
    * une fois la session acceptée, elle se tait ; l'agent peut lui demander une SUGGESTION de réponse ;
    * à la fin, elle résume la conversation : « Détails du Support », rangés sur le ticket et l'intervention.
  Désactivable par la variable `LOOIS_SUPPORT_LILUVINE=0` (inactive aussi sans clé IA).

Collection `support_loois_sessions` : id, poste_id, poste_nom, statut, en_cours (booléen, vrai en attente /
active), demande_le, acceptee_le, acceptee_par_id/nom, client_id, client_nom, motif, ticket_id,
ticket_number, refusee_le, motif_refus, terminee_le, terminee_par_nom, fin_raison (agent / duree),
intervention_id, intervention_number, details_support.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sawali.support_loois_sessions")

STATUTS_EN_COURS = ("attente", "active")
LILUVINE_ID = "liluvine"
LILUVINE_NOM = "🤖 Liluvine"
MODELE_REPONSE = "claude-haiku-4-5-20251001"   # rapide : réponses dans le chat (même modèle que Liluvine PRO)
MODELE_RESUME = "claude-sonnet-4-5-20250929"    # plus soigné : résumé « Détails du Support »


# =====================================================================
# Outils de date et durée
# =====================================================================
def _date(v: Any) -> Optional[datetime]:
    """Lit une date ISO (avec ou sans fuseau) → datetime UTC, None si illisible."""
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def duree_max_secondes() -> float:
    """Durée maximale d'une session ACCEPTÉE (30 min par défaut, LOOIS_SUPPORT_SESSION_MINUTES)."""
    try:
        minutes = float(os.environ.get("LOOIS_SUPPORT_SESSION_MINUTES") or 30)
    except ValueError:
        minutes = 30.0
    return max(minutes, 0.01) * 60


def restant_secondes(session: Dict[str, Any], maintenant: Optional[datetime] = None) -> Optional[float]:
    """Secondes restantes d'une session active (None si elle n'a pas encore commencé)."""
    debut = _date(session.get("acceptee_le"))
    if session.get("statut") != "active" or not debut:
        return None
    maintenant = maintenant or datetime.now(timezone.utc)
    return duree_max_secondes() - (maintenant - debut).total_seconds()


# =====================================================================
# Trames envoyées au poste Loois
# =====================================================================
def trame_session(session: Dict[str, Any]) -> Dict[str, Any]:
    """État de la session tel que Loois l'affiche (sans les informations internes : client, notes…)."""
    restant = restant_secondes(session)
    return {
        "type": "session",
        "session_id": session.get("id"),
        "statut": session.get("statut"),
        "ticket_number": session.get("ticket_number"),
        "acceptee_le": session.get("acceptee_le"),
        "agent": session.get("acceptee_par_nom"),
        "motif_refus": session.get("motif_refus"),
        "duree_max_s": int(duree_max_secondes()),
        "restant_s": None if restant is None else max(0, int(restant)),
    }


def texte_fin(session: Dict[str, Any]) -> str:
    """Message de fin affiché par Loois (« fin_session »)."""
    if session.get("fin_raison") == "duree":
        debut = f"Session terminée : {int(duree_max_secondes() // 60)} minutes maximum."
    else:
        debut = "Session terminée par le support SAWALI."
    suite = []
    if session.get("ticket_number"):
        suite.append(f"Ticket n° {session['ticket_number']} clôturé")
    if session.get("intervention_number"):
        suite.append(f"intervention {session['intervention_number']} enregistrée")
    return debut + (" " + ", ".join(suite) + "." if suite else "") + " Ouvrez une nouvelle session pour continuer."


# =====================================================================
# Lecture / ouverture d'une session
# =====================================================================
async def session_en_cours(db, pid: str) -> Optional[Dict[str, Any]]:
    """Session en attente ou active de ce poste (None s'il n'y en a pas)."""
    return await db.support_loois_sessions.find_one({"poste_id": pid, "en_cours": True}, {"_id": 0},
                                                    sort=[("demande_le", -1)])


async def lire(db, sid: str) -> Optional[Dict[str, Any]]:
    return await db.support_loois_sessions.find_one({"id": sid}, {"_id": 0})


async def ouvrir_ou_reprendre(db, pid: str, nom: str, now_iso) -> tuple:
    """Reprend la session en cours du poste (reconnexion réseau) ou crée une DEMANDE en attente.
    Renvoie (session, nouvelle)."""
    existante = await session_en_cours(db, pid)
    if existante:
        return existante, False
    poste = await db.support_loois_postes.find_one({"id": pid}, {"_id": 0, "client_id": 1, "ecole": 1}) or {}
    # Lot 58.1 — 1re demande d'un poste : client SAWALI retrouvé par le nom de l'école (s'il correspond)
    if not poste.get("client_id"):
        trouve = await client_par_nom(db, poste.get("ecole"))
        if trouve:
            await associer_client(db, pid, trouve, auto=True)
            poste["client_id"] = trouve
    session = {
        "id": uuid.uuid4().hex, "poste_id": pid, "poste_nom": nom, "statut": "attente", "en_cours": True,
        "demande_le": now_iso(), "client_id_suggere": poste.get("client_id"),
        "acceptee_le": None, "ticket_number": None,
    }
    await db.support_loois_sessions.insert_one(dict(session))
    return session, True


def _normaliser(nom: Optional[str]) -> str:
    """« École des Métiers » → « ecole des metiers » (sans accents, ponctuation ni espaces multiples)."""
    t = unicodedata.normalize("NFKD", nom or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


async def client_par_nom(db, ecole: Optional[str]) -> Optional[str]:
    """Client SAWALI dont la société (ou le nom) est EXACTEMENT celui de l'école (accents et casse ignorés)."""
    cible = _normaliser(ecole)
    if not cible:
        return None
    async for c in db.users.find({"role": "client"}, {"_id": 0, "id": 1, "company": 1, "full_name": 1}):
        if cible in (_normaliser(c.get("company")), _normaliser(c.get("full_name"))):
            return c["id"]
    return None


async def associer_client(db, pid: str, client_id: str, *, auto: bool = False) -> None:
    """Lot 58.1 — associe le poste à un client SAWALI (prompt Liluvine du client, ticket proposé) ;
    la demande en attente de ce poste est mise à jour aussi."""
    await db.support_loois_postes.update_one({"id": pid}, {"$set": {"client_id": client_id, "client_associe_auto": auto}})
    await db.support_loois_sessions.update_one({"poste_id": pid, "statut": "attente"},
                                               {"$set": {"client_id_suggere": client_id}})


async def abandonner_si_en_attente(db, sid: str, now_iso) -> bool:
    """Le poste a fermé sa fenêtre avant d'être pris en charge : la demande disparaît de la liste."""
    res = await db.support_loois_sessions.update_one(
        {"id": sid, "statut": "attente"},
        {"$set": {"statut": "abandonnee", "en_cours": False, "abandonnee_le": now_iso()}})
    return bool(res.modified_count)


# =====================================================================
# Numérotation du ticket (même compteur et même préfixe que server._next_ticket_number)
# =====================================================================
def prefixe_ticket(client_doc: Dict[str, Any]) -> str:
    """« Ecole des Métiers » → « ECOLE DES M TIERS » (règle historique : 20 caractères, majuscules)."""
    brut = client_doc.get("company") or client_doc.get("full_name") or ""
    slug = re.sub(r"[^A-Za-z0-9]+", " ", str(brut)).strip().upper()
    slug = re.sub(r"\s+", " ", slug)[:20].strip()
    return slug or "TKT"


async def numero_ticket(db, client_doc: Dict[str, Any]) -> str:
    """{CLIENT}-AAAA-NNNN, compteur atomique `tickets_{client}_{année}` partagé avec les autres tickets."""
    annee = datetime.now(timezone.utc).year
    compteur = f"tickets_{client_doc['id']}_{annee}"
    res = await db.counters.find_one_and_update({"_id": compteur}, {"$inc": {"seq": 1}},
                                                upsert=True, return_document=True)
    if res is None:  # certains pilotes renvoient None à la création
        res = await db.counters.find_one({"_id": compteur})
    return f"{prefixe_ticket(client_doc)}-{annee}-{int((res or {}).get('seq', 1)):04d}"


def _nom_agent(agent: Dict[str, Any]) -> str:
    return agent.get("full_name") or agent.get("email") or agent.get("id") or "Support SAWALI"


# =====================================================================
# Actions de l'équipe du support
# =====================================================================
class ErreurSession(Exception):
    """Action impossible (code HTTP + message en français)."""

    def __init__(self, code: int, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


async def accepter(db, sid: str, client_id: str, agent: Dict[str, Any], now_iso,
                   motif: Optional[str] = None) -> Dict[str, Any]:
    """Prise en charge : la session devient active, le ticket est créé pour le client choisi."""
    client_doc = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0}) if client_id else None
    if not client_doc:
        raise ErreurSession(400, "Choisissez le client SAWALI de ce poste.")
    maintenant = now_iso()
    # Passage atomique attente → active : deux agents ne peuvent pas accepter la même demande
    res = await db.support_loois_sessions.update_one(
        {"id": sid, "statut": "attente"},
        {"$set": {"statut": "active", "acceptee_le": maintenant, "acceptee_par_id": agent.get("id"),
                  "acceptee_par_nom": _nom_agent(agent), "client_id": client_id,
                  "client_nom": client_doc.get("company") or client_doc.get("full_name")}})
    if not res.modified_count:
        raise ErreurSession(409, "Cette demande n'est plus en attente (déjà prise en charge, refusée ou abandonnée).")
    session = await lire(db, sid)
    motif = (motif or "").strip()[:300] or f"Assistance Loois — {session.get('poste_nom') or session['poste_id']}"

    # Ticket SAWALI (même forme que les tickets ouverts depuis le portail)
    numero = await numero_ticket(db, client_doc)
    ticket = {
        "id": uuid.uuid4().hex, "number": numero, "client_id": client_id,
        "contact_id": session["poste_id"], "contact_name": session.get("poste_nom"), "contact_phone": None,
        "contact_ids": [], "motif": motif, "status": "open", "notes": None,
        "opened_at": maintenant, "opened_by_id": agent.get("id"), "opened_by_label": _nom_agent(agent),
        "closed_at": None, "closed_by_id": None, "closed_by_label": None, "outcome": None,
        "resolution_note": None, "created_at": maintenant, "updated_at": maintenant,
        # Pas de session WhatsApp minutée : la session Loois a sa propre durée
        "session_wa_minutes": None, "session_wa_debut": None, "session_wa_fin": None, "rappels_envoyes": [],
        "source": "support_loois", "support_session_id": sid, "poste_id": session["poste_id"],
    }
    await db.support_tickets.insert_one(dict(ticket))
    await db.support_loois_sessions.update_one({"id": sid}, {"$set": {
        "ticket_id": ticket["id"], "ticket_number": numero, "motif": motif}})
    # Le client est retenu pour ce poste (proposé à la prochaine demande)
    await db.support_loois_postes.update_one({"id": session["poste_id"]}, {"$set": {"client_id": client_id}})
    try:
        await db.activity_events.insert_one({
            "id": uuid.uuid4().hex, "client_id": client_id, "kind": "ticket", "action": "created",
            "label": f"{numero} — {motif[:80]}", "target_id": ticket["id"], "actor_id": agent.get("id"),
            "actor_label": _nom_agent(agent), "ts": maintenant})
    except Exception:  # noqa: BLE001 — le fil d'activité ne bloque jamais l'acceptation
        pass
    return await lire(db, sid)


async def refuser(db, sid: str, agent: Dict[str, Any], now_iso, motif: Optional[str] = None) -> Dict[str, Any]:
    """Refus d'une demande en attente (motif affiché au poste)."""
    res = await db.support_loois_sessions.update_one(
        {"id": sid, "statut": "attente"},
        {"$set": {"statut": "refusee", "en_cours": False, "refusee_le": now_iso(),
                  "refusee_par_nom": _nom_agent(agent),
                  "motif_refus": (motif or "").strip()[:300] or "Le support n'est pas disponible pour le moment."}})
    if not res.modified_count:
        raise ErreurSession(409, "Cette demande n'est plus en attente.")
    return await lire(db, sid)


async def terminer(db, sid: str, agent: Optional[Dict[str, Any]], now_iso, *, raison: str = "agent",
                   tickets=None) -> Dict[str, Any]:
    """Fin d'une session active : ticket clôturé + intervention créée (fonction commune des tickets).
    `tickets` : module tickets_clients (injecté par les tests)."""
    acteur = agent or {"id": "system", "full_name": "Fin automatique de session (Loois)"}
    res = await db.support_loois_sessions.update_one(
        {"id": sid, "statut": "active"},
        {"$set": {"statut": "terminee", "en_cours": False, "terminee_le": now_iso(),
                  "terminee_par_nom": _nom_agent(acteur), "fin_raison": raison}})
    if not res.modified_count:
        raise ErreurSession(409, "Cette session n'est pas active.")
    session = await lire(db, sid)
    ticket = await db.support_tickets.find_one({"id": session.get("ticket_id")}, {"_id": 0}) \
        if session.get("ticket_id") else None
    if ticket:
        try:
            if tickets is None:
                import tickets_clients as tickets  # noqa: PLW0127 — import tardif (base réelle)
            bilan = await tickets.cloturer_ticket(
                ticket, outcome="done", acteur=acteur,
                note="Session d'assistance Loois terminée" + (" (durée maximale atteinte)" if raison == "duree" else ""),
                cloture_auto="session_loois_expiree" if raison == "duree" else None)
            inter = (bilan or {}).get("intervention") or {}
            if inter:
                await db.support_loois_sessions.update_one({"id": sid}, {"$set": {
                    "intervention_id": inter.get("id"), "intervention_number": inter.get("intervention_number")}})
        except Exception:  # noqa: BLE001 — la session se termine même si l'historique échoue
            logger.exception("[support_loois] clôture du ticket %s impossible", ticket.get("id"))
    return await lire(db, sid)


# =====================================================================
# Liluvine
# =====================================================================
def liluvine_active() -> bool:
    """Liluvine répond/résume sauf si LOOIS_SUPPORT_LILUVINE vaut 0/non/off, et seulement avec une clé IA."""
    if (os.environ.get("LOOIS_SUPPORT_LILUVINE") or "1").strip().lower() in ("0", "non", "no", "false", "off"):
        return False
    try:
        from ia_client import cle_ia
        return bool(cle_ia("anthropic"))
    except Exception:  # noqa: BLE001
        return False


async def appeler_ia(systeme: str, texte: str, modele: str) -> str:
    """Appel du modèle (remplacé par une fonction factice dans les tests)."""
    from ia_client import LlmChat, UserMessage, cle_ia
    chat = LlmChat(api_key=cle_ia("anthropic"), session_id=f"support-loois-{uuid.uuid4().hex[:8]}",
                   system_message=systeme).with_model("anthropic", modele).with_params(max_tokens=1500)
    return (await chat.send_message(UserMessage(text=texte)) or "").strip()


async def conversation(db, pid: str, depuis: Optional[str] = None, limite: int = 60) -> List[Dict[str, Any]]:
    """Messages du fil du poste (du plus ancien au plus récent), depuis une date si donnée."""
    q: Dict[str, Any] = {"client_id": "support-loois", "$or": [{"sender_id": pid}, {"recipient_id": pid}]}
    if depuis:
        q["created_at"] = {"$gte": depuis}
    msgs = [m async for m in db.internal_chat_messages.find(q, {"_id": 0}).sort("created_at", -1).limit(limite)]
    msgs.reverse()
    return msgs


def transcrire(messages: List[Dict[str, Any]], pid: str) -> str:
    """Conversation lisible par l'IA : « [10:42] Poste : … » ; pièces jointes signalées par leur type."""
    lignes = []
    for m in messages:
        heure = str(m.get("created_at") or "")[11:16]
        qui = "Utilisateur Loois" if m.get("sender_id") == pid else (m.get("sender_name") or "Support")
        contenu = (m.get("text") or "").strip()
        if m.get("media_kind"):
            contenu = f"[{m['media_kind']} joint{' : ' + m['file_name'] if m.get('file_name') else ''}] {contenu}".strip()
        if contenu:
            lignes.append(f"[{heure}] {qui} : {contenu}")
    return "\n".join(lignes)


SYSTEME_REPONSE = (
    "Tu es Liluvine, l'assistante du support SAWALI SMART SYSTEMS. Tu réponds dans la fenêtre « Ecrire Support » "
    "du logiciel Loois (gestion scolaire e-Kol : inscriptions, élèves, règlements, impayés, listes PDF). "
    "Réponds en français, brièvement (2 à 5 phrases), avec politesse. Aide l'utilisateur à décrire précisément "
    "son problème (écran concerné, message d'erreur, élève ou classe, étapes), propose une capture (bouton "
    "« 📷 Capture ») ou une vidéo de l'écran (bouton « 🎥 Vidéo ») si utile, et donne une solution seulement si "
    "tu en es sûre. N'invente jamais de fonction ni de procédure. Ne demande jamais de mot de passe ni de clé."
)
SYSTEME_RESUME = (
    "Tu es Liluvine, l'assistante du support SAWALI. On te donne la conversation d'une session d'assistance "
    "entre un utilisateur du logiciel Loois (école) et le support. Rédige les « Détails du Support » en français, "
    "factuels et concis, avec exactement ces rubriques : « Problème signalé », « Diagnostic », « Actions "
    "réalisées », « Résolution », « Suite à donner ». Écris « — » si une rubrique est vide. N'invente rien."
)


MESSAGE_RESTREINT_DEFAUT = ("Bonjour, les réponses automatiques Liluvine pour {client_name} sont disponibles "
                            "uniquement pendant les heures/jours ouvrés avec votre formule actuelle. "
                            "Un conseiller vous répondra dès la reprise.")


async def client_du_poste(db, pid: str, session: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Client SAWALI lié : celui de la session acceptée, sinon celui associé au poste ({} si aucun)."""
    session = session or await session_en_cours(db, pid) or {}
    cid = session.get("client_id") or session.get("client_id_suggere")
    if not cid:
        cid = ((await db.support_loois_postes.find_one({"id": pid}, {"_id": 0, "client_id": 1})) or {}).get("client_id")
    if not cid:
        return {}
    return await db.users.find_one({"id": cid}, {"_id": 0, "password_hash": 0}) or {}


def acces_restreint_maintenant(client_doc: Dict[str, Any], reglages: Dict[str, Any]) -> bool:
    """« Accès Liluvine (WA) » de la fiche client (et seuil de montant du contrat) : en mode Restreint,
    Liluvine ne répond qu'aux jours et heures ouvrés (mêmes règles que l'auto-réponse WhatsApp)."""
    if not client_doc:
        return False
    try:
        from routes.liluvine_wa_autoreply import _in_business_window, _tenant_effective_access_mode
        if _tenant_effective_access_mode(client_doc, reglages) != "restricted":
            return False
        ouverture = int(str(reglages.get("business_open_time") or "09:00").split(":", 1)[0])
        fermeture = int(str(reglages.get("business_close_time") or "18:00").split(":", 1)[0])
        return not _in_business_window(reglages.get("business_days"), ouverture, fermeture)
    except Exception:  # noqa: BLE001 — en cas de doute, Liluvine répond (comme l'auto-réponse WA)
        return False


async def systeme_liluvine(db, client_doc: Dict[str, Any], question: str = "") -> str:
    """Prompt de Liluvine : celui du CLIENT lié (fiche client, « liluvine_pro_system_prompt ») s'il existe,
    complété par les consignes du support Loois et la base de connaissances SAWALI + recherche Qdrant sur
    la question (lot 58.2 ; Qdrant n'est interrogé que si la mémoire du serveur le permet, voir
    qdrant_rag.embeddings_autorises — sinon la base de connaissances seule)."""
    prompt_client = (client_doc.get("liluvine_pro_system_prompt") or "").strip()
    base = (prompt_client + "\n\n[Mode support Loois]\n" + SYSTEME_REPONSE) if prompt_client else SYSTEME_REPONSE
    if client_doc:
        base += f"\n\nClient SAWALI de ce poste : {client_doc.get('company') or client_doc.get('full_name')}."
    try:
        from routes.liluvine_kb import build_kb_context
        connaissances = await build_kb_context(db, max_chars=5000, query=question or None, audience="clients")
    except Exception:  # noqa: BLE001 — sans base de connaissances, Liluvine répond quand même
        connaissances = ""
    return base + (("\n\n" + connaissances) if connaissances else "")


async def reponse_liluvine(db, pid: str, en_attente: bool = True) -> str:
    """Réponse (attente) ou suggestion (session active, pour l'agent) à partir de la conversation récente,
    du prompt du client lié et de la base de connaissances.
    En attente, si l'accès Liluvine du client est « Restreint » hors heures ouvrées : un seul message
    d'information par session, puis silence (l'agent répondra)."""
    messages = await conversation(db, pid, limite=20)
    if not messages:
        return ""
    session = await session_en_cours(db, pid) or {}
    client_doc = await client_du_poste(db, pid, session)
    if en_attente:
        reglages = await db.settings.find_one({"_id": "global"}) or {}
        if acces_restreint_maintenant(client_doc, reglages):
            if session.get("liluvine_restreint_annonce"):
                return ""
            await db.support_loois_sessions.update_one({"id": session.get("id")},
                                                       {"$set": {"liluvine_restreint_annonce": True}})
            modele = (reglages.get("liluvine_access_restricted_message") or "").strip() or MESSAGE_RESTREINT_DEFAUT
            return modele.replace("{client_name}", client_doc.get("company") or client_doc.get("full_name") or "votre établissement")
    consigne = ("Un agent humain va prendre le relais : dis-le si l'utilisateur attend une intervention."
                if en_attente else
                "Rédige la PROCHAINE réponse que l'agent du support pourra envoyer (il la relira).")
    texte = f"{consigne}\n\nConversation :\n{transcrire(messages, pid)}\n\nTa réponse :"
    # Question à rechercher dans Qdrant : derniers messages du poste
    question = " ".join(m.get("text") or "" for m in messages if m.get("sender_id") == pid)[-500:]
    return (await appeler_ia(await systeme_liluvine(db, client_doc, question), texte, MODELE_REPONSE))[:2000]


async def resumer(db, session: Dict[str, Any]) -> str:
    """« Détails du Support » d'une session terminée."""
    messages = await conversation(db, session["poste_id"], depuis=session.get("demande_le"), limite=200)
    transcription = transcrire(messages, session["poste_id"])
    if not transcription:
        return ""
    entete = (f"Poste : {session.get('poste_nom')}\nClient : {session.get('client_nom') or '—'}\n"
              f"Ticket : {session.get('ticket_number') or '—'}\nAgent : {session.get('acceptee_par_nom') or '—'}\n")
    return (await appeler_ia(SYSTEME_RESUME, f"{entete}\nConversation :\n{transcription}", MODELE_RESUME))[:6000]


async def enregistrer_details(db, session: Dict[str, Any], details: str) -> None:
    """Range les « Détails du Support » sur la session, le ticket et l'intervention."""
    if not details:
        return
    await db.support_loois_sessions.update_one({"id": session["id"]}, {"$set": {"details_support": details}})
    if session.get("ticket_id"):
        await db.support_tickets.update_one({"id": session["ticket_id"]}, {"$set": {"details_support": details}})
    if session.get("intervention_id"):
        inter = await db.interventions.find_one({"id": session["intervention_id"]}, {"_id": 0, "description": 1}) or {}
        description = (inter.get("description") or "") + "\n\nDétails du Support (Liluvine) :\n" + details
        await db.interventions.update_one({"id": session["intervention_id"]},
                                          {"$set": {"details_support": details, "description": description}})
