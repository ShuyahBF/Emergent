"""Lot 47 — Parc informatique : équipements, interventions, rapports signés par le client.

Le prestataire (SAWALI) suit le parc informatique de chaque compte client (tenant) :

ÉQUIPEMENTS (collection `parc_equipements`), par compte client :
  - numéro d'inventaire automatique PARC-<CODE>-0001 (par client) ;
  - catégorie (liste par défaut + ajouts par client, comme les types de matériel de la
    maintenance), fabricant, modèle, n° de série, adresse IP (facultative, IPv4 ou IPv6),
    adresse MAC (facultative, normalisée AA:BB:CC:DD:EE:FF), nom d'hôte, système
    d'exploitation, utilisateur affecté, lieu (site / service / bureau), date d'achat, fin
    de garantie, fournisseur, état (en service, en panne, en réparation, en stock, réformé),
    notes, photos ;
  - n° de série et adresse MAC uniques par client (409 avec l'équipement qui les porte) ;
  - liste filtrée (recherche, catégorie, état, site) avec compteurs, export CSV (UTF-8 avec
    BOM, séparateur « ; ») et import CSV (mêmes colonnes, rapport des lignes rejetées).

INTERVENTIONS (collection `parc_interventions`) :
  - numéro INT-<CODE>-<AAAA>-0001 (par client et par année) ;
  - un ou plusieurs équipements (instantané de leurs identifiants au moment de
    l'enregistrement : le rapport signé ne change pas si la fiche de l'équipement change) ;
  - type, début / fin (saisis, ou « Démarrer » / « Terminer »), équipe = liste de personnes
    (noms libres, éventuellement liés à un compte de la plateforme), problème, actions,
    pièces remplacées, résultat, recommandations, état des équipements après intervention
    (reporté sur leur fiche), photos, responsable côté client (nom, fonction, téléphone,
    e-mail ; par défaut celui du client).

RAPPORT D'INTERVENTION — même parcours de preuve que la signature des PV de réunion
(routes/meetings.py : signature horodatée, nom du signataire, document verrouillé 423) :
  - lien public aléatoire non devinable (/rapport-parc/<jeton>), lecture seule, non indexé
    (en-tête X-Robots-Tag), signable pendant 30 jours ; le rapport signé reste consultable ;
  - envoi du lien par WhatsApp (message libre dans la fenêtre de 24 h, sinon modèle Meta :
    même logique que la fiche de maintenance) ou par e-mail (SMTP existant) ;
  - le responsable lit puis signe : nom, fonction, signature tracée, date/heure, adresse IP,
    navigateur et empreinte SHA-256 du contenu lu (refus si le rapport a changé entretemps) ;
  - après la signature l'intervention est VERROUILLÉE (modification, photos, suppression :
    423), comme un PV signé : tout complément se fait par une nouvelle intervention ;
  - l'auteur est prévenu par le rapport Liluvine de l'admin (WhatsApp, repli e-mail) ;
  - PDF du rapport (reportlab, comme le PDF des PV).

Fonction activable « Parc informatique » (clé `parc_informatique`), par l'Admin ou le
Superviseur (Outils+), contrôlée côté serveur. Admin / Superviseur : tous les comptes
clients ; un compte client (et ses utilisateurs suivis) : son parc et ses interventions.

  GET    /api/me/parc-clients                         comptes clients proposés
  GET    /api/me/parc-categories                      catégories (défaut + ajouts du client)
  POST   /api/me/parc-categories                      {libelle, compte_client_id?}
  DELETE /api/me/parc-categories/{id}
  GET    /api/me/parc-responsable                     responsable du client
  PUT    /api/me/parc-responsable                     {nom, fonction, telephone, email}
  GET    /api/me/parc-equipe                          personnes proposées pour l'équipe
  GET    /api/me/parc/equipements                     liste (q, categorie, etat, site, compte_client_id)
  GET    /api/me/parc/equipements/export.csv          export CSV (mêmes filtres)
  POST   /api/me/parc/equipements/import              import CSV (fichier, compte_client_id)
  POST   /api/me/parc/equipements                     nouvel équipement
  GET    /api/me/parc/equipements/{id}                fiche + historique des interventions
  PUT    /api/me/parc/equipements/{id}
  DELETE /api/me/parc/equipements/{id}                refusé s'il a des interventions
  POST   /api/me/parc/equipements/{id}/photos         photo (JPEG / PNG, 5 Mo)
  DELETE /api/me/parc/equipements/{id}/photos/{pid}
  GET    /api/me/parc/interventions                   liste (q, equipement_id, signe, compte_client_id)
  POST   /api/me/parc/interventions                   nouvelle intervention
  GET    /api/me/parc/interventions/{id}
  PUT    /api/me/parc/interventions/{id}              refusé (423) après signature
  DELETE /api/me/parc/interventions/{id}              refusé (423) après signature
  POST   /api/me/parc/interventions/{id}/demarrer     début = maintenant
  POST   /api/me/parc/interventions/{id}/terminer     fin = maintenant
  POST   /api/me/parc/interventions/{id}/photos
  DELETE /api/me/parc/interventions/{id}/photos/{pid}
  POST   /api/me/parc/interventions/{id}/rapport      lien public du rapport {renouveler?}
  POST   /api/me/parc/interventions/{id}/envoyer      envoi du lien (WhatsApp ou e-mail)
  GET    /api/me/parc/interventions/{id}/pdf          PDF du rapport
  GET    /api/public/parc-rapport/{jeton}             rapport public (lecture seule)
  POST   /api/public/parc-rapport/{jeton}/signer      signature du responsable
  GET    /api/public/parc-rapport/{jeton}/pdf         PDF du rapport (public)

Collections : parc_equipements, parc_interventions, parc_categories, parc_responsables,
compteurs (+ whatsapp_messages pour la trace des envois).
"""
from __future__ import annotations

import base64
import csv
import hashlib
import html
import io
import ipaddress
import json
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Union

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

CLE_FONCTION = "parc_informatique"
CATEGORIES_PAR_DEFAUT = ["PC portable", "PC de bureau", "Serveur", "Imprimante", "Onduleur", "Switch", "Routeur",
                         "Point d'accès", "Téléphone IP", "Écran", "Autre"]
ETATS = ("en_service", "en_panne", "en_reparation", "en_stock", "reforme")
LIBELLES_ETAT = {"en_service": "En service", "en_panne": "En panne", "en_reparation": "En réparation",
                 "en_stock": "En stock", "reforme": "Réformé"}
TYPES_INTERVENTION = ("preventive", "curative", "installation", "mise_a_jour", "audit", "autre")
LIBELLES_TYPE = {"preventive": "Maintenance préventive", "curative": "Maintenance curative",
                 "installation": "Installation", "mise_a_jour": "Mise à jour", "audit": "Audit", "autre": "Autre"}
LIBELLES_STATUT = {"planifiee": "Planifiée", "en_cours": "En cours", "terminee": "Terminée"}
PHOTOS_MAX = 12
PHOTO_MAX_OCTETS = 5 * 1024 * 1024
TYPES_PHOTO = {"image/jpeg": "jpg", "image/png": "png"}
DUREE_LIEN_JOURS = 30                      # lien de signature valable 30 jours
SIGNATURE_MAX_OCTETS = 300 * 1024          # image de la signature tracée (PNG)
IMPORT_MAX_OCTETS = 2 * 1024 * 1024
IMPORT_MAX_LIGNES = 2000
ROLES_COMPTES = ["client", "pharmacien", "medecin", "regulateur", "editeur_vidal", "moderateur", "moderator"]
# Coordonnées du prestataire imprimées en tête du rapport
PRESTATAIRE = {"nom": "SAWALI Smart Systems", "email": "contact@sawalismartsystems.com",
               "telephone": "+226 25 65 81 65"}
# Colonnes du CSV (export et import) : clé interne -> en-tête lisible. À l'import, les
# en-têtes sont reconnus sans tenir compte des accents ni de la casse ; « N° inventaire »
# est ignoré (numéro attribué automatiquement) et seule « Catégorie » est obligatoire.
COLONNES_CSV = [("numero_inventaire", "N° inventaire"), ("categorie", "Catégorie"), ("fabricant", "Fabricant"),
                ("modele", "Modèle"), ("numero_serie", "N° de série"), ("adresse_ip", "Adresse IP"),
                ("adresse_mac", "Adresse MAC"), ("nom_hote", "Nom d'hôte"),
                ("systeme_exploitation", "Système d'exploitation"), ("utilisateur_affecte", "Utilisateur affecté"),
                ("site", "Site"), ("service", "Service"), ("bureau", "Bureau"), ("date_achat", "Date d'achat"),
                ("fin_garantie", "Fin de garantie"), ("fournisseur", "Fournisseur"), ("etat", "État"),
                ("notes", "Notes")]
CHAMPS_TEXTE = ("fabricant", "modele", "numero_serie", "nom_hote", "systeme_exploitation", "utilisateur_affecte",
                "site", "service", "bureau", "fournisseur", "notes")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Validation : adresse IP, adresse MAC, dates
# ---------------------------------------------------------------------------
def normaliser_ip(valeur: Optional[str]) -> Optional[str]:
    """« 192.168.1.10 » ou « fe80::1 » -> forme canonique ; vide -> None ; invalide -> ValueError."""
    s = (valeur or "").strip()
    if not s:
        return None
    return str(ipaddress.ip_address(s))


def normaliser_mac(valeur: Optional[str]) -> Optional[str]:
    """« aa-bb-cc-dd-ee-ff », « aabb.ccdd.eeff » ou « AABBCCDDEEFF » -> « AA:BB:CC:DD:EE:FF »."""
    s = (valeur or "").strip()
    if not s:
        return None
    hexa = re.sub(r"[\s:.\-]", "", s)
    if not re.fullmatch(r"[0-9A-Fa-f]{12}", hexa):
        raise ValueError(s)
    return ":".join(hexa[i:i + 2] for i in range(0, 12, 2)).upper()


def cle_serie(valeur: Optional[str]) -> Optional[str]:
    """Clé de comparaison du n° de série (sans espaces, en majuscules)."""
    s = re.sub(r"\s+", "", valeur or "").upper()
    return s or None


def normaliser_date(valeur: Optional[str]) -> Optional[str]:
    """« 2026-01-31 » ou « 31/01/2026 » -> « 2026-01-31 » ; vide -> None ; invalide -> ValueError."""
    s = (valeur or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(s)


def normaliser_date_heure(valeur: Optional[str]) -> Optional[str]:
    """Date/heure saisie (« 2026-09-30T08:00 », sans fuseau = heure de Ouagadougou, UTC) -> ISO UTC."""
    s = (valeur or "").strip()
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def _sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def _cle_entete(s: str) -> str:
    """En-tête CSV comparable : sans accents, sans casse, lettres et chiffres seulement."""
    return re.sub(r"[^a-z0-9]", "", _sans_accents(s).lower())


def etat_depuis_texte(valeur: Optional[str]) -> Optional[str]:
    """« En panne », « en_panne », « EN PANNE » -> « en_panne » ; vide -> None ; inconnu -> ValueError."""
    s = _cle_entete(valeur or "")
    if not s:
        return None
    for cle, libelle in LIBELLES_ETAT.items():
        if s in (_cle_entete(cle), _cle_entete(libelle)):
            return cle
    raise ValueError(valeur)


def _date_heure_fr(iso: Optional[str]) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return "—"


def _date_fr(iso: Optional[str]) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return "—"


def duree_fr(minutes: Any) -> str:
    m = int(minutes or 0)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


# ---------------------------------------------------------------------------
# Modèles d'entrée
# ---------------------------------------------------------------------------
class EquipementIn(BaseModel):
    compte_client_id: Optional[str] = None          # Admin / Superviseur : compte client du parc
    categorie: str = Field(..., min_length=1, max_length=80)
    fabricant: Optional[str] = Field(None, max_length=120)
    modele: Optional[str] = Field(None, max_length=160)
    numero_serie: Optional[str] = Field(None, max_length=120)
    adresse_ip: Optional[str] = Field(None, max_length=64)
    adresse_mac: Optional[str] = Field(None, max_length=32)
    nom_hote: Optional[str] = Field(None, max_length=120)
    systeme_exploitation: Optional[str] = Field(None, max_length=120)
    utilisateur_affecte: Optional[str] = Field(None, max_length=160)
    site: Optional[str] = Field(None, max_length=120)
    service: Optional[str] = Field(None, max_length=120)
    bureau: Optional[str] = Field(None, max_length=120)
    date_achat: Optional[str] = None
    fin_garantie: Optional[str] = None
    fournisseur: Optional[str] = Field(None, max_length=160)
    etat: Literal["en_service", "en_panne", "en_reparation", "en_stock", "reforme"] = "en_service"
    notes: Optional[str] = Field(None, max_length=4000)


class MembreEquipe(BaseModel):
    nom: str = Field(..., min_length=1, max_length=120)
    user_id: Optional[str] = None                   # compte de la plateforme, facultatif


class Piece(BaseModel):
    designation: str = Field(..., min_length=1, max_length=200)
    quantite: int = Field(1, ge=1, le=10_000)
    reference: Optional[str] = Field(None, max_length=120)


class ResponsableIn(BaseModel):
    nom: Optional[str] = Field(None, max_length=160)
    fonction: Optional[str] = Field(None, max_length=120)
    telephone: Optional[str] = Field(None, max_length=40)
    email: Optional[str] = Field(None, max_length=200)
    compte_client_id: Optional[str] = None           # PUT /me/parc-responsable (Admin)


class InterventionIn(BaseModel):
    equipement_ids: List[str] = Field(..., min_length=1, max_length=50)
    type_intervention: Literal["preventive", "curative", "installation", "mise_a_jour", "audit", "autre"] = "curative"
    debut: Optional[str] = None
    fin: Optional[str] = None
    equipe: List[Union[MembreEquipe, str]] = Field(default_factory=list, max_length=30)
    probleme: Optional[str] = Field(None, max_length=4000)
    actions: Optional[str] = Field(None, max_length=6000)
    pieces: List[Piece] = Field(default_factory=list, max_length=40)
    resultat: Optional[str] = Field(None, max_length=4000)
    recommandations: Optional[str] = Field(None, max_length=4000)
    etat_apres: Optional[Literal["en_service", "en_panne", "en_reparation", "en_stock", "reforme"]] = None
    responsable: Optional[ResponsableIn] = None


class CategorieIn(BaseModel):
    libelle: str = Field(..., min_length=2, max_length=80)
    compte_client_id: Optional[str] = None


class RapportIn(BaseModel):
    renouveler: bool = False                         # nouveau lien (l'ancien ne marche plus)


class EnvoiRapportIn(BaseModel):
    """Envoi du lien du rapport : WhatsApp (libre dans les 24 h, sinon modèle Meta) ou e-mail."""
    canal: Literal["whatsapp", "email"] = "whatsapp"
    mode: Literal["auto", "text", "template"] = "auto"
    message: Optional[str] = Field(None, max_length=3000)
    telephone: Optional[str] = Field(None, max_length=40)      # sinon celui du responsable
    email: Optional[str] = Field(None, max_length=200)
    template_name: Optional[str] = None
    language_code: Optional[str] = "fr"
    variables: List[str] = Field(default_factory=list)
    header_text: Optional[str] = None
    button_specs: Optional[List[Dict[str, Any]]] = None


class SignatureIn(BaseModel):
    nom: str = Field(..., min_length=2, max_length=120)
    fonction: Optional[str] = Field(None, max_length=120)
    image: str = Field(..., min_length=30, max_length=int(SIGNATURE_MAX_OCTETS * 1.4))   # data:image/png;base64,…
    empreinte: str = Field(..., pattern=r"^[0-9a-f]{64}$")       # empreinte du contenu lu
    accepte: bool = False                                          # « J'ai lu le rapport »


# ---------------------------------------------------------------------------
# Rapport : contenu signé, empreinte, texte WhatsApp
# ---------------------------------------------------------------------------
def statut_intervention(iv: Dict[str, Any]) -> str:
    if iv.get("fin"):
        return "terminee"
    return "en_cours" if iv.get("debut") else "planifiee"


def contenu_signe(iv: Dict[str, Any]) -> Dict[str, Any]:
    """Contenu du rapport couvert par la signature : tout ce que le responsable lit (hors
    signature, lien et présentation). Même contenu -> même empreinte SHA-256."""
    return {
        "numero": iv.get("numero"), "client": iv.get("client_nom"), "type": iv.get("type_intervention"),
        "debut": iv.get("debut"), "fin": iv.get("fin"), "duree_minutes": iv.get("duree_minutes"),
        "equipe": [m.get("nom") for m in iv.get("equipe") or []],
        "equipements": [{k: e.get(k) for k in ("numero_inventaire", "categorie", "fabricant", "modele",
                                                "numero_serie", "adresse_mac", "adresse_ip", "nom_hote", "lieu")}
                        for e in iv.get("equipements") or []],
        "probleme": iv.get("probleme"), "actions": iv.get("actions"), "pieces": iv.get("pieces") or [],
        "resultat": iv.get("resultat"), "recommandations": iv.get("recommandations"),
        "etat_apres": iv.get("etat_apres"), "photos": [p.get("url") for p in iv.get("photos") or []],
        "responsable": {"nom": (iv.get("responsable") or {}).get("nom"),
                        "fonction": (iv.get("responsable") or {}).get("fonction")},
    }


def empreinte(iv: Dict[str, Any]) -> str:
    brut = json.dumps(contenu_signe(iv), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()


def texte_lien(iv: Dict[str, Any], lien: str) -> str:
    """Message WhatsApp (fenêtre de 24 h ouverte) ou corps de l'e-mail."""
    r = iv.get("responsable") or {}
    lignes = [f"📋 *Rapport d'intervention {iv.get('numero')}*",
              f"Client : {iv.get('client_nom') or '—'}",
              f"Date : {_date_fr(iv.get('debut') or iv.get('cree_le'))}",
              f"Type : {LIBELLES_TYPE.get(iv.get('type_intervention'), '—')}",
              f"Équipements : {', '.join(e.get('numero_inventaire') or '' for e in iv.get('equipements') or [])}"]
    if iv.get("equipe"):
        lignes.append(f"Équipe : {', '.join(m['nom'] for m in iv['equipe'])}")
    lignes += ["", (f"{r['nom']}, merci" if r.get("nom") else "Merci")
               + " de lire le rapport et de le signer électroniquement :", lien]
    return "\n".join(lignes)


def _lieu(e: Dict[str, Any]) -> str:
    return " / ".join(x for x in (e.get("site"), e.get("service"), e.get("bureau")) if x)


def instantane_equipement(e: Dict[str, Any]) -> Dict[str, Any]:
    """Identifiants de l'équipement recopiés dans l'intervention (le rapport reste fidèle)."""
    return {"id": e["id"], "numero_inventaire": e.get("numero_inventaire"), "categorie": e.get("categorie"),
            "fabricant": e.get("fabricant"), "modele": e.get("modele"), "numero_serie": e.get("numero_serie"),
            "adresse_mac": e.get("adresse_mac"), "adresse_ip": e.get("adresse_ip"), "nom_hote": e.get("nom_hote"),
            "lieu": _lieu(e) or None}


def attach_parc_routes(*, api, db, get_current_user, fonction_active=None,
                       slugify_code: Callable[[str], str] = lambda s: re.sub(r"[^A-Z0-9]", "", s.upper())[:4] or "CLI",
                       is_admin_like: Callable[[dict], bool] = lambda u: u.get("role") in ("admin", "superviseur"),
                       save_and_log=None, base_publique: Callable[[], str] = lambda: "",
                       wa_send_text=None, wa_send_template=None, build_components=None,
                       fenetres_ouvertes=None,                           # async ([chiffres]) -> set
                       envoyer_email=None,                               # async (a, sujet, html, texte) -> bool
                       notifier_admin: Optional[Callable[[str, str], Awaitable[Any]]] = None,
                       client_ip: Callable[[Request], str] = lambda r: r.client.host if r.client else "",
                       ) -> Dict[str, Any]:

    def _tenant(user: dict) -> str:
        return user.get("parent_client_id") or user.get("client_id") or user["id"]

    async def utilisateur(user: dict = Depends(get_current_user)) -> dict:
        if fonction_active is not None and not await fonction_active(user, CLE_FONCTION):
            raise HTTPException(status_code=403, detail="La fonction « Parc informatique » n'est pas activée pour votre "
                                                        "compte. Demandez son activation à votre administrateur SAWALI.")
        return user

    def _auteur(user: dict) -> str:
        return user.get("full_name") or user.get("email") or user["id"]

    def _perimetre(user: dict, compte_client_id: Optional[str] = None) -> Dict[str, Any]:
        """Admin / Superviseur : tous les clients (ou celui choisi) ; sinon le compte du client."""
        if is_admin_like(user):
            return {"tenant_id": compte_client_id} if compte_client_id else {}
        return {"tenant_id": _tenant(user)}

    async def _compte(tenant_id: str) -> Dict[str, Any]:
        return await db.users.find_one({"id": tenant_id}, {"_id": 0, "id": 1, "company": 1, "full_name": 1,
                                                           "email": 1, "client_code": 1, "whatsapp_number": 1,
                                                           "phone": 1, "logo_url": 1}) or {}

    def _nom_compte(c: Dict[str, Any]) -> str:
        return c.get("company") or c.get("full_name") or c.get("email") or ""

    async def _tenant_cible(user: dict, compte_client_id: Optional[str]) -> str:
        """Compte client propriétaire d'un enregistrement : celui choisi par l'Admin / le
        Superviseur, sinon le compte de l'utilisateur (un client ne peut pas en choisir un autre)."""
        if compte_client_id and compte_client_id != _tenant(user):
            if not is_admin_like(user):
                raise HTTPException(status_code=403, detail="Seuls l'Admin et le Superviseur choisissent un compte client")
            if not await db.users.find_one({"id": compte_client_id}, {"_id": 1}):
                raise HTTPException(status_code=400, detail="Compte client introuvable")
            return compte_client_id
        return _tenant(user)

    async def _code(tenant_id: str) -> str:
        c = await _compte(tenant_id)
        return c.get("client_code") or slugify_code(_nom_compte(c) or "CLI")

    async def _compteur(cle: str) -> int:
        c = await db.compteurs.find_one_and_update({"_id": cle}, {"$inc": {"n": 1}}, upsert=True,
                                                   return_document=True)
        return (c or {}).get("n") or 1

    async def _numero_inventaire(tenant_id: str) -> str:
        return f"PARC-{await _code(tenant_id)}-{await _compteur(f'parc:{tenant_id}'):04d}"

    async def _numero_intervention(tenant_id: str) -> str:
        annee = datetime.fromisoformat(_maintenant()).year
        return f"INT-{await _code(tenant_id)}-{annee}-{await _compteur(f'parc-int:{tenant_id}:{annee}'):04d}"

    # ---- Validation d'un équipement (formulaire et import CSV) --------------------------------
    def _champs_equipement(data: EquipementIn) -> Dict[str, Any]:
        d = data.model_dump(exclude={"compte_client_id"})
        for k in CHAMPS_TEXTE:
            d[k] = (d.get(k) or "").strip() or None
        d["categorie"] = d["categorie"].strip()
        try:
            d["adresse_ip"] = normaliser_ip(d.get("adresse_ip"))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Adresse IP invalide : « {data.adresse_ip} » (IPv4 ou IPv6 attendue)")
        try:
            d["adresse_mac"] = normaliser_mac(d.get("adresse_mac"))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Adresse MAC invalide : « {data.adresse_mac} » "
                                                        "(12 chiffres hexadécimaux, ex. AA:BB:CC:DD:EE:FF)")
        for k, libelle in (("date_achat", "Date d'achat"), ("fin_garantie", "Fin de garantie")):
            try:
                d[k] = normaliser_date(d.get(k))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"{libelle} invalide : « {d.get(k)} » (AAAA-MM-JJ ou JJ/MM/AAAA)")
        d["numero_serie_cle"] = cle_serie(d.get("numero_serie"))
        return d

    async def _verifier_unicite(tenant_id: str, d: Dict[str, Any], sauf: Optional[str] = None) -> None:
        """N° de série et adresse MAC uniques dans le parc d'un client (409 clair sinon)."""
        for champ, valeur, libelle in (("numero_serie_cle", d.get("numero_serie_cle"), "Le n° de série"),
                                       ("adresse_mac", d.get("adresse_mac"), "L'adresse MAC")):
            if not valeur:
                continue
            q: Dict[str, Any] = {"tenant_id": tenant_id, champ: valeur}
            if sauf:
                q["id"] = {"$ne": sauf}
            autre = await db.parc_equipements.find_one(q, {"_id": 0, "numero_inventaire": 1, "categorie": 1, "modele": 1})
            if autre:
                quoi = " ".join(x for x in (autre.get("categorie"), autre.get("modele")) if x)
                raise HTTPException(status_code=409, detail=f"{libelle} {d.get('numero_serie') if champ == 'numero_serie_cle' else valeur} "
                                                            f"est déjà utilisé(e) par {autre['numero_inventaire']}"
                                                            + (f" ({quoi})" if quoi else "") + " dans ce parc")

    async def _equipement(user: dict, eid: str) -> Dict[str, Any]:
        e = await db.parc_equipements.find_one({"id": eid, **_perimetre(user)}, {"_id": 0})
        if not e:
            raise HTTPException(status_code=404, detail="Équipement introuvable")
        return e

    async def _intervention(user: dict, iid: str) -> Dict[str, Any]:
        iv = await db.parc_interventions.find_one({"id": iid, **_perimetre(user)}, {"_id": 0})
        if not iv:
            raise HTTPException(status_code=404, detail="Intervention introuvable")
        return iv

    def _non_signee(iv: Dict[str, Any]) -> None:
        """Rapport signé = intervention verrouillée (comme un PV signé : 423)."""
        if iv.get("signature"):
            raise HTTPException(status_code=423, detail="Rapport signé par le client : l'intervention est verrouillée. "
                                                        "Créez une nouvelle intervention pour tout complément.")

    def _lien(iv: Dict[str, Any]) -> Optional[str]:
        jeton = (iv.get("rapport") or {}).get("jeton")
        return f"{base_publique().rstrip('/')}/rapport-parc/{jeton}" if jeton else None

    def _presenter(iv: Dict[str, Any]) -> Dict[str, Any]:
        """Champs calculés d'une intervention : statut, lien, état de la signature."""
        rapport = dict(iv.get("rapport") or {})
        if rapport:
            rapport["url"] = _lien(iv)
            rapport["expire"] = bool(rapport.get("expire_le") and rapport["expire_le"] < _maintenant())
        sig = iv.get("signature")
        return {**iv, "statut": statut_intervention(iv), "rapport": rapport or None, "signee": bool(sig),
                "signature": ({k: sig.get(k) for k in ("nom", "fonction", "signe_le", "ip", "empreinte")} if sig else None),
                "etat_signature": "signe" if sig else ("en_attente" if rapport else "sans_rapport")}

    # ---- Comptes clients, catégories, responsable, équipe --------------------------------------
    @api.get("/me/parc-clients", tags=["Parc informatique"])
    async def clients(user: dict = Depends(utilisateur)):
        if is_admin_like(user):
            comptes = await db.users.find(
                {"role": {"$in": ROLES_COMPTES},
                 "$or": [{"parent_client_id": {"$exists": False}}, {"parent_client_id": {"$in": [None, ""]}}]},
                {"_id": 0, "id": 1, "company": 1, "full_name": 1, "email": 1, "client_code": 1}).to_list(3000)
        else:
            comptes = [await _compte(_tenant(user))]
        items = [{"id": c["id"], "nom": _nom_compte(c), "code": c.get("client_code") or ""} for c in comptes if c.get("id")]
        items.sort(key=lambda x: (x["nom"] or "").lower())
        return {"admin": is_admin_like(user), "items": items, "compte_courant": _tenant(user)}

    @api.get("/me/parc-categories", tags=["Parc informatique"])
    async def categories(compte_client_id: Optional[str] = None, user: dict = Depends(utilisateur)):
        tenant_id = await _tenant_cible(user, compte_client_id)
        ajoutees = await db.parc_categories.find({"tenant_id": tenant_id}, {"_id": 0}).sort("libelle", 1).to_list(200)
        return {"defaut": CATEGORIES_PAR_DEFAUT, "ajoutees": ajoutees,
                "toutes": CATEGORIES_PAR_DEFAUT[:-1] + [c["libelle"] for c in ajoutees] + CATEGORIES_PAR_DEFAUT[-1:]}

    @api.post("/me/parc-categories", tags=["Parc informatique"])
    async def ajouter_categorie(data: CategorieIn, user: dict = Depends(utilisateur)):
        tenant_id = await _tenant_cible(user, data.compte_client_id)
        libelle = data.libelle.strip()
        existe = [c.lower() for c in CATEGORIES_PAR_DEFAUT] + [
            c["libelle"].lower() async for c in db.parc_categories.find({"tenant_id": tenant_id}, {"libelle": 1})]
        if libelle.lower() in existe:
            raise HTTPException(status_code=409, detail="Cette catégorie existe déjà")
        doc = {"id": secrets.token_hex(6), "tenant_id": tenant_id, "libelle": libelle, "cree_le": _maintenant()}
        await db.parc_categories.insert_one(dict(doc))
        return doc

    @api.delete("/me/parc-categories/{cid}", tags=["Parc informatique"])
    async def supprimer_categorie(cid: str, user: dict = Depends(utilisateur)):
        r = await db.parc_categories.delete_one({"id": cid, **_perimetre(user)})
        if not r.deleted_count:
            raise HTTPException(status_code=404, detail="Catégorie introuvable")
        return {"ok": True}

    async def _responsable_client(tenant_id: str) -> Dict[str, Any]:
        """Responsable du client ; à défaut, le numéro qui reçoit les alertes de la société."""
        r = await db.parc_responsables.find_one({"tenant_id": tenant_id}, {"_id": 0, "tenant_id": 0}) or {}
        if not r.get("telephone"):
            c = await _compte(tenant_id)
            r["telephone"] = c.get("whatsapp_number") or c.get("phone") or ""
        return {k: r.get(k) or "" for k in ("nom", "fonction", "telephone", "email")}

    @api.get("/me/parc-responsable", tags=["Parc informatique"])
    async def lire_responsable(compte_client_id: Optional[str] = None, user: dict = Depends(utilisateur)):
        return await _responsable_client(await _tenant_cible(user, compte_client_id))

    @api.put("/me/parc-responsable", tags=["Parc informatique"])
    async def modifier_responsable(data: ResponsableIn, user: dict = Depends(utilisateur)):
        tenant_id = await _tenant_cible(user, data.compte_client_id)
        doc = {k: (getattr(data, k) or "").strip() for k in ("nom", "fonction", "telephone", "email")}
        if doc["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", doc["email"]):
            raise HTTPException(status_code=400, detail="Adresse e-mail du responsable invalide")
        await db.parc_responsables.update_one({"tenant_id": tenant_id}, {"$set": {**doc, "maj_le": _maintenant()}},
                                              upsert=True)
        return await _responsable_client(tenant_id)

    @api.get("/me/parc-equipe", tags=["Parc informatique"])
    async def equipe_proposee(user: dict = Depends(utilisateur)):
        """Personnes proposées pour l'équipe : l'utilisateur et les comptes de son organisation."""
        t = _tenant(user)
        q: Dict[str, Any] = {"$or": [{"id": t}, {"client_id": t}, {"parent_client_id": t}]}
        if is_admin_like(user):
            q["$or"].append({"role": {"$in": ["admin", "superviseur"]}})
        comptes = await db.users.find(q, {"_id": 0, "id": 1, "full_name": 1, "email": 1}).to_list(500)
        items = [{"user_id": c["id"], "nom": c.get("full_name") or c.get("email") or ""} for c in comptes]
        return {"items": sorted([i for i in items if i["nom"]], key=lambda x: x["nom"].lower())}

    # ---- Équipements ------------------------------------------------------------------------------
    def _filtre_equipements(user: dict, q: Optional[str], categorie: Optional[str], etat: Optional[str],
                            site: Optional[str], compte_client_id: Optional[str]) -> Dict[str, Any]:
        filtre: Dict[str, Any] = dict(_perimetre(user, compte_client_id))
        if categorie:
            filtre["categorie"] = categorie
        if etat:
            filtre["etat"] = etat
        if site:
            filtre["site"] = site
        if q and q.strip():
            motif = {"$regex": re.escape(q.strip()), "$options": "i"}
            filtre["$or"] = [{k: motif} for k in ("numero_inventaire", "fabricant", "modele", "numero_serie",
                                                   "adresse_ip", "adresse_mac", "nom_hote", "utilisateur_affecte",
                                                   "site", "service", "bureau", "client_nom")]
        return filtre

    @api.get("/me/parc/equipements", tags=["Parc informatique"])
    async def lister_equipements(q: Optional[str] = None, categorie: Optional[str] = None, etat: Optional[str] = None,
                                 site: Optional[str] = None, compte_client_id: Optional[str] = None,
                                 user: dict = Depends(utilisateur)):
        base = _perimetre(user, compte_client_id)
        liste = await db.parc_equipements.find(_filtre_equipements(user, q, categorie, etat, site, compte_client_id),
                                               {"_id": 0}).sort("numero_inventaire", 1).to_list(5000)
        # Compteurs sur tout le parc du périmètre (pas seulement le résultat filtré)
        tous = await db.parc_equipements.find(base, {"_id": 0, "etat": 1, "categorie": 1, "site": 1}).to_list(20000)
        compte = {e: 0 for e in ETATS}
        categories_vues: Dict[str, int] = {}
        for e in tous:
            compte[e.get("etat") if e.get("etat") in ETATS else "en_service"] += 1
            categories_vues[e.get("categorie") or "Autre"] = categories_vues.get(e.get("categorie") or "Autre", 0) + 1
        sites = sorted({e["site"] for e in tous if e.get("site")}, key=str.lower)
        return {"equipements": liste, "total": len(tous), "compte": compte, "par_categorie": categories_vues,
                "sites": sites}

    @api.get("/me/parc/equipements/export.csv", tags=["Parc informatique"])
    async def exporter_csv(q: Optional[str] = None, categorie: Optional[str] = None, etat: Optional[str] = None,
                           site: Optional[str] = None, compte_client_id: Optional[str] = None,
                           user: dict = Depends(utilisateur)):
        liste = await db.parc_equipements.find(_filtre_equipements(user, q, categorie, etat, site, compte_client_id),
                                               {"_id": 0}).sort([("client_nom", 1), ("numero_inventaire", 1)]).to_list(20000)
        sortie = io.StringIO()
        w = csv.writer(sortie, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        admin = is_admin_like(user)
        w.writerow((["Client"] if admin else []) + [t for _, t in COLONNES_CSV] + ["Dernière intervention"])

        def cellule(v: Any) -> str:
            s = "" if v is None else str(v)
            # Protection contre l'injection de formules dans le tableur
            return "'" + s if s[:1] in ("=", "+", "@") else s

        for e in liste:
            valeurs = [LIBELLES_ETAT.get(e.get("etat"), "") if k == "etat" else e.get(k) for k, _ in COLONNES_CSV]
            der = e.get("derniere_intervention") or {}
            w.writerow(([cellule(e.get("client_nom"))] if admin else []) + [cellule(v) for v in valeurs]
                       + [f"{der.get('numero', '')} {_date_fr(der.get('date'))}".strip() if der else ""])
        contenu = "﻿" + sortie.getvalue()                        # BOM : accents lus par Excel
        nom = f"parc-informatique-{_maintenant()[:10]}.csv"
        return Response(content=contenu.encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{nom}"'})

    @api.post("/me/parc/equipements/import", tags=["Parc informatique"])
    async def importer_csv(fichier: UploadFile = File(...), compte_client_id: Optional[str] = Form(None),
                           user: dict = Depends(utilisateur)):
        """Import CSV (« ; » ou « , », UTF-8 ou Windows-1252). Chaque ligne passe par la même
        validation que le formulaire ; les lignes refusées sont listées avec leur motif."""
        tenant_id = await _tenant_cible(user, compte_client_id)
        brut = await fichier.read(IMPORT_MAX_OCTETS + 1)
        if len(brut) > IMPORT_MAX_OCTETS:
            raise HTTPException(status_code=400, detail="Fichier trop lourd : 2 Mo au maximum")
        try:
            texte = brut.decode("utf-8-sig")
        except UnicodeDecodeError:
            texte = brut.decode("cp1252", errors="replace")
        premiere = texte.split("\n", 1)[0]
        sep = ";" if premiere.count(";") >= premiere.count(",") else ","
        lecteur = csv.reader(io.StringIO(texte), delimiter=sep)
        entetes = next(lecteur, None)
        if not entetes:
            raise HTTPException(status_code=400, detail="Fichier vide")
        correspondance = {}
        for cle, titre in COLONNES_CSV:
            for i, h in enumerate(entetes):
                if _cle_entete(h) in (_cle_entete(cle), _cle_entete(titre)):
                    correspondance[cle] = i
        if "categorie" not in correspondance:
            raise HTTPException(status_code=400, detail="Colonne « Catégorie » introuvable dans la 1re ligne du fichier")
        compte = await _compte(tenant_id)
        importes, rejets = [], []
        for n, ligne in enumerate(lecteur, start=2):
            if n - 1 > IMPORT_MAX_LIGNES:
                rejets.append({"ligne": n, "motif": f"au-delà de {IMPORT_MAX_LIGNES} lignes : non lue"})
                break
            if not any((c or "").strip() for c in ligne):
                continue
            valeurs = {k: (ligne[i].strip() if i < len(ligne) else "") for k, i in correspondance.items()}
            if not valeurs.get("categorie"):
                rejets.append({"ligne": n, "motif": "Catégorie manquante"})
                continue
            try:
                etat = etat_depuis_texte(valeurs.get("etat")) or "en_service"
            except ValueError:
                rejets.append({"ligne": n, "motif": f"État inconnu : « {valeurs.get('etat')} »"})
                continue
            try:
                data = EquipementIn(**{k: v or None for k, v in valeurs.items() if k not in ("numero_inventaire", "etat")},
                                    etat=etat)
                d = _champs_equipement(data)
                await _verifier_unicite(tenant_id, d)
            except HTTPException as exc:
                rejets.append({"ligne": n, "motif": str(exc.detail)})
                continue
            except Exception as exc:  # noqa: BLE001 — erreur de validation (Pydantic) : motif lisible
                errs = getattr(exc, "errors", lambda: [])()
                motif = " ; ".join(f"{'.'.join(str(x) for x in e.get('loc', []))} : {e.get('msg')}" for e in errs) or str(exc)
                rejets.append({"ligne": n, "motif": motif[:300]})
                continue
            doc = {"id": secrets.token_hex(8), "tenant_id": tenant_id, "client_nom": _nom_compte(compte),
                   "numero_inventaire": await _numero_inventaire(tenant_id), **d, "photos": [],
                   "cree_par": _auteur(user), "cree_le": _maintenant(), "maj_le": _maintenant(), "source": "import"}
            await db.parc_equipements.insert_one(dict(doc))
            importes.append(doc["numero_inventaire"])
        return {"importes": len(importes), "numeros": importes, "rejets": rejets}

    @api.post("/me/parc/equipements", tags=["Parc informatique"])
    async def creer_equipement(data: EquipementIn, user: dict = Depends(utilisateur)):
        tenant_id = await _tenant_cible(user, data.compte_client_id)
        d = _champs_equipement(data)
        await _verifier_unicite(tenant_id, d)
        doc = {"id": secrets.token_hex(8), "tenant_id": tenant_id, "client_nom": _nom_compte(await _compte(tenant_id)),
               "numero_inventaire": await _numero_inventaire(tenant_id), **d, "photos": [],
               "cree_par": _auteur(user), "cree_le": _maintenant(), "maj_le": _maintenant()}
        await db.parc_equipements.insert_one(dict(doc))
        return doc

    @api.get("/me/parc/equipements/{eid}", tags=["Parc informatique"])
    async def lire_equipement(eid: str, user: dict = Depends(utilisateur)):
        e = await _equipement(user, eid)
        historique = await db.parc_interventions.find({"equipement_ids": eid, "tenant_id": e["tenant_id"]},
                                                      {"_id": 0}).to_list(1000)
        # Ordre chronologique inverse (début, sinon date de création)
        historique.sort(key=lambda i: i.get("debut") or i.get("cree_le") or "", reverse=True)
        return {**e, "interventions": [_presenter(i) for i in historique]}

    @api.put("/me/parc/equipements/{eid}", tags=["Parc informatique"])
    async def modifier_equipement(eid: str, data: EquipementIn, user: dict = Depends(utilisateur)):
        e = await _equipement(user, eid)
        d = _champs_equipement(data)
        await _verifier_unicite(e["tenant_id"], d, sauf=eid)
        await db.parc_equipements.update_one({"id": eid}, {"$set": {**d, "maj_le": _maintenant(),
                                                                    "maj_par": _auteur(user)}})
        return await lire_equipement(eid, user)

    @api.delete("/me/parc/equipements/{eid}", tags=["Parc informatique"])
    async def supprimer_equipement(eid: str, user: dict = Depends(utilisateur)):
        e = await _equipement(user, eid)
        if not (is_admin_like(user) or user["id"] == e["tenant_id"]):
            raise HTTPException(status_code=403, detail="Seul le compte client ou l'Admin peut supprimer un équipement")
        if await db.parc_interventions.find_one({"equipement_ids": eid}, {"_id": 1}):
            raise HTTPException(status_code=409, detail="Cet équipement a un historique d'interventions : "
                                                        "passez-le à l'état « Réformé » au lieu de le supprimer")
        await db.parc_equipements.delete_one({"id": eid})
        return {"ok": True}

    # ---- Photos (équipements et interventions) --------------------------------------------------
    async def _ajouter_photo(collection, doc: Dict[str, Any], fichier: UploadFile, user: dict) -> Dict[str, Any]:
        if save_and_log is None:
            raise HTTPException(status_code=503, detail="Stockage des photos indisponible")
        if len(doc.get("photos") or []) >= PHOTOS_MAX:
            raise HTTPException(status_code=400, detail=f"{PHOTOS_MAX} photos au maximum")
        ext = TYPES_PHOTO.get((fichier.content_type or "").lower())
        if not ext:
            raise HTTPException(status_code=400, detail="Photo JPEG ou PNG uniquement")
        data = await fichier.read(PHOTO_MAX_OCTETS + 1)
        if len(data) > PHOTO_MAX_OCTETS:
            raise HTTPException(status_code=400, detail="Photo trop lourde : 5 Mo au maximum")
        saved = await save_and_log(db, data=data, kind="parc", tenant_id=doc["tenant_id"], ext=ext,
                                   content_type=fichier.content_type, original_filename=fichier.filename,
                                   user_id=user.get("id"))
        url = saved["url"] if saved["url"].startswith("http") else base_publique().rstrip("/") + saved["url"]
        photo = {"id": secrets.token_hex(6), "url": url, "nom": (fichier.filename or f"photo.{ext}")[:120],
                 "ajoutee_le": _maintenant(), "par": _auteur(user)}
        await collection.update_one({"id": doc["id"]}, {"$push": {"photos": photo}, "$set": {"maj_le": _maintenant()}})
        return photo

    @api.post("/me/parc/equipements/{eid}/photos", tags=["Parc informatique"])
    async def photo_equipement(eid: str, fichier: UploadFile = File(...), user: dict = Depends(utilisateur)):
        return await _ajouter_photo(db.parc_equipements, await _equipement(user, eid), fichier, user)

    @api.delete("/me/parc/equipements/{eid}/photos/{pid}", tags=["Parc informatique"])
    async def supprimer_photo_equipement(eid: str, pid: str, user: dict = Depends(utilisateur)):
        await _equipement(user, eid)
        await db.parc_equipements.update_one({"id": eid}, {"$pull": {"photos": {"id": pid}}})
        return {"ok": True}

    # ---- Interventions ------------------------------------------------------------------------------
    async def _champs_intervention(user: dict, data: InterventionIn) -> Dict[str, Any]:
        """Validation : équipements du même client, dates cohérentes, équipe dédoublonnée."""
        ids = list(dict.fromkeys(data.equipement_ids))
        equipements = await db.parc_equipements.find({"id": {"$in": ids}, **_perimetre(user)}, {"_id": 0}).to_list(100)
        if len(equipements) != len(ids):
            raise HTTPException(status_code=404, detail="Équipement introuvable")
        tenants = {e["tenant_id"] for e in equipements}
        if len(tenants) > 1:
            raise HTTPException(status_code=400, detail="Les équipements d'une intervention appartiennent au même client")
        par_id = {e["id"]: e for e in equipements}
        try:
            debut, fin = normaliser_date_heure(data.debut), normaliser_date_heure(data.fin)
        except ValueError:
            raise HTTPException(status_code=400, detail="Date / heure invalide")
        if fin and not debut:
            raise HTTPException(status_code=400, detail="Indiquez le début de l'intervention")
        if debut and fin and fin < debut:
            raise HTTPException(status_code=400, detail="La fin précède le début de l'intervention")
        equipe, vus = [], set()
        for m in data.equipe:
            m = MembreEquipe(nom=m) if isinstance(m, str) else m
            nom = m.nom.strip()
            if nom and nom.lower() not in vus:
                vus.add(nom.lower())
                equipe.append({"nom": nom, "user_id": m.user_id or None})
        texte = {k: (getattr(data, k) or "").strip() or None for k in ("probleme", "actions", "resultat", "recommandations")}
        return {"tenant_id": tenants.pop(), "equipement_ids": ids,
                "equipements": [instantane_equipement(par_id[i]) for i in ids],
                "type_intervention": data.type_intervention, "debut": debut, "fin": fin,
                "duree_minutes": round((datetime.fromisoformat(fin) - datetime.fromisoformat(debut)).total_seconds() / 60)
                if debut and fin else None,
                "equipe": equipe, **texte,
                "pieces": [{"designation": p.designation.strip(), "quantite": p.quantite,
                            "reference": (p.reference or "").strip() or None} for p in data.pieces],
                "etat_apres": data.etat_apres}

    async def _reporter_etat(iv: Dict[str, Any]) -> None:
        """État des équipements après intervention reporté sur leur fiche, avec la dernière intervention."""
        maj: Dict[str, Any] = {"derniere_intervention": {"id": iv["id"], "numero": iv["numero"],
                                                         "date": iv.get("fin") or iv.get("debut") or iv.get("cree_le")},
                               "maj_le": _maintenant()}
        if iv.get("etat_apres"):
            maj["etat"] = iv["etat_apres"]
        await db.parc_equipements.update_many({"id": {"$in": iv["equipement_ids"]}, "tenant_id": iv["tenant_id"]},
                                              {"$set": maj})

    def _responsable(data: Optional[ResponsableIn], defaut: Dict[str, Any]) -> Dict[str, Any]:
        r = {k: ((getattr(data, k) if data else None) or "").strip() or (defaut.get(k) or "")
             for k in ("nom", "fonction", "telephone", "email")}
        if r["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", r["email"]):
            raise HTTPException(status_code=400, detail="Adresse e-mail du responsable invalide")
        return r

    @api.get("/me/parc/interventions", tags=["Parc informatique"])
    async def lister_interventions(q: Optional[str] = None, equipement_id: Optional[str] = None,
                                   signe: Optional[str] = None, compte_client_id: Optional[str] = None,
                                   user: dict = Depends(utilisateur)):
        filtre: Dict[str, Any] = dict(_perimetre(user, compte_client_id))
        if equipement_id:
            filtre["equipement_ids"] = equipement_id
        if q and q.strip():
            motif = {"$regex": re.escape(q.strip()), "$options": "i"}
            filtre["$or"] = [{"numero": motif}, {"client_nom": motif}, {"probleme": motif}, {"actions": motif},
                             {"equipe.nom": motif}, {"equipements.numero_inventaire": motif},
                             {"equipements.numero_serie": motif}]
        liste = [_presenter(i) for i in await db.parc_interventions.find(filtre, {"_id": 0}).to_list(3000)]
        liste.sort(key=lambda i: i.get("debut") or i.get("cree_le") or "", reverse=True)
        compte = {"signe": 0, "en_attente": 0, "sans_rapport": 0}
        for i in liste:
            compte[i["etat_signature"]] += 1
        if signe in compte:
            liste = [i for i in liste if i["etat_signature"] == signe]
        return {"interventions": liste, "compte": compte}

    @api.post("/me/parc/interventions", tags=["Parc informatique"])
    async def creer_intervention(data: InterventionIn, user: dict = Depends(utilisateur)):
        champs = await _champs_intervention(user, data)
        tenant_id = champs["tenant_id"]
        doc = {"id": secrets.token_hex(8), "numero": await _numero_intervention(tenant_id),
               "client_nom": _nom_compte(await _compte(tenant_id)), **champs,
               "responsable": _responsable(data.responsable, await _responsable_client(tenant_id)),
               "photos": [], "rapport": None, "signature": None, "envois": [],
               "auteur": {"id": user["id"], "nom": _auteur(user)}, "cree_le": _maintenant(), "maj_le": _maintenant()}
        await db.parc_interventions.insert_one(dict(doc))
        await _reporter_etat(doc)
        return _presenter(doc)

    @api.get("/me/parc/interventions/{iid}", tags=["Parc informatique"])
    async def lire_intervention(iid: str, user: dict = Depends(utilisateur)):
        return _presenter(await _intervention(user, iid))

    @api.put("/me/parc/interventions/{iid}", tags=["Parc informatique"])
    async def modifier_intervention(iid: str, data: InterventionIn, user: dict = Depends(utilisateur)):
        iv = await _intervention(user, iid)
        _non_signee(iv)
        champs = await _champs_intervention(user, data)
        if champs["tenant_id"] != iv["tenant_id"]:
            raise HTTPException(status_code=400, detail="Les équipements doivent rester ceux du même client")
        maj = {**champs, "responsable": _responsable(data.responsable, iv.get("responsable") or {}),
               "maj_le": _maintenant(), "maj_par": _auteur(user)}
        # Filtre « non signé » : une signature arrivée entretemps n'est jamais écrasée
        r = await db.parc_interventions.update_one({"id": iid, "signature": None}, {"$set": maj})
        if not r.modified_count and not r.matched_count:
            _non_signee({"signature": True})
        iv.update(maj)
        await _reporter_etat(iv)
        return _presenter(iv)

    @api.delete("/me/parc/interventions/{iid}", tags=["Parc informatique"])
    async def supprimer_intervention(iid: str, user: dict = Depends(utilisateur)):
        iv = await _intervention(user, iid)
        _non_signee(iv)
        await db.parc_interventions.delete_one({"id": iid, "signature": None})
        return {"ok": True}

    @api.post("/me/parc/interventions/{iid}/demarrer", tags=["Parc informatique"])
    async def demarrer(iid: str, user: dict = Depends(utilisateur)):
        iv = await _intervention(user, iid)
        _non_signee(iv)
        if iv.get("debut"):
            raise HTTPException(status_code=409, detail="Intervention déjà démarrée")
        await db.parc_interventions.update_one({"id": iid}, {"$set": {"debut": _maintenant(), "maj_le": _maintenant()}})
        return await lire_intervention(iid, user)

    @api.post("/me/parc/interventions/{iid}/terminer", tags=["Parc informatique"])
    async def terminer(iid: str, user: dict = Depends(utilisateur)):
        iv = await _intervention(user, iid)
        _non_signee(iv)
        if not iv.get("debut"):
            raise HTTPException(status_code=409, detail="Démarrez l'intervention d'abord")
        if iv.get("fin"):
            raise HTTPException(status_code=409, detail="Intervention déjà terminée")
        fin = _maintenant()
        duree = max(0, round((datetime.fromisoformat(fin) - datetime.fromisoformat(iv["debut"])).total_seconds() / 60))
        await db.parc_interventions.update_one({"id": iid}, {"$set": {"fin": fin, "duree_minutes": duree, "maj_le": fin}})
        iv.update(fin=fin, duree_minutes=duree)
        await _reporter_etat(iv)
        return await lire_intervention(iid, user)

    @api.post("/me/parc/interventions/{iid}/photos", tags=["Parc informatique"])
    async def photo_intervention(iid: str, fichier: UploadFile = File(...), user: dict = Depends(utilisateur)):
        iv = await _intervention(user, iid)
        _non_signee(iv)
        return await _ajouter_photo(db.parc_interventions, iv, fichier, user)

    @api.delete("/me/parc/interventions/{iid}/photos/{pid}", tags=["Parc informatique"])
    async def supprimer_photo_intervention(iid: str, pid: str, user: dict = Depends(utilisateur)):
        _non_signee(await _intervention(user, iid))
        await db.parc_interventions.update_one({"id": iid, "signature": None}, {"$pull": {"photos": {"id": pid}}})
        return {"ok": True}

    # ---- Rapport : lien public, envoi ------------------------------------------------------------
    async def _assurer_lien(iv: Dict[str, Any], renouveler: bool = False) -> Dict[str, Any]:
        """Lien aléatoire (256 bits) valable 30 jours pour la signature ; un rapport signé
        garde son lien (consultation) et n'en reçoit pas de nouveau."""
        rapport = iv.get("rapport") or {}
        valide = rapport.get("jeton") and (iv.get("signature") or rapport.get("expire_le", "") > _maintenant())
        if valide and not (renouveler and not iv.get("signature")):
            return rapport
        maintenant = datetime.fromisoformat(_maintenant())
        rapport = {"jeton": secrets.token_urlsafe(32), "cree_le": maintenant.isoformat(),
                   "expire_le": (maintenant + timedelta(days=DUREE_LIEN_JOURS)).isoformat()}
        await db.parc_interventions.update_one({"id": iv["id"], "signature": None}, {"$set": {"rapport": rapport}})
        iv["rapport"] = rapport
        return rapport

    @api.post("/me/parc/interventions/{iid}/rapport", tags=["Parc informatique"])
    async def generer_rapport(iid: str, data: RapportIn, user: dict = Depends(utilisateur)):
        iv = await _intervention(user, iid)
        await _assurer_lien(iv, data.renouveler)
        return _presenter(iv)

    @api.post("/me/parc/interventions/{iid}/envoyer", tags=["Parc informatique"])
    async def envoyer_rapport(iid: str, data: EnvoiRapportIn, user: dict = Depends(utilisateur)):
        iv = await _intervention(user, iid)
        await _assurer_lien(iv)
        lien = _lien(iv)
        responsable = iv.get("responsable") or {}
        trace: Dict[str, Any] = {"le": _maintenant(), "par": _auteur(user), "canal": data.canal}
        if data.canal == "email":
            adresse = (data.email or responsable.get("email") or "").strip()
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", adresse):
                raise HTTPException(status_code=400, detail="Adresse e-mail du responsable manquante ou invalide")
            if envoyer_email is None:
                raise HTTPException(status_code=503, detail="Envoi d'e-mails indisponible")
            texte = (data.message or "").strip() or texte_lien(iv, lien).replace("*", "")
            corps = (f"<div style=\"font-family:Arial,sans-serif;font-size:14px;white-space:pre-wrap\">{html.escape(texte)}</div>"
                     f"<p><a href=\"{html.escape(lien)}\" style=\"display:inline-block;background:#4f46e5;color:#fff;"
                     f"padding:10px 16px;border-radius:6px;text-decoration:none\">Lire et signer le rapport</a></p>")
            ok = bool(await envoyer_email(adresse, f"Rapport d'intervention {iv['numero']} — à signer", corps, texte))
            if not ok:
                raise HTTPException(status_code=502, detail="L'e-mail n'a pas pu être envoyé (SMTP)")
            trace.update(a=adresse, mode="email")
            await db.parc_interventions.update_one({"id": iid}, {"$push": {"envois": {"$each": [trace], "$slice": -30}}})
            return {"canal": "email", "a": adresse, "lien": lien}
        # WhatsApp : même logique que la fiche de maintenance (fenêtre de 24 h, sinon modèle Meta)
        if wa_send_text is None:
            raise HTTPException(status_code=503, detail="WhatsApp indisponible")
        tel = (data.telephone or responsable.get("telephone") or "").strip()
        chiffres = "".join(ch for ch in tel if ch.isdigit())
        if len(chiffres) < 8:
            raise HTTPException(status_code=400, detail="Numéro WhatsApp du responsable manquant")
        ouverte = chiffres in (await fenetres_ouvertes([chiffres]) if fenetres_ouvertes else set())
        mode = data.mode if data.mode != "auto" else ("text" if ouverte else "template")
        if mode == "text":
            if not ouverte:
                raise HTTPException(status_code=400, detail=(
                    "Fenêtre de 24 h fermée : ce responsable ne vous a pas écrit récemment. Choisissez un modèle Meta."))
            corps = (data.message or "").strip()
            corps = f"{corps}\n\n{lien}" if corps and lien not in corps else (corps or texte_lien(iv, lien))
            r = await wa_send_text(tel, corps)
        else:
            if not data.template_name or wa_send_template is None or build_components is None:
                raise HTTPException(status_code=400, detail=(
                    "Fenêtre de 24 h fermée : choisissez un modèle Meta approuvé (ex. sawali_rapport_intervention)"))
            ctx = {"numero": iv["numero"], "client": iv.get("client_nom") or "", "full_name": responsable.get("nom") or "",
                   "responsable": responsable.get("nom") or "", "date": _date_fr(iv.get("debut") or iv.get("cree_le")),
                   "lien": lien, "type": LIBELLES_TYPE.get(iv.get("type_intervention"), ""),
                   "equipements": ", ".join(e.get("numero_inventaire") or "" for e in iv.get("equipements") or []),
                   "equipe": ", ".join(m["nom"] for m in iv.get("equipe") or []), "jeton": iv["rapport"]["jeton"]}
            comps = build_components(data.variables or [], ctx, header_text=data.header_text,
                                     header_media=None, button_specs=data.button_specs)
            r = await wa_send_template(tel, data.template_name, data.language_code or "fr", comps)
        if not r.get("ok"):
            raise HTTPException(status_code=502, detail=f"Envoi refusé par WhatsApp : {r.get('error')}")
        trace.update(a=tel, mode=mode, modele=data.template_name if mode == "template" else None)
        await db.parc_interventions.update_one({"id": iid}, {"$push": {"envois": {"$each": [trace], "$slice": -30}}})
        try:
            await db.whatsapp_messages.insert_one({
                "id": secrets.token_hex(12), "client_id": iv["tenant_id"], "direction": "outbound",
                "sender_id": user["id"], "sender_label": _auteur(user), "to": tel, "phone_digits": chiffres,
                "message_type": "text" if mode == "text" else "template",
                "template_name": data.template_name if mode == "template" else None,
                "body": texte_lien(iv, lien) if mode == "text" else f"[Rapport d'intervention] {iv['numero']}",
                "parc_intervention_id": iid, "ok": True, "wa_status": "sent", "sent_at": _maintenant(),
                "created_at": _maintenant()})
        except Exception:  # noqa: BLE001 — la trace ne bloque pas l'envoi
            pass
        return {"canal": "whatsapp", "mode": mode, "fenetre_ouverte": ouverte, "a": tel, "lien": lien}

    # ---- Rapport public (lecture, signature, PDF) --------------------------------------------------
    async def _par_jeton(jeton: str) -> Dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_\-]{20,100}", jeton or ""):
            raise HTTPException(status_code=404, detail="Lien de rapport inconnu")
        iv = await db.parc_interventions.find_one({"rapport.jeton": jeton}, {"_id": 0})
        if not iv:
            raise HTTPException(status_code=404, detail="Lien de rapport inconnu")
        return iv

    async def _vue_publique(iv: Dict[str, Any]) -> Dict[str, Any]:
        """Rapport tel que le responsable le lit (aucun identifiant interne ni coordonnée privée)."""
        client = await _compte(iv["tenant_id"])
        auteur = await db.users.find_one({"id": (iv.get("auteur") or {}).get("id")},
                                         {"_id": 0, "client_id": 1, "parent_client_id": 1, "logo_url": 1}) or {}
        prestataire_logo = auteur.get("logo_url")
        if not prestataire_logo and (auteur.get("parent_client_id") or auteur.get("client_id")):
            prestataire_logo = (await _compte(auteur.get("parent_client_id") or auteur.get("client_id"))).get("logo_url")
        sig = iv.get("signature")
        expire = (iv.get("rapport") or {}).get("expire_le", "") <= _maintenant()
        return {
            **contenu_signe(iv),
            "type_libelle": LIBELLES_TYPE.get(iv.get("type_intervention"), ""),
            "statut": LIBELLES_STATUT[statut_intervention(iv)],
            "etat_apres_libelle": LIBELLES_ETAT.get(iv.get("etat_apres"), ""),
            "photos": [{"url": p["url"], "nom": p.get("nom")} for p in iv.get("photos") or []],
            "auteur": (iv.get("auteur") or {}).get("nom"), "cree_le": iv.get("cree_le"),
            "prestataire": {**PRESTATAIRE, "logo_url": prestataire_logo},
            "client_logo_url": client.get("logo_url"),
            "empreinte_sha256": empreinte(iv),
            "signature": ({k: sig.get(k) for k in ("nom", "fonction", "image", "signe_le", "ip", "navigateur", "empreinte")}
                          if sig else None),
            "expire_le": (iv.get("rapport") or {}).get("expire_le"),
            "signable": not sig and not expire,
            "expire": bool(not sig and expire),
        }

    ENTETES_PUBLICS = {"X-Robots-Tag": "noindex, nofollow, noarchive", "Cache-Control": "no-store",
                       "Referrer-Policy": "no-referrer"}

    @api.get("/public/parc-rapport/{jeton}", tags=["Public"])
    async def rapport_public(jeton: str, response: Response):
        vue = await _vue_publique(await _par_jeton(jeton))
        response.headers.update(ENTETES_PUBLICS)
        return vue

    @api.post("/public/parc-rapport/{jeton}/signer", tags=["Public"])
    async def signer_rapport(jeton: str, data: SignatureIn, request: Request, response: Response):
        iv = await _par_jeton(jeton)
        response.headers.update(ENTETES_PUBLICS)
        if iv.get("signature"):
            raise HTTPException(status_code=409, detail="Ce rapport est déjà signé")
        if (iv.get("rapport") or {}).get("expire_le", "") <= _maintenant():
            raise HTTPException(status_code=410, detail="Lien expiré : demandez un nouveau lien à votre prestataire")
        if not data.accepte:
            raise HTTPException(status_code=400, detail="Cochez « J'ai lu le rapport » avant de signer")
        # Le responsable signe exactement ce qu'il a lu : empreinte identique au contenu actuel
        actuelle = empreinte(iv)
        if data.empreinte != actuelle:
            raise HTTPException(status_code=409, detail="Le rapport a été modifié depuis votre lecture : "
                                                        "rechargez la page, relisez-le puis signez")
        prefixe = "data:image/png;base64,"
        if not data.image.startswith(prefixe):
            raise HTTPException(status_code=400, detail="Signature manquante : tracez votre signature")
        try:
            png = base64.b64decode(data.image[len(prefixe):], validate=True)
        except ValueError:
            raise HTTPException(status_code=400, detail="Signature illisible")
        if not png.startswith(b"\x89PNG") or len(png) > SIGNATURE_MAX_OCTETS:
            raise HTTPException(status_code=400, detail="Signature illisible ou trop lourde")
        signature = {"nom": data.nom.strip(), "fonction": (data.fonction or "").strip() or None, "image": data.image,
                     "signe_le": _maintenant(), "ip": client_ip(request) or "",
                     "navigateur": (request.headers.get("user-agent") or "")[:300], "empreinte": actuelle,
                     "image_sha256": hashlib.sha256(png).hexdigest(), "jeton": jeton}
        # Filtre « non signé » : deux signatures simultanées -> une seule gagne
        r = await db.parc_interventions.update_one({"id": iv["id"], "signature": None},
                                                   {"$set": {"signature": signature, "maj_le": _maintenant()}})
        if not r.modified_count:
            raise HTTPException(status_code=409, detail="Ce rapport est déjà signé")
        iv["signature"] = signature
        # Notification de l'auteur (rapport Liluvine de l'admin) — n'empêche jamais la signature
        if notifier_admin is not None:
            texte = (f"🤖 Liluvine — Rapport d'intervention signé\n{iv['numero']} · {iv.get('client_nom') or ''}\n"
                     f"Signé par {signature['nom']}" + (f" ({signature['fonction']})" if signature["fonction"] else "")
                     + f" le {_date_heure_fr(signature['signe_le'])}\nAuteur : {(iv.get('auteur') or {}).get('nom') or '—'}")
            try:
                resultat = await notifier_admin(f"Rapport {iv['numero']} signé", texte)
                await db.parc_interventions.update_one({"id": iv["id"]}, {"$set": {
                    "signature_notifiee": {"le": _maintenant(), "ok": bool((resultat or {}).get("envoye", True))}}})
            except Exception:  # noqa: BLE001
                pass
        return await _vue_publique(iv)

    @api.get("/public/parc-rapport/{jeton}/pdf", tags=["Public"])
    async def pdf_public(jeton: str):
        vue = await _vue_publique(await _par_jeton(jeton))
        return Response(content=rendre_pdf(vue), media_type="application/pdf",
                        headers={**ENTETES_PUBLICS, "Content-Disposition": f'inline; filename="{vue["numero"]}.pdf"'})

    @api.get("/me/parc/interventions/{iid}/pdf", tags=["Parc informatique"])
    async def pdf_intervention(iid: str, user: dict = Depends(utilisateur)):
        vue = await _vue_publique(await _intervention(user, iid))
        return Response(content=rendre_pdf(vue), media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{vue["numero"]}.pdf"'})

    return {"empreinte": empreinte}


def rendre_pdf(r: Dict[str, Any]) -> bytes:
    """PDF du rapport, même mise en page que le PDF des PV (routes/meetings.py : reportlab,
    tableau d'informations, bloc vert de signature électronique)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    def p(texte: Any, style) -> Paragraph:
        return Paragraph(html.escape(str(texte or "—")).replace("\n", "<br/>"), style)

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.5 * cm,
                            bottomMargin=1.5 * cm, title=r.get("numero") or "Rapport")
    styles = getSampleStyleSheet()
    titre = ParagraphStyle("ti", parent=styles["Title"], fontSize=17, textColor=colors.HexColor("#1E3A8A"))
    meta = ParagraphStyle("mt", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#475569"))
    corps = ParagraphStyle("bd", parent=styles["BodyText"], fontSize=10, leading=13)
    h = ParagraphStyle("h", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor("#1E40AF"))
    style_tableau = TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F5F9")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1E3A8A")),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E2E8F0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)])
    pr = r.get("prestataire") or PRESTATAIRE
    story = [Paragraph(f"<b>{html.escape(pr['nom'])}</b> · {html.escape(pr['email'])} · {html.escape(pr['telephone'])}", meta),
             Spacer(1, 6), Paragraph("Rapport d'intervention", titre),
             Paragraph(f"<b>{html.escape(r.get('numero') or '')}</b> — {html.escape(r.get('client') or '')}", meta),
             Spacer(1, 10)]
    lignes = [["Client", p(r.get("client"), corps)], ["Type", p(r.get("type_libelle"), corps)],
              ["Début", p(_date_heure_fr(r.get("debut")), corps)], ["Fin", p(_date_heure_fr(r.get("fin")), corps)]]
    if r.get("duree_minutes") is not None:
        lignes.append(["Durée", p(duree_fr(r["duree_minutes"]), corps)])
    lignes += [["Équipe", p(", ".join(r.get("equipe") or []) or "—", corps)],
               ["Responsable", p(" — ".join(x for x in ((r.get("responsable") or {}).get("nom"),
                                                       (r.get("responsable") or {}).get("fonction")) if x) or "—", corps)]]
    t = Table(lignes, colWidths=[3.5 * cm, 13.5 * cm])
    t.setStyle(style_tableau)
    story += [t, Spacer(1, 10), Paragraph("Équipements concernés", h)]
    eq = [["Inventaire", "Équipement", "N° de série", "MAC", "IP"]] + [
        [p(e.get("numero_inventaire"), corps),
         p(" ".join(x for x in (e.get("categorie"), e.get("fabricant"), e.get("modele")) if x)
           + (f"\n{e['lieu']}" if e.get("lieu") else ""), corps),
         p(e.get("numero_serie"), corps), p(e.get("adresse_mac"), corps), p(e.get("adresse_ip"), corps)]
        for e in r.get("equipements") or []]
    te = Table(eq, colWidths=[3 * cm, 5 * cm, 3 * cm, 3.3 * cm, 2.7 * cm], repeatRows=1)
    te.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
                            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E2E8F0"))]))
    story.append(te)
    for libelle, cle in (("Problème constaté", "probleme"), ("Actions réalisées", "actions"),
                         ("Résultat", "resultat"), ("Recommandations", "recommandations")):
        if r.get(cle):
            story += [Spacer(1, 8), Paragraph(libelle, h), p(r[cle], corps)]
    if r.get("pieces"):
        story += [Spacer(1, 8), Paragraph("Pièces remplacées", h)]
        for x in r["pieces"]:
            story.append(p(f"• {x.get('quantite') or 1} × {x.get('designation')}"
                           + (f" (réf. {x['reference']})" if x.get("reference") else ""), corps))
    if r.get("etat_apres_libelle"):
        story += [Spacer(1, 8), p(f"État des équipements après intervention : {r['etat_apres_libelle']}", corps)]
    if r.get("photos"):
        story += [Spacer(1, 6), p(f"{len(r['photos'])} photo(s) jointe(s) : consultables sur le lien du rapport.", meta)]
    story += [Spacer(1, 6), p(f"Empreinte SHA-256 du contenu : {r.get('empreinte_sha256')}", meta)]
    sig = r.get("signature")
    if sig:
        vert = ParagraphStyle("sig", parent=styles["Normal"], fontSize=9, leading=13, textColor=colors.HexColor("#065F46"))
        cellules: List[Any] = [Paragraph(
            f"<b>✓ Rapport signé électroniquement</b><br/>par <b>{html.escape(sig.get('nom') or '')}</b>"
            + (f" ({html.escape(sig['fonction'])})" if sig.get("fonction") else "")
            + f"<br/>le <b>{_date_heure_fr(sig.get('signe_le'))} (UTC)</b> — adresse IP {html.escape(sig.get('ip') or '—')}"
            + f"<br/><font size='7' color='#475569'>Empreinte signée : {html.escape(sig.get('empreinte') or '')}<br/>"
            + "Document verrouillé après signature.</font>", vert)]
        try:
            png = base64.b64decode((sig.get("image") or "").split(",", 1)[1])
            cellules.append(Image(io.BytesIO(png), width=5 * cm, height=2 * cm, kind="proportional"))
        except Exception:  # noqa: BLE001 — l'image de la signature est facultative dans le PDF
            cellules.append("")
        bloc = Table([cellules], colWidths=[11.5 * cm, 5.5 * cm])
        bloc.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ECFDF5")),
                                  ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#10B981")),
                                  ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story += [Spacer(1, 16), bloc]
    else:
        story += [Spacer(1, 16), p("En attente de la signature du responsable.", meta)]
    pdf.build(story)
    return buf.getvalue()


__all__ = ["attach_parc_routes", "normaliser_ip", "normaliser_mac", "empreinte", "rendre_pdf"]
