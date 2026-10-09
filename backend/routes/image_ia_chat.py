# image_ia_chat.py — Lot 87 : image illustrative générée par l'IA dans la fenêtre de support (chat interne).
#
# Demande du propriétaire (09/10/2026) : « Sur la fenêtre de support SAWALI, avoir un bouton pour une
# génération d'image illustrative comme pour le carrousel. On clique sur un bouton, ça ouvre une modale,
# on tape le prompt et si on accepte l'image générée, elle vient dans le chat du support. Réservé au
# support ou à l'admin. Il peut aussi transférer cette image à n'importe qui. »
#
# Principe (même mécanisme en 2 temps que le carrousel, lot 75) :
#   1. GÉNÉRER : la description (prompt) + un style + un format → l'IA (gpt-image-1) produit l'image,
#      gardée 2 h comme APERÇU (collection chat_images_ia) ; rien n'est encore envoyé.
#   2. ACCEPTER : l'image part dans la discussion ouverte (fil d'un poste Loois, #général, message privé),
#      comme une photo ordinaire (stockage + diffusion temps réel), marquée « 🎨 Image IA ».
#   3. TRANSFÉRER à n'importe qui : une autre discussion SAWALI (n'importe quel espace / membre visible),
#      un numéro WhatsApp (image + légende) ou une adresse e-mail. Le transfert marche aussi pour toute
#      image déjà présente dans le chat (bouton « ↪ Transférer » de l'agrandissement).
#   4. DROITS : équipe SAWALI seulement — administrateur, superviseur (ou utilisateur suivi « Administrateur »
#      / « Superviseur ») et compte du support Loois (LOOIS_SUPPORT_ADMIN_EMAIL). Jamais un compte client.
#   5. ANNOTER (demande du 09/10/2026) : avant l'envoi, l'image générée s'ouvre dans l'annotateur
#      (flèches, cercles, texte, flou…), comme dans la discussion WhatsApp ; la version annotée remplace l'aperçu.
#   6. PLANIFIER : l'envoi dans le chat comme le transfert (WhatsApp, e-mail, autre discussion) peut partir
#      « maintenant » ou à une date et une heure choisies (collection chat_images_ia_planifies, traitée chaque minute
#      par le planificateur) ; les envois planifiés se consultent et s'annulent depuis la modale.
#   7. RÉGLAGES (Paramètres → « 🎨 Images IA du chat de support ») : activé ou non, images par heure et
#      par personne, style proposé par défaut ; état : images générées, envoyées, transférées (7 jours).
from __future__ import annotations

import base64
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from fastapi import Body, Depends, File, HTTPException, UploadFile

from routes import support_loois
from routes.requetes_clients import est_admin_sawali

log = logging.getLogger("sawali.image_ia_chat")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
COLLECTION = "chat_images_ia"              # aperçus et images retenues
COLLECTION_JOURNAL = "chat_images_ia_transferts"   # qui a transféré quoi, à qui, quand, résultat
COLLECTION_PLANIFIES = "chat_images_ia_planifies"   # envois planifiés (date et heure choisies)
PLANIFICATION_MAX_JOURS = 60               # au plus 60 jours à l'avance
PROMPT_MAX = 1000                          # longueur maximale de la description
LEGENDE_MAX = 500                          # légende jointe à l'image
APERCU_DUREE_H = 2                         # un aperçu non retenu est effacé après 2 h
PAR_HEURE_DEFAUT = 20                      # images générées par heure et par personne (réglable)
IMAGE_MAX_OCTETS = 5 * 1024 * 1024         # limite WhatsApp pour une image
INDICATIF_DEFAUT = "226"                   # numéro local à 8 chiffres : Burkina Faso

# Styles proposés dans la modale : consigne ajoutée à la description de l'utilisateur
STYLES = {
    "illustration": "Illustration moderne, claire et professionnelle, couleurs douces, fond simple.",
    "photo": "Photographie réaliste, bien éclairée, nette, cadrage professionnel.",
    "schema": "Schéma explicatif épuré, style pictogrammes, lisible, fond blanc.",
    "libre": "",
}
STYLE_DEFAUT = "illustration"
# Formats : taille demandée à l'IA (gpt-image-1)
FORMATS = {"carre": "1024x1024", "paysage": "1536x1024", "portrait": "1024x1536"}
# Consigne commune : pas de texte incrusté (l'IA écrit souvent mal), sauf demande explicite
CONSIGNE_TEXTE = "N'ajoute aucun texte dans l'image, sauf si la description le demande explicitement."


# ---------------------------------------------------------------------------
# Fonctions pures (testées sans base)
# ---------------------------------------------------------------------------
def peut_generer(user: Dict[str, Any]) -> bool:
    """Équipe SAWALI (admin, superviseur) ou compte désigné du support Loois. Jamais un compte client."""
    if not user or user.get("parent_client_id"):
        return False
    return est_admin_sawali(user) or support_loois.est_compte_support(user)


def prompt_final(description: str, style: Optional[str] = None) -> str:
    """Consigne envoyée à l'IA : description nettoyée + consigne du style + pas de texte incrusté."""
    description = " ".join((description or "").split())[:PROMPT_MAX]
    if not description:
        raise ValueError("Décrivez l'image à générer.")
    consigne = STYLES.get(style or STYLE_DEFAUT, STYLES[STYLE_DEFAUT])
    return " ".join(x for x in (description.rstrip(".") + ".", consigne, CONSIGNE_TEXTE) if x).strip()


def taille_du_format(fmt: Optional[str]) -> str:
    """Format choisi → taille gpt-image-1 (carré par défaut)."""
    return FORMATS.get(fmt or "carre", FORMATS["carre"])


def numero_whatsapp(brut: Any) -> str:
    """Chiffres seuls avec l'indicatif : « 76 22 22 22 » → « 22676222222 » ; « +33 6… » → « 336… »."""
    tel = re.sub(r"\D", "", str(brut or ""))
    if tel.startswith("00"):
        tel = tel[2:]
    return INDICATIF_DEFAUT + tel if len(tel) == 8 else tel


def email_valide(adresse: Any) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(adresse or "").strip()))


def raison_whatsapp(erreur: Any) -> str:
    """Message d'échec WhatsApp lisible (fenêtre de 24 h fermée : cas le plus fréquent)."""
    texte = str(erreur or "")
    if "131047" in texte or "24 hours" in texte or "re-engagement" in texte.lower():
        return ("Fenêtre de 24 h fermée : ce numéro ne vous a pas écrit depuis 24 h. "
                "WhatsApp n'accepte alors qu'un modèle approuvé ; envoyez plutôt l'image par e-mail.")
    return texte[:300] or "Envoi WhatsApp refusé"


def legende_propre(texte: Any) -> str:
    return " ".join(str(texte or "").split())[:LEGENDE_MAX]


def date_planifiee(valeur: Any, maintenant: Optional[datetime] = None) -> Optional[datetime]:
    """« Planifier » : date ISO → datetime UTC ; None si vide ou déjà passée (= envoi immédiat).
    ValueError si illisible ou à plus de 60 jours."""
    if valeur in (None, ""):
        return None
    try:
        d = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Date de planification illisible") from exc
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    maintenant = maintenant or datetime.now(timezone.utc)
    if d <= maintenant + timedelta(seconds=30):
        return None
    if d > maintenant + timedelta(days=PLANIFICATION_MAX_JOURS):
        raise ValueError(f"Planification limitée à {PLANIFICATION_MAX_JOURS} jours")
    return d.astimezone(timezone.utc)


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def setup_image_ia_chat_routes(*, db, api, get_current_user, chat, save_and_log=None, wa_send_media=None,
                               send_email=None, base_publique: Optional[Callable[[], str]] = None,
                               generateur: Optional[Callable] = None) -> None:
    """Branche les routes du lot 87.
    chat : routeur du chat interne (poster_image, verifier_membre… exposés par make_router) ;
    save_and_log : stockage public (lien https pour WhatsApp / e-mail) ; wa_send_media / send_email : envois ;
    base_publique() : adresse publique du serveur ; generateur(prompt, taille) → octets (remplacé dans les tests)."""

    async def _generer_octets(prompt: str, taille: str) -> bytes:
        """Appel à l'IA (gpt-image-1) ; renvoie les octets PNG de la première image."""
        if generateur:
            return await generateur(prompt, taille)
        from ia_client import OpenAIImageGeneration
        images = await OpenAIImageGeneration().generate_images(prompt, model="gpt-image-1", quality="medium",
                                                               size=taille)
        if not images:
            raise RuntimeError("L'IA n'a renvoyé aucune image. Reformulez la description.")
        return images[0]

    async def _reglages() -> Dict[str, Any]:
        """Réglages de la rubrique des Paramètres (valeurs par défaut si jamais enregistrés)."""
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "chat_image_ia_actif": 1,
                                                            "chat_image_ia_par_heure": 1,
                                                            "chat_image_ia_style": 1}) or {}
        try:
            par_heure = max(1, min(200, int(s.get("chat_image_ia_par_heure") or PAR_HEURE_DEFAUT)))
        except (TypeError, ValueError):
            par_heure = PAR_HEURE_DEFAUT
        style = s.get("chat_image_ia_style") if s.get("chat_image_ia_style") in STYLES else STYLE_DEFAUT
        return {"actif": s.get("chat_image_ia_actif") is not False, "par_heure": par_heure, "style": style}

    def _exiger_droit(user: dict) -> None:
        if not peut_generer(user):
            raise HTTPException(status_code=403, detail="Réservé au support et à l'administration de SAWALI")

    async def _utilisees(user_id: str) -> int:
        """Images générées par cette personne depuis une heure."""
        il_y_a_une_heure = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        return await db[COLLECTION].count_documents({"user_id": user_id, "cree_le": {"$gte": il_y_a_une_heure}})

    async def _image(apercu_id: str, user: dict) -> Dict[str, Any]:
        """Image générée par cette personne (aperçu ou déjà retenue)."""
        doc = await db[COLLECTION].find_one({"id": apercu_id, "user_id": user["id"]}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Image introuvable : générez-la à nouveau.")
        return doc

    async def _octets_image(doc: Dict[str, Any]) -> bytes:
        """Octets de l'image : aperçu encore en base, sinon copie stockée."""
        if doc.get("octets_b64"):
            return base64.b64decode(doc["octets_b64"])
        if doc.get("storage_path"):          # copie du message envoyé dans le chat
            from storage import afetch_bytes
            data, _ = await afetch_bytes(doc["storage_path"])
            return data
        if doc.get("public_path"):           # copie publique (transfert WhatsApp / e-mail)
            from object_storage import get_object
            data, _ = await get_object(doc["public_path"])
            return data
        raise HTTPException(status_code=404, detail="Aperçu expiré (2 h) : générez l'image à nouveau.")

    async def _source(p: Dict[str, Any], user: dict) -> Dict[str, Any]:
        """Image à transférer : une image IA (apercu_id) OU une image déjà dans le chat (message_id)."""
        if p.get("apercu_id"):
            doc = await _image(str(p["apercu_id"]), user)
            mime = doc.get("mime") or "image/png"     # JPEG possible après annotation
            return {"octets": await _octets_image(doc), "mime": mime, "doc": doc,
                    "nom": f"image-ia-{doc['id'][:8]}.{'jpg' if mime == 'image/jpeg' else 'png'}", "libelle": "image IA"}
        mid = str(p.get("message_id") or "").strip()
        if not mid:
            raise HTTPException(status_code=422, detail="Aucune image à transférer")
        m = await db.internal_chat_messages.find_one({"id": mid}, {"_id": 0})
        if not m or m.get("media_kind") != "image" or not m.get("storage_path"):
            raise HTTPException(status_code=404, detail="Image introuvable dans le chat")
        await chat.verifier_membre(user, m["client_id"])     # même contrôle que l'affichage de l'image
        from storage import afetch_bytes
        data, ct = await afetch_bytes(m["storage_path"])
        mime = (ct or m.get("media_mime") or "image/jpeg").split(";")[0]
        ext = {"image/png": "png", "image/webp": "webp"}.get(mime, "jpg")
        return {"octets": data, "mime": mime, "doc": None, "nom": f"image-{mid[:8]}.{ext}", "libelle": "image du chat",
                "message": m}

    async def _lien_public(src: Dict[str, Any], user: dict) -> str:
        """Adresse https de l'image (WhatsApp et e-mail la téléchargent) ; créée une seule fois par image IA."""
        doc = src.get("doc")
        if doc and doc.get("url"):
            return doc["url"]
        if save_and_log is None:
            raise HTTPException(status_code=503, detail="Stockage des fichiers indisponible")
        ext = src["nom"].rsplit(".", 1)[-1]
        saved = await save_and_log(db, data=src["octets"], kind="chat-ia", tenant_id=user["id"], ext=ext,
                                   content_type=src["mime"], original_filename=src["nom"], user_id=user["id"])
        url = saved["url"]
        if url.startswith("/"):
            url = f"{(base_publique() if base_publique else '').rstrip('/')}{url}"
        if doc:
            await db[COLLECTION].update_one({"id": doc["id"]}, {"$set": {"url": url, "public_path": saved.get("path")}})
            doc["url"] = url
        return url

    async def _journaliser(user: dict, src: Dict[str, Any], canal: str, vers: str, ok: bool, raison: str = "") -> None:
        try:
            await db[COLLECTION_JOURNAL].insert_one({
                "id": uuid.uuid4().hex, "par_id": user["id"], "par_nom": user.get("full_name") or user.get("email"),
                "apercu_id": (src.get("doc") or {}).get("id"), "message_id": (src.get("message") or {}).get("id"),
                "canal": canal, "vers": vers, "ok": ok, "raison": raison, "le": _maintenant()})
        except Exception:  # noqa: BLE001 — le journal ne doit jamais faire échouer l'envoi
            log.exception("journal du transfert impossible")

    # --- État (la fenêtre de chat affiche le bouton 🎨 seulement si autorisé) ---------------------
    @api.get("/me/chat/image-ia/etat", tags=["Chat interne — image IA"])
    async def etat(user: dict = Depends(get_current_user)):
        r = await _reglages()
        autorise = peut_generer(user) and r["actif"]
        return {"autorise": autorise, "par_heure": r["par_heure"], "style": r["style"],
                "utilisees": await _utilisees(user["id"]) if autorise else 0,
                "styles": list(STYLES), "formats": list(FORMATS)}

    # --- 1. Générer l'aperçu ---------------------------------------------------------------------
    @api.post("/me/chat/image-ia", tags=["Chat interne — image IA"])
    async def generer(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        _exiger_droit(user)
        r = await _reglages()
        if not r["actif"]:
            raise HTTPException(status_code=403, detail="Génération d'images désactivée dans les Paramètres")
        p = payload or {}
        try:
            consigne = prompt_final(p.get("prompt"), p.get("style") or r["style"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if await _utilisees(user["id"]) >= r["par_heure"]:
            raise HTTPException(status_code=429, detail=f"Limite atteinte : {r['par_heure']} images par heure. Réessayez plus tard.")
        try:
            octets = await _generer_octets(consigne, taille_du_format(p.get("format")))
        except Exception as exc:  # noqa: BLE001 — clé absente, contenu refusé, réseau…
            raise HTTPException(status_code=502, detail=f"Génération de l'image impossible : {str(exc)[:200]}") from exc
        if len(octets) > 10 * 1024 * 1024:
            raise HTTPException(status_code=502, detail="Image générée trop lourde. Réessayez.")
        # Effacement des aperçus de plus de 2 h jamais retenus, puis enregistrement de celui-ci
        limite = (datetime.now(timezone.utc) - timedelta(hours=APERCU_DUREE_H)).isoformat()
        await db[COLLECTION].update_many({"cree_le": {"$lt": limite}, "octets_b64": {"$ne": None}, "garder": {"$ne": True}},
                                         {"$set": {"octets_b64": None}})
        b64 = base64.b64encode(octets).decode("ascii")
        doc = {"id": uuid.uuid4().hex, "user_id": user["id"], "prompt": str(p.get("prompt") or "")[:PROMPT_MAX],
               "style": p.get("style") or r["style"], "format": p.get("format") or "carre", "octets_b64": b64, "mime": "image/png",
               "storage_path": None, "public_path": None, "url": None, "envois": 0, "cree_le": _maintenant()}
        await db[COLLECTION].insert_one(doc.copy())
        return {"apercu_id": doc["id"], "apercu": f"data:image/png;base64,{b64}", "taille": len(octets)}

    # --- Cœur des envois (appelé tout de suite, ou plus tard par le planificateur) ------------------
    async def _executer_envoi(user: dict, apercu_id: str, p: Dict[str, Any]) -> Dict[str, Any]:
        """Accepter : l'image IA part dans la discussion choisie (fil, #général, message privé)."""
        client_id = str(p.get("client_id") or "").strip()
        if not client_id:
            raise HTTPException(status_code=422, detail="Ouvrez d'abord une discussion")
        await chat.verifier_membre(user, client_id)
        doc = await _image(apercu_id, user)
        message = await chat.poster_image(
            user, client_id, await _octets_image(doc), doc.get("mime") or "image/png",
            recipient_id=(None if p.get("recipient_id") in (None, "", "general") else str(p["recipient_id"])),
            caption=legende_propre(p.get("legende")) or None,
            extra={"ia": True, "ia_prompt": doc.get("prompt"), "ia_image_id": doc["id"],
                   "ia_annotee": bool(doc.get("annotee"))})
        # L'image retenue garde sa copie stockée : on peut la transférer après l'expiration de l'aperçu
        await db[COLLECTION].update_one({"id": doc["id"]}, {"$inc": {"envois": 1},
                                                            "$set": {"storage_path": doc.get("storage_path") or message.get("storage_path")}})
        return message

    async def _executer_transfert(user: dict, p: Dict[str, Any]) -> Dict[str, Any]:
        """Transférer à n'importe qui : autre discussion SAWALI, numéro WhatsApp ou adresse e-mail."""
        canal = str(p.get("canal") or "").strip()
        legende = legende_propre(p.get("legende"))
        if canal not in ("chat", "whatsapp", "email"):
            raise HTTPException(status_code=422, detail="Canal inconnu : chat, whatsapp ou email")
        src = await _source(p, user)

        if canal == "chat":
            client_id = str(p.get("client_id") or "").strip()
            if not client_id:
                raise HTTPException(status_code=422, detail="Choisissez une discussion")
            await chat.verifier_membre(user, client_id)
            dest = None if p.get("recipient_id") in (None, "", "general") else str(p["recipient_id"])
            extra = {"transfere": True}
            if src.get("doc"):
                extra.update({"ia": True, "ia_prompt": src["doc"].get("prompt"), "ia_image_id": src["doc"]["id"]})
            message = await chat.poster_image(user, client_id, src["octets"], src["mime"], recipient_id=dest,
                                              caption=legende or None, extra=extra)
            await _journaliser(user, src, "chat", f"{client_id}/{dest or 'general'}", True)
            return {"ok": True, "canal": "chat", "message": message}

        if canal == "whatsapp":
            numero = numero_whatsapp(p.get("telephone"))
            if len(numero) < 8:
                raise HTTPException(status_code=422, detail="Numéro WhatsApp invalide")
            if wa_send_media is None:
                raise HTTPException(status_code=503, detail="WhatsApp non configuré")
            if len(src["octets"]) > IMAGE_MAX_OCTETS:
                raise HTTPException(status_code=413, detail="Image trop lourde pour WhatsApp (5 Mo)")
            url = await _lien_public(src, user)
            res = await wa_send_media(numero, "image", public_url=url, caption=legende or None) or {}
            if not res.get("ok"):
                raison = raison_whatsapp(res.get("error"))
                await _journaliser(user, src, "whatsapp", numero, False, raison)
                raise HTTPException(status_code=502, detail=raison)
            await _journaliser(user, src, "whatsapp", numero, True)
            return {"ok": True, "canal": "whatsapp", "vers": numero}

        # canal == "email"
        adresse = str(p.get("email") or "").strip()
        if not email_valide(adresse):
            raise HTTPException(status_code=422, detail="Adresse e-mail invalide")
        if send_email is None:
            raise HTTPException(status_code=503, detail="Service d'e-mail indisponible")
        url = await _lien_public(src, user)
        expediteur = user.get("full_name") or user.get("email") or "SAWALI"
        html = (f"<p>{expediteur} vous transmet une image depuis SAWALI.</p>"
                + (f"<p>{legende}</p>" if legende else "")
                + f'<p><img src="{url}" alt="Image" style="max-width:100%;border-radius:8px"/></p>'
                + f'<p><a href="{url}">Ouvrir l\'image</a></p>')
        ok = await send_email(adresse, "SAWALI — image transmise", html, f"{legende}\n{url}".strip())
        await _journaliser(user, src, "email", adresse, bool(ok), "" if ok else "envoi refusé")
        if not ok:
            raise HTTPException(status_code=502, detail="Envoi de l'e-mail impossible")
        return {"ok": True, "canal": "email", "vers": adresse}

    async def _planifier(user: dict, action: str, p: Dict[str, Any], quand: datetime) -> Dict[str, Any]:
        """Enregistre un envoi planifié ; l'image IA est gardée (pas effacée au bout de 2 h)."""
        if p.get("apercu_id"):
            doc = await _image(str(p["apercu_id"]), user)
            if not doc.get("octets_b64") and not doc.get("storage_path"):
                raise HTTPException(status_code=404, detail="Aperçu expiré (2 h) : générez l'image à nouveau.")
            await db[COLLECTION].update_one({"id": doc["id"]}, {"$set": {"garder": True}})
        if action == "envoyer":
            await chat.verifier_membre(user, str(p.get("client_id") or ""))
        plan = {"id": uuid.uuid4().hex, "user_id": user["id"], "action": action,
                "payload": {k: v for k, v in p.items() if k != "planifie_le"},
                "planifie_le": quand.isoformat(), "statut": "planifie", "raison": "", "cree_le": _maintenant()}
        await db[COLLECTION_PLANIFIES].insert_one(plan.copy())
        return {"ok": True, "planifie": True, "id": plan["id"], "planifie_le": plan["planifie_le"]}

    def _quand(p: Dict[str, Any]) -> Optional[datetime]:
        try:
            return date_planifiee(p.get("planifie_le"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # --- 2. Annoter (facultatif) : la version annotée remplace l'aperçu ----------------------------
    @api.post("/me/chat/image-ia/{apercu_id}/annoter", tags=["Chat interne — image IA"])
    async def annoter(apercu_id: str, image: UploadFile = File(...), user: dict = Depends(get_current_user)):
        _exiger_droit(user)
        doc = await _image(apercu_id, user)
        octets = await image.read()
        mime = (image.content_type or "").lower()
        if not octets or mime not in ("image/png", "image/jpeg"):
            raise HTTPException(status_code=400, detail="Image annotée invalide (PNG ou JPEG)")
        if len(octets) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Image annotée trop lourde (10 Mo)")
        # Nouvelle image : l'ancien lien public et l'ancienne copie stockée ne la représentent plus
        b64 = base64.b64encode(octets).decode("ascii")
        await db[COLLECTION].update_one({"id": doc["id"]}, {"$set": {
            "octets_b64": b64, "mime": mime, "annotee": True, "url": None, "storage_path": None, "public_path": None,
            "annotee_le": _maintenant()}})
        return {"apercu_id": doc["id"], "apercu": f"data:{mime};base64,{b64}", "annotee": True}

    # --- 3. Accepter : l'image part dans la discussion ouverte (maintenant ou planifié) -------------
    @api.post("/me/chat/image-ia/{apercu_id}/envoyer", tags=["Chat interne — image IA"])
    async def envoyer(apercu_id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        _exiger_droit(user)
        p = dict(payload or {})
        quand = _quand(p)
        if quand:
            return await _planifier(user, "envoyer", {**p, "apercu_id": apercu_id}, quand)
        return await _executer_envoi(user, apercu_id, p)

    # --- 4. Transférer à n'importe qui (maintenant ou planifié) ------------------------------------
    @api.post("/me/chat/image-ia/transferer", tags=["Chat interne — image IA"])
    async def transferer(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        _exiger_droit(user)
        p = dict(payload or {})
        quand = _quand(p)
        if quand:
            if str(p.get("canal") or "") not in ("chat", "whatsapp", "email"):
                raise HTTPException(status_code=422, detail="Canal inconnu : chat, whatsapp ou email")
            if p.get("canal") == "email" and not email_valide(p.get("email")):
                raise HTTPException(status_code=422, detail="Adresse e-mail invalide")
            if p.get("canal") == "whatsapp" and len(numero_whatsapp(p.get("telephone"))) < 8:
                raise HTTPException(status_code=422, detail="Numéro WhatsApp invalide")
            if not p.get("apercu_id") and not p.get("message_id"):
                raise HTTPException(status_code=422, detail="Aucune image à transférer")
            return await _planifier(user, "transferer", p, quand)
        return await _executer_transfert(user, p)

    # --- 5. Envois planifiés : liste, annulation, traitement chaque minute ---------------------------
    @api.get("/me/chat/image-ia/planifies", tags=["Chat interne — image IA"])
    async def lister_planifies(user: dict = Depends(get_current_user)):
        _exiger_droit(user)
        docs = await db[COLLECTION_PLANIFIES].find({"user_id": user["id"]}, {"_id": 0}).sort("planifie_le", -1).to_list(50)
        return {"planifies": docs}

    @api.delete("/me/chat/image-ia/planifies/{plan_id}", tags=["Chat interne — image IA"])
    async def annuler_planifie(plan_id: str, user: dict = Depends(get_current_user)):
        _exiger_droit(user)
        res = await db[COLLECTION_PLANIFIES].update_one({"id": plan_id, "user_id": user["id"], "statut": "planifie"},
                                                        {"$set": {"statut": "annule", "traite_le": _maintenant()}})
        if not res.modified_count:
            raise HTTPException(status_code=404, detail="Envoi planifié introuvable ou déjà parti")
        return {"ok": True}

    async def traiter_planifies(limite: int = 20) -> int:
        """Appelé chaque minute par le planificateur : envoie les images dont l'heure est venue.
        Chaque envoi est réservé (statut « en_cours ») avant d'être fait : jamais deux fois."""
        faits = 0
        for _ in range(limite):
            plan = await db[COLLECTION_PLANIFIES].find_one_and_update(
                {"statut": "planifie", "planifie_le": {"$lte": _maintenant()}},
                {"$set": {"statut": "en_cours"}}, projection={"_id": 0})
            if not plan:
                break
            statut, raison = "envoye", ""
            try:
                user = await db.users.find_one({"id": plan["user_id"]}, {"_id": 0, "password": 0, "password_hash": 0})
                if not user or not peut_generer(user):
                    raise HTTPException(status_code=403, detail="Auteur introuvable ou sans droit")
                if plan["action"] == "envoyer":
                    await _executer_envoi(user, plan["payload"]["apercu_id"], plan["payload"])
                else:
                    await _executer_transfert(user, plan["payload"])
            except HTTPException as exc:
                statut, raison = "echec", str(exc.detail)[:300]
            except Exception as exc:  # noqa: BLE001 — un envoi en échec ne bloque pas les suivants
                log.exception("envoi planifié %s en échec", plan.get("id"))
                statut, raison = "echec", str(exc)[:300]
            await db[COLLECTION_PLANIFIES].update_one({"id": plan["id"]}, {"$set": {
                "statut": statut, "raison": raison, "traite_le": _maintenant()}})
            faits += 1
        return faits

    # --- Paramètres (rubrique « 🎨 Images IA du chat de support ») ---------------------------------
    @api.get("/admin/chat-image-ia", tags=["Chat interne — image IA"])
    async def lire_reglages(user: dict = Depends(get_current_user)):
        _exiger_droit(user)
        depuis = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        return {**await _reglages(), "styles": list(STYLES), "formats": list(FORMATS),
                "stats_7j": {
                    "generees": await db[COLLECTION].count_documents({"cree_le": {"$gte": depuis}}),
                    "envoyees": await db[COLLECTION].count_documents({"cree_le": {"$gte": depuis}, "envois": {"$gt": 0}}),
                    "transferts": await db[COLLECTION_JOURNAL].count_documents({"le": {"$gte": depuis}, "ok": True}),
                }}

    @api.put("/admin/chat-image-ia", tags=["Chat interne — image IA"])
    async def ecrire_reglages(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "super_admin", "superviseur") or user.get("parent_client_id"):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur ou au superviseur")
        p = payload or {}
        maj: Dict[str, Any] = {}
        if "actif" in p:
            maj["chat_image_ia_actif"] = bool(p["actif"])
        if "par_heure" in p:
            try:
                maj["chat_image_ia_par_heure"] = max(1, min(200, int(p["par_heure"])))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="Nombre d'images par heure invalide") from exc
        if "style" in p:
            if p["style"] not in STYLES:
                raise HTTPException(status_code=422, detail="Style inconnu")
            maj["chat_image_ia_style"] = p["style"]
        if maj:
            await db.settings.update_one({"_id": "global"}, {"$set": maj}, upsert=True)
        return await lire_reglages(user)

    return {"traiter_planifies": traiter_planifies}
