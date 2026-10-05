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
                    {"type":"message","client_id":"support-loois","message":{…}}  (nouveau message)
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
import os
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from urllib.parse import unquote

from fastapi import File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

# Identifiant de l'espace virtuel dans internal_chat_messages.client_id
ESPACE_ID = "support-loois"
ESPACE_NOM = "Support Loois"

# Limites de protection (un poste ne peut pas inonder le chat)
TEXTE_MAX = 2000
MESSAGES_PAR_MINUTE = 20
HISTORIQUE_MAX = 100


def duree_session_secondes() -> float:
    """Lot 57.16 — durée MAXIMALE d'une session de chat Loois (30 min par défaut ; variable
    LOOIS_SUPPORT_SESSION_MINUTES pour l'ajuster). Au-delà, le serveur ferme la session."""
    try:
        minutes = float(os.environ.get("LOOIS_SUPPORT_SESSION_MINUTES") or 30)
    except ValueError:
        minutes = 30.0
    return max(minutes, 0.01) * 60

# Lot 57.13 — images échangées avec Loois : types acceptés (→ extension du fichier stocké) et taille maximale
TYPES_IMAGES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
IMAGE_MAX = 10 * 1024 * 1024


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
def installer(*, router, db, manager, now_iso: Callable[[], str]) -> None:
    """Ajoute /ws/support-loois au routeur du chat interne (même gestionnaire de connexions :
    une réponse de l'administrateur est poussée au poste comme à n'importe quel membre)."""

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
        try:
            await websocket.send_json({"type": "hello", "poste_id": pid, "nom": nom, "ts": now_iso()})
            # Historique du poste (ses messages et les réponses reçues), du plus ancien au plus récent
            curseur = db.internal_chat_messages.find(
                {"client_id": ESPACE_ID, "$or": [{"sender_id": pid}, {"recipient_id": pid}]}, {"_id": 0}
            ).sort("created_at", -1).limit(HISTORIQUE_MAX)
            historique = [m async for m in curseur]
            historique.reverse()
            await websocket.send_json({"type": "historique", "messages": historique})

            mauvais = 0
            # Lot 57.16 — session limitée (30 min par défaut) : à l'échéance, « fin_session » puis fermeture
            fin_session = time.monotonic() + duree_session_secondes()
            while True:
                if websocket.application_state != WebSocketState.CONNECTED or \
                        websocket.client_state != WebSocketState.CONNECTED:
                    break
                reste = fin_session - time.monotonic()
                try:
                    if reste <= 0:
                        raise asyncio.TimeoutError
                    data = await asyncio.wait_for(websocket.receive_json(), timeout=reste)
                    mauvais = 0
                except asyncio.TimeoutError:
                    try:
                        await websocket.send_json({"type": "fin_session",
                                                   "detail": "Session terminée : 30 minutes maximum. Ouvrez une nouvelle session pour continuer."})
                        await websocket.close(code=4000)
                    except Exception:
                        pass
                    break
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
                admin_id = await _admin_destinataire(db, pid)
                if not admin_id:
                    await websocket.send_json({"type": "erreur", "detail": "Aucun administrateur SAWALI pour recevoir le message."})
                    continue

                # Même format que les messages du chat interne : l'administrateur le voit comme un DM
                doc = {
                    "id": str(uuid.uuid4()),
                    "client_id": ESPACE_ID,
                    "sender_id": pid,
                    "sender_name": nom,
                    "recipient_id": admin_id,
                    "text": texte,
                    "created_at": now_iso(),
                    "read_by": [pid],
                }
                await db.internal_chat_messages.insert_one(doc.copy())
                doc.pop("_id", None)
                await db.support_loois_postes.update_one({"id": pid}, {"$set": {"dernier_contact": now_iso()}})
                diffusion = {"type": "message", "client_id": ESPACE_ID, "message": doc}
                # Lot 57.12.1 — poussé à TOUS les administrateurs connectés (espace partagé), pas seulement au destinataire
                for cible in {pid, admin_id, *(await ids_admins(db))}:
                    try:
                        await manager.send_to_user(cible, diffusion)
                    except Exception:
                        pass
        finally:
            await manager.disconnect(pid, websocket)

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
