"""Lot 40 — Carrousel WhatsApp : 2 à 10 cartes (photo, titre, texte, bouton) envoyées en un
seul message modèle Meta, comme le carrousel d'adLyn.

Deux côtés :
  - PORTAIL (fonction activable « Carrousel WhatsApp », clé `whatsapp_carrousel`, par
    l'Admin dans SMART Communications ; la fonction `whatsapp` doit aussi être active) :
    un client envoie à SES contacts (annuaire, groupes) qui ont ACCEPTÉ de recevoir ses
    messages WhatsApp (champ `accepte_whatsapp` du contact). Envoi avec le numéro
    WhatsApp du client s'il a le sien (tenant_smart_comm), sinon celui de la plateforme.
      GET  /api/me/whatsapp/carrousel                 état (fonction, modèles, limites)
      GET  /api/me/whatsapp/carrousel/produits        produits de la caisse (avec photo)
      GET  /api/me/whatsapp/carrousel/images          images utilisables (générées, médiathèque, envoyées)
      POST /api/me/whatsapp/carrousel/images          envoi d'une image (JPEG/PNG, 5 Mo)
      GET  /api/me/whatsapp/carrousel/destinataires   contacts + groupes, avec le consentement
      PUT  /api/me/whatsapp/carrousel/consentements   {ids, accepte} : note le consentement
      POST /api/me/whatsapp/carrousel/envoyer         lance une campagne (202, envoi en fond)
      GET  /api/me/whatsapp/carrousel/campagnes[/{id}] historique et résultat par destinataire
  - ADMINISTRATION (Admin) : SAWALI envoie à SES clients (comptes clients) qui ont accepté,
    avec le numéro de la plateforme. Mêmes routes sous /api/admin/whatsapp/carrousel, plus
      GET/PUT /api/admin/whatsapp/carrousel/reglages  nom et langue des modèles Meta.

Les cartes viennent au choix des PRODUITS DE LA CAISSE (photo, nom, prix, bouton « Voir le
produit » → page du produit) ou sont LIBRES (image, titre, texte, lien). Un seul format de
modèle Meta sert aux deux : il en faut un par nombre de cartes, `<nom>_2` à `<nom>_10`
(message : {{1}} expéditeur, {{2}} texte ; carte : image en en-tête, corps {{1}} titre et
{{2}} texte, bouton URL `<site>/api/public/carrousel/l/{{1}}`). Le bouton passe par
GET /api/public/carrousel/l/{code} qui compte les clics puis redirige vers le lien.
"""
from __future__ import annotations

import base64
import logging
import re
import time
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional

from fastapi import BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from routes.whatsapp_helpers import _normalize_wa_phone

logger = logging.getLogger("sawali.carrousel")

CLE_FONCTION = "whatsapp_carrousel"
CARTES_MIN, CARTES_MAX = 2, 10          # limites Meta d'un carrousel
DESTINATAIRES_MAX = 200                 # par campagne
IMAGE_MAX_OCTETS = 5 * 1024 * 1024      # limite Meta d'une image d'en-tête
TYPES_IMAGE = {"image/jpeg": "jpg", "image/png": "png"}   # seuls formats acceptés par Meta
LANGUE_DEFAUT = "fr"
ROLES_CLIENTS = ["client", "pharmacien", "medecin", "regulateur", "editeur_vidal", "moderateur", "moderator"]
COMPTE_PLATEFORME = "admin@sawalismartsystems.com"
CHEMIN_LIEN = "/api/public/carrousel/l/"
INDICATIF_DEFAUT = "226"                # numéro local à 8 chiffres : Burkina Faso (pays par défaut)
# Lot 75 — image d'une carte générée par l'IA (gpt-image-1) à partir d'une description
IA_PROMPT_MAX = 1000                    # longueur maximale de la description
IA_PAR_HEURE_DEFAUT = 20                # générations par compte et par heure (réglable dans Paramètres)
IA_APERCU_DUREE_H = 2                   # un aperçu non retenu est oublié après 2 h
IA_CONSIGNE = ("Image publicitaire carrée pour une carte de carrousel WhatsApp : visuel net et lumineux, "
               "sujet centré, aucun texte ni lettre incrustés dans l'image.")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def statut_pour_cartes(nb_cartes: int, statuts: Dict[int, str]) -> str:
    """Lot 77 — statut chez Meta du modèle utilisé par un carrousel de nb_cartes cartes
    (<préfixe>_<nb>) : APPROVED, PENDING, REJECTED…, « HORS_LIMITES » (moins de 2 ou plus de 10 cartes)
    ou « ABSENT » (modèle pas encore créé chez Meta)."""
    if nb_cartes < CARTES_MIN or nb_cartes > CARTES_MAX:
        return "HORS_LIMITES"
    return (statuts.get(nb_cartes) or "ABSENT").upper()


def statuts_depuis_liste(prefixe: str, langue: str, modeles: List[dict]) -> Dict[int, str]:
    """Lot 77 — {nombre de cartes: statut} à partir de la liste des modèles renvoyée par Meta
    (seuls les noms <préfixe>_2 … _10 dans la bonne langue comptent)."""
    sortie: Dict[int, str] = {}
    for m in modeles or []:
        nom = str(m.get("name") or "")
        if not nom.startswith(f"{prefixe}_") or (langue and (m.get("language") or langue) != langue):
            continue
        suffixe = nom[len(prefixe) + 1:]
        if suffixe.isdigit() and CARTES_MIN <= int(suffixe) <= CARTES_MAX:
            sortie[int(suffixe)] = str(m.get("status") or "").upper()
    return sortie


def prompt_image_carte(description: str, titre: str = "") -> str:
    """Lot 75 — consigne envoyée à l'IA : la description saisie, le titre de la carte (contexte)
    et la consigne de format (carré, sans texte : WhatsApp affiche déjà titre et texte sous l'image)."""
    description = " ".join((description or "").split())[:IA_PROMPT_MAX]
    contexte = f" Sujet de la carte : « {titre.strip()[:60]} »." if (titre or "").strip() else ""
    return f"{description}.{contexte} {IA_CONSIGNE}".strip()


# ---------------------------------------------------------------------------
# Fonctions pures (testées sans base)
# ---------------------------------------------------------------------------
def nom_modele(prefixe: str, nb_cartes: int) -> str:
    """Un modèle Meta par nombre de cartes : « sawali_carrousel_3 » pour 3 cartes."""
    return f"{prefixe}_{nb_cartes}"


def url_absolue(url: Optional[str], base: str) -> str:
    """Meta télécharge l'image lui-même : l'adresse doit être complète (https://…)."""
    url = (url or "").strip()
    if url.startswith("/"):
        return f"{base.rstrip('/')}{url}"
    return url


def image_acceptee(url: str) -> bool:
    """Adresse publique d'une image JPEG ou PNG (Meta refuse WebP, GIF…)."""
    u = url.lower().split("?")[0]
    return u.startswith("https://") and u.endswith((".jpg", ".jpeg", ".png"))


def numero_whatsapp(brut: Optional[str]) -> str:
    """Chiffres seuls avec l'indicatif, comme l'attend Meta : « 76 22 22 22 » → « 22676222222 »."""
    tel = _normalize_wa_phone(brut)
    return INDICATIF_DEFAUT + tel if len(tel) == 8 else tel


def lien_accepte(url: str) -> bool:
    return bool(re.match(r"^https?://[^\s/]+\.[^\s]+$", (url or "").strip()))


def prix_affiche(montant: Any, devise: str = "FCFA") -> str:
    """12500 → « 12 500 FCFA » (espace insécable remplacé par une espace simple pour Meta)."""
    try:
        return f"{int(round(float(montant))):,}".replace(",", " ") + f" {devise}"
    except (TypeError, ValueError):
        return ""


def composants(expediteur: str, message: str, cartes: List[dict]) -> List[dict]:
    """Composants du message modèle : bulle de texte puis une entrée par carte
    (image d'en-tête, titre + texte, suffixe du bouton URL)."""
    return [
        {"type": "body", "parameters": [
            {"type": "text", "text": (expediteur or "SAWALI")[:60]},
            {"type": "text", "text": (message or "")[:500]},
        ]},
        {"type": "carousel", "cards": [
            {"card_index": i, "components": [
                {"type": "header", "parameters": [{"type": "image", "image": {"link": c["image_url"]}}]},
                {"type": "body", "parameters": [
                    {"type": "text", "text": c["titre"][:60]},
                    {"type": "text", "text": (c.get("texte") or "-")[:80]},
                ]},
                {"type": "button", "sub_type": "url", "index": "0",
                 "parameters": [{"type": "text", "text": c["code_lien"]}]},
            ]}
            for i, c in enumerate(cartes)
        ]},
    ]


# ---------------------------------------------------------------------------
# Modèles de requête
# ---------------------------------------------------------------------------
class CarteIn(BaseModel):
    source: Literal["produit", "libre"] = "libre"
    produit_id: Optional[str] = None
    image_url: Optional[str] = Field(None, max_length=600)
    titre: Optional[str] = Field(None, max_length=60)
    texte: Optional[str] = Field(None, max_length=80)
    lien: Optional[str] = Field(None, max_length=600)


class EnvoiIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    cartes: List[CarteIn] = Field(..., min_length=CARTES_MIN, max_length=CARTES_MAX)
    ids: List[str] = Field(default_factory=list)          # contacts (portail) ou clients (admin)
    groupes: List[str] = Field(default_factory=list)      # groupes de contacts (portail)


class BrouillonIn(BaseModel):
    """Lot 77 — carrousel enregistré sous un nom (message + cartes), réutilisable et duplicable."""
    nom: str = Field(..., min_length=1, max_length=80)
    message: str = Field("", max_length=500)
    cartes: List[CarteIn] = Field(default_factory=list, max_length=CARTES_MAX)


class BrouillonAutoIn(BaseModel):
    """Lot 78 — enregistrement automatique du carrousel en cours (sans nom)."""
    message: str = Field("", max_length=500)
    cartes: List[CarteIn] = Field(default_factory=list, max_length=CARTES_MAX)
    carrousel_id: Optional[str] = None      # carrousel nommé ouvert dans l'éditeur, s'il y en a un


class DemandeAccordIn(BaseModel):
    """Lot 79 — personnes à qui demander leur accord WhatsApp (boutons Oui / Non)."""
    ids: List[str] = Field(default_factory=list, max_length=DESTINATAIRES_MAX)


class PartageIn(BaseModel):
    """Lot 79 — adresses e-mail des comptes avec qui partager un carrousel (liste complète, vide = aucun)."""
    emails: List[str] = Field(default_factory=list, max_length=50)


class PreferencesIn(BaseModel):
    """Lot 78 — lien utilisé par les cartes libres laissées sans lien (vide = aucun)."""
    lien_defaut: str = Field("", max_length=600)


class ImageIaIn(BaseModel):
    """Lot 75 — description de l'image à générer pour une carte (et titre de la carte, facultatif)."""
    prompt: str = Field(..., min_length=3, max_length=IA_PROMPT_MAX)
    titre: Optional[str] = Field(None, max_length=120)


class ConsentementIn(BaseModel):
    ids: List[str] = Field(..., min_length=1, max_length=2000)
    accepte: bool


class ReglagesIn(BaseModel):
    modele: str = Field(..., min_length=3, max_length=60, pattern=r"^[a-z0-9_]+$")
    langue: str = Field(LANGUE_DEFAUT, min_length=2, max_length=10)
    tenant_id: Optional[str] = None     # modèles propres à un client qui a son numéro WhatsApp


# ---------------------------------------------------------------------------
# Branchement
# ---------------------------------------------------------------------------
def attach_carrousel_whatsapp_routes(
    *, api, db, get_current_user, get_current_admin,
    fonction_active: Callable[[dict, str], Awaitable[bool]],
    visible_client_ids: Callable[[dict], Awaitable[List[str]]],
    wa_send_template: Callable[..., Awaitable[dict]],
    resolve_wa_credentials: Callable[[Optional[str]], Awaitable[dict]],
    base_publique: Callable[[], str],
    save_and_log: Optional[Callable[..., Awaitable[dict]]] = None,
) -> Dict[str, Any]:
    """Branche les routes du carrousel. `base_publique()` : adresse publique du site
    (PUBLIC_BASE_URL), utilisée pour les images et les liens des boutons."""

    def _tenant_id(user: dict) -> str:
        return user.get("parent_client_id") or user.get("client_id") or user["id"]

    async def utilisateur(user: dict = Depends(get_current_user)) -> dict:
        """Portail : fonctions « WhatsApp » ET « Carrousel WhatsApp » actives (contrôle serveur)."""
        if not (await fonction_active(user, "whatsapp") and await fonction_active(user, CLE_FONCTION)):
            raise HTTPException(status_code=403, detail="La fonction « Carrousel WhatsApp » n'est pas activée "
                                                        "pour votre compte. Demandez son activation à votre "
                                                        "administrateur SAWALI.")
        return user

    # --- Réglages des modèles Meta ------------------------------------------
    async def _reglages(tenant_id: Optional[str]) -> dict:
        """Numéro utilisé (celui du client ou de la plateforme) et modèles qui vont avec :
        les modèles appartiennent au compte WhatsApp Business qui envoie."""
        creds = await resolve_wa_credentials(tenant_id)
        if creds.get("source") == "tenant":
            doc = await db.tenant_smart_comm.find_one({"tenant_id": tenant_id}, {"_id": 0}) or {}
        else:
            doc = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
        modele = (doc.get("wa_carrousel_modele") or "").strip()
        return {
            "numero": "client" if creds.get("source") == "tenant" else "plateforme",
            "whatsapp_configure": bool(creds.get("access_token") and creds.get("phone_number_id")),
            "modele": modele,
            "langue": (doc.get("wa_carrousel_langue") or LANGUE_DEFAUT).strip(),
            "creds_tenant": creds.get("tenant_id"),
        }

    def _url_bouton() -> str:
        return f"{base_publique().rstrip('/')}{CHEMIN_LIEN}{{{{1}}}}"

    async def _etat(tenant_id: Optional[str], filtre_campagnes: dict) -> dict:
        r = await _reglages(tenant_id)
        debut_mois = datetime.now(timezone.utc).strftime("%Y-%m-01")
        envoyes = 0
        async for c in db.carrousel_campagnes.find({**filtre_campagnes, "cree_le": {"$gte": debut_mois}},
                                                   {"_id": 0, "compte": 1}):
            envoyes += (c.get("compte") or {}).get("envoyes", 0)
        return {
            "pret": bool(r["whatsapp_configure"] and r["modele"]),
            "whatsapp_configure": r["whatsapp_configure"], "numero": r["numero"],
            "modele": r["modele"], "langue": r["langue"],
            "modeles_attendus": [nom_modele(r["modele"] or "<nom>", n) for n in range(CARTES_MIN, CARTES_MAX + 1)],
            "url_bouton_modele": _url_bouton(),
            "cartes_min": CARTES_MIN, "cartes_max": CARTES_MAX, "destinataires_max": DESTINATAIRES_MAX,
            "envoyes_ce_mois": envoyes,
        }

    # --- Produits et images -------------------------------------------------
    async def _produits(tenant_id: Optional[str]) -> List[dict]:
        q: Dict[str, Any] = {"deleted_at": None, "active": {"$ne": False},
                             "image_url": {"$nin": [None, ""]}}
        if tenant_id:
            q["$or"] = [{"client_id": tenant_id}, {"tenant_id": tenant_id}]
        base = base_publique()
        lignes = []
        async for p in db.products.find(q, {"_id": 0}).sort("name", 1).limit(500):
            image = url_absolue(p.get("image_url"), base)
            lignes.append({"id": p["id"], "nom": p.get("name") or "", "prix": prix_affiche(p.get("unit_price_ht")),
                           "image_url": image, "image_ok": image_acceptee(image),
                           "public": bool(p.get("is_public")), "categorie": p.get("category") or ""})
        return lignes

    async def _images(tenant_id: Optional[str], admin: bool) -> List[dict]:
        """Images JPEG/PNG publiques : envoyées pour le carrousel, générées (Générateur de
        médias), médiathèque et, pour l'Admin, Story Studio."""
        base = base_publique()
        vues, lignes = set(), []

        def ajouter(url, titre, origine):
            u = url_absolue(url, base)
            if u and u not in vues and image_acceptee(u):
                vues.add(u)
                lignes.append({"url": u, "titre": (titre or "")[:80], "origine": origine})

        q_tenant = {} if admin else {"tenant_id": tenant_id}
        async for o in db.stored_objects.find({**q_tenant, "kind": "carrousel", "is_deleted": False},
                                              {"_id": 0}).sort("created_at", -1).limit(100):
            ajouter(f"/api/files/{o['storage_path']}", o.get("original_filename"), "Envoyée")
        async for g in db.ai_generations.find(q_tenant, {"_id": 0}).sort("created_at", -1).limit(100):
            ajouter(g.get("url"), g.get("prompt"), "Générateur de médias")
        q_media = {"kind": "image", "is_deleted": {"$ne": True}}
        if not admin:
            q_media["public"] = True
        async for m in db.media_library.find(q_media, {"_id": 0}).limit(200):
            ajouter(m.get("url"), m.get("title"), "Médiathèque")
        if admin:
            async for s in db.story_assets.find({"kind": "image"}, {"_id": 0}).sort("created_at", -1).limit(100):
                if (s.get("url") or "").startswith("/api/files/"):
                    ajouter(s.get("url"), s.get("title"), "Story Studio")
        return lignes

    async def _envoyer_image(fichier: UploadFile, tenant_id: str, user: dict) -> dict:
        if save_and_log is None:
            raise HTTPException(status_code=503, detail="Stockage des fichiers indisponible")
        ext = TYPES_IMAGE.get((fichier.content_type or "").lower())
        if not ext:
            raise HTTPException(status_code=400, detail="Image JPEG ou PNG uniquement (format exigé par WhatsApp)")
        data = await fichier.read(IMAGE_MAX_OCTETS + 1)
        if len(data) > IMAGE_MAX_OCTETS:
            raise HTTPException(status_code=400, detail="Image trop lourde : 5 Mo au maximum")
        saved = await save_and_log(db, data=data, kind="carrousel", tenant_id=tenant_id, ext=ext,
                                   content_type=fichier.content_type, original_filename=fichier.filename,
                                   user_id=user.get("id"))
        return {"url": url_absolue(saved["url"], base_publique())}

    # --- Lot 77 : carrousels nommés et statut des modèles chez Meta --------
    _cache_statuts: Dict[str, tuple] = {}                 # clé → (horodatage, statuts) : 2 minutes

    async def _statuts_meta(tenant_id: Optional[str], rafraichir: bool = False) -> Dict[str, Any]:
        """Statut chez Meta de chaque modèle <préfixe>_2 … _10 (lecture de la liste des modèles du WABA)."""
        r = await _reglages(tenant_id)
        prefixe, langue = r["modele"], r["langue"]
        if not prefixe:
            return {"prefixe": "", "statuts": {}, "erreur": "Nom des modèles non renseigné"}
        cle = f"{tenant_id or 'plateforme'}:{prefixe}:{langue}"
        cache = _cache_statuts.get(cle)
        if cache and not rafraichir and time.time() - cache[0] < 120:
            return {"prefixe": prefixe, "statuts": cache[1], "erreur": None}
        creds = await resolve_wa_credentials(tenant_id)
        jeton, waba = (creds.get("access_token") or "").strip(), (creds.get("waba_id") or "").strip()
        if not jeton or not waba:
            return {"prefixe": prefixe, "statuts": {}, "erreur": "WhatsApp Business incomplet (jeton ou WABA)"}
        s_glob = await db.settings.find_one({"_id": "global"}, {"_id": 0, "wa_graph_version": 1}) or {}
        version = (s_glob.get("wa_graph_version") or "v22.0").strip()
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as http:
                rep = await http.get(f"https://graph.facebook.com/{version}/{waba}/message_templates",
                                     params={"name": prefixe, "fields": "name,status,language", "limit": 200},
                                     headers={"Authorization": f"Bearer {jeton}"})
            if rep.status_code >= 300:
                return {"prefixe": prefixe, "statuts": {}, "erreur": f"Meta : HTTP {rep.status_code}"}
            statuts = statuts_depuis_liste(prefixe, langue, (rep.json() or {}).get("data") or [])
        except Exception as exc:  # noqa: BLE001 — l'écran reste utilisable sans les pastilles
            return {"prefixe": prefixe, "statuts": {}, "erreur": f"Meta injoignable : {type(exc).__name__}"}
        _cache_statuts[cle] = (time.time(), statuts)
        return {"prefixe": prefixe, "statuts": statuts, "erreur": None}

    def _filtre_brouillons(perimetre: str, tenant_id: Optional[str]) -> dict:
        return {"perimetre": perimetre, **({"tenant_id": tenant_id} if perimetre == "client" else {})}

    async def _figer_cartes(cartes: List[dict], tenant_source: Optional[str]) -> List[dict]:
        """Lot 79.1 — un carrousel partagé peut contenir des cartes « Produit » de l'espace qui partage : le
        destinataire n'a pas accès à ces produits. Elles sont donc transformées en cartes libres (photo, nom,
        prix et page du produit), lues dans l'espace d'origine."""
        base = base_publique()
        sortie = []
        for c in cartes or []:
            if c.get("source") != "produit" or not c.get("produit_id"):
                sortie.append(c)
                continue
            q: Dict[str, Any] = {"id": c["produit_id"], "deleted_at": None}
            if tenant_source:
                q["$or"] = [{"client_id": tenant_source}, {"tenant_id": tenant_source}]
            p = await db.products.find_one(q, {"_id": 0, "id": 1, "name": 1, "image_url": 1, "unit_price_ht": 1})
            if not p:
                sortie.append(c)
                continue
            sortie.append({"source": "libre", "produit_id": None,
                           "image_url": url_absolue(c.get("image_url") or p.get("image_url"), base),
                           "titre": (c.get("titre") or p.get("name") or "")[:60],
                           "texte": (c.get("texte") or prix_affiche(p.get("unit_price_ht")))[:80],
                           "lien": c.get("lien") or f"{base.rstrip('/')}/api/public/og/product/{p['id']}"})
        return sortie

    def _filtre_partages(perimetre: str, tenant_id: Optional[str]) -> dict:
        """Lot 79 — carrousels d'un AUTRE espace partagés avec cet espace (admin, ou client = tenant)."""
        cible = {"perimetre": perimetre, **({"tenant_id": tenant_id} if perimetre == "client" else {})}
        return {"partages": {"$elemMatch": cible}, "$nor": [_filtre_brouillons(perimetre, tenant_id)]}

    async def _partager(bid: str, data: PartageIn, perimetre: str, tenant_id: Optional[str]) -> dict:
        """Lot 79 — partage d'un carrousel avec des comptes désignés par leur e-mail. Le compte destinataire le
        voit dans « Mes carrousels » (sans les envois ni leurs statistiques, qui restent chez l'expéditeur)."""
        src = await db.carrousel_brouillons.find_one({**_filtre_brouillons(perimetre, tenant_id), "id": bid}, {"_id": 0})
        if not src:
            raise HTTPException(status_code=404, detail="Carrousel introuvable")
        partages, inconnus = [], []
        for e in dict.fromkeys(x.strip().lower() for x in data.emails if x and x.strip()):
            u = await db.users.find_one({"email": {"$regex": f"^{re.escape(e)}$", "$options": "i"}},
                                        {"_id": 0, "id": 1, "email": 1, "role": 1, "full_name": 1, "company": 1,
                                         "client_id": 1, "parent_client_id": 1})
            if not u:
                inconnus.append(e)
                continue
            if u.get("role") == "admin":
                cible = {"perimetre": "admin", "tenant_id": None}
            else:
                cible = {"perimetre": "client", "tenant_id": _tenant_id(u)}
            partages.append({**cible, "email": u.get("email") or e, "user_id": u["id"],
                             "nom": u.get("full_name") or u.get("company") or u.get("email") or e})
        if inconnus:
            raise HTTPException(status_code=400, detail="Aucun compte SAWALI pour : " + ", ".join(inconnus))
        await db.carrousel_brouillons.update_one({"id": bid}, {"$set": {"partages": partages}})
        return {"id": bid, "partages": partages}

    # --- Lot 79 : accord WhatsApp demandé à la personne (boutons) et lien / QR code d'accord ---
    _numeros_affiches: Dict[str, str] = {}

    async def _version_graph() -> str:
        g = await db.settings.find_one({"_id": "global"}, {"_id": 0, "wa_graph_version": 1}) or {}
        return (g.get("wa_graph_version") or "v22.0").strip()

    async def _demander_accord(personnes: List[dict], tenant_id: Optional[str]) -> dict:
        from routes import accord_whatsapp as aw
        sans_accord = [p for p in personnes if not p.get("accepte") and len(numero_whatsapp(p.get("telephone"))) >= 10]
        if not sans_accord:
            return {"envoyees": 0, "fenetre_fermee": [], "erreurs": [], "deja": len(personnes)}
        creds = await resolve_wa_credentials(tenant_id)
        res = await aw.envoyer_demandes(db, sans_accord, creds, await _version_graph())
        return {**res, "deja": len(personnes) - len(sans_accord)}

    async def _lien_accord(tenant_id: Optional[str]) -> dict:
        """Lien wa.me (et texte pré-rempli « OUI NOUVEAUTES ») vers le numéro WhatsApp qui envoie les carrousels."""
        from routes import accord_whatsapp as aw
        creds = await resolve_wa_credentials(tenant_id)
        numero_id, jeton = (creds.get("phone_number_id") or "").strip(), (creds.get("access_token") or "").strip()
        if not numero_id or not jeton:
            return {"lien": "", "numero": "", "mot_cle": aw.MOT_CLE_ACCORD, "erreur": "WhatsApp n'est pas configuré"}
        affiche = _numeros_affiches.get(numero_id, "")
        if not affiche:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10) as http:
                    r = await http.get(f"https://graph.facebook.com/{await _version_graph()}/{numero_id}",
                                       params={"fields": "display_phone_number"},
                                       headers={"Authorization": f"Bearer {jeton}"})
                affiche = str((r.json() or {}).get("display_phone_number") or "") if r.status_code < 300 else ""
                if affiche:
                    _numeros_affiches[numero_id] = affiche
            except Exception:  # noqa: BLE001 — le lien est un plus : l'écran reste utilisable
                affiche = ""
        return {"lien": aw.lien_accord(affiche), "numero": affiche, "mot_cle": aw.MOT_CLE_ACCORD,
                "erreur": None if affiche else "Numéro WhatsApp introuvable chez Meta"}

    def _peut_partager(user: dict) -> None:
        """Lot 79 — le partage est réservé à l'administration et aux superviseurs."""
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Le partage des carrousels est réservé aux administrateurs et superviseurs")

    async def _lister_brouillons(perimetre: str, tenant_id: Optional[str]) -> Dict[str, Any]:
        meta = await _statuts_meta(tenant_id if perimetre == "client" else None)
        lignes = []
        async for b in db.carrousel_brouillons.find({**_filtre_brouillons(perimetre, tenant_id), "auto": {"$ne": True}},
                                                    {"_id": 0}).sort("modifie_le", -1):
            n = len(b.get("cartes") or [])
            lignes.append({**b, "nb_cartes": n, "modele": f"{meta['prefixe']}_{n}" if meta["prefixe"] else None,
                           "statut_meta": statut_pour_cartes(n, meta["statuts"])})
        # Lot 79 — carrousels partagés AVEC ce périmètre (lecture seule : ouvrir, dupliquer, envoyer à ses contacts)
        async for b in db.carrousel_brouillons.find({**_filtre_partages(perimetre, tenant_id), "auto": {"$ne": True}},
                                                    {"_id": 0, "partages": 0}).sort("modifie_le", -1):
            b["cartes"] = await _figer_cartes(b.get("cartes") or [], b.get("tenant_id"))   # lot 79.1
            n = len(b.get("cartes") or [])
            lignes.append({**b, "nb_cartes": n, "modele": f"{meta['prefixe']}_{n}" if meta["prefixe"] else None,
                           "statut_meta": statut_pour_cartes(n, meta["statuts"]), "partage": True,
                           "partage_par": b.get("cree_par_nom") or b.get("modifie_par") or ""})
        return {"carrousels": lignes, "statuts_meta": {str(k): v for k, v in meta["statuts"].items()},
                "erreur_meta": meta["erreur"]}

    async def _enregistrer_brouillon(data: BrouillonIn, perimetre: str, tenant_id: Optional[str], user: dict,
                                     bid: Optional[str] = None) -> dict:
        maintenant = _maintenant()
        doc = {"nom": data.nom.strip(), "message": data.message, "cartes": [c.model_dump() for c in data.cartes],
               "modifie_le": maintenant, "modifie_par": user.get("email") or user.get("id")}
        if bid:
            res = await db.carrousel_brouillons.update_one({**_filtre_brouillons(perimetre, tenant_id), "id": bid}, {"$set": doc})
            if not res.matched_count:
                raise HTTPException(status_code=404, detail="Carrousel introuvable")
            return {"id": bid, **doc}
        doc.update({"id": uuid.uuid4().hex, "perimetre": perimetre, "tenant_id": tenant_id if perimetre == "client" else None,
                    "cree_le": maintenant, "cree_par_nom": user.get("full_name") or user.get("email") or ""})
        await db.carrousel_brouillons.insert_one(dict(doc))
        return doc

    # --- Lot 78 : préférences (lien par défaut) et brouillon automatique ----
    def _cle_pref(perimetre: str, tenant_id: Optional[str]) -> dict:
        return {"perimetre": perimetre, "tenant_id": tenant_id if perimetre == "client" else None}

    async def _preferences(perimetre: str, tenant_id: Optional[str]) -> dict:
        doc = await db.carrousel_preferences.find_one(_cle_pref(perimetre, tenant_id), {"_id": 0}) or {}
        return {"lien_defaut": (doc.get("lien_defaut") or "").strip()}

    async def _ecrire_preferences(data: PreferencesIn, perimetre: str, tenant_id: Optional[str]) -> dict:
        lien = (data.lien_defaut or "").strip()
        if lien and not lien_accepte(lien):
            raise HTTPException(status_code=400, detail="Lien par défaut invalide : adresse complète https://… attendue")
        await db.carrousel_preferences.update_one(_cle_pref(perimetre, tenant_id),
                                                  {"$set": {**_cle_pref(perimetre, tenant_id), "lien_defaut": lien}}, upsert=True)
        return {"lien_defaut": lien}

    def _cle_auto(perimetre: str, tenant_id: Optional[str], user: dict) -> dict:
        """Un brouillon automatique par utilisateur (et par client sur le portail)."""
        return {**_filtre_brouillons(perimetre, tenant_id), "auto": True, "user_id": user.get("id")}

    async def _lire_auto(perimetre: str, tenant_id: Optional[str], user: dict) -> dict:
        doc = await db.carrousel_brouillons.find_one(_cle_auto(perimetre, tenant_id, user), {"_id": 0})
        return {"brouillon": doc}

    async def _ecrire_auto(data: BrouillonAutoIn, perimetre: str, tenant_id: Optional[str], user: dict) -> dict:
        cle = _cle_auto(perimetre, tenant_id, user)
        maj = {**cle, "nom": "Sans nom (automatique)", "message": data.message,
               "cartes": [c.model_dump() for c in data.cartes], "carrousel_id": data.carrousel_id,
               "modifie_le": _maintenant()}
        await db.carrousel_brouillons.update_one(cle, {"$set": maj, "$setOnInsert": {"id": uuid.uuid4().hex, "cree_le": _maintenant()}},
                                                 upsert=True)
        return {"ok": True, "enregistre_le": maj["modifie_le"]}

    async def _dupliquer_brouillon(bid: str, perimetre: str, tenant_id: Optional[str], user: dict) -> dict:
        src = await db.carrousel_brouillons.find_one(
            {"id": bid, "$or": [_filtre_brouillons(perimetre, tenant_id), _filtre_partages(perimetre, tenant_id)]}, {"_id": 0})
        if not src:
            raise HTTPException(status_code=404, detail="Carrousel introuvable")
        cartes_src = src.get("cartes") or []
        if src.get("perimetre") != perimetre or src.get("tenant_id") != (tenant_id if perimetre == "client" else None):
            cartes_src = await _figer_cartes(cartes_src, src.get("tenant_id"))   # lot 79.1 : copie d'un carrousel partagé
        copie = BrouillonIn(nom=f"Copie de {src['nom']}"[:80], message=src.get("message") or "",
                            cartes=[CarteIn(**c) for c in cartes_src])
        return await _enregistrer_brouillon(copie, perimetre, tenant_id, user)

    async def _supprimer_brouillon(bid: str, perimetre: str, tenant_id: Optional[str]) -> dict:
        res = await db.carrousel_brouillons.delete_one({**_filtre_brouillons(perimetre, tenant_id), "id": bid})
        if not res.deleted_count:
            raise HTTPException(status_code=404, detail="Carrousel introuvable")
        return {"ok": True}

    # --- Lot 75 : image générée par l'IA -----------------------------------
    async def _generer_image_ia(data: ImageIaIn, tenant_id: str, user: dict) -> dict:
        """Étape 1 : génère l'image et la garde 2 h comme APERÇU (pas encore dans les fichiers).
        Rien n'est enregistré dans la médiathèque tant que l'utilisateur ne l'a pas retenue."""
        reglages = await db.settings.find_one({"_id": "global"}, {"_id": 0, "carrousel_ia_par_heure": 1}) or {}
        try:
            par_heure = max(1, int(reglages.get("carrousel_ia_par_heure") or IA_PAR_HEURE_DEFAUT))
        except (TypeError, ValueError):
            par_heure = IA_PAR_HEURE_DEFAUT
        il_y_a_une_heure = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        if await db.carrousel_images_ia.count_documents({"tenant_id": tenant_id, "cree_le": {"$gte": il_y_a_une_heure}}) >= par_heure:
            raise HTTPException(status_code=429, detail=f"Limite atteinte : {par_heure} images générées par heure. Réessayez plus tard.")
        try:
            from ia_client import OpenAIImageGeneration
            images = await OpenAIImageGeneration().generate_images(
                prompt_image_carte(data.prompt, data.titre or ""), model="gpt-image-1", quality="medium")
        except Exception as exc:  # noqa: BLE001 — clé absente, refus de contenu, réseau…
            raise HTTPException(status_code=502, detail=f"Génération de l'image impossible : {str(exc)[:200]}") from exc
        if not images:
            raise HTTPException(status_code=502, detail="L'IA n'a renvoyé aucune image. Reformulez la description.")
        octets = images[0]
        if len(octets) > IMAGE_MAX_OCTETS:
            raise HTTPException(status_code=502, detail="Image générée trop lourde pour WhatsApp (5 Mo). Réessayez.")
        apercu_id = uuid.uuid4().hex
        # Nettoyage des aperçus anciens, puis enregistrement de celui-ci
        limite = (datetime.now(timezone.utc) - timedelta(hours=IA_APERCU_DUREE_H)).isoformat()
        await db.carrousel_images_ia.update_many({"cree_le": {"$lt": limite}, "octets_b64": {"$ne": None}},
                                                 {"$set": {"octets_b64": None}})
        b64 = base64.b64encode(octets).decode("ascii")
        await db.carrousel_images_ia.insert_one({
            "id": apercu_id, "tenant_id": tenant_id, "user_id": user.get("id"), "prompt": data.prompt[:IA_PROMPT_MAX],
            "octets_b64": b64, "retenue": False, "cree_le": _maintenant(),
        })
        return {"apercu_id": apercu_id, "apercu": f"data:image/png;base64,{b64}"}

    async def _retenir_image_ia(apercu_id: str, tenant_id: str, user: dict) -> dict:
        """Étape 2 : l'image convient → elle est enregistrée (fichiers SAWALI), son adresse publique
        https://… est renvoyée et placée dans le champ « image » de la carte."""
        if save_and_log is None:
            raise HTTPException(status_code=503, detail="Stockage des fichiers indisponible")
        doc = await db.carrousel_images_ia.find_one({"id": apercu_id, "tenant_id": tenant_id}, {"_id": 0})
        if doc and doc.get("url"):
            return {"url": doc["url"]}                     # déjà retenue (double clic) : même adresse
        if not doc or not doc.get("octets_b64"):
            raise HTTPException(status_code=404, detail="Aperçu expiré ou introuvable : générez l'image à nouveau.")
        saved = await save_and_log(db, data=base64.b64decode(doc["octets_b64"]), kind="carrousel", tenant_id=tenant_id,
                                   ext="png", content_type="image/png", original_filename=f"carrousel-ia-{apercu_id[:8]}.png",
                                   user_id=user.get("id"))
        url = url_absolue(saved["url"], base_publique())
        await db.carrousel_images_ia.update_one({"id": apercu_id}, {"$set": {"retenue": True, "url": url, "octets_b64": None}})
        return {"url": url}

    # --- Cartes --------------------------------------------------------------
    async def _preparer_cartes(cartes: List[CarteIn], tenant_id: Optional[str], lien_defaut: str = "") -> List[dict]:
        """Vérifie chaque carte ; une carte produit prend photo, nom et prix du produit
        (du client connecté seulement) et son bouton mène à la page du produit."""
        base = base_publique()
        prets = []
        for i, c in enumerate(cartes, 1):
            if c.source == "produit":
                q: Dict[str, Any] = {"id": c.produit_id, "deleted_at": None}
                if tenant_id:
                    q["$or"] = [{"client_id": tenant_id}, {"tenant_id": tenant_id}]
                p = await db.products.find_one(q, {"_id": 0}) if c.produit_id else None
                if not p:
                    raise HTTPException(status_code=400, detail=f"Carte {i} : produit introuvable")
                image = url_absolue(c.image_url or p.get("image_url"), base)
                titre = (c.titre or p.get("name") or "").strip()
                texte = (c.texte or prix_affiche(p.get("unit_price_ht"))).strip()
                lien = (c.lien or f"{base.rstrip('/')}/api/public/og/product/{p['id']}").strip()
                produit_id = p["id"]
            else:
                image, titre = url_absolue(c.image_url, base), (c.titre or "").strip()
                # Lot 78 — carte libre sans lien : lien par défaut réglé sur la page Carrousel
                texte, lien, produit_id = (c.texte or "").strip(), (c.lien or "").strip() or lien_defaut, None
            if not image_acceptee(image):
                raise HTTPException(status_code=400, detail=f"Carte {i} : image JPEG ou PNG publique (https) obligatoire")
            if not titre:
                raise HTTPException(status_code=400, detail=f"Carte {i} : titre obligatoire")
            if not lien_accepte(lien):
                raise HTTPException(status_code=400, detail=f"Carte {i} : lien manquant ou invalide (https://…) — "
                                                            "saisissez-le, ou réglez un « lien par défaut » sur la page Carrousel")
            prets.append({"source": c.source, "produit_id": produit_id, "image_url": image,
                          "titre": titre[:60], "texte": texte[:80], "lien": lien})
        return prets

    # --- Destinataires -------------------------------------------------------
    async def _contacts_portail(user: dict) -> Dict[str, Any]:
        ids = await visible_client_ids(user)
        contacts = await db.directory_contacts.find(
            {"client_id": {"$in": ids}},
            {"_id": 0, "id": 1, "name": 1, "company": 1, "whatsapp": 1, "phone": 1, "tags": 1,
             "accepte_whatsapp": 1, "accepte_whatsapp_le": 1, "accepte_whatsapp_moyen": 1}).sort("name", 1).to_list(5000)
        groupes = await db.contact_groups.find(
            {"client_id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1, "color": 1, "contact_ids": 1}
        ).sort("name", 1).to_list(500)
        lignes = [{"id": c["id"], "nom": c.get("name") or "", "societe": c.get("company") or "",
                   "telephone": c.get("whatsapp") or c.get("phone") or "",
                   "accepte": bool(c.get("accepte_whatsapp")), "accepte_le": c.get("accepte_whatsapp_le"),
                   "moyen": c.get("accepte_whatsapp_moyen")}
                  for c in contacts]
        # Lot 78.1 — les utilisateurs suivis du client sont aussi des destinataires possibles
        suivis_docs = await db.tracked_users.find({"client_id": {"$in": ids}}, {
            "_id": 0, "id": 1, "name": 1, "whatsapp_number": 1, "phone": 1,
            "accepte_whatsapp": 1, "accepte_whatsapp_le": 1, "accepte_whatsapp_moyen": 1}).to_list(2000)
        suivis = [_ligne(t, t.get("name"), "Utilisateur suivi", t.get("whatsapp_number") or t.get("phone"))
                  for t in suivis_docs if t.get("id")]
        lignes = sorted(lignes + suivis, key=lambda x: x["nom"].lower())
        liste_groupes = [{"id": g["id"], "nom": g.get("name") or "", "couleur": g.get("color"),
                          "contact_ids": g.get("contact_ids") or []} for g in groupes]
        if suivis:
            liste_groupes.insert(0, {"id": "@suivis", "nom": "Utilisateurs suivis", "couleur": None,
                                     "contact_ids": [x["id"] for x in suivis]})
        return {"contacts": lignes, "groupes": liste_groupes}

    def _filtre_clients(ids: Optional[List[str]] = None) -> dict:
        q: Dict[str, Any] = {
            "role": {"$in": ROLES_CLIENTS}, "email": {"$nin": [COMPTE_PLATEFORME]},
            "$or": [{"parent_client_id": {"$exists": False}}, {"parent_client_id": {"$in": [None, ""]}}],
        }
        if ids is not None:
            q["id"] = {"$in": ids}
        return q

    def _ligne(doc: dict, nom: str, societe: str, telephone: str) -> dict:
        """Une ligne de la liste des destinataires (même forme pour clients, suivis et contacts)."""
        return {"id": doc["id"], "nom": nom or "", "societe": societe or "", "telephone": telephone or "",
                "accepte": bool(doc.get("accepte_whatsapp")), "accepte_le": doc.get("accepte_whatsapp_le"),
                "moyen": doc.get("accepte_whatsapp_moyen")}   # lot 79 : bouton, mot-clé ou noté à la main

    def _portees_admin(user: Optional[dict]) -> List[str]:
        """Lot 78.1 — « mes contacts » de l'administration : ceux rangés sous le compte admin connecté."""
        return [x for x in {(user or {}).get("id"), (user or {}).get("client_id")} if x]

    async def _clients_admin(user: Optional[dict] = None) -> Dict[str, Any]:
        """Destinataires de l'administration SAWALI.
        Lot 78.1 : en plus des clients, les utilisateurs suivis (tracked_users) et les contacts
        de l'annuaire de l'administration ; des groupes « Clients », « Utilisateurs suivis »,
        « Mes contacts » et les groupes de contacts de l'administration permettent de tout cocher d'un clic."""
        comptes = await db.users.find(_filtre_clients(), {
            "_id": 0, "id": 1, "company": 1, "full_name": 1, "email": 1, "client_code": 1,
            "whatsapp_number": 1, "phone": 1, "accepte_whatsapp": 1, "accepte_whatsapp_le": 1, "accepte_whatsapp_moyen": 1}).to_list(3000)
        noms_clients = {c["id"]: c.get("company") or c.get("full_name") or c.get("email") or "" for c in comptes}
        clients = [_ligne(c, noms_clients[c["id"]], f"Client {c.get('client_code') or ''}".strip(),
                          c.get("whatsapp_number") or c.get("phone")) for c in comptes]
        # Utilisateurs suivis : rattachés à un client (on affiche le nom du client à côté)
        suivis_docs = await db.tracked_users.find({}, {
            "_id": 0, "id": 1, "name": 1, "client_id": 1, "whatsapp_number": 1, "phone": 1,
            "accepte_whatsapp": 1, "accepte_whatsapp_le": 1, "accepte_whatsapp_moyen": 1}).to_list(5000)
        suivis = [_ligne(t, t.get("name"), f"Suivi · {noms_clients.get(t.get('client_id'), '')}".rstrip(" ·"),
                         t.get("whatsapp_number") or t.get("phone")) for t in suivis_docs if t.get("id")]
        # Contacts de l'annuaire de l'administration
        portees = _portees_admin(user)
        contacts_docs = await db.directory_contacts.find({"client_id": {"$in": portees}}, {
            "_id": 0, "id": 1, "name": 1, "company": 1, "whatsapp": 1, "phone": 1,
            "accepte_whatsapp": 1, "accepte_whatsapp_le": 1, "accepte_whatsapp_moyen": 1}).to_list(5000) if portees else []
        contacts = [_ligne(c, c.get("name"), f"Contact · {c.get('company') or ''}".rstrip(" ·"),
                           c.get("whatsapp") or c.get("phone")) for c in contacts_docs if c.get("id")]
        groupes_docs = await db.contact_groups.find({"client_id": {"$in": portees}}, {
            "_id": 0, "id": 1, "name": 1, "color": 1, "contact_ids": 1}).sort("name", 1).to_list(500) if portees else []
        lignes = clients + suivis + contacts
        lignes.sort(key=lambda x: x["nom"].lower())
        groupes = [{"id": "@clients", "nom": "Clients", "couleur": None, "contact_ids": [x["id"] for x in clients]},
                   {"id": "@suivis", "nom": "Utilisateurs suivis", "couleur": None, "contact_ids": [x["id"] for x in suivis]},
                   {"id": "@contacts", "nom": "Mes contacts", "couleur": None, "contact_ids": [x["id"] for x in contacts]}]
        groupes += [{"id": g["id"], "nom": g.get("name") or "", "couleur": g.get("color"),
                     "contact_ids": g.get("contact_ids") or []} for g in groupes_docs]
        return {"contacts": lignes, "groupes": [g for g in groupes if g["contact_ids"]]}

    def _dedoublonner(personnes: List[dict]) -> List[dict]:
        """Seulement ceux qui ont accepté et ont un numéro ; un numéro reçoit une seule fois."""
        vus, retenus = set(), []
        for p in personnes:
            tel = numero_whatsapp(p.get("telephone"))
            if p.get("accepte") and len(tel) >= 10 and tel not in vus:
                vus.add(tel)
                retenus.append({"id": p["id"], "nom": p["nom"], "telephone": tel, "statut": "EN_ATTENTE"})
        return retenus

    # --- Campagne ------------------------------------------------------------
    async def _creer_campagne(*, perimetre: str, user: dict, tenant_id: Optional[str], envoi: EnvoiIn,
                              personnes: List[dict], expediteur: str, bg: BackgroundTasks) -> dict:
        r = await _reglages(tenant_id)
        if not r["whatsapp_configure"]:
            raise HTTPException(status_code=400, detail="WhatsApp n'est pas configuré pour ce numéro")
        if not r["modele"]:
            raise HTTPException(status_code=400, detail="Modèles de carrousel non renseignés : voir les réglages "
                                                        "de l'administration SAWALI")
        prefs = await _preferences(perimetre, tenant_id)
        try:
            cartes = await _preparer_cartes(envoi.cartes, tenant_id if perimetre == "client" else None, prefs["lien_defaut"])
        except HTTPException as exc:
            # Lot 79.1 — motif du refus gardé dans le journal (aide au diagnostic d'un « rien ne se passe »)
            logger.info("[carrousel] envoi refusé (%s, %s) : %s", perimetre, tenant_id, exc.detail)
            raise
        destinataires = _dedoublonner(personnes)
        if not destinataires:
            logger.info("[carrousel] envoi refusé (%s, %s) : aucun destinataire consentant", perimetre, tenant_id)
            raise HTTPException(status_code=400, detail="Aucun destinataire n'a accepté de recevoir vos messages "
                                                        "WhatsApp (ou aucun numéro valable)")
        if len(destinataires) > DESTINATAIRES_MAX:
            raise HTTPException(status_code=400, detail=f"{DESTINATAIRES_MAX} destinataires au maximum par campagne")
        campagne_id = secrets.token_hex(8)
        for i, c in enumerate(cartes):
            c["code_lien"] = secrets.token_urlsafe(6)
            await db.carrousel_liens.insert_one({"code": c["code_lien"], "cible": c["lien"], "campagne_id": campagne_id,
                                                 "carte_index": i, "clics": 0, "cree_le": _maintenant()})
        doc = {
            "id": campagne_id, "perimetre": perimetre, "tenant_id": tenant_id, "cree_le": _maintenant(),
            "cree_par": user["id"], "cree_par_nom": user.get("full_name") or user.get("email"),
            "expediteur": expediteur[:60], "message": envoi.message, "cartes": cartes,
            "modele": nom_modele(r["modele"], len(cartes)), "langue": r["langue"],
            "creds_tenant": r["creds_tenant"], "destinataires": destinataires,
            "statut": "EN_COURS", "compte": {"total": len(destinataires), "envoyes": 0, "echecs": 0},
        }
        await db.carrousel_campagnes.insert_one(dict(doc))
        bg.add_task(_executer, campagne_id)
        return {"id": campagne_id, "destinataires": len(destinataires), "modele": doc["modele"],
                "ignores": len(personnes) - len(destinataires)}

    async def _executer(campagne_id: str) -> None:
        """Envoi un par un ; chaque résultat est gardé sur la campagne et dans
        whatsapp_messages (compteurs d'usage de la plateforme)."""
        c = await db.carrousel_campagnes.find_one({"id": campagne_id}, {"_id": 0})
        if not c:
            return
        comps = composants(c["expediteur"], c["message"], c["cartes"])
        envoyes = echecs = 0
        for i, d in enumerate(c["destinataires"]):
            try:
                r = await wa_send_template(d["telephone"], c["modele"], c["langue"], comps,
                                           tenant_id=c.get("creds_tenant"))
            except Exception as exc:  # noqa: BLE001
                r = {"ok": False, "status": None, "message_id": None, "error": str(exc)[:300]}
            statut = "ENVOYE" if r.get("ok") else "ECHEC"
            envoyes += statut == "ENVOYE"
            echecs += statut == "ECHEC"
            await db.carrousel_campagnes.update_one({"id": campagne_id}, {"$set": {
                f"destinataires.{i}.statut": statut, f"destinataires.{i}.message_id": r.get("message_id"),
                f"destinataires.{i}.erreur": (r.get("error") or None) and str(r["error"])[:300],
                "compte.envoyes": envoyes, "compte.echecs": echecs}})
            try:
                await db.whatsapp_messages.insert_one({
                    "id": secrets.token_hex(12), "client_id": c.get("tenant_id"),
                    "sender_id": c["cree_par"], "sender_label": c.get("cree_par_nom"), "to": d["telephone"],
                    "template_name": c["modele"], "language_code": c["langue"],
                    "contact_id": d["id"] if c["perimetre"] == "client" else None,
                    "recipient_kind": "contact" if c["perimetre"] == "client" else "client",
                    "recipient_label": d["nom"], "bulk": True, "carrousel_id": campagne_id,
                    "ok": bool(r.get("ok")), "status": r.get("status"), "message_id": r.get("message_id"),
                    "error": r.get("error"), "created_at": _maintenant()})
            except Exception:  # noqa: BLE001 — le journal ne bloque jamais l'envoi
                pass
        await db.carrousel_campagnes.update_one({"id": campagne_id}, {"$set": {
            "statut": "TERMINEE", "termine_le": _maintenant()}})

    async def _campagnes(filtre: dict) -> List[dict]:
        lignes = await db.carrousel_campagnes.find(filtre, {"_id": 0, "destinataires": 0}).sort(
            "cree_le", -1).limit(50).to_list(50)
        for c in lignes:
            codes = [x.get("code_lien") for x in c.get("cartes") or []]
            clics = {x["code"]: x.get("clics", 0) async for x in db.carrousel_liens.find(
                {"code": {"$in": codes}}, {"_id": 0, "code": 1, "clics": 1})}
            for x in c.get("cartes") or []:
                x["clics"] = clics.get(x.get("code_lien"), 0)
        return lignes

    async def _campagne(filtre: dict) -> dict:
        c = await db.carrousel_campagnes.find_one(filtre, {"_id": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Campagne introuvable")
        return c

    async def _noter_consentement(collection, filtre: dict, accepte: bool, user: dict) -> int:
        maj = {"accepte_whatsapp": accepte, "accepte_whatsapp_le": _maintenant() if accepte else None,
               "accepte_whatsapp_par": user.get("email") or user["id"],
               "accepte_whatsapp_moyen": f"noté par {user.get('email') or user['id']}"}   # lot 79 : traçabilité
        res = await collection.update_many(filtre, {"$set": maj})
        return res.modified_count

    # =======================================================================
    # Lien du bouton (public) : compte le clic et redirige
    # =======================================================================
    @api.get("/public/carrousel/l/", tags=["Public"], include_in_schema=False)
    async def ouvrir_lien_vide():
        # Lot 78.1 — Meta vérifie l'adresse du bouton sans code : on redirige vers le site au lieu d'un 404
        return RedirectResponse(base_publique() or "/", status_code=302)

    @api.get("/public/carrousel/l/{code}", tags=["Public"])
    async def ouvrir_lien(code: str):
        doc = await db.carrousel_liens.find_one_and_update({"code": code[:40]}, {"$inc": {"clics": 1}},
                                                          projection={"_id": 0, "cible": 1})
        if not doc:
            return RedirectResponse(base_publique() or "/", status_code=302)
        return RedirectResponse(doc["cible"], status_code=302)

    # =======================================================================
    # Portail client
    # =======================================================================
    @api.get("/me/whatsapp/carrousel", tags=["Portail Client — Carrousel WhatsApp"])
    async def etat_portail(user: dict = Depends(utilisateur)):
        tid = _tenant_id(user)
        etat = await _etat(tid, {"perimetre": "client", "tenant_id": tid})
        etat["ia_images"] = bool(await fonction_active(user, "ai_image_gen"))   # lot 75
        return etat

    @api.get("/me/whatsapp/carrousel/produits", tags=["Portail Client — Carrousel WhatsApp"])
    async def produits_portail(user: dict = Depends(utilisateur)):
        return {"produits": await _produits(_tenant_id(user))}

    @api.get("/me/whatsapp/carrousel/images", tags=["Portail Client — Carrousel WhatsApp"])
    async def images_portail(user: dict = Depends(utilisateur)):
        return {"images": await _images(_tenant_id(user), admin=False)}

    @api.post("/me/whatsapp/carrousel/images", tags=["Portail Client — Carrousel WhatsApp"])
    async def envoyer_image_portail(fichier: UploadFile = File(...), user: dict = Depends(utilisateur)):
        return await _envoyer_image(fichier, _tenant_id(user), user)

    # Lot 77 — carrousels nommés (portail)
    @api.get("/me/whatsapp/carrousel/brouillons", tags=["Portail Client — Carrousel WhatsApp"])
    async def brouillons_portail(user: dict = Depends(utilisateur)):
        return await _lister_brouillons("client", _tenant_id(user))

    @api.post("/me/whatsapp/carrousel/brouillons", tags=["Portail Client — Carrousel WhatsApp"])
    async def creer_brouillon_portail(data: BrouillonIn, user: dict = Depends(utilisateur)):
        return await _enregistrer_brouillon(data, "client", _tenant_id(user), user)

    @api.put("/me/whatsapp/carrousel/brouillons/{bid}", tags=["Portail Client — Carrousel WhatsApp"])
    async def modifier_brouillon_portail(bid: str, data: BrouillonIn, user: dict = Depends(utilisateur)):
        return await _enregistrer_brouillon(data, "client", _tenant_id(user), user, bid)

    @api.post("/me/whatsapp/carrousel/brouillons/{bid}/dupliquer", tags=["Portail Client — Carrousel WhatsApp"])
    async def dupliquer_brouillon_portail(bid: str, user: dict = Depends(utilisateur)):
        return await _dupliquer_brouillon(bid, "client", _tenant_id(user), user)

    @api.put("/me/whatsapp/carrousel/brouillons/{bid}/partages", tags=["Portail Client — Carrousel WhatsApp"])
    async def partager_portail(bid: str, data: PartageIn, user: dict = Depends(utilisateur)):
        _peut_partager(user)
        return await _partager(bid, data, "client", _tenant_id(user))

    @api.post("/me/whatsapp/carrousel/demande-accord", tags=["Portail Client — Carrousel WhatsApp"])
    async def demande_accord_portail(data: DemandeAccordIn, user: dict = Depends(utilisateur)):
        voulus = set(data.ids)
        personnes = [c for c in (await _contacts_portail(user))["contacts"] if c["id"] in voulus]
        return await _demander_accord(personnes, _tenant_id(user))

    @api.get("/me/whatsapp/carrousel/lien-accord", tags=["Portail Client — Carrousel WhatsApp"])
    async def lien_accord_portail(user: dict = Depends(utilisateur)):
        return await _lien_accord(_tenant_id(user))

    @api.delete("/me/whatsapp/carrousel/brouillons/{bid}", tags=["Portail Client — Carrousel WhatsApp"])
    async def supprimer_brouillon_portail(bid: str, user: dict = Depends(utilisateur)):
        return await _supprimer_brouillon(bid, "client", _tenant_id(user))

    @api.get("/me/whatsapp/carrousel/brouillon-auto", tags=["Portail Client — Carrousel WhatsApp"])
    async def lire_auto_portail(user: dict = Depends(utilisateur)):
        return await _lire_auto("client", _tenant_id(user), user)

    @api.put("/me/whatsapp/carrousel/brouillon-auto", tags=["Portail Client — Carrousel WhatsApp"])
    async def ecrire_auto_portail(data: BrouillonAutoIn, user: dict = Depends(utilisateur)):
        return await _ecrire_auto(data, "client", _tenant_id(user), user)

    @api.get("/me/whatsapp/carrousel/preferences", tags=["Portail Client — Carrousel WhatsApp"])
    async def preferences_portail(user: dict = Depends(utilisateur)):
        return await _preferences("client", _tenant_id(user))

    @api.put("/me/whatsapp/carrousel/preferences", tags=["Portail Client — Carrousel WhatsApp"])
    async def ecrire_preferences_portail(data: PreferencesIn, user: dict = Depends(utilisateur)):
        return await _ecrire_preferences(data, "client", _tenant_id(user))

    @api.get("/me/whatsapp/carrousel/statuts-meta", tags=["Portail Client — Carrousel WhatsApp"])
    async def statuts_meta_portail(rafraichir: bool = False, user: dict = Depends(utilisateur)):
        return await _statuts_meta(_tenant_id(user), rafraichir)

    async def _ia_autorisee(user: dict) -> None:
        """Portail : la génération d'images IA est une fonction payante, activée par client."""
        if not await fonction_active(user, "ai_image_gen"):
            raise HTTPException(status_code=403, detail="La génération d'images par l'IA n'est pas activée pour votre compte. "
                                                        "Demandez son activation à votre administrateur SAWALI.")

    @api.post("/me/whatsapp/carrousel/images/ia", tags=["Portail Client — Carrousel WhatsApp"])
    async def generer_image_ia_portail(data: ImageIaIn, user: dict = Depends(utilisateur)):
        await _ia_autorisee(user)
        return await _generer_image_ia(data, _tenant_id(user), user)

    @api.post("/me/whatsapp/carrousel/images/ia/{apercu_id}/retenir", tags=["Portail Client — Carrousel WhatsApp"])
    async def retenir_image_ia_portail(apercu_id: str, user: dict = Depends(utilisateur)):
        await _ia_autorisee(user)
        return await _retenir_image_ia(apercu_id, _tenant_id(user), user)

    @api.get("/me/whatsapp/carrousel/destinataires", tags=["Portail Client — Carrousel WhatsApp"])
    async def destinataires_portail(user: dict = Depends(utilisateur)):
        return await _contacts_portail(user)

    @api.put("/me/whatsapp/carrousel/consentements", tags=["Portail Client — Carrousel WhatsApp"])
    async def consentements_portail(data: ConsentementIn, user: dict = Depends(utilisateur)):
        ids = await visible_client_ids(user)
        n = await _noter_consentement(db.directory_contacts, {"id": {"$in": data.ids}, "client_id": {"$in": ids}},
                                      data.accepte, user)
        # Lot 78.1 — consentement des utilisateurs suivis du client
        n += await _noter_consentement(db.tracked_users, {"id": {"$in": data.ids}, "client_id": {"$in": ids}},
                                       data.accepte, user)
        return {"modifies": n}

    @api.post("/me/whatsapp/carrousel/envoyer", status_code=202, tags=["Portail Client — Carrousel WhatsApp"])
    async def envoyer_portail(envoi: EnvoiIn, bg: BackgroundTasks, user: dict = Depends(utilisateur)):
        tid = _tenant_id(user)
        annuaire = await _contacts_portail(user)
        voulus = set(envoi.ids)
        for g in annuaire["groupes"]:
            if g["id"] in envoi.groupes:
                voulus.update(g["contact_ids"])
        personnes = [c for c in annuaire["contacts"] if c["id"] in voulus]
        client = await db.users.find_one({"id": tid}, {"_id": 0, "company": 1, "full_name": 1}) or {}
        expediteur = client.get("company") or client.get("full_name") or user.get("company") or "SAWALI"
        return await _creer_campagne(perimetre="client", user=user, tenant_id=tid, envoi=envoi,
                                     personnes=personnes, expediteur=expediteur, bg=bg)

    @api.get("/me/whatsapp/carrousel/campagnes", tags=["Portail Client — Carrousel WhatsApp"])
    async def campagnes_portail(user: dict = Depends(utilisateur)):
        return {"campagnes": await _campagnes({"perimetre": "client", "tenant_id": _tenant_id(user)})}

    @api.get("/me/whatsapp/carrousel/campagnes/{cid}", tags=["Portail Client — Carrousel WhatsApp"])
    async def campagne_portail(cid: str, user: dict = Depends(utilisateur)):
        return await _campagne({"id": cid, "perimetre": "client", "tenant_id": _tenant_id(user)})

    # =======================================================================
    # Administration SAWALI → ses clients
    # =======================================================================
    @api.get("/admin/whatsapp/carrousel", tags=["Admin — Carrousel WhatsApp"])
    async def etat_admin(_: dict = Depends(get_current_admin)):
        return {**(await _etat(None, {"perimetre": "admin"})), "ia_images": True}   # lot 75

    @api.get("/admin/whatsapp/carrousel/reglages", tags=["Admin — Carrousel WhatsApp"])
    async def lire_reglages(tenant_id: Optional[str] = None, _: dict = Depends(get_current_admin)):
        r = await _reglages(tenant_id)
        return {k: r[k] for k in ("numero", "whatsapp_configure", "modele", "langue")} | {
            "url_bouton_modele": _url_bouton()}

    @api.put("/admin/whatsapp/carrousel/reglages", tags=["Admin — Carrousel WhatsApp"])
    async def ecrire_reglages(data: ReglagesIn, _: dict = Depends(get_current_admin)):
        maj = {"wa_carrousel_modele": data.modele, "wa_carrousel_langue": data.langue}
        if data.tenant_id:
            if not await db.tenant_smart_comm.find_one({"tenant_id": data.tenant_id}, {"_id": 1}):
                raise HTTPException(status_code=400, detail="Ce client n'a pas son propre numéro WhatsApp : "
                                                            "il utilise les modèles de la plateforme")
            await db.tenant_smart_comm.update_one({"tenant_id": data.tenant_id}, {"$set": maj})
        else:
            await db.settings.update_one({"_id": "global"}, {"$set": maj}, upsert=True)
        return {"ok": True}

    @api.post("/admin/whatsapp/carrousel/modeles-meta", tags=["Admin — Carrousel WhatsApp"])
    async def creer_modeles_meta(data: ReglagesIn, _: dict = Depends(get_current_admin)):
        """Lot 76 — bouton « Créer les modèles chez Meta » : dépose les 9 modèles <préfixe>_2 … _10
        (catégorie MARKETING, type carrousel) sur le compte WhatsApp Business qui envoie
        (plateforme, ou client qui a son propre numéro), puis enregistre le préfixe et la langue."""
        from routes import carrousel_modeles_meta as cmm
        creds = await resolve_wa_credentials(data.tenant_id)
        jeton, waba = (creds.get("access_token") or "").strip(), (creds.get("waba_id") or "").strip()
        if not jeton or not waba:
            raise HTTPException(status_code=400, detail="WhatsApp Business incomplet : jeton d'accès ou identifiant du compte "
                                                        "WhatsApp Business (WABA) manquant dans les Paramètres.")
        s_glob = await db.settings.find_one({"_id": "global"}, {"_id": 0, "meta_app_id": 1, "wa_graph_version": 1}) or {}
        # Lot 76.1 — App ID saisi dans « Intégration Meta » ; sinon retrouvé à partir du jeton WhatsApp
        app_id = (s_glob.get("meta_app_id") or "").strip() or None
        version = (s_glob.get("wa_graph_version") or "v22.0").strip()
        try:
            resultats = await cmm.creer_modeles(version=version, app_id=app_id, waba_id=waba, jeton=jeton,
                                                prefixe=data.modele, langue=data.langue, url_bouton=_url_bouton())
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if any(r["statut"] in ("soumis", "existe déjà") for r in resultats):
            await ecrire_reglages(data, _)          # préfixe et langue retenus pour les envois
        _cache_statuts.clear()                      # lot 77 : les pastilles relisent Meta
        return {"resultats": resultats, "url_bouton": _url_bouton()}

    @api.get("/admin/whatsapp/carrousel/produits", tags=["Admin — Carrousel WhatsApp"])
    async def produits_admin(_: dict = Depends(get_current_admin)):
        return {"produits": await _produits(None)}

    @api.get("/admin/whatsapp/carrousel/images", tags=["Admin — Carrousel WhatsApp"])
    async def images_admin(_: dict = Depends(get_current_admin)):
        return {"images": await _images(None, admin=True)}

    @api.post("/admin/whatsapp/carrousel/images", tags=["Admin — Carrousel WhatsApp"])
    async def envoyer_image_admin(fichier: UploadFile = File(...), user: dict = Depends(get_current_admin)):
        return await _envoyer_image(fichier, user["id"], user)

    # Lot 77 — carrousels nommés (administration)
    @api.get("/admin/whatsapp/carrousel/brouillons", tags=["Admin — Carrousel WhatsApp"])
    async def brouillons_admin(_: dict = Depends(get_current_admin)):
        return await _lister_brouillons("admin", None)

    @api.post("/admin/whatsapp/carrousel/brouillons", tags=["Admin — Carrousel WhatsApp"])
    async def creer_brouillon_admin(data: BrouillonIn, user: dict = Depends(get_current_admin)):
        return await _enregistrer_brouillon(data, "admin", None, user)

    @api.put("/admin/whatsapp/carrousel/brouillons/{bid}", tags=["Admin — Carrousel WhatsApp"])
    async def modifier_brouillon_admin(bid: str, data: BrouillonIn, user: dict = Depends(get_current_admin)):
        return await _enregistrer_brouillon(data, "admin", None, user, bid)

    @api.post("/admin/whatsapp/carrousel/brouillons/{bid}/dupliquer", tags=["Admin — Carrousel WhatsApp"])
    async def dupliquer_brouillon_admin(bid: str, user: dict = Depends(get_current_admin)):
        return await _dupliquer_brouillon(bid, "admin", None, user)

    @api.put("/admin/whatsapp/carrousel/brouillons/{bid}/partages", tags=["Admin — Carrousel WhatsApp"])
    async def partager_admin(bid: str, data: PartageIn, user: dict = Depends(get_current_admin)):
        return await _partager(bid, data, "admin", None)

    @api.post("/admin/whatsapp/carrousel/demande-accord", tags=["Admin — Carrousel WhatsApp"])
    async def demande_accord_admin(data: DemandeAccordIn, user: dict = Depends(get_current_admin)):
        voulus = set(data.ids)
        personnes = [c for c in (await _clients_admin(user))["contacts"] if c["id"] in voulus]
        return await _demander_accord(personnes, None)

    @api.get("/admin/whatsapp/carrousel/lien-accord", tags=["Admin — Carrousel WhatsApp"])
    async def lien_accord_admin(_: dict = Depends(get_current_admin)):
        return await _lien_accord(None)

    @api.delete("/admin/whatsapp/carrousel/brouillons/{bid}", tags=["Admin — Carrousel WhatsApp"])
    async def supprimer_brouillon_admin(bid: str, _: dict = Depends(get_current_admin)):
        return await _supprimer_brouillon(bid, "admin", None)

    @api.get("/admin/whatsapp/carrousel/brouillon-auto", tags=["Admin — Carrousel WhatsApp"])
    async def lire_auto_admin(user: dict = Depends(get_current_admin)):
        return await _lire_auto("admin", None, user)

    @api.put("/admin/whatsapp/carrousel/brouillon-auto", tags=["Admin — Carrousel WhatsApp"])
    async def ecrire_auto_admin(data: BrouillonAutoIn, user: dict = Depends(get_current_admin)):
        return await _ecrire_auto(data, "admin", None, user)

    @api.get("/admin/whatsapp/carrousel/preferences", tags=["Admin — Carrousel WhatsApp"])
    async def preferences_admin(_: dict = Depends(get_current_admin)):
        return await _preferences("admin", None)

    @api.put("/admin/whatsapp/carrousel/preferences", tags=["Admin — Carrousel WhatsApp"])
    async def ecrire_preferences_admin(data: PreferencesIn, _: dict = Depends(get_current_admin)):
        return await _ecrire_preferences(data, "admin", None)

    @api.get("/admin/whatsapp/carrousel/statuts-meta", tags=["Admin — Carrousel WhatsApp"])
    async def statuts_meta_admin(rafraichir: bool = False, _: dict = Depends(get_current_admin)):
        return await _statuts_meta(None, rafraichir)

    @api.post("/admin/whatsapp/carrousel/images/ia", tags=["Admin — Carrousel WhatsApp"])
    async def generer_image_ia_admin(data: ImageIaIn, user: dict = Depends(get_current_admin)):
        return await _generer_image_ia(data, user["id"], user)

    @api.post("/admin/whatsapp/carrousel/images/ia/{apercu_id}/retenir", tags=["Admin — Carrousel WhatsApp"])
    async def retenir_image_ia_admin(apercu_id: str, user: dict = Depends(get_current_admin)):
        return await _retenir_image_ia(apercu_id, user["id"], user)

    @api.get("/admin/whatsapp/carrousel/destinataires", tags=["Admin — Carrousel WhatsApp"])
    async def destinataires_admin(user: dict = Depends(get_current_admin)):
        return await _clients_admin(user)

    @api.put("/admin/whatsapp/carrousel/consentements", tags=["Admin — Carrousel WhatsApp"])
    async def consentements_admin(data: ConsentementIn, user: dict = Depends(get_current_admin)):
        # Lot 78.1 — le consentement est noté là où vit la personne : compte client, utilisateur suivi ou contact
        n = await _noter_consentement(db.users, _filtre_clients(data.ids), data.accepte, user)
        n += await _noter_consentement(db.tracked_users, {"id": {"$in": data.ids}}, data.accepte, user)
        portees = _portees_admin(user)
        if portees:
            n += await _noter_consentement(db.directory_contacts, {"id": {"$in": data.ids}, "client_id": {"$in": portees}},
                                           data.accepte, user)
        return {"modifies": n}

    @api.post("/admin/whatsapp/carrousel/envoyer", status_code=202, tags=["Admin — Carrousel WhatsApp"])
    async def envoyer_admin(envoi: EnvoiIn, bg: BackgroundTasks, user: dict = Depends(get_current_admin)):
        annuaire = await _clients_admin(user)
        # Lot 78.1 — les groupes cochés (Clients, Utilisateurs suivis, Mes contacts…) sont aussi pris en compte
        voulus = set(envoi.ids)
        for g in annuaire["groupes"]:
            if g["id"] in set(envoi.groupes or []):
                voulus.update(g["contact_ids"])
        personnes = [c for c in annuaire["contacts"] if c["id"] in voulus]
        return await _creer_campagne(perimetre="admin", user=user, tenant_id=None, envoi=envoi,
                                     personnes=personnes, expediteur="SAWALI SMART SYSTEMS", bg=bg)

    @api.get("/admin/whatsapp/carrousel/campagnes", tags=["Admin — Carrousel WhatsApp"])
    async def campagnes_admin(_: dict = Depends(get_current_admin)):
        return {"campagnes": await _campagnes({"perimetre": "admin"})}

    @api.get("/admin/whatsapp/carrousel/campagnes/{cid}", tags=["Admin — Carrousel WhatsApp"])
    async def campagne_admin(cid: str, _: dict = Depends(get_current_admin)):
        return await _campagne({"id": cid, "perimetre": "admin"})

    return {"executer": _executer}
