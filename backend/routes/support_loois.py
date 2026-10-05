"""Lot 57.12 — « Support Loois » : le bouton noir « Ecrire Support » de Loois (WinForms, e-Kol) ouvre
une discussion en temps réel avec l'équipe SAWALI, À TRAVERS LE CHAT INTERNE existant.

Principe (pour un développeur WinDev)
-------------------------------------
- Côté SAWALI, un espace de discussion VIRTUEL « Support Loois » (identifiant ``support-loois``)
  apparaît dans le chat interne des ADMINISTRATEURS seulement. Chaque poste Loois y est un fil
  1-à-1 (« École des Métiers — PC-SECRETARIAT (marie) »). L'administrateur répond depuis le portail,
  comme à n'importe quel membre.
- Côté Loois, aucune connexion SAWALI (ni identifiant ni mot de passe) : le poste ouvre le
  WebSocket ``/api/ws/support-loois?cle=…&ecole=…&poste=…&utilisateur=…``. La clé partagée est
  la variable d'environnement ``LOOIS_SUPPORT_CLE`` (saisie par le propriétaire sur Render ET une
  fois dans Loois) : sans elle, le support est fermé.
- Un poste n'est PAS un utilisateur SAWALI : il n'a pas de jeton, ne voit que SES messages et ne peut
  rien faire d'autre qu'écrire au support.

Protocole du WebSocket Loois (JSON)
-----------------------------------
  serveur → Loois : {"type":"hello","poste_id","ts"} puis {"type":"historique","messages":[…]}
                    {"type":"session","statut":"attente|active|refusee","ticket_number","restant_s",…}  (lot 58)
                    {"type":"message","client_id":"support-loois","message":{…}}  (nouveau message)
                    {"type":"fin_session","detail","ticket_number","intervention_number"}  (puis fermeture 4000)
                    {"type":"pong"} · {"type":"erreur","detail":"…"}
  Loois → serveur : {"type":"message","texte":"…"} · {"type":"ping"}

Variables d'environnement
-------------------------
  LOOIS_SUPPORT_CLE           clé partagée (obligatoire pour ouvrir le support) — jamais dans le code ;
  LOOIS_SUPPORT_ADMIN_EMAIL   (facultatif) e-mail(s) du/des compte(s) du support (séparés par « , » ou « ; »),
                              QUEL QUE SOIT LEUR RÔLE (admin, superviseur…) : ils voient l'espace et reçoivent
                              les messages (lot 57.13.1) ;
                              sinon : le dernier administrateur qui a répondu au poste, sinon le 1er admin.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from urllib.parse import unquote

from fastapi import Body, Depends, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from routes import support_loois_sessions as sessions  # lot 58 : sessions, ticket, intervention, Liluvine

log = logging.getLogger("sawali.support_loois")
# Tâches de fond en cours (réponses et résumés de Liluvine)
_taches: set = set()
# Lot 58 — intervalle de relecture de l'état de la session par le WebSocket du poste (secondes)
VERIFICATION_S = 1.0

# Identifiant de l'espace virtuel dans internal_chat_messages.client_id
ESPACE_ID = "support-loois"
ESPACE_NOM = "Support Loois"

# Limites de protection (un poste ne peut pas inonder le chat)
TEXTE_MAX = 2000
MESSAGES_PAR_MINUTE = 20
HISTORIQUE_MAX = 100


def duree_session_secondes() -> float:
    """Lot 57.16 — durée MAXIMALE d'une session de chat Loois (30 min par défaut ; variable
    LOOIS_SUPPORT_SESSION_MINUTES pour l'ajuster). Lot 58 : comptée à partir de l'ACCEPTATION par un agent."""
    return sessions.duree_max_secondes()

# Lot 57.13 — images échangées avec Loois : types acceptés (→ extension du fichier stocké) et taille maximale
TYPES_IMAGES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
IMAGE_MAX = 10 * 1024 * 1024


# Lot 58 — fichiers acceptés : type MIME → (extension, nature, taille maximale)
MO = 1024 * 1024
TYPES_FICHIERS = {
    "image/jpeg": (".jpg", "image", 10 * MO), "image/png": (".png", "image", 10 * MO),
    "image/webp": (".webp", "image", 10 * MO),
    "video/mp4": (".mp4", "video", 50 * MO), "video/webm": (".webm", "video", 50 * MO),
    "application/pdf": (".pdf", "document", 20 * MO),
    "application/msword": (".doc", "document", 20 * MO),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (".docx", "document", 20 * MO),
    "application/vnd.ms-excel": (".xls", "document", 20 * MO),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (".xlsx", "document", 20 * MO),
    "application/vnd.ms-powerpoint": (".ppt", "document", 20 * MO),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (".pptx", "document", 20 * MO),
    "text/plain": (".txt", "document", 5 * MO), "text/csv": (".csv", "document", 5 * MO),
}
# Extension du nom → type MIME (quand le poste envoie « application/octet-stream »)
MIME_PAR_EXTENSION = {ext: mime for mime, (ext, _, _) in TYPES_FICHIERS.items()}
MIME_PAR_EXTENSION[".jpeg"] = "image/jpeg"


def type_fichier(mime: Optional[str], nom: Optional[str]) -> Optional[tuple]:
    """(mime, extension, nature, taille max) d'un fichier accepté, None sinon (exécutables, archives…)."""
    m = (mime or "").split(";")[0].strip().lower()
    if m not in TYPES_FICHIERS:
        ext = os.path.splitext((nom or "").lower())[1]
        m = MIME_PAR_EXTENSION.get(ext, "")
    if m not in TYPES_FICHIERS:
        return None
    return (m, *TYPES_FICHIERS[m])


def nom_fichier_propre(nom: Optional[str], extension: str) -> str:
    """Nom affiché du fichier : sans chemin ni caractères gênants, 120 caractères au plus."""
    base = os.path.basename((nom or "").replace("\\", "/")).strip()
    base = re.sub(r"[^\w .()\-]+", "_", base)[:120]
    return base or ("fichier" + extension)


# =====================================================================
# Fonctions pures (testées sans base ni réseau)
# =====================================================================
def cle_configuree() -> str:
    """Clé partagée lue dans l'environnement (vide = support fermé)."""
    return (os.environ.get("LOOIS_SUPPORT_CLE") or "").strip()


def actif() -> bool:
    """Le support n'existe que si le propriétaire a saisi LOOIS_SUPPORT_CLE sur Render."""
    return bool(cle_configuree())


def cle_valide(cle_recue: Optional[str]) -> bool:
    """Comparaison en temps constant (pas d'indice sur la clé en mesurant le temps de réponse)."""
    attendue = cle_configuree()
    recue = (cle_recue or "").strip()
    if not attendue or not recue:
        return False
    return hmac.compare_digest(attendue.encode("utf-8"), recue.encode("utf-8"))


def nettoyer(texte: Optional[str], longueur: int) -> str:
    """Texte d'identification d'un poste : sans retours à la ligne, espaces réduits, longueur bornée."""
    t = " ".join((texte or "").replace("\r", " ").replace("\n", " ").split())
    return t[:longueur]


def poste_id(ecole: str, poste: str, utilisateur: str) -> str:
    """Identifiant STABLE d'un poste Loois : même école + même ordinateur + même session Windows
    = même fil de discussion d'un lancement à l'autre (l'historique est retrouvé)."""
    base = f"{ecole.strip().lower()}|{poste.strip().lower()}|{utilisateur.strip().lower()}"
    return "loois-" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def nom_affiche(ecole: str, poste: str, utilisateur: str) -> str:
    """Nom du fil côté administrateur : « École des Métiers — PC-SECRETARIAT (marie) »."""
    debut = ecole or "École inconnue"
    milieu = poste or "poste inconnu"
    return f"{debut} — {milieu}" + (f" ({utilisateur})" if utilisateur else "")


class LimiteDebit:
    """Au plus N messages par minute glissante pour UNE connexion."""

    def __init__(self, maximum: int = MESSAGES_PAR_MINUTE, fenetre: float = 60.0):
        self.maximum = maximum
        self.fenetre = fenetre
        self._instants: List[float] = []

    def autorise(self, maintenant: Optional[float] = None) -> bool:
        t = time.monotonic() if maintenant is None else maintenant
        self._instants = [x for x in self._instants if t - x < self.fenetre]
        if len(self._instants) >= self.maximum:
            return False
        self._instants.append(t)
        return True


# =====================================================================
# Accès base (appelés par internal_chat pour intégrer l'espace virtuel)
# =====================================================================
async def ids_postes(db) -> List[str]:
    """Identifiants de tous les postes Loois connus (membres de l'espace virtuel)."""
    return [p["id"] async for p in db.support_loois_postes.find({}, {"_id": 0, "id": 1})]


async def nom_du_poste(db, uid: str) -> Optional[str]:
    """Nom affiché d'un poste (pour les fils de discussion), None si ce n'est pas un poste."""
    if not uid.startswith("loois-"):
        return None
    p = await db.support_loois_postes.find_one({"id": uid}, {"_id": 0, "nom": 1})
    return (p or {}).get("nom")


async def membres_postes(db, est_en_ligne: Callable[[str], bool]) -> List[Dict[str, Any]]:
    """Postes au format de /me/chat/{client}/members (nom, en ligne…)."""
    out = []
    async for p in db.support_loois_postes.find({}, {"_id": 0}):
        out.append({
            "id": p["id"], "name": p.get("nom") or p["id"], "email": None, "role": "poste_loois",
            "online": est_en_ligne(p["id"]), "is_self": False,
        })
    return out


def requete_fil(pid: str) -> Dict[str, Any]:
    """Tous les messages du fil d'un poste, QUEL QUE SOIT l'administrateur (espace partagé entre admins)."""
    return {"client_id": ESPACE_ID, "$or": [{"sender_id": pid}, {"recipient_id": pid}]}


def requete_non_lus(uid: str) -> Dict[str, Any]:
    """Messages des postes Loois pas encore lus par cet administrateur."""
    return {"client_id": ESPACE_ID, "sender_id": {"$regex": "^loois-"}, "read_by": {"$nin": [uid]}}


def emails_support() -> List[str]:
    """E-mails des comptes du support (LOOIS_SUPPORT_ADMIN_EMAIL), en minuscules."""
    brut = (os.environ.get("LOOIS_SUPPORT_ADMIN_EMAIL") or "").replace(";", ",")
    return [e.strip().lower() for e in brut.split(",") if e.strip()]


def _filtre_emails(emails: List[str]) -> Dict[str, Any]:
    """Recherche d'utilisateurs par e-mail sans tenir compte des majuscules."""
    return {"$or": [{"email": {"$regex": f"^{re.escape(e)}$", "$options": "i"}} for e in emails]}


def est_compte_support(user: Dict[str, Any]) -> bool:
    """Lot 57.13.1 — compte désigné par LOOIS_SUPPORT_ADMIN_EMAIL (ex. un compte « superviseur »)."""
    return (user.get("email") or "").strip().lower() in emails_support()


async def ids_admins(db) -> List[str]:
    """
    L'ÉQUIPE DU SUPPORT, qui partage l'espace « Support Loois » : tous les administrateurs + les comptes de
    LOOIS_SUPPORT_ADMIN_EMAIL quel que soit leur rôle (cas réel du 05/10/2026 : compte « superviseur »).
    """
    ids = {a["id"] async for a in db.users.find({"role": "admin"}, {"_id": 0, "id": 1})}
    emails = emails_support()
    if emails:
        ids |= {u["id"] async for u in db.users.find(_filtre_emails(emails), {"_id": 0, "id": 1})}
    return list(ids)


async def fils(db, uid: str) -> List[Dict[str, Any]]:
    """
    Liste des fils de l'espace « Support Loois » pour UN administrateur : un fil par poste qui a déjà écrit
    ou reçu un message, avec le dernier message et le nombre de messages du poste non lus PAR CET ADMIN.
    Lot 57.12.1 — partagé entre TOUS les administrateurs (avant : seul l'admin destinataire voyait le fil).
    """
    out: List[Dict[str, Any]] = []
    async for p in db.support_loois_postes.find({}, {"_id": 0}):
        pid = p["id"]
        dernier = await db.internal_chat_messages.find_one(requete_fil(pid), {"_id": 0}, sort=[("created_at", -1)])
        if not dernier:
            continue
        non_lus = await db.internal_chat_messages.count_documents(
            {"client_id": ESPACE_ID, "sender_id": pid, "read_by": {"$nin": [uid]}})
        out.append({"kind": "dm", "key": pid, "label": p.get("nom") or pid, "unread": int(non_lus),
                    "last_message": dernier})
    out.sort(key=lambda f: (f["last_message"] or {}).get("created_at") or "", reverse=True)
    return out


async def _admin_destinataire(db, pid: str) -> Optional[str]:
    """Administrateur qui reçoit le message d'un poste : celui de LOOIS_SUPPORT_ADMIN_EMAIL, sinon le
    dernier administrateur qui a répondu à ce poste, sinon le premier administrateur actif."""
    # Lot 57.13.1 — le compte désigné reçoit les messages QUEL QUE SOIT son rôle (avant : admin seulement)
    emails = emails_support()
    if emails:
        a = await db.users.find_one(_filtre_emails(emails[:1]), {"_id": 0, "id": 1})
        if a:
            return a["id"]
    derniere = await db.internal_chat_messages.find_one(
        {"client_id": ESPACE_ID, "recipient_id": pid}, {"_id": 0, "sender_id": 1}, sort=[("created_at", -1)]
    )
    if derniere and derniere.get("sender_id"):
        return derniere["sender_id"]
    a = await db.users.find_one(
        {"role": "admin", "account_status": "active"}, {"_id": 0, "id": 1}, sort=[("created_at", 1)]
    )
    return (a or {}).get("id")


# =====================================================================
# WebSocket des postes Loois (installé dans le routeur du chat interne)
# =====================================================================
def installer(*, router, db, manager, now_iso: Callable[[], str], get_current_user=None, tickets=None) -> None:
    """Ajoute /ws/support-loois au routeur du chat interne (même gestionnaire de connexions :
    une réponse de l'administrateur est poussée au poste comme à n'importe quel membre).
    Lot 58 : sessions (attente → active → terminée), ticket, intervention, fichiers, Liluvine.
    `tickets` : module tickets_clients (injecté par les tests ; sinon importé à la clôture)."""

    async def diffuser_equipe(trame: Dict[str, Any], aussi: Optional[List[str]] = None) -> None:
        """Pousse une trame à toute l'équipe du support connectée (et aux identifiants `aussi`)."""
        for cible in {*(aussi or []), *(await ids_admins(db))}:
            try:
                await manager.send_to_user(cible, trame)
            except Exception:
                pass

    async def enregistrer_message(pid: str, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Range un message du fil d'un poste et le pousse au poste + à l'équipe."""
        await db.internal_chat_messages.insert_one(doc.copy())
        doc.pop("_id", None)
        await diffuser_equipe({"type": "message", "client_id": ESPACE_ID, "message": doc},
                              aussi=[pid, doc.get("recipient_id") or pid])
        return doc

    async def message_systeme(pid: str, texte: str, expediteur: str = "sawali", nom: str = "Support SAWALI") -> None:
        """Message d'information dans le fil (ticket créé, session terminée…), visible des deux côtés."""
        await enregistrer_message(pid, {
            "id": str(uuid.uuid4()), "client_id": ESPACE_ID, "sender_id": expediteur, "sender_name": nom,
            "recipient_id": pid, "text": texte[:TEXTE_MAX], "created_at": now_iso(), "read_by": [expediteur],
            "systeme": True})

    async def repondre_liluvine(pid: str, sid: str) -> None:
        """Pendant l'attente, Liluvine répond au poste (tâche de fond : n'interrompt pas la discussion)."""
        try:
            texte = await sessions.reponse_liluvine(db, pid, en_attente=True)
            session = await sessions.lire(db, sid)
            # L'agent a pris la main entre-temps : Liluvine se tait
            if not texte or not session or session.get("statut") != "attente":
                return
            await message_systeme(pid, texte, sessions.LILUVINE_ID, sessions.LILUVINE_NOM)
        except Exception:  # noqa: BLE001
            log.warning("[support_loois] réponse Liluvine impossible", exc_info=True)

    async def details_liluvine(session: Dict[str, Any]) -> None:
        """En fin de session, Liluvine résume l'assistance (« Détails du Support »)."""
        try:
            details = await sessions.resumer(db, session)
            await sessions.enregistrer_details(db, session, details)
            if details:
                await diffuser_equipe({"type": "support_loois_session", "session": await sessions.lire(db, session["id"])})
        except Exception:  # noqa: BLE001
            log.warning("[support_loois] résumé Liluvine impossible", exc_info=True)

    def lancer(coro) -> None:
        """Tâche de fond gardée en mémoire jusqu'à sa fin (sinon Python peut l'abandonner)."""
        tache = asyncio.ensure_future(coro)
        _taches.add(tache)
        tache.add_done_callback(_taches.discard)

    async def apres_fin(session: Dict[str, Any]) -> None:
        """Annonce de fin dans le fil + équipe prévenue + résumé Liluvine."""
        await message_systeme(session["poste_id"], "✅ " + sessions.texte_fin(session))
        await diffuser_equipe({"type": "support_loois_session", "session": session})
        if sessions.liluvine_active():
            lancer(details_liluvine(session))

    @router.websocket("/ws/support-loois")
    async def ws_support_loois(websocket: WebSocket):
        await websocket.accept()
        q = websocket.query_params
        # Lot 57.13 — clé lue de préférence dans l'en-tête X-Loois-Cle (jamais journalisée dans l'adresse)
        cle = websocket.headers.get("x-loois-cle") or q.get("cle")
        if not actif() or not cle_valide(cle):
            await websocket.send_json({"type": "erreur", "detail": "Support fermé ou clé du support incorrecte."})
            await websocket.close(code=4401)
            return

        ecole = nettoyer(q.get("ecole"), 80)
        poste = nettoyer(q.get("poste"), 60)
        utilisateur = nettoyer(q.get("utilisateur"), 60)
        version = nettoyer(q.get("version"), 30)
        pid = poste_id(ecole, poste, utilisateur)
        nom = nom_affiche(ecole, poste, utilisateur)

        # Fiche du poste (créée au 1er contact, mise à jour ensuite)
        await db.support_loois_postes.update_one(
            {"id": pid},
            {"$set": {"nom": nom, "ecole": ecole, "poste": poste, "utilisateur": utilisateur,
                      "version_loois": version, "dernier_contact": now_iso()},
             "$setOnInsert": {"id": pid, "premier_contact": now_iso()}},
            upsert=True,
        )

        await manager.connect(pid, websocket)
        limite = LimiteDebit()
        session: Optional[Dict[str, Any]] = None
        try:
            await websocket.send_json({"type": "hello", "poste_id": pid, "nom": nom, "ts": now_iso()})
            # Historique du poste (ses messages et les réponses reçues), du plus ancien au plus récent
            curseur = db.internal_chat_messages.find(
                {"client_id": ESPACE_ID, "$or": [{"sender_id": pid}, {"recipient_id": pid}]}, {"_id": 0}
            ).sort("created_at", -1).limit(HISTORIQUE_MAX)
            historique = [m async for m in curseur]
            historique.reverse()
            await websocket.send_json({"type": "historique", "messages": historique})

            # Lot 58 — session : reprise (coupure réseau) ou nouvelle DEMANDE en attente d'un agent
            session, nouvelle = await sessions.ouvrir_ou_reprendre(db, pid, nom, now_iso)
            await websocket.send_json(sessions.trame_session(session))
            if nouvelle:
                await diffuser_equipe({"type": "support_loois_session", "session": session})
            dernier_envoi = sessions.trame_session(session)

            mauvais = 0
            while True:
                if websocket.application_state != WebSocketState.CONNECTED or \
                        websocket.client_state != WebSocketState.CONNECTED:
                    break
                try:
                    # Réveil régulier : l'état de la session est relu (acceptation, refus, fin par un agent)
                    data = await asyncio.wait_for(websocket.receive_json(), timeout=VERIFICATION_S)
                    mauvais = 0
                except asyncio.TimeoutError:
                    session = await sessions.lire(db, session["id"]) or session
                    # Durée maximale atteinte (comptée depuis l'acceptation) : fin automatique
                    restant = sessions.restant_secondes(session)
                    if restant is not None and restant <= 0:
                        try:
                            session = await sessions.terminer(db, session["id"], None, now_iso,
                                                              raison="duree", tickets=tickets)
                            await apres_fin(session)
                        except sessions.ErreurSession:
                            session = await sessions.lire(db, session["id"]) or session
                    statut = session.get("statut")
                    if statut == "terminee":
                        try:
                            await websocket.send_json({"type": "fin_session", "detail": sessions.texte_fin(session),
                                                       "ticket_number": session.get("ticket_number"),
                                                       "intervention_number": session.get("intervention_number")})
                            await websocket.close(code=4000)
                        except Exception:
                            pass
                        break
                    trame = sessions.trame_session(session)
                    # Le temps restant change à chaque réveil : on ne renvoie que si l'état a changé
                    if {**trame, "restant_s": None} != {**dernier_envoi, "restant_s": None}:
                        await websocket.send_json(trame)
                        dernier_envoi = trame
                    if statut in ("refusee", "abandonnee"):
                        try:
                            await websocket.close(code=4001)
                        except Exception:
                            pass
                        break
                    continue
                except (WebSocketDisconnect, RuntimeError):
                    break
                except Exception:
                    mauvais += 1          # trame illisible : ignorée, abandon après 20 d'affilée
                    if mauvais > 20:
                        break
                    continue

                genre = (data or {}).get("type")
                if genre == "ping":
                    await websocket.send_json({"type": "pong", "ts": now_iso()})
                    continue
                if genre != "message":
                    continue
                texte = (data.get("texte") or "").strip()[:TEXTE_MAX]
                if not texte:
                    continue
                if not limite.autorise():
                    await websocket.send_json({"type": "erreur", "detail": "Trop de messages : patientez une minute."})
                    continue
                session = await sessions.lire(db, session["id"]) or session
                if session.get("statut") not in sessions.STATUTS_EN_COURS:
                    await websocket.send_json({"type": "erreur", "detail": "La session est terminée : ouvrez une nouvelle session."})
                    continue
                admin_id = await _admin_destinataire(db, pid)
                if not admin_id:
                    await websocket.send_json({"type": "erreur", "detail": "Aucun administrateur SAWALI pour recevoir le message."})
                    continue

                # Même format que les messages du chat interne : l'administrateur le voit comme un DM
                await enregistrer_message(pid, {
                    "id": str(uuid.uuid4()), "client_id": ESPACE_ID, "sender_id": pid, "sender_name": nom,
                    "recipient_id": admin_id, "text": texte, "created_at": now_iso(), "read_by": [pid],
                    "session_id": session["id"]})
                await db.support_loois_postes.update_one({"id": pid}, {"$set": {"dernier_contact": now_iso()}})
                # Lot 58 — en attente d'un agent, Liluvine répond
                if session.get("statut") == "attente" and sessions.liluvine_active():
                    lancer(repondre_liluvine(pid, session["id"]))
        finally:
            await manager.disconnect(pid, websocket)
            # Le poste ferme sa fenêtre avant d'être pris en charge : la demande est retirée
            if session and not manager.is_online(pid):
                try:
                    if await sessions.abandonner_si_en_attente(db, session["id"], now_iso):
                        await diffuser_equipe({"type": "support_loois_session",
                                               "session": await sessions.lire(db, session["id"])})
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Lot 57.13 — IMAGES échangées avec les postes Loois
    # ------------------------------------------------------------------
    def _poste_de_la_requete(request: Request) -> Dict[str, str]:
        """Identité du poste dans les en-têtes X-Loois-* (valeurs encodées en %XX par Loois) ; 401 si clé refusée."""
        h = request.headers
        if not actif() or not cle_valide(h.get("x-loois-cle")):
            raise HTTPException(status_code=401, detail="Support fermé ou clé du support incorrecte.")
        ecole = nettoyer(unquote(h.get("x-loois-ecole") or ""), 80)
        poste = nettoyer(unquote(h.get("x-loois-poste") or ""), 60)
        utilisateur = nettoyer(unquote(h.get("x-loois-utilisateur") or ""), 60)
        return {"pid": poste_id(ecole, poste, utilisateur), "nom": nom_affiche(ecole, poste, utilisateur),
                "ecole": ecole, "poste": poste, "utilisateur": utilisateur}

    @router.post("/support-loois/photo")
    async def support_loois_photo(request: Request, photo: UploadFile = File(...), caption: Optional[str] = Form(None)):
        """Un poste Loois envoie une image (capture d'écran, photo) au support : rangée dans le chat interne
        comme une photo ordinaire, visible et annotable par les administrateurs."""
        ident = _poste_de_la_requete(request)
        pid = ident["pid"]
        mime = (photo.content_type or "").lower()
        if mime not in TYPES_IMAGES:
            raise HTTPException(status_code=400, detail="Format non supporté : JPEG, PNG ou WebP uniquement.")
        data = await photo.read()
        if not data:
            raise HTTPException(status_code=400, detail="Fichier vide.")
        if len(data) > IMAGE_MAX:
            raise HTTPException(status_code=413, detail="Image trop volumineuse (plus de 10 Mo).")
        admin_id = await _admin_destinataire(db, pid)
        if not admin_id:
            raise HTTPException(status_code=503, detail="Aucun administrateur SAWALI pour recevoir l'image.")
        await db.support_loois_postes.update_one(
            {"id": pid},
            {"$set": {"nom": ident["nom"], "ecole": ident["ecole"], "poste": ident["poste"],
                      "utilisateur": ident["utilisateur"], "dernier_contact": now_iso()},
             "$setOnInsert": {"id": pid, "premier_contact": now_iso()}},
            upsert=True,
        )
        msg_id = str(uuid.uuid4())
        try:
            from storage import aupload_bytes, astorage_available  # stockage des images (R2)
            if not await astorage_available():
                raise HTTPException(status_code=503, detail="Stockage indisponible : réessayez plus tard.")
            chemin = await aupload_bytes(f"chat/{ESPACE_ID}/{msg_id}{TYPES_IMAGES[mime]}", data, mime)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Envoi de l'image échoué : {str(exc)[:160]}")
        doc = {
            "id": msg_id, "client_id": ESPACE_ID, "sender_id": pid, "sender_name": ident["nom"],
            "recipient_id": admin_id, "text": ((caption or "").strip())[:500],
            "media_url": f"/api/me/chat/media/{msg_id}", "media_mime": mime, "media_size": len(data),
            "media_kind": "image", "storage_path": chemin, "created_at": now_iso(), "read_by": [pid],
        }
        await db.internal_chat_messages.insert_one(doc.copy())
        doc.pop("_id", None)
        diffusion = {"type": "message", "client_id": ESPACE_ID, "message": doc}
        for cible in {pid, admin_id, *(await ids_admins(db))}:
            try:
                await manager.send_to_user(cible, diffusion)
            except Exception:
                pass
        return doc

    @router.get("/support-loois/media/{msg_id}")
    async def support_loois_media(msg_id: str, request: Request):
        """Image d'un message du fil de CE poste (envoyée par lui ou par un administrateur) ; jamais celle
        d'un autre poste ni d'un autre espace."""
        pid = _poste_de_la_requete(request)["pid"]
        m = await db.internal_chat_messages.find_one({"id": msg_id, "client_id": ESPACE_ID}, {"_id": 0})
        if not m or pid not in (m.get("sender_id"), m.get("recipient_id")) or not m.get("storage_path"):
            raise HTTPException(status_code=404, detail="Image introuvable.")
        try:
            from storage import afetch_bytes
            data, ct = await afetch_bytes(m["storage_path"])
        except Exception:
            raise HTTPException(status_code=502, detail="Lecture de l'image impossible.")
        return Response(content=data, media_type=ct or m.get("media_mime") or "application/octet-stream",
                        headers={"Cache-Control": "private, max-age=86400"})

    # ------------------------------------------------------------------
    # Lot 58 — FICHIERS : documents (PDF, Office, texte) et vidéos de l'écran (MP4) en plus des images
    # ------------------------------------------------------------------
    async def stocker_fichier(*, pid: str, expediteur: str, nom_expediteur: str, destinataire: Optional[str],
                              fichier: UploadFile, legende: Optional[str], lus: List[str]) -> Dict[str, Any]:
        """Contrôle (type, taille), range le fichier dans le stockage R2 et crée le message du fil."""
        nature = type_fichier(fichier.content_type, fichier.filename)
        if not nature:
            raise HTTPException(status_code=400, detail="Type de fichier non accepté : images, vidéos MP4/WebM, "
                                                        "PDF, Word, Excel, PowerPoint, texte ou CSV.")
        mime, extension, genre, maximum = nature
        data = await fichier.read()
        if not data:
            raise HTTPException(status_code=400, detail="Fichier vide.")
        if len(data) > maximum:
            raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (plus de {maximum // (1024 * 1024)} Mo).")
        msg_id = str(uuid.uuid4())
        try:
            from storage import aupload_bytes, astorage_available  # stockage des fichiers (R2)
            if not await astorage_available():
                raise HTTPException(status_code=503, detail="Stockage indisponible : réessayez plus tard.")
            chemin = await aupload_bytes(f"chat/{ESPACE_ID}/{msg_id}{extension}", data, mime)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Envoi du fichier échoué : {str(exc)[:160]}")
        return await enregistrer_message(pid, {
            "id": msg_id, "client_id": ESPACE_ID, "sender_id": expediteur, "sender_name": nom_expediteur,
            "recipient_id": destinataire, "text": ((legende or "").strip())[:500],
            "media_url": f"/api/me/chat/media/{msg_id}", "media_mime": mime, "media_size": len(data),
            "media_kind": genre, "file_name": nom_fichier_propre(fichier.filename, extension),
            "storage_path": chemin, "created_at": now_iso(), "read_by": lus})

    @router.post("/support-loois/fichier")
    async def support_loois_fichier(request: Request, fichier: UploadFile = File(...),
                                    caption: Optional[str] = Form(None)):
        """Un poste Loois envoie un document ou une vidéo de son écran (session en attente ou active)."""
        ident = _poste_de_la_requete(request)
        pid = ident["pid"]
        if not await sessions.session_en_cours(db, pid):
            raise HTTPException(status_code=409, detail="Aucune session d'assistance en cours.")
        admin_id = await _admin_destinataire(db, pid)
        if not admin_id:
            raise HTTPException(status_code=503, detail="Aucun administrateur SAWALI pour recevoir le fichier.")
        return await stocker_fichier(pid=pid, expediteur=pid, nom_expediteur=ident["nom"], destinataire=admin_id,
                                     fichier=fichier, legende=caption, lus=[pid])

    if get_current_user is None:
        return  # ancien montage sans authentification : pas de routes pour l'équipe

    # ------------------------------------------------------------------
    # Lot 58 — ROUTES DE L'ÉQUIPE DU SUPPORT (portail SAWALI)
    # ------------------------------------------------------------------
    async def equipe(user: dict = Depends(get_current_user)) -> dict:
        """Seuls les administrateurs et les comptes désignés (LOOIS_SUPPORT_ADMIN_EMAIL) gèrent les sessions."""
        if not actif() or not (user.get("role") == "admin" or est_compte_support(user)):
            raise HTTPException(status_code=403, detail="Réservé à l'équipe du support.")
        return user

    def erreur_http(exc: "sessions.ErreurSession") -> HTTPException:
        return HTTPException(status_code=exc.code, detail=exc.detail)

    @router.get("/support-loois/sessions")
    async def liste_sessions(user: dict = Depends(equipe)):
        """Demandes en attente, sessions actives et dernières sessions closes (bandeau du chat)."""
        en_cours = [s async for s in db.support_loois_sessions.find({"en_cours": True}, {"_id": 0})
                    .sort("demande_le", 1)]
        recentes = [s async for s in db.support_loois_sessions.find({"en_cours": False}, {"_id": 0})
                    .sort("demande_le", -1).limit(30)]
        return {"en_cours": en_cours, "recentes": recentes, "liluvine": sessions.liluvine_active(),
                "duree_max_s": int(sessions.duree_max_secondes())}

    @router.get("/support-loois/postes/{pid}/session")
    async def session_du_poste(pid: str, user: dict = Depends(equipe)):
        """Session en cours (ou la dernière) d'un poste + client retenu pour ce poste."""
        session = await sessions.session_en_cours(db, pid) or await db.support_loois_sessions.find_one(
            {"poste_id": pid}, {"_id": 0}, sort=[("demande_le", -1)])
        poste = await db.support_loois_postes.find_one({"id": pid}, {"_id": 0}) or {}
        return {"session": session, "client_id_suggere": poste.get("client_id"),
                "duree_max_s": int(sessions.duree_max_secondes())}

    @router.get("/support-loois/clients")
    async def clients_pour_ticket(q: Optional[str] = None, user: dict = Depends(equipe)):
        """Clients SAWALI à qui rattacher le ticket (recherche par nom ou société)."""
        filtre: Dict[str, Any] = {"role": "client", "account_status": {"$nin": ["deleted", "archived"]}}
        if q and q.strip():
            motif = re.escape(q.strip()[:60])
            filtre["$or"] = [{"company": {"$regex": motif, "$options": "i"}},
                             {"full_name": {"$regex": motif, "$options": "i"}}]
        out = [{"id": c["id"], "nom": c.get("company") or c.get("full_name") or c["id"]}
               async for c in db.users.find(filtre, {"_id": 0, "id": 1, "company": 1, "full_name": 1}).limit(200)]
        out.sort(key=lambda c: c["nom"].lower())
        return out

    @router.post("/support-loois/postes/{pid}/client")
    async def associer_client_au_poste(pid: str, corps: Dict[str, Any] = Body(...), user: dict = Depends(equipe)):
        """Lot 58.1 — associe le poste à un client SAWALI dès la demande : Liluvine répond alors avec le
        prompt et les règles d'accès de ce client ; il est retenu pour les demandes suivantes."""
        client_id = (corps or {}).get("client_id")
        if not client_id or not await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=400, detail="Client SAWALI introuvable.")
        if not await db.support_loois_postes.find_one({"id": pid}, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=404, detail="Poste Loois inconnu.")
        await sessions.associer_client(db, pid, client_id)
        return {"ok": True, "client_id": client_id}

    @router.post("/support-loois/sessions/{sid}/accepter")
    async def accepter_session(sid: str, corps: Dict[str, Any] = Body(...), user: dict = Depends(equipe)):
        """Prise en charge : ticket créé pour le client choisi, numéro annoncé au poste."""
        try:
            session = await sessions.accepter(db, sid, (corps or {}).get("client_id"), user, now_iso,
                                              motif=(corps or {}).get("motif"))
        except sessions.ErreurSession as exc:
            raise erreur_http(exc)
        await message_systeme(session["poste_id"],
                              f"🎫 Ticket n° {session['ticket_number']} ouvert — "
                              f"{session.get('acceptee_par_nom')} prend en charge votre demande.")
        await diffuser_equipe({"type": "support_loois_session", "session": session})
        return session

    @router.post("/support-loois/sessions/{sid}/refuser")
    async def refuser_session(sid: str, corps: Optional[Dict[str, Any]] = Body(None), user: dict = Depends(equipe)):
        """Refus d'une demande (motif affiché dans Loois)."""
        try:
            session = await sessions.refuser(db, sid, user, now_iso, motif=(corps or {}).get("motif"))
        except sessions.ErreurSession as exc:
            raise erreur_http(exc)
        await message_systeme(session["poste_id"], f"⛔ Demande non acceptée : {session.get('motif_refus')}")
        await diffuser_equipe({"type": "support_loois_session", "session": session})
        return session

    @router.post("/support-loois/sessions/{sid}/terminer")
    async def terminer_session(sid: str, user: dict = Depends(equipe)):
        """Fin de la session par l'agent : ticket clôturé, intervention créée, Liluvine résume."""
        try:
            session = await sessions.terminer(db, sid, user, now_iso, raison="agent", tickets=tickets)
        except sessions.ErreurSession as exc:
            raise erreur_http(exc)
        await apres_fin(session)
        return session

    @router.post("/support-loois/sessions/{sid}/details")
    async def details_du_support(sid: str, user: dict = Depends(equipe)):
        """Lot 58.2 — (re)génère les « Détails du Support » d'une session terminée (par exemple si le résumé
        automatique a été interrompu par un redéploiement)."""
        session = await sessions.lire(db, sid)
        if not session or session.get("statut") != "terminee":
            raise HTTPException(status_code=409, detail="La session n'est pas terminée.")
        if not sessions.liluvine_active():
            raise HTTPException(status_code=503, detail="Liluvine n'est pas disponible (clé IA ou LOOIS_SUPPORT_LILUVINE).")
        try:
            details = await sessions.resumer(db, session)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Liluvine n'a pas pu résumer : {str(exc)[:160]}")
        await sessions.enregistrer_details(db, session, details)
        return await sessions.lire(db, sid)

    @router.post("/support-loois/postes/{pid}/suggestion")
    async def suggestion_liluvine(pid: str, user: dict = Depends(equipe)):
        """Liluvine propose la prochaine réponse de l'agent (à relire avant envoi)."""
        if not sessions.liluvine_active():
            raise HTTPException(status_code=503, detail="Liluvine n'est pas disponible (clé IA ou LOOIS_SUPPORT_LILUVINE).")
        try:
            texte = await sessions.reponse_liluvine(db, pid, en_attente=False)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Liluvine n'a pas pu répondre : {str(exc)[:160]}")
        return {"texte": texte}

    @router.post("/support-loois/postes/{pid}/fichier")
    async def fichier_vers_poste(pid: str, fichier: UploadFile = File(...), caption: Optional[str] = Form(None),
                                 user: dict = Depends(equipe)):
        """L'agent envoie un document (ou une image, une vidéo) au poste."""
        if not await db.support_loois_postes.find_one({"id": pid}, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=404, detail="Poste Loois inconnu.")
        return await stocker_fichier(pid=pid, expediteur=user["id"],
                                     nom_expediteur=user.get("full_name") or user.get("email") or user["id"],
                                     destinataire=pid, fichier=fichier, legende=caption, lus=[user["id"]])
