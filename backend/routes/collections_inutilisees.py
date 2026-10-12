# collections_inutilisees.py — Lot 116 : libérer les collections les moins utilisées de la base de SAWALI.
#
# Demande validée par le propriétaire (12/10/2026) : « mesure, puis sauvegarde, désactivation et suppression des
# collections cochées ». Le cluster Atlas accepte au plus 500 collections, toutes bases confondues (voir
# routes/quota_atlas.py) ; la rubrique « 🧹 Libérer l'Espace » (lot 113) traitait déjà R2 et les bases obsolètes,
# ce module ajoute un 4e bloc : les collections peu ou pas utilisées DANS la base de SAWALI.
#
# Routes (administrateur seulement, même contrôle que liberer_espace / quota_atlas) :
#   GET  /api/admin/collections-inutilisees/analyse?jours=90   LECTURE SEULE : chaque collection, ses documents,
#        sa taille, sa dernière activité, la fonction SAWALI qui l'utilise, son état (vide / inactive / active),
#        ses protections ; cochées par défaut : les collections VIDES non protégées.
#   POST /api/admin/collections-inutilisees/liberer   {collections, confirmation: "LIBERER"}
#        Re-vérifie TOUT (si une seule collection est protégée ou introuvable, rien n'est fait), puis pour chacune :
#        a) sauvegarde dans R2 (documents en JSON étendu + index, compressés gzip) — si elle échoue, on ne supprime pas ;
#        b) désactivation de la fonction associée (interrupteur de db.settings « global ») si elle n'est plus utilisée ;
#        c) suppression de la collection ; d) inscription au registre db.settings {_id: "collections_archivees"}.
#   POST /api/admin/collections-inutilisees/restaurer {nom}   recrée la collection depuis R2, réactive la fonction.
#   GET  /api/admin/collections-inutilisees/archivees         liste du registre.
#
# Pas de recréation au démarrage : voir garde_collections_archivees.py (garde-fou central sur create_index).
# Aucune nouvelle collection Mongo (le cluster est presque plein). Aucun identifiant R2 n'est renvoyé ni journalisé.
from __future__ import annotations

import asyncio
import gzip
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId, json_util
from bson.json_util import JSONOptions, JSONMode
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import garde_collections_archivees as garde
from routes import liberer_espace as le
from routes import migration_programmation as mp
from routes import quota_atlas as qa

logger = logging.getLogger("sawali.collections_inutilisees")

DOC_REGISTRE = garde.DOC_REGISTRE          # db.settings {_id: "collections_archivees"}
PREFIXE_R2 = "collections-archivees"       # dossier des archives dans le bucket des sauvegardes programmées
JOURS_DEFAUT = 90                          # « inactive » : aucune activité depuis 90 jours (paramètre `jours`)
PARALLELE = 8                              # mesures simultanées (efficace sans surcharger Atlas)
LOT_INSERTION = 1000                       # restauration : documents insérés par paquets
# JSON étendu « canonique » : types MongoDB conservés à l'identique (ObjectId, dates, décimaux…)
JSON_CANONIQUE = JSONOptions(json_mode=JSONMode.CANONICAL, tz_aware=True)


def _maintenant() -> datetime:
    """Horloge (remplaçable en test)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. Table de correspondance : collection → fonction SAWALI (+ interrupteur qui la désactive)
# ---------------------------------------------------------------------------
# Chaque ligne : (motif, libellé lisible, interrupteur). Le motif est un nom EXACT, ou un PRÉFIXE s'il finit par « * ».
# L'interrupteur est un champ du document db.settings {_id: "global"} (notation pointée admise pour un sous-champ) :
# le mettre à False arrête la fonction (contrôles relevés dans le code : vidal.py, sms (p12), liluvine_*…).
# None : fonction connue mais sans interrupteur général (activée client par client, ou toujours présente) — la
# collection peut alors être archivée, mais rien n'est désactivé.
# Le motif le plus LONG l'emporte (ex. « liluvine_agenda* » avant « liluvine_* »).
FONCTIONS: List[Tuple[str, str, Optional[str]]] = [
    # --- Fonctions avec un interrupteur général (db.settings « global ») ---
    ("vidal_*", "VIDAL (base médicamenteuse, ordonnances)", "vidal_enabled"),
    ("bird_*", "SMS par Bird", "bird_enabled"),
    ("liluvine_wa_autoreply_*", "Réponse automatique WhatsApp de Liluvine", "liluvine_wa_autoreply_enabled"),
    ("liluvine_escalations", "Escalade des conversations Liluvine", "liluvine_escalation_enabled"),
    ("liluvine_unmatched_messages", "Capture des messages non reconnus (Liluvine)",
     "liluvine_reactions_config.unmatched_capture_enabled"),
    ("liluvine_agenda*", "Agenda de Liluvine", "liluvine_agenda_actif"),
    ("appel_proprio_*", "Appel du propriétaire (relais Liluvine)", "appel_proprio_actif"),
    ("download_approvals", "Approbation des téléchargements", "download_approval_enabled"),
    ("gdpr_anonymization_runs", "Anonymisation RGPD automatique", "gdpr_auto_anonymize_enabled"),
    ("wa_tasks_digest_*", "Résumé WhatsApp des tâches", "wa_tasks_digest_enabled"),
    ("wa_absence_*", "Message d'absence WhatsApp", "wa_absence_actif"),
    ("auto_relance_runs", "Relances automatiques de la caisse", "auto_relance_enabled"),
    ("linkedin_*", "Publication automatique LinkedIn", "linkedin_autopost_enabled"),
    # --- Fonctions connues, sans interrupteur général ---
    ("carrousel_*", "Carrousels WhatsApp", None),
    ("ad_*", "Régie publicitaire (bannières)", None),
    ("story_*", "Story Studio", None),
    ("wa_survey*", "Sondages WhatsApp", None),
    ("forms", "Formulaires et Sondages", None),
    ("form_*", "Formulaires et Sondages", None),
    ("liluvine_formulaires", "Formulaires Liluvine", None),
    ("loois_*", "Loois (synchro HFSQL)", None),
    ("support_loois_*", "Support Loois", None),
    ("support_plateformes_*", "Support des plateformes", None),
    ("requetes_*", "Requêtes clients", None),
    ("hr_*", "Ressources humaines / paie", None),
    ("payroll_*", "Ressources humaines / paie", None),
    ("employee_matricule_counters", "Ressources humaines / paie", None),
    ("cashier_*", "Caisse", None),
    ("twitter_*", "Publication réseaux sociaux (X / Twitter)", None),
    ("facebook_*", "Publication réseaux sociaux (Facebook)", None),
    ("instagram_*", "Publication réseaux sociaux (Instagram)", None),
    ("tiktok_*", "Publication réseaux sociaux (TikTok)", None),
    ("fb_publications", "Publication réseaux sociaux (Facebook)", None),
    ("social_accounts", "Comptes de réseaux sociaux", None),
    ("voice_notifications_*", "Notifications vocales", None),
    ("eleven_*", "Voix de synthèse (ElevenLabs)", None),
    ("veo_jobs", "Génération de vidéos IA", None),
    ("imagen_jobs", "Génération d'images IA", None),
    ("ai_generations", "Génération IA (images / textes)", None),
    ("ai_summaries", "Synthèses IA", None),
    ("ai_usage*", "Consommation de l'IA (journal)", None),
    ("ai_quotas", "Quotas de l'IA", None),
    ("llm_*", "Consommation de l'IA (journal)", None),
    ("journal_ia", "Consommation de l'IA (journal)", None),
    ("geo_ip", "Géolocalisation des adresses IP (cache)", None),
    ("i18n_*", "Traductions du site", None),
    ("formation*", "Formations", None),
    ("blog_posts", "Site public (blog)", None),
    ("case_studies", "Site public (études de cas)", None),
    ("testimonials", "Site public (témoignages)", None),
    ("contents", "Site public (contenus CMS)", None),
    ("newsletter", "Lettre d'information", None),
    ("catalog_events", "Catalogue (événements)", None),
    ("country_catalog", "Catalogue par pays", None),
    ("planning_*", "Planning", None),
    ("garde_planning", "Planning des gardes", None),
    ("creneaux_bloques", "Planning (créneaux bloqués)", None),
    ("calendrier_partages", "Calendriers partagés", None),
    ("appointments", "Rendez-vous", None),
    ("parc_*", "Parc informatique", None),
    ("maintenance_plateforme*", "Maintenance de la plateforme", None),
    ("maintenance_*", "Maintenance des équipements", None),
    ("ordonnances_stock", "Ordonnances et stock", None),
    ("stock_*", "Stocks des clients", None),
    ("officine_*", "Portail des officines", None),
    ("officines_*", "Portail des officines", None),
    ("ocr_piece*", "OCR sur pièces", None),
    ("inventaires_postes", "Inventaires (postes)", None),
    ("reseau_*", "Réseau (appareils et découvertes)", None),
    ("production_*", "Production (recettes et intrants)", None),
    ("products", "Catalogue de produits", None),
    ("product_*", "Catalogue de produits", None),
    ("meta_*", "Intégrations Meta (Messenger, webhooks)", None),
    ("whatsapp_flow_*", "WhatsApp Flows", None),
    ("whatsapp_schedules", "Envois WhatsApp programmés", None),
    ("sms_schedules", "Envois SMS programmés", None),
    ("demandes_fonctionnalites", "Demandes de fonctionnalités", None),
    ("roadmap_*", "Feuille de route", None),
    ("meeting_minutes", "Comptes rendus de réunion", None),
    ("user_notes*", "Notes personnelles", None),
    ("user_tasks_personal", "Tâches personnelles", None),
    ("user_reports", "Rapports des utilisateurs", None),
    ("user_module_visits", "Statistiques de visite des modules", None),
    ("client_notes", "Notes sur les clients", None),
    ("client_tasks", "Tâches des clients", None),
    ("wa_appels*", "Appels WhatsApp", None),
    ("wa_silent_*", "Surveillance des silences WhatsApp", None),
    ("wa_silence_*", "Surveillance des silences WhatsApp", None),
    ("wa_webhook_logs", "Journal des webhooks WhatsApp", None),
    ("wa_reply_*", "Réponses WhatsApp (jetons de réponse)", None),
    ("wa_template_notes", "Notes sur les modèles WhatsApp", None),
    ("automations", "Automatisations", None),
    ("api_traces", "Traces des appels API", None),
    ("visits", "Compteur de visites", None),
    ("activity_events", "Journal d'activité", None),
    ("error_registry", "Registre des erreurs", None),
    ("demo_expiry_events", "Comptes de démonstration", None),
    ("tenant_publish_*", "Publication des tenants", None),
    ("tenant_webhooks", "Webhooks des tenants", None),
    ("media_library", "Médiathèque", None),
    ("amm_numbers", "Numéros AMM", None),
    ("plateformes_stats", "Statistiques des plateformes", None),
    ("suggestion_override*", "Suggestions (corrections manuelles)", None),
    ("uptime_checks", "Supervision de la disponibilité", None),
    ("auth_checks", "Contrôle d'authentification (supervision)", None),
    ("integration_health_checks", "Surveillance des intégrations", None),
    ("ratings", "Notes et avis", None),
    ("public_orders", "Commandes publiques", None),
    ("profile_update_requests", "Demandes de mise à jour de profil", None),
    ("ticket_motif_templates", "Modèles de motifs de tickets", None),
    ("fs_vus", "Suivi de lecture", None),
    ("deployments", "Déploiements", None),
    ("app_deployments", "Déploiements des applications", None),
    ("portfolio_reports", "Rapports de portefeuille", None),
    ("internal_chat_messages", "Messagerie interne", None),
    ("interventions", "Interventions", None),
    ("liluvine_*", "Liluvine (assistante)", None),
]

# ---------------------------------------------------------------------------
# 2. Collections PROTÉGÉES : jamais proposées (affichées grisées avec la raison)
# ---------------------------------------------------------------------------
# Établie avec soin : tout ce qui touche aux comptes, à la sécurité, aux messages des clients, à l'argent, aux
# contrats, aux sauvegardes, aux incidents et aux obligations légales (désinscriptions STOP, accords WhatsApp).
# Motif : nom EXACT, ou PRÉFIXE s'il finit par « * ». S'ajoutent les règles calculées de `raison_protection` :
# collections système (system.*), noms contenant « audit », « secret » ou « token », et toute collection NON VIDE
# sans fonction connue (on ne saurait pas l'arrêter proprement).
PROTEGEES: List[Tuple[str, str]] = [
    # Comptes, connexion, sessions
    ("users", "comptes des utilisateurs"), ("tracked_user*", "utilisateurs suivis"), ("user_suivis", "utilisateurs suivis"),
    ("sessions*", "sessions de connexion"), ("otps", "codes de connexion"), ("officine_otp_codes", "codes de connexion"),
    ("officine_magic_tokens", "liens de connexion"), ("wa_otp_requests", "codes de connexion WhatsApp"),
    ("role*", "rôles et droits"), ("permissions*", "rôles et droits"),
    # Paramètres et compteurs (numérotation des factures, matricules…)
    ("settings", "paramètres de SAWALI"), ("app_settings", "paramètres"), ("parametres*", "paramètres"),
    ("counters", "compteurs de numérotation"), ("compteurs", "compteurs de numérotation"),
    ("hr_counters", "compteurs de numérotation"), ("product_sku_counters", "compteurs de numérotation"),
    # Sécurité et journaux de sécurité
    ("access_logs", "journal des accès (sécurité)"), ("connexions*", "journal des connexions (sécurité)"),
    ("alertes_connexions", "alertes de connexion (sécurité)"), ("blacklisted_ips", "adresses IP bloquées (sécurité)"),
    ("impersonation_journal", "journal des prises de contrôle (sécurité)"), ("geo_ip_bloquees", "sécurité"),
    ("loois_cles_clients", "clés Loois des clients (sécurité)"), ("vault*", "coffre de secrets"),
    # Messages et conversations des clients
    ("whatsapp_messages", "messages WhatsApp"), ("wa_messages", "messages WhatsApp"), ("sms_messages", "messages SMS"),
    ("wa_pending_*", "conversations WhatsApp en attente"), ("meta_messenger_messages", "messages Messenger"),
    ("liluvine_pro_*", "conversations Liluvine Pro"), ("conversations*", "conversations"),
    # Clients, contacts, tenants
    ("directory_contacts", "annuaire des clients"), ("contacts", "contacts"), ("contact_groups", "groupes de contacts"),
    ("business_clients", "clients"), ("client_categories", "catégories de clients"), ("clients*", "clients"),
    ("officines", "officines clientes"), ("tenant_kyc", "identité des tenants"), ("tenant_smart_comm", "tenants"),
    ("tenant_country", "tenants"), ("tenant_meta", "tenants"),
    # Contrats et abonnements
    ("contrat*", "contrats"), ("contract*", "contrats"), ("subscription*", "abonnements"),
    ("ai_subscriptions", "abonnements IA"), ("abonnement*", "abonnements"),
    # Paiements et factures
    ("payment*", "paiements"), ("payments", "paiements"), ("tenant_payments", "paiements"), ("invoices", "factures"),
    ("interventions_invoices", "factures"), ("tenant_publish_invoices", "factures"), ("receipts", "reçus"),
    ("pawapay_*", "paiements PawaPay"), ("pispi_*", "paiements PI-SPI"), ("webhook_events_stripe", "paiements Stripe"),
    ("billing*", "facturation"), ("portfolio_billing", "facturation"), ("factur*", "factures"),
    ("paiement*", "paiements"), ("coupons", "bons de réduction"),
    # Sauvegardes, migration, espace
    ("migration_*", "sauvegardes et migration"), ("sauvegarde*", "sauvegardes"), ("db_snapshot*", "instantanés de la base"),
    ("liberer_espace*", "outil de libération d'espace"), ("quota*", "jauge du cluster"),
    # Incidents
    ("incident*", "incidents"), ("liluvine_incidents", "incidents"),
    # Obligations légales, consentements, transmission universelle
    ("liluvine_desinscriptions", "désinscriptions STOP (obligation légale)"),
    ("liluvine_liste_noire", "liste noire (obligation légale)"), ("accords_whatsapp_journal", "accords WhatsApp (légal)"),
    ("liluvine_emetteurs", "émetteurs de la transmission universelle"), ("liluvine_transmissions", "transmission universelle"),
    ("policies", "documents légaux"), ("legal_forms", "documents légaux"),
    # Fichiers et documents des clients (les fichiers dans le stockage y sont référencés)
    ("documents", "documents des clients"), ("document_*", "documents des clients"), ("files", "fichiers"),
    ("stored_objects", "fichiers stockés"), ("stock_files", "fichiers de stock"),
    # Support et présence des logiciels (règle 4)
    ("support_tickets", "tickets du support"), ("tickets", "tickets du support"),
    ("presences_logiciels", "présence des logiciels (règle 4)"),
]
# Mots qui protègent toute collection qui les contient (journaux d'audit, secrets, jetons)
MOTS_PROTEGES = {"audit": "journal d'audit", "secret": "secrets", "token": "jetons de connexion"}


def _correspond(nom: str, motif: str) -> bool:
    """Nom exact, ou préfixe si le motif finit par « * »."""
    return nom.startswith(motif[:-1]) if motif.endswith("*") else nom == motif


def fonction_de(nom: str) -> Optional[Dict[str, Any]]:
    """Fonction SAWALI qui utilise la collection (motif le plus long) → {libelle, cle_fonction} ou None."""
    meilleurs = [(len(m), lib, cle) for m, lib, cle in FONCTIONS if _correspond(nom, m)]
    if not meilleurs:
        return None
    _l, lib, cle = max(meilleurs, key=lambda x: x[0])
    return {"libelle": lib, "cle_fonction": cle}


def raison_protection(nom: str, documents: Optional[int], fonction: Optional[Dict[str, Any]]) -> Optional[str]:
    """Raison pour laquelle la collection n'est JAMAIS proposée, ou None si elle peut l'être."""
    if nom.startswith("system."):
        return "collection système MongoDB"
    for motif, raison in PROTEGEES:
        if _correspond(nom, motif):
            return f"vitale : {raison}"
    bas = nom.lower()
    for mot, raison in MOTS_PROTEGES.items():
        if mot in bas:
            return f"vitale : {raison}"
    if fonction is None and (documents is None or documents > 0):
        return "fonction inconnue : non désactivable proprement"
    return None


# ---------------------------------------------------------------------------
# 3. Mesure (lecture seule, au plus 1 document lu par collection)
# ---------------------------------------------------------------------------
CHAMPS_DATE = ("updated_at", "created_at", "cree_le", "modifie_le", "date", "le", "timestamp", "datetime")


def _en_date(v: Any) -> Optional[datetime]:
    """Valeur de date (datetime, texte ISO, horodatage en secondes / millisecondes) → datetime UTC, ou None."""
    try:
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if isinstance(v, str) and len(v) >= 10 and v[:4].isdigit():
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        if isinstance(v, (int, float)) and v > 10 ** 9:
            return datetime.fromtimestamp(v / 1000 if v > 10 ** 11 else v, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return None


def derniere_activite(doc: Optional[dict]) -> Optional[datetime]:
    """Date la plus récente connue du document le plus récent : horodatage de l'ObjectId et champs usuels."""
    if not doc:
        return None
    dates = [_en_date(doc.get(c)) for c in CHAMPS_DATE]
    if isinstance(doc.get("_id"), ObjectId):
        dates.append(doc["_id"].generation_time)
    dates = [d for d in dates if d]
    return max(dates) if dates else None


async def _taille(db, nom: str) -> Dict[str, Optional[int]]:
    """Taille par la commande collStats si le compte en a le droit ; sinon None (jamais d'échec)."""
    try:
        s = await db.command({"collStats": nom})
        return {"octets": int(s.get("size") or 0), "stockage": int(s.get("storageSize") or 0),
                "index_octets": int(s.get("totalIndexSize") or 0)}
    except Exception:  # noqa: BLE001 — droit absent (Atlas Flex) ou commande indisponible
        return {"octets": None, "stockage": None, "index_octets": None}


async def mesurer_collection(db, nom: str) -> Dict[str, Any]:
    """Documents (estimation rapide), taille, dernière activité (1 document lu au plus)."""
    coll = db[nom]
    try:
        documents: Optional[int] = int(await coll.estimated_document_count() or 0)
    except Exception:  # noqa: BLE001
        documents = None
    activite = None
    if documents:
        try:
            projection = {c: 1 for c in CHAMPS_DATE}
            doc = await coll.find_one({}, projection, sort=[("_id", -1)])
            activite = derniere_activite(doc)
        except Exception:  # noqa: BLE001 — tri impossible : date inconnue
            activite = None
    return {"nom": nom, "documents": documents, **(await _taille(db, nom)),
            "derniere_activite": activite.isoformat() if activite else None}


def classer(mesure: Dict[str, Any], jours: int, maintenant: datetime) -> Dict[str, Any]:
    """État (vide / inactive / active), fonction, protection et case cochée par défaut. Fonction pure, testée."""
    nom, documents = mesure["nom"], mesure.get("documents")
    fonction = fonction_de(nom)
    protection = raison_protection(nom, documents, fonction)
    if documents == 0:
        etat = "vide"
    else:
        d = _en_date(mesure.get("derniere_activite"))
        etat = "inactive" if d and d < maintenant - timedelta(days=jours) else "active"
    ligne = dict(mesure)
    ligne.update({
        "fonction": fonction["libelle"] if fonction else "Fonction inconnue",
        "cle_fonction": fonction["cle_fonction"] if fonction else None,
        "etat": etat, "protegee": protection is not None, "raison": protection,
        # Cochée par défaut : seulement les collections VIDES non protégées
        "coche": protection is None and etat == "vide",
    })
    return ligne


def _cle_tri(ligne: Dict[str, Any]) -> tuple:
    """Du moins utilisé au plus utilisé : vides d'abord, puis dernière activité la plus ancienne, puis documents."""
    return (0 if ligne.get("documents") == 0 else 1, ligne.get("derniere_activite") or "", ligne.get("documents") or 0,
            ligne["nom"])


def plan_desactivation(lignes: List[Dict[str, Any]], interrupteurs: Dict[str, Any]) -> None:
    """Indique pour chaque ligne ce qui arrivera à sa fonction. Prudence : on ne coupe PAS une fonction encore
    utilisée par une autre collection « active » (ex. archiver la collection vide « vidal_sync_log » ne doit pas
    éteindre VIDAL si « vidal_patients » sert tous les jours)."""
    actives: Dict[str, List[str]] = {}
    for l in lignes:
        if l.get("cle_fonction") and l["etat"] == "active":
            actives.setdefault(l["cle_fonction"], []).append(l["nom"])
    for l in lignes:
        cle = l.get("cle_fonction")
        if not cle:
            l["action_fonction"] = {"desactiver": False, "texte": "aucun interrupteur général"}
        elif _valeur(interrupteurs, cle) is False:
            l["action_fonction"] = {"desactiver": False, "texte": "fonction déjà désactivée"}
        else:
            autres = [n for n in actives.get(cle, []) if n != l["nom"]]
            if autres:
                l["action_fonction"] = {"desactiver": False,
                                        "texte": f"fonction gardée : encore utilisée par {', '.join(autres[:3])}"}
            else:
                l["action_fonction"] = {"desactiver": True, "texte": f"désactivera « {cle} »"}


def _valeur(doc: Dict[str, Any], chemin: str) -> Any:
    """Valeur d'un champ en notation pointée (« a.b.c ») ; None si absent."""
    v: Any = doc
    for morceau in chemin.split("."):
        if not isinstance(v, dict):
            return None
        v = v.get(morceau)
    return v


async def _reglages_global(db) -> Dict[str, Any]:
    return await db.settings.find_one({"_id": "global"}) or {}


async def mesurer_tout(db, jours: int, maintenant: datetime, noms: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Mesure et classe les collections de la base (toutes, ou celles demandées), en parallèle limité."""
    if noms is None:
        noms = await db.list_collection_names()
    semaphore = asyncio.Semaphore(PARALLELE)

    async def une(nom: str) -> Dict[str, Any]:
        async with semaphore:
            return classer(await mesurer_collection(db, nom), jours, maintenant)
    lignes = list(await asyncio.gather(*(une(n) for n in noms)))
    plan_desactivation(lignes, await _reglages_global(db))
    lignes.sort(key=_cle_tri)
    return lignes


async def analyser(db, client, base_courante: str, jours: int = JOURS_DEFAUT,
                   maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Tableau complet + synthèse + jauge du cluster. Ne modifie RIEN."""
    maintenant = maintenant or _maintenant()
    jours = max(1, min(int(jours or JOURS_DEFAUT), 3650))
    lignes = await mesurer_tout(db, jours, maintenant)
    try:
        jauge = await qa.mesurer(db, client, base_courante)
    except Exception as exc:  # noqa: BLE001
        jauge = {"erreur": f"Mesure indisponible : {le._motif(exc)}"}
    proposees = [l for l in lignes if not l["protegee"]]
    return {
        "le": maintenant.isoformat(), "base": db.name, "jours": jours, "collections": lignes, "jauge": jauge,
        "synthese": {
            "total": len(lignes),
            "proposees": len(proposees),
            "protegees": len(lignes) - len(proposees),
            "vides": sum(1 for l in lignes if l["etat"] == "vide"),
            "inactives": sum(1 for l in lignes if l["etat"] == "inactive"),
            "liberables_par_defaut": sum(1 for l in lignes if l["coche"]),
        },
        "archivees": len(await lister_registre(db)),
    }


# ---------------------------------------------------------------------------
# 4. Registre db.settings {_id: "collections_archivees"} (aucune nouvelle collection)
# ---------------------------------------------------------------------------
def _cle_registre(nom: str) -> str:
    """Nom de collection → clé de champ Mongo sûre (le point et le dollar sont interdits dans une clé)."""
    return nom.replace("%", "%25").replace(".", "%2E").replace("$", "%24")


async def lister_registre(db) -> List[Dict[str, Any]]:
    """Entrées du registre, les plus récentes d'abord."""
    doc = await db.settings.find_one({"_id": DOC_REGISTRE}) or {}
    entrees = [dict(v, nom=v.get("nom") or k) for k, v in doc.items() if k != "_id" and isinstance(v, dict)]
    entrees.sort(key=lambda e: e.get("archivee_le") or "", reverse=True)
    return entrees


async def _entree_registre(db, nom: str) -> Optional[Dict[str, Any]]:
    doc = await db.settings.find_one({"_id": DOC_REGISTRE}, {_cle_registre(nom): 1}) or {}
    return doc.get(_cle_registre(nom))


# ---------------------------------------------------------------------------
# 5. Sauvegarde dans R2 et restauration
# ---------------------------------------------------------------------------
def _index_exportables(info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """index_information() → liste d'index à recréer (hors _id), options utiles seulement (comme le lot 47)."""
    sortie = []
    for nom_index, i in (info or {}).items():
        if nom_index == "_id_":
            continue
        options = {k: v for k, v in i.items()
                   if k in ("unique", "sparse", "expireAfterSeconds", "partialFilterExpression",
                            "collation", "weights", "default_language", "language_override")}
        sortie.append({"nom": nom_index, "cles": [list(p) for p in i.get("key", [])], "options": options})
    return sortie


async def exporter(db, nom: str, maintenant: datetime) -> Tuple[bytes, int, List[Dict[str, Any]]]:
    """Archive gzip d'une collection : {collection, base, exportee_le, index, documents} en JSON étendu canonique.
    Écrit document par document (pas de liste complète en mémoire avant compression)."""
    index = _index_exportables(await db[nom].index_information())
    tampon = io.BytesIO()
    n = 0
    with gzip.GzipFile(fileobj=tampon, mode="wb") as gz:
        entete = json_util.dumps({"collection": nom, "base": db.name, "exportee_le": maintenant.isoformat(),
                                  "index": index}, json_options=JSON_CANONIQUE)
        gz.write((entete[:-1] + ', "documents": [').encode("utf-8"))      # on ouvre la liste des documents
        async for d in db[nom].find({}):
            gz.write(((", " if n else "") + json_util.dumps(d, json_options=JSON_CANONIQUE)).encode("utf-8"))
            n += 1
        gz.write(b"]}")
    return tampon.getvalue(), n, index


def lire_archive(donnees: bytes) -> Dict[str, Any]:
    """Archive gzip → {collection, index, documents} (types MongoDB rétablis)."""
    return json_util.loads(gzip.decompress(donnees).decode("utf-8"), json_options=JSON_CANONIQUE)


def _envoyer_r2(r2, bucket: str, cle: str, donnees: bytes) -> None:
    """Dépose l'archive dans R2 puis VÉRIFIE sa présence et sa taille (sinon : erreur → pas de suppression)."""
    r2.upload_fileobj(io.BytesIO(donnees), bucket, cle, ExtraArgs={"ContentType": "application/gzip"})
    info = r2.head_object(Bucket=bucket, Key=cle)
    if int(info.get("ContentLength") or -1) != len(donnees):
        raise RuntimeError("archive incomplète dans R2")


def _lire_r2(r2, bucket: str, cle: str) -> bytes:
    return r2.get_object(Bucket=bucket, Key=cle)["Body"].read()


async def _r2_ou_erreur() -> Dict[str, Any]:
    """Client R2 + bucket des sauvegardes programmées (mêmes identifiants que le lot 47/107), sinon 400."""
    ctx = await le._contexte_migration()
    if "message" in ctx:
        raise HTTPException(400, f"Sauvegarde impossible : {ctx['message']}")
    return ctx


# ---------------------------------------------------------------------------
# 6. Exécution : sauvegarde → désactivation → suppression → registre
# ---------------------------------------------------------------------------
class LibererIn(BaseModel):
    collections: List[str] = Field(default_factory=list, max_length=300)
    confirmation: str = ""
    jours: int = JOURS_DEFAUT


class RestaurerIn(BaseModel):
    nom: str


async def _verifier(db, noms: List[str], jours: int, maintenant: datetime) -> Dict[str, Dict[str, Any]]:
    """Re-vérification côté serveur : la moindre collection protégée ou introuvable → rien n'est fait."""
    existantes = set(await db.list_collection_names())
    for nom in noms:
        if nom not in existantes:
            raise HTTPException(404, f"Collection introuvable : {nom} (rien n'a été fait)")
    # On remesure TOUTE la base : le plan de désactivation dépend des autres collections de la même fonction
    lignes = {l["nom"]: l for l in await mesurer_tout(db, jours, maintenant)}
    for nom in noms:
        if lignes[nom]["protegee"]:
            raise HTTPException(409, f"La collection « {nom} » est protégée ({lignes[nom]['raison']}) : rien n'a été fait")
    return lignes


async def _desactiver(db, cle: str) -> Dict[str, Any]:
    """Met l'interrupteur à False dans db.settings « global » ; renvoie l'ancienne valeur (pour la restauration)."""
    avant = _valeur(await _reglages_global(db), cle)
    await db.settings.update_one({"_id": "global"}, {"$set": {cle: False}}, upsert=True)
    return {"desactivee": True, "valeur_avant": avant}


async def liberer(db, client, base_courante: str, corps: LibererIn, user: Dict[str, Any],
                  maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Sauvegarde, désactive, supprime et inscrit au registre chaque collection choisie (rapport détaillé)."""
    if not le.mot_confirme(corps.confirmation):
        raise HTTPException(400, "Tapez LIBERER pour confirmer la suppression des collections")
    noms = [n for n in dict.fromkeys(str(x).strip() for x in corps.collections) if n]
    if not noms:
        raise HTTPException(400, "Aucune collection sélectionnée")
    maintenant = maintenant or _maintenant()
    jours = max(1, min(int(corps.jours or JOURS_DEFAUT), 3650))
    par = user.get("email", "")

    # 1. Toutes les vérifications AVANT la moindre action (protections recalculées, R2 joignable)
    lignes = await _verifier(db, noms, jours, maintenant)
    ctx = await _r2_ou_erreur()
    r2, bucket = ctx["r2"], ctx["bucket"]
    dossier = f"{PREFIXE_R2}/{maintenant.strftime('%Y%m%d-%H%M%S')}"
    logger.warning("[collections-inutilisees] libération lancée par %s : %d collection(s)", par, len(noms))

    elements: List[Dict[str, Any]] = []
    deja_desactivees: Dict[str, Dict[str, Any]] = {}       # une fonction partagée n'est coupée qu'une fois
    for nom in noms:
        l = lignes[nom]
        e: Dict[str, Any] = {"nom": nom, "fonction": l["fonction"], "cle_fonction": l["cle_fonction"],
                             "documents": 0, "octets": l.get("octets"), "ok": False, "etapes": []}
        # a) Sauvegarde dans R2 — en cas d'échec, la collection n'est PAS supprimée
        cle_r2 = f"{dossier}/{nom}.json.gz"
        try:
            donnees, n, index = await exporter(db, nom, maintenant)
            await asyncio.to_thread(_envoyer_r2, r2, bucket, cle_r2, donnees)
            e.update({"documents": n, "archive_octets": len(donnees), "r2_cle": cle_r2, "index": len(index)})
            e["etapes"].append("sauvegardée")
        except Exception as exc:  # noqa: BLE001
            e["erreur"] = f"sauvegarde impossible ({le._motif(exc)}) : collection conservée"
            elements.append(e)
            logger.warning("[collections-inutilisees] %s non sauvegardée : %s", nom, e["erreur"])
            continue
        # b) Désactivation de la fonction (si elle n'est plus utilisée ailleurs — voir plan_desactivation)
        desactivation: Dict[str, Any] = {"desactivee": False, "valeur_avant": None}
        action = l.get("action_fonction") or {}
        try:
            if action.get("desactiver") and l["cle_fonction"]:
                if l["cle_fonction"] in deja_desactivees:
                    desactivation = {"desactivee": False, "valeur_avant": None, "par_collection":
                                     deja_desactivees[l["cle_fonction"]]["nom"]}
                else:
                    desactivation = await _desactiver(db, l["cle_fonction"])
                    deja_desactivees[l["cle_fonction"]] = {"nom": nom}
                    e["etapes"].append(f"fonction désactivée ({l['cle_fonction']})")
        except Exception as exc:  # noqa: BLE001 — on continue : la sauvegarde est faite, la suppression reste sûre
            e["avertissement"] = f"fonction non désactivée : {le._motif(exc)}"
        e["fonction_action"] = action.get("texte")
        # c) Suppression de la collection
        try:
            await db.drop_collection(nom)
            e["etapes"].append("supprimée")
        except Exception as exc:  # noqa: BLE001
            e["erreur"] = f"suppression refusée ({le._motif(exc)}) — sauvegarde gardée dans R2"
            elements.append(e)
            continue
        # d) Registre (dans db.settings) + garde-fou du démarrage
        entree = {"nom": nom, "r2_cle": cle_r2, "r2_bucket": bucket, "documents": e["documents"],
                  "octets": l.get("octets"), "archive_octets": e["archive_octets"],
                  # Index : seulement leur nombre et leurs noms ici (la définition complète est dans l'archive R2)
                  "index": len(index), "index_noms": [ix["nom"] for ix in index],
                  "fonction": l["fonction"], "cle_fonction": l["cle_fonction"],
                  "fonction_desactivee": desactivation["desactivee"], "valeur_avant": desactivation.get("valeur_avant"),
                  "archivee_le": maintenant.isoformat(), "par": par}
        await db.settings.update_one({"_id": DOC_REGISTRE}, {"$set": {_cle_registre(nom): entree}}, upsert=True)
        garde.noter_archivee(nom, db.name)
        e["etapes"].append("inscrite au registre")
        e["ok"] = True
        elements.append(e)
        logger.warning("[collections-inutilisees] %s archivée par %s : %s document(s), %s", nom, par, e["documents"],
                       cle_r2)

    # Jauge APRÈS + rapport
    try:
        jauge = await qa.mesurer(db, client, base_courante)
    except Exception as exc:  # noqa: BLE001
        jauge = {"erreur": f"Mesure indisponible : {le._motif(exc)}"}
    rapport = {"le": maintenant.isoformat(), "par": par, "dossier_r2": dossier, "elements": elements,
               "liberees": sum(1 for e in elements if e["ok"]), "erreurs": sum(1 for e in elements if not e["ok"]),
               "jauge_apres": jauge}
    try:
        cfg = await mp.lire_reglage()
        texte = "\n".join(
            ["🤖 Liluvine — Collections archivées", f"Par {par} le {rapport['le'][:16].replace('T', ' ')} (UTC)",
             f"{rapport['liberees']} collection(s) libérée(s), {rapport['erreurs']} erreur(s)"]
            + ([f"Cluster Atlas : {jauge['total']}/{jauge['limite']} collections"] if jauge.get("total") is not None else [])
            + [f"  {'✅' if e['ok'] else '❌'} {e['nom']} ({e['documents']} doc.)" + (f" — {e['erreur']}" if e.get("erreur") else "")
               for e in elements])
        rapport["rapport"] = await asyncio.wait_for(
            mp.envoyer_rapport("Collections archivées", texte, cfg, important=True, maintenant=maintenant),
            timeout=le.DELAI_RAPPORT)
    except Exception as exc:  # noqa: BLE001 — l'envoi du rapport ne doit jamais faire échouer la libération
        logger.warning("[collections-inutilisees] rapport non envoyé : %s", type(exc).__name__)
        rapport["rapport"] = {"envoye": False, "erreur": "envoi du rapport impossible"}
    return rapport


async def restaurer(db, nom: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """Recrée la collection depuis R2 (documents + index), réactive la fonction, retire l'entrée du registre."""
    nom = (nom or "").strip()
    entree = await _entree_registre(db, nom)
    if not entree:
        raise HTTPException(404, f"« {nom} » n'est pas dans le registre des collections archivées")
    if nom in await db.list_collection_names() and await db[nom].estimated_document_count() > 0:
        raise HTTPException(409, f"La collection « {nom} » existe déjà avec des documents : restauration refusée")
    ctx = await _r2_ou_erreur()
    bucket = entree.get("r2_bucket") or ctx["bucket"]
    try:
        archive = lire_archive(await asyncio.to_thread(_lire_r2, ctx["r2"], bucket, entree["r2_cle"]))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Archive illisible dans R2 : {le._motif(exc)}")
    # Le garde-fou ne doit plus bloquer cette collection (ses index vont être recréés)
    garde.noter_restauree(nom, db.name)
    docs = archive.get("documents") or []
    for i in range(0, len(docs), LOT_INSERTION):
        await db[nom].insert_many(docs[i:i + LOT_INSERTION], ordered=False)
    index_ok, index_erreurs = 0, []
    for ix in archive.get("index") or []:
        try:
            await db[nom].create_index([tuple(c) for c in ix["cles"]], name=ix["nom"], **(ix.get("options") or {}))
            index_ok += 1
        except Exception as exc:  # noqa: BLE001
            index_erreurs.append(f"{ix.get('nom')} ({type(exc).__name__})")
    if not docs and not index_ok:
        # Collection vide sans index : on la recrée explicitement pour qu'elle réapparaisse
        try:
            await db.create_collection(nom)
        except Exception:  # noqa: BLE001 — déjà présente
            pass
    # Réactivation : on remet la valeur d'avant (ou on retire le champ s'il n'existait pas)
    reactivee = False
    if entree.get("fonction_desactivee") and entree.get("cle_fonction"):
        cle = entree["cle_fonction"]
        avant = entree.get("valeur_avant")
        maj = {"$unset": {cle: ""}} if avant is None else {"$set": {cle: avant}}
        await db.settings.update_one({"_id": "global"}, maj, upsert=True)
        reactivee = True
    await db.settings.update_one({"_id": DOC_REGISTRE}, {"$unset": {_cle_registre(nom): ""}})
    logger.warning("[collections-inutilisees] %s restaurée par %s : %d document(s)", nom, user.get("email"), len(docs))
    return {"ok": True, "nom": nom, "documents": len(docs), "index": index_ok, "index_erreurs": index_erreurs,
            "fonction": entree.get("fonction"), "fonction_reactivee": reactivee}


# ---------------------------------------------------------------------------
# Routes (branchées dans server_parts/p20_branchement_routeurs.py)
# ---------------------------------------------------------------------------
def setup_collections_inutilisees_routes(*, db, client, api, get_current_user, base_courante: str) -> None:
    """Routes du bloc « Collections les moins utilisées » de « 🧹 Libérer l'Espace »."""

    @api.get("/admin/collections-inutilisees/analyse", tags=["Admin — Santé"])
    async def route_analyse(jours: int = JOURS_DEFAUT, user: dict = Depends(get_current_user)):
        """Mesure en lecture seule des collections de la base de SAWALI."""
        le._admin_strict(user)
        return await analyser(db, client, base_courante, jours)

    @api.post("/admin/collections-inutilisees/liberer", tags=["Admin — Santé"])
    async def route_liberer(corps: LibererIn, user: dict = Depends(get_current_user)):
        """Sauvegarde R2, désactivation, suppression et registre (confirmation LIBERER, tout est re-vérifié)."""
        le._admin_strict(user)
        return await liberer(db, client, base_courante, corps, user)

    @api.post("/admin/collections-inutilisees/restaurer", tags=["Admin — Santé"])
    async def route_restaurer(corps: RestaurerIn, user: dict = Depends(get_current_user)):
        """Recrée une collection archivée depuis sa sauvegarde R2."""
        le._admin_strict(user)
        return await restaurer(db, corps.nom, user)

    @api.get("/admin/collections-inutilisees/archivees", tags=["Admin — Santé"])
    async def route_archivees(user: dict = Depends(get_current_user)):
        """Registre des collections archivées (avec « recréée » si une fonction a de nouveau écrit dedans)."""
        le._admin_strict(user)
        presentes = set(await db.list_collection_names())
        entrees = await lister_registre(db)
        for e in entrees:
            e["recreee"] = e["nom"] in presentes
        return {"archivees": entrees}
