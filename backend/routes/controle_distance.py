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

Lot 135 (propriétaire, 12/10/2026) — EXTENSIONS :
  - commandes système (mode « contrôler ») : {"type":"systeme","action":"deconnecter|redemarrer|eteindre|verrouiller|
    ctrl_alt_suppr"} ; blocage du clavier et de la souris du poste {"type":"bloquer_entrees","valeur":1|0} ;
  - transfert de fichiers dans les deux sens : technicien → poste {"type":"fichier_debut","id","nom","taille"}, trames
    binaires de type 2 (octet 0 = 2, octets 1-4 = id u32 petit-boutiste, puis les données), {"type":"fichier_fin","id"} ;
    poste → technicien : {"type":"fichiers_lister","chemin"} / {"type":"fichier_demander","chemin"} puis trames de type 3 ;
  - réglages d'affichage : {"type":"echelle","valeur":100|75|50|25} (connexions lentes), {"type":"infos_demander"} ;
  - le poste envoie {"type":"infos_poste",…} (matériel, logiciels), {"type":"perf",…} (processeur, mémoire, disques,
    réseau), {"type":"bureau","nom","securise"} (écran de connexion ou verrouillé), {"type":"capture","moteur"} ;
  - identifiants Windows mémorisés par poste (chiffrés) : le technicien envoie {"type":"identifiants_windows"} et c'est LE
    SERVEUR qui transmet {"type":"saisir_identifiants",…} au poste — le mot de passe ne passe jamais par le navigateur ;
    avec « saisie automatique », il est saisi dès que le poste signale l'écran de connexion ;
  - numéro « CD-AAAA-NNNNN », ticket du client ouvert au début et clôturé à la fin (intervention dans la fiche client) ;
  - délais mesurés (accord, connexion, durée) + mesures de la visionneuse, résumé dans le journal d'activités ;
  - vidéo de la session envoyée par parties par la visionneuse, relue par un lien signé de courte durée ;
  - agent du SERVICE WINDOWS Loois (en-tête X-Loois-Agent: service) : fiche « machine » distincte, qui fonctionne
    écran verrouillé, à l'écran de connexion et session fermée.
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

from fastapi import APIRouter, Body, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from routes import controle_distance_outils as outils   # lot 135 : numéro, mesures, identifiants, vidéo, réglages

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
COMMANDES_ENTREE = {"souris", "clavier", "presse_papiers", "texte",
                    # Lot 135 : système, blocage des entrées, fichiers
                    "systeme", "bloquer_entrees", "fichier_debut", "fichier_fin", "fichier_annuler",
                    "fichiers_lister", "fichier_demander"}
# Commandes du technicien autorisées dans tous les modes (réglages de l'affichage)
COMMANDES_AFFICHAGE = {"choix_ecran", "qualite", "image_complete", "ping", "arreter",
                       "echelle", "infos_demander"}   # lot 135
# Lot 135 — commandes TRAITÉES PAR LE SERVEUR (jamais relayées telles quelles), mode « contrôler » seulement
COMMANDES_SERVEUR = {"identifiants_windows"}
# Lot 135 — actions système acceptées
# Lot 135.2 : bureaux virtuels de Windows (Win+Tab) — bascule VISIBLE de l'écran de l'utilisateur (raccourcis Win+Ctrl+→ / ← / D)
ACTIONS_SYSTEME = {"deconnecter", "redemarrer", "eteindre", "verrouiller", "ctrl_alt_suppr",
                   "bureau_suivant", "bureau_precedent", "bureau_nouveau"}
# Informations que le poste peut envoyer au technicien
MESSAGES_POSTE = {"ecrans", "curseur", "stats", "presse_papiers", "pong", "arreter", "erreur",
                  # Lot 135
                  "infos_poste", "perf", "bureau", "capture", "fichier_debut", "fichier_fin", "fichier_recu",
                  "fichiers_liste", "systeme_resultat", "entrees_bloquees"}
# Lot 135 — types des trames binaires (octet 0)
TRAME_TUILE, TRAME_FICHIER_VERS_POSTE, TRAME_FICHIER_VERS_TECHNICIEN = 1, 2, 3


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
    if type_ == "systeme" and str(message.get("action") or "") not in ACTIONS_SYSTEME:
        return False   # lot 135 : action système inconnue, jamais relayée
    if type_ in COMMANDES_ENTREE:
        return mode == "controler"
    return False   # type inconnu : jamais relayé


def trame_binaire_autorisee(role: str, mode: str, donnees: bytes) -> bool:
    """Lot 135 — trames binaires : tuiles et fichiers du poste vers le technicien ; fichiers du technicien vers le poste
    seulement en mode « contrôler » ; taille bornée."""
    if not donnees or len(donnees) > TAILLE_MAX_TRAME:
        return False
    if role == "poste":
        return donnees[0] in (TRAME_TUILE, TRAME_FICHIER_VERS_TECHNICIEN)
    return donnees[0] == TRAME_FICHIER_VERS_POSTE and mode == "controler"


def action_journal(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Lot 135 — commande du technicien à garder dans le journal de la session (sans contenu sensible) ; None sinon."""
    type_ = str(message.get("type") or "")
    if type_ == "systeme":
        return {"type": "systeme", "detail": str(message.get("action") or "")}
    if type_ == "bloquer_entrees":
        return {"type": "bloquer_entrees", "detail": "bloquées" if message.get("valeur") else "débloquées"}
    if type_ == "fichier_debut":
        dossier = str(message.get("chemin") or "")[:260]
        return {"type": "fichier_envoye", "detail": f"{str(message.get('nom') or '')[:120]} ({message.get('taille') or 0} o)"
                + (f" → {dossier}" if dossier else "")}
    if type_ == "fichier_demander":
        return {"type": "fichier_recupere", "detail": str(message.get("chemin") or "")[:260]}
    return None


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
    # Lot 135 : client SAWALI du poste (ticket automatique) — facultatif si le poste est déjà rattaché à un client
    client_id: Optional[str] = Field(None, max_length=100)


class IdentifiantsWindows(BaseModel):
    """Lot 135 — identifiant Windows mémorisé pour un poste (mot de passe vide = garder celui déjà enregistré)."""
    utilisateur: str = Field("", max_length=outils.MAX_UTILISATEUR)
    domaine: str = Field("", max_length=80)
    mot_de_passe: Optional[str] = Field(None, max_length=outils.MAX_MOT_DE_PASSE)
    saisie_auto: bool = True


class ReponsePoste(BaseModel):
    accepte: bool
    # L'utilisateur du poste peut réduire le mode demandé (« contrôler » → « voir seulement »), jamais l'augmenter
    mode: Optional[str] = Field(None, pattern="^(voir|controler)$")
    # Lot 131.1 : accord donné AUTOMATIQUEMENT par un poste sans surveillance (clé « LKS-… » obligatoire)
    automatique: bool = False


class StockageR2:
    """Lot 135 — accès au stockage des vidéos (R2 via storage.py) ; remplacé par un faux stockage dans les tests."""

    async def ecrire(self, chemin: str, donnees: bytes, type_mime: str) -> None:
        import storage
        await asyncio.to_thread(storage.upload_bytes, chemin, donnees, type_mime, False)

    async def lire(self, chemin: str) -> bytes:
        import storage
        donnees, _ = await asyncio.to_thread(storage.fetch_bytes, chemin)
        return donnees

    async def supprimer(self, chemin: str) -> None:
        import storage
        await asyncio.to_thread(storage.delete_bytes, chemin, False)


async def purger_videos(db, stockage: Any, *, jours: Optional[int] = None,
                        quand: Optional[datetime] = None) -> Dict[str, Any]:
    """Lot 135.1 — PURGE AUTOMATIQUE des vidéos des prises en main (réglage « conservation_jours », 90 par défaut).

    Pour un développeur WinDev : chaque nuit (planificateur, voir server_parts/p17_demarrage_planificateur.py), on
    cherche les sessions terminées depuis plus de N jours qui ont encore une vidéo ; on supprime ses parties dans R2
    et on note la purge dans la session (le journal garde tout le reste : numéro, durée, ticket, mesures, actions).
    Une partie impossible à supprimer est réessayée la nuit suivante (la session garde alors sa vidéo)."""
    if jours is None:
        doc = await db.controle_distance_reglages.find_one({"id": "reglages"}, {"_id": 0}) or {}
        jours = outils.reglages_valides(doc)["conservation_jours"]
    limite = iso((quand or maintenant()) - timedelta(days=int(jours)))
    curseur = db.controle_distance_sessions.find(
        {"video": True, "video_purgee": {"$ne": True},
         "$or": [{"fin_le": {"$lt": limite}}, {"fin_le": None, "cree_le": {"$lt": limite}}]},
        {"_id": 0, "id": 1, "video_parties": 1, "video_octets": 1})
    sessions, octets, erreurs = 0, 0, 0
    async for s in curseur:
        restantes = []
        for index in s.get("video_parties") or []:
            try:
                await stockage.supprimer(outils.chemin_partie_video(s["id"], int(index)))
            except Exception as exc:  # noqa: BLE001 — réessayée la nuit suivante
                erreurs += 1
                restantes.append(index)
                logger.warning("[controle_distance] purge vidéo %s partie %s : %s", s["id"], index, exc)
        if restantes:
            await db.controle_distance_sessions.update_one({"id": s["id"]}, {"$set": {"video_parties": restantes}})
            continue
        await db.controle_distance_sessions.update_one(
            {"id": s["id"]}, {"$set": {"video": False, "video_purgee": True, "video_purgee_le": iso(maintenant()),
                                       "video_parties": []}})
        sessions += 1
        octets += int(s.get("video_octets") or 0)
    if sessions or erreurs:
        logger.info("[controle_distance] purge des vidéos (> %s j) : %s session(s), %s octet(s), %s erreur(s)",
                    jours, sessions, octets, erreurs)
    return {"jours": int(jours), "sessions": sessions, "octets": octets, "erreurs": erreurs}


def creer_routeur(*, db, get_current_user: Callable[..., Awaitable[Dict[str, Any]]],
                  identifier_cle: Optional[Callable[..., Awaitable[Optional[Dict[str, Any]]]]] = None,
                  decode_token: Optional[Callable[[str], Dict[str, Any]]] = None,
                  tickets: Any = None, stockage: Any = None) -> APIRouter:
    """Routes du contrôle à distance. Dépendances injectées pour que les tests puissent les simuler.
    Lot 135 : `tickets` (module tickets_clients, clôture du ticket) et `stockage` (vidéos) injectables."""
    router = APIRouter(tags=["Contrôle à distance"])
    relais = Relais()
    router.relais = relais  # accès pour les tests
    stockage = stockage or StockageR2()

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

    # --- Lot 135 : outils internes des extensions --------------------------------------------------------------------
    _identifiants_saisis: set = set()      # sessions où l'identifiant Windows a déjà été saisi automatiquement

    async def _reglages() -> Dict[str, Any]:
        doc = await db.controle_distance_reglages.find_one({"id": "reglages"}, {"_id": 0}) or {}
        return outils.reglages_valides(doc)

    async def _numero() -> str:
        """Numéro « CD-AAAA-NNNNN » tiré d'un compteur atomique annuel."""
        annee = maintenant().year
        res = await db.counters.find_one_and_update({"_id": outils.compteur_annuel(annee)}, {"$inc": {"seq": 1}},
                                                    upsert=True, return_document=True)
        if res is None:   # certains pilotes renvoient None à la création
            res = await db.counters.find_one({"_id": outils.compteur_annuel(annee)})
        return outils.numero_session(annee, int((res or {}).get("seq", 1)))

    async def _client_du_poste(poste: Dict[str, Any], demande: Optional[str]) -> Optional[Dict[str, Any]]:
        """Client SAWALI de la prise en main : choisi par le technicien, sinon celui du poste, sinon par le nom du site."""
        candidats = [demande, poste.get("client_id")]
        for cid in candidats:
            if cid:
                c = await db.users.find_one({"id": cid}, {"_id": 0, "id": 1, "company": 1, "full_name": 1})
                if c:
                    return c
        try:
            from routes.support_loois_sessions import client_par_nom
            cid = await client_par_nom(db, poste.get("ecole"))
        except Exception:  # noqa: BLE001 — recherche facultative
            cid = None
        if cid:
            return await db.users.find_one({"id": cid}, {"_id": 0, "id": 1, "company": 1, "full_name": 1})
        return None

    def _id_machine(poste: Dict[str, Any]) -> str:
        """Identifiant de l'ORDINATEUR (sans l'utilisateur Windows) : sert aux identifiants Windows mémorisés,
        communs à toutes les fiches d'un même poste (icône de l'utilisateur et service Windows)."""
        if poste.get("ecole") is not None and poste.get("poste"):
            from routes.support_loois import poste_id as calculer_poste_id
            # Lot 135.7 : le CLIENT (clé Loois) fait partie de l'identifiant. Avant, deux clients ayant un ordinateur de même
            # nom (ex. « XVERSER » chez trois pharmacies, « école » = nom de la machine) partageaient les mêmes
            # identifiants Windows et les mêmes dossiers : on affichait ceux d'une autre machine.
            ecole = f"{poste.get('cle_client_code') or ''}|{poste.get('ecole') or ''}"
            return calculer_poste_id(ecole, poste.get("poste") or "", "")
        return str(poste.get("id") or "")

    async def _ouvrir_ticket(session: Dict[str, Any]) -> None:
        """Ticket du client ouvert au DÉBUT de la prise en main (même forme que les tickets du support Loois)."""
        if session.get("ticket_id") or not session.get("client_id") or not (await _reglages())["ticket_automatique"]:
            return
        client_doc = await db.users.find_one({"id": session["client_id"]}, {"_id": 0, "password_hash": 0})
        if not client_doc:
            return
        try:
            from routes.support_loois_sessions import numero_ticket
            numero_tk = await numero_ticket(db, client_doc)
        except Exception:  # noqa: BLE001
            numero_tk = f"TKT-{session.get('numero')}"
        quand = iso(maintenant())
        motif = f"Prise en main {session.get('numero') or ''} — {session.get('poste_nom') or 'poste Loois'}"
        if session.get("motif"):
            motif += f" ({session['motif']})"
        ticket = {
            "id": uuid.uuid4().hex, "number": numero_tk, "client_id": client_doc["id"],
            "contact_id": session.get("poste_id"), "contact_name": session.get("poste_nom"), "contact_phone": None,
            "contact_ids": [], "motif": motif[:300], "status": "open", "notes": None,
            "opened_at": quand, "opened_by_id": session.get("technicien_id"), "opened_by_label": session.get("technicien_nom"),
            "closed_at": None, "closed_by_id": None, "closed_by_label": None, "outcome": None, "resolution_note": None,
            "created_at": quand, "updated_at": quand, "session_wa_minutes": None, "session_wa_debut": None,
            "session_wa_fin": None, "rappels_envoyes": [],
            "source": "controle_distance", "controle_distance_id": session["id"], "poste_id": session.get("poste_id"),
        }
        await db.support_tickets.insert_one(dict(ticket))
        await db.controle_distance_sessions.update_one(
            {"id": session["id"]}, {"$set": {"ticket_id": ticket["id"], "ticket_number": numero_tk}})
        await _evenement(client_doc["id"], "ticket", "created", f"{numero_tk} — {motif[:80]}", ticket["id"], session)

    async def _evenement(client_id: Optional[str], kind: str, action: str, libelle: str, cible: str,
                         session: Dict[str, Any]) -> None:
        """Fil d'activité du client (journal d'activités) ; jamais bloquant."""
        if not client_id:
            return
        try:
            await db.activity_events.insert_one({
                "id": uuid.uuid4().hex, "client_id": client_id, "kind": kind, "action": action, "label": libelle,
                "target_id": cible, "actor_id": session.get("technicien_id"), "actor_label": session.get("technicien_nom"),
                "ts": iso(maintenant())})
        except Exception:  # noqa: BLE001
            pass

    async def _cloturer_ticket(session: Dict[str, Any], motif: str) -> None:
        """Ticket clôturé à la fin (intervention créée dans l'historique du client)."""
        if not session.get("ticket_id"):
            return
        ticket = await db.support_tickets.find_one({"id": session["ticket_id"]}, {"_id": 0})
        if not ticket:
            return
        try:
            module = tickets
            if module is None:
                import tickets_clients as module  # noqa: PLW0127 — import tardif (base réelle)
            bilan = await module.cloturer_ticket(
                ticket, outcome="done",
                acteur={"id": session.get("technicien_id"), "full_name": session.get("technicien_nom")},
                note=f"Prise en main {session.get('numero') or ''} terminée ({motif})")
            inter = (bilan or {}).get("intervention") or {}
            if inter:
                await db.controle_distance_sessions.update_one({"id": session["id"]}, {"$set": {
                    "intervention_id": inter.get("id"), "intervention_number": inter.get("intervention_number")}})
        except Exception:  # noqa: BLE001 — la session se termine même si l'historique échoue
            logger.exception("[controle_distance] clôture du ticket %s impossible", session.get("ticket_id"))

    async def _noter_action(sid: str, action: Dict[str, Any]) -> None:
        """Action du technicien gardée dans le journal de la session (200 dernières)."""
        try:
            await db.controle_distance_sessions.update_one(
                {"id": sid}, {"$push": {"actions": {"$each": [{**action, "le": iso(maintenant())}], "$slice": -200}}})
        except Exception:  # noqa: BLE001
            pass

    async def _injecter_identifiants(sid: str, session: Dict[str, Any], origine: str) -> Optional[str]:
        """Envoie au POSTE l'identifiant Windows mémorisé (le navigateur ne le reçoit jamais). Renvoie une erreur lisible."""
        poste = await db.support_loois_postes.find_one({"id": session.get("poste_id")}, {"_id": 0}) or {}
        doc = await db.controle_distance_identifiants.find_one({"id": _id_machine(poste or {"id": session.get("poste_id")})},
                                                               {"_id": 0})
        trame = outils.trame_identifiants(doc or {})
        if not trame:
            return "Aucun identifiant Windows mémorisé pour ce poste (ou à saisir de nouveau)."
        if not await relais.envoyer_json(sid, "poste", trame):
            return "Poste injoignable."
        await _noter_action(sid, {"type": "identifiants_windows", "detail": origine})
        return None

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
        # Lot 135 : délais mesurés (accord, connexion) gardés avec la session
        delais = outils.delais_session(s, iso(fin))
        resultat = await db.controle_distance_sessions.update_one(
            {"id": sid, "statut": {"$nin": ["terminee", "refusee", "expiree"]}},
            {"$set": {"statut": "terminee", "fin_le": iso(fin), "duree_s": max(0, duree),
                      "delai_accord_s": delais["delai_accord_s"], "delai_connexion_s": delais["delai_connexion_s"],
                      "motif_fin": motif}})
        await relais.fermer(sid, motif)
        _identifiants_saisis.discard(sid)
        if not resultat.modified_count:
            return   # déjà clôturée par l'autre bout
        logger.info("[controle_distance] session %s terminée (%s, %s s)", sid, motif, duree)
        # Lot 135 : ticket clôturé + journal d'activités du client (temps de connexion)
        s = await db.controle_distance_sessions.find_one({"id": sid}, {"_id": 0}) or s
        await _cloturer_ticket(s, motif)
        await _evenement(s.get("client_id"), "controle_distance", "terminee", outils.resume_mesures(s), sid, s)

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
        # Lot 135 : client SAWALI de la prise en main (ticket automatique) ; le choix du technicien est retenu pour le poste
        client = await _client_du_poste(poste, payload.client_id)
        if client and payload.client_id and client["id"] == payload.client_id and poste.get("client_id") != client["id"]:
            await db.support_loois_postes.update_one({"id": payload.poste_id}, {"$set": {"client_id": client["id"]}})
        session = {
            "id": str(uuid.uuid4()), "numero": await _numero(),   # lot 135 : « CD-AAAA-NNNNN »
            "poste_id": payload.poste_id, "poste_nom": poste.get("nom"),
            "agent_service": bool(poste.get("agent_service")),
            "client_id": (client or {}).get("id"),
            "client_nom": (client or {}).get("company") or (client or {}).get("full_name"),
            "cle_client_code": poste.get("cle_client_code"),
            "technicien_id": user.get("id"), "technicien_nom": user.get("full_name") or user.get("email"),
            "mode_demande": payload.mode, "mode": payload.mode, "motif": (payload.motif or "").strip(),
            "statut": "demandee", "cree_le": iso(maintenant()),
            "poste_sans_surveillance": bool(poste.get("sans_surveillance")),
            "expire_le": iso(maintenant() + timedelta(seconds=DELAI_REPONSE_S)),
        }
        await db.controle_distance_sessions.insert_one(dict(session))
        session.pop("_id", None)
        return {"session_id": session["id"], "numero": session["numero"], "statut": "demandee",
                "delai_reponse_s": DELAI_REPONSE_S, "client_nom": session["client_nom"]}

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
            # Lot 135 : agent du SERVICE WINDOWS Loois → fiche « machine » (sans utilisateur), qui fonctionne écran
            # verrouillé, à l'écran de connexion et session fermée
            agent_service = (h.get("x-loois-agent") or "").strip().lower() == "service"
            if agent_service:
                utilisateur = ""
            poste_id = calculer_poste_id(ecole, nom_poste, utilisateur)
            # Lot 131.1 : fiche du poste tenue à jour (au plus une écriture par minute), même s'il n'a jamais ouvert le
            # chat du support : il apparaît ainsi dans la liste des postes de la rubrique « Contrôle à distance »
            if time.monotonic() - _derniere_fiche.get(poste_id, 0.0) > 60:
                _derniere_fiche[poste_id] = time.monotonic()
                await db.support_loois_postes.update_one(
                    {"id": poste_id},
                    {"$set": {"nom": nom_affiche(ecole, nom_poste, utilisateur) + (" · service Windows" if agent_service else ""),
                              "agent_service": agent_service, "ecole": ecole, "poste": nom_poste,
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
                            "numero": s.get("numero"),   # lot 135 : affiché dans la fenêtre d'accord
                            "enregistree": bool((await _reglages())["enregistrement_video"]),   # lot 135 : bandeau « REC »
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
                   "motif_fin": s.get("motif_fin"),
                   # Lot 135
                   "numero": s.get("numero"), "client_nom": s.get("client_nom"), "ticket_number": s.get("ticket_number")}
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
             "signal_controle_distance": 1, "dernier_contact": 1,
             # Lot 135 : agent du service Windows, site, ordinateur, client
             "agent_service": 1, "ecole": 1, "poste": 1, "client_id": 1}).sort("signal_controle_distance", -1).limit(500)
        return {"postes": [p async for p in curseur], "super_admin": est_super_admin(user)}

    # --- Lot 131.1 : le technicien peut-il prendre la main sur ce poste ? ---------------------------------------------
    @router.get("/controle-distance/postes/{poste_id}")
    async def etat_poste(poste_id: str, user: Dict[str, Any] = Depends(_technicien)):
        """Bouton « Prendre la main » : visible si le poste a une clé client ; « sans surveillance » si sa clé est LKS-."""
        p = await db.support_loois_postes.find_one({"id": poste_id}, {"_id": 0})
        if not p:
            return {"possible": False, "sans_surveillance": False}
        ouverte = await db.controle_distance_sessions.find_one(
            {"poste_id": poste_id, "statut": {"$in": ["demandee", "acceptee", "en_cours"]}}, {"_id": 0, "id": 1})
        # Lot 135 : fil du chat du support (pour une fiche « service Windows », celui de l'utilisateur du même ordinateur),
        # client rattaché et identifiant Windows mémorisé (sans le mot de passe)
        fil_id, fiche_service = poste_id, None
        if p.get("agent_service"):
            autre = await db.support_loois_postes.find_one(
                {"ecole": p.get("ecole"), "poste": p.get("poste"), "agent_service": {"$ne": True}, "id": {"$ne": poste_id}},
                {"_id": 0, "id": 1}, sort=[("dernier_contact", -1)])
            fil_id = (autre or {}).get("id")
        elif p.get("poste"):
            # Fiche « service Windows » du même ordinateur (proposée quand l'écran de connexion est affiché)
            fiche_service = await db.support_loois_postes.find_one(
                {"ecole": p.get("ecole"), "poste": p.get("poste"), "agent_service": True}, {"_id": 0, "id": 1, "nom": 1})
        client = await _client_du_poste(p, None)
        identifiants = await db.controle_distance_identifiants.find_one({"id": _id_machine(p)}, {"_id": 0})
        return {"possible": bool(p.get("cle_client_code")), "sans_surveillance": bool(p.get("sans_surveillance")),
                "poste_nom": p.get("nom"), "dernier_contact": p.get("dernier_contact"),
                "session_ouverte": bool(ouverte),
                "agent_service": bool(p.get("agent_service")), "fil_id": fil_id, "fiche_service": fiche_service,
                "client_id": (client or {}).get("id"),
                "client_nom": (client or {}).get("company") or (client or {}).get("full_name"),
                "identifiants": outils.identifiants_publics(identifiants)}

    # --- Lot 135 : identifiants Windows mémorisés par ordinateur (item 7) ----------------------------------------------
    @router.get("/controle-distance/postes/{poste_id}/identifiants")
    async def lire_identifiants(poste_id: str, user: Dict[str, Any] = Depends(_technicien)):
        p = await db.support_loois_postes.find_one({"id": poste_id}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Poste Loois inconnu")
        doc = await db.controle_distance_identifiants.find_one({"id": _id_machine(p)}, {"_id": 0})
        return outils.identifiants_publics(doc)

    @router.put("/controle-distance/postes/{poste_id}/identifiants")
    async def enregistrer_identifiants(poste_id: str, payload: IdentifiantsWindows,
                                       user: Dict[str, Any] = Depends(_technicien)):
        p = await db.support_loois_postes.find_one({"id": poste_id}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Poste Loois inconnu")
        mid = _id_machine(p)
        champs: Dict[str, Any] = {"utilisateur": payload.utilisateur.strip(), "domaine": payload.domaine.strip(),
                                  "saisie_auto": payload.saisie_auto, "maj_le": iso(maintenant()),
                                  "maj_par": user.get("full_name") or user.get("email"), "poste_nom": p.get("nom")}
        if payload.mot_de_passe:
            champs["mdp_chiffre"] = outils.chiffrer(payload.mot_de_passe)
        else:
            existant = await db.controle_distance_identifiants.find_one({"id": mid}, {"_id": 0, "mdp_chiffre": 1})
            if not (existant or {}).get("mdp_chiffre"):
                raise HTTPException(status_code=400, detail="Saisissez le mot de passe Windows.")
        await db.controle_distance_identifiants.update_one({"id": mid}, {"$set": champs, "$setOnInsert": {"id": mid}},
                                                           upsert=True)
        logger.info("[controle_distance] identifiant Windows mémorisé pour %s par %s", p.get("nom"), champs["maj_par"])
        return outils.identifiants_publics(await db.controle_distance_identifiants.find_one({"id": mid}, {"_id": 0}))

    @router.delete("/controle-distance/postes/{poste_id}/identifiants")
    async def oublier_identifiants(poste_id: str, user: Dict[str, Any] = Depends(_technicien)):
        p = await db.support_loois_postes.find_one({"id": poste_id}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Poste Loois inconnu")
        await db.controle_distance_identifiants.delete_one({"id": _id_machine(p)})
        return outils.identifiants_publics(None)

    # --- Lot 135 : dossiers des transferts de fichiers mémorisés par ordinateur ----------------------------------------
    #   dossier_base   : lecteur + dossier où arrivent les fichiers envoyés au poste (vide = « Reçu du support SAWALI »
    #                    sur le Bureau) et point de départ du parcours ;
    #   dernier_chemin : dernier dossier parcouru, enregistré à la fermeture de la visionneuse (repris à l'ouverture).
    @router.get("/controle-distance/postes/{poste_id}/dossiers")
    async def lire_dossiers(poste_id: str, user: Dict[str, Any] = Depends(_technicien)):
        p = await db.support_loois_postes.find_one({"id": poste_id}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Poste Loois inconnu")
        doc = await db.controle_distance_dossiers.find_one({"id": _id_machine(p)}, {"_id": 0}) or {}
        return {"dossier_base": doc.get("dossier_base") or "", "dernier_chemin": doc.get("dernier_chemin") or ""}

    @router.put("/controle-distance/postes/{poste_id}/dossiers")
    async def enregistrer_dossiers(poste_id: str, payload: Dict[str, Any] = Body(...),
                                   user: Dict[str, Any] = Depends(_technicien)):
        p = await db.support_loois_postes.find_one({"id": poste_id}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Poste Loois inconnu")
        champs: Dict[str, Any] = {}
        for cle in ("dossier_base", "dernier_chemin"):   # seuls les champs envoyés changent
            if cle in (payload or {}):
                champs[cle] = str(payload.get(cle) or "").strip()[:260]
        if champs:
            mid = _id_machine(p)
            await db.controle_distance_dossiers.update_one(
                {"id": mid}, {"$set": {**champs, "maj_le": iso(maintenant())}, "$setOnInsert": {"id": mid}}, upsert=True)
        doc = await db.controle_distance_dossiers.find_one({"id": _id_machine(p)}, {"_id": 0}) or {}
        return {"dossier_base": doc.get("dossier_base") or "", "dernier_chemin": doc.get("dernier_chemin") or ""}

    # --- Lot 135 : réglages de la rubrique (vidéo, ticket automatique) ------------------------------------------------
    @router.get("/controle-distance/reglages")
    async def lire_reglages(user: Dict[str, Any] = Depends(_technicien)):
        return await _reglages()

    @router.put("/controle-distance/reglages")
    async def enregistrer_reglages(payload: Dict[str, Any] = Body(...), user: Dict[str, Any] = Depends(_technicien)):
        reglages = outils.reglages_valides(payload or {})
        await db.controle_distance_reglages.update_one(
            {"id": "reglages"}, {"$set": {**reglages, "maj_le": iso(maintenant()),
                                          "maj_par": user.get("full_name") or user.get("email")}}, upsert=True)
        return reglages

    # --- Lot 135 : mesures de la visionneuse à la fin de la session (item 8) -------------------------------------------
    @router.post("/controle-distance/sessions/{sid}/mesures")
    async def enregistrer_mesures(sid: str, payload: Dict[str, Any] = Body(...),
                                  user: Dict[str, Any] = Depends(_technicien)):
        s = await db.controle_distance_sessions.find_one({"id": sid}, {"_id": 0})
        if not s or s.get("technicien_id") != user.get("id"):
            raise HTTPException(status_code=404, detail="Session introuvable")
        mesures = outils.nettoyer_mesures(payload or {})
        await db.controle_distance_sessions.update_one({"id": sid}, {"$set": {"mesures": mesures}})
        s["mesures"] = mesures
        await _evenement(s.get("client_id"), "controle_distance", "mesures", outils.resume_mesures(s), sid, s)
        return {"mesures": mesures, "resume": outils.resume_mesures(s)}

    # --- Lot 135 : vidéo de la session (item 4), envoyée par parties par la visionneuse --------------------------------
    @router.post("/controle-distance/sessions/{sid}/video/{index}")
    async def recevoir_video(sid: str, index: int, request: Request, user: Dict[str, Any] = Depends(_technicien)):
        s = await db.controle_distance_sessions.find_one({"id": sid}, {"_id": 0})
        if not s or s.get("technicien_id") != user.get("id"):
            raise HTTPException(status_code=404, detail="Session introuvable")
        if not 0 <= index <= 99_999:
            raise HTTPException(status_code=400, detail="Numéro de partie invalide")
        donnees = await request.body()
        if not donnees or len(donnees) > outils.TAILLE_MAX_PARTIE_VIDEO:
            raise HTTPException(status_code=413, detail="Partie de vidéo vide ou trop lourde")
        try:
            await stockage.ecrire(outils.chemin_partie_video(sid, index), donnees, "video/webm")
        except Exception as exc:  # noqa: BLE001 — stockage indisponible : la prise en main continue sans vidéo
            logger.warning("[controle_distance] vidéo %s partie %s non enregistrée : %s", sid, index, exc)
            raise HTTPException(status_code=503, detail="Stockage des vidéos indisponible")
        await db.controle_distance_sessions.update_one(
            {"id": sid}, {"$addToSet": {"video_parties": index}, "$inc": {"video_octets": len(donnees)},
                          "$set": {"video": True}})
        return {"ok": True}

    @router.post("/controle-distance/videos/purger")
    async def purger(user: Dict[str, Any] = Depends(_technicien)):
        """Lot 135.1 — purge immédiate (bouton de la rubrique) ; sinon chaque nuit par le planificateur."""
        return await purger_videos(db, stockage)

    @router.get("/controle-distance/sessions/{sid}/video/lien")
    async def lien_video(sid: str, user: Dict[str, Any] = Depends(_technicien)):
        s = await db.controle_distance_sessions.find_one({"id": sid}, {"_id": 0, "video_parties": 1})
        if not s or not s.get("video_parties"):
            raise HTTPException(status_code=404, detail="Aucune vidéo pour cette session")
        p = outils.lien_video(sid)
        return {"url": f"/api/controle-distance/videos/{sid}?exp={p['exp']}&sig={p['sig']}"}

    @router.get("/controle-distance/videos/{sid}")
    async def lire_video(sid: str, exp: int = 0, sig: str = ""):
        """Lecture de la vidéo (lien signé de 15 minutes) : parties lues l'une après l'autre, bout à bout."""
        if not outils.lien_video_valide(sid, exp, sig):
            raise HTTPException(status_code=403, detail="Lien expiré ou invalide")
        s = await db.controle_distance_sessions.find_one({"id": sid}, {"_id": 0, "video_parties": 1})
        parties = sorted(int(i) for i in (s or {}).get("video_parties") or [])
        if not parties:
            raise HTTPException(status_code=404, detail="Aucune vidéo")

        async def flux():
            for i in parties:
                try:
                    yield await stockage.lire(outils.chemin_partie_video(sid, i))
                except Exception:  # noqa: BLE001 — partie manquante : on passe à la suivante
                    continue
        return StreamingResponse(flux(), media_type="video/webm")

    # --- Lot 135 : historique des prises en main d'un client (fiche client, item 9) ------------------------------------
    @router.get("/controle-distance/clients/{client_id}/sessions")
    async def sessions_du_client(client_id: str, user: Dict[str, Any] = Depends(_technicien)):
        curseur = db.controle_distance_sessions.find(
            {"client_id": client_id}, {"_id": 0, "jeton_poste_hash": 0, "jeton_tech_hash": 0}).sort("cree_le", -1).limit(200)
        return {"sessions": [x async for x in curseur]}

    # --- Journal des sessions --------------------------------------------------------------------------------------
    @router.get("/controle-distance/journal")
    async def journal(limite: int = 100, poste_id: Optional[str] = None, user: Dict[str, Any] = Depends(_technicien)):
        filtre = {"poste_id": poste_id} if poste_id else {}   # lot 135 : historique d'un poste (onglet de la visionneuse)
        curseur = db.controle_distance_sessions.find(
            filtre, {"_id": 0, "jeton_poste_hash": 0, "jeton_tech_hash": 0}).sort("cree_le", -1).limit(max(1, min(limite, 500)))
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
            # Lot 135 : ticket du client ouvert au début de la prise en main (jamais bloquant)
            try:
                await _ouvrir_ticket(await db.controle_distance_sessions.find_one({"id": sid}, {"_id": 0}) or session)
            except Exception:  # noqa: BLE001
                logger.exception("[controle_distance] ticket de la session %s non créé", sid)
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
                    # Images et fichiers du poste vers le technicien ; fichiers du technicien vers le poste (lot 135),
                    # seulement en mode « contrôler » ; taille bornée
                    if trame_binaire_autorisee(role, mode, donnees_bin):
                        await relais.envoyer_binaire(sid, "technicien" if role == "poste" else "poste", donnees_bin)
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
                    # Lot 135 : identifiant Windows mémorisé — envoyé au poste PAR LE SERVEUR (jamais par le navigateur)
                    if message.get("type") in COMMANDES_SERVEUR:
                        if mode != "controler":
                            await websocket.send_json({"type": "refuse", "detail": "Mode « voir seulement » : "
                                                                                  "commande non transmise"})
                            continue
                        erreur = await _injecter_identifiants(sid, session, "demandée par le technicien")
                        await websocket.send_json({"type": "refuse", "detail": erreur} if erreur
                                                  else {"type": "info", "detail": "Identifiant Windows saisi sur le poste"})
                        continue
                    if commande_autorisee(mode, message):
                        await relais.envoyer_json(sid, "poste", message)
                        action = action_journal(message)   # lot 135 : actions sensibles gardées dans le journal
                        if action:
                            await _noter_action(sid, action)
                    else:
                        await websocket.send_json({"type": "refuse", "detail": "Mode « voir seulement » : "
                                                                              "commande non transmise"})
                elif message_poste_autorise(message):
                    await relais.envoyer_json(sid, "technicien", message)
                    # Lot 135 : écran de connexion ou verrouillé signalé par le poste → saisie automatique de l'identifiant
                    # Windows mémorisé (une fois par session, mode « contrôler », option « saisie automatique »)
                    # (agent du service Windows seulement : l'icône de l'utilisateur ne peut pas écrire sur cet écran)
                    if (message.get("type") == "bureau" and message.get("securise") and mode == "controler"
                            and session.get("agent_service") and sid not in _identifiants_saisis):
                        poste = await db.support_loois_postes.find_one({"id": session.get("poste_id")}, {"_id": 0}) or {}
                        doc = await db.controle_distance_identifiants.find_one({"id": _id_machine(poste)}, {"_id": 0})
                        if doc and doc.get("saisie_auto", True) and doc.get("mdp_chiffre"):
                            _identifiants_saisis.add(sid)
                            if not await _injecter_identifiants(sid, session, "saisie automatique"):
                                await relais.envoyer_json(sid, "technicien", {
                                    "type": "info", "detail": "Identifiant Windows mémorisé saisi automatiquement"})
        except WebSocketDisconnect:
            motif = f"déconnexion du {role}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("[controle_distance] relais %s interrompu : %s", sid, exc)
        finally:
            relais.debrancher(sid, role)
            await _terminer(sid, motif)

    return router
