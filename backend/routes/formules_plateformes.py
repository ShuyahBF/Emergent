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
        POST /api/formules-plateformes/acheter     {utilisateur, formule_id, retour?} → lien de la page de paiement PawaPay
        POST /api/formules-plateformes/achat       {utilisateur, deposit_id}      → état du paiement (active la formule si payé)
        POST /api/formules-plateformes/acces       {utilisateur, fonction}        → {actif, expire_le, jours_restants}
        POST /api/formules-plateformes/parrainage  {utilisateur, code?}           → mon code, filleuls, jours gagnés ; lie un parrain
  - Lot 228 — OCR réservé aux abonnés (plaques de marchands, ordonnances) :
        POST /api/formules-plateformes/ocr         {utilisateur, type, image (data URL)} → champs lus ; refusé (402) sans abonnement
                                                   actif, avec le NOM et le PRIX de la formule à prendre ; limite par jour (429)
  - Administration (administrateur principal) : rubrique des Paramètres « Formules des plateformes » :
        GET/POST /api/admin/formules-plateformes · PUT/DELETE …/{id} · PUT /api/admin/formules-plateformes-reglages (jours de parrainage)
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.formules_plateformes")

# Transport HTTP de remplacement (tests) : None en production
_transport: Optional[httpx.AsyncBaseTransport] = None
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
FONCTIONS = {"ocr_ordonnances": "OCR (ordonnances et plaques de marchands)"}
FONCTION_OCR = "ocr_ordonnances"          # une seule fonction débloque toutes les lectures OCR
OCR_PAR_JOUR_DEFAUT = 30                  # lectures par jour et par utilisateur (réglable par l'administrateur)
OCR_TYPES = ("plaque_marchand", "ordonnance")
OCR_TAILLE_MAX = 8_000_000                # octets de l'image décodée
DUREE_DEFAUT = 30
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


class CatalogueIn(BaseModel):
    utilisateur: Utilisateur


class AcheterIn(BaseModel):
    utilisateur: Utilisateur
    formule_id: str = Field(..., min_length=1, max_length=80)
    retour: str = Field("", max_length=400)   # page où PawaPay renvoie l'utilisateur après le paiement


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
        f = await db.formules_plateformes.find_one({"id": payment.get("formule_id")}, {"_id": 0})
        if not m or not f:
            logger.warning("[formules] paiement %s : membre ou formule introuvable", payment["deposit_id"])
            return
        await activer(m, f, int(f.get("duree_jours") or DUREE_DEFAUT), "achat")
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

    @router.post("/formules-plateformes/acheter")
    async def acheter(request: Request):
        emetteur, corps = await plateforme_signee(request)
        d = lire(AcheterIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        f = await db.formules_plateformes.find_one({"id": d.formule_id, "plateforme": emetteur["code"], "actif": True}, {"_id": 0})
        if not f:
            raise HTTPException(status_code=404, detail="Formule introuvable")
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
                                    "amountDetails": {"amount": str(int(f["prix"])), "currency": pawapay["devise"](country)}}
        if d.retour.startswith("https://"):
            # PawaPay n'ajoute rien à l'adresse de retour : on y joint le numéro du paiement pour que la plateforme vérifie l'achat
            corps_pp["returnUrl"] = f"{d.retour}{'&' if '?' in d.retour else '?'}depositId={deposit_id}"
        if len(msisdn) >= 8:
            corps_pp["phoneNumber"] = msisdn
        # On inscrit le paiement AVANT d'appeler PawaPay (jamais de depositId perdu)
        paiement = {"id": str(uuid.uuid4()), "deposit_id": deposit_id, "client_id": None, "user_id": None, "user_label": m.get("nom") or m["utilisateur_id"],
                    "amount": float(f["prix"]), "currency": "XOF", "country": country, "msisdn": msisdn or None,
                    "description": f"Abonnement {f['nom']} — {emetteur['code']}", "environment": env, "flow": "formule_plateforme",
                    "plateforme": emetteur["code"], "membre_id": m["id"], "formule_id": f["id"], "status": "initiated",
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
        return {"ok": True, "deposit_id": deposit_id, "redirect_url": url}

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
        statut = {"completed": "paye", "failed": "echec"}.get(p.get("status"), "attente")
        return {"statut": statut, "formule_id": p.get("formule_id")}

    @router.post("/formules-plateformes/acces")
    async def acces(request: Request):
        """La plateforme demande si l'utilisateur a droit à une fonction (ex. ocr_ordonnances)."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(AccesIn, corps)
        m = await db.membres_plateformes.find_one({"plateforme": emetteur["code"], "utilisateur_id": d.utilisateur.id}, {"_id": 0}) or {}
        maintenant, meilleur = _maintenant(), acces_fonction(m, d.fonction)
        return {"actif": meilleur is not None, "expire_le": meilleur, "jours_restants": jours_restants(meilleur, maintenant)}

    @router.post("/formules-plateformes/ocr")
    async def ocr(request: Request):
        """Lecture OCR d'une photo (plaque de marchand, ordonnance), réservée aux abonnés d'une formule qui débloque l'OCR."""
        emetteur, corps = await plateforme_signee(request)
        d = lire(OcrIn, corps)
        m = await membre(emetteur["code"], d.utilisateur)
        # 1. Abonnement actif ? Sinon refus (402) avec le nom et le PRIX de la formule à prendre
        if not acces_fonction(m, FONCTION_OCR):
            formules = await db.formules_plateformes.find({"plateforme": emetteur["code"], "actif": True, "fonctions": FONCTION_OCR}, {"_id": 0}).sort("prix", 1).to_list(20)
            if formules:
                f = formules[0]
                prix = f"{int(f['prix']):,}".replace(",", " ")
                message = f"Lecture OCR réservée aux abonnés. Formule « {f['nom']} » : {prix} FCFA pour {f.get('duree_jours') or DUREE_DEFAUT} jours."
                formule = {"id": f["id"], "nom": f["nom"], "prix": f["prix"], "duree_jours": f.get("duree_jours") or DUREE_DEFAUT}
            else:
                message, formule = "Lecture OCR réservée aux abonnés : aucune formule n'est proposée pour le moment.", None
            raise HTTPException(status_code=402, detail={"code": "abonnement_requis", "message": message, "formule": formule})
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
        async for p in db.payments.find({"flow": "formule_plateforme", "status": "completed"}, {"_id": 0, "formule_id": 1, "amount": 1}):
            v = ventes.setdefault(p.get("formule_id"), {"ventes": 0, "chiffre": 0})
            v["ventes"] += 1
            v["chiffre"] += int(p.get("amount") or 0)
        for f in formules:
            f.update(stats.get(f["id"], {"abonnes_actifs": 0}))
            f.update(ventes.get(f["id"], {"ventes": 0, "chiffre": 0}))
        return {"formules": formules, "plateformes": await plateformes_connues(), "fonctions": FONCTIONS,
                "membres": await db.membres_plateformes.count_documents({}), "parrainage_jours": await reglages_parrainage(),
                "ocr_par_jour": await reglage_ocr_par_jour(),
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
        await db.settings.update_one({"_id": "global"}, {"$set": maj}, upsert=True)
        return {"ok": True, "parrainage_jours": r.parrainage_jours, "ocr_par_jour": await reglage_ocr_par_jour()}

    return router
