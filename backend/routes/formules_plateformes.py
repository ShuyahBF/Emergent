"""Lot 227 — Formules (abonnements) et parrainage des utilisateurs des plateformes (Paiement Mobile…).

Demande du propriétaire (17/10/2026) : la lecture des ordonnances (OCR) devient une FORMULE payante, gérée côté SAWALI.
Chaque plateforme affiche dans sa rubrique « Abonnement » les formules créées ici ; tout paiement active la formule pour
sa durée (30 jours par défaut), qui SE CUMULE : payer avant l'échéance ajoute la durée au temps restant. Un système de
parrainage offre des jours au parrain ET au filleul quand le filleul paie sa première formule.

Pour un développeur WinDev (c'est l'équivalent de deux fichiers HFSQL + des procédures d'encaissement) :
  - fichier `formules_plateformes` : la vitrine (plateforme, nom, prix, durée, fonctions débloquées, active) ;
  - fichier `membres_plateformes` : un utilisateur d'une plateforme (identifié par la plateforme elle-même, jamais par un
    mot de passe SAWALI), son code de parrainage, son parrain, et ses abonnements { formule : date d'expiration } ;
  - l'encaissement passe par la page PawaPay hébergée (comme les paiements déjà en place) ; le paiement est inscrit dans
    `payments` (flow « formule_plateforme »). À sa confirmation (webhook PawaPay, ou relecture à la demande) le crochet
    `apres_paiement` active la formule — UNE seule fois (verrou « activation_faite »).
  - Routes SIGNÉES des plateformes (en-têtes X-Emetteur, X-Timestamp, X-Signature = HMAC-SHA256 de « <ts>.<corps> », comme
    le support et la transmission WA) : le navigateur de l'utilisateur ne parle jamais à SAWALI.
        POST /api/formules-plateformes/catalogue   {utilisateur, code_parrain?}  → formules, abonnements, code de parrainage
        POST /api/formules-plateformes/acheter     {utilisateur, formule_id | formule_ids, retour?} → lien de la page de paiement PawaPay
        POST /api/formules-plateformes/devis       {utilisateur, formule_ids}     → {lignes, total} (lot 244 : achat groupé, un seul paiement)
        POST /api/formules-plateformes/achat       {utilisateur, deposit_id}      → état du paiement (active la formule si payé)
        POST /api/formules-plateformes/acces       {utilisateur, fonction}        → {actif, expire_le, jours_restants}
        POST /api/formules-plateformes/parrainage  {utilisateur, code?}           → mon code, filleuls, jours gagnés ; lie un parrain
  - Lot 228 — OCR réservé aux abonnés (plaques de marchands, ordonnances) :
        POST /api/formules-plateformes/ocr         {utilisateur, type, image (data URL)} → champs lus ; refusé (402) sans abonnement
                                                   actif, avec le NOM et le PRIX de la formule à prendre ; limite par jour (429)
  - Lot 229 — transcription vocale réservée aux abonnés (30 s au plus par note, limite par jour) :
        POST /api/formules-plateformes/transcrire  {utilisateur, audio (data URL), duree_s} → {texte}
  - Administration (administrateur principal) : rubrique des Paramètres « Formules des plateformes » :
        GET/POST /api/admin/formules-plateformes · PUT/DELETE …/{id} · PUT /api/admin/formules-plateformes-reglages (jours de parrainage)
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import archives_totp

logger = logging.getLogger("sawali.formules_plateformes")

# Transport HTTP de remplacement (tests) : None en production
_transport: Optional[httpx.AsyncBaseTransport] = None
# Transcription de remplacement (tests) : async (octets, extension, langue) → texte ; None = Whisper (ia_client)
_transcrire: Optional[Callable] = None
# Stockage des archives chiffrées (lot 233) : crochets remplacés par les tests ; en production, Cloudflare R2 (object_storage.py)
_ecrire_archive: Optional[Callable] = None
_lire_archive: Optional[Callable] = None
_effacer_archive: Optional[Callable] = None
# Lecture OCR de remplacement (tests) : async (octets, type_mime, nom, consigne) → dict ; None = vrai moteur ocr_core
_analyser: Optional[Callable] = None

# Consignes OCR propres à Paiement Mobile (ajoutées au format de réponse commun d'ocr_core)
CONSIGNE_PLAQUE = (
    "La photo montre la PLAQUE d'un marchand acceptant un paiement mobile (Orange Money, Moov Money, Telecel Cash…) : texte "
    "imprimé, souvent un numéro marchand ÉCRIT À LA MAIN dans une case, et un QR code. Dans extracted_fields, mets exactement ces clés : "
    '"operateur" (Orange, Moov ou Telecel d\'après le logo ou le texte, sinon null), "code_marchand" (uniquement les chiffres écrits dans '
    'la case du numéro marchand ; null si illisible), "nom_marchand" (nom de la boutique imprimé ou écrit, sinon null), '
    '"numero_sous_qr" (le numéro imprimé sous le QR code, sinon null), "texte_complet" (tout le texte lisible, ligne par ligne). '
    "Ne devine jamais un chiffre : mets null et cite la clé dans uncertain_fields.")
CONSIGNE_ORDONNANCE = (
    "La photo montre une ORDONNANCE médicale (imprimée ou manuscrite). Dans extracted_fields, mets exactement ces clés : "
    '"prescripteur" (nom du médecin, sinon null), "date" (AAAA-MM-JJ, sinon null), "patient" (sinon null), '
    '"medicaments" (liste d\'objets {"nom", "dose", "posologie", "duree"} dans l\'ordre de l\'ordonnance ; chaque valeur en texte, null si absente), '
    '"texte_complet" (tout le texte lisible). Ne devine jamais un nom de médicament ou une dose illisible : mets null et cite-le dans uncertain_fields. '
    "Tu ne donnes AUCUN conseil médical : tu retranscris seulement.")
# Fonctions qu'une formule peut débloquer (liste fermée : alimente la liste déroulante d'administration)
FONCTIONS = {"ocr_ordonnances": "OCR (ordonnances et plaques de marchands)",
             "transcription_vocale": "Transcription vocale (notes de 30 secondes)",
             "archives_cloud": "Archives en ligne chiffrées (documents importants)"}
FONCTIONS["annonceur_pm"] = "Annonceur (passer des annonces, devis et statistiques)"   # lot 236
FONCTIONS["cartes_virtuelles"] = "Cartes virtuelles (voeux illustrés par l'IA, envoyés par WhatsApp)"   # lot 242
FONCTION_ARCHIVES = "archives_cloud"      # lot 233 : stockage cloud chiffré des documents archivés
ARCHIVES_MO_DEFAUT = 200                  # espace par utilisateur, en Mo (réglable)
PIN_ESSAIS_AVANT_PAUSE = 5                # lot 278 : essais de code/phrase ratés de suite avant une pause
PIN_PAUSE_MINUTES = 15                    # lot 278 : durée de la pause
PIN_ECHECS_AVANT_SECOURS = 10             # lot 278 : échecs sans réussite entre deux : le code de secours devient nécessaire
ARCHIVES_GRATUIT_MO_DEFAUT = 50           # lot 277 : espace en ligne OFFERT à tout utilisateur sans abonnement, en Mo (réglable)
ARCHIVES_GRATUIT_NOMBRE_DEFAUT = 30       # lot 277 : nombre de documents en ligne offerts sans abonnement (réglable)
ARCHIVE_FICHIER_MAX = 8_000_000           # octets d'un document chiffré (le site réduit les photos avant de chiffrer)
ARCHIVE_META_MAX = 6000                   # caractères des informations chiffrées d'un document (titre, catégorie, étiquettes…)
FONCTION_OCR = "ocr_ordonnances"          # une seule fonction débloque toutes les lectures OCR
FONCTION_VOIX = "transcription_vocale"    # lot 229 : transcription des notes vocales
VOIX_PAR_JOUR_DEFAUT = 10                 # notes par jour et par utilisateur (réglable)
VOIX_DUREE_MAX_S = 31                     # 30 s + marge d'arrêt de l'enregistreur
VOIX_TAILLE_MAX = 900_000                 # octets de l'audio décodé (≈ 30 s en webm/opus ou m4a ; au-delà : refusé)
OCR_PAR_JOUR_DEFAUT = 30                  # lectures par jour et par utilisateur (réglable par l'administrateur)
OCR_TYPES = ("plaque_marchand", "ordonnance")
OCR_TAILLE_MAX = 8_000_000                # octets de l'image décodée
DUREE_DEFAUT = 30
ACHAT_FORMULES_MAX = 8                    # lot 244 : formules au plus dans un même paiement
PARRAINAGE_JOURS_DEFAUT = 7
ALPHABET_CODE = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"   # sans 0/O/1/I


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def nouvelle_expiration(courante: Optional[str], jours: int, maintenant: datetime) -> datetime:
    """Cumul : on part du temps RESTANT s'il y en a, sinon de maintenant, puis on ajoute les jours."""
    base = maintenant
    if courante:
        try:
            actuelle = datetime.fromisoformat(courante)
            if actuelle.tzinfo is None:
                actuelle = actuelle.replace(tzinfo=timezone.utc)
            base = max(maintenant, actuelle)
        except ValueError:
            pass
    return base + timedelta(days=jours)


def jours_restants(expire_le: Optional[str], maintenant: datetime) -> int:
    """Jours entiers restants (arrondis au-dessus), 0 si expiré."""
    if not expire_le:
        return 0
    try:
        e = datetime.fromisoformat(expire_le)
    except ValueError:
        return 0
    if e.tzinfo is None:
        e = e.replace(tzinfo=timezone.utc)
    reste = (e - maintenant).total_seconds()
    return max(0, int(-(-reste // 86400)))


class Utilisateur(BaseModel):
    """Identité transmise par la plateforme (déjà authentifiée par elle) : aucun secret."""
    id: str = Field(..., min_length=1, max_length=80)
    nom: str = Field("", max_length=120)
    telephone: str = Field("", max_length=30)
    # Super-administrateur de la plateforme dispensé d'abonnement (la plateforme, signée, l'affirme ; elle l'éteint en mode démo)
    acces_libre: bool = False


class AbonnesIn(BaseModel):
    """Liste des comptes dont la plateforme veut connaître les abonnements actifs (200 au plus par appel)."""
    utilisateurs: List[str] = Field(..., max_length=200)


class PispiDemandeIn(BaseModel):
    utilisateur: Utilisateur
    formule_id: Optional[str] = Field(None, min_length=1, max_length=80)             # une seule formule (ancien mode)
    formule_ids: List[str] = Field(default_factory=list, max_length=ACHAT_FORMULES_MAX)   # lot 244 : plusieurs formules, un seul paiement


class PispiDeclareIn(BaseModel):
    utilisateur: Utilisateur
    reference: str = Field(..., min_length=4, max_length=40)
    reference_bancaire: str = Field(..., min_length=4, max_length=120)


class PispiConfirmationIn(BaseModel):
    reference_bancaire: Optional[str] = Field(None, max_length=120)


class ArchiveCleIn(BaseModel):
    """Sel public et jeton de contrôle de la phrase secrète (jamais la phrase elle-même, jamais la clé).
    Lot 277 : `enveloppe` et `secours` = la clé des documents CHIFFRÉE (par la phrase, par le code de secours) : octets illisibles
    pour le serveur, qui ne peut ni les ouvrir ni retrouver la clé."""
    utilisateur: Utilisateur
    sel: str = Field(..., min_length=16, max_length=64)
    verif: str = Field(..., min_length=16, max_length=600)
    enveloppe: Optional[str] = Field(None, min_length=16, max_length=800)
    secours: Optional[str] = Field(None, min_length=16, max_length=800)


class ArchivePinEnregistrerIn(BaseModel):
    """Lot 278 — enregistre la PREUVE du code PIN / de la phrase (une empreinte dérivée, jamais le code lui-même) : le serveur limite ensuite
    les essais et ne rend son élément secret (« poivre ») qu'à la bonne preuve. `verif_actuelle` : obligatoire si des archives existent déjà."""
    utilisateur: Utilisateur
    preuve: str = Field(..., min_length=40, max_length=64)
    type_secret: str = Field("pin", pattern="^(pin|phrase)$")
    verif_actuelle: Optional[str] = Field(None, min_length=16, max_length=600)


class ArchivePinOuvrirIn(BaseModel):
    utilisateur: Utilisateur
    preuve: str = Field(..., min_length=40, max_length=64)
    code_totp: Optional[str] = Field(None, max_length=12)       # lot 279 : code de l'application d'authentification (si activée)


class ArchiveTotpPreparerIn(BaseModel):
    """Lot 279 — début de l'activation de l'application d'authentification (QR code). `verif_actuelle` : seul un appareil qui a ouvert les archives le connaît."""
    utilisateur: Utilisateur
    verif_actuelle: str = Field(..., min_length=16, max_length=600)


class ArchiveTotpActiverIn(BaseModel):
    utilisateur: Utilisateur
    code: str = Field(..., min_length=6, max_length=12)


class ArchiveTotpDesactiverIn(BaseModel):
    """Lot 279 — retire l'application d'authentification : exige le code PIN/la phrase (preuve) ET un code de l'application."""
    utilisateur: Utilisateur
    preuve: str = Field(..., min_length=40, max_length=64)
    code: str = Field(..., min_length=6, max_length=12)


class ArchiveEnveloppesIn(BaseModel):
    """Lot 277 : remplace l'enveloppe (nouvelle phrase secrète) et/ou le secours. `verif_actuelle` = jeton de contrôle déjà enregistré :
    seul un appareil qui a ouvert les archives le connaît (le jeton est renvoyé par « etat » mais ne suffit pas à lire les documents)."""
    utilisateur: Utilisateur
    verif_actuelle: str = Field(..., min_length=16, max_length=600)
    enveloppe: str = Field(..., min_length=16, max_length=800)
    secours: Optional[str] = Field(None, min_length=16, max_length=800)


class ArchiveAjoutIn(BaseModel):
    utilisateur: Utilisateur
    meta: str = Field(..., min_length=16, max_length=ARCHIVE_META_MAX)          # informations du document, CHIFFRÉES par le site
    contenu: str = Field(..., min_length=40, max_length=12_000_000)             # document CHIFFRÉ par le site, en base64


class ArchiveModifierIn(BaseModel):
    utilisateur: Utilisateur
    id: str = Field(..., min_length=8, max_length=64)
    meta: str = Field(..., min_length=16, max_length=ARCHIVE_META_MAX)          # nouvelles informations, CHIFFRÉES par le site


class ArchiveIdIn(BaseModel):
    utilisateur: Utilisateur
    id: str = Field(..., min_length=8, max_length=64)


class CatalogueIn(BaseModel):
    utilisateur: Utilisateur


class AcheterIn(BaseModel):
    utilisateur: Utilisateur
    formule_id: Optional[str] = Field(None, min_length=1, max_length=80)             # une seule formule (ancien mode)
    formule_ids: List[str] = Field(default_factory=list, max_length=ACHAT_FORMULES_MAX)   # lot 244 : plusieurs formules, un seul paiement
    retour: str = Field("", max_length=400)   # page où PawaPay renvoie l'utilisateur après le paiement


class DevisIn(BaseModel):
    """Lot 244 : devis d'un achat groupé (la plateforme l'affiche avant le paiement)."""
    utilisateur: Utilisateur
    formule_ids: List[str] = Field(..., min_length=1, max_length=ACHAT_FORMULES_MAX)


class AchatIn(BaseModel):
    utilisateur: Utilisateur
    deposit_id: str = Field(..., min_length=8, max_length=80)


class AccesIn(BaseModel):
    utilisateur: Utilisateur
    fonction: str = Field(..., min_length=1, max_length=40)


class OcrIn(BaseModel):
    utilisateur: Utilisateur
    type: str = Field(..., pattern="^(plaque_marchand|ordonnance)$")
    image: str = Field(..., min_length=100, max_length=11_500_000)   # data URL base64 (image/jpeg, image/png, image/webp)


class VoixIn(BaseModel):
    utilisateur: Utilisateur
    audio: str = Field(..., min_length=100, max_length=1_400_000)    # data URL base64 (audio/webm, audio/mp4, audio/ogg…)
    duree_s: float = Field(..., gt=0, le=VOIX_DUREE_MAX_S)           # durée annoncée par l'enregistreur du navigateur


class ParrainageIn(BaseModel):
    utilisateur: Utilisateur
    code: str = Field("", max_length=20)


class FormuleIn(BaseModel):
    plateforme: str = Field(..., min_length=2, max_length=30)
    nom: str = Field(..., min_length=2, max_length=60)
    description: str = Field("", max_length=300)
    prix: int = Field(..., ge=100, le=10_000_000)            # FCFA
    duree_jours: int = Field(DUREE_DEFAUT, ge=1, le=366)
    fonctions: List[str] = Field(default_factory=list, max_length=5)
    actif: bool = True
    ordre: int = Field(0, ge=0, le=999)


class ReglagesIn(BaseModel):
    parrainage_jours: int = Field(..., ge=0, le=90)           # jours offerts à CHACUN (0 = parrainage sans récompense)
    ocr_par_jour: Optional[int] = Field(None, ge=1, le=500)   # lectures OCR par jour et par utilisateur
    voix_par_jour: Optional[int] = Field(None, ge=1, le=200)  # notes vocales transcrites par jour et par utilisateur
    archives_mo: Optional[int] = Field(None, ge=10, le=5000)  # espace d'archives en ligne par utilisateur, en Mo
    archives_gratuit_mo: Optional[int] = Field(None, ge=0, le=1000)      # lot 277 : espace en ligne offert sans abonnement, en Mo
    archives_gratuit_nombre: Optional[int] = Field(None, ge=0, le=1000)  # lot 277 : documents en ligne offerts sans abonnement
    cartes_par_jour: Optional[int] = Field(None, ge=1, le=100)  # lot 242 : images de cartes générées par jour et par utilisateur


async def _whisper(octets: bytes, extension: str, langue: str) -> str:
    """Transcription par Whisper (client IA local, même que le support) ; fichier temporaire supprimé aussitôt."""
    import os
    import tempfile
    from ia_client import OpenAISpeechToText, cle_ia
    chemin = None
    try:
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as f:
            f.write(octets)
            chemin = f.name
        stt = OpenAISpeechToText(api_key=cle_ia("openai"))
        with open(chemin, "rb") as fh:
            resp = await stt.transcribe(file=fh, model="whisper-1", response_format="json", language=langue)
        return getattr(resp, "text", None) or ""
    finally:
        if chemin and os.path.exists(chemin):
            try:
                os.unlink(chemin)
            except OSError:
                pass


def make_formules_plateformes(*, db, get_super_admin: Callable, pawapay: Dict[str, Any], hooks_apres_paiement: List[Any]):
    """Construit le routeur. `pawapay` : {jeton(reglages), hotes, devise(pays)} fournis par le portail client (p02)."""
    from routes.contrats_plateformes import signature_valide

    router = APIRouter(tags=["Formules des plateformes (lot 227)"])

    # ------------------------------------------------------------------ outils
    async def reglages_parrainage() -> int:
        s = await db.settings.find_one({"_id": "global"}, {"parrainage_jours": 1}) or {}
        v = s.get("parrainage_jours")
        return PARRAINAGE_JOURS_DEFAUT if v is None else int(v)

    async def reglage_ocr_par_jour() -> int:
        s = await db.settings.find_one({"_id": "global"}, {"ocr_plateformes_par_jour": 1}) or {}
        return int(s.get("ocr_plateformes_par_jour") or OCR_PAR_JOUR_DEFAUT)

    async def reglage_cartes_par_jour() -> int:
        s = await db.settings.find_one({"_id": "global"}, {"cartes_plateformes_par_jour": 1}) or {}
        return int(s.get("cartes_plateformes_par_jour") or 9)

    async def reglage_voix_par_jour() -> int:
        s = await db.settings.find_one({"_id": "global"}, {"transcription_plateformes_par_jour": 1}) or {}
        return int(s.get("transcription_plateformes_par_jour") or VOIX_PAR_JOUR_DEFAUT)

    async def exiger_abonnement(plateforme: str, m: dict, fonction: str, nom_service: str, libre: bool = False, refus: Optional[str] = None) -> None:
        """Refus 402 sans abonnement actif qui débloque `fonction` : le message donne le NOM et le PRIX de la formule la moins chère.
        `libre` = super-administrateur dispensé d'abonnement (les limites par jour restent appliquées)."""
        if libre or acces_fonction(m, fonction):
            return
        formules = await db.formules_plateformes.find({"plateforme": plateforme, "actif": True, "fonctions": fonction}, {"_id": 0}).sort("prix", 1).to_list(20)
        if formules:
            f = formules[0]
            prix = f"{int(f['prix']):,}".replace(",", " ")
            message = f"{refus or nom_service + ' réservée aux abonnés.'} Formule « {f['nom']} » : {prix} FCFA pour {f.get('duree_jours') or DUREE_DEFAUT} jours."
            formule = {"id": f["id"], "nom": f["nom"], "prix": f["prix"], "duree_jours": f.get("duree_jours") or DUREE_DEFAUT}
        else:
            message = f"{refus} Aucune formule n'est proposée pour le moment." if refus else f"{nom_service} réservée aux abonnés : aucune formule n'est proposée pour le moment."
            formule = None
        raise HTTPException(status_code=402, detail={"code": "abonnement_requis", "message": message, "formule": formule})

    def acces_fonction(m: dict, fonction: str) -> Optional[str]:
        """Meilleure expiration (ISO) d'un abonnement actif qui débloque `fonction`, sinon None."""
        maintenant, meilleur = _maintenant(), None
        for a in (m.get("abonnements") or {}).values():
            if fonction in (a.get("fonctions") or []) and jours_restants(a.get("expire_le"), maintenant) > 0:
                if meilleur is None or a["expire_le"] > meilleur:
                    meilleur = a["expire_le"]
        return meilleur

    async def plateforme_signee(request: Request) -> tuple:
        """Émetteur actif + signature valable → (émetteur, corps JSON brut décodé)."""
        code = (request.headers.get("X-Emetteur") or "").strip().lower()
        emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0}) if code else None
        if not emetteur or not emetteur.get("actif", True):
            raise HTTPException(status_code=401, detail="Émetteur inconnu ou désactivé")
        brut = await request.body()
        if not signature_valide(emetteur.get("secret") or "", request.headers.get("X-Timestamp") or "", brut,
                                request.headers.get("X-Signature") or "", _maintenant()):
            raise HTTPException(status_code=401, detail="Signature refusée")
        try:
            corps = json.loads(brut.decode("utf-8") or "{}")
        except ValueError:
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        if not isinstance(corps, dict):
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        return emetteur, corps

    def lire(modele, corps: dict):
        try:
            return modele(**corps)
        except Exception:  # noqa: BLE001 — message simple pour la plateforme
            raise HTTPException(status_code=422, detail="Données invalides")

    async def code_unique(plateforme: str) -> str:
        prefixe = "".join(c for c in plateforme.upper() if c.isalpha())[:2] or "SW"
        for _ in range(20):
            code = prefixe + "".join(secrets.choice(ALPHABET_CODE) for _ in range(6))
            if not await db.membres_plateformes.find_one({"code_parrainage": code}, {"_id": 1}):
                return code
        raise HTTPException(status_code=503, detail="Code de parrainage indisponible, réessayez")

    async def membre(plateforme: str, u: Utilisateur) -> dict:
        """Fiche de l'utilisateur de la plateforme : créée à la première demande, nom et téléphone tenus à jour."""
        m = await db.membres_plateformes.find_one({"plateforme": plateforme, "utilisateur_id": u.id}, {"_id": 0})
        if m:
            maj = {k: v for k, v in (("nom", u.nom), ("telephone", u.telephone)) if v and v != m.get(k)}
            if maj:
                await db.membres_plateformes.update_one({"id": m["id"]}, {"$set": maj})
                m.update(maj)
            return m
        m = {"id": str(uuid.uuid4()), "plateforme": plateforme, "utilisateur_id": u.id, "nom": u.nom, "telephone": u.telephone,
             "code_parrainage": await code_unique(plateforme), "parrain_id": None, "recompense_donnee": False,
             "abonnements": {}, "jours_gagnes": 0, "cree_le": _iso(_maintenant())}
        await db.membres_plateformes.insert_one(m.copy())
        return m

    def vue_abonnements(m: dict, formules: List[dict]) -> List[dict]:
        """Une ligne par abonnement connu : formule, fonctions, expiration, jours restants, actif."""
        maintenant, noms = _maintenant(), {f["id"]: f for f in formules}
        out = []
        for fid, a in (m.get("abonnements") or {}).items():
            f = noms.get(fid) or {}
            out.append({"formule_id": fid, "nom": a.get("nom") or f.get("nom") or "Formule", "fonctions": a.get("fonctions") or [],
                        "expire_le": a.get("expire_le"), "jours_restants": jours_restants(a.get("expire_le"), maintenant),
                        "actif": jours_restants(a.get("expire_le"), maintenant) > 0})
        return sorted(out, key=lambda a: a["expire_le"] or "", reverse=True)

    async def formules_demandees(plateforme: str, formule_id: Optional[str], formule_ids: List[str]) -> List[dict]:
        """Lot 244 : formules ACTIVES de la plateforme, dans l'ordre demandé, sans doublon. 422 si aucune ; 404 si l'une est introuvable.
        Le montant à payer est TOUJOURS recalculé ici, jamais lu depuis la plateforme."""
        ids = list(dict.fromkeys([*formule_ids, *([formule_id] if formule_id else [])]))
        if not ids:
            raise HTTPException(status_code=422, detail="Choisissez au moins une formule")
        trouvees = {f["id"]: f async for f in db.formules_plateformes.find({"id": {"$in": ids}, "plateforme": plateforme, "actif": True}, {"_id": 0})}
        if len(trouvees) != len(ids):
            raise HTTPException(status_code=404, detail="Formule introuvable")
        return [trouvees[i] for i in ids]

    def lignes_achat(formules: List[dict]) -> List[dict]:
        return [{"id": f["id"], "nom": f["nom"], "prix": int(f["prix"]), "duree_jours": int(f.get("duree_jours") or DUREE_DEFAUT),
                 "fonctions": f.get("fonctions") or []} for f in formules]

    def libelle_achat(formules: List[dict]) -> str:
        return formules[0]["nom"] if len(formules) == 1 else f"{len(formules)} formules : " + ", ".join(f["nom"] for f in formules)

    async def activer(m: dict, formule: dict, jours: int, source: str) -> str:
        """Ajoute `jours` à l'abonnement du membre pour cette formule (cumul) et renvoie la nouvelle expiration."""
        courante = ((m.get("abonnements") or {}).get(formule["id"]) or {}).get("expire_le")
        e = _iso(nouvelle_expiration(courante, jours, _maintenant()))
        await db.membres_plateformes.update_one({"id": m["id"]}, {"$set": {
            f"abonnements.{formule['id']}": {"nom": formule["nom"], "fonctions": formule.get("fonctions") or [],
                                             "expire_le": e, "source": source, "maj_le": _iso(_maintenant())}}})
        return e

    # ------------------------------------------------------------------ après paiement (crochet du portail)
    async def apres_paiement(payment: dict) -> None:
        """Paiement « completed » d'une formule : active (UNE fois) et applique le parrainage."""
        if payment.get("flow") != "formule_plateforme":
            return
        # Verrou d'idempotence : seul le premier appel passe (webhooks répétés, relecture + webhook…)
        r = await db.payments.update_one({"deposit_id": payment["deposit_id"], "activation_faite": {"$ne": True}},
                                         {"$set": {"activation_faite": True, "activation_le": _iso(_maintenant())}})
        if not r.modified_count:
            return
        m = await db.membres_plateformes.find_one({"id": payment.get("membre_id")}, {"_id": 0})
        # Lot 244 : un paiement peut couvrir plusieurs formules (champ « formule_ids ») ; les anciens paiements n'en ont qu'une (« formule_id »)
        ids = payment.get("formule_ids") or [payment.get("formule_id")]
        trouvees = {x["id"]: x async for x in db.formules_plateformes.find({"id": {"$in": ids}}, {"_id": 0})}
        formules = [trouvees[i] for i in ids if i in trouvees]
        if not m or not formules:
            logger.warning("[formules] paiement %s : membre ou formule introuvable", payment["deposit_id"])
            return
        for formule in formules:
            await activer(m, formule, int(formule.get("duree_jours") or DUREE_DEFAUT), "achat")
        f = formules[0]       # parrainage : les jours offerts portent sur la première formule du paiement
        # Parrainage : à la PREMIÈRE formule payée du filleul, jours offerts au filleul et au parrain (même formule)
        jours = await reglages_parrainage()
        if m.get("parrain_id") and not m.get("recompense_donnee") and jours > 0:
            await db.membres_plateformes.update_one({"id": m["id"]}, {"$set": {"recompense_donnee": True}})
            parrain = await db.membres_plateformes.find_one({"id": m["parrain_id"]}, {"_id": 0})
            m2 = await db.membres_plateformes.find_one({"id": m["id"]}, {"_id": 0})
            await activer(m2, f, jours, "parrainage")
            await db.membres_plateformes.update_one({"id": m["id"]}, {"$inc": {"jours_gagnes": jours}})
            if parrain:
                await activer(parrain, f, jours, "parrainage")
                await db.membres_plateformes.update_one({"id": parrain["id"]}, {"$inc": {"jours_gagnes": jours}})

    hooks_apres_paiement.append(apres_paiement)

    # ------------------------------------------------------------------ routes signées des plateformes
    @router.post("/formules-plateformes/catalogue")
    async def catalogue(request: Request):
        emetteur, corps = await plateforme_signee(request)
        u = lire(CatalogueIn, corps).utilisateur
        m = await membre(emetteur["code"], u)
        formules = await db.formules_plateformes.find({"plateforme": emetteur["code"], "actif": True}, {"_id": 0}).sort("ordre", 1).to_list(50)
        return {"formules": [{"id": f["id"], "nom": f["nom"], "description": f.get("description", ""), "prix": f["prix"], "devise": "XOF",
                              "duree_jours": f.get("duree_jours") or DUREE_DEFAUT, "fonctions": f.get("fonctions") or []} for f in formules],
                "abonnements": vue_abonnements(m, formules + await db.formules_plateformes.find({"plateforme": emetteur["code"], "actif": False}, {"_id": 0}).to_list(50)),
                "code_parrainage": m["code_parrainage"], "a_un_parrain": bool(m.get("parrain_id")), "parrainage_jours": await reglages_parrainage()}

    @router.post("/formules-plateformes/devis")
    async def devis(request: Request):
        """Lot 244 : récapitulatif d'un achat groupé (lignes et total) affiché avant le paiement ; rien n'est enregistré."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(DevisIn, corps)
        formules = await formules_demandees(emetteur["code"], None, d.formule_ids)
        lignes = lignes_achat(formules)
        return {"lignes": lignes, "nombre": len(lignes), "total": sum(x["prix"] for x in lignes), "devise": "XOF"}

    @router.post("/formules-plateformes/acheter")
    async def acheter(request: Request):
        emetteur, corps = await plateforme_signee(request)
        d = lire(AcheterIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        formules = await formules_demandees(emetteur["code"], d.formule_id, d.formule_ids)     # lot 244 : une ou plusieurs formules
        lignes = lignes_achat(formules)
        total = sum(x["prix"] for x in lignes)
        f = {"id": formules[0]["id"], "nom": libelle_achat(formules), "prix": total}
        s = await db.settings.find_one({"_id": "global"}) or {}
        if not s.get("pawapay_enabled"):
            raise HTTPException(status_code=503, detail="Paiement indisponible pour le moment")
        token = pawapay["jeton"](s)
        if not token:
            raise HTTPException(status_code=503, detail="Paiement indisponible pour le moment")
        env = (s.get("pawapay_environment") or "sandbox").lower()
        host = pawapay["hotes"].get(env, pawapay["hotes"]["sandbox"])
        country = (s.get("pawapay_country") or "BFA").upper()
        deposit_id = str(uuid.uuid4())
        msisdn = "".join(c for c in (m.get("telephone") or "") if c.isdigit())
        corps_pp: Dict[str, Any] = {"depositId": deposit_id, "country": country, "reason": f"Abonnement {f['nom']}"[:50],
                                    "amountDetails": {"amount": str(total), "currency": pawapay["devise"](country)}}
        if d.retour.startswith("https://"):
            # PawaPay n'ajoute rien à l'adresse de retour : on y joint le numéro du paiement pour que la plateforme vérifie l'achat
            corps_pp["returnUrl"] = f"{d.retour}{'&' if '?' in d.retour else '?'}depositId={deposit_id}"
        if len(msisdn) >= 8:
            corps_pp["phoneNumber"] = msisdn
        # On inscrit le paiement AVANT d'appeler PawaPay (jamais de depositId perdu)
        paiement = {"id": str(uuid.uuid4()), "deposit_id": deposit_id, "client_id": None, "user_id": None, "user_label": m.get("nom") or m["utilisateur_id"],
                    "amount": float(total), "currency": "XOF", "country": country, "msisdn": msisdn or None,
                    "description": f"Abonnement {f['nom']} — {emetteur['code']}", "environment": env, "flow": "formule_plateforme",
                    "plateforme": emetteur["code"], "membre_id": m["id"], "formule_id": f["id"], "formule_ids": [x["id"] for x in lignes],
                    "lignes": [{"formule_id": x["id"], "prix": x["prix"]} for x in lignes], "status": "initiated",
                    "created_at": _iso(_maintenant()), "updated_at": _iso(_maintenant())}
        await db.payments.insert_one(paiement.copy())
        try:
            async with httpx.AsyncClient(timeout=20, transport=_transport) as http:
                r = await http.post(f"{host}/v2/paymentpage", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=corps_pp)
                rep = r.json()
        except Exception:  # noqa: BLE001
            await db.payments.update_one({"deposit_id": deposit_id}, {"$set": {"status": "failed", "api_status": "ERREUR_RESEAU"}})
            raise HTTPException(status_code=502, detail="Page de paiement indisponible, réessayez dans un instant")
        url = (rep or {}).get("redirectUrl")
        if not url:
            await db.payments.update_one({"deposit_id": deposit_id}, {"$set": {"status": "failed", "api_status": "PAGE_REFUSEE", "raw_response": rep}})
            raise HTTPException(status_code=502, detail="Page de paiement refusée, réessayez dans un instant")
        await db.payments.update_one({"deposit_id": deposit_id}, {"$set": {"redirect_url": url}})
        return {"ok": True, "deposit_id": deposit_id, "redirect_url": url, "total": total, "lignes": lignes}

    async def rafraichir(deposit_id: str, p: dict) -> dict:
        """Interroge PawaPay si le webhook n'est pas encore arrivé ; paiement confirmé → active la formule."""
        s = await db.settings.find_one({"_id": "global"}) or {}
        token = pawapay["jeton"](s)
        if not token:
            return p
        env = (p.get("environment") or s.get("pawapay_environment") or "sandbox").lower()
        host = pawapay["hotes"].get(env, pawapay["hotes"]["sandbox"])
        try:
            async with httpx.AsyncClient(timeout=15, transport=_transport) as http:
                r = await http.get(f"{host}/v2/deposits/{deposit_id}", headers={"Authorization": f"Bearer {token}"})
                data = r.json() if r.status_code < 400 else {}
        except Exception:  # noqa: BLE001
            return p
        entree = (data.get("data") or {}) if (data.get("status") or "").upper() == "FOUND" else {}
        api = (entree.get("status") or "").upper()
        nouveau = {"COMPLETED": "completed", "FAILED": "failed", "REJECTED": "failed"}.get(api)
        if nouveau:
            await db.payments.update_one({"deposit_id": deposit_id}, {"$set": {"status": nouveau, "api_status": api, "updated_at": _iso(_maintenant())}})
            p = await db.payments.find_one({"deposit_id": deposit_id}, {"_id": 0}) or p
            if nouveau == "completed":
                await apres_paiement(p)
        return p

    # ------------------------------------------------------------------ paiement PI-SPI (virement instantané BCEAO), version MANUELLE
    # Les réglages (banque, titulaire, QR de la banque, consigne) sont ceux de l'encaissement PI-SPI (routes/pispi.py).
    # Manuel : l'utilisateur paie avec le QR de la banque, déclare la référence bancaire, l'administrateur CONFIRME ici.
    # Prêt pour l'automatique : quand une banque fournira son API (routes/pispi_connecteur.py), sa notification de paiement
    # n'aura qu'à appeler `confirmer_pispi(...)` — la même fonction que le bouton « Confirmer » de l'administrateur.
    STATUTS_PISPI_OUVERTS = ("pispi_attente", "pispi_verification")

    async def confirmer_pispi(reference: str, reference_bancaire: Optional[str], par: str, source: str = "manuel") -> dict:
        """Paiement PI-SPI reçu : la formule est activée (une seule fois) et l'encaissement est inscrit au registre PI-SPI."""
        from routes.pispi import enregistrer_transaction
        p = await db.payments.find_one({"deposit_id": reference, "flow": "formule_plateforme", "methode": "pispi"}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Demande PI-SPI introuvable")
        if p.get("status") == "completed":
            return p                                                        # déjà confirmée : rien à refaire
        if p.get("status") not in STATUTS_PISPI_OUVERTS:
            raise HTTPException(status_code=409, detail="Demande déjà refusée ou clôturée")
        ref_banque = (reference_bancaire or p.get("reference_bancaire") or "").strip() or None
        await db.payments.update_one({"deposit_id": reference}, {"$set": {"status": "completed", "api_status": "PISPI", "reference_bancaire": ref_banque,
                                                                          "confirme_par": par, "updated_at": _iso(_maintenant())}})
        p = await db.payments.find_one({"deposit_id": reference}, {"_id": 0})
        await apres_paiement(p)
        await enregistrer_transaction(reference=reference, montant=float(p["amount"]), statut="rapproche", source=source,
                                      reference_bancaire=ref_banque, document={"type": "abonnement_plateforme", "id": p.get("membre_id"), "numero": reference},
                                      saisi_par=par)
        return p

    @router.post("/formules-plateformes/pispi/demander")
    async def pispi_demander(request: Request):
        """L'utilisateur choisit de payer par PI-SPI : référence de la demande + bloc de paiement (banque, titulaire, QR, montant, consigne)."""
        from routes.pispi import bloc, lire_parametres, sans_octets
        from routes.pispi_connecteur import ConnecteurIndisponible, connecteur_actif
        emetteur, corps = await plateforme_signee(request)
        d = lire(PispiDemandeIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        formules = await formules_demandees(emetteur["code"], d.formule_id, d.formule_ids)     # lot 244 : une ou plusieurs formules
        lignes = lignes_achat(formules)
        total = sum(x["prix"] for x in lignes)
        ids = sorted(x["id"] for x in lignes)
        f = {"id": formules[0]["id"], "nom": libelle_achat(formules), "prix": total}
        param = await lire_parametres()
        b = bloc(param, reference="", reste_du=float(f["prix"]))
        if not b.get("afficher"):
            raise HTTPException(status_code=503, detail="Paiement PI-SPI indisponible pour le moment")
        # Une demande encore ouverte pour la même formule est reprise (pas de doublon à confirmer)
        ouverte = await db.payments.find_one({"flow": "formule_plateforme", "methode": "pispi", "membre_id": m["id"], "formule_ids_tri": ids,
                                              "status": {"$in": list(STATUTS_PISPI_OUVERTS)}}, {"_id": 0})
        if not ouverte and len(ids) == 1:       # anciennes demandes (avant le lot 244) : une seule formule, sans liste
            ouverte = await db.payments.find_one({"flow": "formule_plateforme", "methode": "pispi", "membre_id": m["id"], "formule_id": ids[0],
                                                  "formule_ids_tri": {"$exists": False}, "status": {"$in": list(STATUTS_PISPI_OUVERTS)}}, {"_id": 0})
        if ouverte:
            reference = ouverte["deposit_id"]
        else:
            reference = "ABO-" + secrets.token_hex(4).upper()
            await db.payments.insert_one({"id": str(uuid.uuid4()), "deposit_id": reference, "client_id": None, "user_id": None,
                                          "user_label": m.get("nom") or m["utilisateur_id"], "amount": float(f["prix"]), "currency": "XOF",
                                          "description": f"Abonnement {f['nom']} — {emetteur['code']} (PI-SPI)", "flow": "formule_plateforme",
                                          "methode": "pispi", "plateforme": emetteur["code"], "membre_id": m["id"], "formule_id": f["id"],
                                          "formule_ids": [x["id"] for x in lignes], "formule_ids_tri": ids,
                                          "lignes": [{"formule_id": x["id"], "prix": x["prix"]} for x in lignes], "status": "pispi_attente", "created_at": _iso(_maintenant()), "updated_at": _iso(_maintenant())})
        c = connecteur_actif()
        try:
            await c.demander_paiement(reference=reference, montant=float(f["prix"]))      # manuel : simple rappel ; banque branchée : demande réelle
        except ConnecteurIndisponible:
            pass
        b = bloc(param, reference=reference, reste_du=float(f["prix"]))
        statut = ouverte["status"] if ouverte else "pispi_attente"       # « pispi_verification » : référence déjà déclarée
        return {"reference": reference, "bloc": sans_octets(b), "automatique": bool(c.automatique), "statut": statut, "total": total, "lignes": lignes}

    @router.post("/formules-plateformes/pispi/declarer")
    async def pispi_declarer(request: Request):
        """L'utilisateur a payé : il indique la référence bancaire de son virement ; l'administrateur la vérifie puis confirme."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(PispiDeclareIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        p = await db.payments.find_one({"deposit_id": d.reference, "flow": "formule_plateforme", "methode": "pispi", "membre_id": m["id"]}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Demande PI-SPI introuvable")
        if p["status"] == "completed":
            return {"statut": "paye"}
        if p["status"] not in STATUTS_PISPI_OUVERTS:
            raise HTTPException(status_code=409, detail="Cette demande est clôturée : faites-en une nouvelle")
        await db.payments.update_one({"deposit_id": d.reference}, {"$set": {"status": "pispi_verification", "reference_bancaire": d.reference_bancaire.strip(),
                                                                            "declare_le": _iso(_maintenant()), "updated_at": _iso(_maintenant())}})
        return {"statut": "pispi_verification"}

    @router.get("/admin/formules-plateformes/pispi")
    async def admin_pispi_liste(_: dict = Depends(get_super_admin)):
        """Demandes PI-SPI à traiter : « à vérifier » (référence déclarée) d'abord, puis « en attente » de virement."""
        lignes = await db.payments.find({"flow": "formule_plateforme", "methode": "pispi", "status": {"$in": list(STATUTS_PISPI_OUVERTS)}},
                                        {"_id": 0}).sort("created_at", -1).to_list(100)
        formules = {f["id"]: f for f in await db.formules_plateformes.find({}, {"_id": 0, "id": 1, "nom": 1}).to_list(200)}
        out = [{"reference": p["deposit_id"], "plateforme": p.get("plateforme"), "utilisateur": p.get("user_label"), "formule": " + ".join((formules.get(i) or {}).get("nom") or "?" for i in (p.get("formule_ids") or [p.get("formule_id")])),
                "montant": p.get("amount"), "statut": p["status"], "reference_bancaire": p.get("reference_bancaire"), "cree_le": p.get("created_at"),
                "declare_le": p.get("declare_le")} for p in lignes]
        out.sort(key=lambda x: 0 if x["statut"] == "pispi_verification" else 1)
        return {"demandes": out}

    @router.post("/admin/formules-plateformes/pispi/{reference}/confirmer")
    async def admin_pispi_confirmer(reference: str, corps: PispiConfirmationIn, adm: dict = Depends(get_super_admin)):
        p = await confirmer_pispi(reference, corps.reference_bancaire, adm.get("email") or "admin")
        return {"ok": True, "statut": p["status"]}

    @router.post("/admin/formules-plateformes/pispi/{reference}/refuser")
    async def admin_pispi_refuser(reference: str, _: dict = Depends(get_super_admin)):
        r = await db.payments.update_one({"deposit_id": reference, "flow": "formule_plateforme", "methode": "pispi", "status": {"$in": list(STATUTS_PISPI_OUVERTS)}},
                                         {"$set": {"status": "failed", "api_status": "PISPI_REFUSE", "updated_at": _iso(_maintenant())}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Demande PI-SPI introuvable ou déjà clôturée")
        return {"ok": True}

    @router.post("/formules-plateformes/achat")
    async def achat(request: Request):
        emetteur, corps = await plateforme_signee(request)
        d = lire(AchatIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        p = await db.payments.find_one({"deposit_id": d.deposit_id, "flow": "formule_plateforme", "membre_id": m["id"]}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Paiement introuvable")
        if p.get("status") in ("initiated", "pending"):
            p = await rafraichir(d.deposit_id, p)
        # PI-SPI : « pispi_attente » = le QR est affiché, rien n'est encore déclaré ; « pispi_verification » = référence bancaire
        # déclarée, en attente de confirmation de l'administrateur
        statut = {"completed": "paye", "failed": "echec", "pispi_attente": "pispi_attente",
                  "pispi_verification": "pispi_verification"}.get(p.get("status"), "attente")
        return {"statut": statut, "formule_id": p.get("formule_id"), "formule_ids": p.get("formule_ids") or [p.get("formule_id")]}

    @router.post("/formules-plateformes/acces")
    async def acces(request: Request):
        """La plateforme demande si l'utilisateur a droit à une fonction (ex. ocr_ordonnances)."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(AccesIn, corps)
        m = await db.membres_plateformes.find_one({"plateforme": emetteur["code"], "utilisateur_id": d.utilisateur.id}, {"_id": 0}) or {}
        maintenant, meilleur = _maintenant(), acces_fonction(m, d.fonction)
        return {"actif": meilleur is not None, "expire_le": meilleur, "jours_restants": jours_restants(meilleur, maintenant)}

    @router.post("/formules-plateformes/abonnes")
    async def abonnes(request: Request):
        """La plateforme (administrateur) demande les abonnements ACTIFS de ses comptes : formule, fonctions, date d'expiration."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(AbonnesIn, corps)
        maintenant, resultat = _maintenant(), {}
        # Une seule lecture pour tous les comptes demandés (jamais une lecture par compte)
        async for m in db.membres_plateformes.find({"plateforme": emetteur["code"], "utilisateur_id": {"$in": d.utilisateurs}}, {"_id": 0, "utilisateur_id": 1, "abonnements": 1}):
            actifs = [{"formule": a.get("nom"), "fonctions": a.get("fonctions") or [], "expire_le": a.get("expire_le"),
                       "jours_restants": jours_restants(a.get("expire_le"), maintenant)}
                      for a in (m.get("abonnements") or {}).values() if jours_restants(a.get("expire_le"), maintenant) > 0]
            if actifs:
                resultat[m["utilisateur_id"]] = sorted(actifs, key=lambda x: x["expire_le"] or "", reverse=True)
        return {"abonnes": resultat}

    # ------------------------------------------------------------------ archives en ligne chiffrées (lot 233)
    # Le site chiffre LUI-MÊME chaque document et ses informations (AES-256-GCM, clé dérivée d'une phrase secrète que SAWALI ne connaît pas) :
    # ici ne transitent et ne sont gardés que des octets illisibles. Lire et supprimer restent permis après la fin de l'abonnement ;
    # ajouter exige un abonnement actif qui débloque « archives_cloud ».
    async def reglage_archives_octets() -> int:
        s = await db.settings.find_one({"_id": "global"}, {"archives_plateformes_mo": 1}) or {}
        return int(s.get("archives_plateformes_mo") or ARCHIVES_MO_DEFAUT) * 1_000_000

    async def reglage_archives_gratuit() -> tuple:
        """Lot 277 — (octets, nombre de documents) offerts à tout utilisateur SANS abonnement : ses papiers importants ne doivent pas
        dépendre de la mémoire d'un navigateur."""
        s = await db.settings.find_one({"_id": "global"}, {"archives_gratuit_mo": 1, "archives_gratuit_nombre": 1}) or {}
        mo = s.get("archives_gratuit_mo")
        nb = s.get("archives_gratuit_nombre")
        return (int(ARCHIVES_GRATUIT_MO_DEFAUT if mo is None else mo) * 1_000_000,
                int(ARCHIVES_GRATUIT_NOMBRE_DEFAUT if nb is None else nb))

    async def usage_archives(m: dict) -> tuple:
        """(octets utilisés, nombre de documents) d'un utilisateur : une seule lecture."""
        octets, n = 0, 0
        async for a in db.archives_cloud.find({"plateforme": m["plateforme"], "membre_id": m["id"]}, {"_id": 0, "taille": 1}):
            octets += int(a.get("taille") or 0)
            n += 1
        return octets, n

    def chemin_archive(m: dict, archive_id: str) -> str:
        return f"sawali/archives/{m['plateforme']}/{m['id']}/{archive_id}"

    @router.post("/formules-plateformes/archives/etat")
    async def archives_etat(request: Request):
        """Abonnement actif ? sel et jeton de contrôle de la phrase secrète (s'ils existent), espace utilisé et espace total."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(CatalogueIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        utilise, n = await usage_archives(m)
        cle = m.get("archives_cle") or {}
        abonne = bool(d.utilisateur.acces_libre or acces_fonction(m, FONCTION_ARCHIVES))
        gratuit_octets, gratuit_nombre = await reglage_archives_gratuit()
        # Lot 277 : sans abonnement, l'espace offert s'applique (quota et nombre de documents) ; abonné : l'espace de la formule
        return {"abonne": abonne, "sel": cle.get("sel"), "verif": cle.get("verif"),
                "enveloppe": cle.get("enveloppe"), "secours": cle.get("secours"),
                "a2f": bool((m.get("archives_pin") or {}).get("totp")),      # lot 279 : application d'authentification activée ?
                "pin": (m.get("archives_pin") or {}).get("type"),     # lot 278 : "pin" | "phrase" si le serveur contrôle les essais, sinon None
                "quota_octets": await reglage_archives_octets() if abonne else gratuit_octets,
                "nombre_max": None if abonne else gratuit_nombre,
                "utilise_octets": utilise, "nombre": n, "fichier_max_octets": ARCHIVE_FICHIER_MAX}

    @router.post("/formules-plateformes/archives/cle")
    async def archives_cle(request: Request):
        """Première activation : enregistre le sel et le jeton de contrôle (JAMAIS la phrase). Une seule fois : changer de phrase rendrait
        les documents déjà archivés illisibles."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(ArchiveCleIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        existante = m.get("archives_cle")
        if existante:
            if existante.get("sel") == d.sel:
                return {"ok": True}
            raise HTTPException(status_code=409, detail="Une phrase secrète est déjà enregistrée pour vos archives")
        cle = {"sel": d.sel, "verif": d.verif}
        if d.enveloppe:
            cle["enveloppe"] = d.enveloppe          # lot 277 : clé des documents chiffrée par la phrase
        if d.secours:
            cle["secours"] = d.secours              # lot 277 : clé des documents chiffrée par le code de secours
        await db.membres_plateformes.update_one({"id": m["id"], "archives_cle": {"$exists": False}}, {"$set": {"archives_cle": cle}})
        return {"ok": True}

    # ---- Lot 278 : code PIN ou phrase COURTE, protégés par une limite d'essais côté serveur ----------------------------------------
    # Un code de 4 chiffres n'offre que 10 000 possibilités : seul, il serait deviné en quelques minutes par qui détiendrait les données.
    # Le serveur garde donc, hors de la base, un secret (variable d'environnement ARCHIVES_SECRET_SERVEUR, à défaut dérivé de JWT_SECRET) dont il
    # tire un « poivre » propre à chaque utilisateur ; la clé qui ouvre les documents est protégée par (code + poivre). Le poivre n'est rendu qu'à
    # la bonne preuve du code : 5 essais ratés = 15 min de pause ; 10 échecs = le code de secours devient nécessaire. Le serveur ne connaît ni le
    # code ni la clé des documents et ne peut pas les lire. Limite honnête : si la base ET ce secret du serveur sont volés ensemble, un code court
    # peut être deviné (un code de secours ou une phrase longue restent hors de portée).
    def poivre_archives(m: dict, sel_serveur: str) -> str:
        secret = (os.environ.get("ARCHIVES_SECRET_SERVEUR") or (os.environ.get("JWT_SECRET", "") + "-archives")).encode()
        return base64.b64encode(hmac.new(secret, f"{m['id']}|{sel_serveur}".encode(), hashlib.sha256).digest()).decode("ascii")

    def empreinte_preuve(preuve: str) -> str:
        return hashlib.sha256(preuve.encode("ascii", "ignore")).hexdigest()

    @router.post("/formules-plateformes/archives/pin/enregistrer")
    async def archives_pin_enregistrer(request: Request):
        """Enregistre (ou remplace, après récupération par le code de secours ou changement) la preuve du code. Rend le poivre."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(ArchivePinEnregistrerIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        existante = m.get("archives_cle")
        if existante and existante.get("verif") != d.verif_actuelle:
            raise HTTPException(status_code=409, detail="Jeton de contrôle incorrect")       # 409 : le 403 est réservé aux plateformes non autorisées
        sel_serveur = secrets.token_hex(16)                                                    # nouveau sel serveur : le poivre change à chaque (ré)enregistrement
        await db.membres_plateformes.update_one({"id": m["id"]}, {"$set": {"archives_pin": {
            "preuve_hash": empreinte_preuve(d.preuve), "sel_serveur": sel_serveur, "type": d.type_secret,
            "essais": 0, "echecs": 0, "bloque_jusqu": None}}})
        return {"ok": True, "poivre": poivre_archives(m, sel_serveur)}

    # ---- Contrôle des essais, partagé par « pin/ouvrir » et « totp/desactiver » -------------------------------------------------
    def exiger_hors_pause(pin: dict) -> None:
        """429 si les essais sont en pause (5 ratés) ou si le code de secours est devenu nécessaire (10 échecs)."""
        if int(pin.get("echecs") or 0) >= PIN_ECHECS_AVANT_SECOURS:
            raise HTTPException(status_code=429, detail="Trop d'essais ratés : utilisez votre code de secours pour rouvrir vos archives")
        bloque = pin.get("bloque_jusqu")
        if bloque and datetime.fromisoformat(bloque) > _maintenant():
            minutes = max(1, int((datetime.fromisoformat(bloque) - _maintenant()).total_seconds() // 60) + 1)
            raise HTTPException(status_code=429, detail=f"Trop d'essais : réessayez dans {minutes} min (ou utilisez votre code de secours)")

    async def noter_echec(m: dict, pin: dict, message: str) -> None:
        """Compte l'essai raté puis lève l'erreur adaptée (409 avec essais restants, 429 pause ou code de secours)."""
        essais, echecs = int(pin.get("essais") or 0) + 1, int(pin.get("echecs") or 0) + 1
        maj = {"archives_pin.essais": essais, "archives_pin.echecs": echecs}
        if essais >= PIN_ESSAIS_AVANT_PAUSE:
            maj["archives_pin.essais"] = 0
            maj["archives_pin.bloque_jusqu"] = _iso(_maintenant() + timedelta(minutes=PIN_PAUSE_MINUTES))
        await db.membres_plateformes.update_one({"id": m["id"]}, {"$set": maj})
        if echecs >= PIN_ECHECS_AVANT_SECOURS:
            raise HTTPException(status_code=429, detail="Trop d'essais ratés : utilisez votre code de secours pour rouvrir vos archives")
        if essais >= PIN_ESSAIS_AVANT_PAUSE:
            raise HTTPException(status_code=429, detail=f"Trop d'essais : réessayez dans {PIN_PAUSE_MINUTES} min (ou utilisez votre code de secours)")
        restants = PIN_ESSAIS_AVANT_PAUSE - essais
        raise HTTPException(status_code=409, detail=f"{message} ({restants} essai{'s' if restants > 1 else ''} avant une pause)")

    # Secret de l'application d'authentification : gardé CHIFFRÉ (AES-GCM, clé tirée du secret du serveur hors base)
    def cle_totp() -> bytes:
        secret = (os.environ.get("ARCHIVES_SECRET_SERVEUR") or (os.environ.get("JWT_SECRET", "") + "-archives"))
        return hashlib.sha256((secret + "|totp").encode()).digest()

    def chiffrer_totp(secret_b32: str) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = secrets.token_bytes(12)
        return base64.b64encode(nonce + AESGCM(cle_totp()).encrypt(nonce, secret_b32.encode(), b"archives-totp")).decode("ascii")

    def dechiffrer_totp(valeur: str) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        brut = base64.b64decode(valeur)
        return AESGCM(cle_totp()).decrypt(brut[:12], brut[12:], b"archives-totp").decode()

    @router.post("/formules-plateformes/archives/pin/ouvrir")
    async def archives_pin_ouvrir(request: Request):
        """Contrôle la preuve du code (et, si activée, le code de l'application d'authentification) : bonne = rend le poivre ;
        mauvaise = compte l'essai (pause après 5, code de secours après 10)."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(ArchivePinOuvrirIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        pin = m.get("archives_pin")
        if not pin:
            raise HTTPException(status_code=404, detail="Aucun code enregistré pour vos archives")
        exiger_hors_pause(pin)
        preuve_ok = hmac.compare_digest(empreinte_preuve(d.preuve), pin["preuve_hash"])
        totp = pin.get("totp")
        pas = None
        if totp:
            pas = archives_totp.verifier(dechiffrer_totp(totp["secret_chiffre"]), d.code_totp or "", time.time(), totp.get("dernier_pas"))
        if preuve_ok and (not totp or pas is not None):
            maj = {"archives_pin.essais": 0, "archives_pin.echecs": 0, "archives_pin.bloque_jusqu": None}
            if pas is not None:
                maj["archives_pin.totp.dernier_pas"] = pas              # un code ne sert qu'une fois
            await db.membres_plateformes.update_one({"id": m["id"]}, {"$set": maj})
            return {"ok": True, "poivre": poivre_archives(m, pin["sel_serveur"])}
        # Même message que le code soit faux ou l'application : on ne dit pas lequel des deux a échoué
        await noter_echec(m, pin, "Code, phrase ou code de l'application incorrect" if totp else "Code ou phrase incorrect")

    # ---- Lot 279 : application d'authentification (Authenticator…) en plus du code PIN / de la phrase -------------------------------
    @router.post("/formules-plateformes/archives/totp/preparer")
    async def archives_totp_preparer(request: Request):
        """Crée un secret en attente et renvoie l'adresse otpauth:// (le site en fait un QR code). Rien n'est actif tant que
        « totp/activer » n'a pas reçu un code valable : une erreur de scan ne peut jamais verrouiller l'utilisateur dehors."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(ArchiveTotpPreparerIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        pin, cle = m.get("archives_pin"), m.get("archives_cle") or {}
        if not pin or cle.get("verif") != d.verif_actuelle:
            raise HTTPException(status_code=409, detail="Jeton de contrôle incorrect")
        secret = archives_totp.nouveau_secret()
        await db.membres_plateformes.update_one({"id": m["id"]}, {"$set": {"archives_pin.totp_attente": chiffrer_totp(secret)}})
        compte = (d.utilisateur.telephone or d.utilisateur.nom or "archives").strip() or "archives"
        return {"secret": secret, "uri": archives_totp.uri_otpauth(secret, compte)}

    @router.post("/formules-plateformes/archives/totp/activer")
    async def archives_totp_activer(request: Request):
        emetteur, corps = await plateforme_signee(request)
        d = lire(ArchiveTotpActiverIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        pin = m.get("archives_pin") or {}
        attente = pin.get("totp_attente")
        if not attente:
            raise HTTPException(status_code=409, detail="Aucune activation en cours : recommencez")
        exiger_hors_pause(pin)
        pas = archives_totp.verifier(dechiffrer_totp(attente), d.code, time.time())
        if pas is None:
            await noter_echec(m, pin, "Code incorrect : vérifiez l'heure de votre téléphone")
        await db.membres_plateformes.update_one({"id": m["id"]}, {
            "$set": {"archives_pin.totp": {"secret_chiffre": attente, "dernier_pas": pas}, "archives_pin.essais": 0},
            "$unset": {"archives_pin.totp_attente": ""}})
        return {"ok": True}

    @router.post("/formules-plateformes/archives/totp/desactiver")
    async def archives_totp_desactiver(request: Request):
        emetteur, corps = await plateforme_signee(request)
        d = lire(ArchiveTotpDesactiverIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        pin = m.get("archives_pin") or {}
        totp = pin.get("totp")
        if not totp:
            return {"ok": True}
        exiger_hors_pause(pin)
        pas = archives_totp.verifier(dechiffrer_totp(totp["secret_chiffre"]), d.code, time.time(), totp.get("dernier_pas"))
        if not hmac.compare_digest(empreinte_preuve(d.preuve), pin["preuve_hash"]) or pas is None:
            await noter_echec(m, pin, "Code, phrase ou code de l'application incorrect")
        await db.membres_plateformes.update_one({"id": m["id"]}, {"$unset": {"archives_pin.totp": "", "archives_pin.totp_attente": ""}})
        return {"ok": True}

    @router.post("/formules-plateformes/archives/enveloppes")
    async def archives_enveloppes(request: Request):
        """Lot 277 — enregistre ou remplace l'enveloppe (nouvelle phrase choisie après usage du code de secours, ou mise à niveau d'une
        ancienne clé) et le secours. Les documents ne changent pas : seule la façon d'ouvrir leur clé change."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(ArchiveEnveloppesIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        existante = m.get("archives_cle") or {}
        if not existante or existante.get("verif") != d.verif_actuelle:
            raise HTTPException(status_code=409, detail="Jeton de contrôle incorrect")   # 409 : le 403 est réservé aux plateformes non autorisées
        maj = {"archives_cle.enveloppe": d.enveloppe}
        if d.secours:
            maj["archives_cle.secours"] = d.secours
        await db.membres_plateformes.update_one({"id": m["id"]}, {"$set": maj})
        return {"ok": True}

    @router.post("/formules-plateformes/archives/liste")
    async def archives_liste(request: Request):
        """Documents archivés : identifiant, informations chiffrées, taille, date. Le site les déchiffre pour chercher."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(CatalogueIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        docs = await db.archives_cloud.find({"plateforme": m["plateforme"], "membre_id": m["id"]}, {"_id": 0, "plateforme": 0, "membre_id": 0}).sort("cree_le", -1).to_list(3000)
        return {"archives": docs}

    @router.post("/formules-plateformes/archives/ajouter")
    async def archives_ajouter(request: Request):
        emetteur, corps = await plateforme_signee(request)
        d = lire(ArchiveAjoutIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        abonne = bool(d.utilisateur.acces_libre or acces_fonction(m, FONCTION_ARCHIVES))
        if not m.get("archives_cle"):
            raise HTTPException(status_code=409, detail="Choisissez d'abord la phrase secrète de vos archives")
        try:
            octets = base64.b64decode(d.contenu, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="Document illisible")
        if len(octets) > ARCHIVE_FICHIER_MAX:
            raise HTTPException(status_code=413, detail=f"Document trop volumineux : {ARCHIVE_FICHIER_MAX // 1_000_000} Mo au plus")
        utilise, nombre = await usage_archives(m)
        if abonne:
            quota = await reglage_archives_octets()
            if utilise + len(octets) > quota:
                raise HTTPException(status_code=413, detail=f"Espace d'archives plein ({quota // 1_000_000} Mo) : supprimez des documents ou demandez plus d'espace")
        else:
            # Lot 277 : sans abonnement, l'espace offert s'applique ; au-delà, refus 402 avec le prix de la formule
            gratuit_octets, gratuit_nombre = await reglage_archives_gratuit()
            if nombre >= gratuit_nombre or utilise + len(octets) > gratuit_octets:
                await exiger_abonnement(emetteur["code"], m, FONCTION_ARCHIVES, "Archives en ligne", False,
                                        refus=f"Espace gratuit atteint ({gratuit_octets // 1_000_000} Mo ou {gratuit_nombre} documents).")
        archive_id = str(uuid.uuid4())
        chemin = chemin_archive(m, archive_id)
        if _ecrire_archive:
            await _ecrire_archive(chemin, octets)
        else:
            import object_storage
            await object_storage.put_object(chemin, octets, "application/octet-stream")
        doc = {"id": archive_id, "plateforme": m["plateforme"], "membre_id": m["id"], "meta": d.meta, "taille": len(octets), "chemin": chemin, "cree_le": _iso(_maintenant())}
        await db.archives_cloud.insert_one(doc.copy())
        return {"id": archive_id, "taille": len(octets), "cree_le": doc["cree_le"], "utilise_octets": utilise + len(octets)}

    @router.post("/formules-plateformes/archives/telecharger")
    async def archives_telecharger(request: Request):
        emetteur, corps = await plateforme_signee(request)
        d = lire(ArchiveIdIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        a = await db.archives_cloud.find_one({"id": d.id, "plateforme": m["plateforme"], "membre_id": m["id"]}, {"_id": 0})
        if not a:
            raise HTTPException(status_code=404, detail="Document introuvable")
        if _lire_archive:
            octets = await _lire_archive(a["chemin"])
        else:
            import object_storage
            octets, _ = await object_storage.get_object(a["chemin"])
        return {"id": a["id"], "meta": a["meta"], "contenu": base64.b64encode(octets).decode("ascii")}

    @router.post("/formules-plateformes/archives/modifier")
    async def archives_modifier(request: Request):
        """Remplace les informations chiffrées d'un document (titre, catégorie, étiquettes…) ; le document lui-même ne change pas.
        Permis après la fin de l'abonnement (rangement de ses propres documents)."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(ArchiveModifierIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        r = await db.archives_cloud.update_one({"id": d.id, "plateforme": m["plateforme"], "membre_id": m["id"]}, {"$set": {"meta": d.meta}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Document introuvable")
        return {"ok": True}

    @router.post("/formules-plateformes/archives/supprimer")
    async def archives_supprimer(request: Request):
        emetteur, corps = await plateforme_signee(request)
        d = lire(ArchiveIdIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        a = await db.archives_cloud.find_one({"id": d.id, "plateforme": m["plateforme"], "membre_id": m["id"]}, {"_id": 0})
        if not a:
            raise HTTPException(status_code=404, detail="Document introuvable")
        try:
            if _effacer_archive:
                await _effacer_archive(a["chemin"])
            else:
                import storage
                await asyncio.to_thread(storage.delete_bytes, a["chemin"], False)
        except Exception as exc:  # noqa: BLE001 — l'inscription en base est retirée quand même (aucun document « fantôme » dans la liste)
            logger.warning("[archives] objet non supprimé (%s)", type(exc).__name__)
        await db.archives_cloud.delete_one({"id": a["id"]})
        return {"ok": True}

    @router.post("/formules-plateformes/ocr")
    async def ocr(request: Request):
        """Lecture OCR d'une photo (plaque de marchand, ordonnance), réservée aux abonnés d'une formule qui débloque l'OCR."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(OcrIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        # 1. Abonnement actif ? Sinon refus (402) avec le nom et le PRIX de la formule à prendre
        await exiger_abonnement(emetteur["code"], m, FONCTION_OCR, "Lecture OCR", d.utilisateur.acces_libre)
        # 2. Limite par jour et par utilisateur (protège le coût de l'IA)
        jour, limite = _maintenant().date().isoformat(), await reglage_ocr_par_jour()
        if int((m.get("ocr_jours") or {}).get(jour, 0)) >= limite:
            raise HTTPException(status_code=429, detail=f"Limite atteinte : {limite} lectures OCR par jour. Réessayez demain.")
        # 3. Image
        entete, _, b64 = d.image.partition(",")
        type_mime = entete[5:].split(";")[0] if entete.startswith("data:") else ""
        if type_mime not in ("image/jpeg", "image/png", "image/webp"):
            raise HTTPException(status_code=422, detail="Photo attendue (JPEG, PNG ou WebP)")
        try:
            octets = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="Photo illisible")
        if len(octets) > OCR_TAILLE_MAX:
            raise HTTPException(status_code=413, detail="Photo trop lourde (8 Mo au plus)")
        # 4. Lecture (le moteur ne lève jamais : erreur dans le résultat)
        import ocr_core
        analyser = _analyser or ocr_core.analyze_document
        consigne = CONSIGNE_PLAQUE if d.type == "plaque_marchand" else CONSIGNE_ORDONNANCE
        systeme = ocr_core.build_system_prompt(
            organisation="Paiement Mobile (application de paiements mobiles et de rappels du quotidien, Burkina Faso)",
            documents="photo d'une plaque de marchand ou d'une ordonnance médicale") + "\n\n" + consigne
        res = await analyser(octets, type_mime, "photo.jpg", None, system_prompt=systeme, default_model="claude-sonnet-5")
        if res.get("error") or not isinstance(res.get("extracted_fields"), dict) or not res["extracted_fields"]:
            raise HTTPException(status_code=502, detail="Lecture impossible : refaites la photo, bien nette et de face.")
        # Lecture réussie seulement : compte dans la limite du jour
        await db.membres_plateformes.update_one({"id": m["id"]}, {"$inc": {f"ocr_jours.{jour}": 1, "ocr_total": 1}})
        restant = max(0, limite - int((m.get("ocr_jours") or {}).get(jour, 0)) - 1)
        return {"type": d.type, "champs": res["extracted_fields"], "resume": res.get("summary", ""), "confiance": res.get("confidence"),
                "incertains": res.get("uncertain_fields") or [], "avertissements": res.get("flags") or [], "restant_aujourdhui": restant}

    @router.post("/formules-plateformes/transcrire")
    async def transcrire(request: Request):
        """Note vocale (30 s au plus) → texte, réservée aux abonnés d'une formule qui débloque la transcription."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(VoixIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        await exiger_abonnement(emetteur["code"], m, FONCTION_VOIX, "Transcription vocale", d.utilisateur.acces_libre)
        jour, limite = _maintenant().date().isoformat(), await reglage_voix_par_jour()
        if int((m.get("voix_jours") or {}).get(jour, 0)) >= limite:
            raise HTTPException(status_code=429, detail=f"Limite atteinte : {limite} notes vocales par jour. Réessayez demain.")
        entete, _, b64 = d.audio.partition(",")
        type_mime = entete[5:].split(";")[0] if entete.startswith("data:") else ""
        if not type_mime.startswith("audio/") and type_mime != "video/webm":
            raise HTTPException(status_code=422, detail="Note vocale attendue")
        try:
            octets = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="Note vocale illisible")
        if not octets:
            raise HTTPException(status_code=422, detail="Note vocale vide")
        if len(octets) > VOIX_TAILLE_MAX:
            raise HTTPException(status_code=413, detail="Note vocale trop longue : 30 secondes au plus.")
        ext = {"audio/webm": ".webm", "video/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-m4a": ".m4a"}.get(type_mime, ".webm")
        try:
            texte = await (_transcrire or _whisper)(octets, ext, "fr")
        except Exception:  # noqa: BLE001
            logger.exception("[formules] transcription impossible")
            raise HTTPException(status_code=502, detail="Transcription impossible pour le moment, réessayez.")
        texte = (texte or "").strip()
        if not texte:
            raise HTTPException(status_code=422, detail="Aucune parole reconnue : parlez plus près du micro et réessayez.")
        await db.membres_plateformes.update_one({"id": m["id"]}, {"$inc": {f"voix_jours.{jour}": 1, "voix_total": 1}})
        restant = max(0, limite - int((m.get("voix_jours") or {}).get(jour, 0)) - 1)
        return {"ok": True, "texte": texte[:4000], "duree_s": d.duree_s, "restant_aujourdhui": restant}

    @router.post("/formules-plateformes/parrainage")
    async def parrainage(request: Request):
        emetteur, corps = await plateforme_signee(request)
        d = lire(ParrainageIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        message = None
        code = d.code.strip().upper()
        if code:
            parrain = await db.membres_plateformes.find_one({"code_parrainage": code, "plateforme": emetteur["code"]}, {"_id": 0})
            if not parrain:
                raise HTTPException(status_code=404, detail="Code de parrainage inconnu")
            if parrain["id"] == m["id"]:
                raise HTTPException(status_code=422, detail="Vous ne pouvez pas utiliser votre propre code")
            if m.get("parrain_id"):
                raise HTTPException(status_code=409, detail="Un code de parrainage est déjà enregistré")
            if m.get("recompense_donnee") or any(True for _ in (m.get("abonnements") or {})):
                raise HTTPException(status_code=409, detail="Le code doit être saisi avant le premier abonnement")
            # Pas de parrainage croisé : le parrain ne peut pas être lui-même filleul de ce membre
            if parrain.get("parrain_id") == m["id"]:
                raise HTTPException(status_code=422, detail="Parrainage croisé impossible")
            await db.membres_plateformes.update_one({"id": m["id"]}, {"$set": {"parrain_id": parrain["id"]}})
            m["parrain_id"] = parrain["id"]
            message = "Code enregistré : vous recevrez des jours offerts à votre premier abonnement."
        filleuls = await db.membres_plateformes.count_documents({"parrain_id": m["id"]})
        payes = await db.membres_plateformes.count_documents({"parrain_id": m["id"], "recompense_donnee": True})
        return {"code": m["code_parrainage"], "a_un_parrain": bool(m.get("parrain_id")), "filleuls": filleuls, "filleuls_payants": payes,
                "jours_gagnes": m.get("jours_gagnes", 0), "parrainage_jours": await reglages_parrainage(), "message": message}

    # ------------------------------------------------------------------ administration (administrateur principal)
    async def plateformes_connues() -> List[dict]:
        return [{"code": e["code"], "nom": e.get("nom") or e["code"]} async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "code": 1, "nom": 1}).sort("code", 1)]

    @router.get("/admin/formules-plateformes")
    async def admin_liste(_: dict = Depends(get_super_admin)):
        formules = await db.formules_plateformes.find({}, {"_id": 0}).sort([("plateforme", 1), ("ordre", 1)]).to_list(200)
        maintenant, stats = _maintenant(), {}
        async for m in db.membres_plateformes.find({}, {"_id": 0, "abonnements": 1, "plateforme": 1}):
            for fid, a in (m.get("abonnements") or {}).items():
                s = stats.setdefault(fid, {"abonnes_actifs": 0})
                if jours_restants(a.get("expire_le"), maintenant) > 0:
                    s["abonnes_actifs"] += 1
        ventes: Dict[str, Dict[str, int]] = {}
        async for p in db.payments.find({"flow": "formule_plateforme", "status": "completed"}, {"_id": 0, "formule_id": 1, "amount": 1, "lignes": 1}):
            # Lot 244 : un paiement groupé compte une vente et son prix pour CHAQUE formule achetée
            for ligne in p.get("lignes") or [{"formule_id": p.get("formule_id"), "prix": p.get("amount")}]:
                v = ventes.setdefault(ligne["formule_id"], {"ventes": 0, "chiffre": 0})
                v["ventes"] += 1
                v["chiffre"] += int(ligne.get("prix") or 0)
        for f in formules:
            f.update(stats.get(f["id"], {"abonnes_actifs": 0}))
            f.update(ventes.get(f["id"], {"ventes": 0, "chiffre": 0}))
        return {"formules": formules, "plateformes": await plateformes_connues(), "fonctions": FONCTIONS,
                "membres": await db.membres_plateformes.count_documents({}), "parrainage_jours": await reglages_parrainage(),
                "ocr_par_jour": await reglage_ocr_par_jour(), "voix_par_jour": await reglage_voix_par_jour(),
                "cartes_par_jour": await reglage_cartes_par_jour(),
                "archives_mo": (await reglage_archives_octets()) // 1_000_000,
                "archives_gratuit_mo": (await reglage_archives_gratuit())[0] // 1_000_000,
                "archives_gratuit_nombre": (await reglage_archives_gratuit())[1],
                "pispi_demandes": await db.payments.count_documents({"flow": "formule_plateforme", "methode": "pispi", "status": {"$in": list(STATUTS_PISPI_OUVERTS)}}),
                "pawapay_actif": bool((await db.settings.find_one({"_id": "global"}, {"pawapay_enabled": 1}) or {}).get("pawapay_enabled"))}

    def verifier(f: FormuleIn) -> dict:
        inconnues = [x for x in f.fonctions if x not in FONCTIONS]
        if inconnues:
            raise HTTPException(status_code=422, detail=f"Fonction inconnue : {', '.join(inconnues)}")
        return f.model_dump()

    @router.post("/admin/formules-plateformes", status_code=201)
    async def admin_creer(f: FormuleIn, _: dict = Depends(get_super_admin)):
        if not await db.liluvine_emetteurs.find_one({"code": f.plateforme}, {"_id": 1}):
            raise HTTPException(status_code=422, detail="Plateforme inconnue (créez-la dans « Transmission WA universelle »)")
        doc = {"id": str(uuid.uuid4()), **verifier(f), "cree_le": _iso(_maintenant())}
        await db.formules_plateformes.insert_one(doc.copy())
        return doc

    @router.put("/admin/formules-plateformes/{formule_id}")
    async def admin_modifier(formule_id: str, f: FormuleIn, _: dict = Depends(get_super_admin)):
        r = await db.formules_plateformes.update_one({"id": formule_id}, {"$set": verifier(f)})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Formule introuvable")
        return await db.formules_plateformes.find_one({"id": formule_id}, {"_id": 0})

    @router.delete("/admin/formules-plateformes/{formule_id}")
    async def admin_supprimer(formule_id: str, _: dict = Depends(get_super_admin)):
        # Une formule déjà vendue n'est jamais supprimée (les abonnés en cours la gardent) : on la désactive
        if await db.payments.find_one({"flow": "formule_plateforme", "formule_id": formule_id}, {"_id": 1}):
            await db.formules_plateformes.update_one({"id": formule_id}, {"$set": {"actif": False}})
            return {"ok": True, "desactivee": True}
        r = await db.formules_plateformes.delete_one({"id": formule_id})
        if not r.deleted_count:
            raise HTTPException(status_code=404, detail="Formule introuvable")
        return {"ok": True, "desactivee": False}

    @router.put("/admin/formules-plateformes-reglages")
    async def admin_reglages(r: ReglagesIn, _: dict = Depends(get_super_admin)):
        maj = {"parrainage_jours": r.parrainage_jours}
        if r.ocr_par_jour is not None:
            maj["ocr_plateformes_par_jour"] = r.ocr_par_jour
        if r.voix_par_jour is not None:
            maj["transcription_plateformes_par_jour"] = r.voix_par_jour
        if r.archives_mo is not None:
            maj["archives_plateformes_mo"] = r.archives_mo
        if r.archives_gratuit_mo is not None:
            maj["archives_gratuit_mo"] = r.archives_gratuit_mo
        if r.archives_gratuit_nombre is not None:
            maj["archives_gratuit_nombre"] = r.archives_gratuit_nombre
        if r.cartes_par_jour is not None:
            maj["cartes_plateformes_par_jour"] = r.cartes_par_jour
        await db.settings.update_one({"_id": "global"}, {"$set": maj}, upsert=True)
        return {"ok": True, "parrainage_jours": r.parrainage_jours, "ocr_par_jour": await reglage_ocr_par_jour(),
                "voix_par_jour": await reglage_voix_par_jour(), "cartes_par_jour": await reglage_cartes_par_jour(),
                "archives_mo": (await reglage_archives_octets()) // 1_000_000,
                "archives_gratuit_mo": (await reglage_archives_gratuit())[0] // 1_000_000,
                "archives_gratuit_nombre": (await reglage_archives_gratuit())[1]}

    # Outils partagés avec le module des annonceurs (lot 235) : signature des plateformes, fiche membre, lecture des corps
    from types import SimpleNamespace
    router.outils = SimpleNamespace(plateforme_signee=plateforme_signee, membre=membre, lire=lire,
                                    acces_fonction=acces_fonction, exiger_abonnement=exiger_abonnement)
    return router
