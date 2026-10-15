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

Lot 94 — carte SANS lien (carte produit sans lien saisi, carte libre sans lien ni « lien par défaut ») :
le bouton mène à la PAGE DE PRÉSENTATION du site, <site>/presentation/{code} (photo, titre, texte,
prix et description du produit), au lieu d'une page d'erreur. Données lues par
GET /api/public/carrousel/carte/{code} (public, sans compter de clic).

Lot 111 — PAGE DE PRÉSENTATION DE TOUT LE CARROUSEL, une position par carte, et CARROUSEL SPONSORISÉ :
  - chaque carte a une « description détaillée » (markdown simple, 4000 caractères) et un mode de bouton :
    « presentation » (par défaut sans lien) ou « lien » (lien personnalisé, comportement d'avant) ;
  - en mode présentation, le lien court renvoie vers <site>/presentation/c/<id_public>?depuis=<code>#carte-<n>
    (le « # » est ajouté par le serveur dans la redirection, jamais dans la variable du modèle Meta) ;
      GET  /api/public/carrousel/presentation/{id_public}   toutes les cartes (aucune donnée de destinataire)
      POST /api/public/carrousel/evenement                  « vue » / « interesse », dédupliqués 24 h
  - un carrousel de l'administration peut être rattaché à une campagne de la RÉGIE PUBLICITAIRE (ad_banners,
    placement « carrousel_wa ») : clics facturés au coût par clic (dédupliqués), envois au coût par envoi,
    garde-fou à l'envoi quand le budget est épuisé ou la campagne expirée. Voir routes/carrousel_regie.py.
      GET  /api/admin/whatsapp/carrousel/regies                       campagnes de régie « Carrousel WhatsApp »
      PUT  /api/admin/whatsapp/carrousel/campagnes/{id}/regie         rattacher / détacher un envoi
      GET  /api/admin/whatsapp/carrousel/regie/etat                   état pour la page Paramètres

Lot 114 — CARROUSELS PROGRAMMÉS et PLAGES HORAIRES D'ENVOI (portail ET administration, sponsorisés compris) :
  - « Envoyer maintenant » ou « Programmer le JJ/MM/AAAA à HH:MM » (heure de Ouagadougou) : champ `programme_le`
    de l'envoi, contrôlé par routes/plages_envoi.py (une date passée est refusée) ;
  - les envois respectent les plages horaires fixées par l'Admin (lot 42, Paramètres) : hors plage, la campagne
    passe « EN_ATTENTE » et démarre à la prochaine ouverture ; une campagne en cours s'arrête à la fin de la
    plage et reprend toute seule à l'ouverture suivante, là où elle s'était arrêtée (un destinataire déjà
    servi — ENVOYE ou ECHEC — n'est jamais renvoyé) ;
  - statuts d'une campagne : PROGRAMMEE, EN_ATTENTE (hors plage), EN_COURS, TERMINEE, ANNULEE ;
  - un verrou en base (`verrou_jusqu_a`) empêche deux envois en parallèle de la même campagne (deux tâches,
    deux serveurs, redémarrage) ;
  - carrousel sponsorisé : le contrôle budget / dates de la régie est refait AU MOMENT RÉEL de l'envoi
    (campagne ANNULEE avec son motif si la régie ne le permet plus) ;
  - un planificateur (toutes les minutes) démarre les campagnes échues et reprend celles restées EN_COURS
    après un redémarrage du serveur.
      POST /api/me/whatsapp/carrousel/campagnes/{id}/annuler       annuler (ses propres campagnes)
      POST /api/admin/whatsapp/carrousel/campagnes/{id}/annuler    annuler (toutes les campagnes)
      GET  /api/admin/whatsapp/carrousel/programmation/etat        état pour la page Paramètres
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional

from fastapi import BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from routes.whatsapp_helpers import _normalize_wa_phone
from routes import carrousel_regie as regie     # lot 111 : présentation par campagne et régie publicitaire
from routes.plages_envoi import DEFAUT as PLAGES_DEFAUT, instant_programme   # lot 114 : envois programmés

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
CHEMIN_BOUTON = "/l/"                      # lot 117 : page du site qui ouvre la carte (sans redirection serveur)
CHEMIN_PRESENTATION = "/presentation/"   # lot 94 : page du site qui présente une carte sans lien
CHEMIN_OG_PRODUIT = "/api/public/og/product/"   # ancien lien automatique des cartes produit
DESCRIPTION_MAX = 4000                  # lot 111 : description détaillée d'une carte (page de présentation)


# Lot 114 — statuts d'une campagne de carrousel et leur libellé français (pastilles des listes)
STATUTS_CAMPAGNE = {
    "PROGRAMMEE": "Programmée",          # date d'envoi future choisie par l'utilisateur
    "EN_ATTENTE": "En attente",          # hors des plages horaires d'envoi : reprendra à l'ouverture suivante
    "EN_COURS": "En cours",              # envoi en train de partir
    "TERMINEE": "Terminée",              # tous les destinataires ont été servis
    "ANNULEE": "Annulée",                # annulée par l'utilisateur (ou régie qui ne permet plus l'envoi)
}
STATUTS_ANNULABLES = ["PROGRAMMEE", "EN_ATTENTE", "EN_COURS"]
STATUTS_DEST_SERVIS = ("ENVOYE", "ECHEC")   # destinataire déjà traité : jamais renvoyé à la reprise
VERROU_MINUTES = 5                       # durée du verrou d'envoi (renouvelé à chaque destinataire)
PLANIFICATEUR_SECONDES = 60              # fréquence du planificateur des envois programmés / en attente


def doit_presenter(cible: Optional[str]) -> bool:
    """Lot 94 — le bouton d'une carte mène-t-il à la page de présentation du site ? Oui si la carte n'a
    pas de lien, ou si son lien est l'ancien lien automatique d'un produit (il finissait sur une erreur)."""
    cible = (cible or "").strip()
    return not cible or CHEMIN_OG_PRODUIT in cible
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


# Lot 115.1 — motif du refus donné par Meta (champ rejected_reason), traduit en mots simples.
# Constat du 12/10/2026 : plusieurs séries de modèles refusées, sans que SAWALI n'en affiche la raison.
MOTIFS_REFUS = {
    "INVALID_FORMAT": "format non conforme (variables, exemple d'URL ou image d'exemple)",
    "TAG_CONTENT_MISMATCH": "le contenu ne correspond pas à la catégorie choisie",
    "INCORRECT_CATEGORY": "catégorie incorrecte",
    "PROMOTIONAL": "contenu jugé promotionnel pour la catégorie",
    "ABUSIVE_CONTENT": "contenu jugé abusif ou trompeur",
    "SCAM": "contenu jugé frauduleux (souvent : lien de redirection)",
    "NONE": "aucun motif donné par Meta",
}


def motifs_depuis_liste(prefixe: str, langue: str, modeles: List[dict]) -> Dict[int, Dict[str, str]]:
    """Lot 115.1 — {nombre de cartes: {"code", "libelle"}} pour les modèles REFUSÉS (même filtre que les statuts)."""
    sortie: Dict[int, Dict[str, str]] = {}
    for m in modeles or []:
        nom = str(m.get("name") or "")
        if not nom.startswith(f"{prefixe}_") or (langue and (m.get("language") or langue) != langue):
            continue
        suffixe = nom[len(prefixe) + 1:]
        if (suffixe.isdigit() and CARTES_MIN <= int(suffixe) <= CARTES_MAX
                and str(m.get("status") or "").upper() == "REJECTED"):
            code = str(m.get("rejected_reason") or "NONE").upper()
            sortie[int(suffixe)] = {"code": code, "libelle": MOTIFS_REFUS.get(code, code)}
    return sortie


def _est_carrousel(m: dict) -> bool:
    """Lot 117.1 — vrai si le modèle Meta est un carrousel (composant CAROUSEL)."""
    return any(str(c.get("type") or "").upper() == "CAROUSEL" for c in (m.get("components") or []))


def series_carrousel_approuvees(modeles: List[dict], langue: str, sauf: str = "") -> Dict[str, int]:
    """Lot 117.1 — {préfixe: nombre de modèles APPROUVÉS} des séries de carrousel du compte (noms <préfixe>_2 … _10).
    Constat du 12/10/2026 : Meta refuse aussitôt (« format non conforme ») une nouvelle série qui recopie les textes d'une
    série déjà approuvée ; il faut alors réutiliser celle-ci au lieu d'en déposer une autre."""
    series: Dict[str, int] = {}
    for m in modeles or []:
        nom = str(m.get("name") or "")
        prefixe, _, n = nom.rpartition("_")
        if (not prefixe or prefixe == sauf or not n.isdigit() or not (CARTES_MIN <= int(n) <= CARTES_MAX)
                or str(m.get("status") or "").upper() != "APPROVED" or (langue and (m.get("language") or langue) != langue)
                or (m.get("components") is not None and not _est_carrousel(m))):
            continue
        series[prefixe] = series.get(prefixe, 0) + 1
    return series


def url_bouton_reelle(modeles: List[dict], prefixe: str) -> Optional[str]:
    """Lot 117.1 — adresse RÉELLE du bouton des cartes dans les modèles <préfixe>_N déjà déposés chez Meta
    (une série approuvée garde l'adresse de son dépôt, même si SAWALI en propose une autre pour les nouvelles séries)."""
    for m in modeles or []:
        if not str(m.get("name") or "").startswith(f"{prefixe}_"):
            continue
        for c in m.get("components") or []:
            for carte in c.get("cards") or []:
                for sc in carte.get("components") or []:
                    for b in sc.get("buttons") or []:
                        if str(b.get("type") or "").upper() == "URL" and b.get("url"):
                            return str(b["url"])
    return None


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
    # Lot 111 — texte long de la page de présentation (gras, listes, liens en markdown simple)
    description_detaillee: Optional[str] = Field(None, max_length=DESCRIPTION_MAX)
    # Lot 111 — où mène le bouton : page de présentation (défaut sans lien) ou lien personnalisé
    bouton: Optional[Literal["presentation", "lien"]] = None


class EnvoiIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    cartes: List[CarteIn] = Field(..., min_length=CARTES_MIN, max_length=CARTES_MAX)
    ids: List[str] = Field(default_factory=list)          # contacts (portail) ou clients (admin)
    groupes: List[str] = Field(default_factory=list)      # groupes de contacts (portail)
    # Lot 111 — campagne de la régie publicitaire qui sponsorise ce carrousel (administration seulement)
    regie_id: Optional[str] = Field(None, max_length=80)
    # Lot 114 — date et heure d'envoi programmées (« 2026-10-15T09:30 », heure de Ouagadougou) ; vide = maintenant
    programme_le: Optional[str] = Field(None, max_length=40)
    # Lot 168 — société (compte client) dont l'administration utilise les contacts et groupes ; vide = « mes contacts »
    societe_id: Optional[str] = Field(None, max_length=80)


class LienRegieIn(BaseModel):
    """Lot 111 — rattacher un envoi de carrousel à une campagne de régie (vide = détacher)."""
    regie_id: Optional[str] = Field(None, max_length=80)


class EvenementIn(BaseModel):
    """Lot 111 — événement de la page de présentation : « vue » (arrivée sur la carte) ou « interesse »
    (bouton « Je suis intéressé »). La campagne est donnée par son identifiant public ou par le code d'une carte."""
    campagne: Optional[str] = Field(None, max_length=40)
    code: Optional[str] = Field(None, max_length=40)
    carte: int = Field(..., ge=1, le=CARTES_MAX)
    type: Literal["vue", "interesse"]


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
    societe_id: Optional[str] = Field(None, max_length=80)      # lot 168 : contacts d'une société


class OrphelinIn(BaseModel):
    """Lot 204 — une personne dont l'accord est tracé mais sans fiche : numéro, client choisi, nom (facultatif)."""
    telephone: str = Field(..., min_length=8, max_length=30)
    client_id: str = Field(..., min_length=1, max_length=80)
    nom: Optional[str] = Field(None, max_length=120)


class RattacherIn(BaseModel):
    """Lot 204 — rattacher des accords orphelins à un client ; `campagne_id` = carrousel à leur envoyer ensuite (facultatif)."""
    items: List[OrphelinIn] = Field(..., min_length=1, max_length=200)
    campagne_id: Optional[str] = Field(None, max_length=80)


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


class DemandeAccordModeleIn(BaseModel):
    """Lot 167 — personnes à qui envoyer le modèle d'accord, tout de suite ou à `programme_le` (heure de Ouagadougou)."""
    ids: List[str] = Field(default_factory=list, max_length=DESTINATAIRES_MAX)
    programme_le: Optional[str] = Field(None, max_length=40)
    societe_id: Optional[str] = Field(None, max_length=80)      # lot 168 : société dont on utilise les contacts


class AccordModeleIn(BaseModel):
    """Lot 165 — modèle de demande d'accord à lien personnel (nom en minuscules, chiffres et _)."""
    modele: str = Field("sawali_accord_lien", min_length=3, max_length=60, pattern=r"^[a-z0-9_]+$")
    langue: str = Field(LANGUE_DEFAUT, min_length=2, max_length=10)


class ReglagesIn(BaseModel):
    modele: str = Field(..., min_length=3, max_length=60, pattern=r"^[a-z0-9_]+$")
    langue: str = Field(LANGUE_DEFAUT, min_length=2, max_length=10)
    tenant_id: Optional[str] = None     # modèles propres à un client qui a son numéro WhatsApp
    forcer: bool = False                # lot 117.1 : déposer une nouvelle série même si une série approuvée existe


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
    plages: Optional[Dict[str, Any]] = None,
    is_preview_env: Callable[[], bool] = lambda: False,
    wa_send_text: Optional[Callable[..., Awaitable[dict]]] = None,
) -> Dict[str, Any]:
    """Branche les routes du carrousel. `base_publique()` : adresse publique du site
    (PUBLIC_BASE_URL), utilisée pour les images et les liens des boutons.
    Lot 114 — `plages` : {config, attente, programme} de routes/plages_envoi.py (plages horaires d'envoi et
    contrôle de la date programmée) ; None = aucune restriction horaire.
    `is_preview_env()` : vrai dans la preview Emergent (copie de la production) → aucun envoi automatique."""

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
        # Lot 117 — page du site « /l/{{1}} » (et non plus /api/public/carrousel/l/{{1}}, qui redirigeait :
        # Meta a refusé tous les modèles pour « format non conforme », constat du 12/10/2026)
        return f"{base_publique().rstrip('/')}{CHEMIN_BOUTON}{{{{1}}}}"

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
            return {"prefixe": prefixe, "statuts": cache[1], "motifs": cache[2] if len(cache) > 2 else {},
                    "url_bouton_reelle": cache[3] if len(cache) > 3 else None, "erreur": None}
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
                                     params={"name": prefixe, "fields": "name,status,language,rejected_reason,components", "limit": 200},   # lot 115.1 : motif ; 117.1 : adresse du bouton
                                     headers={"Authorization": f"Bearer {jeton}"})
            if rep.status_code >= 300:
                return {"prefixe": prefixe, "statuts": {}, "erreur": f"Meta : HTTP {rep.status_code}"}
            donnees = (rep.json() or {}).get("data") or []
            statuts = statuts_depuis_liste(prefixe, langue, donnees)
            motifs = motifs_depuis_liste(prefixe, langue, donnees)          # lot 115.1
            url_reelle = url_bouton_reelle(donnees, prefixe)                 # lot 117.1
        except Exception as exc:  # noqa: BLE001 — l'écran reste utilisable sans les pastilles
            return {"prefixe": prefixe, "statuts": {}, "erreur": f"Meta injoignable : {type(exc).__name__}"}
        _cache_statuts[cle] = (time.time(), statuts, motifs, url_reelle)
        return {"prefixe": prefixe, "statuts": statuts, "motifs": motifs, "url_bouton_reelle": url_reelle, "erreur": None}

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
                           "lien": c.get("lien") or f"{base.rstrip('/')}/api/public/og/product/{p['id']}",
                           # Lot 111 — description détaillée et mode du bouton conservés
                           "description_detaillee": c.get("description_detaillee") or "",
                           "bouton": c.get("bouton") or ("lien" if c.get("lien") else "presentation")})
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
        # Lot 164 — lien PERSONNEL (page SAWALI d'accord) de chaque personne sans accord : à donner à celles dont la
        # fenêtre WhatsApp est fermée, ou à mettre dans un bouton de message
        return {**res, "deja": len(personnes) - len(sans_accord), "liens": _liens_accord(sans_accord)}

    def _liens_accord(personnes: List[dict]) -> List[dict]:
        """Lot 164 — [{id, nom, lien}] : page /accord/<jeton> de chaque contact (le jeton est signé par le serveur)."""
        from routes import accord_page as ap
        base = base_publique()
        try:
            return [{"id": p["id"], "nom": p.get("nom") or "", "lien": ap.lien_personnel(base, p["id"])} for p in personnes]
        except RuntimeError:           # secret de signature absent : pas de liens, mais la demande d'accord reste utilisable
            logger.warning("[carrousel] liens d'accord personnels indisponibles (JWT_SECRET absent)")
            return []

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
                # Lot 94 — sans lien saisi : page de présentation du site (lien vide, voir doit_presenter)
                lien = (c.lien or "").strip()
                produit_id = p["id"]
            else:
                image, titre = url_absolue(c.image_url, base), (c.titre or "").strip()
                # Lot 78 — carte libre sans lien : lien par défaut réglé sur la page Carrousel
                texte, lien, produit_id = (c.texte or "").strip(), (c.lien or "").strip() or lien_defaut, None
            if not image_acceptee(image):
                raise HTTPException(status_code=400, detail=f"Carte {i} : image JPEG ou PNG publique (https) obligatoire")
            if not titre:
                raise HTTPException(status_code=400, detail=f"Carte {i} : titre obligatoire")
            # Lot 94 — pas de lien : la carte mène à sa page de présentation sur le site (plus d'erreur)
            if lien and not lien_accepte(lien):
                raise HTTPException(status_code=400, detail=f"Carte {i} : lien invalide (https://…) — corrigez-le, "
                                                            "ou laissez-le vide pour présenter la carte sur le site")
            # Lot 111 — mode du bouton : choisi dans l'éditeur ; sinon « lien » s'il y a un lien, « presentation » sinon.
            # Un mode « lien » sans lien mène quand même à la page de présentation (jamais de page d'erreur).
            bouton = c.bouton or ("lien" if lien else "presentation")
            if bouton == "lien" and not lien:
                bouton = "presentation"
            prets.append({"source": c.source, "produit_id": produit_id, "image_url": image,
                          "titre": titre[:60], "texte": texte[:80], "lien": lien, "bouton": bouton,
                          "description_detaillee": (c.description_detaillee or "").strip()[:DESCRIPTION_MAX]})
        return prets

    # --- Destinataires -------------------------------------------------------
    async def _marquer_reponses(lignes: List[dict]) -> List[dict]:
        """Lot 155 — ajoute `a_repondu` à chaque ligne : ce numéro a-t-il DÉJÀ écrit à la plateforme (message WhatsApp reçu) ?
        WhatsApp peut refuser (code 131049) un modèle MARKETING à quelqu'un qui n'interagit jamais : l'écran prévient
        avant l'envoi. Une seule requête pour toute la liste."""
        numeros = {numero_whatsapp(x.get("telephone")) for x in lignes if x.get("telephone")}
        numeros.discard("")
        ont_ecrit: set = set()
        if numeros:
            ont_ecrit = set(await db.whatsapp_messages.distinct(
                "phone_digits", {"direction": "inbound", "phone_digits": {"$in": list(numeros)}}))
        for x in lignes:
            x["a_repondu"] = bool(x.get("telephone")) and numero_whatsapp(x.get("telephone")) in ont_ecrit
        return lignes

    async def _contacts_portail(user: dict) -> Dict[str, Any]:
        return await _annuaire_pour_ids(await visible_client_ids(user))

    SOCIETE_PLATEFORME = "@plateforme"           # lot 168.1 : SAWALI SMART SYSTEMS (comptes de l'administration)

    async def _ids_plateforme() -> List[str]:
        """Lot 168.2 — tous les identifiants sous lesquels sont rangés les contacts, utilisateurs suivis et groupes de
        SAWALI SMART SYSTEMS (SAWALI-2S). Ce n'est pas un client « canonique » : ses données sont éparpillées sur plusieurs
        identifiants (compte plateforme, administrateurs, superviseurs, anciens `client_id`). Même règle que le portail
        (`_resolve_visible_client_ids`) : on part des comptes plateforme / administrateurs / superviseurs, puis on ajoute
        TOUS les comptes de la même société (insensible à la casse) avec leurs `id`, `client_id`, `parent_client_id`
        et ancien `client_id_legacy`."""
        champs = {"_id": 0, "id": 1, "client_id": 1, "parent_client_id": 1, "client_id_legacy": 1, "company": 1, "email": 1}
        ids: set = set()
        # Lot 168.3 — la société s'écrit de plusieurs façons (« SAWALI-2S », « SAWALI SMART SYSTEMS »…) selon les comptes
        societes: set = {"sawali-2s", "sawali 2s", "sawali smart systems", "sawali"}

        def noter(u: dict) -> None:
            ids.update(x for x in (u.get("id"), u.get("client_id"), u.get("parent_client_id"), u.get("client_id_legacy")) if x)

        async for u in db.users.find({"$or": [{"email": COMPTE_PLATEFORME}, {"role": {"$in": ["admin", "superviseur"]}}]}, champs):
            noter(u)
            if (u.get("company") or "").strip():
                societes.add(u["company"].strip().lower())
        async for u in db.users.find({}, champs):
            # même société (quelle que soit l'écriture) ou adresse e-mail de la société (@sawalismartsystems.com)
            if (u.get("company") or "").strip().lower() in societes or (u.get("email") or "").lower().endswith("@sawalismartsystems.com"):
                noter(u)
        return sorted(ids)

    async def _societes_visibles(ids: List[str]) -> List[str]:
        """Lot 168.1 — identifiants de société qu'un utilisateur du portail peut voir : les siens, plus SAWALI SMART
        SYSTEMS s'il en fait partie (ses demandes et carrousels lui sont alors visibles)."""
        plateforme = set(await _ids_plateforme())
        return list(ids) + ([SOCIETE_PLATEFORME] if plateforme & set(ids) else [])

    async def _ids_societe(societe_id: str) -> List[str]:
        """Lot 168 — la société (compte client) et ses sous-comptes : les données de tous sont rangées sous leur identifiant."""
        if societe_id == SOCIETE_PLATEFORME:
            return await _ids_plateforme()
        sous = [u["id"] async for u in db.users.find({"parent_client_id": societe_id}, {"_id": 0, "id": 1})]
        return [societe_id] + sous

    async def _annuaire_pour_ids(ids: List[str]) -> Dict[str, Any]:
        """Contacts, utilisateurs suivis et groupes rangés sous les comptes `ids` (portail : ceux que l'utilisateur voit ;
        lot 168 : ceux d'une société choisie par l'administration)."""
        # Lot 168.3 — comme la page « Groupes de contacts » : rangés sous le compte (`client_id`) OU créés par lui (`owner_id`)
        portee = {"$or": [{"client_id": {"$in": ids}}, {"owner_id": {"$in": ids}}]}
        contacts = await db.directory_contacts.find(
            portee,
            {"_id": 0, "id": 1, "name": 1, "company": 1, "whatsapp": 1, "phone": 1, "tags": 1, "accord_demande_le": 1,
             "accepte_whatsapp": 1, "accepte_whatsapp_le": 1, "accepte_whatsapp_moyen": 1}).sort("name", 1).to_list(5000)
        groupes = await db.contact_groups.find(
            portee, {"_id": 0, "id": 1, "name": 1, "color": 1, "contact_ids": 1}
        ).sort("name", 1).to_list(500)
        lignes = [{"id": c["id"], "nom": c.get("name") or "", "societe": c.get("company") or "",
                   "telephone": c.get("whatsapp") or c.get("phone") or "",
                   "accepte": bool(c.get("accepte_whatsapp")), "accepte_le": c.get("accepte_whatsapp_le"),
                   "moyen": c.get("accepte_whatsapp_moyen"), "demande_le": c.get("accord_demande_le")}
                  for c in contacts]
        # Lot 78.1 — les utilisateurs suivis du client sont aussi des destinataires possibles
        suivis_docs = await db.tracked_users.find({"client_id": {"$in": ids}}, {
            "_id": 0, "id": 1, "name": 1, "whatsapp_number": 1, "phone": 1, "accord_demande_le": 1,
            "accepte_whatsapp": 1, "accepte_whatsapp_le": 1, "accepte_whatsapp_moyen": 1}).to_list(2000)
        suivis = [_ligne(t, t.get("name"), "Utilisateur suivi", t.get("whatsapp_number") or t.get("phone"))
                  for t in suivis_docs if t.get("id")]
        lignes = sorted(lignes + suivis, key=lambda x: x["nom"].lower())
        liste_groupes = [{"id": g["id"], "nom": g.get("name") or "", "couleur": g.get("color"),
                          "contact_ids": g.get("contact_ids") or []} for g in groupes]
        if suivis:
            liste_groupes.insert(0, {"id": "@suivis", "nom": "Utilisateurs suivis", "couleur": None,
                                     "contact_ids": [x["id"] for x in suivis]})
        return {"contacts": await _marquer_reponses(lignes), "groupes": liste_groupes}

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
                "moyen": doc.get("accepte_whatsapp_moyen"),   # lot 79 : bouton, mot-clé ou noté à la main
                "demande_le": doc.get("accord_demande_le")}   # lot 168 : date de la dernière demande d'accord

    def _portees_admin(user: Optional[dict]) -> List[str]:
        """Lot 78.1 — « mes contacts » de l'administration : ceux rangés sous le compte admin connecté."""
        return [x for x in {(user or {}).get("id"), (user or {}).get("client_id")} if x]

    async def _societes_admin() -> List[dict]:
        """Lot 168 — les sociétés (comptes clients) qui possèdent des contacts, des utilisateurs suivis ou des groupes,
        avec leurs effectifs : l'administration choisit une société pour en voir les groupes (ex. « Prospects publicités
        Facebook » de SAWALI SMART SYSTEMS, invisible dans « mes contacts »). Les sous-comptes comptent pour leur parent."""
        comptes = {c["id"]: c async for c in db.users.find(
            {"role": {"$in": ROLES_CLIENTS}, "email": {"$nin": [COMPTE_PLATEFORME]}},
            {"_id": 0, "id": 1, "company": 1, "full_name": 1, "email": 1, "parent_client_id": 1})}

        plateforme = set(await _ids_plateforme())

        def racine(cid: str) -> str:
            if cid in plateforme:
                return SOCIETE_PLATEFORME
            return (comptes.get(cid) or {}).get("parent_client_id") or cid

        effectifs: Dict[str, Dict[str, int]] = {}
        for cle, coll in (("contacts", db.directory_contacts), ("suivis", db.tracked_users), ("groupes", db.contact_groups)):
            async for d in coll.find({}, {"_id": 0, "client_id": 1, "owner_id": 1}):
                # Lot 168.3 — rangé sous un compte (`client_id`) ou créé par lui (`owner_id`), comme la page des groupes
                cid = next((x for x in (d.get("client_id"), d.get("owner_id")) if x in comptes or x in plateforme), None)
                if cid:
                    e = effectifs.setdefault(racine(cid), {"contacts": 0, "suivis": 0, "groupes": 0})
                    e[cle] += 1
        lignes = []
        for rid, e in effectifs.items():
            c = comptes.get(rid) or {}
            nom = "SAWALI SMART SYSTEMS" if rid == SOCIETE_PLATEFORME else (c.get("company") or c.get("full_name") or c.get("email") or rid)
            lignes.append({"id": rid, "nom": nom, **e})
        return sorted(lignes, key=lambda x: x["nom"].lower())

    async def _clients_admin(user: Optional[dict] = None, societe_id: Optional[str] = None) -> Dict[str, Any]:
        """Destinataires de l'administration SAWALI.
        Lot 168 : avec `societe_id`, uniquement les contacts, utilisateurs suivis et groupes de cette société.
        Lot 78.1 : en plus des clients, les utilisateurs suivis (tracked_users) et les contacts
        de l'annuaire de l'administration ; des groupes « Clients », « Utilisateurs suivis »,
        « Mes contacts » et les groupes de contacts de l'administration permettent de tout cocher d'un clic."""
        if societe_id:
            return await _annuaire_pour_ids(await _ids_societe(societe_id))
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
        return {"contacts": await _marquer_reponses(lignes), "groupes": [g for g in groupes if g["contact_ids"]]}

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
        # Lot 114 — date d'envoi programmée (refusée si déjà passée) : contrôlée AVANT tout enregistrement
        quand = await _programme(envoi.programme_le)
        programme = bool(quand and quand > datetime.now(timezone.utc))
        # Lot 111 — carrousel sponsorisé (administration seulement) : garde-fou budget / dates de la régie
        regie_id = ((envoi.regie_id or "").strip() or None) if perimetre == "admin" else None
        if regie_id:
            try:
                await regie.regie_envoyable(db, regie_id, len(destinataires))
            except ValueError as exc:
                # Lot 114 — envoi PROGRAMMÉ : une régie « pas encore commencée » ou « en pause » peut l'être au
                # moment réel de l'envoi (contrôle refait par _executer) ; budget épuisé / expirée = refus immédiat
                if not (programme and _regie_peut_attendre(str(exc))):
                    logger.info("[carrousel] envoi sponsorisé refusé (%s) : %s", regie_id, exc)
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Lot 114 — statut de départ : PROGRAMMEE (date future), EN_ATTENTE (hors plage horaire) ou EN_COURS
        ouverture = None if programme else await _attente()
        if programme:
            statut, reprise = "PROGRAMMEE", quand
        elif ouverture is not None:
            statut, reprise = "EN_ATTENTE", ouverture
        else:
            statut, reprise = "EN_COURS", None
        campagne_id = secrets.token_hex(8)
        for i, c in enumerate(cartes):
            # Code court du bouton : caractères base64 URL seulement (jamais de « # » dans la variable Meta)
            c["code_lien"] = secrets.token_urlsafe(6)
            await db.carrousel_liens.insert_one({"code": c["code_lien"], "cible": c["lien"], "campagne_id": campagne_id,
                                                 "carte_index": i, "clics": 0, "bouton": c.get("bouton") or "presentation",
                                                 "cree_le": _maintenant()})
        doc = {
            "id": campagne_id, "perimetre": perimetre, "tenant_id": tenant_id, "cree_le": _maintenant(),
            "cree_par": user["id"], "cree_par_nom": user.get("full_name") or user.get("email"),
            "expediteur": expediteur[:60], "message": envoi.message, "cartes": cartes,
            "modele": nom_modele(r["modele"], len(cartes)), "langue": r["langue"],
            "creds_tenant": r["creds_tenant"], "destinataires": destinataires,
            "statut": statut, "compte": {"total": len(destinataires), "envoyes": 0, "echecs": 0},
            # Lot 111 — identifiant public (page de présentation) et campagne de régie qui sponsorise
            "id_public": regie.nouvel_id_public(), "regie_id": regie_id,
            # Lot 168 — société dont l'administration a utilisé les contacts : son superviseur voit alors le statut
            "societe_id": ((envoi.societe_id or "").strip() or None) if perimetre == "admin" else None,
            # Lot 114 — programmation et reprise : date choisie, prochaine reprise, verrou d'envoi.
            # `reprenable` distingue les campagnes du lot 114 : seules elles sont reprises après un redémarrage
            # (une ancienne campagne restée « EN_COURS » ne repart jamais d'elle-même des semaines plus tard).
            "programme_le": quand.isoformat() if programme else None,
            "reprise_le": reprise.isoformat() if reprise else None,
            "verrou_jusqu_a": None, "reprenable": True,
        }
        await db.carrousel_campagnes.insert_one(dict(doc))
        if regie_id:
            await db.ad_banners.update_one({"id": regie_id}, {"$addToSet": {"carrousel_campagne_ids": campagne_id}})
            await regie.apercu_si_vide(db, regie_id, campagne_id)
        if statut == "EN_COURS":
            bg.add_task(_executer, campagne_id)          # envoi immédiat, en fond après la réponse
        logger.info("[carrousel] campagne %s créée (%s) : %s, %d destinataire(s)", campagne_id, perimetre, statut,
                    len(destinataires))
        return {"id": campagne_id, "destinataires": len(destinataires), "modele": doc["modele"],
                "ignores": len(personnes) - len(destinataires), "statut": statut,
                "statut_libelle": STATUTS_CAMPAGNE[statut], "programme_le": doc["programme_le"],
                "reprise_le": doc["reprise_le"]}

    # --- Lot 114 : plages horaires, programmation, verrou, reprise -----------------------
    async def _attente() -> Optional[datetime]:
        """None si l'envoi est permis maintenant ; sinon la prochaine ouverture de plage (UTC).
        Sans réglage des plages (tests, ancien branchement) : jamais d'attente."""
        if plages is None:
            return None
        return await plages["attente"]()

    async def _programme(texte: Optional[str]) -> Optional[datetime]:
        """Date programmée saisie → instant UTC (None si vide). Refus (400) si illisible ou déjà passée.
        Même contrôle que les formulaires et sondages (routes/plages_envoi.py)."""
        if plages is not None:
            return await plages["programme"](texte)
        try:
            d = instant_programme(texte, PLAGES_DEFAUT)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if d and d < datetime.now(timezone.utc) - timedelta(minutes=5):
            raise HTTPException(status_code=400, detail="La date d'envoi programmée est déjà passée")
        return d

    def _regie_peut_attendre(motif: str) -> bool:
        """Lot 114 — motifs de refus de la régie qui peuvent se lever d'ici la date programmée."""
        return "pas encore commencée" in motif or "en pause" in motif

    async def _prendre_verrou(campagne_id: str) -> bool:
        """Verrou simple en base : une seule tâche à la fois envoie une campagne donnée (même entre deux
        serveurs). Pris seulement si la campagne est EN_COURS et que le verrou est libre ou périmé
        (tâche arrêtée par un redémarrage : le verrou expire de lui-même après VERROU_MINUTES)."""
        maintenant = datetime.now(timezone.utc)
        r = await db.carrousel_campagnes.update_one(
            {"id": campagne_id, "statut": "EN_COURS",
             "$or": [{"verrou_jusqu_a": None}, {"verrou_jusqu_a": {"$lt": maintenant.isoformat()}}]},
            {"$set": {"verrou_jusqu_a": (maintenant + timedelta(minutes=VERROU_MINUTES)).isoformat()}})
        return bool(r.modified_count)

    async def _prolonger_verrou(campagne_id: str) -> None:
        """Renouvelle le verrou pendant l'envoi (un destinataire = quelques secondes au plus)."""
        fin = (datetime.now(timezone.utc) + timedelta(minutes=VERROU_MINUTES)).isoformat()
        await db.carrousel_campagnes.update_one({"id": campagne_id}, {"$set": {"verrou_jusqu_a": fin}})

    async def _prevenir_admin(campagne_id: str) -> None:
        """Lot 186 — Liluvine tient l'administrateur au courant : un message WhatsApp au numéro réglé dans les Paramètres
        (`carrousel_notif_wa_phone`) à la fin de chaque campagne. Jamais bloquant : une erreur est seulement journalisée."""
        try:
            if wa_send_text is None:
                return
            reglages = await db.settings.find_one({"_id": "global"}, {"_id": 0, "carrousel_notif_wa_phone": 1}) or {}
            numero = str(reglages.get("carrousel_notif_wa_phone") or "").strip()
            if not numero:
                return
            c = await db.carrousel_campagnes.find_one({"id": campagne_id}, {"_id": 0}) or {}
            from routes.carrousel_notification import texte_envoi_carrousel
            res = await wa_send_text(numero, texte_envoi_carrousel(c))
            logger.info("[carrousel] compte rendu de la campagne %s envoyé à l'administrateur : %s", campagne_id,
                        "ok" if (res or {}).get("ok") else f"échec ({(res or {}).get('error')})")
        except Exception:  # noqa: BLE001
            logger.warning("[carrousel] compte rendu à l'administrateur impossible", exc_info=True)

    async def _executer(campagne_id: str) -> None:
        """Envoi un par un ; chaque résultat est gardé sur la campagne et dans
        whatsapp_messages (compteurs d'usage de la plateforme).
        Lot 114 — REPRENABLE : saute les destinataires déjà servis (ENVOYE / ECHEC), vérifie la plage horaire
        et l'annulation avant chaque envoi, s'arrête proprement hors plage (EN_ATTENTE + reprise_le) et ne
        tourne jamais deux fois en même temps pour la même campagne (verrou en base)."""
        if not await _prendre_verrou(campagne_id):
            return                                    # déjà en cours ailleurs, annulée, programmée ou terminée
        try:
            c = await db.carrousel_campagnes.find_one({"id": campagne_id}, {"_id": 0})
            if not c:
                return
            restants = [d for d in c["destinataires"] if d.get("statut") not in STATUTS_DEST_SERVIS]
            # Lot 114 — carrousel sponsorisé : budget et dates de la régie contrôlés AU MOMENT RÉEL de l'envoi
            if c.get("regie_id") and restants:
                try:
                    await regie.regie_envoyable(db, c["regie_id"], len(restants))
                except ValueError as exc:
                    if not _regie_peut_attendre(str(exc)) or not c.get("programme_le"):
                        await db.carrousel_campagnes.update_one({"id": campagne_id, "statut": "EN_COURS"}, {"$set": {
                            "statut": "ANNULEE", "annule_le": _maintenant(), "annule_par": "Régie publicitaire",
                            "motif_arret": str(exc)[:300]}})
                        logger.info("[carrousel] campagne %s annulée au moment de l'envoi : %s", campagne_id, exc)
                        return
                    # Régie pas encore commencée / en pause : on réessaie dans une heure
                    reprise = datetime.now(timezone.utc) + timedelta(hours=1)
                    await db.carrousel_campagnes.update_one({"id": campagne_id, "statut": "EN_COURS"}, {"$set": {
                        "statut": "EN_ATTENTE", "reprise_le": reprise.isoformat(), "motif_arret": str(exc)[:300]}})
                    return
            comps = composants(c["expediteur"], c["message"], c["cartes"])
            for i, d in enumerate(c["destinataires"]):
                if d.get("statut") in STATUTS_DEST_SERVIS:
                    continue                                  # déjà servi : jamais renvoyé (reprise)
                # Annulation demandée entre deux envois (relue en base : vaut aussi d'un autre serveur)
                etat = await db.carrousel_campagnes.find_one({"id": campagne_id}, {"_id": 0, "statut": 1}) or {}
                if etat.get("statut") != "EN_COURS":
                    return
                # Plage horaire refermée : arrêt propre, reprise automatique à l'ouverture suivante
                ouverture = await _attente()
                if ouverture is not None:
                    await db.carrousel_campagnes.update_one({"id": campagne_id, "statut": "EN_COURS"}, {"$set": {
                        "statut": "EN_ATTENTE", "reprise_le": ouverture.isoformat()}})
                    logger.info("[carrousel] campagne %s hors plage : reprise le %s", campagne_id, ouverture.isoformat())
                    return
                try:
                    r = await wa_send_template(d["telephone"], c["modele"], c["langue"], comps,
                                               tenant_id=c.get("creds_tenant"))
                except Exception as exc:  # noqa: BLE001
                    r = {"ok": False, "status": None, "message_id": None, "error": str(exc)[:300]}
                statut = "ENVOYE" if r.get("ok") else "ECHEC"
                if statut == "ENVOYE" and c.get("regie_id"):
                    # Lot 111 — carrousel sponsorisé : envoi accepté par Meta = un envoi compté (et facturé au coût
                    # par envoi s'il y en a un), jamais bloquant pour la suite des envois
                    try:
                        await regie.enregistrer_envoi(db, c["regie_id"])
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[carrousel] comptage de l'envoi sponsorisé impossible : %s", exc)
                # Lot 114 — compteurs INCRÉMENTÉS (et non recalculés) : justes même après une reprise
                await db.carrousel_campagnes.update_one({"id": campagne_id}, {
                    "$set": {f"destinataires.{i}.statut": statut, f"destinataires.{i}.message_id": r.get("message_id"),
                             f"destinataires.{i}.erreur": (r.get("error") or None) and str(r["error"])[:300],
                             f"destinataires.{i}.envoye_le": _maintenant()},
                    "$inc": {"compte.envoyes": 1 if statut == "ENVOYE" else 0,
                             "compte.echecs": 1 if statut == "ECHEC" else 0}})
                await _prolonger_verrou(campagne_id)
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
            # Tous servis : terminée (sauf si annulée entre-temps)
            fin = await db.carrousel_campagnes.update_one({"id": campagne_id, "statut": "EN_COURS"}, {"$set": {
                "statut": "TERMINEE", "termine_le": _maintenant(), "reprise_le": None}})
            if getattr(fin, "modified_count", 0):
                await _prevenir_admin(campagne_id)      # lot 186 : compte rendu au numéro réglé (une seule fois par campagne)
        finally:
            # Verrou libéré dans tous les cas (fin, arrêt hors plage, annulation, erreur)
            await db.carrousel_campagnes.update_one({"id": campagne_id}, {"$set": {"verrou_jusqu_a": None}})

    # Tâches d'envoi lancées par CE serveur (évite de recréer une tâche déjà vivante)
    _taches: Dict[str, asyncio.Task] = {}

    def _lancer(campagne_id: str) -> None:
        """Lance _executer en tâche de fond (sans attendre) si elle ne tourne pas déjà ici."""
        t = _taches.get(campagne_id)
        if t is not None and not t.done():
            return
        _taches[campagne_id] = asyncio.create_task(_executer(campagne_id))
        _taches[campagne_id].add_done_callback(lambda _t, cid=campagne_id: _taches.pop(cid, None))

    async def lancer_echus(attendre: bool = False) -> int:
        """Lot 114 — appelé par le planificateur (toutes les minutes) :
          1. passe EN_COURS les campagnes PROGRAMMEE / EN_ATTENTE dont l'heure de reprise est arrivée ;
          2. relance les campagnes EN_COURS du lot 114 sans verrou vivant (serveur redémarré en plein envoi).
        `attendre=True` (tests) : les envois sont faits avant de rendre la main. Renvoie le nombre lancé."""
        maintenant = _maintenant()
        a_lancer: List[str] = []
        async for c in db.carrousel_campagnes.find(
                {"statut": {"$in": ["PROGRAMMEE", "EN_ATTENTE"]}, "reprise_le": {"$lte": maintenant}},
                {"_id": 0, "id": 1}):
            # Passage conditionnel : un seul serveur gagne si deux planificateurs tournent en même temps
            r = await db.carrousel_campagnes.update_one(
                {"id": c["id"], "statut": {"$in": ["PROGRAMMEE", "EN_ATTENTE"]}},
                {"$set": {"statut": "EN_COURS", "reprise_le": None, "repris_le": maintenant}})
            if r.modified_count:
                a_lancer.append(c["id"])
        async for c in db.carrousel_campagnes.find(
                {"statut": "EN_COURS", "reprenable": True,
                 "$or": [{"verrou_jusqu_a": None}, {"verrou_jusqu_a": {"$lt": maintenant}}]},
                {"_id": 0, "id": 1}):
            if c["id"] not in a_lancer:
                a_lancer.append(c["id"])
        for cid in a_lancer:
            if attendre:
                await _executer(cid)
            else:
                _lancer(cid)
        return len(a_lancer)

    async def _annuler(filtre: dict, user: dict) -> dict:
        """Lot 114 — annule une campagne programmée, en attente ou en cours (l'envoi en cours s'arrête avant
        le destinataire suivant : ceux déjà servis le restent)."""
        c = await db.carrousel_campagnes.find_one(filtre, {"_id": 0, "id": 1, "statut": 1})
        if not c:
            raise HTTPException(status_code=404, detail="Campagne introuvable")
        r = await db.carrousel_campagnes.update_one(
            {"id": c["id"], "statut": {"$in": STATUTS_ANNULABLES}},
            {"$set": {"statut": "ANNULEE", "annule_le": _maintenant(), "reprise_le": None,
                      "annule_par": user.get("full_name") or user.get("email") or user.get("id")}})
        if not r.modified_count:
            raise HTTPException(status_code=409, detail=f"Cet envoi est déjà {STATUTS_CAMPAGNE.get(c.get('statut'), 'terminé').lower()} : "
                                                        "il ne peut plus être annulé")
        logger.info("[carrousel] campagne %s annulée par %s", c["id"], user.get("email") or user.get("id"))
        return {"ok": True, "id": c["id"], "statut": "ANNULEE", "statut_libelle": STATUTS_CAMPAGNE["ANNULEE"]}

    async def _planificateur() -> None:
        """Boucle de fond : démarre les campagnes échues et reprend les interrompues, toutes les minutes."""
        while True:
            try:
                await lancer_echus()
            except Exception:  # noqa: BLE001 — une erreur ne doit jamais arrêter la boucle
                logger.warning("[carrousel] planificateur des envois programmés", exc_info=True)
            try:
                await executer_accords_echus()      # lot 167 : demandes d'accord programmées
            except Exception:  # noqa: BLE001
                logger.warning("[carrousel] planificateur des demandes d'accord", exc_info=True)
            await asyncio.sleep(PLANIFICATEUR_SECONDES)

    _planif: Dict[str, Any] = {}

    async def demarrer() -> None:
        """Lot 114 — au démarrage du serveur : lance le planificateur (qui reprend aussitôt les campagnes
        restées EN_COURS / EN_ATTENTE). Jamais dans la preview : sa base est une copie de la production."""
        if is_preview_env() or _planif.get("tache"):
            return
        _planif["tache"] = asyncio.create_task(_planificateur())

    async def _campagnes(filtre: dict) -> List[dict]:
        lignes = await db.carrousel_campagnes.find(filtre, {"_id": 0, "destinataires": 0}).sort(
            "cree_le", -1).limit(50).to_list(50)
        noms_regie = {b["id"]: b.get("name") or "" async for b in db.ad_banners.find(
            {"id": {"$in": [c.get("regie_id") for c in lignes if c.get("regie_id")]}}, {"_id": 0, "id": 1, "name": 1})}
        base = (base_publique() or "").rstrip("/")
        for c in lignes:
            codes = [x.get("code_lien") for x in c.get("cartes") or []]
            # Lot 111 — par carte : clics, clics facturés (sponsorisé), vues de la présentation, « Je suis intéressé »
            stats = {x["code"]: x async for x in db.carrousel_liens.find(
                {"code": {"$in": codes}}, {"_id": 0, "code": 1, "clics": 1, "clics_factures": 1, "vues": 1, "interesses": 1})}
            for x in c.get("cartes") or []:
                s = stats.get(x.get("code_lien")) or {}
                x["clics"] = int(s.get("clics") or 0)
                x["clics_factures"] = int(s.get("clics_factures") or 0)
                x["vues"] = int(s.get("vues") or 0)
                x["interesses"] = int(s.get("interesses") or 0)
            c["regie_nom"] = noms_regie.get(c.get("regie_id"), "")
            # Lot 114 — libellé français du statut (pastille) et possibilité d'annuler
            c["statut_libelle"] = STATUTS_CAMPAGNE.get(c.get("statut"), c.get("statut") or "")
            c["annulable"] = c.get("statut") in STATUTS_ANNULABLES
            c.pop("verrou_jusqu_a", None)
            c["url_presentation"] = f"{base}{regie.CHEMIN_PRESENTATION_CAMPAGNE}{c['id_public']}" if c.get("id_public") else ""
        return lignes

    async def _campagne(filtre: dict) -> dict:
        c = await db.carrousel_campagnes.find_one(filtre, {"_id": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Campagne introuvable")
        # Lot 152 — « ENVOYE » = accepté par WhatsApp ; la remise réelle (remis / lu / NON REMIS + motif) arrive plus tard
        # par les accusés de WhatsApp et est lue dans whatsapp_messages : on l'ajoute à chaque destinataire.
        suivi = {m["message_id"]: m async for m in db.whatsapp_messages.find(
            {"carrousel_id": c["id"]}, {"_id": 0, "message_id": 1, "wa_status": 1, "wa_error_code": 1, "wa_error_message": 1})
            if m.get("message_id")}
        resume = {"remis": 0, "lus": 0, "non_remis": 0, "en_attente": 0}
        for d in c.get("destinataires") or []:
            if d.get("statut") != "ENVOYE":
                continue
            m = suivi.get(d.get("message_id")) or {}
            etat = m.get("wa_status") or "sent"            # sent | delivered | read | failed
            d["livraison"] = etat
            if etat == "failed":
                d["livraison_erreur"] = " — ".join(str(x) for x in (m.get("wa_error_code"), m.get("wa_error_message")) if x) or None
                resume["non_remis"] += 1
            elif etat == "read":
                resume["lus"] += 1
            elif etat == "delivered":
                resume["remis"] += 1
            else:
                resume["en_attente"] += 1
        c["livraison"] = resume
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
    async def ouvrir_lien(code: str, request: Request):
        """Anciens liens (avant le lot 117) : compte le clic et redirige (302)."""
        return RedirectResponse(await _destination(code, request), status_code=302)

    @api.get("/public/carrousel/destination/{code}", tags=["Public"])
    async def destination_lien(code: str, request: Request):
        """Lot 117 — adresse du bouton = page du SITE « /l/<code> » (aucune redirection côté serveur, exigence
        de Meta pour valider le modèle) ; cette page demande ici l'adresse finale, le clic est compté ici."""
        return {"url": await _destination(code, request)}

    async def _destination(code: str, request: Request) -> str:
        """Compte le clic (et le facture à la régie) puis renvoie l'adresse finale de la carte."""
        code = code[:40]
        # Clic BRUT compté sur la carte (toujours, même hors budget ou en double)
        doc = await db.carrousel_liens.find_one_and_update(
            {"code": code}, {"$inc": {"clics": 1}},
            projection={"_id": 0, "cible": 1, "campagne_id": 1, "carte_index": 1, "bouton": 1})
        if not doc:
            return (base_publique() or "").rstrip("/") + "/"
        campagne = await db.carrousel_campagnes.find_one(
            {"id": doc.get("campagne_id")}, {"_id": 0, "id": 1, "id_public": 1, "regie_id": 1}) or {}
        index = int(doc.get("carte_index") or 0)
        # Lot 111 — carrousel sponsorisé : clic facturé à la régie (dédupliqué par appareil, dans le budget)
        if campagne.get("regie_id"):
            try:
                await regie.enregistrer_clic(db, campagne_id=campagne["id"], carte_index=index,
                                             regie_id=campagne["regie_id"], emp=regie.empreinte_requete(request))
            except Exception as exc:  # noqa: BLE001 — la facturation ne bloque jamais l'ouverture du lien
                logger.warning("[carrousel] facturation du clic impossible : %s", exc)
        if doc.get("bouton") == "presentation" or doit_presenter(doc.get("cible")):
            base = (base_publique() or "").rstrip("/")
            # Lot 111 — page de TOUT le carrousel, positionnée sur la carte (#carte-n, appliqué par le navigateur)
            id_public = campagne.get("id_public") or (await regie.assurer_id_public(db, doc.get("campagne_id")) if campagne else None)
            if id_public:
                return f"{base}{regie.chemin_presentation(id_public, code, index + 1)}"
            # Lot 94 — repli : page d'une seule carte
            return f"{base}{CHEMIN_PRESENTATION}{code}"
        return doc["cible"]

    @api.get("/public/carrousel/carte/{code}", tags=["Public"])
    async def carte_publique(code: str):
        """Lot 94 — contenu d'une carte pour la page de présentation du site : photo, titre, texte,
        expéditeur et, pour un produit, son nom, son prix et sa description (aucune donnée personnelle)."""
        lien = await db.carrousel_liens.find_one({"code": code[:40]}, {"_id": 0, "campagne_id": 1, "carte_index": 1})
        campagne = await db.carrousel_campagnes.find_one(
            {"id": (lien or {}).get("campagne_id")}, {"_id": 0, "cartes": 1, "expediteur": 1, "perimetre": 1}) if lien else None
        cartes = (campagne or {}).get("cartes") or []
        i = int((lien or {}).get("carte_index") or 0)
        if not campagne or i >= len(cartes):
            raise HTTPException(status_code=404, detail="Carte introuvable")
        c = cartes[i]
        produit = None
        if c.get("produit_id"):
            p = await db.products.find_one({"id": c["produit_id"]}, {"_id": 0, "name": 1, "description": 1,
                                                                     "unit_price_ht": 1, "unit": 1})
            if p:
                produit = {"nom": p.get("name") or "", "description": (p.get("description") or "")[:2000],
                           "prix": prix_affiche(p.get("unit_price_ht")) if p.get("unit_price_ht") else "",
                           "unite": p.get("unit") or ""}
        # Lot 111 — l'ancienne page /presentation/{code} redirige vers la page du carrousel, sur cette carte
        id_public = await regie.assurer_id_public(db, lien["campagne_id"])
        return {"code": code[:40], "titre": c.get("titre") or "", "texte": c.get("texte") or "",
                "image_url": c.get("image_url") or "", "expediteur": campagne.get("expediteur") or "",
                "plateforme": campagne.get("perimetre") == "admin", "produit": produit,
                "id_public": id_public, "n": i + 1}

    async def _produit_public(produit_id: Optional[str]) -> Optional[dict]:
        """Lot 111 — nom, prix, unité et description publique d'un produit de la caisse (ou None)."""
        if not produit_id:
            return None
        p = await db.products.find_one({"id": produit_id}, {"_id": 0, "name": 1, "description": 1,
                                                             "unit_price_ht": 1, "unit": 1})
        if not p:
            return None
        return {"nom": p.get("name") or "", "description": (p.get("description") or "")[:2000],
                "prix": prix_affiche(p.get("unit_price_ht")) if p.get("unit_price_ht") else "",
                "unite": p.get("unit") or ""}

    async def _contact_whatsapp(campagne: dict) -> str:
        """Lot 111 — numéro WhatsApp de contact de l'expéditeur (chiffres avec indicatif) pour « Je suis
        intéressé » : celui du client pour un carrousel du portail, celui de l'entreprise (Paramètres,
        company_whatsapp) pour un carrousel de SAWALI. Vide s'il n'est pas connu."""
        brut = ""
        if campagne.get("perimetre") == "client" and campagne.get("tenant_id"):
            u = await db.users.find_one({"id": campagne["tenant_id"]}, {"_id": 0, "whatsapp_number": 1, "phone": 1}) or {}
            brut = u.get("whatsapp_number") or u.get("phone") or ""
        if not brut:
            s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "company_whatsapp": 1}) or {}
            brut = (s.get("company_whatsapp") or "") if campagne.get("perimetre") == "admin" else ""
        tel = numero_whatsapp(brut) if brut else ""
        return tel if len(tel) >= 10 else ""

    @api.get("/public/carrousel/presentation/{id_public}", tags=["Public"])
    async def presentation_publique(id_public: str):
        """Lot 111 — page de présentation d'un carrousel : toutes ses cartes (photo, titre, texte, description
        détaillée, produit), l'expéditeur et son numéro WhatsApp de contact. AUCUNE donnée de destinataire :
        la lecture se limite aux champs listés ici (jamais la liste des destinataires ni leurs numéros)."""
        campagne = await db.carrousel_campagnes.find_one(
            {"id_public": id_public[:40]},
            {"_id": 0, "id": 1, "id_public": 1, "expediteur": 1, "message": 1, "cartes": 1, "perimetre": 1,
             "tenant_id": 1, "cree_le": 1})
        if not campagne:
            raise HTTPException(status_code=404, detail="Présentation introuvable")
        cartes = []
        for i, c in enumerate(campagne.get("cartes") or []):
            lien = (c.get("lien") or "").strip()
            cartes.append({
                "n": i + 1, "titre": c.get("titre") or "", "texte": c.get("texte") or "",
                "image_url": c.get("image_url") or "",
                "description_detaillee": (c.get("description_detaillee") or "")[:DESCRIPTION_MAX],
                "produit": await _produit_public(c.get("produit_id")),
                # Lien personnalisé saisi (affiché comme « En savoir plus ») ; jamais l'ancien lien automatique
                "lien": lien if lien and lien_accepte(lien) and not doit_presenter(lien) else "",
            })
        return {"id": campagne["id_public"], "expediteur": campagne.get("expediteur") or "",
                "message": campagne.get("message") or "", "plateforme": campagne.get("perimetre") == "admin",
                "contact_whatsapp": await _contact_whatsapp(campagne), "date": campagne.get("cree_le"),
                "cartes": cartes}

    @api.post("/public/carrousel/evenement", tags=["Public"])
    async def evenement_public(data: EvenementIn, request: Request):
        """Lot 111 — « vue » ou « Je suis intéressé » sur une carte de la page de présentation. Dédupliqué par
        empreinte (IP + navigateur) sur 24 h : un même appareil n'est compté qu'une fois par carte et par type."""
        filtre = None
        if data.campagne:
            filtre = {"id_public": data.campagne[:40]}
        elif data.code:
            lien = await db.carrousel_liens.find_one({"code": data.code[:40]}, {"_id": 0, "campagne_id": 1})
            filtre = {"id": lien["campagne_id"]} if lien else None
        campagne = await db.carrousel_campagnes.find_one(
            filtre, {"_id": 0, "id": 1, "regie_id": 1, "cartes": 1}) if filtre else None
        if not campagne:
            raise HTTPException(status_code=404, detail="Présentation introuvable")
        if data.carte > len(campagne.get("cartes") or []):
            raise HTTPException(status_code=400, detail="Carte inexistante")
        compte = await regie.enregistrer_evenement(db, campagne=campagne, carte_index=data.carte - 1,
                                                   type_evt=data.type, emp=regie.empreinte_requete(request))
        return {"ok": True, "compte": compte}

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

    @api.post("/me/whatsapp/carrousel/liens-accord", tags=["Portail Client — Carrousel WhatsApp"])
    async def liens_accord_portail(data: DemandeAccordIn, user: dict = Depends(utilisateur)):
        """Lot 164 — liens d'accord personnels (page SAWALI) des contacts demandés, parmi ceux que l'utilisateur voit."""
        voulus = set(data.ids)
        return {"liens": _liens_accord([c for c in (await _contacts_portail(user))["contacts"] if c["id"] in voulus])}

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
        """Campagnes du client + (lot 168) celles que l'administration SAWALI a lancées avec les contacts de sa société :
        le superviseur en voit le statut, sans pouvoir les annuler."""
        ids = await _societes_visibles(await visible_client_ids(user))
        lignes = await _campagnes({"$or": [{"perimetre": "client", "tenant_id": _tenant_id(user)},
                                           {"perimetre": "admin", "societe_id": {"$in": ids}}]})
        for c in lignes:
            if c.get("perimetre") == "admin":
                c["annulable"] = False                       # lancée par l'administration : elle seule peut l'annuler
        return {"campagnes": lignes}

    @api.get("/me/whatsapp/carrousel/campagnes/{cid}", tags=["Portail Client — Carrousel WhatsApp"])
    async def campagne_portail(cid: str, user: dict = Depends(utilisateur)):
        ids = await _societes_visibles(await visible_client_ids(user))
        return await _campagne({"id": cid, "$or": [{"perimetre": "client", "tenant_id": _tenant_id(user)},
                                                   {"perimetre": "admin", "societe_id": {"$in": ids}}]})

    @api.get("/me/whatsapp/carrousel/demandes-accord", tags=["Portail Client — Carrousel WhatsApp"])
    async def demandes_accord_portail(user: dict = Depends(utilisateur)):
        """Lot 168 — statut des demandes d'autorisation (modèle d'accord) lancées ou programmées par l'administration
        SAWALI pour les contacts de la société de l'utilisateur. Lecture seule."""
        ids = set(await _societes_visibles(await visible_client_ids(user)))
        items = [i for i in await _items_prog() if i.get("societe_id") in ids]
        items.sort(key=lambda i: i.get("programme_le") or "", reverse=True)
        return {"demandes": [_vue_prog(i) for i in items]}

    @api.post("/me/whatsapp/carrousel/campagnes/{cid}/annuler", tags=["Portail Client — Carrousel WhatsApp"])
    async def annuler_portail(cid: str, user: dict = Depends(utilisateur)):
        """Lot 114 — annule un envoi programmé, en attente ou en cours : seulement les campagnes du client."""
        return await _annuler({"id": cid, "perimetre": "client", "tenant_id": _tenant_id(user)}, user)

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
        # Lot 117.1 — une série de carrousel APPROUVÉE existe déjà (autre nom) : on ne dépose rien, on propose de la
        # réutiliser (Meta refuse une série qui recopie ses textes). « forcer » permet de déposer quand même.
        if not data.forcer:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=20) as http:
                    rep = await http.get(f"https://graph.facebook.com/{version}/{waba}/message_templates",
                                         params={"fields": "name,status,language,components", "limit": 250},
                                         headers={"Authorization": f"Bearer {jeton}"})
                series = (series_carrousel_approuvees((rep.json() or {}).get("data") or [], data.langue, sauf=data.modele)
                          if rep.status_code < 300 else {})
            except Exception:  # noqa: BLE001 — Meta muet : on ne bloque pas le dépôt
                series = {}
            if series:
                meilleure = max(series, key=lambda p: series[p])
                raise HTTPException(status_code=409, detail={
                    "message": (f"Une série de carrousel est déjà approuvée par Meta : « {meilleure} » "
                                f"({series[meilleure]} modèle(s)). Réutilisez-la : une nouvelle série aux mêmes textes "
                                "serait refusée (« format non conforme »)."),
                    "serie_approuvee": meilleure, "series": series})
        try:
            resultats = await cmm.creer_modeles(version=version, app_id=app_id, waba_id=waba, jeton=jeton,
                                                prefixe=data.modele, langue=data.langue, url_bouton=_url_bouton())
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if any(r["statut"] in ("soumis", "existe déjà") for r in resultats):
            await ecrire_reglages(data, _)          # préfixe et langue retenus pour les envois
        _cache_statuts.clear()                      # lot 77 : les pastilles relisent Meta
        return {"resultats": resultats, "url_bouton": _url_bouton()}

    async def _acces_meta() -> dict:
        """Lot 165 — jeton, WABA et version de l'API du compte WhatsApp Business de la plateforme."""
        creds = await resolve_wa_credentials(None)
        jeton, waba = (creds.get("access_token") or "").strip(), (creds.get("waba_id") or "").strip()
        if not jeton or not waba:
            raise HTTPException(status_code=400, detail="WhatsApp Business incomplet : jeton d'accès ou identifiant du compte "
                                                        "WhatsApp Business (WABA) manquant dans les Paramètres.")
        return {"jeton": jeton, "waba": waba, "version": await _version_graph()}

    def _url_bouton_accord() -> str:
        from routes import accord_page as ap
        return f"{base_publique().rstrip('/')}{ap.CHEMIN_PAGE}{{{{1}}}}"

    # --- Lot 204 : accords sans fiche (numéro changé ?) → fiche rattachée à un client, accord noté, carrousel envoyé ---
    @api.get("/admin/whatsapp/carrousel/accords-orphelins", tags=["Admin — Carrousel WhatsApp"])
    async def accords_orphelins(_: dict = Depends(get_current_admin)):
        """Personnes qui ont accepté (bouton, mot-clé) mais dont le numéro ne figure sur aucune fiche, la liste des clients
        où les rattacher et les derniers carrousels terminés (à leur envoyer)."""
        from routes import carrousel_accords_orphelins as ao
        comptes = await db.users.find(_filtre_clients(), {"_id": 0, "id": 1, "company": 1, "full_name": 1, "email": 1,
                                                          "client_code": 1}).to_list(3000)
        clients = sorted(({"id": c["id"], "nom": c.get("company") or c.get("full_name") or c.get("email") or "",
                           "code": c.get("client_code") or ""} for c in comptes), key=lambda x: x["nom"].lower())
        campagnes = [{"id": c["id"], "libelle": (c.get("message") or "")[:80], "cree_le": c.get("cree_le"),
                      "total": (c.get("compte") or {}).get("total", 0)}
                     async for c in db.carrousel_campagnes.find({"perimetre": "admin", "statut": "TERMINEE"},
                                                                 {"_id": 0, "id": 1, "message": 1, "cree_le": 1, "compte": 1})
                     .sort("cree_le", -1).limit(10)]
        return {"orphelins": await ao.lister(db), "clients": clients, "campagnes": campagnes}

    @api.post("/admin/whatsapp/carrousel/accords-orphelins/rattacher", tags=["Admin — Carrousel WhatsApp"])
    async def rattacher_orphelins(data: RattacherIn, user: dict = Depends(get_current_admin)):
        """1) fiche contact rattachée au client choisi, 2) accord repris tel qu'il a été donné (date et moyen d'origine),
        3) si `campagne_id` : les personnes sont ajoutées à cette campagne terminée, qui repart pour elles SEULES
        (les destinataires déjà servis ne sont jamais renvoyés)."""
        from routes import carrousel_accords_orphelins as ao
        comptes = await db.users.find(_filtre_clients(), {"_id": 0, "id": 1, "company": 1, "full_name": 1, "email": 1}).to_list(3000)
        valides = {c["id"]: c.get("company") or c.get("full_name") or c.get("email") or "" for c in comptes}
        par = user.get("full_name") or user.get("email") or "administrateur"
        res = await ao.rattacher(db, [i.model_dump() for i in data.items], valides, par)
        envoi = None
        if data.campagne_id and res["crees"]:
            nouveaux = [{"id": c["id"], "nom": c["nom"], "telephone": numero_whatsapp(c["telephone"]), "statut": "EN_ATTENTE"}
                        for c in res["crees"] if len(numero_whatsapp(c["telephone"])) >= 10]
            r = await db.carrousel_campagnes.update_one(
                {"id": data.campagne_id, "perimetre": "admin", "statut": "TERMINEE"},
                {"$push": {"destinataires": {"$each": nouveaux}}, "$inc": {"compte.total": len(nouveaux)},
                 "$set": {"statut": "EN_COURS", "termine_le": None, "complement_le": _maintenant(), "reprenable": True}})
            if r.modified_count:
                _lancer(data.campagne_id)
                envoi = {"campagne_id": data.campagne_id, "destinataires": len(nouveaux)}
            else:
                envoi = {"campagne_id": data.campagne_id, "destinataires": 0,
                         "erreur": "Cette campagne n'est plus terminée : choisissez-en une autre"}
        logger.info("[carrousel] %d accord(s) orphelin(s) rattaché(s) par %s ; envoi : %s", len(res["crees"]), par, envoi)
        return {**res, "envoi": envoi}

    @api.get("/admin/whatsapp/carrousel/accord-modele", tags=["Admin — Carrousel WhatsApp"])
    async def lire_accord_modele(_: dict = Depends(get_current_admin)):
        """Lot 165 — modèle d'accord à lien personnel : nom retenu, statut actuel chez Meta et motif d'un refus."""
        from routes import accord_modele_meta as amm
        g = await db.settings.find_one({"_id": "global"}, {"_id": 0, "wa_accord_modele": 1, "wa_accord_modele_langue": 1}) or {}
        nom, langue = g.get("wa_accord_modele") or amm.NOM_DEFAUT, g.get("wa_accord_modele_langue") or LANGUE_DEFAUT
        acces = await _acces_meta()
        return {"modele": nom, "langue": langue, "enregistre": bool(g.get("wa_accord_modele")),
                "url_bouton": _url_bouton_accord(),
                **(await amm.lire_statut(version=acces["version"], waba_id=acces["waba"], jeton=acces["jeton"],
                                         nom=nom, langue=langue))}

    @api.post("/admin/whatsapp/carrousel/accord-modele", tags=["Admin — Carrousel WhatsApp"])
    async def creer_accord_modele(data: AccordModeleIn, _: dict = Depends(get_current_admin)):
        """Lot 165 — dépose chez Meta le modèle de demande d'accord (bouton → <site>/accord/{{1}}). Aucun message n'est
        envoyé aux contacts ; l'approbation par Meta prend de quelques minutes à 24 h."""
        from routes import accord_modele_meta as amm
        acces = await _acces_meta()
        resultat = await amm.creer_modele(version=acces["version"], waba_id=acces["waba"], jeton=acces["jeton"],
                                          nom=data.modele, langue=data.langue, url_bouton=_url_bouton_accord())
        if resultat["statut"] in ("soumis", "existe déjà"):
            await db.settings.update_one({"_id": "global"}, {"$set": {
                "wa_accord_modele": data.modele, "wa_accord_modele_langue": data.langue}}, upsert=True)
        return {**resultat, "url_bouton": _url_bouton_accord()}

    async def _executer_demande_accord(ids: List[str], user: dict, societe_id: Optional[str] = None) -> dict:
        """Lot 166 — envoie le modèle de demande d'accord (bouton → page /accord/<jeton>) aux personnes `ids`, chacune
        avec SON lien personnel (plus de saisie un à un). Lot 167 : appelée tout de suite OU à l'heure programmée
        (les garde-fous sont alors réévalués AU MOMENT de l'envoi). Garde-fous :
          - jamais à quelqu'un qui a déjà accepté, ni à quelqu'un qui a REFUSÉ (STOP / « NON ») ;
          - jamais deux demandes à la même personne en 7 jours ;
          - le modèle doit être APPROUVÉ par Meta ; au plus DESTINATAIRES_MAX personnes par envoi ;
          - c'est un message Marketing facturé par Meta : l'écran demande confirmation avant l'envoi."""
        from routes import accord_modele_meta as amm, accord_page as ap
        if len(ids) > DESTINATAIRES_MAX:
            raise HTTPException(status_code=400, detail=f"{DESTINATAIRES_MAX} personnes au plus par envoi")
        g = await db.settings.find_one({"_id": "global"}, {"_id": 0, "wa_accord_modele": 1, "wa_accord_modele_langue": 1}) or {}
        nom_accord = g.get("wa_accord_modele")
        if not nom_accord:
            raise HTTPException(status_code=409, detail="Créez d'abord le modèle d'accord chez Meta (Modèles Meta).")
        langue = g.get("wa_accord_modele_langue") or LANGUE_DEFAUT
        acces = await _acces_meta()
        etat = await amm.lire_statut(version=acces["version"], waba_id=acces["waba"], jeton=acces["jeton"],
                                     nom=nom_accord, langue=langue)
        if etat["statut"] != "APPROVED":
            raise HTTPException(status_code=409, detail=f"Le modèle « {nom_accord} » n'est pas encore approuvé par Meta "
                                                        f"(statut : {etat['statut']}).")
        voulus = set(ids)
        personnes = [c for c in (await _clients_admin(user, societe_id))["contacts"] if c["id"] in voulus]
        # État réel du consentement et dernière demande : « refusé » (False) se distingue de « jamais demandé » (None)
        etats: Dict[str, dict] = {}
        for coll in ("directory_contacts", "tracked_users", "users"):
            async for d in db[coll].find({"id": {"$in": list(voulus)}},
                                         {"_id": 0, "id": 1, "accepte_whatsapp": 1, "accord_demande_le": 1}):
                etats.setdefault(d["id"], d)
        limite = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        ignores = {"deja_accepte": 0, "refus": 0, "demande_recente": 0, "sans_numero": 0}
        a_envoyer: List[dict] = []
        for p in personnes:
            e = etats.get(p["id"], {})
            if len(numero_whatsapp(p.get("telephone"))) < 10:
                ignores["sans_numero"] += 1
            elif e.get("accepte_whatsapp") is True:
                ignores["deja_accepte"] += 1
            elif e.get("accepte_whatsapp") is False:
                ignores["refus"] += 1                      # la personne a dit non : on ne la sollicite plus
            elif (e.get("accord_demande_le") or "") > limite:
                ignores["demande_recente"] += 1
            else:
                a_envoyer.append(p)
        envoyees, echecs = 0, []
        verrou = asyncio.Semaphore(5)

        async def _envoyer_un(p: dict) -> None:
            nonlocal envoyees
            prenom = ((p.get("nom") or "").split() or ["cher contact"])[0][:30]
            comps = [{"type": "body", "parameters": [{"type": "text", "text": prenom}]},
                     {"type": "button", "sub_type": "url", "index": "0",
                      "parameters": [{"type": "text", "text": ap.creer_jeton(p["id"])}]},
                     # bouton « NON » : l'identifiant revient au webhook, qui note le refus
                     {"type": "button", "sub_type": "quick_reply", "index": "1",
                      "parameters": [{"type": "payload", "payload": amm.PAYLOAD_NON}]}]
            async with verrou:
                try:
                    r = await wa_send_template(p["telephone"], nom_accord, langue, comps, tenant_id=None)
                except Exception as exc:  # noqa: BLE001
                    r = {"ok": False, "error": str(exc)[:200]}
            if r.get("ok"):
                envoyees += 1
                maintenant = _maintenant()
                for coll in ("directory_contacts", "tracked_users", "users"):
                    await db[coll].update_one({"id": p["id"]}, {"$set": {"accord_demande_le": maintenant}})
            else:
                echecs.append({"nom": p.get("nom") or p["telephone"],
                               "erreur": str(r.get("error") or r.get("message") or "refusé")[:160]})

        try:
            await asyncio.gather(*[_envoyer_un(p) for p in a_envoyer])
        except RuntimeError as exc:                        # JWT_SECRET absent : aucun jeton possible
            raise HTTPException(status_code=503, detail="Secret de signature des liens absent (JWT_SECRET) : envoi impossible") from exc
        return {"envoyees": envoyees, "echecs": echecs[:20], "nb_echecs": len(echecs), "ignores": ignores,
                "modele": nom_accord}

    # --- Lot 167 : demande d'accord PROGRAMMÉE (« demain 8 h 30 ») ---------------------------------------------
    # Les envois programmés sont gardés dans UN document de `settings` (aucune nouvelle collection : le cluster est
    # plein) : {_id: "accord_programmations", items: [{id, ids, programme_le (UTC), statut, utilisateur, ...}]}.
    # Statuts : PROGRAMMEE → EN_COURS → TERMINEE | ECHEC, ou ANNULEE. Le planificateur (toutes les minutes) les lance.
    DOC_PROG = {"_id": "accord_programmations"}
    PROG_MAX = 50                                       # envois gardés dans le document (les plus récents)

    async def _items_prog() -> List[dict]:
        return list((await db.settings.find_one(DOC_PROG, {"_id": 0, "items": 1}) or {}).get("items") or [])

    async def _ecrire_items(items: List[dict]) -> None:
        await db.settings.replace_one(DOC_PROG, {**DOC_PROG, "items": items[-PROG_MAX:]}, upsert=True)

    def _vue_prog(it: dict) -> dict:
        """Ce que l'écran voit : sans la liste d'identifiants ni l'utilisateur interne."""
        return {k: it.get(k) for k in ("id", "programme_le", "statut", "nb", "cree_le", "cree_par", "termine_le", "resultat",
                                       "motif", "societe_id")}

    async def executer_accords_echus() -> int:
        """Lot 167 — lance les demandes d'accord dont l'heure est arrivée (appelée par le planificateur chaque minute).
        Hors plage horaire d'envoi (Paramètres) : attend l'ouverture. Une demande restée EN_COURS plus de 15 minutes
        (serveur redémarré en plein envoi) repasse PROGRAMMEE : les garde-fous « pas deux fois en 7 jours » évitent
        tout doublon. Renvoie le nombre lancé."""
        items = await _items_prog()
        if not items:
            return 0
        maintenant = _maintenant()
        change = False
        for it in items:
            if it.get("statut") == "EN_COURS" and (it.get("demarre_le") or "") < (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat():
                it["statut"], change = "PROGRAMMEE", True
        if change:
            await _ecrire_items(items)
        echus = [it for it in items if it.get("statut") == "PROGRAMMEE" and (it.get("programme_le") or "") <= maintenant]
        if not echus or await _attente() is not None:
            return 0
        lances = 0
        for it in echus:
            # Passage conditionnel : un seul serveur gagne si deux planificateurs tournent en même temps
            r = await db.settings.update_one({**DOC_PROG, "items": {"$elemMatch": {"id": it["id"], "statut": "PROGRAMMEE"}}},
                                             {"$set": {"items.$.statut": "EN_COURS", "items.$.demarre_le": _maintenant()}})
            if not r.modified_count:
                continue
            lances += 1
            fin: Dict[str, Any] = {}
            try:
                res = await _executer_demande_accord(it["ids"], it.get("utilisateur") or {}, it.get("societe_id"))
                fin = {"statut": "TERMINEE", "resultat": {"envoyees": res["envoyees"], "nb_echecs": res["nb_echecs"],
                                                          "ignores": res["ignores"]}}
            except HTTPException as exc:                     # ex. modèle pas (ou plus) approuvé : rien n'est envoyé
                fin = {"statut": "ECHEC", "motif": str(exc.detail)[:300]}
            except Exception as exc:  # noqa: BLE001
                logger.warning("[accord] demande programmée en échec", exc_info=True)
                fin = {"statut": "ECHEC", "motif": f"Erreur : {type(exc).__name__}"}
            await db.settings.update_one({**DOC_PROG, "items": {"$elemMatch": {"id": it["id"]}}},
                                         {"$set": {**{f"items.$.{k}": v for k, v in fin.items()}, "items.$.termine_le": _maintenant()}})
        return lances

    @api.post("/admin/whatsapp/carrousel/demande-accord-modele", tags=["Admin — Carrousel WhatsApp"])
    async def demande_accord_modele(data: DemandeAccordModeleIn, user: dict = Depends(get_current_admin)):
        """Lot 166 — envoie en UN clic le modèle de demande d'accord, chacune avec SON lien personnel.
        Lot 167 — `programme_le` (« 2026-10-15T08:30 », heure de Ouagadougou) : la demande est PROGRAMMÉE et partira
        toute seule à cette heure (date passée refusée) ; sinon elle part tout de suite."""
        quand = await _programme(data.programme_le)
        if quand is None:
            return await _executer_demande_accord(data.ids, user, data.societe_id)
        # Contrôles faits maintenant (message clair tout de suite) ; les garde-fous sont refaits à l'heure dite
        if len(data.ids) > DESTINATAIRES_MAX:
            raise HTTPException(status_code=400, detail=f"{DESTINATAIRES_MAX} personnes au plus par envoi")
        g = await db.settings.find_one({"_id": "global"}, {"_id": 0, "wa_accord_modele": 1}) or {}
        if not g.get("wa_accord_modele"):
            raise HTTPException(status_code=409, detail="Créez d'abord le modèle d'accord chez Meta (Modèles Meta).")
        items = await _items_prog()
        item = {"id": uuid.uuid4().hex, "ids": list(dict.fromkeys(data.ids)), "nb": len(set(data.ids)),
                "societe_id": (data.societe_id or "").strip() or None,        # lot 168 : visible du superviseur de la société
                "programme_le": quand.isoformat(), "statut": "PROGRAMMEE", "cree_le": _maintenant(),
                "cree_par": user.get("full_name") or user.get("email") or user.get("id"),
                "utilisateur": {"id": user.get("id"), "client_id": user.get("client_id")}}
        await _ecrire_items(items + [item])
        return {"programmee": True, **_vue_prog(item)}

    @api.get("/admin/whatsapp/carrousel/demande-accord-modele/programmations", tags=["Admin — Carrousel WhatsApp"])
    async def programmations_accord(_: dict = Depends(get_current_admin)):
        """Lot 167 — demandes d'accord programmées ou récentes (les plus proches en premier)."""
        items = sorted(await _items_prog(), key=lambda i: i.get("programme_le") or "", reverse=True)
        return {"programmations": [_vue_prog(i) for i in items]}

    @api.post("/admin/whatsapp/carrousel/demande-accord-modele/programmations/{pid}/annuler", tags=["Admin — Carrousel WhatsApp"])
    async def annuler_programmation_accord(pid: str, _: dict = Depends(get_current_admin)):
        """Lot 167 — annule une demande d'accord programmée (seulement tant qu'elle n'est pas partie)."""
        r = await db.settings.update_one({**DOC_PROG, "items": {"$elemMatch": {"id": pid, "statut": "PROGRAMMEE"}}},
                                         {"$set": {"items.$.statut": "ANNULEE", "items.$.termine_le": _maintenant()}})
        if not r.modified_count:
            raise HTTPException(status_code=409, detail="Cette demande est introuvable ou déjà partie : elle ne peut plus être annulée")
        return {"ok": True, "id": pid, "statut": "ANNULEE"}

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
        personnes = [c for c in (await _clients_admin(user, data.societe_id))["contacts"] if c["id"] in voulus]
        return await _demander_accord(personnes, None)

    @api.post("/admin/whatsapp/carrousel/liens-accord", tags=["Admin — Carrousel WhatsApp"])
    async def liens_accord_admin(data: DemandeAccordIn, user: dict = Depends(get_current_admin)):
        """Lot 164 — liens d'accord personnels (page SAWALI) des clients demandés."""
        voulus = set(data.ids)
        return {"liens": _liens_accord([c for c in (await _clients_admin(user, data.societe_id))["contacts"] if c["id"] in voulus])}

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
    async def destinataires_admin(societe: Optional[str] = None, user: dict = Depends(get_current_admin)):
        """Lot 168 — `?societe=<id>` : contacts, suivis et groupes de cette société (sinon « mes contacts » et clients)."""
        return await _clients_admin(user, (societe or "").strip() or None)

    @api.get("/admin/whatsapp/carrousel/societes", tags=["Admin — Carrousel WhatsApp"])
    async def societes_admin(_: dict = Depends(get_current_admin)):
        """Lot 168 — sociétés dont l'administration peut utiliser les groupes de contacts, avec leurs effectifs."""
        return {"societes": await _societes_admin()}

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
        annuaire = await _clients_admin(user, (envoi.societe_id or "").strip() or None)
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

    @api.post("/admin/whatsapp/carrousel/campagnes/{cid}/annuler", tags=["Admin — Carrousel WhatsApp"])
    async def annuler_admin(cid: str, user: dict = Depends(get_current_admin)):
        """Lot 114 — l'administration peut annuler TOUTE campagne (la sienne ou celle d'un client)."""
        return await _annuler({"id": cid}, user)

    @api.get("/admin/whatsapp/carrousel/programmation/etat", tags=["Admin — Carrousel WhatsApp"])
    async def etat_programmation_admin(_: dict = Depends(get_current_admin)):
        """Lot 114 — état pour la rubrique « Plages horaires d'envoi » des Paramètres : nombre de campagnes de
        carrousel par statut (toutes, portail et administration) et prochaine reprise prévue."""
        compte = {k: await db.carrousel_campagnes.count_documents({"statut": k}) for k in STATUTS_ANNULABLES}
        prochaine = await db.carrousel_campagnes.find(
            {"statut": {"$in": ["PROGRAMMEE", "EN_ATTENTE"]}, "reprise_le": {"$ne": None}},
            {"_id": 0, "reprise_le": 1}).sort("reprise_le", 1).limit(1).to_list(1)
        ouverture = await _attente()
        return {"programmees": compte["PROGRAMMEE"], "en_attente": compte["EN_ATTENTE"], "en_cours": compte["EN_COURS"],
                "prochaine_reprise": prochaine[0]["reprise_le"] if prochaine else None,
                "plages_actives": plages is not None and bool((await plages["config"]()).get("actif")),
                "ouvert_maintenant": ouverture is None,
                "prochaine_ouverture": ouverture.isoformat() if ouverture else None,
                "statuts": STATUTS_CAMPAGNE}

    # Lot 111 — carrousel sponsorisé : campagnes de la régie publicitaire (placement « carrousel_wa »)
    @api.get("/admin/whatsapp/carrousel/regies", tags=["Admin — Carrousel WhatsApp"])
    async def regies_admin(_: dict = Depends(get_current_admin)):
        """Campagnes de régie « Carrousel WhatsApp » proposées dans l'éditeur, avec le motif qui empêche
        l'envoi (budget épuisé, expirée, en pause…) le cas échéant."""
        lignes = []
        async for b in db.ad_banners.find({"placement": regie.PLACEMENT_CARROUSEL}, {"_id": 0}).sort("created_at", -1):
            budget, depense = float(b.get("budget_amount") or 0), float(b.get("amount_spent") or 0)
            lignes.append({"id": b["id"], "nom": b.get("name") or "", "annonceur": b.get("advertiser_name") or "",
                           "cout_par_clic": float(b.get("cost_per_click") or 0),
                           "cout_par_envoi": float(b.get("cost_per_impression") or 0),
                           "budget": budget, "reste": max(0.0, budget - depense) if budget else None,
                           "devise": b.get("currency") or "XOF", "motif": regie.motif_non_facturable(b)})
        return {"regies": lignes}

    @api.put("/admin/whatsapp/carrousel/campagnes/{cid}/regie", tags=["Admin — Carrousel WhatsApp"])
    async def lier_regie_admin(cid: str, data: LienRegieIn, _: dict = Depends(get_current_admin)):
        """Rattache un envoi déjà fait à une campagne de régie (ses prochains clics seront facturés), ou le détache."""
        await _campagne({"id": cid, "perimetre": "admin"})
        regie_id = (data.regie_id or "").strip() or None
        if regie_id:
            b = await db.ad_banners.find_one({"id": regie_id}, {"_id": 0, "placement": 1})
            if not b or b.get("placement") != regie.PLACEMENT_CARROUSEL:
                raise HTTPException(status_code=400, detail="Campagne de régie « Carrousel WhatsApp » introuvable")
        await regie.lier_une(db, cid, regie_id)
        return {"id": cid, "regie_id": regie_id}

    @api.get("/admin/whatsapp/carrousel/regie/etat", tags=["Admin — Carrousel WhatsApp"])
    async def etat_regie_admin(_: dict = Depends(get_current_admin)):
        """État de la rubrique « 📣 Régie publicitaire — carrousels WhatsApp sponsorisés » des Paramètres."""
        regies = await db.ad_banners.find({"placement": regie.PLACEMENT_CARROUSEL}, {"_id": 0}).to_list(500)
        return {
            "dedup_heures": await regie.dedup_heures(db),
            "campagnes_regie": len(regies),
            "actives": sum(1 for b in regies if not regie.motif_non_facturable(b)),
            "carrousels_sponsorises": await db.carrousel_campagnes.count_documents({"regie_id": {"$nin": [None, ""]}}),
            "clics_factures": sum(int(b.get("total_clicks") or 0) for b in regies),
            "clics_bruts": sum(int(b.get("carrousel_clics_bruts") or 0) for b in regies),
            "montant_consomme": round(sum(float(b.get("amount_spent") or 0) for b in regies), 2),
            "vues_presentation": sum([int(x.get("vues") or 0) async for x in db.carrousel_liens.find(
                {"vues": {"$gt": 0}}, {"_id": 0, "vues": 1})]),
            "interesses": sum([int(x.get("interesses") or 0) async for x in db.carrousel_liens.find(
                {"interesses": {"$gt": 0}}, {"_id": 0, "interesses": 1})]),
        }

    # Lot 114 — pour le branchement (démarrage du planificateur) et les tests
    return {"executer": _executer, "lancer_echus": lancer_echus, "demarrer": demarrer,
            "accords_echus": executer_accords_echus}      # lot 167 : demandes d'accord programmées
