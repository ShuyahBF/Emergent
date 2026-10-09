# support_plateformes.py — Lot 90 : SUPPORT SAWALI DANS LES PLATEFORMES WEB (sTer, bfmobility, adLyn, beAuthentik…).
#
# Demande du propriétaire (09/10/2026) : « déployer cette requête au support dans toutes les autres plateformes WEB
# enregistrées sur SAWALI : un petit pictogramme d'assistance dans la barre latérale du portail (sTer, bfmobility),
# dans chaque boutique (adLyn) ou espace membre (beAuthentik). La fenêtre de chat du support SAWALI précise dans sa
# liste déroulante par exemple « sTer - Support ». Pendant une conversation le support doit savoir qu'il y a d'autres
# requêtes en attente. »
#
# En résumé (pour un développeur WinDev) :
#   - une plateforme = une fiche de liluvine_emetteurs (code « ster », nom « sTer », clé HMAC). Le support s'y ACTIVE
#     plateforme par plateforme (champ support_actif, rubrique des Paramètres « 🛟 Support des plateformes web ») ;
#   - le NAVIGATEUR de l'utilisateur ne parle jamais à SAWALI : il parle au serveur de SA plateforme, qui relaie
#     vers SAWALI avec une requête SIGNÉE (en-têtes X-Emetteur, X-Timestamp, X-Signature = HMAC-SHA256 de
#     « <ts>.<corps> » avec la clé de l'émetteur — la même que pour les contrats et la transmission WhatsApp) ;
#       POST /api/support-plateforme/messages  {utilisateur:{id, nom, role, contexte}, texte}  → message envoyé ;
#       POST /api/support-plateforme/fil       {utilisateur:{id}, depuis}                    → réponses du support ;
#     Lot 93 (pictogrammes de la fenêtre de chat, comme dans SAWALI : image, trombone, note vocale) :
#       POST /api/support-plateforme/fichier     {utilisateur, fichier (base64), nom, legende} → photo / document / vidéo ;
#       POST /api/support-plateforme/transcrire  {utilisateur, audio (base64), nom}            → texte de la note vocale ;
#       POST /api/support-plateforme/media       {utilisateur, message_id}                     → fichier d'un message du fil ;
#   - dans SAWALI, chaque plateforme est un ESPACE du chat interne : identifiant « support-plat-<code> », libellé
#     « <nom> - Support » (ex. « sTer - Support »), visible par l'équipe du support (administrateurs + comptes de
#     LOOIS_SUPPORT_ADMIN_EMAIL, comme le Support Loois). Un fil par utilisateur de la plateforme (« demandeur ») ;
#   - REQUÊTE : le premier message d'un utilisateur sans requête en cours ouvre une requête numérotée
#     (SUP-STER-2026-0001) « en attente » ; la première réponse du support la passe « en cours » ; « Terminer » la clôt
#     (ou 12 h sans message). GET /api/support/en-attente regroupe les demandes en attente de TOUS les espaces
#     (Support Loois compris) : le chat l'affiche pendant une conversation.
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import tempfile
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import Request  # au niveau du module : l'annotation de la route doit être résolue (from __future__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
PREFIXE_ESPACE = "support-plat-"        # identifiant d'espace : « support-plat-ster »
PREFIXE_DEMANDEUR = "plat-"              # identifiant d'un utilisateur de plateforme : « plat-ster-1a2b… »
MAX_TEXTE = 2000
MAX_FIL = 200                            # messages renvoyés au plus par lecture du fil
MO = 1024 * 1024
MAX_FICHIER_PLATEFORME = 15 * MO         # lot 93 : fichier relayé par une plateforme (JSON base64)
MAX_AUDIO = 25 * MO                      # lot 93 : note vocale (limite de Whisper)
INACTIVITE_CLOTURE = timedelta(hours=12) # requête close d'elle-même après 12 h sans message
STATUTS_EN_COURS = ("attente", "active")
LIBELLES_STATUT = {"attente": "En attente", "active": "En cours", "terminee": "Terminée"}

log = logging.getLogger("sawali.support_plateformes")


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def nettoyer(texte: Any, longueur: int) -> str:
    """Texte sur une ligne, sans caractères de contrôle, coupé à `longueur`."""
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(texte or "")).strip()
    return t[:longueur]


# ---------------------------------------------------------------------------
# Espaces (une plateforme = un espace du chat interne)
# ---------------------------------------------------------------------------
def decoder_base64(valeur: Any) -> tuple:
    """Lot 93 — « data:<type>;base64,<…> » ou base64 seul → (octets, type annoncé). ValueError si illisible."""
    texte = str(valeur or "").strip()
    annonce = ""
    if texte.startswith("data:"):
        entete, _, texte = texte.partition(",")
        annonce = entete[5:].split(";")[0].strip().lower()
    try:
        return base64.b64decode(texte, validate=True), annonce
    except (binascii.Error, ValueError):
        raise ValueError("Fichier illisible (base64 attendu)")


def vue_media(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Lot 93 — pièce jointe d'un message telle que la plateforme la montre (jamais le chemin de stockage)."""
    if not m.get("media_url"):
        return None
    return {"id": m["id"], "type": m.get("media_mime") or "application/octet-stream",
            "genre": m.get("media_kind") or "image", "nom": m.get("file_name") or "", "taille": m.get("media_size") or 0}


def espace_id(code: str) -> str:
    return f"{PREFIXE_ESPACE}{code}"


def est_espace(client_id: Optional[str]) -> bool:
    return str(client_id or "").startswith(PREFIXE_ESPACE)


def code_de_l_espace(client_id: str) -> str:
    return client_id[len(PREFIXE_ESPACE):]


def libelle_espace(emetteur: Dict[str, Any]) -> str:
    """« sTer - Support » (nom de l'émetteur, sinon son code)."""
    return f"{emetteur.get('nom') or emetteur.get('code')} - Support"


async def espaces(db) -> List[Dict[str, Any]]:
    """Espaces des plateformes dont le support est activé, au format de /me/chat/clients."""
    out = []
    async for e in db.liluvine_emetteurs.find({"support_actif": True, "actif": {"$ne": False}},
                                              {"_id": 0, "code": 1, "nom": 1}).sort("nom", 1):
        nom = libelle_espace(e)
        out.append({"id": espace_id(e["code"]), "full_name": nom, "company": nom, "plateforme": e["code"]})
    return out


async def espace_actif(db, client_id: str) -> bool:
    e = await db.liluvine_emetteurs.find_one({"code": code_de_l_espace(client_id), "support_actif": True,
                                              "actif": {"$ne": False}}, {"_id": 1})
    return bool(e)


# ---------------------------------------------------------------------------
# Demandeurs (utilisateurs des plateformes)
# ---------------------------------------------------------------------------
def demandeur_id(code: str, utilisateur_id: str) -> str:
    """Identifiant stable d'un utilisateur de plateforme (l'identifiant d'origine n'est pas exposé tel quel)."""
    return f"{PREFIXE_DEMANDEUR}{code}-{hashlib.sha1(f'{code}|{utilisateur_id}'.encode()).hexdigest()[:16]}"


def nom_affiche(nom: str, contexte: str, role: str) -> str:
    """« Awa Traoré — Boutique Lyna (gérant) » : ce que voit l'agent du support."""
    nom = nom or "Utilisateur"
    if contexte:
        nom += f" — {contexte}"
    if role:
        nom += f" ({role})"
    return nom


def nettoyer_utilisateur(u: Any) -> Dict[str, str]:
    """Identité envoyée par la plateforme : identifiant obligatoire, le reste facultatif et coupé."""
    if not isinstance(u, dict):
        raise ValueError("utilisateur attendu")
    uid = nettoyer(u.get("id"), 120)
    if not uid:
        raise ValueError("identifiant de l'utilisateur manquant")
    return {"id": uid, "nom": nettoyer(u.get("nom"), 80), "role": nettoyer(u.get("role"), 40),
            "contexte": nettoyer(u.get("contexte"), 80), "email": nettoyer(u.get("email"), 120),
            "telephone": nettoyer(u.get("telephone"), 30)}


async def enregistrer_demandeur(db, code: str, u: Dict[str, str]) -> Dict[str, Any]:
    """Crée ou met à jour la fiche du demandeur (nom, rôle, contexte peuvent changer)."""
    did = demandeur_id(code, u["id"])
    maintenant = _maintenant().isoformat()
    champs = {"id": did, "plateforme": code, "utilisateur_id": u["id"], "dernier_contact": maintenant,
              "nom": nom_affiche(u["nom"], u["contexte"], u["role"])}
    for k in ("role", "contexte", "email", "telephone"):
        if u.get(k):
            champs[k] = u[k]
    await db.support_plateformes_demandeurs.update_one(
        {"id": did}, {"$set": champs, "$setOnInsert": {"premier_contact": maintenant}}, upsert=True)
    return champs


async def ids_demandeurs(db, client_id: str) -> List[str]:
    code = code_de_l_espace(client_id)
    return [d["id"] async for d in db.support_plateformes_demandeurs.find({"plateforme": code}, {"_id": 0, "id": 1})]


async def nom_du_demandeur(db, uid: str) -> Optional[str]:
    """Nom affiché d'un demandeur, None si ce n'est pas un utilisateur de plateforme."""
    if not uid.startswith(PREFIXE_DEMANDEUR):
        return None
    d = await db.support_plateformes_demandeurs.find_one({"id": uid}, {"_id": 0, "nom": 1})
    return (d or {}).get("nom")


async def membres(db, client_id: str, est_en_ligne: Callable[[str], bool]) -> List[Dict[str, Any]]:
    """Demandeurs au format de /me/chat/{client}/members."""
    code = code_de_l_espace(client_id)
    return [{"id": d["id"], "name": d.get("nom") or d["id"], "email": None, "role": "utilisateur_plateforme",
             "online": False, "is_self": False}
            async for d in db.support_plateformes_demandeurs.find({"plateforme": code}, {"_id": 0})]


def requete_fil(client_id: str, did: str) -> Dict[str, Any]:
    """Tous les messages du fil d'un demandeur, quel que soit l'agent qui a répondu."""
    return {"client_id": client_id, "$or": [{"sender_id": did}, {"recipient_id": did}]}


def requete_non_lus(client_id: str, uid: str) -> Dict[str, Any]:
    """Messages des demandeurs pas encore lus par cet agent."""
    return {"client_id": client_id, "sender_id": {"$regex": f"^{PREFIXE_DEMANDEUR}"}, "read_by": {"$nin": [uid]}}


# ---------------------------------------------------------------------------
# Requêtes (attente → en cours → terminée)
# ---------------------------------------------------------------------------
async def requete_en_cours(db, did: str) -> Optional[Dict[str, Any]]:
    """Requête en cours du demandeur ; close d'elle-même après 12 h sans message."""
    r = await db.support_plateformes_requetes.find_one({"demandeur_id": did, "statut": {"$in": list(STATUTS_EN_COURS)}},
                                                        {"_id": 0}, sort=[("ouverte_le", -1)])
    if r and (r.get("dernier_message_le") or r["ouverte_le"]) < (_maintenant() - INACTIVITE_CLOTURE).isoformat():
        await db.support_plateformes_requetes.update_one({"id": r["id"]}, {"$set": {
            "statut": "terminee", "terminee_le": _maintenant().isoformat(), "terminee_par": "inactivite"}})
        return None
    return r


async def numero_suivant(db, code: str) -> str:
    """SUP-STER-2026-0001 : compteur par plateforme et par année."""
    annee = _maintenant().year
    from pymongo import ReturnDocument
    c = await db.counters.find_one_and_update({"id": f"support_plat_{code}_{annee}"}, {"$inc": {"valeur": 1}},
                                             upsert=True, return_document=ReturnDocument.AFTER)
    return f"SUP-{code.upper()}-{annee}-{int((c or {}).get('valeur') or 1):04d}"


async def ouvrir_ou_reprendre(db, code: str, did: str, nom: str) -> Dict[str, Any]:
    """Requête en cours du demandeur, ou nouvelle requête « en attente »."""
    r = await requete_en_cours(db, did)
    if r:
        return r
    maintenant = _maintenant().isoformat()
    r = {"id": str(uuid.uuid4()), "numero": await numero_suivant(db, code), "plateforme": code, "demandeur_id": did,
         "demandeur_nom": nom, "statut": "attente", "ouverte_le": maintenant, "dernier_message_le": maintenant,
         "prise_par": None, "prise_le": None, "terminee_le": None}
    await db.support_plateformes_requetes.insert_one(r.copy())
    return r


async def apres_message_agent(db, user: Dict[str, Any], client_id: str, destinataire: Optional[str]) -> Optional[Dict[str, Any]]:
    """Réponse d'un agent : la requête du demandeur passe « en cours » (ouverte au besoin : message à l'initiative
    du support). Appelée par internal_chat après chaque envoi ; jamais bloquante."""
    if not est_espace(client_id) or not destinataire or not destinataire.startswith(PREFIXE_DEMANDEUR):
        return None
    try:
        code = code_de_l_espace(client_id)
        d = await db.support_plateformes_demandeurs.find_one({"id": destinataire}, {"_id": 0, "nom": 1})
        r = await ouvrir_ou_reprendre(db, code, destinataire, (d or {}).get("nom") or destinataire)
        maintenant = _maintenant().isoformat()
        maj = {"dernier_message_le": maintenant}
        if r["statut"] == "attente":
            maj.update(statut="active", prise_par=user.get("full_name") or user.get("email"), prise_le=maintenant)
        await db.support_plateformes_requetes.update_one({"id": r["id"]}, {"$set": maj})
        return {**r, **maj}
    except Exception:  # noqa: BLE001
        return None


async def fils(db, client_id: str, uid: str) -> List[Dict[str, Any]]:
    """Un fil par demandeur ayant écrit (ou reçu) un message, avec l'état de sa requête et ses non-lus."""
    code = code_de_l_espace(client_id)
    out: List[Dict[str, Any]] = []
    async for d in db.support_plateformes_demandeurs.find({"plateforme": code}, {"_id": 0}):
        dernier = await db.internal_chat_messages.find_one(requete_fil(client_id, d["id"]), {"_id": 0},
                                                           sort=[("created_at", -1)])
        if not dernier:
            continue
        non_lus = await db.internal_chat_messages.count_documents(
            {"client_id": client_id, "sender_id": d["id"], "read_by": {"$nin": [uid]}})
        r = await requete_en_cours(db, d["id"])
        label = d.get("nom") or d["id"]
        if r:
            label = f"{'⏳' if r['statut'] == 'attente' else '💬'} {label}"
        out.append({"kind": "dm", "key": d["id"], "label": label, "unread": int(non_lus), "last_message": dernier,
                    "requete": r})
    # en attente d'abord, puis les plus récents
    attente = [f for f in out if f["requete"] and f["requete"]["statut"] == "attente"]
    autres = sorted([f for f in out if f not in attente],
                    key=lambda f: (f["last_message"] or {}).get("created_at") or "", reverse=True)
    return sorted(attente, key=lambda f: f["requete"]["ouverte_le"]) + autres


async def en_attente(db) -> List[Dict[str, Any]]:
    """Requêtes en attente de TOUS les espaces : plateformes web + Support Loois (indicateur du chat)."""
    noms = {e["code"]: libelle_espace(e) async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "code": 1, "nom": 1})}
    out: List[Dict[str, Any]] = []
    async for r in db.support_plateformes_requetes.find({"statut": "attente"}, {"_id": 0}).sort("ouverte_le", 1):
        if await requete_en_cours(db, r["demandeur_id"]) is None:
            continue   # close entre-temps (inactivité)
        out.append({"espace": espace_id(r["plateforme"]), "espace_nom": noms.get(r["plateforme"], r["plateforme"]),
                    "fil": r["demandeur_id"], "nom": r.get("demandeur_nom") or r["demandeur_id"],
                    "numero": r["numero"], "depuis": r["ouverte_le"]})
    try:
        from routes import support_loois
        async for s in db.support_loois_sessions.find({"statut": "attente", "en_cours": True}, {"_id": 0}):
            out.append({"espace": support_loois.ESPACE_ID, "espace_nom": support_loois.ESPACE_NOM,
                        "fil": s.get("poste_id"), "nom": s.get("poste_nom") or s.get("poste_id"),
                        "numero": s.get("ticket_number") or "", "depuis": s.get("demande_le") or ""})
    except Exception:  # noqa: BLE001 — Support Loois indisponible : seules les plateformes sont listées
        pass
    out.sort(key=lambda x: x["depuis"] or "")
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def installer(*, router, db, manager, now_iso: Callable[[], str], get_current_user) -> None:
    """Routes signées des plateformes + routes de l'équipe du support (ajoutées au routeur du chat interne :
    même gestionnaire de connexions, un message d'utilisateur est poussé en direct à l'équipe)."""
    from fastapi import Depends, HTTPException
    from routes import support_loois
    from routes.contrats_plateformes import signature_valide
    from routes import avis_claude  # lot 91 : avis de Claude sur les demandes de fonctionnalités

    async def equipe(user: dict = Depends(get_current_user)) -> dict:
        """Équipe du support : administrateurs + comptes de LOOIS_SUPPORT_ADMIN_EMAIL."""
        if user.get("role") != "admin" and not support_loois.est_compte_support(user):
            raise HTTPException(status_code=403, detail="Réservé à l'équipe du support")
        return user

    async def plateforme_signee(request: Request) -> tuple:
        """Émetteur actif, support activé, signature valable → (émetteur, corps JSON)."""
        code = (request.headers.get("X-Emetteur") or "").strip().lower()
        emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0}) if code else None
        if not emetteur or not emetteur.get("actif", True):
            raise HTTPException(status_code=401, detail="Émetteur inconnu ou désactivé")
        brut = await request.body()
        if not signature_valide(emetteur.get("secret") or "", request.headers.get("X-Timestamp") or "", brut,
                                request.headers.get("X-Signature") or "", _maintenant()):
            raise HTTPException(status_code=401, detail="Signature refusée")
        if not emetteur.get("support_actif"):
            raise HTTPException(status_code=403, detail="Support SAWALI non activé pour cette plateforme")
        try:
            corps = json.loads(brut.decode("utf-8") or "{}")
        except ValueError:
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        if not isinstance(corps, dict):
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        return emetteur, corps

    async def diffuser_equipe(trame: Dict[str, Any]) -> None:
        for cible in await support_loois.ids_admins(db):
            try:
                await manager.send_to_user(cible, trame)
            except Exception:  # noqa: BLE001
                pass

    def vue_requete(r: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Ce que la plateforme montre à son utilisateur (jamais les autres requêtes)."""
        if not r:
            return None
        return {"numero": r["numero"], "statut": r["statut"], "libelle": LIBELLES_STATUT.get(r["statut"], r["statut"]),
                "ouverte_le": r["ouverte_le"], "prise_par": r.get("prise_par")}

    async def avis_pour_plateforme(emetteur: Dict[str, Any], d: Dict[str, Any], texte: str) -> None:
        """Lot 91 — avis de Claude sur une demande d'ajout / de correction de fonctionnalité de la plateforme."""
        try:
            code = emetteur["code"]
            await avis_claude.traiter(db, source="plateforme", espace=espace_id(code), fil=d["id"], plateforme=code,
                                      plateforme_nom=emetteur.get("nom") or code, demandeur_nom=d["nom"], texte=texte)
        except Exception:  # noqa: BLE001
            log.warning("[support_plateformes] avis Claude impossible", exc_info=True)

    @router.post("/support-plateforme/messages", tags=["Support des plateformes"])
    async def message_utilisateur(request: Request):
        """Message d'un utilisateur de la plateforme vers le support SAWALI (requête signée)."""
        emetteur, corps = await plateforme_signee(request)
        try:
            u = nettoyer_utilisateur(corps.get("utilisateur"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        texte = str(corps.get("texte") or "").strip()[:MAX_TEXTE]
        if not texte:
            raise HTTPException(status_code=422, detail="Message vide")
        code = emetteur["code"]
        d = await enregistrer_demandeur(db, code, u)
        r = await ouvrir_ou_reprendre(db, code, d["id"], d["nom"])
        await db.support_plateformes_requetes.update_one({"id": r["id"]}, {"$set": {
            "dernier_message_le": _maintenant().isoformat(), "demandeur_nom": d["nom"]}})
        doc = {"id": str(uuid.uuid4()), "client_id": espace_id(code), "sender_id": d["id"], "sender_name": d["nom"],
               "recipient_id": None, "text": texte, "created_at": now_iso(), "read_by": [d["id"]],
               "requete_numero": r["numero"]}
        await db.internal_chat_messages.insert_one(doc.copy())
        doc.pop("_id", None)
        await diffuser_equipe({"type": "message", "client_id": espace_id(code), "message": doc})
        if r["statut"] == "attente":
            await diffuser_equipe({"type": "support_plateforme_requete", "client_id": espace_id(code),
                                   "requete": {**r, "espace_nom": libelle_espace(emetteur)}})
        # Lot 91 — demande de fonctionnalité : Liluvine la transmet à Claude (tâche de fond, jamais bloquante)
        avis_claude.lancer(avis_pour_plateforme(emetteur, d, texte))
        return {"ok": True, "message": {"id": doc["id"], "texte": texte, "le": doc["created_at"], "de": "moi"},
                "requete": vue_requete(r)}

    @router.post("/support-plateforme/fil", tags=["Support des plateformes"])
    async def fil_utilisateur(request: Request):
        """Fil de l'utilisateur (ses messages et les réponses du support) depuis une date ; réponses marquées lues."""
        emetteur, corps = await plateforme_signee(request)
        try:
            u = nettoyer_utilisateur(corps.get("utilisateur"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        code = emetteur["code"]
        did = demandeur_id(code, u["id"])
        q = requete_fil(espace_id(code), did)
        depuis = nettoyer(corps.get("depuis"), 40)
        if depuis:
            q = {**q, "created_at": {"$gt": depuis}}
        lignes = [m async for m in db.internal_chat_messages.find(q, {"_id": 0}).sort("created_at", -1).limit(MAX_FIL)]
        lignes.reverse()
        non_lus = await db.internal_chat_messages.count_documents(
            {"client_id": espace_id(code), "recipient_id": did, "read_by": {"$nin": [did]}})
        if corps.get("marquer_lu", True):
            await db.internal_chat_messages.update_many(
                {"client_id": espace_id(code), "recipient_id": did, "read_by": {"$nin": [did]}},
                {"$addToSet": {"read_by": did}})
        messages = [{"id": m["id"], "texte": m.get("text") or "", "le": m["created_at"],
                     "de": "moi" if m.get("sender_id") == did else "support",
                     "auteur": None if m.get("sender_id") == did else (m.get("sender_name") or "Support SAWALI"),
                     "systeme": bool(m.get("systeme")),
                     "media": vue_media(m)} for m in lignes]   # lot 93 : photo, document, vidéo
        r = await requete_en_cours(db, did)
        return {"messages": messages, "non_lus": int(non_lus), "requete": vue_requete(r),
                "plateforme": libelle_espace(emetteur)}

    # ------------------------------------------------------------------------------------------------------------
    # Lot 93 — pictogrammes de la fenêtre de chat des plateformes : image, trombone (document / vidéo), note vocale
    # ------------------------------------------------------------------------------------------------------------
    @router.post("/support-plateforme/fichier", tags=["Support des plateformes"])
    async def fichier_utilisateur(request: Request):
        """Photo, document ou vidéo d'un utilisateur de la plateforme vers le support (requête signée)."""
        emetteur, corps = await plateforme_signee(request)
        try:
            u = nettoyer_utilisateur(corps.get("utilisateur"))
            data, annonce = decoder_base64(corps.get("fichier"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if not data:
            raise HTTPException(status_code=422, detail="Fichier vide")
        nature = support_loois.type_fichier(corps.get("type") or annonce, corps.get("nom"))
        if not nature:
            raise HTTPException(status_code=415, detail="Type de fichier non accepté : images, vidéos MP4/WebM, "
                                                        "PDF, Word, Excel, PowerPoint, texte ou CSV.")
        mime, extension, genre, maximum = nature
        if len(data) > min(maximum, MAX_FICHIER_PLATEFORME):
            raise HTTPException(status_code=413, detail=f"Fichier trop volumineux ({min(maximum, MAX_FICHIER_PLATEFORME) // MO} Mo au plus)")
        code = emetteur["code"]
        d = await enregistrer_demandeur(db, code, u)
        r = await ouvrir_ou_reprendre(db, code, d["id"], d["nom"])
        msg_id = str(uuid.uuid4())
        try:
            from storage import aupload_bytes, astorage_available
            if not await astorage_available():
                raise HTTPException(status_code=503, detail="Stockage indisponible — réessayez plus tard")
            chemin = await aupload_bytes(f"chat/{espace_id(code)}/{msg_id}{extension}", data, mime)
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            log.exception("[support_plateformes] envoi du fichier impossible")
            raise HTTPException(status_code=502, detail="Envoi du fichier impossible")
        legende = nettoyer(corps.get("legende"), 500)
        doc = {"id": msg_id, "client_id": espace_id(code), "sender_id": d["id"], "sender_name": d["nom"],
               "recipient_id": None, "text": legende, "created_at": now_iso(), "read_by": [d["id"]],
               "requete_numero": r["numero"], "media_url": f"/api/me/chat/media/{msg_id}", "media_mime": mime,
               "media_size": len(data), "media_kind": genre, "storage_path": chemin,
               "file_name": support_loois.nom_fichier_propre(corps.get("nom"), extension)}
        await db.internal_chat_messages.insert_one(doc.copy())
        doc.pop("_id", None)
        await db.support_plateformes_requetes.update_one({"id": r["id"]}, {"$set": {
            "dernier_message_le": _maintenant().isoformat(), "demandeur_nom": d["nom"]}})
        await diffuser_equipe({"type": "message", "client_id": espace_id(code), "message": doc})
        if r["statut"] == "attente":
            await diffuser_equipe({"type": "support_plateforme_requete", "client_id": espace_id(code),
                                   "requete": {**r, "espace_nom": libelle_espace(emetteur)}})
        return {"ok": True, "message": {"id": msg_id, "texte": legende, "le": doc["created_at"], "de": "moi",
                                        "media": vue_media(doc)}, "requete": vue_requete(r)}

    @router.post("/support-plateforme/transcrire", tags=["Support des plateformes"])
    async def transcrire_utilisateur(request: Request):
        """Note vocale → texte (Whisper), placé dans la zone de saisie de l'utilisateur avant l'envoi."""
        _emetteur, corps = await plateforme_signee(request)
        try:
            nettoyer_utilisateur(corps.get("utilisateur"))
            data, _annonce = decoder_base64(corps.get("audio"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if not data:
            raise HTTPException(status_code=422, detail="Note vocale vide")
        if len(data) > MAX_AUDIO:
            raise HTTPException(status_code=413, detail="Note vocale trop longue (25 Mo au plus)")
        ext = os.path.splitext(str(corps.get("nom") or ""))[1].lower()
        if ext not in {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg"}:
            ext = ".webm"   # MediaRecorder des navigateurs : webm par défaut
        chemin = None
        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(data)
                chemin = f.name
            from ia_client import OpenAISpeechToText, cle_ia
            stt = OpenAISpeechToText(api_key=cle_ia("openai"))
            with open(chemin, "rb") as fh:
                resp = await stt.transcribe(file=fh, model="whisper-1", response_format="json",
                                            language=str(corps.get("langue") or "fr")[:5])
            return {"ok": True, "texte": (getattr(resp, "text", None) or "").strip()}
        except Exception:  # noqa: BLE001
            log.exception("[support_plateformes] transcription impossible")
            raise HTTPException(status_code=502, detail="Transcription impossible pour le moment")
        finally:
            if chemin and os.path.exists(chemin):
                try:
                    os.unlink(chemin)
                except OSError:
                    pass

    @router.post("/support-plateforme/media", tags=["Support des plateformes"])
    async def media_utilisateur(request: Request):
        """Fichier d'un message du fil de l'utilisateur (le sien ou une réponse du support), en base64."""
        emetteur, corps = await plateforme_signee(request)
        try:
            u = nettoyer_utilisateur(corps.get("utilisateur"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        did = demandeur_id(emetteur["code"], u["id"])
        m = await db.internal_chat_messages.find_one(
            {"id": nettoyer(corps.get("message_id"), 80), "client_id": espace_id(emetteur["code"]),
             "$or": [{"sender_id": did}, {"recipient_id": did}]}, {"_id": 0})
        if not m or not m.get("storage_path"):
            raise HTTPException(status_code=404, detail="Fichier introuvable")
        try:
            from storage import afetch_bytes
            data, ct = await afetch_bytes(m["storage_path"])
        except Exception:  # noqa: BLE001
            log.exception("[support_plateformes] lecture du fichier impossible")
            raise HTTPException(status_code=502, detail="Fichier indisponible")
        return {"type": ct or m.get("media_mime") or "application/octet-stream", "nom": m.get("file_name") or "",
                "contenu": base64.b64encode(data).decode("ascii")}

    @router.get("/support/en-attente", tags=["Support des plateformes"])
    async def demandes_en_attente(user: dict = Depends(equipe)):
        """Indicateur du chat : requêtes en attente de tous les espaces (plateformes + Support Loois)."""
        liste = await en_attente(db)
        return {"total": len(liste), "elements": liste}

    @router.get("/support-plateformes/{code}/fils/{did}/requete", tags=["Support des plateformes"])
    async def requete_du_fil(code: str, did: str, user: dict = Depends(equipe)):
        """Bandeau du fil ouvert : requête en cours (ou dernière) du demandeur et sa fiche."""
        r = await requete_en_cours(db, did) or await db.support_plateformes_requetes.find_one(
            {"demandeur_id": did}, {"_id": 0}, sort=[("ouverte_le", -1)])
        d = await db.support_plateformes_demandeurs.find_one({"id": did, "plateforme": code}, {"_id": 0})
        if not d:
            raise HTTPException(status_code=404, detail="Utilisateur inconnu")
        return {"requete": r, "demandeur": d}

    @router.post("/support-plateformes/{code}/fils/{did}/terminer", tags=["Support des plateformes"])
    async def terminer(code: str, did: str, user: dict = Depends(equipe)):
        """Clôt la requête en cours du demandeur (message système dans son fil)."""
        r = await requete_en_cours(db, did)
        if not r or r["plateforme"] != code:
            raise HTTPException(status_code=404, detail="Aucune requête en cours")
        maintenant = _maintenant().isoformat()
        await db.support_plateformes_requetes.update_one({"id": r["id"]}, {"$set": {
            "statut": "terminee", "terminee_le": maintenant,
            "terminee_par": user.get("full_name") or user.get("email")}})
        doc = {"id": str(uuid.uuid4()), "client_id": espace_id(code), "sender_id": user["id"],
               "sender_name": "Support SAWALI", "recipient_id": did, "systeme": True,
               "text": f"✅ Requête {r['numero']} terminée. Écrivez à nouveau si besoin : une nouvelle requête s'ouvrira.",
               "created_at": now_iso(), "read_by": [user["id"]]}
        await db.internal_chat_messages.insert_one(doc.copy())
        doc.pop("_id", None)
        await diffuser_equipe({"type": "message", "client_id": espace_id(code), "message": doc})
        return {"ok": True, "numero": r["numero"]}

    # ---------------- Réglage par plateforme (rubrique des Paramètres) ----------------
    @router.get("/admin/support-plateformes", tags=["Support des plateformes"])
    async def reglages(user: dict = Depends(equipe)):
        """Plateformes enregistrées, support activé ou non, requêtes en attente / en cours / du mois."""
        debut_mois = _maintenant().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        out = []
        async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "code": 1, "nom": 1, "actif": 1, "support_actif": 1}).sort("nom", 1):
            q = {"plateforme": e["code"]}
            out.append({"code": e["code"], "nom": e.get("nom") or e["code"], "libelle": libelle_espace(e),
                        "actif": e.get("actif", True), "support_actif": bool(e.get("support_actif")),
                        "attente": await db.support_plateformes_requetes.count_documents({**q, "statut": "attente"}),
                        "en_cours": await db.support_plateformes_requetes.count_documents({**q, "statut": "active"}),
                        "ce_mois": await db.support_plateformes_requetes.count_documents({**q, "ouverte_le": {"$gte": debut_mois}})})
        return {"plateformes": out}

    @router.put("/admin/support-plateformes/{code}", tags=["Support des plateformes"])
    async def activer(code: str, request: Request, user: dict = Depends(get_current_user)):
        """Active / désactive le support SAWALI d'une plateforme (administrateur)."""
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        res = await db.liluvine_emetteurs.update_one({"code": code}, {"$set": {
            "support_actif": bool((corps or {}).get("support_actif"))}})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="Plateforme inconnue")
        return {"ok": True, "code": code, "support_actif": bool((corps or {}).get("support_actif"))}
