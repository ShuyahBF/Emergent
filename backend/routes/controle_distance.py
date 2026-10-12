"""Lot 131 — Contrôle à distance des postes Loois depuis SAWALI (« Prendre la main »).

Demande du propriétaire (12/10/2026) : « Créer un outil de contrôle à distance plus complet et performant que
Splashtop », intégré à Loois (choix du propriétaire : étendre Loois).

Principes (non négociables) :
  - CONSENTEMENT : aucune session sans l'accord explicite de l'utilisateur du poste (fenêtre Loois au premier plan,
    « Accepter / Refuser ») ; il choisit « voir seulement » ou « contrôler » et peut tout arrêter à tout moment
    (bandeau permanent côté Loois) ;
  - seul un technicien SAWALI (super-admin ou compte support) peut demander une session, et seulement vers un poste
    qui s'est présenté avec une CLÉ CLIENT valide (jamais la clé commune) ;
  - jetons à usage unique et de courte durée, conservés uniquement sous forme d'empreinte (SHA-256) ;
  - tout passe par SAWALI en WebSocket chiffré (wss) ; le serveur relaie sans rien enregistrer des images ;
  - mode « voir seulement » IMPOSÉ PAR LE SERVEUR : les commandes clavier / souris / presse-papiers du technicien
    sont rejetées si la session n'est pas en mode « contrôler » ;
  - journal de chaque session : qui, quel poste, mode, début, fin, durée, motif de fin.

Déroulé (pour un développeur WinDev : une « machine à états » simple) :
  1. Technicien → POST /api/controle-distance/sessions {poste_id, mode}        → statut « demandee »
  2. Loois interroge GET /api/controle-distance/poste/demande (toutes les 5 s, clé X-Loois-Cle)
     et affiche la fenêtre d'accord ;
  3. Loois → POST /api/controle-distance/poste/sessions/{sid}/reponse {accepte, mode}
     → « acceptee » + jeton du poste (renvoyé UNE fois) ;
  4. Technicien → GET /api/controle-distance/sessions/{sid}  → jeton du technicien (renvoyé UNE fois) ;
  5. Les deux bouts ouvrent wss://…/api/ws/controle-distance et envoient d'abord
     {"type": "auth", "role": "poste"|"technicien", "session_id", "jeton"} ;
  6. Relais : images (trames binaires) du poste vers le technicien ; commandes JSON du technicien vers le poste
     (filtrées selon le mode) ; informations JSON du poste (écrans, curseur, statistiques) vers le technicien ;
  7. Fin : « arreter » d'un côté, déconnexion, durée maximale atteinte → statut « terminee » + journal.

Format des trames binaires (images) — décrit ici pour Loois et la visionneuse, le serveur ne les lit pas :
  octet 0 = type (1 = tuile JPEG) ; puis entiers 16 bits petit-boutiste : écran, x, y, largeur, hauteur ;
  puis les octets JPEG de la tuile.
Le transport est isolé dans la classe Relais : un lot suivant pourra passer en pair-à-pair (WebRTC) sans changer
les droits, le consentement ni le journal.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.controle_distance")

# ---------------------------------------------------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------------------------------------------------
MODES = ("voir", "controler")
DELAI_REPONSE_S = 120            # le poste a 2 minutes pour accepter, sinon la demande expire
DELAI_CONNEXION_S = 120          # après l'accord, 2 minutes pour ouvrir les deux connexions
DUREE_MAX_S = 4 * 3600           # une session dure au plus 4 heures
TAILLE_MAX_TRAME = 2 * 1024 * 1024   # 2 Mo par trame binaire (une tuile JPEG est bien plus petite)
# Commandes du technicien qui AGISSENT sur le poste : refusées en mode « voir seulement »
COMMANDES_ENTREE = {"souris", "clavier", "presse_papiers", "texte"}
# Commandes du technicien autorisées dans tous les modes (réglages de l'affichage)
COMMANDES_AFFICHAGE = {"choix_ecran", "qualite", "image_complete", "ping", "arreter"}
# Informations que le poste peut envoyer au technicien
MESSAGES_POSTE = {"ecrans", "curseur", "stats", "presse_papiers", "pong", "arreter", "erreur"}


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def iso(d: datetime) -> str:
    return d.isoformat()


def empreinte(jeton: str) -> str:
    """Empreinte SHA-256 d'un jeton : seul ce condensé est conservé en base (jamais le jeton lui-même)."""
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


def nouveau_jeton() -> str:
    """Jeton aléatoire de 256 bits, transmis une seule fois."""
    return secrets.token_urlsafe(32)


def est_super_admin(user: Optional[Dict[str, Any]]) -> bool:
    """Lot 131.1 — seul le super-admin SAWALI (SUPER_ADMIN_EMAIL) prend la main sur un poste SANS SURVEILLANCE."""
    email = str((user or {}).get("email") or "").strip().lower()
    super_admin = (os.environ.get("SUPER_ADMIN_EMAIL") or "admin@sawalismartsystems.com").strip().lower()
    return bool(email) and email == super_admin


def est_technicien(user: Optional[Dict[str, Any]]) -> bool:
    """Peut prendre la main : le super-admin SAWALI et les comptes du support Loois."""
    if not user:
        return False
    email = str(user.get("email") or "").strip().lower()
    super_admin = (os.environ.get("SUPER_ADMIN_EMAIL") or "admin@sawalismartsystems.com").strip().lower()
    if email and email == super_admin:
        return True
    try:
        from routes.support_loois import est_compte_support
        return bool(est_compte_support(user))
    except Exception:  # noqa: BLE001 — module indisponible : seul le super-admin
        return False


def commande_autorisee(mode: str, message: Dict[str, Any]) -> bool:
    """Le serveur impose le mode : une commande d'entrée n'est relayée que si la session est en « contrôler »."""
    type_ = str(message.get("type") or "")
    if type_ in COMMANDES_AFFICHAGE:
        return True
    if type_ in COMMANDES_ENTREE:
        return mode == "controler"
    return False   # type inconnu : jamais relayé


def message_poste_autorise(message: Dict[str, Any]) -> bool:
    return str(message.get("type") or "") in MESSAGES_POSTE


# ---------------------------------------------------------------------------------------------------------------------
# Relais en mémoire (le serveur SAWALI tourne en un seul processus)
# ---------------------------------------------------------------------------------------------------------------------
class Relais:
    """Associe, pour chaque session, la connexion du poste et celle du technicien, et transmet les messages."""

    def __init__(self) -> None:
        self.bouts: Dict[str, Dict[str, Any]] = {}     # session_id → {"poste": ws, "technicien": ws}

    def brancher(self, sid: str, role: str, ws: Any) -> None:
        self.bouts.setdefault(sid, {})[role] = ws

    def debrancher(self, sid: str, role: str) -> None:
        bouts = self.bouts.get(sid) or {}
        bouts.pop(role, None)
        if not bouts:
            self.bouts.pop(sid, None)

    def autre(self, sid: str, role: str) -> Any:
        return (self.bouts.get(sid) or {}).get("technicien" if role == "poste" else "poste")

    async def envoyer_json(self, sid: str, role_dest: str, message: Dict[str, Any]) -> bool:
        ws = (self.bouts.get(sid) or {}).get(role_dest)
        if ws is None:
            return False
        try:
            await ws.send_json(message)
            return True
        except Exception:  # noqa: BLE001 — bout déjà fermé
            return False

    async def envoyer_binaire(self, sid: str, role_dest: str, donnees: bytes) -> bool:
        ws = (self.bouts.get(sid) or {}).get(role_dest)
        if ws is None:
            return False
        try:
            await ws.send_bytes(donnees)
            return True
        except Exception:  # noqa: BLE001
            return False

    async def fermer(self, sid: str, motif: str) -> None:
        """Prévient les deux bouts puis ferme les connexions."""
        for role, ws in list((self.bouts.get(sid) or {}).items()):
            try:
                await ws.send_json({"type": "fin", "motif": motif})
                await ws.close(code=1000)
            except Exception:  # noqa: BLE001
                pass
        self.bouts.pop(sid, None)


# ---------------------------------------------------------------------------------------------------------------------
# Modèles des requêtes
# ---------------------------------------------------------------------------------------------------------------------
class DemandeSession(BaseModel):
    poste_id: str = Field(..., min_length=1, max_length=200)
    mode: str = Field("controler", pattern="^(voir|controler)$")
    motif: Optional[str] = Field(None, max_length=200)


class ReponsePoste(BaseModel):
    accepte: bool
    # L'utilisateur du poste peut réduire le mode demandé (« contrôler » → « voir seulement »), jamais l'augmenter
    mode: Optional[str] = Field(None, pattern="^(voir|controler)$")
    # Lot 131.1 : accord donné AUTOMATIQUEMENT par un poste sans surveillance (clé « LKS-… » obligatoire)
    automatique: bool = False


def creer_routeur(*, db, get_current_user: Callable[..., Awaitable[Dict[str, Any]]],
                  identifier_cle: Optional[Callable[..., Awaitable[Optional[Dict[str, Any]]]]] = None,
                  decode_token: Optional[Callable[[str], Dict[str, Any]]] = None) -> APIRouter:
    """Routes du contrôle à distance. Dépendances injectées pour que les tests puissent les simuler."""
    router = APIRouter(tags=["Contrôle à distance"])
    relais = Relais()
    router.relais = relais  # accès pour les tests

    if identifier_cle is None:
        from routes.loois_cles_clients import identifier_cle as _identifier
        identifier_cle = _identifier
    if decode_token is None:
        from auth import decode_token as _decode
        decode_token = _decode

    # --- Outils internes ----------------------------------------------------------------------------------------
    _derniere_fiche: Dict[str, float] = {}   # lot 131.1 : poste → dernière écriture de sa fiche (time.monotonic)

    async def _technicien(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if not est_technicien(user):
            raise HTTPException(status_code=403, detail="Réservé au support SAWALI")
        return user

    async def _poste_de_la_requete(request: Request) -> Dict[str, Any]:
        """Le poste prouve son identité par sa clé CLIENT (en-tête X-Loois-Cle) ; la clé commune est refusée."""
        identite = await identifier_cle(db, request.headers.get("x-loois-cle"))
        if not identite or identite.get("type") != "client":
            raise HTTPException(status_code=401, detail="Clé client Loois requise")
        return identite

    async def _expirer(session: Dict[str, Any]) -> Dict[str, Any]:
        """Passe en « expiree » une demande sans réponse ou un accord sans connexion, au-delà du délai."""
        if session.get("statut") == "demandee" and session.get("expire_le", "") < iso(maintenant()):
            await db.controle_distance_sessions.update_one(
                {"id": session["id"], "statut": "demandee"},
                {"$set": {"statut": "expiree", "fin_le": iso(maintenant()), "motif_fin": "sans réponse du poste"}})
            session["statut"] = "expiree"
        return session

    async def _terminer(sid: str, motif: str) -> None:
        """Clôt la session et complète le journal (durée)."""
        s = await db.controle_distance_sessions.find_one({"id": sid}, {"_id": 0})
        if not s or s.get("statut") in ("terminee", "refusee", "expiree"):
            await relais.fermer(sid, motif)
            return
        fin = maintenant()
        debut = s.get("debut_le") or s.get("accepte_le") or s.get("cree_le")
        try:
            duree = int((fin - datetime.fromisoformat(debut)).total_seconds()) if debut else 0
        except ValueError:
            duree = 0
        await db.controle_distance_sessions.update_one(
            {"id": sid}, {"$set": {"statut": "terminee", "fin_le": iso(fin), "duree_s": max(0, duree),
                                   "motif_fin": motif}})
        await relais.fermer(sid, motif)
        logger.info("[controle_distance] session %s terminée (%s, %s s)", sid, motif, duree)

    # --- 1. Le technicien demande une session -------------------------------------------------------------------
    @router.post("/controle-distance/sessions")
    async def demander(payload: DemandeSession, user: Dict[str, Any] = Depends(_technicien)):
        poste = await db.support_loois_postes.find_one({"id": payload.poste_id}, {"_id": 0})
        if not poste:
            raise HTTPException(status_code=404, detail="Poste Loois inconnu")
        if not poste.get("cle_client_code"):
            raise HTTPException(status_code=403,
                                detail="Ce poste n'utilise pas de clé client : prise en main impossible")
        # Lot 131.1 : poste sans surveillance (clé « LKS-… ») → il accepte seul : réservé au super-admin
        if poste.get("sans_surveillance") and not est_super_admin(user):
            raise HTTPException(status_code=403, detail="Poste sans surveillance : prise en main réservée au super-admin")
        # Une seule demande ou session ouverte à la fois par poste
        ouverte = await db.controle_distance_sessions.find_one(
            {"poste_id": payload.poste_id, "statut": {"$in": ["demandee", "acceptee", "en_cours"]}}, {"_id": 0})
        if ouverte:
            ouverte = await _expirer(ouverte)
            if ouverte.get("statut") != "expiree":
                raise HTTPException(status_code=409, detail="Une session est déjà ouverte pour ce poste")
        session = {
            "id": str(uuid.uuid4()), "poste_id": payload.poste_id, "poste_nom": poste.get("nom"),
            "cle_client_code": poste.get("cle_client_code"),
            "technicien_id": user.get("id"), "technicien_nom": user.get("full_name") or user.get("email"),
            "mode_demande": payload.mode, "mode": payload.mode, "motif": (payload.motif or "").strip(),
            "statut": "demandee", "cree_le": iso(maintenant()),
            "poste_sans_surveillance": bool(poste.get("sans_surveillance")),
            "expire_le": iso(maintenant() + timedelta(seconds=DELAI_REPONSE_S)),
        }
        await db.controle_distance_sessions.insert_one(dict(session))
        session.pop("_id", None)
        return {"session_id": session["id"], "statut": "demandee", "delai_reponse_s": DELAI_REPONSE_S}

    # --- 2. Le poste vérifie s'il a une demande en attente --------------------------------------------------------
    @router.get("/controle-distance/poste/demande")
    async def demande_en_attente(request: Request, poste_id: Optional[str] = None,
                                 identite: Dict[str, Any] = Depends(_poste_de_la_requete)):
        # Sans poste_id : identifiant déduit des en-têtes X-Loois-Ecole / -Poste / -Utilisateur (même calcul
        # que le support Loois, donc le même fil de discussion et la même fiche de poste)
        if not poste_id:
            from urllib.parse import unquote
            from routes.support_loois import nettoyer, nom_affiche, poste_id as calculer_poste_id
            h = request.headers
            ecole = nettoyer(unquote(h.get("x-loois-ecole") or ""), 80)
            nom_poste = nettoyer(unquote(h.get("x-loois-poste") or ""), 60)
            utilisateur = nettoyer(unquote(h.get("x-loois-utilisateur") or ""), 60)
            poste_id = calculer_poste_id(ecole, nom_poste, utilisateur)
            # Lot 131.1 : fiche du poste tenue à jour (au plus une écriture par minute), même s'il n'a jamais ouvert le
            # chat du support : il apparaît ainsi dans la liste des postes de la rubrique « Contrôle à distance »
            if time.monotonic() - _derniere_fiche.get(poste_id, 0.0) > 60:
                _derniere_fiche[poste_id] = time.monotonic()
                await db.support_loois_postes.update_one(
                    {"id": poste_id},
                    {"$set": {"nom": nom_affiche(ecole, nom_poste, utilisateur), "ecole": ecole, "poste": nom_poste,
                              "utilisateur": utilisateur, "cle_client_code": identite.get("code"),
                              "cle_client_libelle": identite.get("libelle"),
                              "sans_surveillance": bool(identite.get("sans_surveillance")),
                              "signal_controle_distance": iso(maintenant())},
                     "$setOnInsert": {"id": poste_id, "premier_contact": iso(maintenant())}},
                    upsert=True)
        s = await db.controle_distance_sessions.find_one(
            {"poste_id": poste_id, "statut": "demandee", "cle_client_code": identite.get("code")}, {"_id": 0},
            sort=[("cree_le", -1)])
        if not s:
            return {"demande": None}
        s = await _expirer(s)
        if s.get("statut") != "demandee":
            return {"demande": None}
        return {"demande": {"session_id": s["id"], "technicien": s.get("technicien_nom"), "mode": s.get("mode"),
                            "motif": s.get("motif"), "expire_le": s.get("expire_le"),
                            # Lot 131.1 : vrai si CE poste utilise la clé sans surveillance → Loois accepte seul
                            "sans_surveillance": bool(identite.get("sans_surveillance"))}}

    # --- 3. Le poste accepte ou refuse -----------------------------------------------------------------------------
    @router.post("/controle-distance/poste/sessions/{sid}/reponse")
    async def repondre(sid: str, payload: ReponsePoste, identite: Dict[str, Any] = Depends(_poste_de_la_requete)):
        s = await db.controle_distance_sessions.find_one({"id": sid, "cle_client_code": identite.get("code")},
                                                         {"_id": 0})
        if not s:
            raise HTTPException(status_code=404, detail="Demande introuvable")
        s = await _expirer(s)
        if s.get("statut") != "demandee":
            raise HTTPException(status_code=409, detail="Demande expirée ou déjà traitée")
        # Lot 131.1 : un accord automatique n'est admis que d'un poste muni de la clé sans surveillance
        automatique = bool(payload.accepte and payload.automatique)
        if automatique and not identite.get("sans_surveillance"):
            raise HTTPException(status_code=403, detail="Accord automatique réservé aux postes sans surveillance")
        if not payload.accepte:
            await db.controle_distance_sessions.update_one(
                {"id": sid}, {"$set": {"statut": "refusee", "fin_le": iso(maintenant()),
                                       "motif_fin": "refusée par l'utilisateur du poste"}})
            return {"statut": "refusee"}
        # Le poste peut seulement réduire les droits demandés
        mode = s["mode_demande"]
        if payload.mode == "voir":
            mode = "voir"
        jeton_poste, jeton_tech = nouveau_jeton(), nouveau_jeton()
        resultat = await db.controle_distance_sessions.update_one(
            {"id": sid, "statut": "demandee"},
            {"$set": {"statut": "acceptee", "mode": mode, "accepte_le": iso(maintenant()),
                      "sans_surveillance": automatique,   # lot 131.1 : accord donné par le poste sans surveillance
                      "connexion_avant": iso(maintenant() + timedelta(seconds=DELAI_CONNEXION_S)),
                      "jeton_poste_hash": empreinte(jeton_poste), "jeton_poste_utilise": False,
                      "jeton_tech_hash": empreinte(jeton_tech), "jeton_tech_utilise": False,
                      "jeton_tech_remis": False}})
        if not resultat.modified_count:
            raise HTTPException(status_code=409, detail="Demande déjà traitée")
        # Le jeton du technicien est gardé en mémoire le temps qu'il le récupère (une seule fois)
        _jetons_tech_a_remettre[sid] = jeton_tech
        return {"statut": "acceptee", "mode": mode, "jeton": jeton_poste, "duree_max_s": DUREE_MAX_S}

    _jetons_tech_a_remettre: Dict[str, str] = {}

    # --- 4. Le technicien suit sa demande (et reçoit son jeton une seule fois) -------------------------------------
    @router.get("/controle-distance/sessions/{sid}")
    async def etat(sid: str, user: Dict[str, Any] = Depends(_technicien)):
        s = await db.controle_distance_sessions.find_one({"id": sid}, {"_id": 0})
        if not s or s.get("technicien_id") != user.get("id"):
            raise HTTPException(status_code=404, detail="Session introuvable")
        s = await _expirer(s)
        reponse = {"session_id": sid, "statut": s["statut"], "mode": s.get("mode"), "poste_nom": s.get("poste_nom"),
                   "motif_fin": s.get("motif_fin")}
        if s["statut"] == "acceptee" and not s.get("jeton_tech_remis"):
            jeton = _jetons_tech_a_remettre.pop(sid, None)
            if jeton:
                await db.controle_distance_sessions.update_one({"id": sid}, {"$set": {"jeton_tech_remis": True}})
                reponse["jeton"] = jeton
        return reponse

    @router.post("/controle-distance/sessions/{sid}/arreter")
    async def arreter(sid: str, user: Dict[str, Any] = Depends(_technicien)):
        s = await db.controle_distance_sessions.find_one({"id": sid}, {"_id": 0})
        if not s or s.get("technicien_id") != user.get("id"):
            raise HTTPException(status_code=404, detail="Session introuvable")
        if s.get("statut") == "demandee":
            await db.controle_distance_sessions.update_one(
                {"id": sid}, {"$set": {"statut": "terminee", "fin_le": iso(maintenant()),
                                       "motif_fin": "demande annulée par le technicien"}})
            return {"statut": "terminee"}
        await _terminer(sid, "arrêtée par le technicien")
        return {"statut": "terminee"}

    # --- Lot 131.1 : postes Loois munis d'une clé client (les plus récents d'abord) ------------------------------------
    @router.get("/controle-distance/postes")
    async def postes(user: Dict[str, Any] = Depends(_technicien)):
        curseur = db.support_loois_postes.find(
            {"cle_client_code": {"$nin": [None, ""]}},
            {"_id": 0, "id": 1, "nom": 1, "cle_client_code": 1, "cle_client_libelle": 1, "sans_surveillance": 1,
             "signal_controle_distance": 1, "dernier_contact": 1}).sort("signal_controle_distance", -1).limit(500)
        return {"postes": [p async for p in curseur], "super_admin": est_super_admin(user)}

    # --- Lot 131.1 : le technicien peut-il prendre la main sur ce poste ? ---------------------------------------------
    @router.get("/controle-distance/postes/{poste_id}")
    async def etat_poste(poste_id: str, user: Dict[str, Any] = Depends(_technicien)):
        """Bouton « Prendre la main » : visible si le poste a une clé client ; « sans surveillance » si sa clé est LKS-."""
        p = await db.support_loois_postes.find_one(
            {"id": poste_id}, {"_id": 0, "nom": 1, "cle_client_code": 1, "sans_surveillance": 1, "dernier_contact": 1})
        if not p:
            return {"possible": False, "sans_surveillance": False}
        ouverte = await db.controle_distance_sessions.find_one(
            {"poste_id": poste_id, "statut": {"$in": ["demandee", "acceptee", "en_cours"]}}, {"_id": 0, "id": 1})
        return {"possible": bool(p.get("cle_client_code")), "sans_surveillance": bool(p.get("sans_surveillance")),
                "poste_nom": p.get("nom"), "dernier_contact": p.get("dernier_contact"),
                "session_ouverte": bool(ouverte)}

    # --- Journal des sessions --------------------------------------------------------------------------------------
    @router.get("/controle-distance/journal")
    async def journal(limite: int = 100, user: Dict[str, Any] = Depends(_technicien)):
        curseur = db.controle_distance_sessions.find(
            {}, {"_id": 0, "jeton_poste_hash": 0, "jeton_tech_hash": 0}).sort("cree_le", -1).limit(max(1, min(limite, 500)))
        return {"sessions": [s async for s in curseur]}

    # --- 5 à 7. Relais WebSocket -------------------------------------------------------------------------------------
    async def _authentifier(websocket: WebSocket) -> Optional[Dict[str, Any]]:
        """Premier message obligatoire : {"type":"auth","role","session_id","jeton"} ; jeton à usage unique."""
        try:
            msg = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(msg, dict) or msg.get("type") != "auth":
            return None
        role, sid, jeton = msg.get("role"), str(msg.get("session_id") or ""), str(msg.get("jeton") or "")
        if role not in ("poste", "technicien") or not sid or not jeton:
            return None
        champ = "jeton_poste" if role == "poste" else "jeton_tech"
        # Consommation atomique du jeton : il ne peut servir qu'une fois, avant la limite de connexion
        s = await db.controle_distance_sessions.find_one_and_update(
            {"id": sid, "statut": {"$in": ["acceptee", "en_cours"]}, f"{champ}_hash": empreinte(jeton),
             f"{champ}_utilise": False, "connexion_avant": {"$gte": iso(maintenant())}},
            {"$set": {f"{champ}_utilise": True}}, projection={"_id": 0})
        if not s:
            return None
        return {"role": role, "session": s}

    @router.websocket("/ws/controle-distance")
    async def ws_controle(websocket: WebSocket):
        await websocket.accept()
        auth = await _authentifier(websocket)
        if not auth:
            await websocket.send_json({"type": "erreur", "detail": "Jeton invalide, expiré ou déjà utilisé"})
            await websocket.close(code=4401)
            return
        role, session = auth["role"], auth["session"]
        sid, mode = session["id"], session.get("mode", "voir")
        relais.brancher(sid, role, websocket)
        await websocket.send_json({"type": "pret", "mode": mode, "role": role})
        # Les deux bouts sont là : la session commence (début du chronomètre et du journal)
        if relais.autre(sid, role) is not None:
            await db.controle_distance_sessions.update_one(
                {"id": sid}, {"$set": {"statut": "en_cours", "debut_le": iso(maintenant())}})
            await relais.envoyer_json(sid, "poste", {"type": "debut", "mode": mode})
            await relais.envoyer_json(sid, "technicien", {"type": "debut", "mode": mode})
        limite_fin = maintenant() + timedelta(seconds=DUREE_MAX_S)
        motif = "connexion fermée"
        try:
            while True:
                if maintenant() > limite_fin:
                    motif = "durée maximale atteinte"
                    break
                trame = await websocket.receive()
                if trame.get("type") == "websocket.disconnect":
                    motif = f"déconnexion du {role}"
                    break
                donnees_bin, texte = trame.get("bytes"), trame.get("text")
                if donnees_bin is not None:
                    # Images : seulement du poste vers le technicien, taille bornée
                    if role == "poste" and len(donnees_bin) <= TAILLE_MAX_TRAME:
                        await relais.envoyer_binaire(sid, "technicien", donnees_bin)
                    continue
                if texte is None:
                    continue
                try:
                    message = json.loads(texte)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                if message.get("type") == "arreter":
                    motif = f"arrêtée par le {role}"
                    break
                if role == "technicien":
                    if commande_autorisee(mode, message):
                        await relais.envoyer_json(sid, "poste", message)
                    else:
                        await websocket.send_json({"type": "refuse", "detail": "Mode « voir seulement » : "
                                                                              "commande non transmise"})
                elif message_poste_autorise(message):
                    await relais.envoyer_json(sid, "technicien", message)
        except WebSocketDisconnect:
            motif = f"déconnexion du {role}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("[controle_distance] relais %s interrompu : %s", sid, exc)
        finally:
            relais.debrancher(sid, role)
            await _terminer(sid, motif)

    return router
