# wa_memoire_qdrant.py — Lot 344 : « mémoire des conversations WhatsApp » dans Qdrant (recherche par similarité).
#
# Idée du propriétaire (29/10/2026) : utiliser l'espace Qdrant pour retrouver, par numéro ET par sujet, le contenu des
# échanges (messages, PDF, images — sauf les vocaux) afin que l'IA retrouve un fond de discussion ou de réponse.
# Les FICHIERS restent sur R2 : Qdrant ne garde que le TEXTE (+ le lien du fichier) et son vecteur de recherche.
#
# Ce qui est indexé (collection « wa_conversations », vecteurs 384 d., distance cosinus) :
#   - messages reçus des clients (texte, légendes, boutons) ;
#   - messages et pièces envoyés par un HUMAIN de SAWALI (sender_id) — jamais les réponses de l'IA (pas de boucle) ;
#   - contenu des PDF (texte extrait, découpé) ;
#   - contenu des images (texte lu + description, par la vision de Claude) — réglable, plafond quotidien ;
#   - JAMAIS : vocaux / audios, messages retenus par la barrière, réponses automatiques.
# Chaque point : numéro, client, sens, expéditeur, date, nature (texte / pdf / image), lien du fichier, extrait.
#
# Fonctionnement : un indexeur d'ARRIÈRE-PLAN (planificateur, toutes les minutes) lit les nouveaux messages depuis un
# curseur (document settings «wa_memoire», aucune nouvelle collection MongoDB), les découpe, calcule les vecteurs hors de la
# boucle principale et les envoie à Qdrant par lots. Identifiants de points déterministes → relancer ne crée jamais de doublon.
# Une panne de Qdrant n'avance pas le curseur : le lot est réessayé à la minute suivante. Jamais bloquant pour la réception.
#
# ENRICHISSEMENT DE LA BASE DE CONNAISSANCES (précision du propriétaire, 29/10/2026) : les collections Qdrant de SAWALI servent déjà de
# base de connaissances à Liluvine ; elle doit s'enrichir au fil des conversations. Chaque réponse d'un HUMAIN à une question d'un client
# devient une « question / réponse CANDIDATE » (nature « qr », statut « propose »), ANONYMISÉE (numéros, e-mails, noms retirés). Rien
# n'entre dans la base sans la VALIDATION du propriétaire (relecture, correction possible, choix de la collection) : une réponse humaine
# peut contenir une donnée de santé ou une erreur, et l'IA la répéterait à d'autres clients.
#
# CONFIDENTIALITÉ — ces échanges contiennent des données de santé / personnelles :
#   - fonction désactivée tant que le propriétaire ne l'active pas (Paramètres) ;
#   - recherche humaine réservée aux administrateurs et superviseurs ;
#   - l'IA ne reçoit QUE l'historique du MÊME numéro (même client) ; les réponses d'équipe d'autres numéros ne sont proposées
#     qu'avec le réglage séparé « wa_memoire_ia_reponses_equipe » (désactivé par défaut) ;
#   - la collection n'est jamais ajoutée à la base de connaissances générale de Liluvine.
# Réglages (settings global) : wa_memoire_active, wa_memoire_images (défaut oui), wa_memoire_ia (défaut oui),
#   wa_memoire_ia_reponses_equipe (défaut non), wa_memoire_images_par_jour (défaut 200).
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sawali.wa_memoire")

COLLECTION = "wa_conversations"
ETAT_ID = "wa_memoire"                 # document de la collection `settings` (curseur + compteurs)
TAILLE_LOT = 40                        # messages lus par passage
PDF_MAX_OCTETS = 15 * 1024 * 1024
IMAGE_MAX_OCTETS = 5 * 1024 * 1024
PDF_MAX_BLOCS = 40                     # un PDF géant n'occupe pas tout l'espace
_NS = uuid.UUID("5c0e3f3e-7a54-4f1e-9a52-1c6f2d9a0e44")   # espace de noms des identifiants de points


# ───────────────────────────── fonctions pures ─────────────────────────────

def reglages(s: Dict[str, Any]) -> Dict[str, Any]:
    """Réglages lus dans `settings` (fonction pure). La mémoire est DÉSACTIVÉE par défaut."""
    def _oui(cle: str, defaut: bool) -> bool:
        v = s.get(cle)
        return defaut if v is None else bool(v)
    try:
        plafond = max(0, int(s.get("wa_memoire_images_par_jour") if s.get("wa_memoire_images_par_jour") is not None else 200))
    except (TypeError, ValueError):
        plafond = 200
    return {
        "actif": _oui("wa_memoire_active", False),
        "images": _oui("wa_memoire_images", True),
        "ia": _oui("wa_memoire_ia", True),
        "ia_reponses_equipe": _oui("wa_memoire_ia_reponses_equipe", False),
        "images_par_jour": plafond,
    }


def nature_du_message(m: Dict[str, Any], images_actives: bool = True) -> Optional[str]:
    """Que faut-il indexer dans ce message ? « texte », « pdf », « image » ou None (à ignorer). Fonction pure.

    Ignorés : vocaux et audios ; réponses automatiques / de l'IA ; messages retenus par la barrière ; sortants sans
    expéditeur humain ; messages sans contenu."""
    if m.get("barriere_retenu") or m.get("auto_reply") or m.get("ai_generated"):
        return None
    sortant = m.get("direction") == "outbound"
    if sortant and not m.get("sender_id"):
        return None
    if m.get("direction") not in ("inbound", "outbound") or not (m.get("phone_digits") or "").strip():
        return None
    mime = (m.get("media_mime_type") or "").lower()
    genre = (m.get("media_kind") or m.get("message_type") or "").lower()
    if genre in ("audio", "voice", "ptt") or mime.startswith("audio/"):
        return None
    if mime == "application/pdf" and m.get("media_id"):
        return "pdf"
    if (genre == "image" or mime.startswith("image/")) and m.get("media_id"):
        return "image" if images_actives else ("texte" if (m.get("media_caption") or "").strip() else None)
    texte = (m.get("media_caption") or m.get("body") or "").strip()
    if not texte or re.fullmatch(r"\[[^\]]{1,40}\]", texte):      # « [image envoyé] » : marqueur, pas un contenu
        return None
    return "texte"


def identifiant_point(message_id: str, rang: int) -> str:
    """Identifiant déterministe d'un point : relancer l'indexation d'un message ne crée jamais de doublon."""
    return str(uuid.uuid5(_NS, f"{message_id}:{rang}"))


def blocs_de_message(m: Dict[str, Any], contenu_media: str = "") -> List[str]:
    """Textes à indexer pour ce message : légende / texte puis contenu du fichier, découpés (1 200 caractères)."""
    from routes.qdrant_rag import chunk_text
    morceaux: List[str] = []
    for t in ((m.get("media_caption") or ""), (m.get("body") or "")):
        t = (t or "").strip()
        if t and not re.fullmatch(r"\[[^\]]{1,40}\]", t) and t not in morceaux:
            morceaux.append(t)
    if (contenu_media or "").strip():
        morceaux.append(contenu_media.strip())
    blocs: List[str] = []
    for t in morceaux:
        blocs += chunk_text(t, max_chars=1200, overlap=150)
    return blocs[:PDF_MAX_BLOCS]


def filtre_qdrant(*, phone_digits: Optional[str] = None, client_id: Optional[str] = None,
                  direction: Optional[str] = None, nature: Optional[str] = None, sans_nature: Optional[str] = None,
                  statut: Optional[str] = None):
    """Filtre Qdrant (champs exacts). None si aucun critère. `sans_nature` exclut une nature (ex. « qr » : les questions /
    réponses candidates ne se mêlent pas aux messages d'origine dans les recherches)."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    conditions = []
    for champ, valeur in (("phone_digits", phone_digits), ("client_id", client_id), ("direction", direction),
                          ("nature", nature), ("statut", statut)):
        if valeur:
            conditions.append(FieldCondition(key=champ, match=MatchValue(value=str(valeur))))
    exclusions = [FieldCondition(key="nature", match=MatchValue(value=sans_nature))] if sans_nature else []
    return Filter(must=conditions or None, must_not=exclusions or None) if (conditions or exclusions) else None


_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_RE_NUMERO = re.compile(r"(?<!\w)\+?\d[\d .\-]{6,}\d(?!\w)")


def anonymiser(texte: str, noms: Tuple[str, ...] = ()) -> str:
    """Retire d'un texte les données qui identifient une personne : e-mails, numéros (7 chiffres et plus) et les noms connus de
    la conversation (contact, agent). Fonction pure. Ne remplace pas la relecture du propriétaire : c'est un premier filtre."""
    t = _RE_EMAIL.sub("[e-mail]", texte or "")
    t = _RE_NUMERO.sub("[numéro]", t)
    for nom in noms:
        for mot in re.split(r"\s+", (nom or "").strip()):
            if len(mot) >= 3 and mot.lower() not in ("monsieur", "madame", "docteur", "client", "equipe", "équipe"):
                t = re.sub(r"(?<!\w)" + re.escape(mot) + r"(?!\w)", "[nom]", t, flags=re.IGNORECASE)
    return t.strip()


def est_reponse_utile(question: str, reponse: str) -> bool:
    """Une réponse humaine mérite d'être proposée à la base si elle dit quelque chose : ni salutation, ni simple accusé."""
    q, r = (question or "").strip(), (reponse or "").strip()
    if len(q) < 12 or len(r) < 30:
        return False
    return not re.fullmatch(r"(?i)(ok|d'accord|merci|bien reçu|bonjour|bonsoir|c'est noté)[\s.!,]*", r)


# ───────────────────────────── accès Qdrant ─────────────────────────────

async def _etat(db) -> Dict[str, Any]:
    return await db.settings.find_one({"_id": ETAT_ID}) or {}


async def _preparer_collection(db):
    """Crée la collection (si besoin) SANS la marquer « enabled_for_liluvine » : elle ne doit jamais alimenter la base
    de connaissances générale (qui mélangerait les numéros). Index des champs de filtre en best-effort."""
    from routes.qdrant_rag import _EMBED_VECTOR_SIZE, _client_pret, _resolve_credentials
    from qdrant_client.models import Distance, VectorParams
    url, cle = await _resolve_credentials(db)
    client = await _client_pret(url, cle)
    if not await asyncio.to_thread(lambda: client.collection_exists(COLLECTION)):
        await asyncio.to_thread(lambda: client.create_collection(
            collection_name=COLLECTION, vectors_config=VectorParams(size=_EMBED_VECTOR_SIZE, distance=Distance.COSINE)))
        for champ in ("phone_digits", "client_id", "direction", "nature"):
            try:
                await asyncio.to_thread(lambda c=champ: client.create_payload_index(COLLECTION, c, field_schema="keyword"))
            except Exception:  # noqa: BLE001
                logger.info("[wa_memoire] index de champ %s non créé", champ)
    return client


async def _octets_du_fichier(db, file_id: str, limite: int) -> Optional[bytes]:
    """Contenu du fichier d'un message (R2 en priorité, puis disque local) ; None si absent ou trop gros."""
    fiche = await db.files.find_one({"id": file_id}, {"_id": 0, "storage_path": 1, "stored_name": 1, "size": 1})
    if not fiche or int(fiche.get("size") or 0) > limite:
        return None
    try:
        if fiche.get("storage_path"):
            from storage import afetch_bytes
            data, _ = await afetch_bytes(fiche["storage_path"])
            return data if len(data) <= limite else None
    except Exception:  # noqa: BLE001
        logger.info("[wa_memoire] fichier %s illisible sur R2", file_id)
    return None


async def _contenu_media(db, m: Dict[str, Any], nature: str, etat: Dict[str, Any], plafond_images: int) -> Tuple[str, bool]:
    """Texte lu dans le fichier (PDF ou image). Retourne (texte, image_analysee)."""
    from routes.qdrant_rag import describe_image_with_vision, extract_pdf_text
    if nature == "pdf":
        data = await _octets_du_fichier(db, m["media_id"], PDF_MAX_OCTETS)
        return (await asyncio.to_thread(extract_pdf_text, data) if data else ""), False
    if nature == "image":
        jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        deja = (etat.get("images_jour") or {}).get(jour, 0)
        if deja >= plafond_images:
            return "", False
        data = await _octets_du_fichier(db, m["media_id"], IMAGE_MAX_OCTETS)
        if not data:
            return "", False
        analyse = await describe_image_with_vision(data, m.get("media_mime_type") or "image/jpeg")
        return "\n".join(x for x in (analyse.get("ocr_text"), analyse.get("visual_summary")) if x), True
    return "", False


async def _candidat_qr(db, client, reponse_msg: Dict[str, Any], mid: str):
    """Question / réponse CANDIDATE : la réponse d'un humain + les derniers messages texte du client (24 h au plus avant). Anonymisée,
    statut « propose » (jamais publiée sans validation). None si la réponse n'apporte rien ou si une candidate très proche existe."""
    from routes.qdrant_rag import _embed_texts
    from qdrant_client.models import PointStruct
    fin = reponse_msg.get("created_at") or ""
    debut = (datetime.fromisoformat(fin.replace("Z", "+00:00")) - timedelta(hours=24)).isoformat() if fin else ""
    questions = await db.whatsapp_messages.find(
        {"direction": "inbound", "phone_digits": reponse_msg.get("phone_digits"), "created_at": {"$gte": debut, "$lt": fin},
         "message_type": {"$in": [None, "text", "button", "interactive"]}}, {"_id": 0, "body": 1, "created_at": 1},
    ).sort("created_at", -1).limit(3).to_list(3)
    question = " ".join(x["body"].strip() for x in reversed(questions) if (x.get("body") or "").strip())[:700]
    reponse = (reponse_msg.get("body") or "").strip()[:1500]
    if not est_reponse_utile(question, reponse):
        return None
    noms = (reponse_msg.get("contact_name") or "", reponse_msg.get("sender_label") or "")
    q, r = anonymiser(question, noms), anonymiser(reponse, noms)
    vecteur = (await asyncio.to_thread(_embed_texts, [q]))[0]
    try:   # doublon : une question / réponse presque identique (proposée, validée ou refusée) existe déjà
        proches = (await asyncio.to_thread(lambda: client.query_points(
            collection_name=COLLECTION, query=vecteur, query_filter=filtre_qdrant(nature="qr"), limit=1, with_payload=False))).points
        if proches and float(proches[0].score) >= 0.93:
            return None
    except Exception:  # noqa: BLE001
        pass
    return PointStruct(id=identifiant_point(f"qr:{mid}", 0), vector=vecteur, payload={
        "kind": "text", "nature": "qr", "statut": "propose", "title": q[:120], "text": f"Question : {q}\nRéponse : {r}",
        "question": q, "reponse": r, "source": "whatsapp", "direction": "outbound", "phone_digits": reponse_msg.get("phone_digits"),
        "client_id": reponse_msg.get("client_id"), "created_at": reponse_msg.get("created_at"), "message_id": str(mid)})


# ───────────────────────────── indexeur d'arrière-plan ─────────────────────────────

async def indexer_lot(db, taille: int = TAILLE_LOT) -> Dict[str, Any]:
    """Un passage de l'indexeur. Jamais d'exception vers le planificateur. Retourne un bilan."""
    bilan = {"lus": 0, "indexes": 0, "ignores": 0, "erreurs": 0, "raison": None}
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        r = reglages(s)
        if not r["actif"] or not s.get("qdrant_enabled"):
            bilan["raison"] = "desactive"
            return bilan
        from routes.qdrant_rag import _embed_texts, embeddings_autorises
        if not embeddings_autorises():
            bilan["raison"] = "memoire_serveur_insuffisante"
            return bilan
        etat = await _etat(db)
        curseur = etat.get("curseur") or datetime.now(timezone.utc).isoformat()       # première activation : à partir de maintenant
        messages = await db.whatsapp_messages.find(
            {"created_at": {"$gt": curseur}, "phone_digits": {"$nin": [None, ""]}}, {"_id": 0},
        ).sort("created_at", 1).limit(taille).to_list(taille)
        if not messages:
            return bilan
        client = await _preparer_collection(db)
        from qdrant_client.models import PointStruct
        images_jour = dict(etat.get("images_jour") or {})
        jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        images_jour = {k: v for k, v in images_jour.items() if k >= (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")}
        points: List[Any] = []
        for m in messages:
            bilan["lus"] += 1
            nature = nature_du_message(m, r["images"])
            if not nature:
                bilan["ignores"] += 1
                continue
            try:
                contenu, image_ok = await _contenu_media(db, m, nature, {"images_jour": images_jour}, r["images_par_jour"])
                if image_ok:
                    images_jour[jour] = images_jour.get(jour, 0) + 1
                blocs = blocs_de_message(m, contenu)
                if not blocs:
                    bilan["ignores"] += 1
                    continue
                vecteurs = await asyncio.to_thread(_embed_texts, blocs)
                mid = m.get("id") or m.get("wa_message_id") or m.get("message_id") or f"{m.get('phone_digits')}:{m.get('created_at')}"
                for rang, (bloc, vec) in enumerate(zip(blocs, vecteurs)):
                    points.append(PointStruct(id=identifiant_point(str(mid), rang), vector=vec, payload={
                        "kind": "text", "title": (m.get("contact_name") or m.get("sender_label") or m.get("phone_digits") or "")[:120],
                        "text": bloc, "source": "whatsapp", "nature": nature, "direction": m.get("direction"),
                        "phone_digits": m.get("phone_digits"), "client_id": m.get("client_id"), "contact_name": m.get("contact_name"),
                        "sender_label": m.get("sender_label") if m.get("direction") == "outbound" else None,
                        "message_id": str(mid), "created_at": m.get("created_at"),
                        "media_url": m.get("media_url"), "media_filename": m.get("media_filename"), "rang": rang,
                    }))
                bilan["indexes"] += 1
                if nature == "texte" and m.get("direction") == "outbound":
                    candidat = await _candidat_qr(db, client, m, mid)
                    if candidat is not None:
                        points.append(candidat)
                        bilan["candidats"] = bilan.get("candidats", 0) + 1
            except Exception:  # noqa: BLE001 — un message illisible ne bloque jamais les suivants
                logger.warning("[wa_memoire] message ignoré (erreur de lecture)", exc_info=True)
                bilan["erreurs"] += 1
        if points:
            await asyncio.to_thread(lambda: client.upsert(collection_name=COLLECTION, points=points))   # échec → curseur inchangé
        await db.settings.update_one({"_id": ETAT_ID}, {"$set": {
            "curseur": messages[-1]["created_at"], "images_jour": images_jour, "derniere_execution": datetime.now(timezone.utc).isoformat(),
            "derniere_erreur": None}, "$inc": {"total_points": len(points), "total_messages": bilan["indexes"]}}, upsert=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[wa_memoire] passage d'indexation échoué : %s", exc, exc_info=True)
        bilan["raison"] = f"erreur: {str(exc)[:160]}"
        try:
            await db.settings.update_one({"_id": ETAT_ID}, {"$set": {"derniere_erreur": bilan["raison"],
                                         "derniere_execution": datetime.now(timezone.utc).isoformat()}}, upsert=True)
        except Exception:  # noqa: BLE001
            pass
    return bilan


async def rattraper_historique(db, jours: int) -> Dict[str, Any]:
    """Replace le curseur `jours` jours en arrière : l'indexeur reprend alors l'historique par lots (sans doublon)."""
    jours = max(0, min(int(jours), 3650))
    depuis = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
    await db.settings.update_one({"_id": ETAT_ID}, {"$set": {"curseur": depuis}}, upsert=True)
    return {"ok": True, "reprise_depuis": depuis}


# ───────────────────────────── recherche ─────────────────────────────

async def rechercher(db, *, requete: str, phone_digits: Optional[str] = None, client_id: Optional[str] = None,
                     direction: Optional[str] = None, nature: Optional[str] = None, top_k: int = 8) -> List[Dict[str, Any]]:
    """Recherche par similarité dans la mémoire des conversations (filtres exacts facultatifs)."""
    from routes.qdrant_rag import _client_pret, _embed_query, _resolve_credentials
    if not (requete or "").strip():
        return []
    url, cle = await _resolve_credentials(db)
    client = await _client_pret(url, cle)
    vec = await asyncio.to_thread(_embed_query, requete)
    filtre = filtre_qdrant(phone_digits=phone_digits, client_id=client_id, direction=direction, nature=nature,
                           sans_nature=None if nature == "qr" else "qr")      # les candidates ont leur propre écran
    k = min(max(1, int(top_k or 8)), 30)
    hits = (await asyncio.to_thread(lambda: client.query_points(
        collection_name=COLLECTION, query=vec, query_filter=filtre, limit=k, with_payload=True))).points
    return [{"score": round(float(h.score), 4), **{c: (h.payload or {}).get(c) for c in (
        "text", "nature", "direction", "phone_digits", "contact_name", "sender_label", "created_at", "media_url", "media_filename", "message_id")}}
        for h in hits]


async def contexte_pour_ia(db, *, phone_digits: str, client_id: Optional[str], requete: str, max_chars: int = 1800) -> str:
    """Bloc de contexte pour Liluvine : les extraits les plus proches du MÊME numéro (même client). Avec le réglage
    « réponses de l'équipe », ajoute des réponses humaines d'autres conversations du même client, sans nom ni numéro.
    Jamais d'exception : en cas de problème, Liluvine répond comme avant (chaîne vide)."""
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        r = reglages(s)
        if not (r["actif"] and r["ia"] and s.get("qdrant_enabled") and (requete or "").strip() and phone_digits):
            return ""
        from routes.qdrant_rag import embeddings_autorises
        if not embeddings_autorises():
            return ""
        parts: List[str] = []
        total = 0
        propres = await asyncio.wait_for(rechercher(db, requete=requete, phone_digits=phone_digits, client_id=client_id, top_k=5), timeout=4)
        if propres:
            parts.append("[HISTORIQUE DE CE CONTACT — extraits d'anciens échanges, à utiliser seulement s'ils sont pertinents]")
        for h in propres:
            if h["score"] < 0.35:
                continue
            ligne = f"• {(h.get('created_at') or '')[:10]} — {'client' if h.get('direction') == 'inbound' else 'équipe'} : {(h.get('text') or '')[:500]}"
            if total + len(ligne) > max_chars:
                break
            parts.append(ligne)
            total += len(ligne)
        if r["ia_reponses_equipe"] and client_id:
            autres = await asyncio.wait_for(rechercher(db, requete=requete, client_id=client_id, direction="outbound", top_k=4), timeout=4)
            retenus = [h for h in autres if h["score"] >= 0.5 and h.get("phone_digits") != phone_digits]
            if retenus:
                parts.append("[RÉPONSES DÉJÀ DONNÉES PAR L'ÉQUIPE SUR CE SUJET — anonymes ; ne cite jamais de nom, numéro ni donnée personnelle]")
                for h in retenus:
                    ligne = f"• {(h.get('text') or '')[:400]}"
                    if total + len(ligne) > max_chars:
                        break
                    parts.append(ligne)
                    total += len(ligne)
        return "\n".join(parts) if len(parts) > 1 else ""
    except Exception:  # noqa: BLE001
        logger.info("[wa_memoire] contexte IA indisponible", exc_info=True)
        return ""


# ───────────────────────────── routes d'administration ─────────────────────────────
from pydantic import BaseModel, Field  # noqa: E402  (modèles au niveau du module : annotations différées)


class Recherche(BaseModel):
    requete: str = Field(min_length=2, max_length=500)
    numero: Optional[str] = Field(None, max_length=40)
    direction: Optional[str] = Field(None, pattern="^(inbound|outbound)$")
    nature: Optional[str] = Field(None, pattern="^(texte|pdf|image)$")
    top_k: int = Field(8, ge=1, le=30)

class Historique(BaseModel):
    jours: int = Field(30, ge=0, le=3650)

class Decision(BaseModel):
    collection: str = Field(min_length=1, max_length=64)
    question: Optional[str] = Field(None, max_length=900)      # corrigées par le propriétaire avant publication
    reponse: Optional[str] = Field(None, max_length=1800)



def make_router(*, db, get_current_user):
    from fastapi import APIRouter, Depends, HTTPException

    router = APIRouter(prefix="/admin/wa-memoire", tags=["Admin — Mémoire des conversations (Qdrant)"])

    def _gate(user: dict):
        if user.get("role") not in ("admin", "superviseur") and user.get("tracked_role") not in ("Administrateur", "Superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")



    @router.get("/etat")
    async def etat(user: dict = Depends(get_current_user)):
        """Réglages, curseur, compteurs et espace utilisé par la collection."""
        _gate(user)
        s = await db.settings.find_one({"_id": "global"}) or {}
        e = await _etat(db)
        points = None
        try:
            from routes.qdrant_rag import _client_pret, _resolve_credentials, embeddings_autorises
            url, cle = await _resolve_credentials(db)
            client = await _client_pret(url, cle)
            if await asyncio.to_thread(lambda: client.collection_exists(COLLECTION)):
                points = (await asyncio.to_thread(lambda: client.count(COLLECTION, exact=False))).count
            serveur_ok = embeddings_autorises()
        except Exception:  # noqa: BLE001
            serveur_ok = None
        return {"reglages": reglages(s), "qdrant_active": bool(s.get("qdrant_enabled")), "serveur_assez_grand": serveur_ok,
                "points": points, "total_messages": e.get("total_messages", 0), "curseur": e.get("curseur"),
                "derniere_execution": e.get("derniere_execution"), "derniere_erreur": e.get("derniere_erreur")}

    @router.post("/rechercher")
    async def chercher(corps: Recherche, user: dict = Depends(get_current_user)):
        """Recherche par similarité (filtres : numéro, sens, nature)."""
        _gate(user)
        chiffres = re.sub(r"\D", "", corps.numero or "")
        try:
            return {"items": await rechercher(db, requete=corps.requete, phone_digits=chiffres or None,
                                              direction=corps.direction, nature=corps.nature, top_k=corps.top_k)}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"Recherche indisponible : {str(exc)[:160]}") from exc

    @router.post("/historique")
    async def historique(corps: Historique, user: dict = Depends(get_current_user)):
        """Indexe aussi l'historique des N derniers jours (reprise par lots, sans doublon)."""
        _gate(user)
        return await rattraper_historique(db, corps.jours)


    async def _client_qdrant():
        from routes.qdrant_rag import _client_pret, _resolve_credentials
        url, cle = await _resolve_credentials(db)
        return await _client_pret(url, cle)

    @router.get("/candidates")
    async def candidates(statut: str = "propose", limite: int = 30, user: dict = Depends(get_current_user)):
        """Questions / réponses candidates à relire (statut « propose »), les plus récentes d'abord."""
        _gate(user)
        if statut not in ("propose", "valide", "refuse"):
            raise HTTPException(status_code=422, detail="Statut inconnu")
        client = await _client_qdrant()
        try:
            pts, _ = await asyncio.to_thread(lambda: client.scroll(
                collection_name=COLLECTION, scroll_filter=filtre_qdrant(nature="qr", statut=statut),
                limit=min(max(1, limite), 100), with_payload=True, with_vectors=False))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"Lecture impossible : {str(exc)[:160]}") from exc
        items = [{"id": str(p.id), **{c: (p.payload or {}).get(c) for c in ("question", "reponse", "created_at", "statut", "collection")}} for p in pts]
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return {"items": items}

    async def _maj_statut(client, pid: str, statut: str, extra: Optional[Dict[str, Any]] = None):
        await asyncio.to_thread(lambda: client.set_payload(collection_name=COLLECTION, payload={"statut": statut, **(extra or {})}, points=[pid]))

    @router.post("/candidates/{pid}/valider")
    async def valider(pid: str, corps: Decision, user: dict = Depends(get_current_user)):
        """Publie la question / réponse (relue, éventuellement corrigée) dans la collection choisie de la base de connaissances."""
        _gate(user)
        from routes.qdrant_rag import list_collections, upsert_text_documents
        noms = {c["name"] for c in await list_collections(db)}
        if corps.collection not in noms or corps.collection == COLLECTION:
            raise HTTPException(status_code=422, detail="Collection inconnue (choisissez une collection de la base de connaissances)")
        client = await _client_qdrant()
        trouves = await asyncio.to_thread(lambda: client.retrieve(collection_name=COLLECTION, ids=[pid], with_payload=True))
        if not trouves or (trouves[0].payload or {}).get("nature") != "qr":
            raise HTTPException(status_code=404, detail="Candidate introuvable")
        pl = trouves[0].payload or {}
        q = anonymiser((corps.question or pl.get("question") or "").strip())
        r = anonymiser((corps.reponse or pl.get("reponse") or "").strip())
        if len(q) < 5 or len(r) < 5:
            raise HTTPException(status_code=422, detail="Question et réponse ne peuvent pas être vides")
        await upsert_text_documents(db, collection=corps.collection, docs=[{
            "title": q[:200], "text": f"Question : {q}\nRéponse : {r}", "source": "conversations WhatsApp (validé)",
            "tags": ["conversation", "validé"]}])
        await _maj_statut(client, pid, "valide", {"collection": corps.collection, "valide_par": user.get("email"),
                                                  "valide_le": datetime.now(timezone.utc).isoformat()})
        return {"ok": True, "collection": corps.collection}

    @router.post("/candidates/{pid}/refuser")
    async def refuser(pid: str, user: dict = Depends(get_current_user)):
        """Écarte la candidate (elle ne sera plus reproposée : les doublons sont ignorés)."""
        _gate(user)
        await _maj_statut(await _client_qdrant(), pid, "refuse")
        return {"ok": True}

    @router.post("/indexer-maintenant")
    async def indexer_maintenant(user: dict = Depends(get_current_user)):
        """Lance un passage tout de suite (utile pour tester)."""
        _gate(user)
        return await indexer_lot(db)

    return router
