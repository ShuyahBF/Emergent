"""Lot 235 — Annonceurs des plateformes (Paiement Mobile…) : devis en temps réel, médias chiffrés, paiement, statistiques.

Demande du propriétaire (17/10/2026) : « Un abonné peut devenir annonceur. Il choisit sa formule parmi les paramètres
d'enregistrement de SAWALI, envoie ses images ou vidéo avec une taille raisonnable, médias qui seront cryptés, et paie.
Un calculateur lui affiche en temps réel son devis en fonction des paramètres choisis (format, durée, ses dates, etc.).
Seul SAWALI peut corriger les montants si besoin. Il reçoit son devis, paie et peut suivre à tout moment ses statistiques. »

Pour un développeur WinDev (équivalent de deux fichiers HFSQL + une procédure de calcul) :
  - réglages `settings._id = "annonceurs_plateformes"` : TARIFS (formats avec prix par jour, options en %, remises par durée,
    tailles maximales des médias). Modifiables SEULEMENT par l'administrateur principal (rubrique des Paramètres) ;
  - fichier `annonceurs_campagnes` : une demande d'annonce (annonceur, format, dates, devis figé, média chiffré, état) ;
  - le calcul du devis est UNE fonction pure (`calculer_devis`), la même pour l'aperçu en direct et pour le devis enregistré :
    le montant payé ne vient JAMAIS du navigateur, il est recalculé ici à partir des tarifs ;
  - le média est chiffré (AES-256-GCM, clé du serveur) AVANT d'être rangé dans le stockage R2 ; il n'est déchiffré que pour
    être affiché dans l'annonce une fois la campagne payée ;
  - paiement : page PawaPay hébergée, ou PI-SPI manuel (confirmé par l'administrateur) ; à la confirmation (UNE seule fois),
    la campagne est publiée dans la régie existante (`ad_banners`, emplacement « paiementmobile ») avec ses dates ;
  - statistiques : lues dans la régie (impressions, clics, taux de clic, jour par jour).

Routes SIGNÉES des plateformes (mêmes en-têtes que les formules : X-Emetteur, X-Timestamp, X-Signature) :
    POST /api/annonceurs-plateformes/tarifs     {utilisateur}                       → tarifs publics + « est_abonne »
    POST /api/annonceurs-plateformes/devis      {utilisateur, format, debut, fin, options} → devis calculé (rien n'est enregistré)
    POST /api/annonceurs-plateformes/creer      {utilisateur, nom, annonceur, format, debut, fin, options, lien, media} → campagne + devis
    POST /api/annonceurs-plateformes/campagnes  {utilisateur}                       → mes campagnes
    POST /api/annonceurs-plateformes/payer      {utilisateur, campagne_id, mode: pawapay|pispi, retour?} → lien PawaPay ou bloc PI-SPI
    POST /api/annonceurs-plateformes/declarer   {utilisateur, campagne_id, reference_bancaire} → PI-SPI : référence déclarée
    POST /api/annonceurs-plateformes/etat       {utilisateur, campagne_id, deposit_id?} → état (relit PawaPay si besoin)
    POST /api/annonceurs-plateformes/stats      {utilisateur, campagne_id}          → impressions, clics, taux de clic, jour par jour
Public :
    GET  /api/public/annonceurs-plateformes/media/{jeton}  → média déchiffré (campagne payée seulement)
Administration (administrateur principal) :
    GET/PUT /api/admin/annonceurs-plateformes/tarifs · GET /api/admin/annonceurs-plateformes/campagnes
    PUT  …/campagnes/{id}/montant  (correction du montant, avant paiement) · POST …/campagnes/{id}/suspendre|reactiver
    POST …/campagnes/{id}/pispi/confirmer|refuser
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from routes.formules_plateformes import Utilisateur, jours_restants

logger = logging.getLogger("sawali.annonceurs_plateformes")

# Remplacements pour les tests : None en production (PawaPay réel, stockage R2 réel)
_transport: Optional[httpx.AsyncBaseTransport] = None
_ecrire: Optional[Callable] = None      # async (chemin, octets)
_lire: Optional[Callable] = None        # async (chemin) → octets

ID_REGLAGES = "annonceurs_plateformes"
PLACEMENT = "paiementmobile"
FONCTION = "annonceur_pm"       # fonction débloquée par la formule « Annonceur » (créée dans Formules des plateformes)
FLOW = "annonce_plateforme"
STATUTS_PISPI_OUVERTS = ("pispi_attente", "pispi_verification")
TYPES_IMAGE = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG", "image/webp": b"RIFF"}
TYPES_VIDEO = {"video/mp4": None, "video/webm": b"\x1a\x45\xdf\xa3"}     # mp4 : signature « ftyp » à l'offset 4

# Tarifs de départ (réglables ensuite par l'administrateur)
TARIFS_DEFAUT: Dict[str, Any] = {
    "formats": [
        {"code": "banniere_image", "libelle": "Bannière image", "media": "image", "prix_jour": 1000},
        {"code": "banniere_video", "libelle": "Bannière vidéo", "media": "video", "prix_jour": 2500},
    ],
    "options": [{"code": "avant", "libelle": "Mise en avant (affichée en premier)", "majoration_pct": 30}],
    "remises": [{"jours_min": 7, "remise_pct": 5}, {"jours_min": 15, "remise_pct": 10}, {"jours_min": 30, "remise_pct": 15}],
    "duree_min": 1, "duree_max": 90, "avance_max_jours": 90,
    "image_max_ko": 600, "video_max_mo": 6,
    "actif": True,
}


# ---------------------------------------------------------------------------
# Fonctions pures (testées sans base)
# ---------------------------------------------------------------------------
def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def valider_tarifs(t: Dict[str, Any]) -> Dict[str, Any]:
    """Contrôle et nettoie les tarifs saisis par l'administrateur (ValueError avec un message simple en cas d'erreur)."""
    formats, codes = [], set()
    for f in t.get("formats") or []:
        code = re.sub(r"[^a-z0-9_]", "", str(f.get("code") or "").lower())[:30]
        if not code or code in codes:
            raise ValueError("Chaque format a un code unique (lettres, chiffres, _).")
        if f.get("media") not in ("image", "video"):
            raise ValueError("Le type de média d'un format est « image » ou « video ».")
        prix = int(f.get("prix_jour") or 0)
        if not 0 < prix <= 10_000_000:
            raise ValueError("Le prix par jour d'un format doit être positif.")
        codes.add(code)
        formats.append({"code": code, "libelle": str(f.get("libelle") or code)[:60], "media": f["media"], "prix_jour": prix})
    if not formats:
        raise ValueError("Au moins un format est nécessaire.")
    options, ocodes = [], set()
    for o in t.get("options") or []:
        code = re.sub(r"[^a-z0-9_]", "", str(o.get("code") or "").lower())[:30]
        pct = float(o.get("majoration_pct") or 0)
        if not code or code in ocodes or not 0 <= pct <= 500:
            raise ValueError("Option invalide (code unique, majoration entre 0 et 500 %).")
        ocodes.add(code)
        options.append({"code": code, "libelle": str(o.get("libelle") or code)[:80], "majoration_pct": pct})
    remises = []
    for r in t.get("remises") or []:
        jours, pct = int(r.get("jours_min") or 0), float(r.get("remise_pct") or 0)
        if jours < 2 or not 0 < pct <= 90:
            raise ValueError("Remise invalide (à partir de 2 jours, entre 0 et 90 %).")
        remises.append({"jours_min": jours, "remise_pct": pct})
    remises.sort(key=lambda r: r["jours_min"])
    duree_min, duree_max = int(t.get("duree_min") or 1), int(t.get("duree_max") or 90)
    if not 1 <= duree_min <= duree_max <= 366:
        raise ValueError("Durées invalides (minimum ≥ 1, maximum ≤ 366 jours).")
    return {"formats": formats, "options": options, "remises": remises, "duree_min": duree_min, "duree_max": duree_max,
            "avance_max_jours": max(0, min(365, int(t.get("avance_max_jours") if t.get("avance_max_jours") is not None else 90))),
            "image_max_ko": max(50, min(3000, int(t.get("image_max_ko") or 600))), "video_max_mo": max(1, min(12, int(t.get("video_max_mo") or 6))),
            "actif": bool(t.get("actif", True))}


def lire_date(texte: Any) -> date:
    try:
        return date.fromisoformat(str(texte)[:10])
    except ValueError:
        raise ValueError("Date invalide (format AAAA-MM-JJ).")


def calculer_devis(tarifs: Dict[str, Any], code_format: str, debut: Any, fin: Any, options: List[str], aujourdhui: Optional[date] = None) -> Dict[str, Any]:
    """Devis d'une annonce. Fonction PURE : mêmes entrées → même montant, côté aperçu comme côté enregistrement.
    Montant = prix du jour × nombre de jours (début et fin INCLUS), + majoration des options, − remise de durée.
    Arrondi à l'unité (FCFA). ValueError avec un message simple si un paramètre est hors des limites."""
    f = next((x for x in tarifs["formats"] if x["code"] == code_format), None)
    if not f:
        raise ValueError("Format inconnu.")
    d1, d2 = lire_date(debut), lire_date(fin)
    if d2 < d1:
        raise ValueError("La date de fin précède la date de début.")
    jours = (d2 - d1).days + 1
    if not tarifs["duree_min"] <= jours <= tarifs["duree_max"]:
        raise ValueError(f"Durée de {tarifs['duree_min']} à {tarifs['duree_max']} jours.")
    auj = aujourdhui or _maintenant().date()
    if d1 < auj:
        raise ValueError("La date de début ne peut pas être passée.")
    if (d1 - auj).days > tarifs["avance_max_jours"]:
        raise ValueError(f"Début au plus tard dans {tarifs['avance_max_jours']} jours.")
    base = f["prix_jour"] * jours
    lignes = []
    majoration = 0.0
    for code in dict.fromkeys(options or []):
        o = next((x for x in tarifs["options"] if x["code"] == code), None)
        if not o:
            raise ValueError("Option inconnue.")
        m = base * o["majoration_pct"] / 100
        majoration += m
        lignes.append({"code": code, "libelle": o["libelle"], "montant": round(m)})
    avant_remise = base + majoration
    pct = 0.0
    for r in tarifs["remises"]:
        if jours >= r["jours_min"]:
            pct = r["remise_pct"]
    remise = avant_remise * pct / 100
    return {"format": f["code"], "format_libelle": f["libelle"], "media": f["media"], "debut": d1.isoformat(), "fin": d2.isoformat(),
            "jours": jours, "prix_jour": f["prix_jour"], "base": round(base), "options": lignes, "remise_pct": pct,
            "remise": round(remise), "total": round(avant_remise - remise), "devise": "XOF"}


def decoder_media(data_url: str, media_attendu: str, tarifs: Dict[str, Any]) -> tuple:
    """Data URL → (octets, type MIME). Contrôle le type, la signature des premiers octets et la taille. ValueError si refusé."""
    m = re.match(r"^data:([a-z0-9/+.-]+);base64,(.+)$", data_url or "", re.S)
    if not m:
        raise ValueError("Média illisible.")
    mime = m.group(1)
    attendus = TYPES_IMAGE if media_attendu == "image" else TYPES_VIDEO
    if mime not in attendus:
        raise ValueError("Ce format demande une image JPEG, PNG ou WebP." if media_attendu == "image" else "Ce format demande une vidéo MP4 ou WebM.")
    try:
        octets = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Média illisible.")
    limite = tarifs["image_max_ko"] * 1000 if media_attendu == "image" else tarifs["video_max_mo"] * 1_000_000
    if len(octets) > limite:
        taille = f"{tarifs['image_max_ko']} Ko" if media_attendu == "image" else f"{tarifs['video_max_mo']} Mo"
        raise ValueError(f"Fichier trop lourd : {taille} au plus.")
    signature = attendus[mime]
    if (signature and not octets.startswith(signature)) or (mime == "video/mp4" and octets[4:8] != b"ftyp"):
        raise ValueError("Le contenu du fichier ne correspond pas à son type.")
    return octets, mime


def _cle() -> bytes:
    """Clé AES-256 des médias : variable d'environnement ANNONCEURS_CLE_MEDIAS (recommandé), sinon dérivée de JWT_SECRET."""
    brute = os.environ.get("ANNONCEURS_CLE_MEDIAS") or ""
    if brute:
        return hashlib.sha256(brute.encode("utf-8")).digest()
    return hashlib.sha256(("annonceurs_plateformes:" + os.environ.get("JWT_SECRET", "fallback-insecure")).encode("utf-8")).digest()


def chiffrer(octets: bytes) -> bytes:
    """AES-256-GCM : nonce aléatoire de 12 octets placé devant le texte chiffré."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return nonce + AESGCM(_cle()).encrypt(nonce, octets, None)


def dechiffrer(donnees: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(_cle()).decrypt(donnees[:12], donnees[12:], None)


# ---------------------------------------------------------------------------
# Modèles de requête
# ---------------------------------------------------------------------------
class TarifsIn(BaseModel):
    formats: List[Dict[str, Any]] = Field(..., max_length=10)
    options: List[Dict[str, Any]] = Field(default_factory=list, max_length=10)
    remises: List[Dict[str, Any]] = Field(default_factory=list, max_length=10)
    duree_min: int = 1
    duree_max: int = 90
    avance_max_jours: int = 90
    image_max_ko: int = 600
    video_max_mo: int = 6
    actif: bool = True


class DevisIn(BaseModel):
    utilisateur: Utilisateur
    format: str = Field(..., max_length=30)
    debut: str = Field(..., max_length=10)
    fin: str = Field(..., max_length=10)
    options: List[str] = Field(default_factory=list, max_length=10)


class CreerIn(DevisIn):
    nom: str = Field(..., min_length=2, max_length=80)
    annonceur: str = Field(..., min_length=2, max_length=80)
    lien: str = Field(..., min_length=8, max_length=500)
    media: str = Field(..., min_length=100, max_length=17_000_000)        # data URL base64


class UtilisateurIn(BaseModel):
    utilisateur: Utilisateur


class CampagneIn(BaseModel):
    utilisateur: Utilisateur
    campagne_id: str = Field(..., min_length=8, max_length=80)


class PayerIn(CampagneIn):
    mode: str = Field(..., pattern="^(pawapay|pispi)$")
    retour: str = Field("", max_length=400)


class DeclarerIn(CampagneIn):
    reference_bancaire: str = Field(..., min_length=4, max_length=120)


class MontantIn(BaseModel):
    montant: int = Field(..., ge=0, le=100_000_000)
    motif: str = Field("", max_length=200)


class ConfirmationIn(BaseModel):
    reference_bancaire: Optional[str] = Field(None, max_length=120)


# ---------------------------------------------------------------------------
def make_annonceurs_plateformes(*, db, get_super_admin: Callable, pawapay: Dict[str, Any], hooks_apres_paiement: List[Any], outils: Any):
    """Construit le routeur. `outils` : fonctions du module des formules (signature, fiche membre, lecture des corps)."""
    router = APIRouter(tags=["Annonceurs des plateformes (lot 235)"])

    async def tarifs() -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": ID_REGLAGES}) or {}
        return valider_tarifs(s["tarifs"]) if s.get("tarifs") else dict(TARIFS_DEFAUT)

    def vue_tarifs(t: Dict[str, Any]) -> Dict[str, Any]:
        return {k: t[k] for k in ("formats", "options", "remises", "duree_min", "duree_max", "avance_max_jours", "image_max_ko", "video_max_mo", "actif")}

    def est_abonne(m: dict, libre: bool) -> bool:
        """Annonceur = utilisateur dont un abonnement ACTIF débloque la fonction « annonceur_pm » ; le super-administrateur est dispensé."""
        return bool(libre or outils.acces_fonction(m, FONCTION))

    async def exiger_annonceur(request: Request, modele):
        emetteur, corps = await outils.plateforme_signee(request)
        d = outils.lire(modele, corps)
        m = await outils.membre(emetteur["code"], d.utilisateur)
        # Refus 402 sans la formule « Annonceur » : le message donne son NOM et son PRIX
        await outils.exiger_abonnement(emetteur["code"], m, FONCTION, "L'espace annonceur", d.utilisateur.acces_libre)
        return emetteur, d, m

    def vue(c: dict) -> dict:
        """Campagne telle que la voit l'annonceur (jamais le chemin de stockage ni le jeton du média)."""
        return {"id": c["id"], "nom": c["nom"], "annonceur": c["annonceur"], "format": c["devis"]["format_libelle"], "debut": c["devis"]["debut"],
                "fin": c["devis"]["fin"], "jours": c["devis"]["jours"], "devis": c["devis"], "montant": c["montant"], "statut": c["statut"],
                "lien": c["lien"], "media_type": c["media"]["mime"], "cree_le": c["cree_le"], "paye_le": c.get("paye_le"),
                "montant_corrige": c.get("montant_corrige", False)}

    async def charger(c_id: str, emetteur: dict, m: dict) -> dict:
        c = await db.annonceurs_campagnes.find_one({"id": c_id, "plateforme": emetteur["code"], "membre_id": m["id"]}, {"_id": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Campagne introuvable")
        return c

    # ------------------------------------------------------------------ routes signées
    @router.post("/annonceurs-plateformes/tarifs")
    async def route_tarifs(request: Request):
        emetteur, corps = await outils.plateforme_signee(request)
        d = outils.lire(UtilisateurIn, corps)
        m = await outils.membre(emetteur["code"], d.utilisateur)
        # Si l'utilisateur n'a pas la formule Annonceur : on propose la moins chère (nom, prix, durée) pour « Devenir annonceur »
        formules = await db.formules_plateformes.find({"plateforme": emetteur["code"], "actif": True, "fonctions": FONCTION}, {"_id": 0}).sort("prix", 1).to_list(5)
        offre = [{"id": f["id"], "nom": f["nom"], "prix": f["prix"], "duree_jours": f.get("duree_jours") or 30} for f in formules]
        return {"tarifs": vue_tarifs(await tarifs()), "est_abonne": est_abonne(m, d.utilisateur.acces_libre), "formules": offre}

    @router.post("/annonceurs-plateformes/devis")
    async def route_devis(request: Request):
        """Aperçu en direct : calcule sans rien enregistrer (réponse 422 avec un message simple si un paramètre est hors limites)."""
        _, d, _m = await exiger_annonceur(request, DevisIn)
        try:
            return {"devis": calculer_devis(await tarifs(), d.format, d.debut, d.fin, d.options)}
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @router.post("/annonceurs-plateformes/creer")
    async def route_creer(request: Request):
        emetteur, d, m = await exiger_annonceur(request, CreerIn)
        t = await tarifs()
        if not t["actif"]:
            raise HTTPException(status_code=503, detail="Les annonces ne sont pas ouvertes pour le moment")
        if not d.lien.startswith("https://"):
            raise HTTPException(status_code=422, detail="Le lien de l'annonce doit commencer par https://")
        try:
            devis = calculer_devis(t, d.format, d.debut, d.fin, d.options)         # le montant est TOUJOURS recalculé ici
            octets, mime = decoder_media(d.media, devis["media"], t)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        c_id, jeton = str(uuid.uuid4()), secrets.token_urlsafe(18)
        chemin = f"annonceurs/{c_id}.bin"
        chiffre = chiffrer(octets)
        if _ecrire:
            await _ecrire(chemin, chiffre)
        else:
            import object_storage
            await object_storage.put_object(chemin, chiffre, "application/octet-stream")
        c = {"id": c_id, "plateforme": emetteur["code"], "membre_id": m["id"], "utilisateur_id": m["utilisateur_id"], "nom": d.nom.strip(),
             "annonceur": d.annonceur.strip(), "lien": d.lien.strip(), "devis": devis, "montant": devis["total"], "montant_corrige": False,
             "statut": "devis", "media": {"chemin": chemin, "mime": mime, "taille": len(octets), "jeton": jeton},
             "cree_le": _iso(_maintenant())}
        await db.annonceurs_campagnes.insert_one(c.copy())
        return {"campagne": vue(c)}

    @router.post("/annonceurs-plateformes/campagnes")
    async def route_campagnes(request: Request):
        emetteur, corps = await outils.plateforme_signee(request)
        d = outils.lire(UtilisateurIn, corps)
        m = await outils.membre(emetteur["code"], d.utilisateur)
        lignes = await db.annonceurs_campagnes.find({"plateforme": emetteur["code"], "membre_id": m["id"]}, {"_id": 0}).sort("cree_le", -1).to_list(100)
        return {"campagnes": [vue(c) for c in lignes]}

    async def publier(c: dict) -> None:
        """Campagne payée → annonce dans la régie (ad_banners), UNE seule fois (verrou « banner_id »)."""
        verrou = await db.annonceurs_campagnes.update_one({"id": c["id"], "banner_id": {"$exists": False}}, {"$set": {"banner_id": "en_cours"}})
        if not verrou.modified_count:
            return
        banner_id = str(uuid.uuid4())
        slug = f"annonce-{banner_id[:8]}"
        maintenant = _iso(_maintenant())
        await db.ad_banners.insert_one({
            "id": banner_id, "tenant_id": "annonceurs", "name": c["nom"], "advertiser_name": c["annonceur"],
            "image_url": f"/api/public/annonceurs-plateformes/media/{c['media']['jeton']}",
            "media_kind": "video" if c["media"]["mime"].startswith("video/") else "image", "target_url": c["lien"],
            "placement": PLACEMENT, "animated": False, "active": True, "budget_amount": 0.0, "currency": "XOF",
            "cost_per_impression": 0.0, "cost_per_click": 0.0, "total_impressions": 0, "total_clicks": 0, "amount_spent": 0.0,
            "paid": True, "payment_date": maintenant[:10], "start_date": c["devis"]["debut"], "expiration_date": c["devis"]["fin"],
            "daily_stats": [], "notes": f"Annonceur de plateforme — campagne {c['id']}" + (" — MISE EN AVANT" if any(o["code"] == "avant" for o in c["devis"]["options"]) else ""),
            "display_mode": "auto", "aspect_ratio": "16:9", "width_pct": 100, "height_px": 80, "width_px": 728, "object_fit": "cover",
            "modal_frequency": "session", "variant_b_modal_frequency": "", "modal_impressions": 0, "modal_clicks": 0,
            "modal_impressions_a": 0, "modal_clicks_a": 0, "modal_impressions_b": 0, "modal_clicks_b": 0, "ab_enabled": False,
            "variant_b_image_url": "", "variant_b_media_kind": "image", "variant_b_target_url": "",
            "total_impressions_a": 0, "total_clicks_a": 0, "total_impressions_b": 0, "total_clicks_b": 0,
            "advertiser_email": "", "advertiser_phone": "", "reminder_email_enabled": False, "reminder_wa_enabled": False,
            "reminder_days_before": 3, "reminder_last_sent_for": None, "slug": slug, "share_token": secrets.token_urlsafe(16),
            "created_by": f"annonceur:{c['utilisateur_id']}", "created_at": maintenant, "updated_at": maintenant})
        await db.annonceurs_campagnes.update_one({"id": c["id"]}, {"$set": {"banner_id": banner_id, "statut": "active", "paye_le": maintenant}})

    async def apres_paiement(payment: dict) -> None:
        """Paiement « completed » d'une annonce : publication (UNE fois grâce au verrou de `publier`)."""
        if payment.get("flow") != FLOW:
            return
        c = await db.annonceurs_campagnes.find_one({"id": payment.get("campagne_id")}, {"_id": 0})
        if c and c.get("statut") in ("devis", "pispi_attente", "pispi_verification", "paiement_en_cours"):
            await publier(c)

    hooks_apres_paiement.append(apres_paiement)

    @router.post("/annonceurs-plateformes/payer")
    async def route_payer(request: Request):
        emetteur, d, m = await exiger_annonceur(request, PayerIn)
        c = await charger(d.campagne_id, emetteur, m)
        if c["statut"] in ("active", "terminee"):
            raise HTTPException(status_code=409, detail="Cette annonce est déjà payée")
        if c["montant"] <= 0:                                           # montant corrigé à 0 par SAWALI : publication directe
            await publier(c)
            return {"statut": "paye"}
        if d.mode == "pispi":
            from routes.pispi import bloc, lire_parametres, sans_octets
            param = await lire_parametres()
            if not bloc(param, reference="", reste_du=float(c["montant"])).get("afficher"):
                raise HTTPException(status_code=503, detail="Paiement PI-SPI indisponible pour le moment")
            ouverte = await db.payments.find_one({"flow": FLOW, "methode": "pispi", "campagne_id": c["id"], "status": {"$in": list(STATUTS_PISPI_OUVERTS)},
                                                  "amount": float(c["montant"])}, {"_id": 0})
            reference = ouverte["deposit_id"] if ouverte else "PUB-" + secrets.token_hex(4).upper()
            if not ouverte:
                await db.payments.insert_one({"id": str(uuid.uuid4()), "deposit_id": reference, "client_id": None, "user_id": None,
                                              "user_label": m.get("nom") or m["utilisateur_id"], "amount": float(c["montant"]), "currency": "XOF",
                                              "description": f"Annonce {c['nom']} — {emetteur['code']} (PI-SPI)", "flow": FLOW, "methode": "pispi",
                                              "plateforme": emetteur["code"], "membre_id": m["id"], "campagne_id": c["id"], "status": "pispi_attente",
                                              "created_at": _iso(_maintenant()), "updated_at": _iso(_maintenant())})
                await db.annonceurs_campagnes.update_one({"id": c["id"]}, {"$set": {"statut": "pispi_attente", "reference_paiement": reference}})
            return {"mode": "pispi", "reference": reference, "bloc": sans_octets(bloc(param, reference=reference, reste_du=float(c["montant"]))),
                    "statut": ouverte["status"] if ouverte else "pispi_attente"}
        # PawaPay : page de paiement hébergée (même principe que les abonnements)
        s = await db.settings.find_one({"_id": "global"}) or {}
        token = pawapay["jeton"](s) if s.get("pawapay_enabled") else None
        if not token:
            raise HTTPException(status_code=503, detail="Paiement indisponible pour le moment")
        env = (s.get("pawapay_environment") or "sandbox").lower()
        host = pawapay["hotes"].get(env, pawapay["hotes"]["sandbox"])
        country = (s.get("pawapay_country") or "BFA").upper()
        deposit_id = str(uuid.uuid4())
        msisdn = "".join(ch for ch in (m.get("telephone") or "") if ch.isdigit())
        corps_pp: Dict[str, Any] = {"depositId": deposit_id, "country": country, "reason": f"Annonce {c['nom']}"[:50],
                                    "amountDetails": {"amount": str(int(c["montant"])), "currency": pawapay["devise"](country)}}
        if d.retour.startswith("https://"):
            corps_pp["returnUrl"] = f"{d.retour}{'&' if '?' in d.retour else '?'}depositId={deposit_id}"
        if len(msisdn) >= 8:
            corps_pp["phoneNumber"] = msisdn
        await db.payments.insert_one({"id": str(uuid.uuid4()), "deposit_id": deposit_id, "client_id": None, "user_id": None,
                                      "user_label": m.get("nom") or m["utilisateur_id"], "amount": float(c["montant"]), "currency": "XOF", "country": country,
                                      "msisdn": msisdn or None, "description": f"Annonce {c['nom']} — {emetteur['code']}", "environment": env, "flow": FLOW,
                                      "plateforme": emetteur["code"], "membre_id": m["id"], "campagne_id": c["id"], "status": "initiated",
                                      "created_at": _iso(_maintenant()), "updated_at": _iso(_maintenant())})
        try:
            async with httpx.AsyncClient(timeout=20, transport=_transport) as http:
                r = await http.post(f"{host}/v2/paymentpage", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=corps_pp)
                rep = r.json()
        except Exception:  # noqa: BLE001
            await db.payments.update_one({"deposit_id": deposit_id}, {"$set": {"status": "failed", "api_status": "ERREUR_RESEAU"}})
            raise HTTPException(status_code=502, detail="Page de paiement indisponible, réessayez dans un instant")
        url = (rep or {}).get("redirectUrl")
        if not url:
            await db.payments.update_one({"deposit_id": deposit_id}, {"$set": {"status": "failed", "api_status": "PAGE_REFUSEE"}})
            raise HTTPException(status_code=502, detail="Page de paiement refusée, réessayez dans un instant")
        await db.payments.update_one({"deposit_id": deposit_id}, {"$set": {"redirect_url": url}})
        await db.annonceurs_campagnes.update_one({"id": c["id"]}, {"$set": {"statut": "paiement_en_cours", "reference_paiement": deposit_id}})
        return {"mode": "pawapay", "deposit_id": deposit_id, "redirect_url": url}

    @router.post("/annonceurs-plateformes/declarer")
    async def route_declarer(request: Request):
        emetteur, d, m = await exiger_annonceur(request, DeclarerIn)
        c = await charger(d.campagne_id, emetteur, m)
        p = await db.payments.find_one({"deposit_id": c.get("reference_paiement"), "flow": FLOW, "methode": "pispi"}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Demande PI-SPI introuvable")
        if p["status"] not in STATUTS_PISPI_OUVERTS:
            raise HTTPException(status_code=409, detail="Cette demande est clôturée : refaites-en une nouvelle")
        await db.payments.update_one({"deposit_id": p["deposit_id"]}, {"$set": {"status": "pispi_verification", "reference_bancaire": d.reference_bancaire.strip(),
                                                                               "declare_le": _iso(_maintenant()), "updated_at": _iso(_maintenant())}})
        await db.annonceurs_campagnes.update_one({"id": c["id"]}, {"$set": {"statut": "pispi_verification"}})
        return {"statut": "pispi_verification"}

    async def relire_pawapay(p: dict) -> dict:
        """Interroge PawaPay si le webhook n'est pas encore arrivé ; paiement confirmé → publication."""
        s = await db.settings.find_one({"_id": "global"}) or {}
        token = pawapay["jeton"](s)
        if not token:
            return p
        env = (p.get("environment") or s.get("pawapay_environment") or "sandbox").lower()
        host = pawapay["hotes"].get(env, pawapay["hotes"]["sandbox"])
        try:
            async with httpx.AsyncClient(timeout=15, transport=_transport) as http:
                r = await http.get(f"{host}/v2/deposits/{p['deposit_id']}", headers={"Authorization": f"Bearer {token}"})
                data = r.json() if r.status_code < 400 else {}
        except Exception:  # noqa: BLE001
            return p
        entree = (data.get("data") or {}) if (data.get("status") or "").upper() == "FOUND" else {}
        api = (entree.get("status") or "").upper()
        nouveau = {"COMPLETED": "completed", "FAILED": "failed", "REJECTED": "failed"}.get(api)
        if nouveau:
            await db.payments.update_one({"deposit_id": p["deposit_id"]}, {"$set": {"status": nouveau, "api_status": api, "updated_at": _iso(_maintenant())}})
            p = await db.payments.find_one({"deposit_id": p["deposit_id"]}, {"_id": 0}) or p
            if nouveau == "completed":
                await apres_paiement(p)
        return p

    @router.post("/annonceurs-plateformes/etat")
    async def route_etat(request: Request):
        emetteur, d, m = await exiger_annonceur(request, CampagneIn)
        c = await charger(d.campagne_id, emetteur, m)
        p = await db.payments.find_one({"deposit_id": c.get("reference_paiement"), "flow": FLOW}, {"_id": 0}) if c.get("reference_paiement") else None
        if p and p.get("status") in ("initiated", "pending"):
            await relire_pawapay(p)
            c = await charger(d.campagne_id, emetteur, m)
        if p and p.get("status") == "failed" and c["statut"] == "paiement_en_cours":
            await db.annonceurs_campagnes.update_one({"id": c["id"]}, {"$set": {"statut": "devis"}})
            c["statut"] = "devis"
        return {"campagne": vue(c)}

    @router.post("/annonceurs-plateformes/stats")
    async def route_stats(request: Request):
        """Statistiques lues dans la régie : jamais d'autres campagnes que les siennes."""
        emetteur, corps = await outils.plateforme_signee(request)
        d = outils.lire(CampagneIn, corps)
        m = await outils.membre(emetteur["code"], d.utilisateur)
        c = await charger(d.campagne_id, emetteur, m)
        b = await db.ad_banners.find_one({"id": c.get("banner_id")}, {"_id": 0}) if c.get("banner_id") not in (None, "en_cours") else None
        imp, clics = int((b or {}).get("total_impressions") or 0), int((b or {}).get("total_clicks") or 0)
        jour = sorted(((b or {}).get("daily_stats") or []), key=lambda r: r.get("date") or "")
        auj = _maintenant().date().isoformat()
        etat = c["statut"]
        if etat == "active" and c["devis"]["fin"] < auj:
            etat = "terminee"
        elif etat == "active" and c["devis"]["debut"] > auj:
            etat = "programmee"
        elif etat == "suspendue":
            etat = "suspendue"
        return {"campagne": {**vue(c), "statut": etat}, "impressions": imp, "clics": clics,
                "taux_clic": round(clics / imp * 100, 2) if imp else 0.0,
                "jours_restants": max(0, (date.fromisoformat(c["devis"]["fin"]) - _maintenant().date()).days + 1) if c.get("banner_id") else None,
                "par_jour": [{"date": r.get("date"), "impressions": int(r.get("impressions") or 0), "clics": int(r.get("clicks") or 0)} for r in jour]}

    # ------------------------------------------------------------------ média public (déchiffré à la demande)
    @router.get("/public/annonceurs-plateformes/media/{jeton}")
    async def media_public(jeton: str):
        c = await db.annonceurs_campagnes.find_one({"media.jeton": jeton, "statut": {"$in": ["active", "suspendue", "terminee"]}}, {"_id": 0, "media": 1})
        if not c:
            raise HTTPException(status_code=404, detail="Média introuvable")
        if _lire:
            chiffre = await _lire(c["media"]["chemin"])
        else:
            import object_storage
            chiffre, _ = await object_storage.get_object(c["media"]["chemin"])
        try:
            octets = dechiffrer(chiffre)
        except Exception:  # noqa: BLE001
            logger.error("[annonceurs] média illisible (clé modifiée ?) : %s", c["media"]["chemin"])
            raise HTTPException(status_code=500, detail="Média illisible")
        return Response(content=octets, media_type=c["media"]["mime"], headers={"Cache-Control": "public, max-age=3600"})

    # ------------------------------------------------------------------ administration (administrateur principal)
    @router.get("/admin/annonceurs-plateformes/tarifs")
    async def admin_tarifs(_: dict = Depends(get_super_admin)):
        return {"tarifs": vue_tarifs(await tarifs())}

    @router.put("/admin/annonceurs-plateformes/tarifs")
    async def admin_tarifs_maj(t: TarifsIn, _: dict = Depends(get_super_admin)):
        try:
            propre = valider_tarifs(t.model_dump())
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        await db.settings.update_one({"_id": ID_REGLAGES}, {"$set": {"tarifs": propre}}, upsert=True)
        return {"ok": True, "tarifs": vue_tarifs(propre)}

    @router.get("/admin/annonceurs-plateformes/campagnes")
    async def admin_campagnes(_: dict = Depends(get_super_admin)):
        lignes = await db.annonceurs_campagnes.find({}, {"_id": 0}).sort("cree_le", -1).to_list(300)
        out = []
        for c in lignes:
            b = await db.ad_banners.find_one({"id": c.get("banner_id")}, {"_id": 0, "total_impressions": 1, "total_clicks": 1, "active": 1}) if c.get("banner_id") not in (None, "en_cours") else None
            p = await db.payments.find_one({"deposit_id": c.get("reference_paiement")}, {"_id": 0, "reference_bancaire": 1, "status": 1}) if c.get("reference_paiement") else None
            out.append({**vue(c), "plateforme": c["plateforme"], "utilisateur": c.get("utilisateur_id"), "montant_calcule": c["devis"]["total"],
                        "impressions": int((b or {}).get("total_impressions") or 0), "clics": int((b or {}).get("total_clicks") or 0),
                        "reference": c.get("reference_paiement"), "reference_bancaire": (p or {}).get("reference_bancaire"),
                        "paiement": (p or {}).get("status"), "media_jeton": c["media"]["jeton"]})
        return {"campagnes": out}

    @router.put("/admin/annonceurs-plateformes/campagnes/{c_id}/montant")
    async def admin_montant(c_id: str, corps: MontantIn, adm: dict = Depends(get_super_admin)):
        """SAWALI seul peut corriger un montant, et seulement AVANT le paiement (toute demande de paiement ouverte est annulée)."""
        c = await db.annonceurs_campagnes.find_one({"id": c_id}, {"_id": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Campagne introuvable")
        if c["statut"] in ("active", "suspendue", "terminee"):
            raise HTTPException(status_code=409, detail="Campagne déjà payée : le montant ne peut plus changer")
        await db.payments.update_many({"flow": FLOW, "campagne_id": c_id, "status": {"$in": ["initiated", "pending", *STATUTS_PISPI_OUVERTS]}},
                                      {"$set": {"status": "failed", "api_status": "MONTANT_CORRIGE"}})
        await db.annonceurs_campagnes.update_one({"id": c_id}, {"$set": {"montant": corps.montant, "montant_corrige": corps.montant != c["devis"]["total"],
                                                                         "statut": "devis", "correction": {"par": adm.get("email") or "admin", "motif": corps.motif.strip(), "le": _iso(_maintenant())}}})
        return {"ok": True, "montant": corps.montant}

    async def basculer(c_id: str, actif: bool):
        c = await db.annonceurs_campagnes.find_one({"id": c_id}, {"_id": 0})
        if not c or c.get("banner_id") in (None, "en_cours"):
            raise HTTPException(status_code=404, detail="Campagne publiée introuvable")
        await db.ad_banners.update_one({"id": c["banner_id"]}, {"$set": {"active": actif, "updated_at": _iso(_maintenant())}})
        await db.annonceurs_campagnes.update_one({"id": c_id}, {"$set": {"statut": "active" if actif else "suspendue"}})
        return {"ok": True}

    @router.post("/admin/annonceurs-plateformes/campagnes/{c_id}/suspendre")
    async def admin_suspendre(c_id: str, _: dict = Depends(get_super_admin)):
        return await basculer(c_id, False)

    @router.post("/admin/annonceurs-plateformes/campagnes/{c_id}/reactiver")
    async def admin_reactiver(c_id: str, _: dict = Depends(get_super_admin)):
        return await basculer(c_id, True)

    @router.post("/admin/annonceurs-plateformes/campagnes/{c_id}/pispi/confirmer")
    async def admin_pispi_confirmer(c_id: str, corps: ConfirmationIn, adm: dict = Depends(get_super_admin)):
        from routes.pispi import enregistrer_transaction
        c = await db.annonceurs_campagnes.find_one({"id": c_id}, {"_id": 0})
        p = await db.payments.find_one({"deposit_id": (c or {}).get("reference_paiement"), "flow": FLOW, "methode": "pispi"}, {"_id": 0}) if c else None
        if not p or p["status"] not in STATUTS_PISPI_OUVERTS:
            raise HTTPException(status_code=404, detail="Demande PI-SPI introuvable ou déjà clôturée")
        ref = (corps.reference_bancaire or p.get("reference_bancaire") or "").strip() or None
        await db.payments.update_one({"deposit_id": p["deposit_id"]}, {"$set": {"status": "completed", "api_status": "PISPI", "reference_bancaire": ref,
                                                                               "confirme_par": adm.get("email") or "admin", "updated_at": _iso(_maintenant())}})
        p = await db.payments.find_one({"deposit_id": p["deposit_id"]}, {"_id": 0})
        await apres_paiement(p)
        await enregistrer_transaction(reference=p["deposit_id"], montant=float(p["amount"]), statut="rapproche", source="manuel", reference_bancaire=ref,
                                      document={"type": "annonce_plateforme", "id": c_id, "numero": p["deposit_id"]}, saisi_par=adm.get("email") or "admin")
        return {"ok": True}

    @router.post("/admin/annonceurs-plateformes/campagnes/{c_id}/pispi/refuser")
    async def admin_pispi_refuser(c_id: str, _: dict = Depends(get_super_admin)):
        c = await db.annonceurs_campagnes.find_one({"id": c_id}, {"_id": 0})
        r = await db.payments.update_one({"deposit_id": (c or {}).get("reference_paiement"), "flow": FLOW, "methode": "pispi", "status": {"$in": list(STATUTS_PISPI_OUVERTS)}},
                                         {"$set": {"status": "failed", "api_status": "PISPI_REFUSE", "updated_at": _iso(_maintenant())}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Demande PI-SPI introuvable ou déjà clôturée")
        await db.annonceurs_campagnes.update_one({"id": c_id}, {"$set": {"statut": "devis"}})
        return {"ok": True}

    return router
