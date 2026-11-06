"""Lot 371 — Formulaire public « Spécifications de votre automate » (aux couleurs d'une clinique).

DEMANDE DU PROPRIÉTAIRE (06/11/2026)
   Pour relier un automate de laboratoire à Loois, il faut connaître son interface (série, USB ou réseau), son protocole (ASTM, HL7,
   propriétaire), les tests et leurs codes, la documentation du constructeur… Au lieu de construire « à l'aveugle », le propriétaire envoie
   un LIEN PUBLIC aux propriétaires et fournisseurs d'automates. Le formulaire porte le LOGO et le NOM de la clinique qui demande ces
   informations, et accepte les documents (PDF…).

POUR UN DÉVELOPPEUR WINDEV
   Rien de nouveau côté données : le formulaire est un formulaire ORDINAIRE du moteur existant (collection `forms`, réponses dans
   `form_submissions`, fichiers dans `files`) créé à partir d'un MODÈLE écrit ici (pages et champs à identifiants stables). Il porte en plus :
     - `modele` = « automate » (pour le retrouver) ;
     - `branding` = {organisation, logo_url, message} : l'identité de la clinique, affichée en tête de la page publique.
   AUCUNE nouvelle collection (cluster MongoDB plein).

ROUTES (sous /api)
   Administrateur / superviseur :
     GET    /admin/formulaire-automates                  — les formulaires créés (un par clinique), liens, nombre de réponses
     POST   /admin/formulaire-automates                  — crée un formulaire pour une clinique {organisation, logo_url?, message?}
     PUT    /admin/formulaire-automates/{id}             — change nom, logo, message, public / privé
     POST   /admin/formulaire-automates/logo             — envoie le logo (image ≤ 1 Mo) → adresse à utiliser
     GET    /admin/formulaire-automates/{id}/reponses    — réponses résumées (format=csv : toutes les colonnes)
   Public (sans connexion) :
     GET    /public/forms/{id}/identite                  — logo, nom de la clinique et message (404 si le formulaire n'est pas public)
     POST   /public/forms/{id}/upload                    — dépose un document dans un champ « fichier » du formulaire

PROTECTIONS DU DÉPÔT PUBLIC DE FICHIERS
   - seulement dans un formulaire PUBLIC qui possède un champ « fichier » ; extensions autorisées uniquement (pas de HTML ni de SVG) ;
   - le CONTENU doit correspondre à l'extension (PDF = « %PDF », Word / Excel / ZIP, images, texte sans octets nuls) ;
   - 15 Mo au plus par fichier ; 20 dépôts par heure et par adresse IP (mémoire du serveur).
"""
from __future__ import annotations

import csv
import io
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.formulaire_automates")

MODELE = "automate"
TAILLE_MAX_FICHIER = 15 * 1024 * 1024         # documents des constructeurs : manuels de plusieurs Mo
TAILLE_MAX_LOGO = 1024 * 1024
EXTENSIONS_DOCUMENTS = {"pdf", "doc", "docx", "xls", "xlsx", "txt", "csv", "zip", "png", "jpg", "jpeg", "webp"}
EXTENSIONS_LOGO = {"png", "jpg", "jpeg", "webp"}
DEPOTS_PAR_HEURE = 20
FENETRE_S = 3600
_ZIP = b"PK\x03\x04"
_OLE = b"\xd0\xcf\x11\xe0"


# ---------------------------------------------------------------------------------------------------- modèle du formulaire

def _c(id_: str, type_: str, label: str, *, req: bool = False, options: Optional[List[str]] = None, placeholder: Optional[str] = None,
       accept: Optional[str] = None) -> Dict[str, Any]:
    """Un champ du modèle (identifiant STABLE : les réponses s'y rattachent)."""
    champ: Dict[str, Any] = {"id": id_, "type": type_, "label": label, "required": req, "col_start": 1, "col_span": 12, "row": 0}
    if options is not None:
        champ["options"] = options
    if placeholder:
        champ["placeholder"] = placeholder
    if accept:
        champ["accept"] = accept
    return champ


JE_NE_SAIS_PAS = "Je ne sais pas"


def pages_modele() -> List[Dict[str, Any]]:
    """Pages et champs du formulaire : tout ce qu'il faut savoir pour relier un automate sans deviner."""
    pages = [
        {"id": "pg_structure", "title": "1. Vous et votre structure", "fields": [
            _c("f_role", "select", "Vous êtes", req=True, options=[
                "Propriétaire ou responsable du laboratoire", "Fournisseur / revendeur de l'automate", "Technicien / ingénieur biomédical", "Représentant du constructeur"]),
            _c("f_fournisseur", "text", "Nom du fournisseur ou du revendeur de l'automate", req=True, placeholder="Société qui a vendu ou installé l'automate"),
            _c("f_contact_nom", "text", "Nom et prénom de la personne à contacter", req=True),
            _c("f_contact_fonction", "text", "Sa fonction"),
            _c("f_contact_tel", "tel", "Téléphone / WhatsApp de cette personne", req=True, placeholder="+226 …"),
            _c("f_contact_email", "email", "E-mail de cette personne", req=True),
            _c("f_pays_ville", "text", "Pays et ville"),
            _c("f_aide_distance", "select", "Pouvez-vous nous aider à distance (appel, visio, WhatsApp) ?", options=["Oui", "Non", "Sur rendez-vous"]),
        ]},
        {"id": "pg_automate", "title": "2. Votre automate", "fields": [
            _c("f_constructeur", "text", "Marque / constructeur", req=True, placeholder="ex. Sun, Mindray, Sysmex, Spinreact…"),
            _c("f_modele", "text", "Modèle exact de l'automate", req=True, placeholder="ex. SPIN 200E, MAGLUMI X8, BS-430"),
            _c("f_numero_serie", "text", "Numéro de série (facultatif)"),
            _c("f_domaine", "multiselect", "Type d'analyses", options=[
                "Biochimie", "Hématologie", "Hémostase / coagulation", "Immunologie / immunoanalyse", "Ionogramme / électrolytes", "Urines",
                "Gaz du sang", "Sérologie / ELISA", "Microbiologie", "Autre"]),
            _c("f_version_logiciel", "text", "Version du logiciel de l'automate (écran « À propos »)"),
            _c("f_deja_lis", "select", "L'automate est-il déjà relié à un logiciel de laboratoire ?", options=[
                "Oui, il l'est actuellement", "Il l'a été par le passé", "Non, jamais", JE_NE_SAIS_PAS]),
            _c("f_lis_nom", "text", "Si oui : nom du logiciel et de son éditeur"),
            _c("f_option_interface", "select", "L'option « interface LIS / communication » est-elle activée sur l'automate ?", options=[
                "Oui", "Non (option payante à activer)", JE_NE_SAIS_PAS]),
        ]},
        {"id": "pg_connexion", "title": "3. Branchement à l'ordinateur", "fields": [
            _c("f_interface", "multiselect", "Quels types de connexion l'automate propose-t-il ? (plusieurs choix possibles)", req=True, options=[
                "Port série (RS-232, connecteur DB9)", "USB", "Réseau Ethernet (prise RJ45, TCP/IP)", "Wi-Fi", "Fichier / clé USB (export)", "Autre", JE_NE_SAIS_PAS]),
            _c("f_connecteur", "text", "Connecteurs visibles à l'arrière de l'automate", placeholder="ex. 1 prise RJ45, 1 port DB9, 2 USB"),
            _c("f_serie_reglages", "text", "Si port série : réglages (vitesse en bauds, bits de données, parité, bit d'arrêt)", placeholder="ex. 9600, 8 bits, aucune parité, 1 bit d'arrêt"),
            _c("f_usb_mode", "select", "Si USB : comment l'automate apparaît-il sur l'ordinateur ?", options=[
                "Comme un port COM (série virtuel)", "Comme un disque / une clé USB", "Avec un pilote spécifique du constructeur", JE_NE_SAIS_PAS, "Sans objet"]),
            _c("f_reseau_role", "select", "Si réseau : qui se connecte à qui ?", options=[
                "L'automate se connecte au logiciel du laboratoire (l'automate est le « client »)",
                "Le logiciel du laboratoire se connecte à l'automate (l'automate est le « serveur »)", JE_NE_SAIS_PAS, "Sans objet"]),
            _c("f_reseau_adresse", "text", "Si réseau : adresse IP de l'automate et numéro de port", placeholder="ex. 192.168.1.50 — port 5000"),
            _c("f_ordinateur", "select", "Système de l'ordinateur situé près de l'automate", options=[
                "Windows 10", "Windows 11", "Windows 7 ou 8", "Windows Server", "Autre / " + JE_NE_SAIS_PAS.lower()]),
            _c("f_cable", "select", "Le câble ou l'adaptateur nécessaire est-il disponible ?", options=[
                "Oui, câble série", "Oui, câble réseau", "Oui, adaptateur USB-série", "Non, il faut l'acheter", JE_NE_SAIS_PAS]),
        ]},
        {"id": "pg_protocole", "title": "4. Protocole et échanges", "fields": [
            _c("f_protocole", "select", "Protocole de communication de l'automate", req=True, options=[
                "ASTM (LIS2-A2 / E1394)", "HL7 (version 2.x)", "Protocole propre au constructeur (trames avec caractères de début et de fin)",
                "POCT1-A", "Fichier texte / CSV", JE_NE_SAIS_PAS]),
            _c("f_sens", "select", "Sens des échanges", req=True, options=[
                "Envoi des résultats seulement", "Bidirectionnel : l'automate demande au logiciel les tests à faire, puis envoie les résultats", JE_NE_SAIS_PAS]),
            _c("f_identifiant", "select", "Comment l'automate lit-il l'identifiant de l'échantillon ?", options=[
                "Lecteur de code-barres intégré", "Saisie manuelle sur l'automate", "Les deux", JE_NE_SAIS_PAS]),
            _c("f_codebarres", "multiselect", "Types de code-barres lus", options=[
                "Code 128", "Code 39", "Codabar", "ITF (2 parmi 5)", "EAN-13", "QR code / Data Matrix", "Autre / " + JE_NE_SAIS_PAS.lower()]),
            _c("f_id_longueur", "number", "Longueur maximale de l'identifiant d'échantillon (en caractères)"),
            _c("f_tests", "textarea", "Liste des tests / paramètres de l'automate, avec leur code ou leur abréviation exacts", req=True,
               placeholder="ex. GLU = glycémie, TSH = thyréostimuline, PT = temps de Quick…"),
            _c("f_unites", "textarea", "Unités et formats particuliers des résultats (virgule ou point, unités…)"),
            _c("f_controle_qualite", "select", "L'automate envoie-t-il aussi les contrôles qualité ?", options=["Oui", "Non", JE_NE_SAIS_PAS]),
            _c("f_exemple", "textarea", "Exemple de message envoyé par l'automate (si vous en avez un)"),
        ]},
        {"id": "pg_documents", "title": "5. Documents", "fields": [
            _c("f_doc_lis", "file", "Documentation d'interface LIS du constructeur (PDF)", accept=".pdf,.doc,.docx"),
            _c("f_doc_manuel", "file", "Manuel d'utilisation de l'automate", accept=".pdf,.doc,.docx"),
            _c("f_doc_exemples", "file", "Exemples de messages (fichier texte) ou captures d'écran des réglages « LIS » de l'automate",
               accept=".txt,.csv,.pdf,.png,.jpg,.jpeg,.zip"),
            _c("f_photo_ports", "file", "Photo de l'arrière de l'automate (prises de connexion)", accept=".png,.jpg,.jpeg,.webp"),
            _c("f_lien_documents", "url", "Lien de téléchargement des documents (si les fichiers sont trop gros)"),
            _c("f_support_constructeur", "text", "Contact du support technique du constructeur (nom, e-mail, téléphone)"),
        ]},
        {"id": "pg_fin", "title": "6. Pour finir", "fields": [
            _c("f_remarques", "textarea", "Contraintes ou remarques (accès à l'automate, horaires, limites connues)"),
            _c("f_essai", "text", "Quand un essai sur place est-il possible ?"),
            _c("f_accord", "boolean", "J'accepte que ces informations servent à relier cet automate au logiciel du laboratoire", req=True),
        ]},
    ]
    for page in pages:
        for ligne, champ in enumerate(page["fields"]):
            champ["row"] = ligne
    return pages


def description_formulaire(organisation: str, message: str) -> str:
    """Texte d'accueil : qui demande, pourquoi, comment répondre."""
    base = (f"{organisation} prépare la connexion de ses automates de laboratoire à son logiciel. "
            "Merci de remplir ce formulaire : plus vos réponses sont précises, plus la mise en route sera rapide et sûre. "
            "Les champs marqués d'une étoile sont obligatoires ; si vous ne savez pas, répondez « Je ne sais pas » ou laissez le champ vide. "
            "Vous pouvez joindre les documents du constructeur (page 5).")
    return f"{message.strip()}\n\n{base}" if message.strip() else base


# ---------------------------------------------------------------------------------------------------- logique pure (testée)

def nettoyer_identite(organisation: str, logo_url: Optional[str], message: Optional[str]) -> Dict[str, str]:
    """Identité de la clinique : nom (1 à 120 caractères), logo (adresse https ou /api/files/…) et message facultatif. 422 si invalide."""
    org = re.sub(r"\s+", " ", organisation or "").strip()
    if not org or len(org) > 120:
        raise HTTPException(status_code=422, detail="Nom de la clinique : 1 à 120 caractères")
    logo = (logo_url or "").strip()
    if logo and not (logo.startswith("https://") or logo.startswith("/api/files/")) or len(logo) > 500 or any(c in logo for c in ' "<>\n\r\t\'\\'):
        raise HTTPException(status_code=422, detail="Adresse du logo non valable : envoyez l'image avec le bouton « Choisir le logo »")
    msg = (message or "").strip()
    if len(msg) > 600:
        raise HTTPException(status_code=422, detail="Message d'accueil : 600 caractères au plus")
    return {"organisation": org, "logo_url": logo, "message": msg}


def contenu_conforme(extension: str, brut: bytes) -> bool:
    """Le contenu correspond-il à l'extension ? (empêche de déposer un programme ou une page web sous un faux nom)"""
    ext = extension.lower()
    tete = brut[:16]
    if ext == "pdf":
        return brut[:5] == b"%PDF-"
    if ext == "png":
        return tete[:8] == b"\x89PNG\r\n\x1a\n"
    if ext in ("jpg", "jpeg"):
        return tete[:3] == b"\xff\xd8\xff"
    if ext == "webp":
        return tete[:4] == b"RIFF" and tete[8:12] == b"WEBP"
    if ext in ("docx", "xlsx", "zip"):
        return tete[:4] == _ZIP
    if ext in ("doc", "xls"):
        return tete[:4] == _OLE or tete[:4] == _ZIP
    if ext in ("txt", "csv"):
        return b"\x00" not in brut[:8192]
    return False


def lignes_reponses(form: dict, soumissions: List[dict]) -> List[Dict[str, Any]]:
    """Une ligne par réponse : valeurs lisibles de chaque champ (selon le formulaire tel qu'il est), documents en liens."""
    champs = [f for p in form.get("pages", []) for f in p.get("fields", [])]
    lignes = []
    for s in soumissions:
        data = s.get("data") or {}
        valeurs: Dict[str, Any] = {}
        documents: List[Dict[str, str]] = []
        for f in champs:
            v = data.get(f["id"])
            if isinstance(v, dict) and v.get("public_url"):
                documents.append({"champ": f["label"], "nom": v.get("filename") or "Fichier", "url": v["public_url"]})
                valeurs[f["id"]] = v["public_url"]
            elif isinstance(v, list):
                valeurs[f["id"]] = "; ".join(str(x) for x in v)
            elif isinstance(v, bool):
                valeurs[f["id"]] = "Oui" if v else "Non"
            else:
                valeurs[f["id"]] = "" if v is None else str(v)
        lignes.append({"id": s.get("id"), "date": s.get("created_at"), "repondant": s.get("user_label") or "", "email": s.get("respondent_email") or "",
                       "valeurs": valeurs, "documents": documents})
    return lignes


def export_csv(form: dict, lignes: List[Dict[str, Any]]) -> str:
    """CSV (séparateur « ; », UTF-8 avec BOM pour Excel) : date, répondant, puis une colonne par champ du formulaire."""
    champs = [f for p in form.get("pages", []) for f in p.get("fields", [])]
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";", lineterminator="\r\n")
    w.writerow(["Date", "Répondant", "E-mail"] + [f["label"] for f in champs])
    for l in lignes:
        w.writerow([str(l["date"] or "")[:19], l["repondant"], l["email"]] + [str(l["valeurs"].get(f["id"], "")).replace("\r", " ").replace("\n", " ") for f in champs])
    return "﻿" + sortie.getvalue()


# ---------------------------------------------------------------------------------------------------- routes

class IdentiteCreation(BaseModel):
    organisation: str = Field(min_length=1, max_length=200)
    logo_url: Optional[str] = None
    message: Optional[str] = None


class IdentiteModification(BaseModel):
    organisation: Optional[str] = Field(default=None, max_length=200)
    logo_url: Optional[str] = None
    message: Optional[str] = None
    is_public: Optional[bool] = None


def attach_formulaire_automates_routes(api: APIRouter | FastAPI, *, db, helpers: Dict[str, Any]) -> None:
    """Branche les routes. `helpers` : get_current_user, _uuid, _now, public_base_url(request), client_ip(request), upload_dir,
    fonction_active_pour_compte(compte_id, cle) (async)."""
    get_current_user = helpers["get_current_user"]
    nouvel_id = helpers["_uuid"]
    maintenant = helpers["_now"]
    base_publique = helpers["public_base_url"]
    ip_client = helpers["client_ip"]
    upload_dir = Path(helpers["upload_dir"])
    fonction_active = helpers["fonction_active_pour_compte"]
    depots: Dict[str, List[float]] = {}

    def exiger_admin(user: dict) -> None:
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    def limiter(request: Request) -> None:
        """20 dépôts par heure et par adresse IP : un robot ne peut pas remplir le stockage."""
        ip = ip_client(request) or "?"
        t = time.monotonic()
        recents = [x for x in depots.get(ip, []) if t - x < FENETRE_S]
        if len(recents) >= DEPOTS_PAR_HEURE:
            depots[ip] = recents
            raise HTTPException(status_code=429, detail="Trop de documents envoyés depuis cette adresse : réessayez dans une heure")
        recents.append(t)
        depots[ip] = recents
        if len(depots) > 5000:
            for cle in [k for k, v in depots.items() if not v or t - v[-1] >= FENETRE_S]:
                depots.pop(cle, None)

    def lien_public(request: Request, form_id: str) -> str:
        return f"{(base_publique(request) or str(request.base_url)).rstrip('/')}/f/{form_id}"

    async def enregistrer_fichier(request: Request, donnees: bytes, nom_original: str, extension: str, type_mime: str, contexte: str, form_id: Optional[str],
                                  par: Optional[dict]) -> Dict[str, Any]:
        """Range le fichier (stockage + cache local) et sa fiche dans `files` (servie ensuite par /api/files/{id}.{ext})."""
        from storage import asave_upload_and_cache  # dans un thread, sans figer le serveur
        file_id = nouvel_id()
        nom_stocke = f"{file_id}.{extension}"
        _cible, chemin_stockage, erreur = await asave_upload_and_cache(upload_dir=upload_dir, filename=nom_stocke, data=donnees, content_type=type_mime)
        if erreur:
            logger.warning("[formulaire_automates] miroir de stockage en échec : %s", erreur)
        chemin_public = f"/api/files/{file_id}.{extension}"
        url = f"{(base_publique(request) or str(request.base_url)).rstrip('/')}{chemin_public}"
        await db.files.insert_one({
            "id": file_id, "filename": nom_original, "stored_name": nom_stocke, "extension": extension, "content_type": type_mime, "size": len(donnees),
            "url": chemin_public, "public_url": url, "uploaded_at": maintenant(), "uploaded_by_id": (par or {}).get("id"), "uploaded_by_email": (par or {}).get("email"),
            "uploaded_from_ip": ip_client(request), "context": contexte, "form_id": form_id, "storage_path": chemin_stockage, "storage_error": erreur,
        })
        return {"file_id": file_id, "filename": nom_original, "size": len(donnees), "content_type": type_mime, "public_url": url}

    async def lire_fichier(fichier: UploadFile, extensions: set, taille_max: int) -> tuple:
        brut = await fichier.read()
        if not brut:
            raise HTTPException(status_code=400, detail="Fichier vide")
        if len(brut) > taille_max:
            raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {taille_max // (1024 * 1024)} Mo)")
        nom = (fichier.filename or "fichier").strip()[:200]
        ext = nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
        if ext not in extensions:
            raise HTTPException(status_code=415, detail="Type de fichier non accepté (autorisés : " + ", ".join(sorted(extensions)) + ")")
        if not contenu_conforme(ext, brut):
            raise HTTPException(status_code=415, detail="Le contenu du fichier ne correspond pas à son extension")
        return brut, nom, ext

    # ---------------------------------------------------------------- public

    async def formulaire_public(form_id: str) -> dict:
        form = await db.forms.find_one({"id": form_id, "is_public": True}, {"_id": 0, "id": 1, "client_id": 1, "pages": 1, "branding": 1, "modele": 1})
        if not form or not await fonction_active(form.get("client_id"), "forms_surveys"):
            raise HTTPException(status_code=404, detail="Formulaire introuvable ou non public")
        return form

    @api.get("/public/forms/{form_id}/identite", tags=["Public"])
    async def identite_publique(form_id: str):
        """Logo, nom de la clinique et message d'accueil d'un formulaire public (vide si le formulaire n'en a pas)."""
        form = await formulaire_public(form_id)
        b = form.get("branding") or {}
        return {"organisation": b.get("organisation") or "", "logo_url": b.get("logo_url") or "", "message": b.get("message") or "", "modele": form.get("modele") or ""}

    @api.post("/public/forms/{form_id}/upload", tags=["Public"])
    async def depot_public(form_id: str, request: Request, file: UploadFile = File(...)):
        """Dépose un document dans un champ « fichier » d'un formulaire public (voir les protections en tête de ce module)."""
        limiter(request)
        form = await formulaire_public(form_id)
        if not any(f.get("type") == "file" for p in form.get("pages", []) for f in p.get("fields", [])):
            raise HTTPException(status_code=400, detail="Ce formulaire n'accepte pas de fichier")
        brut, nom, ext = await lire_fichier(file, EXTENSIONS_DOCUMENTS, TAILLE_MAX_FICHIER)
        type_mime = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "txt": "text/plain",
                     "csv": "text/csv", "zip": "application/zip"}.get(ext, "application/octet-stream")
        res = await enregistrer_fichier(request, brut, nom, ext, type_mime, "form_public_attachment", form_id, None)
        return {"ok": True, **res}

    # ---------------------------------------------------------------- administrateur

    def vue(form: dict, request: Request) -> dict:
        return {"id": form["id"], "number": form.get("number"), "title": form.get("title"), "branding": form.get("branding") or {}, "is_public": bool(form.get("is_public")),
                "reponses": form.get("uses_count") or 0, "created_at": form.get("created_at"), "lien": lien_public(request, form["id"])}

    @api.get("/admin/formulaire-automates", tags=["Formulaire automates"])
    async def lister(request: Request, user: dict = Depends(get_current_user)):
        exiger_admin(user)
        formes = await db.forms.find({"modele": MODELE}, {"_id": 0, "pages": 0}).sort("created_at", -1).to_list(200)
        return {"formulaires": [vue(f, request) for f in formes]}

    @api.post("/admin/formulaire-automates/logo", tags=["Formulaire automates"])
    async def envoyer_logo(request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
        """Envoie le logo de la clinique (PNG, JPEG ou WebP, 1 Mo au plus) et renvoie l'adresse à enregistrer."""
        exiger_admin(user)
        brut, nom, ext = await lire_fichier(file, EXTENSIONS_LOGO, TAILLE_MAX_LOGO)
        type_mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}[ext]
        res = await enregistrer_fichier(request, brut, nom, ext, type_mime, "form_logo", None, user)
        return {"ok": True, "logo_url": res["public_url"]}

    @api.post("/admin/formulaire-automates", tags=["Formulaire automates"])
    async def creer(payload: IdentiteCreation, request: Request, user: dict = Depends(get_current_user)):
        """Crée le formulaire « Spécifications de votre automate » pour une clinique (public dès la création)."""
        exiger_admin(user)
        identite = nettoyer_identite(payload.organisation, payload.logo_url, payload.message)
        titre = f"Spécifications de votre automate — {identite['organisation']}"
        if await db.forms.find_one({"modele": MODELE, "title": {"$regex": f"^{re.escape(titre)}$", "$options": "i"}}, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=409, detail="Un formulaire existe déjà pour cette clinique : modifiez-le au lieu d'en créer un second")
        client = await db.users.find_one({"id": user["id"]}, {"_id": 0, "client_code": 1, "company": 1, "full_name": 1})
        brut = (client or {}).get("client_code") or re.sub(r"[^A-Z0-9]", "", ((client or {}).get("company") or (client or {}).get("full_name") or "X").upper())[:6] or "X"
        compteur = await db.counters.find_one_and_update({"_id": f"form_{brut}"}, {"$inc": {"value": 1}}, upsert=True, return_document=True)
        numero = (compteur or {}).get("value", 1)
        doc = {
            "id": nouvel_id(), "client_id": user["id"], "client_code": brut, "number": f"FORM-{brut}-{numero:04d}", "title": titre,
            "description": description_formulaire(identite["organisation"], identite["message"]), "is_public": True, "category_id": None, "access_client_ids": [],
            "pages": pages_modele(), "modele": MODELE, "branding": identite,
            "created_by_id": user["id"], "created_by_label": user.get("full_name") or user.get("email"), "created_at": maintenant(), "updated_at": maintenant(), "uses_count": 0,
        }
        await db.forms.insert_one(doc.copy())
        logger.info("[formulaire_automates] formulaire créé pour « %s » par %s", identite["organisation"], user.get("id"))
        return vue(doc, request)

    @api.put("/admin/formulaire-automates/{form_id}", tags=["Formulaire automates"])
    async def modifier(form_id: str, payload: IdentiteModification, request: Request, user: dict = Depends(get_current_user)):
        exiger_admin(user)
        form = await db.forms.find_one({"id": form_id, "modele": MODELE}, {"_id": 0})
        if not form:
            raise HTTPException(status_code=404, detail="Formulaire introuvable")
        actuel = form.get("branding") or {}
        identite = nettoyer_identite(payload.organisation if payload.organisation is not None else actuel.get("organisation", ""),
                                     payload.logo_url if payload.logo_url is not None else actuel.get("logo_url", ""),
                                     payload.message if payload.message is not None else actuel.get("message", ""))
        maj: Dict[str, Any] = {"branding": identite, "title": f"Spécifications de votre automate — {identite['organisation']}",
                               "description": description_formulaire(identite["organisation"], identite["message"]), "updated_at": maintenant()}
        if payload.is_public is not None:
            maj["is_public"] = payload.is_public
        autre = await db.forms.find_one({"modele": MODELE, "id": {"$ne": form_id}, "title": {"$regex": f"^{re.escape(maj['title'])}$", "$options": "i"}}, {"_id": 0, "id": 1})
        if autre:
            raise HTTPException(status_code=409, detail="Un autre formulaire porte déjà ce nom de clinique")
        await db.forms.update_one({"id": form_id}, {"$set": maj})
        return vue({**form, **maj}, request)

    @api.get("/admin/formulaire-automates/{form_id}/reponses", tags=["Formulaire automates"])
    async def reponses(form_id: str, format: Optional[str] = None, user: dict = Depends(get_current_user)):
        """Réponses du formulaire : liste lisible (JSON) ou, avec ?format=csv, toutes les colonnes."""
        exiger_admin(user)
        form = await db.forms.find_one({"id": form_id, "modele": MODELE}, {"_id": 0})
        if not form:
            raise HTTPException(status_code=404, detail="Formulaire introuvable")
        soumissions = await db.form_submissions.find({"form_id": form_id}, {"_id": 0}).sort("created_at", -1).to_list(1000)
        lignes = lignes_reponses(form, soumissions)
        if format == "csv":
            return Response(content=export_csv(form, lignes).encode("utf-8"), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="automates_{form.get("number", "formulaire")}.csv"'})
        champs = [{"id": f["id"], "label": f["label"]} for p in form.get("pages", []) for f in p.get("fields", [])]
        return {"titre": form.get("title"), "champs": champs, "reponses": lignes}


__all__ = ["attach_formulaire_automates_routes", "pages_modele", "nettoyer_identite", "contenu_conforme", "lignes_reponses", "export_csv", "MODELE"]
