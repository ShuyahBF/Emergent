# wa_transfert.py — Lot 71 : transférer des messages WhatsApp (texte, image, document, audio, vidéo,
# position) d'une conversation vers un ou plusieurs AUTRES contacts.
#
# Demande du propriétaire (06/10/2026) : « Dans les conversations WA, permettre de transférer messages ou
# images reçus vers un autre contact. »
#
# Principe :
#   1. CHOIX : depuis une bulle de la conversation (« Transférer »), ou plusieurs bulles sélectionnées,
#      l'utilisateur choisit jusqu'à 10 destinataires (contacts WhatsApp de son annuaire ; clients pour
#      l'administrateur et le superviseur), un commentaire facultatif, l'option « indiquer l'origine »
#      (« Transféré de <nom> : » devant le texte, ou dans la légende d'un média) et la ligne d'envoi
#      (par défaut : la ligne de la conversation de chaque destinataire, règle du lot 59).
#   2. FENÊTRE DE 24 H (règle Meta) : un message libre n'est accepté que si le destinataire a écrit à cette
#      ligne depuis moins de 24 h. La fenêtre est affichée AVANT l'envoi (badge « fenêtre fermée ») ;
#      pour un destinataire hors fenêtre, l'utilisateur choisit : envoyer un MODÈLE approuvé à la place
#      (le texte transféré va dans la première variable, le média éventuel dans l'en-tête) ou l'ignorer.
#   3. MÉDIAS : on réutilise la copie DÉJÀ STOCKÉE chez nous (/api/files/…, enregistrée à la réception par
#      le webhook) envoyée à Meta par lien, comme les médias envoyés depuis la conversation (lot 35) :
#      jamais de nouveau téléchargement chez Meta (leurs liens expirent). Limites Meta contrôlées
#      (taille, formats) ; un format non accepté pour une image / un son / une vidéo part en document.
#   4. RÉSULTAT par destinataire (envoyé, partiel, refusé + motif, ignoré) : rien n'échoue en silence.
#      Chaque message transféré apparaît dans la conversation du destinataire (marque « ↪ Transféré »),
#      et un JOURNAL (collection wa_transferts) garde qui a transféré quoi, quand et à qui.
#   5. DROITS : seuls les messages de conversations visibles par l'utilisateur (périmètre du compte et
#      lignes WhatsApp autorisées, lot 59) peuvent être transférés, et seulement vers des contacts qu'il voit.
#
# Les envois passent par appel_proprietaire._graph_post (numéro d'envoi explicite), imité dans les tests.
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import Request   # au niveau du module : annotation lue par FastAPI (from __future__ annotations)

import routes.appel_proprietaire as ap
import routes.numeros_wa as nw

logger = logging.getLogger("sawali.wa_transfert")

# Journal des transferts (qui, quoi, quand, à qui, résultat)
COLLECTION_JOURNAL = "wa_transferts"
# Limites d'un transfert
DESTINATAIRES_MAX = 10
MESSAGES_MAX = 20
COMMENTAIRE_MAX = 1000
# Limites Meta (WhatsApp Cloud API) par type de média, en octets
LIMITES_META = {"image": 5 * 1024 * 1024, "audio": 16 * 1024 * 1024, "video": 16 * 1024 * 1024,
                "document": 100 * 1024 * 1024}
# Formats acceptés par Meta pour chaque type (sinon : envoi en document)
FORMATS_META = {
    "image": ("image/jpeg", "image/png"),
    "audio": ("audio/aac", "audio/amr", "audio/mpeg", "audio/mp4", "audio/ogg"),
    "video": ("video/mp4", "video/3gpp"),
}
# Libellés des natures de message (dialogue, journal)
NATURES = {"texte": "texte", "image": "image", "document": "document", "audio": "audio", "video": "vidéo",
           "position": "position", "contact": "carte de contact", "inconnu": "message"}
# Position reçue : le webhook l'enregistre sous la forme « [position 12.37,-1.52] »
MOTIF_POSITION = re.compile(r"^\[position\s+(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\]$")
# Corps « fantômes » d'un média sans légende (« [image reçu] », « [document envoyé] »)
MOTIF_CORPS_MEDIA = re.compile(r"^\[[a-zé ]+ (reçu|envoyé)\]$", re.I)


def _maintenant() -> datetime:
    """Horloge (celle du lot 67, simulée dans les tests)."""
    return ap._maintenant()


def _iso(dt: datetime) -> str:
    """Date → ISO UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _chiffres(valeur: Any) -> str:
    """« +226 70 00 00 01 » → « 22670000001 »."""
    return re.sub(r"\D", "", str(valeur or ""))


# ---------------------------------------------------------------------------
# Fonctions pures (testées) : nature, origine, corps Meta, modèles
# ---------------------------------------------------------------------------

def _mime(m: Dict[str, Any]) -> str:
    """Type MIME du média d'un message, sans paramètres (« audio/ogg; codecs=opus » → « audio/ogg »)."""
    return str(m.get("media_mime_type") or "").split(";", 1)[0].strip().lower()


def nature_message(m: Dict[str, Any]) -> str:
    """Nature d'un message : texte | image | document | audio | video | position | contact | inconnu."""
    if m.get("media_url"):
        kind = m.get("media_kind")
        if kind in ("image", "document", "audio", "video"):
            return kind
        mime = _mime(m)
        for prefixe in ("image", "audio", "video"):
            if mime.startswith(prefixe + "/"):
                return prefixe
        return "document"
    corps = str(m.get("body") or "").strip()
    if m.get("message_type") == "location" or MOTIF_POSITION.match(corps):
        return "position"
    if m.get("message_type") == "contacts":
        return "contact"
    if (m.get("message_type") in ("image", "document", "audio", "video", "sticker")
            and (not corps or MOTIF_CORPS_MEDIA.match(corps))):
        return "inconnu"                            # média dont la copie n'a pas été conservée
    if corps or m.get("template_rendered_body"):
        return "texte"
    return "inconnu"


def texte_du_message(m: Dict[str, Any]) -> str:
    """Texte à transférer : corps (rendu du modèle pour un message envoyé par modèle), sans les corps
    « fantômes » des médias."""
    t = str(m.get("template_rendered_body") or m.get("body") or "").strip() if m.get("template_name") \
        else str(m.get("body") or "").strip()
    return "" if MOTIF_CORPS_MEDIA.match(t) else t


def nom_origine(m: Dict[str, Any], contact_nom: Optional[str] = None) -> str:
    """Auteur d'origine du message : le contact (message reçu) ou l'agent qui l'a envoyé (message envoyé)."""
    if m.get("direction") == "outbound":
        return str(m.get("sender_label") or "SAWALI").strip()[:80]
    tel = _chiffres(m.get("phone_digits") or m.get("from"))
    return str(contact_nom or m.get("contact_name") or m.get("from_profile_name")
               or (f"+{tel}" if tel else "un contact")).strip()[:80]


def prefixe_origine(nom: str) -> str:
    """« Transféré de Awa KABORÉ : »."""
    return f"Transféré de {nom} : "


def type_envoi_media(kind: str, mime: str, taille: Optional[int]) -> Tuple[str, Optional[str]]:
    """Type d'envoi Meta d'un média stocké : (type, motif de refus ou None).
    Format non accepté pour une image / un son / une vidéo → document ; taille au-delà de la limite → refus."""
    final = kind if kind in LIMITES_META else "document"
    if final in FORMATS_META and mime and mime not in FORMATS_META[final]:
        final = "document"
    limite = LIMITES_META[final]
    if taille and int(taille) > limite:
        return final, (f"fichier trop volumineux pour WhatsApp ({int(taille) / 1048576:.1f} Mo, "
                       f"limite {limite // 1048576} Mo pour un {NATURES.get(final, final)})")
    return final, None


def construire_envois(m: Dict[str, Any], *, base_url: str, origine: Optional[str],
                      taille: Optional[int] = None) -> List[Dict[str, Any]]:
    """Message à transférer → corps Meta (sans « to » ni « messaging_product »), dans l'ordre d'envoi.
    origine : nom à indiquer (« Transféré de … : »), ou None pour ne pas l'indiquer.
    Lève ValueError (motif en français) si le message ne peut pas être transféré."""
    nature = nature_message(m)
    prefixe = prefixe_origine(origine) if origine else ""
    if nature == "texte":
        texte = texte_du_message(m)
        if not texte:
            raise ValueError("message vide")
        return [{"type": "text", "text": {"body": (prefixe + texte)[:4096], "preview_url": False}}]
    if nature in ("image", "document", "audio", "video"):
        url = str(m.get("media_url") or "")
        if not url.startswith("/api/files/") and not url.startswith("http"):
            raise ValueError("copie du média introuvable sur le serveur")
        if not base_url and not url.startswith("http"):
            raise ValueError("adresse publique du serveur inconnue (réglage public_base_url)")
        lien = url if url.startswith("http") else f"{base_url.rstrip('/')}{url}"
        final, refus = type_envoi_media(nature, _mime(m), taille or m.get("media_size_bytes"))
        if refus:
            raise ValueError(refus)
        objet: Dict[str, Any] = {"link": lien}
        legende = str(m.get("media_caption") or "").strip()
        envois: List[Dict[str, Any]] = []
        if final == "audio":
            # Un son n'a pas de légende : l'origine part dans un court texte juste avant
            if prefixe:
                envois.append({"type": "text", "text": {"body": f"{prefixe}note vocale / audio ci-dessous",
                                                        "preview_url": False}})
        else:
            if prefixe or legende:
                objet["caption"] = (prefixe + legende).strip()[:1024]
            if final == "document":
                objet["filename"] = str(m.get("media_filename") or "document")[:200]
        envois.append({"type": final, final: objet})
        return envois
    if nature == "position":
        p = MOTIF_POSITION.match(str(m.get("body") or "").strip())
        if not p:
            raise ValueError("position illisible")
        envois = [{"type": "text", "text": {"body": f"{prefixe}position ci-dessous", "preview_url": False}}] \
            if prefixe else []
        envois.append({"type": "location", "location": {"latitude": float(p.group(1)),
                                                        "longitude": float(p.group(2))}})
        return envois
    if nature == "contact":
        raise ValueError("carte de contact non transférable (son contenu n'est pas conservé)")
    raise ValueError("message non transférable (contenu non conservé)")


def analyser_modele(composants: Any) -> Dict[str, Any]:
    """Composants d'un modèle Meta → {nb_variables (corps), entete (IMAGE|VIDEO|DOCUMENT|TEXT|None),
    entete_variables}. Sert au remplissage du modèle de repli."""
    nb, entete, entete_vars = 0, None, 0
    for c in composants or []:
        if not isinstance(c, dict):
            continue
        genre = str(c.get("type") or "").upper()
        if genre == "BODY":
            nb = len(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", str(c.get("text") or ""))))
        elif genre == "HEADER":
            entete = str(c.get("format") or "TEXT").upper()
            entete_vars = len(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", str(c.get("text") or ""))))
    return {"nb_variables": nb, "entete": entete, "entete_variables": entete_vars}


def corps_modele(modele: Dict[str, Any], *, texte: str, lien_media: Optional[str],
                 nature_media: Optional[str], nom: str) -> Dict[str, Any]:
    """Modèle approuvé envoyé à la place d'un message libre (fenêtre fermée).
    1re variable du corps = texte transféré (une ligne, 900 caractères), autres = « — » ;
    en-tête média = le média transféré (même type exigé) ; en-tête texte à variable = nom d'origine.
    Lève ValueError si le modèle ne convient pas."""
    nom_modele = str(modele.get("name") or "").strip()
    if not nom_modele:
        raise ValueError("aucun modèle choisi")
    infos = analyser_modele(modele.get("components"))
    composants: List[Dict[str, Any]] = []
    if infos["entete"] in ("IMAGE", "VIDEO", "DOCUMENT"):
        genre = infos["entete"].lower()
        if not lien_media or nature_media != genre:
            raise ValueError(f"le modèle « {nom_modele} » exige une en-tête {genre} : transférez un(e) {genre}")
        composants.append({"type": "header", "parameters": [{"type": genre, genre: {"link": lien_media}}]})
    elif infos["entete"] == "TEXT" and infos["entete_variables"]:
        composants.append({"type": "header", "parameters": [{"type": "text", "text": ap.extrait(nom, 60) or "—"}]})
    if infos["nb_variables"]:
        valeurs = [ap.extrait(texte, 900) or "—"] + ["—"] * (infos["nb_variables"] - 1)
        composants.append({"type": "body", "parameters": [{"type": "text", "text": v} for v in valeurs]})
    corps: Dict[str, Any] = {"name": nom_modele, "language": {"code": str(modele.get("language") or "fr")}}
    if composants:
        corps["components"] = composants
    return {"type": "template", "template": corps}


def texte_pour_modele(messages: List[Dict[str, Any]], *, origine: Optional[str], commentaire: str) -> str:
    """Texte placé dans la variable du modèle : commentaire + origine + textes / légendes des messages."""
    morceaux = [commentaire.strip()] if commentaire.strip() else []
    contenus = []
    for m in messages:
        nature = nature_message(m)
        if nature == "texte":
            contenus.append(texte_du_message(m))
        elif nature in ("image", "document", "audio", "video"):
            contenus.append(str(m.get("media_caption") or f"[{NATURES.get(nature)}]"))
        elif nature == "position":
            contenus.append(str(m.get("body") or "[position]"))
    contenu = " / ".join(c for c in contenus if c)
    morceaux.append((prefixe_origine(origine) if origine else "") + contenu)
    return " — ".join(x for x in morceaux if x.strip())


def resume_journal(m: Dict[str, Any]) -> Dict[str, Any]:
    """Message transféré, tel que gardé au journal (pas de contenu complet : un extrait)."""
    return {"id": m.get("id"), "nature": nature_message(m), "direction": m.get("direction"),
            "extrait": ap.extrait(texte_du_message(m) or m.get("media_caption") or m.get("media_filename") or "", 120),
            "contact_id": m.get("contact_id"), "telephone": _chiffres(m.get("phone_digits"))}


# ---------------------------------------------------------------------------
# Accès aux données : messages visibles, destinataires, ligne, fenêtre
# ---------------------------------------------------------------------------

def _est_encadrant(user: Dict[str, Any]) -> bool:
    """Administrateur ou superviseur (voit aussi les clients comme destinataires et tout le journal)."""
    return user.get("role") in ("admin", "superviseur", "super_admin") or \
        user.get("tracked_role") in ("Administrateur", "Superviseur")


async def messages_visibles(db, user: Dict[str, Any], ids: List[str], visibles: List[str]) -> List[Dict[str, Any]]:
    """Messages demandés que l'utilisateur peut voir (périmètre du compte + ligne autorisée), dans l'ordre
    chronologique. Un message hors périmètre est simplement absent (jamais transféré)."""
    ids = [str(i) for i in ids or [] if str(i).strip()][:MESSAGES_MAX]
    if not ids:
        return []
    docs = await db.whatsapp_messages.find({"id": {"$in": ids}, "client_id": {"$in": list(visibles)}},
                                           {"_id": 0}).to_list(MESSAGES_MAX)
    sortie = []
    for m in docs:
        tel = m.get("phone_digits") or m.get("to") or m.get("from")
        if await nw.telephone_visible(db, user, tel):
            sortie.append(m)
    sortie.sort(key=lambda m: str(m.get("created_at") or ""))
    return sortie


async def resoudre_destinataire(db, user: Dict[str, Any], visibles: List[str], source: str,
                                ident: str) -> Optional[Dict[str, Any]]:
    """Destinataire choisi → {source, id, nom, telephone, client_id, contact} si l'utilisateur le voit.
    Le numéro est TOUJOURS relu en base (jamais celui envoyé par le navigateur)."""
    if source == "client":
        if not _est_encadrant(user):
            return None
        u = await db.users.find_one({"id": ident, "role": "client"}, {"_id": 0, "id": 1, "full_name": 1, "company": 1,
                                                                      "whatsapp": 1, "phone": 1, "client_id": 1})
        if not u:
            return None
        tel = _chiffres(u.get("whatsapp") or u.get("phone"))
        nom = u.get("company") or u.get("full_name") or f"+{tel}"
        contact, client_id = None, u.get("client_id") or u.get("id")
    else:
        contact = await db.directory_contacts.find_one({"id": ident, "client_id": {"$in": list(visibles)}}, {"_id": 0})
        if not contact:
            return None
        tel = _chiffres(contact.get("whatsapp") or contact.get("phone"))
        nom = contact.get("name") or f"+{tel}"
        client_id = contact.get("client_id")
    if len(tel) < 8 or not await nw.telephone_visible(db, user, tel, contact):
        return None
    return {"source": "client" if source == "client" else "contact", "id": ident, "nom": str(nom)[:120],
            "telephone": tel, "client_id": client_id, "contact": contact}


async def ligne_envoi(db, s: Dict[str, Any], user: Dict[str, Any], telephone: str, ligne_cle: Optional[str],
                      contact: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Ligne WhatsApp d'envoi : celle choisie (si autorisée à l'utilisateur), sinon la ligne de la conversation
    du destinataire (règle du lot 59). → (ligne, motif de refus)."""
    autorisees = nw.lignes_autorisees(user, s)
    if ligne_cle:
        ligne = nw.ligne_par_cle(s, ligne_cle)
        if not ligne:
            return None, "ligne WhatsApp inconnue"
        if autorisees is not None and ligne["cle"] not in autorisees:
            return None, "ligne WhatsApp non attribuée à l'utilisateur"
        return ligne, None
    cle = await nw.cle_ligne_conversation(db, telephone, s, contact)
    ligne = nw.ligne_par_cle(s, cle) or nw.lignes_configurees(s)[0]
    return ligne, None


async def rechercher_destinataires(db, user: Dict[str, Any], visibles: List[str], s: Dict[str, Any], q: str,
                                   ligne_cle: Optional[str], maintenant: datetime) -> List[Dict[str, Any]]:
    """Recherche de destinataires (nom ou numéro) avec, pour chacun, la ligne d'envoi et l'état de la
    fenêtre de 24 h — affiché AVANT l'envoi (badge « fenêtre fermée »)."""
    q = (q or "").strip()
    filtre: Dict[str, Any] = {"client_id": {"$in": list(visibles)},
                              "$or": [{"whatsapp": {"$nin": [None, ""]}}, {"phone": {"$nin": [None, ""]}}]}
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        chiffres = _chiffres(q)
        cond = [{"name": rx}, {"company": rx}]
        if len(chiffres) >= 3:
            cond += [{"whatsapp": {"$regex": chiffres}}, {"phone": {"$regex": chiffres}}]
        filtre = {"$and": [filtre, {"$or": cond}]}
    contacts = await db.directory_contacts.find(filtre, {"_id": 0}).sort("name", 1).to_list(60)
    trouves: List[Dict[str, Any]] = []
    for c in contacts:
        tel = _chiffres(c.get("whatsapp") or c.get("phone"))
        if len(tel) >= 8 and await nw.telephone_visible(db, user, tel, c):
            trouves.append({"source": "contact", "id": c["id"], "nom": c.get("name") or f"+{tel}", "telephone": tel,
                            "entreprise": c.get("company") or "", "contact": c})
    if _est_encadrant(user) and q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        clients = await db.users.find({"role": "client", "$or": [{"full_name": rx}, {"company": rx}, {"email": rx}]},
                                       {"_id": 0, "id": 1, "full_name": 1, "company": 1, "whatsapp": 1,
                                        "phone": 1}).to_list(20)
        for u in clients:
            tel = _chiffres(u.get("whatsapp") or u.get("phone"))
            if len(tel) >= 8 and not any(t["telephone"][-8:] == tel[-8:] for t in trouves):
                trouves.append({"source": "client", "id": u["id"], "nom": u.get("company") or u.get("full_name"),
                                "telephone": tel, "entreprise": u.get("full_name") or "", "contact": None})
    sortie = []
    for t in trouves[:30]:
        ligne, motif = await ligne_envoi(db, s, user, t["telephone"], ligne_cle, t["contact"])
        ouverte = bool(ligne) and await ap.fenetre_24h_ouverte(db, t["telephone"], ligne["phone_number_id"], maintenant)
        sortie.append({"source": t["source"], "id": t["id"], "nom": t["nom"], "telephone": t["telephone"],
                       "entreprise": t["entreprise"], "ligne_cle": (ligne or {}).get("cle"),
                       "ligne_libelle": (ligne or {}).get("libelle"), "ligne_refus": motif,
                       "fenetre_ouverte": ouverte})
    return sortie


async def _taille_stockee(db, m: Dict[str, Any]) -> Optional[int]:
    """Taille du média d'après la fiche du fichier stocké (si le message ne la porte pas)."""
    if m.get("media_size_bytes"):
        return int(m["media_size_bytes"])
    if m.get("media_id"):
        f = await db.files.find_one({"id": m["media_id"]}, {"_id": 0, "size": 1})
        if f and f.get("size"):
            return int(f["size"])
    return None


# ---------------------------------------------------------------------------
# Transfert : envois par destinataire, trace dans la conversation, journal
# ---------------------------------------------------------------------------

async def _tracer(db, *, user: Dict[str, Any], dest: Dict[str, Any], numero_id: str, corps: Dict[str, Any],
                  res: Dict[str, Any], origine_msg: Optional[Dict[str, Any]], origine_nom: str, transfert_id: str,
                  maintenant: datetime) -> None:
    """Message transféré écrit dans la conversation du destinataire (marque « ↪ Transféré »)."""
    genre = corps.get("type")
    mid = ((res.get("donnees") or {}).get("messages") or [{}])[0].get("id") if res.get("ok") else None
    doc: Dict[str, Any] = {
        "id": str(uuid.uuid4()), "client_id": dest.get("client_id") or user.get("client_id") or user.get("id"),
        "direction": "outbound", "sender_id": user.get("id"),
        "sender_label": user.get("full_name") or user.get("email"), "to": f"+{dest['telephone']}",
        "phone_digits": dest["telephone"], "contact_id": (dest.get("contact") or {}).get("id"),
        "message_type": "text" if genre == "text" else genre, "ok": bool(res.get("ok")),
        "message_id": mid, "error": res.get("erreur"), "wa_status": "sent" if res.get("ok") else "failed",
        "sent_at": _iso(maintenant) if res.get("ok") else None, "failed_at": None if res.get("ok") else _iso(maintenant),
        "created_at": _iso(maintenant), "wa_numero_id": numero_id,
        "transfere": True, "transfert_id": transfert_id,
        "transfere_de": {"message_id": (origine_msg or {}).get("id"), "nom": origine_nom,
                         "contact_id": (origine_msg or {}).get("contact_id")},
    }
    if genre == "text":
        doc["body"] = corps["text"]["body"]
    elif genre == "template":
        doc["template_name"] = corps["template"]["name"]
        doc["language_code"] = corps["template"]["language"]["code"]
        params = [p.get("text") for c in corps["template"].get("components") or [] if c.get("type") == "body"
                  for p in c.get("parameters") or []]
        doc["body"] = params[0] if params else f"Modèle : {corps['template']['name']}"
        doc["template_rendered_body"] = doc["body"]
    elif genre == "location":
        loc = corps["location"]
        doc["body"] = f"[position {loc['latitude']},{loc['longitude']}]"
    else:
        o = origine_msg or {}
        objet = corps.get(genre) or {}
        doc.update({"body": objet.get("caption") or f"[{genre} envoyé]", "media_id": o.get("media_id"),
                    "media_url": o.get("media_url"), "media_mime_type": o.get("media_mime_type"),
                    "media_filename": o.get("media_filename"), "media_size_bytes": o.get("media_size_bytes"),
                    "media_kind": genre,
                    "media_caption": objet.get("caption")})
    try:
        await db.whatsapp_messages.insert_one(doc)
    except Exception:  # noqa: BLE001
        logger.warning("[wa_transfert] trace du message transféré impossible", exc_info=True)


async def transferer(db, s: Dict[str, Any], user: Dict[str, Any], *, messages: List[Dict[str, Any]],
                     destinataires: List[Dict[str, Any]], commentaire: str = "", indiquer_origine: bool = True,
                     ligne_cle: Optional[str] = None, repli: Optional[Dict[str, str]] = None,
                     modele: Optional[Dict[str, Any]] = None, base_url: str = "",
                     contact_origine_nom: Optional[str] = None) -> Dict[str, Any]:
    """Transfère les messages (déjà contrôlés) à chaque destinataire (déjà résolu).
    → {transfert_id, resultats: [{id, nom, telephone, statut, mode, raison, envoyes, total}]}.
    statut : envoye | partiel | refuse | ignore. Le journal est écrit dans tous les cas."""
    maintenant = _maintenant()
    transfert_id = str(uuid.uuid4())
    commentaire = (commentaire or "").strip()[:COMMENTAIRE_MAX]
    repli = repli or {}
    origine_nom = nom_origine(messages[0], contact_origine_nom) if messages else ""
    origine = origine_nom if indiquer_origine else None
    # Préparation des envois (une seule fois) : un message non transférable est signalé, pas envoyé
    preparation: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    non_transferables: List[str] = []
    for m in messages:
        try:
            preparation.append((m, construire_envois(m, base_url=base_url, origine=origine,
                                                     taille=await _taille_stockee(db, m))))
        except ValueError as exc:
            non_transferables.append(f"{NATURES.get(nature_message(m))} : {exc}")
    resultats: List[Dict[str, Any]] = []
    for dest in destinataires:
        r = {"id": dest["id"], "source": dest["source"], "nom": dest["nom"], "telephone": dest["telephone"],
             "statut": "refuse", "mode": None, "raison": None, "envoyes": 0, "total": 0, "ligne": None}
        resultats.append(r)
        if not preparation:
            r["raison"] = "; ".join(non_transferables) or "aucun message transférable"
            continue
        ligne, motif = await ligne_envoi(db, s, user, dest["telephone"], ligne_cle, dest.get("contact"))
        if not ligne or not ligne.get("phone_number_id"):
            r["raison"] = motif or "ligne WhatsApp non configurée"
            continue
        numero_id = ligne["phone_number_id"]
        r["ligne"] = ligne.get("libelle")
        ouverte = await ap.fenetre_24h_ouverte(db, dest["telephone"], numero_id, maintenant)
        if not ouverte:
            choix = repli.get(dest["id"])
            if choix != "modele" or not modele:
                # Jamais d'échec silencieux : « ignoré » si l'utilisateur l'a choisi, sinon « refusé » + motif
                r.update(statut="ignore" if choix == "ignorer" else "refuse",
                         raison="fenêtre de 24 h fermée : message libre refusé par Meta"
                                + (" (destinataire ignoré)" if choix == "ignorer"
                                   else " — choisissez un modèle approuvé"))
                continue
            # Modèle approuvé à la place des messages libres
            premier_media = next((m for m, _ in preparation if nature_message(m) in ("image", "video", "document")), None)
            lien = None
            if premier_media is not None:
                lien = premier_media["media_url"] if str(premier_media.get("media_url")).startswith("http") \
                    else f"{base_url.rstrip('/')}{premier_media.get('media_url')}"
            try:
                corps = corps_modele(modele, texte=texte_pour_modele([m for m, _ in preparation], origine=origine,
                                                                     commentaire=commentaire),
                                     lien_media=lien, nature_media=nature_message(premier_media) if premier_media else None,
                                     nom=origine_nom)
            except ValueError as exc:
                r["raison"] = str(exc)
                continue
            r["mode"], r["total"] = "modele", 1
            res = await ap._graph_post(s, numero_id, "messages",
                                       {"messaging_product": "whatsapp", "to": dest["telephone"], **corps})
            await _tracer(db, user=user, dest=dest, numero_id=numero_id, corps=corps, res=res,
                          origine_msg=preparation[0][0], origine_nom=origine_nom, transfert_id=transfert_id,
                          maintenant=maintenant)
            if res.get("ok"):
                r.update(statut="envoye", envoyes=1)
            else:
                r["raison"] = res.get("erreur") or "refusé par Meta"
            continue
        # Fenêtre ouverte : commentaire, puis chaque message (texte / média / position)
        r["mode"] = "libre"
        envois: List[Tuple[Optional[Dict[str, Any]], Dict[str, Any]]] = []
        if commentaire:
            envois.append((None, {"type": "text", "text": {"body": commentaire, "preview_url": False}}))
        for m, corps_liste in preparation:
            envois.extend((m, c) for c in corps_liste)
        r["total"] = len(envois)
        erreurs = []
        for m, corps in envois:
            res = await ap._graph_post(s, numero_id, "messages",
                                       {"messaging_product": "whatsapp", "to": dest["telephone"], **corps})
            await _tracer(db, user=user, dest=dest, numero_id=numero_id, corps=corps, res=res, origine_msg=m,
                          origine_nom=origine_nom, transfert_id=transfert_id, maintenant=maintenant)
            if res.get("ok"):
                r["envoyes"] += 1
            else:
                erreurs.append(res.get("erreur") or "refusé par Meta")
        r["statut"] = "envoye" if not erreurs else ("partiel" if r["envoyes"] else "refuse")
        raisons = erreurs[:1] + ([f"non transférés : {'; '.join(non_transferables)}"] if non_transferables else [])
        r["raison"] = " ; ".join(raisons) or None
        if non_transferables and r["statut"] == "envoye":
            r["statut"] = "partiel"
    # Journal : qui a transféré quoi, quand, à qui, avec quel résultat
    journal = {
        "id": transfert_id, "le": _iso(maintenant), "par_id": user.get("id"),
        "par_nom": user.get("full_name") or user.get("email"), "client_id": user.get("client_id") or user.get("id"),
        "origine": {"nom": origine_nom, "contact_id": (messages[0] if messages else {}).get("contact_id")},
        "messages": [resume_journal(m) for m in messages], "commentaire": commentaire,
        "indiquer_origine": bool(indiquer_origine), "ligne_cle": ligne_cle,
        "modele": (modele or {}).get("name") if modele else None,
        "destinataires": [{k: r[k] for k in ("id", "source", "nom", "telephone", "statut", "mode", "raison",
                                             "envoyes", "total", "ligne")} for r in resultats],
    }
    try:
        await db[COLLECTION_JOURNAL].insert_one(dict(journal))
        await db.activity_events.insert_one({
            "id": str(uuid.uuid4()), "client_id": journal["client_id"], "kind": "whatsapp", "action": "forwarded",
            "label": f"{len(messages)} message(s) transféré(s) à {len(resultats)} destinataire(s)"[:160],
            "target_id": transfert_id, "actor_id": user.get("id"), "actor_label": journal["par_nom"] or "—",
            "ts": _iso(maintenant)})
    except Exception:  # noqa: BLE001
        logger.warning("[wa_transfert] journal non écrit", exc_info=True)
    return {"transfert_id": transfert_id, "resultats": resultats, "non_transferables": non_transferables}


# ---------------------------------------------------------------------------
# Routes (portail : tout utilisateur autorisé à écrire sur WhatsApp)
# ---------------------------------------------------------------------------

def setup_wa_transfert_routes(*, db, api, get_current_user, visibles_fn: Callable, base_url_fn: Callable,
                              peut_envoyer_fn: Optional[Callable] = None) -> None:
    """Déclare les routes /me/wa-transfert.
    visibles_fn(user) → comptes visibles ; base_url_fn(request) → adresse publique (liens des médias) ;
    peut_envoyer_fn(user) → droit d'écrire sur WhatsApp (mêmes rôles que l'envoi d'un message libre)."""
    from fastapi import Body, Depends, HTTPException, Query

    def _exiger_envoi(user: dict) -> None:
        """Même règle que l'envoi d'un message libre depuis la conversation."""
        ok = peut_envoyer_fn(user) if peut_envoyer_fn else (
            user.get("role") in ("client", "admin", "demo", "superviseur") or bool(user.get("tracked_role")))
        if not ok:
            raise HTTPException(status_code=403, detail="Rôle non autorisé à envoyer des messages WhatsApp")

    @api.get("/me/wa-transfert/lignes", tags=["WhatsApp — transfert"])
    async def lignes(user: dict = Depends(get_current_user)):
        """Lignes WhatsApp que l'utilisateur peut utiliser pour transférer."""
        _exiger_envoi(user)
        s = await db.settings.find_one({"_id": "global"}) or {}
        autorisees = nw.lignes_autorisees(user, s)
        return {"lignes": [{"cle": li["cle"], "libelle": li["libelle"]} for li in nw.lignes_configurees(s)
                           if li.get("phone_number_id") and (autorisees is None or li["cle"] in autorisees)]}

    @api.get("/me/wa-transfert/destinataires", tags=["WhatsApp — transfert"])
    async def destinataires(q: str = Query("", max_length=80), ligne_cle: Optional[str] = Query(None),
                            user: dict = Depends(get_current_user)):
        """Destinataires possibles (contacts visibles ; clients pour l'encadrement) + état de la fenêtre de 24 h."""
        _exiger_envoi(user)
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {"destinataires": await rechercher_destinataires(db, user, await visibles_fn(user), s, q,
                                                                ligne_cle or None, _maintenant())}

    @api.post("/me/wa-transfert", tags=["WhatsApp — transfert"])
    async def transferer_route(request: Request, payload: Dict[str, Any] = Body(...),
                               user: dict = Depends(get_current_user)):
        """Transfère un ou plusieurs messages à 1–10 destinataires → résultat par destinataire."""
        _exiger_envoi(user)
        p = payload or {}
        ids = p.get("message_ids") or ([p["message_id"]] if p.get("message_id") else [])
        if not ids:
            raise HTTPException(status_code=422, detail="Aucun message à transférer")
        if len(ids) > MESSAGES_MAX:
            raise HTTPException(status_code=422, detail=f"{MESSAGES_MAX} messages au plus par transfert")
        choisis = [d for d in p.get("destinataires") or [] if isinstance(d, dict) and d.get("id")]
        if not choisis:
            raise HTTPException(status_code=422, detail="Choisissez au moins un destinataire")
        if len(choisis) > DESTINATAIRES_MAX:
            raise HTTPException(status_code=422, detail=f"{DESTINATAIRES_MAX} destinataires au plus")
        visibles = await visibles_fn(user)
        messages = await messages_visibles(db, user, ids, visibles)
        if len(messages) != len(set(str(i) for i in ids)):
            raise HTTPException(status_code=404, detail="Message introuvable ou conversation non visible")
        resolus, refus = [], []
        for d in choisis:
            dest = await resoudre_destinataire(db, user, visibles, str(d.get("source") or "contact"), str(d["id"]))
            if dest:
                if not any(x["telephone"] == dest["telephone"] for x in resolus):
                    resolus.append(dest)
            else:
                refus.append({"id": d["id"], "nom": d.get("nom") or "?", "telephone": "", "statut": "refuse",
                              "mode": None, "raison": "destinataire introuvable ou non visible", "envoyes": 0,
                              "total": 0})
        s = await db.settings.find_one({"_id": "global"}) or {}
        contact_origine_nom = None
        if messages and messages[0].get("contact_id"):
            c = await db.directory_contacts.find_one({"id": messages[0]["contact_id"]}, {"_id": 0, "name": 1})
            contact_origine_nom = (c or {}).get("name")
        indiquer = p.get("indiquer_origine")
        sortie = await transferer(
            db, s, user, messages=messages, destinataires=resolus, commentaire=str(p.get("commentaire") or ""),
            indiquer_origine=True if indiquer is None else bool(indiquer),
            ligne_cle=(str(p.get("ligne_cle") or "").strip() or None),
            repli={str(k): str(v) for k, v in (p.get("repli") or {}).items()},
            modele=p.get("modele") if isinstance(p.get("modele"), dict) else None,
            base_url=base_url_fn(request) or "", contact_origine_nom=contact_origine_nom)
        sortie["resultats"] = refus + sortie["resultats"]
        return sortie

    @api.get("/me/wa-transfert/journal", tags=["WhatsApp — transfert"])
    async def journal(limit: int = Query(100, ge=1, le=500), user: dict = Depends(get_current_user)):
        """Journal des transferts : tout pour l'encadrement, ses propres transferts pour les autres."""
        _exiger_envoi(user)
        filtre = {} if _est_encadrant(user) else {"par_id": user.get("id")}
        docs = await db[COLLECTION_JOURNAL].find(filtre, {"_id": 0}).sort("le", -1).to_list(limit)
        return {"transferts": docs}
