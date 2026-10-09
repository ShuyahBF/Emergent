# requetes_clients.py — Lot 86 : REQUÊTES DES CLIENTS (dysfonctionnements, remarques, logiciels, équipements…).
#
# Demande du propriétaire (09/10/2026) : « Permettre à mes clients, contractuels ou pas, de me soumettre des points
# (dysfonctionnements, remarques, par logiciel ou sur leurs équipements…). Ces notifications écrites ou vocales sont
# horodatées et numérotées par client. De mon côté j'apprécie par une note/observation (date/heure auto), un état
# (en cours, terminé…) et le client évalue. Toutes ces requêtes sont organisées par lots ; quand c'est corrigé ou
# déployé, l'utilisateur revient pour évaluer. »
#
# En résumé (pour un développeur WinDev) :
#   - collections : db.requetes_clients (une fiche par requête) et db.requetes_lots (lots de correction) ;
#   - numéro par client : REQ-<code client>-0001, 0002… (compteur db.counters « requetes_<client> ») ;
#   - client (portail) : dépose une requête écrite et/ou vocale (fichier audio stocké, transcription automatique si la
#     clé Whisper est réglée), suit l'état et les observations, puis ÉVALUE (note 1 à 5 + commentaire) une fois la
#     requête terminée ou déployée ;
#   - SAWALI (administrateur) : ajoute des observations datées, change l'état, range la requête dans un lot ; quand un
#     lot passe à « Déployé », toutes ses requêtes passent à « Déployée » et chaque client est prévenu (e-mail et
#     WhatsApp, au mieux) qu'il peut évaluer.
#
# Lot 86.1 (09/10/2026) — « Le client reçoit-il par WA un lien public pour fournir ces requêtes ? Donnons aussi la
# possibilité de soumettre photos, captures ou charger des images » :
#   - IMAGES : jusqu'à 6 images par requête (photo prise au téléphone, capture collée, fichier chargé), 8 Mo chacune ;
#   - LIEN PERSONNEL du client (db.requetes_liens, jeton aléatoire, révocable) : page publique /requete/<jeton>, SANS
#     mot de passe, pour déposer, suivre et évaluer ses requêtes. SAWALI l'envoie par WhatsApp (et e-mail) ; le client
#     le retrouve aussi dans « Mes requêtes ». Les messages de suivi (requête traitée, lot déployé) le rappellent.
#
# Lot 86.2 (09/10/2026) — MODÈLES WHATSAPP META : un message libre n'est accepté par Meta que si le client a écrit
# dans les 24 h. Deux modèles « Utilitaire » (langue fr), créés chez Meta depuis l'onglet « Liens clients » :
#   - sawali_lien_requetes  : envoi du lien personnel, bouton « Ouvrir mes requêtes » ;
#   - sawali_suivi_requetes : suivi (requête traitée, lot déployé), même bouton.
#   Le bouton est une URL dynamique « <site>/requete/{{1}} » : on ne transmet que le jeton.
#   Envoi : modèle d'abord (fonctionne à tout moment une fois approuvé), sinon message libre (fenêtre de 24 h).
#   Envoi TOUJOURS depuis le numéro WhatsApp de SAWALI (jamais celui du client).
from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import File, Form, Request, UploadFile   # au niveau du module : annotations des routes résolues (from __future__)

logger = logging.getLogger("sawali.requetes_clients")

CATEGORIES = {
    "dysfonctionnement": "Dysfonctionnement",
    "remarque": "Remarque / suggestion",
    "logiciel": "Logiciel",
    "equipement": "Équipement",
    "autre": "Autre",
}
ETATS = {
    "nouvelle": "Nouvelle",
    "en_cours": "En cours",
    "attente_client": "En attente du client",
    "terminee": "Terminée",
    "deployee": "Déployée",
    "rejetee": "Rejetée",
}
ETATS_A_EVALUER = {"terminee", "deployee", "rejetee"}   # le client peut alors évaluer
ETATS_LOT = {"ouvert": "Ouvert", "en_cours": "En cours", "deploye": "Déployé"}
TAILLE_MAX_AUDIO = 15 * 1024 * 1024   # 15 Mo
TAILLE_MAX_IMAGE = 8 * 1024 * 1024    # 8 Mo par image (lot 86.1)
MAX_IMAGES = 6                        # images par requête
MAX_REQUETES_LIEN_PAR_JOUR = 30       # protection du lien public contre les envois en rafale
URL_SITE_DEFAUT = "https://sawalismartsystems.com"
MODELE_LIEN = "sawali_lien_requetes"     # lot 86.2 : modèle Meta d'envoi du lien
# Lot 90.3 (09/10/2026) — « sawali_suivi_requetes » a été RECLASSÉ « Marketing » par Meta (texte trop général et
# invitation à « évaluer » = demande d'avis). Nouveau modèle strictement transactionnel : état d'UNE requête, sans
# invitation ni avis. L'ancien modèle peut être supprimé dans le WhatsApp Manager une fois le nouveau approuvé.
MODELE_SUIVI = "sawali_requete_etat"     # lot 90.3 : modèle Meta UTILITAIRE des messages de suivi
LANGUE_MODELES = "fr"


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


# =====================================================================================
# Logique pure (testée : tests/test_lot86_requetes_clients.py)
# =====================================================================================

def code_client(client: Optional[Dict[str, Any]]) -> str:
    """Code court du client pour la numérotation : client_code, sinon initiales de la société, sinon « CLI »."""
    c = client or {}
    code = re.sub(r"[^A-Z0-9]", "", str(c.get("client_code") or "").upper())
    if code:
        return code[:10]
    nom = re.sub(r"[^A-Za-z0-9 ]", " ", str(c.get("company") or c.get("full_name") or ""))
    mots = [m for m in nom.upper().split() if m]
    if not mots:
        return "CLI"
    return ("".join(m[0] for m in mots) if len(mots) > 1 else mots[0])[:6]


def numero_requete(code: str, seq: int) -> str:
    """« REQ-ALBRK-0007 »."""
    return f"REQ-{code}-{int(seq):04d}"


def tenant_de(user: Dict[str, Any]) -> str:
    """Client (tenant) d'un utilisateur : son compte principal, sinon lui-même."""
    return user.get("parent_client_id") or user.get("client_id") or user.get("id") or ""


def est_admin_sawali(user: Dict[str, Any]) -> bool:
    """Équipe SAWALI qui traite les requêtes de tous les clients : administrateur ET, depuis le lot 86.3,
    superviseur (compte « superviseur » ou utilisateur suivi « Administrateur » / « Superviseur »).
    Jamais un utilisateur rattaché à un client (parent_client_id)."""
    if user.get("parent_client_id"):
        return False
    return (user.get("role") in ("admin", "super_admin", "superviseur")
            or user.get("tracked_role") in ("Administrateur", "Superviseur"))


def nettoyer_requete(categorie: Any, titre: Any, texte: Any, a_audio: bool) -> Dict[str, str]:
    """Contrôle d'une nouvelle requête ; ValueError avec message clair."""
    cat = str(categorie or "").strip().lower()
    if cat not in CATEGORIES:
        raise ValueError("Catégorie inconnue")
    titre = str(titre or "").strip()[:160]
    texte = str(texte or "").strip()[:5000]
    if not titre and not texte and not a_audio:
        raise ValueError("Écrivez votre requête ou enregistrez un message vocal")
    return {"categorie": cat, "titre": titre or (texte[:80] if texte else "Message vocal"), "texte": texte}


def evaluation_valide(note: Any, commentaire: Any) -> Dict[str, Any]:
    """Note entière de 1 à 5 + commentaire facultatif ; ValueError sinon."""
    try:
        n = int(note)
    except (TypeError, ValueError):
        raise ValueError("Note de 1 à 5 attendue")
    if not 1 <= n <= 5:
        raise ValueError("Note de 1 à 5 attendue")
    return {"note": n, "commentaire": str(commentaire or "").strip()[:1000]}


def resume(requetes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compte par état, requêtes à évaluer et moyenne des évaluations."""
    par_etat = {e: 0 for e in ETATS}
    notes = []
    for r in requetes:
        par_etat[r.get("etat") or "nouvelle"] = par_etat.get(r.get("etat") or "nouvelle", 0) + 1
        if (r.get("evaluation") or {}).get("note"):
            notes.append(r["evaluation"]["note"])
    return {"total": len(requetes), "par_etat": par_etat, "evaluees": len(notes),
            "moyenne": round(sum(notes) / len(notes), 2) if notes else None,
            "a_evaluer": sum(1 for r in requetes if r.get("a_evaluer"))}


def images_valides(fichiers: List[Dict[str, Any]]) -> None:
    """Contrôle des images jointes (nom, mime, taille) ; ValueError avec message clair."""
    if len(fichiers) > MAX_IMAGES:
        raise ValueError(f"{MAX_IMAGES} images au plus par requête")
    for f in fichiers:
        if not str(f.get("mime") or "").startswith("image/"):
            raise ValueError(f"« {f.get('nom') or 'fichier'} » n'est pas une image")
        if int(f.get("taille") or 0) > TAILLE_MAX_IMAGE:
            raise ValueError(f"Image « {f.get('nom') or ''} » trop lourde (8 Mo au plus)")


def url_lien(base: Optional[str], jeton: str) -> str:
    """Adresse de la page publique des requêtes d'un client : <site>/requete/<jeton>."""
    return f"{(base or URL_SITE_DEFAUT).rstrip('/')}/requete/{jeton}"


def message_lien(client_nom: str, url: str) -> str:
    """Message WhatsApp / e-mail d'envoi du lien personnel."""
    return (f"SAWALI : bonjour{(' ' + client_nom) if client_nom else ''}. Voici votre lien personnel pour nous signaler "
            f"un dysfonctionnement, une remarque, un souci de logiciel ou d'équipement (texte, message vocal, photos ou "
            f"captures d'écran), puis suivre et évaluer vos requêtes : {url}\nGardez ce lien : il est propre à votre structure.")


def definitions_modeles(base: Optional[str]) -> List[Dict[str, Any]]:
    """Corps envoyés à Meta (POST /{waba}/message_templates) pour les deux modèles du lot 86.2."""
    site = (base or URL_SITE_DEFAUT).rstrip("/")
    bouton = {"type": "BUTTONS", "buttons": [{
        "type": "URL", "text": "Ouvrir mes requêtes", "url": f"{site}/requete/{{{{1}}}}", "example": [f"{site}/requete/Ab12Cd34Ef56"]}]}
    pied = {"type": "FOOTER", "text": "SAWALI Smart Systems"}
    return [
        {"name": MODELE_LIEN, "language": LANGUE_MODELES, "category": "UTILITY", "components": [
            {"type": "BODY",
             "text": ("Bonjour {{1}}, voici votre lien personnel SAWALI pour nous signaler un dysfonctionnement, une "
                      "remarque ou un souci de logiciel ou d'équipement (texte, message vocal, photos ou captures "
                      "d'écran), puis suivre et évaluer vos requêtes. Ce lien est propre à votre structure : "
                      "partagez-le seulement avec vos agents."),
             "example": {"body_text": [["AL BARKA"]]}},
            pied, bouton]},
        {"name": MODELE_SUIVI, "language": LANGUE_MODELES, "category": "UTILITY", "components": [
            {"type": "BODY",
             # Lot 90.3 : notification d'état d'une requête existante (catégorie Utilitaire) — pas d'avis, pas d'offre
             "text": ("Mise à jour de votre requête SAWALI : {{1}}\n"
                      "Le détail de la requête est disponible via le bouton ci-dessous."),
             "example": {"body_text": [["la requête REQ-ALBRK-0003 est passée à l'état « Terminée »."]]}},
            pied, {"type": "BUTTONS", "buttons": [{
                "type": "URL", "text": "Voir la requête", "url": f"{site}/requete/{{{{1}}}}",
                "example": [f"{site}/requete/Ab12Cd34Ef56"]}]}]},
    ]


def composants_modele(texte: str, jeton: str) -> List[Dict[str, Any]]:
    """Paramètres d'envoi : {{1}} du corps (une seule ligne) et jeton du bouton URL."""
    propre = re.sub(r"\s+", " ", str(texte or "")).strip()[:900] or "-"
    return [{"type": "body", "parameters": [{"type": "text", "text": propre}]},
            {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": jeton}]}]


# =====================================================================================
# Routes
# =====================================================================================

def setup_requetes_clients_routes(*, db, api, get_current_user, send_email=None, wa_send_text=None,
                                  transcrire=None, upload_dir=None, base_url=None, wa_send_template=None,
                                  meta_http=None) -> None:
    """Branche les routes du lot 86 (appelée depuis server_parts/p20)."""
    import secrets
    from datetime import timedelta

    from fastapi import Depends, HTTPException
    from fastapi.responses import Response

    base = (base_url or os.environ.get("SAWALI_SITE_URL") or URL_SITE_DEFAUT).rstrip("/")

    def _admin(user: dict) -> None:
        if not est_admin_sawali(user):
            raise HTTPException(status_code=403, detail="Réservé à l'équipe SAWALI (administrateur ou superviseur)")

    async def _client_doc(tenant_id: str) -> dict:
        return await db.users.find_one({"id": tenant_id}, {"_id": 0, "id": 1, "client_code": 1, "company": 1,
                                                          "full_name": 1, "email": 1, "whatsapp_number": 1,
                                                          "phone": 1}) or {}

    async def _prochain_numero(tenant_id: str, client: dict) -> str:
        doc = await db.counters.find_one_and_update({"_id": f"requetes_{tenant_id}"}, {"$inc": {"seq": 1}},
                                                    upsert=True, return_document=True)
        seq = (doc or {}).get("seq") or 1
        return numero_requete(code_client(client), seq)

    async def _stocker(cle: str, data: bytes, mime: str, nom: str, ext_defaut: str) -> dict:
        """Enregistre un fichier joint (vocal ou image) : stockage R2 si disponible, sinon dossier local."""
        ext = os.path.splitext(nom or "")[1][:8] or ext_defaut
        try:
            from storage import aupload_bytes, astorage_available
            if await astorage_available():
                chemin = await aupload_bytes(f"requetes/{cle}{ext}", data, mime)
                return {"storage_path": chemin, "mime": mime, "taille": len(data)}
        except Exception:  # noqa: BLE001 — repli sur le disque local
            logger.warning("[requetes] stockage R2 indisponible, enregistrement local", exc_info=True)
        dossier = Path(upload_dir or tempfile.gettempdir()) / "requetes"
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / f"{cle}{ext}").write_bytes(data)
        return {"local": f"requetes/{cle}{ext}", "mime": mime, "taille": len(data)}

    async def _stocker_audio(req_id: str, data: bytes, mime: str, nom: str) -> dict:
        return await _stocker(req_id, data, mime, nom, ".webm")

    async def _servir(fichier: dict, defaut_mime: str) -> Response:
        """Renvoie le contenu d'un fichier joint (R2 ou disque local)."""
        if fichier.get("storage_path"):
            from storage import afetch_bytes
            data, ct = await afetch_bytes(fichier["storage_path"])
        else:
            chemin = Path(upload_dir or tempfile.gettempdir()) / fichier.get("local", "")
            if not fichier.get("local") or not chemin.is_file():
                raise HTTPException(status_code=404, detail="Fichier introuvable")
            data, ct = chemin.read_bytes(), fichier.get("mime")
        return Response(content=data, media_type=ct or fichier.get("mime") or defaut_mime,
                        headers={"Cache-Control": "private, max-age=86400"})

    async def _images_du_formulaire(request: Optional[Request]) -> List[UploadFile]:
        """Champs « images » du formulaire multipart (plusieurs fichiers possibles, lus directement dans la requête)."""
        if request is None:
            return []
        formulaire = await request.form()
        return [f for f in formulaire.getlist("images") if hasattr(f, "read")]

    async def _lire_images(images: Optional[List[UploadFile]]) -> List[Dict[str, Any]]:
        """Lit les images envoyées et les contrôle (nombre, type, taille)."""
        lues = []
        for f in images or []:
            if f is None or not getattr(f, "filename", None):
                continue
            data = await f.read()
            if not data:
                continue
            lues.append({"nom": f.filename, "mime": f.content_type or "", "taille": len(data), "data": data})
        try:
            images_valides(lues)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return lues

    # ------------------------------------------------------------------ lien personnel (lot 86.1)
    async def _lien_actif(tenant_id: str) -> Optional[dict]:
        return await db.requetes_liens.find_one({"tenant_id": tenant_id, "actif": True}, {"_id": 0})

    async def _lien(tenant_id: str, par: str = "", renouveler: bool = False) -> dict:
        """Lien personnel actif du client ; créé au besoin (renouveler = l'ancien est révoqué)."""
        actuel = await _lien_actif(tenant_id)
        if actuel and not renouveler:
            return actuel
        if actuel:
            await db.requetes_liens.update_many({"tenant_id": tenant_id, "actif": True},
                                                {"$set": {"actif": False, "revoque_le": _maintenant()}})
        doc = {"jeton": secrets.token_urlsafe(18), "tenant_id": tenant_id, "actif": True,
               "cree_le": _maintenant(), "cree_par": par, "envoye_le": None}
        await db.requetes_liens.insert_one(dict(doc))
        return doc

    async def _tenant_du_jeton(jeton: str) -> str:
        lien = await db.requetes_liens.find_one({"jeton": str(jeton or ""), "actif": True}, {"_id": 0, "tenant_id": 1})
        if not lien:
            raise HTTPException(status_code=404, detail="Lien invalide ou révoqué — demandez un nouveau lien à SAWALI")
        return lien["tenant_id"]

    async def _transcrire(data: bytes, nom: str) -> Optional[str]:
        if not transcrire:
            return None
        try:
            with tempfile.NamedTemporaryFile(suffix=os.path.splitext(nom or "")[1] or ".webm", delete=False) as f:
                f.write(data)
                chemin = Path(f.name)
            try:
                return await transcrire(chemin, "fr")
            finally:
                chemin.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 — la transcription est un plus, jamais bloquante
            return None

    async def _envoyer_wa(numero: str, modele: str, valeur: str, jeton: Optional[str], texte_libre: str) -> Optional[str]:
        """Lot 86.2 : modèle Meta d'abord (à tout moment), sinon message libre (fenêtre de 24 h).
        Depuis le numéro de SAWALI (aucun tenant_id). Renvoie "modele", "texte" ou None (échec)."""
        if wa_send_template and jeton:
            try:
                res = await wa_send_template(numero, modele, LANGUE_MODELES, composants_modele(valeur, jeton))
                if not isinstance(res, dict) or res.get("ok"):
                    return "modele"
                logger.info("[requetes] modèle %s non envoyé (%s) : repli message libre", modele, res.get("error"))
            except Exception:  # noqa: BLE001
                logger.warning("[requetes] envoi du modèle %s impossible", modele, exc_info=True)
        if wa_send_text:
            try:
                res = await wa_send_text(numero, texte_libre)
                if not isinstance(res, dict) or res.get("ok", True):
                    return "texte"
            except Exception:  # noqa: BLE001
                logger.warning("[requetes] message libre non envoyé", exc_info=True)
        return None

    async def _prevenir_client(tenant_id: str, texte: str, sujet: str) -> None:
        """Prévient le client (e-mail + WhatsApp), au mieux : une panne n'empêche jamais la mise à jour."""
        client = await _client_doc(tenant_id)
        lien = await _lien_actif(tenant_id)
        resume_suivi = texte.replace("SAWALI : ", "", 1)
        if lien:   # lot 86.1 : le message rappelle le lien personnel (évaluation sans se connecter)
            texte = f"{texte}\nVotre lien : {url_lien(base, lien['jeton'])}"
        if send_email and client.get("email"):
            try:
                await send_email(client["email"], sujet, f"<p>{texte}</p>", texte)
            except Exception:  # noqa: BLE001
                logger.warning("[requetes] e-mail au client non envoyé", exc_info=True)
        numero = client.get("whatsapp_number") or client.get("phone")
        if numero:   # lot 86.2 : modèle « suivi » (bouton vers le lien), sinon message libre
            await _envoyer_wa(str(numero), MODELE_SUIVI, resume_suivi, (lien or {}).get("jeton"), texte)

    def _public(r: dict) -> dict:
        """Fiche renvoyée (sans le chemin interne du fichier audio)."""
        r = dict(r)
        r.pop("_id", None)
        audio = r.pop("audio", None)
        r["a_audio"] = bool(audio)
        r["images"] = [{"id": i.get("id"), "nom": i.get("nom")} for i in (r.get("images") or [])]
        r["libelle_etat"] = ETATS.get(r.get("etat"), r.get("etat"))
        r["libelle_categorie"] = CATEGORIES.get(r.get("categorie"), r.get("categorie"))
        return r

    # ------------------------------------------------------------------ côté client (portail)
    @api.get("/me/requetes", tags=["Requêtes clients"])
    async def mes_requetes(user: dict = Depends(get_current_user)):
        """Requêtes du client (tous ses utilisateurs), les plus récentes d'abord."""
        lignes = [r async for r in db.requetes_clients.find({"tenant_id": tenant_de(user)}, {"_id": 0})
                  .sort("cree_le", -1).limit(500)]
        return {"requetes": [_public(r) for r in lignes], "categories": CATEGORIES, "etats": ETATS,
                "resume": resume(lignes)}

    async def _creer(tenant_id: str, auteur_id: Optional[str], auteur_nom: str, origine: str, categorie: str,
                     titre: str, texte: str, logiciel: str, equipement: str, audio: Optional[UploadFile],
                     images: Optional[List[UploadFile]], repli_nom: str = "") -> dict:
        """Création commune (portail connecté ou lien personnel) : contrôles, numéro, fichiers joints."""
        data = await audio.read() if audio is not None else b""
        if len(data) > TAILLE_MAX_AUDIO:
            raise HTTPException(status_code=413, detail="Message vocal trop long (15 Mo au plus)")
        lues = await _lire_images(images)
        try:
            champs = nettoyer_requete(categorie, titre, texte, bool(data) or bool(lues))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if champs["titre"] == "Message vocal" and lues and not data:
            champs["titre"] = "Images jointes"
        client = await _client_doc(tenant_id)
        req_id = str(uuid.uuid4())
        maintenant = _maintenant()
        doc = {
            "id": req_id, "numero": await _prochain_numero(tenant_id, client), "tenant_id": tenant_id,
            "client_nom": client.get("company") or client.get("full_name") or repli_nom or "",
            "auteur_id": auteur_id, "auteur_nom": auteur_nom, "origine": origine,
            **champs, "logiciel": str(logiciel or "").strip()[:120], "equipement": str(equipement or "").strip()[:120],
            "cree_le": maintenant, "etat": "nouvelle", "lot_id": None, "lot_numero": None,
            "observations": [], "historique": [{"etat": "nouvelle", "le": maintenant, "par": auteur_nom}],
            "evaluation": None, "a_evaluer": False, "images": [],
        }
        if data:
            mime = audio.content_type or "audio/webm"
            doc["audio"] = await _stocker_audio(req_id, data, mime, audio.filename or "")
            doc["transcription"] = await _transcrire(data, audio.filename or "")
        for img in lues:   # lot 86.1 : photos, captures, images chargées
            img_id = uuid.uuid4().hex[:12]
            stocke = await _stocker(f"{req_id}-{img_id}", img["data"], img["mime"], img["nom"], ".png")
            doc["images"].append({"id": img_id, "nom": str(img["nom"])[:120], **stocke})
        await db.requetes_clients.insert_one(dict(doc))
        return _public(doc)

    @api.post("/me/requetes", tags=["Requêtes clients"])
    async def nouvelle_requete(categorie: str = Form(...), titre: str = Form(""), texte: str = Form(""),
                               logiciel: str = Form(""), equipement: str = Form(""),
                               audio: Optional[UploadFile] = File(None), request: Request = None,
                               user: dict = Depends(get_current_user)):
        """Dépôt d'une requête écrite, vocale et/ou en images : numérotée par client et horodatée automatiquement."""
        return await _creer(tenant_de(user), user.get("id"), user.get("full_name") or user.get("email") or "", "portail",
                            categorie, titre, texte, logiciel, equipement, audio, await _images_du_formulaire(request),
                            user.get("company") or "")

    @api.post("/admin/requetes", tags=["Requêtes clients"])
    async def requete_pour_client(tenant_id: str = Form(...), categorie: str = Form(...), titre: str = Form(""),
                                  texte: str = Form(""), logiciel: str = Form(""), equipement: str = Form(""),
                                  audio: Optional[UploadFile] = File(None), request: Request = None,
                                  user: dict = Depends(get_current_user)):
        """Lot 86.3 — l'équipe SAWALI saisit une requête AU NOM d'un client (appel, visite, message reçu ailleurs)."""
        _admin(user)
        if not await _client_doc(tenant_id):
            raise HTTPException(status_code=404, detail="Client introuvable")
        auteur = f"{user.get('full_name') or user.get('email') or 'SAWALI'} (SAWALI)"
        return await _creer(tenant_id, user.get("id"), auteur, "sawali", categorie, titre, texte, logiciel, equipement,
                            audio, await _images_du_formulaire(request))

    @api.get("/me/requetes-lien", tags=["Requêtes clients"])
    async def mon_lien(user: dict = Depends(get_current_user)):
        """Lien personnel du client (créé au premier appel) : à partager avec ses agents."""
        lien = await _lien(tenant_de(user), user.get("full_name") or "")
        return {"url": url_lien(base, lien["jeton"]), "cree_le": lien["cree_le"]}

    @api.post("/me/requetes/{req_id}/evaluation", tags=["Requêtes clients"])
    async def evaluer(req_id: str, corps: dict, user: dict = Depends(get_current_user)):
        """Évaluation par le client d'une requête terminée, déployée ou rejetée."""
        r = await db.requetes_clients.find_one({"id": req_id, "tenant_id": tenant_de(user)}, {"_id": 0})
        if not r:
            raise HTTPException(status_code=404, detail="Requête introuvable")
        if r.get("etat") not in ETATS_A_EVALUER:
            raise HTTPException(status_code=409, detail="La requête n'est pas encore traitée")
        try:
            ev = evaluation_valide((corps or {}).get("note"), (corps or {}).get("commentaire"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        ev.update(le=_maintenant(), par=user.get("full_name") or user.get("email"))
        await db.requetes_clients.update_one({"id": req_id}, {"$set": {"evaluation": ev, "a_evaluer": False}})
        return {"ok": True, "evaluation": ev}

    @api.get("/requetes/{req_id}/audio", tags=["Requêtes clients"])
    async def ecouter(req_id: str, user: dict = Depends(get_current_user)):
        """Message vocal d'une requête (le client concerné ou l'administrateur de SAWALI)."""
        r = await db.requetes_clients.find_one({"id": req_id}, {"_id": 0, "audio": 1, "tenant_id": 1})
        if not r or not r.get("audio") or not (est_admin_sawali(user) or r.get("tenant_id") == tenant_de(user)):
            raise HTTPException(status_code=404, detail="Message vocal introuvable")
        return await _servir(r["audio"], "audio/webm")

    @api.get("/requetes/{req_id}/images/{img_id}", tags=["Requêtes clients"])
    async def voir_image(req_id: str, img_id: str, user: dict = Depends(get_current_user)):
        """Image jointe à une requête (le client concerné ou l'administrateur de SAWALI)."""
        r = await db.requetes_clients.find_one({"id": req_id}, {"_id": 0, "images": 1, "tenant_id": 1})
        if not r or not (est_admin_sawali(user) or r.get("tenant_id") == tenant_de(user)):
            raise HTTPException(status_code=404, detail="Image introuvable")
        image = next((i for i in r.get("images") or [] if i.get("id") == img_id), None)
        if not image:
            raise HTTPException(status_code=404, detail="Image introuvable")
        return await _servir(image, "image/png")

    # ------------------------------------------------------------------ lien personnel : pages publiques (lot 86.1)
    @api.get("/public/requetes/{jeton}", tags=["Requêtes clients"])
    async def public_liste(jeton: str):
        """Page du lien personnel : nom du client, catégories et suivi de ses requêtes (sans connexion)."""
        tenant_id = await _tenant_du_jeton(jeton)
        client = await _client_doc(tenant_id)
        lignes = [r async for r in db.requetes_clients.find({"tenant_id": tenant_id}, {"_id": 0})
                  .sort("cree_le", -1).limit(200)]
        publiques = []
        for r in lignes:
            p = _public(r)
            p.pop("auteur_id", None)
            publiques.append(p)
        return {"client_nom": client.get("company") or client.get("full_name") or "", "requetes": publiques,
                "categories": CATEGORIES, "etats": ETATS, "resume": resume(lignes)}

    @api.post("/public/requetes/{jeton}", tags=["Requêtes clients"])
    async def public_deposer(jeton: str, categorie: str = Form(...), titre: str = Form(""), texte: str = Form(""),
                             logiciel: str = Form(""), equipement: str = Form(""), auteur_nom: str = Form(""),
                             audio: Optional[UploadFile] = File(None), request: Request = None):
        """Dépôt par le lien personnel (sans connexion), limité à 30 requêtes par 24 h et par client."""
        tenant_id = await _tenant_du_jeton(jeton)
        depuis = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        recentes = await db.requetes_clients.count_documents({"tenant_id": tenant_id, "origine": "lien",
                                                              "cree_le": {"$gte": depuis}})
        if recentes >= MAX_REQUETES_LIEN_PAR_JOUR:
            raise HTTPException(status_code=429, detail="Trop de requêtes aujourd'hui par ce lien — réessayez demain")
        nom = str(auteur_nom or "").strip()[:80] or "Lien personnel"
        return await _creer(tenant_id, None, nom, "lien", categorie, titre, texte, logiciel, equipement, audio,
                            await _images_du_formulaire(request))

    @api.post("/public/requetes/{jeton}/{req_id}/evaluation", tags=["Requêtes clients"])
    async def public_evaluer(jeton: str, req_id: str, corps: dict):
        """Évaluation par le lien personnel d'une requête terminée, déployée ou rejetée."""
        tenant_id = await _tenant_du_jeton(jeton)
        r = await db.requetes_clients.find_one({"id": req_id, "tenant_id": tenant_id}, {"_id": 0})
        if not r:
            raise HTTPException(status_code=404, detail="Requête introuvable")
        if r.get("etat") not in ETATS_A_EVALUER:
            raise HTTPException(status_code=409, detail="La requête n'est pas encore traitée")
        try:
            ev = evaluation_valide((corps or {}).get("note"), (corps or {}).get("commentaire"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        ev.update(le=_maintenant(), par=str((corps or {}).get("auteur_nom") or "Lien personnel")[:80])
        await db.requetes_clients.update_one({"id": req_id}, {"$set": {"evaluation": ev, "a_evaluer": False}})
        return {"ok": True, "evaluation": ev}

    @api.get("/public/requetes/{jeton}/{req_id}/audio", tags=["Requêtes clients"])
    async def public_audio(jeton: str, req_id: str):
        tenant_id = await _tenant_du_jeton(jeton)
        r = await db.requetes_clients.find_one({"id": req_id, "tenant_id": tenant_id}, {"_id": 0, "audio": 1})
        if not r or not r.get("audio"):
            raise HTTPException(status_code=404, detail="Message vocal introuvable")
        return await _servir(r["audio"], "audio/webm")

    @api.get("/public/requetes/{jeton}/{req_id}/images/{img_id}", tags=["Requêtes clients"])
    async def public_image(jeton: str, req_id: str, img_id: str):
        tenant_id = await _tenant_du_jeton(jeton)
        r = await db.requetes_clients.find_one({"id": req_id, "tenant_id": tenant_id}, {"_id": 0, "images": 1})
        image = next((i for i in (r or {}).get("images") or [] if i.get("id") == img_id), None)
        if not image:
            raise HTTPException(status_code=404, detail="Image introuvable")
        return await _servir(image, "image/png")

    # ------------------------------------------------------------------ côté SAWALI (administrateur)
    @api.get("/admin/requetes-liens", tags=["Requêtes clients"])
    async def liens_clients(user: dict = Depends(get_current_user)):
        """Clients de SAWALI avec leur lien personnel (actif ou non) et la date du dernier envoi."""
        _admin(user)
        clients = [c async for c in db.users.find(
            {"role": "client", "$or": [{"parent_client_id": None}, {"parent_client_id": ""},
                                       {"parent_client_id": {"$exists": False}}]},
            {"_id": 0, "id": 1, "company": 1, "full_name": 1, "whatsapp_number": 1, "phone": 1, "email": 1}).limit(2000)]
        liens = {l["tenant_id"]: l async for l in db.requetes_liens.find({"actif": True}, {"_id": 0})}
        sortie = []
        for c in clients:
            l = liens.get(c["id"])
            sortie.append({"id": c["id"], "nom": c.get("company") or c.get("full_name") or c["id"],
                           "whatsapp": c.get("whatsapp_number") or c.get("phone") or "", "email": c.get("email") or "",
                           "url": url_lien(base, l["jeton"]) if l else None,
                           "envoye_le": (l or {}).get("envoye_le")})
        sortie.sort(key=lambda x: x["nom"].lower())
        return {"clients": sortie}

    @api.post("/admin/requetes-liens", tags=["Requêtes clients"])
    async def envoyer_lien(corps: dict, user: dict = Depends(get_current_user)):
        """Crée (ou renouvelle) le lien personnel d'un client et l'envoie par WhatsApp et e-mail si demandé."""
        _admin(user)
        corps = corps or {}
        tenant_id = str(corps.get("tenant_id") or "")
        client = await _client_doc(tenant_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client introuvable")
        lien = await _lien(tenant_id, user.get("full_name") or "", renouveler=bool(corps.get("renouveler")))
        url = url_lien(base, lien["jeton"])
        envoye = {"whatsapp": False, "email": False}
        if corps.get("envoyer", True):
            texte = message_lien(client.get("company") or client.get("full_name") or "", url)
            numero = str(corps.get("numero") or client.get("whatsapp_number") or client.get("phone") or "").strip()
            if numero:   # lot 86.2 : modèle « lien » (bouton « Ouvrir mes requêtes »), sinon message libre
                mode = await _envoyer_wa(numero, MODELE_LIEN, client.get("company") or client.get("full_name") or "",
                                         lien["jeton"], texte)
                envoye["whatsapp"] = bool(mode)
                envoye["mode"] = mode
            if send_email and client.get("email"):
                try:
                    await send_email(client["email"], "SAWALI — votre lien pour nous soumettre vos requêtes",
                                     f"<p>{texte.replace(chr(10), '<br>')}</p><p><a href=\"{url}\">{url}</a></p>", texte)
                    envoye["email"] = True
                except Exception:  # noqa: BLE001
                    logger.warning("[requetes] lien non envoyé par e-mail", exc_info=True)
            if envoye["whatsapp"] or envoye["email"]:
                await db.requetes_liens.update_one({"jeton": lien["jeton"]}, {"$set": {"envoye_le": _maintenant()}})
        return {"url": url, "envoye": envoye}

    # ------------------------------------------------------------------ modèles WhatsApp Meta (lot 86.2)
    async def _meta() -> tuple:
        """Jeton et compte WhatsApp Business (WABA) de SAWALI ; HTTPException si WhatsApp n'est pas configuré."""
        g = await db.settings.find_one({"_id": "global"}) or {}
        jeton, waba = (g.get("wa_access_token") or "").strip(), (g.get("wa_business_account_id") or "").strip()
        if not jeton or not waba:
            raise HTTPException(status_code=400, detail="WhatsApp non configuré (WABA ID et Access Token dans les Paramètres)")
        return jeton, waba

    def _client_http():
        if meta_http:
            return meta_http()
        import httpx
        return httpx.AsyncClient(timeout=15)

    @api.get("/admin/requetes-modeles-meta", tags=["Requêtes clients"])
    async def etat_modeles(user: dict = Depends(get_current_user)):
        """État des deux modèles chez Meta : absent, PENDING (en revue), APPROVED, REJECTED…"""
        _admin(user)
        jeton, waba = await _meta()
        etats = {}
        async with _client_http() as http:
            for d in definitions_modeles(base):
                rep = await http.get(f"https://graph.facebook.com/v21.0/{waba}/message_templates",
                                     params={"name": d["name"], "fields": "name,status,language,rejected_reason"},
                                     headers={"Authorization": f"Bearer {jeton}"})
                donnees = (rep.json() or {}).get("data") if rep.status_code < 300 else None
                trouve = next((m for m in donnees or [] if m.get("language") == LANGUE_MODELES), None)
                etats[d["name"]] = (trouve or {}).get("status") or ("ABSENT" if donnees is not None else "INCONNU")
        return {"modeles": [{"nom": d["name"], "etat": etats[d["name"]],
                             "texte": d["components"][0]["text"]} for d in definitions_modeles(base)]}

    @api.post("/admin/requetes-modeles-meta", tags=["Requêtes clients"])
    async def creer_modeles(user: dict = Depends(get_current_user)):
        """Soumet les deux modèles à Meta (approbation en général en quelques minutes). Déjà existant = sans effet."""
        _admin(user)
        jeton, waba = await _meta()
        resultats = []
        async with _client_http() as http:
            for d in definitions_modeles(base):
                rep = await http.post(f"https://graph.facebook.com/v21.0/{waba}/message_templates", json=d,
                                      headers={"Authorization": f"Bearer {jeton}", "Content-Type": "application/json"})
                try:
                    brut = rep.json()
                except Exception:  # noqa: BLE001
                    brut = {}
                if rep.status_code < 300:
                    resultats.append({"nom": d["name"], "ok": True, "etat": brut.get("status") or "PENDING"})
                else:
                    msg = ((brut.get("error") or {}).get("error_user_msg") or (brut.get("error") or {}).get("message")
                           or f"HTTP {rep.status_code}")
                    existe = "already" in msg.lower() or "existe" in msg.lower()
                    resultats.append({"nom": d["name"], "ok": existe, "etat": "EXISTANT" if existe else "ERREUR", "erreur": None if existe else msg})
        return {"resultats": resultats}

    @api.delete("/admin/requetes-liens/{tenant_id}", tags=["Requêtes clients"])
    async def revoquer_lien(tenant_id: str, user: dict = Depends(get_current_user)):
        """Révoque le lien personnel d'un client (l'ancien lien ne fonctionne plus)."""
        _admin(user)
        res = await db.requetes_liens.update_many({"tenant_id": tenant_id, "actif": True},
                                                  {"$set": {"actif": False, "revoque_le": _maintenant()}})
        return {"ok": True, "revoques": res.modified_count}

    @api.get("/admin/requetes", tags=["Requêtes clients"])
    async def toutes(etat: str = "", tenant_id: str = "", lot_id: str = "", user: dict = Depends(get_current_user)):
        """Requêtes de tous les clients (filtres : état, client, lot)."""
        _admin(user)
        filtre: Dict[str, Any] = {}
        if etat:
            filtre["etat"] = etat
        if tenant_id:
            filtre["tenant_id"] = tenant_id
        if lot_id:
            filtre["lot_id"] = None if lot_id == "aucun" else lot_id
        lignes = [r async for r in db.requetes_clients.find(filtre, {"_id": 0}).sort("cree_le", -1).limit(1000)]
        tous = [r async for r in db.requetes_clients.find({}, {"_id": 0, "etat": 1, "evaluation": 1, "a_evaluer": 1})]
        clients = sorted({(r["tenant_id"], r.get("client_nom") or "") for r in lignes}, key=lambda x: x[1])
        return {"requetes": [_public(r) for r in lignes], "resume": resume(tous), "etats": ETATS,
                "categories": CATEGORIES, "clients": [{"id": i, "nom": n} for i, n in clients]}

    @api.patch("/admin/requetes/{req_id}", tags=["Requêtes clients"])
    async def traiter(req_id: str, corps: dict, user: dict = Depends(get_current_user)):
        """Observation datée, changement d'état, rangement dans un lot."""
        _admin(user)
        r = await db.requetes_clients.find_one({"id": req_id}, {"_id": 0})
        if not r:
            raise HTTPException(status_code=404, detail="Requête introuvable")
        corps = corps or {}
        maintenant, par = _maintenant(), user.get("full_name") or user.get("email")
        maj: Dict[str, Any] = {}
        pousser: Dict[str, Any] = {}
        obs = str(corps.get("observation") or "").strip()[:3000]
        if obs:
            pousser["observations"] = {"texte": obs, "le": maintenant, "par": par}
        etat = corps.get("etat")
        if etat and etat != r.get("etat"):
            if etat not in ETATS:
                raise HTTPException(status_code=422, detail="État inconnu")
            maj["etat"] = etat
            pousser["historique"] = {"etat": etat, "le": maintenant, "par": par}
            if etat in ETATS_A_EVALUER and not r.get("evaluation"):
                maj["a_evaluer"] = True
        if "lot_id" in corps:
            lot_id = corps.get("lot_id") or None
            lot = await db.requetes_lots.find_one({"id": lot_id}, {"_id": 0}) if lot_id else None
            if lot_id and not lot:
                raise HTTPException(status_code=404, detail="Lot introuvable")
            maj.update(lot_id=lot_id, lot_numero=(lot or {}).get("numero"))
        if not maj and not pousser:
            return _public(r)
        operation: Dict[str, Any] = {}
        if maj:
            operation["$set"] = maj
        if pousser:
            operation["$push"] = pousser
        await db.requetes_clients.update_one({"id": req_id}, operation)
        if maj.get("a_evaluer"):
            await _prevenir_client(r["tenant_id"],
                                   f"SAWALI : votre requête {r['numero']} est « {ETATS[etat]} ». Merci de l'évaluer "
                                   f"dans votre espace SAWALI → Mes requêtes.", f"Requête {r['numero']} : {ETATS[etat]}")
        return _public(await db.requetes_clients.find_one({"id": req_id}, {"_id": 0}))

    @api.get("/admin/requetes-lots", tags=["Requêtes clients"])
    async def lots(user: dict = Depends(get_current_user)):
        """Lots de correction, avec le nombre de requêtes de chacun."""
        _admin(user)
        sortie = []
        async for lot in db.requetes_lots.find({}, {"_id": 0}).sort("numero", -1):
            lot["requetes"] = await db.requetes_clients.count_documents({"lot_id": lot["id"]})
            lot["libelle_etat"] = ETATS_LOT.get(lot.get("etat"), lot.get("etat"))
            sortie.append(lot)
        return {"lots": sortie, "etats": ETATS_LOT}

    @api.post("/admin/requetes-lots", tags=["Requêtes clients"])
    async def nouveau_lot(corps: dict, user: dict = Depends(get_current_user)):
        """Nouveau lot (numéro automatique)."""
        _admin(user)
        titre = str((corps or {}).get("titre") or "").strip()[:160]
        if not titre:
            raise HTTPException(status_code=422, detail="Donnez un titre au lot")
        doc = await db.counters.find_one_and_update({"_id": "requetes_lots"}, {"$inc": {"seq": 1}},
                                                    upsert=True, return_document=True)
        lot = {"id": str(uuid.uuid4()), "numero": (doc or {}).get("seq") or 1, "titre": titre,
               "description": str((corps or {}).get("description") or "").strip()[:2000], "etat": "ouvert",
               "cree_le": _maintenant(), "deploye_le": None}
        await db.requetes_lots.insert_one(dict(lot))
        return lot

    @api.patch("/admin/requetes-lots/{lot_id}", tags=["Requêtes clients"])
    async def maj_lot(lot_id: str, corps: dict, user: dict = Depends(get_current_user)):
        """Titre / état du lot. « Déployé » : toutes ses requêtes passent à « Déployée » et les clients sont prévenus."""
        _admin(user)
        lot = await db.requetes_lots.find_one({"id": lot_id}, {"_id": 0})
        if not lot:
            raise HTTPException(status_code=404, detail="Lot introuvable")
        corps = corps or {}
        maj: Dict[str, Any] = {}
        if corps.get("titre"):
            maj["titre"] = str(corps["titre"]).strip()[:160]
        etat = corps.get("etat")
        prevenus = 0
        if etat and etat != lot.get("etat"):
            if etat not in ETATS_LOT:
                raise HTTPException(status_code=422, detail="État de lot inconnu")
            maj["etat"] = etat
            if etat == "deploye":
                maintenant, par = _maintenant(), user.get("full_name") or user.get("email")
                maj["deploye_le"] = maintenant
                requetes = [r async for r in db.requetes_clients.find(
                    {"lot_id": lot_id, "etat": {"$nin": ["deployee", "rejetee"]}}, {"_id": 0})]
                for r in requetes:
                    await db.requetes_clients.update_one({"id": r["id"]}, {
                        "$set": {"etat": "deployee", "a_evaluer": not r.get("evaluation")},
                        "$push": {"historique": {"etat": "deployee", "le": maintenant, "par": par,
                                                 "lot": lot["numero"]}}})
                # Un message par client : ses requêtes déployées dans ce lot
                par_client: Dict[str, List[str]] = {}
                for r in requetes:
                    par_client.setdefault(r["tenant_id"], []).append(r["numero"])
                for tenant_id, numeros in par_client.items():
                    await _prevenir_client(
                        tenant_id,
                        f"SAWALI : le lot {lot['numero']} « {lot['titre']} » est déployé. Vos requêtes "
                        f"{', '.join(numeros)} sont traitées. Merci de les évaluer dans votre espace SAWALI → Mes requêtes.",
                        f"Lot {lot['numero']} déployé — merci d'évaluer vos requêtes")
                    prevenus += 1
        if maj:
            await db.requetes_lots.update_one({"id": lot_id}, {"$set": maj})
        return {**lot, **maj, "clients_prevenus": prevenus}
