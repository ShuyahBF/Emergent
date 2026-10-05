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
  LOOIS_SUPPORT_ADMIN_EMAIL   (facultatif) e-mail de l'administrateur qui reçoit les messages ;
                              sinon : le dernier administrateur qui a répondu au poste, sinon le 1er admin.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

# Identifiant de l'espace virtuel dans internal_chat_messages.client_id
ESPACE_ID = "support-loois"
ESPACE_NOM = "Support Loois"

# Limites de protection (un poste ne peut pas inonder le chat)
TEXTE_MAX = 2000
MESSAGES_PAR_MINUTE = 20
HISTORIQUE_MAX = 100


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


async def _admin_destinataire(db, pid: str) -> Optional[str]:
    """Administrateur qui reçoit le message d'un poste : celui de LOOIS_SUPPORT_ADMIN_EMAIL, sinon le
    dernier administrateur qui a répondu à ce poste, sinon le premier administrateur actif."""
    email = (os.environ.get("LOOIS_SUPPORT_ADMIN_EMAIL") or "").strip().lower()
    if email:
        a = await db.users.find_one({"role": "admin", "email": email}, {"_id": 0, "id": 1})
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
        if not actif() or not cle_valide(q.get("cle")):
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
            while True:
                if websocket.application_state != WebSocketState.CONNECTED or \
                        websocket.client_state != WebSocketState.CONNECTED:
                    break
                try:
                    data = await websocket.receive_json()
                    mauvais = 0
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
                for cible in (pid, admin_id):
                    try:
                        await manager.send_to_user(cible, diffusion)
                    except Exception:
                        pass
        finally:
            await manager.disconnect(pid, websocket)
