"""Lot 51 — Cycle de vie du non-renouvellement (spécification commune, point C, validée le 02/10/2026).

Le « locataire » SAWALI est le CLIENT ABONNÉ : son compte principal (fiche `users`) et tout ce qui
lui est rattaché. Échéance = celle du lot 50 (abonnement_acces.etat_client) : date du dernier
règlement (`last_payment_at`, à défaut `contract_signed_at`) + périodicité du contrat (mensuel 30 j,
trimestriel 90 j, annuel 365 j). Un client sans périodicité ou sans date n'a pas d'échéance : il
n'est JAMAIS concerné. J+N = nombre de jours calendaires depuis l'échéance (grâce comprise).

Calendrier (tâche quotidienne, ou « Lancer maintenant » du super-admin) :
  J+103  avertissement « suspension dans 7 jours » (WhatsApp + e-mail)
  J+110  SUSPENSION (statut SUSPENDU_NON_RENOUVELE sur la fiche du client) + avertissement :
         plus aucun accès pour aucun compte du client (portail client fermé, connexion par mot de
         passe, code e-mail ou code WhatsApp refusée, sessions ouvertes fermées). Le super-admin et
         les sessions « Voir en tant que » (lot 44) restent possibles.
  J+112  avertissement « vos données seront archivées puis supprimées demain »
  J+113  ARCHIVE chiffrée des données du client (même format et même chiffrement que l'export
         complet du lot 49, phrase SAUVEGARDE_AUTO_PHRASE), envoyée dans R2 sous
         `archives-locataires/<client>/`, puis TÉLÉCHARGÉE À NOUVEAU, déchiffrée et comparée
         (nombre de documents ET identifiants de chaque collection). SEULEMENT si tout concorde, les
         données sont supprimées de la base ; la fiche du client est conservée, réduite, au statut
         ARCHIVE (référence de l'archive, date, nombres de documents). Si la vérification échoue :
         RIEN n'est supprimé et le super-admin reçoit une alerte (e-mail + rapport + journal).
  + conservation de l'archive : 365 jours par défaut (réglable), puis effacement dans R2.

Les délais sont des MINIMUMS : chaque étape exige que la précédente ait eu lieu (au moins 7 jours
entre l'avertissement J+103 et la suspension, au moins 3 jours de suspension et un avertissement
« veille » envoyé la veille au plus tard avant l'archivage). Un client déjà très en retard le jour
où l'interrupteur est activé reçoit donc d'abord l'avertissement, et n'est jamais suspendu ni
archivé sans préavis.

Un règlement saisi (Admin → Clients) repousse l'échéance : la suspension tombe aussitôt (contrôle
de chaque requête) et la tâche suivante la retire de la fiche. Après l'archivage, seule la
« Réouverture » du super-admin (frais de réouverture paramétrables, montant + devise) rend
l'accès : l'archive est relue, vérifiée puis restaurée (remplacement limité aux documents du
client), le statut redevient actif et une nouvelle échéance part du jour de la réouverture.

Données archivées (choix du lot, voir `collecter`) : toute collection de la base (hors journaux de
la plateforme et réglages, COLLECTIONS_CONSERVEES) dont un champ « propriétaire »
(CHAMPS_PROPRIETAIRE) désigne un compte du client — compte principal, comptes rattachés
(parent_client_id / client_id), utilisateurs suivis (tracked_users) — ainsi que les documents
« enfants » de ses formulaires, sondages, campagnes et officines (CHAMPS_ENFANTS : réponses,
envois, invitations, inventaires…). Les identifiants sont des UUID : aucun autre client n'est touché.

INTERRUPTEUR GÉNÉRAL `cycle_vie_actif` : DÉSACTIVÉ par défaut (même prudence que la coupure du
lot 50 : des règlements ont pu ne pas être saisis). Mode SIMULATION `cycle_vie_simulation`
(activé par défaut) : la tâche liste ce qui serait fait sans rien faire. Le bouton « Simuler
maintenant » fonctionne même interrupteur désactivé. La tâche quotidienne est programmée dans le
planificateur existant : jamais avec DISABLE_SCHEDULER=1 ni dans la preview. Clients de test
(`est_test`), démo (`is_demo`, DEMO SAWALI), comptes internes (domaines internes) et super-admin :
toujours exclus.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import secrets
import time
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from bson import json_util

import abonnement_acces as abo
import sauvegarde_format as sf
from chemins import EXPORTS_DIR
from controle_acces import RefusAcces
from db import db

logger = logging.getLogger("sawali.cycle_vie")

# ---------------------------------------------------------------------------
# Calendrier et réglages
# ---------------------------------------------------------------------------
J_AVERT_SUSPENSION = 103      # J-7 avant la suspension
J_SUSPENSION = 110
J_AVERT_SUPPRESSION = 112     # veille de la suppression
J_ARCHIVE = 113
PREAVIS_SUSPENSION_J = J_SUSPENSION - J_AVERT_SUSPENSION        # 7 jours au moins
DUREE_SUSPENSION_MIN_J = J_ARCHIVE - J_SUSPENSION               # 3 jours au moins
PREAVIS_SUPPRESSION_J = J_ARCHIVE - J_AVERT_SUPPRESSION         # 1 jour au moins

CONSERVATION_DEFAUT, CONSERVATION_MIN, CONSERVATION_MAX = 365, 30, 3650
DEVISE_DEFAUT = "XOF"

ACTIF, SUSPENDU, ARCHIVE = "ACTIF", "SUSPENDU_NON_RENOUVELE", "ARCHIVE"
CODE_SUSPENDU = "abonnement_suspendu"
ETAPES = {"J103": J_AVERT_SUSPENSION, "J110": J_SUSPENSION, "J112": J_AVERT_SUPPRESSION}

JOURNAL = "cycle_vie_journal"
AVERTISSEMENTS = "cycle_vie_avertissements"
ETAT = "cycle_vie_etat"                 # dernier rapport, verrou de la tâche
FORMAT_ARCHIVE = "sawali-archive-client"
PREFIXE_ARCHIVES = "archives-locataires/"
RE_CLE_ARCHIVE = re.compile(r"archives-locataires/[A-Za-z0-9_.-]+/sawali-client-\d{8}-\d{6}-[0-9a-f]{6}\.sawali")
LOT_LECTURE = 500
LOT_ECRITURE = 1000

# Champs qui désignent le propriétaire d'un document (valeur = identifiant d'un compte du client)
CHAMPS_PROPRIETAIRE = (
    "client_id", "tenant_id", "parent_client_id", "user_id", "owner_id", "owner_user_id",
    "owner_parent_client_id", "tracked_user_id", "user_account_id", "created_by_id",
    "uploaded_by_user_id", "billing_tenant_id", "linked_client_id",
)
# Documents « enfants » : rattachés à un document du client par son identifiant
CHAMPS_ENFANTS = {
    "form_id": "forms",                       # réponses, envois, imports de formulaires
    "survey_id": "wa_surveys",                # invitations et réponses aux sondages
    "campaign_id": "wa_survey_campaigns",
    "officine_id": "officines",               # inventaires, produits, codes des officines liées
}
# Jamais archivées ni supprimées : réglages, journaux et suivis de la plateforme, sessions (fermées à
# part) et pièces comptables de SAWALI (règlements reçus, factures d'interventions, paiements en
# ligne, relances), qui doivent être conservées.
COLLECTIONS_CONSERVEES = frozenset({
    "settings", "sauvegardes_completes", "migration_programmation", "maintenance_plateforme",
    "maintenance_plateforme_journal", "sessions_comptes", "sessions_comptes_journal",
    "abonnements_grace_journal", JOURNAL, AVERTISSEMENTS, ETAT, "impersonation_journal",
    "activity_events", "demo_expiry_events",
    "connexions_journal", "connexions_ip_actions",   # lot 55 : journaux des connexions et des blocages d'IP
    "tenant_payments", "interventions_invoices", "payments", "payment_transactions",
    "billing_reminders", "contract_overdue_alerts",
})
# Champs gardés sur la fiche réduite d'un client archivé
CHAMPS_FICHE = (
    "id", "user_no", "email", "full_name", "company", "role", "phone", "whatsapp_number", "client_code",
    "contract_number", "contract_billing_period", "contract_amount", "contract_currency",
    "contract_signed_at", "last_payment_at", "created_at", "business_type",
)
DEMO_EMAIL = "demo@sawalismartsystems.com"

# Envois (configurés par server.py : email_service.send_email, _wa_send_text) et super-admin
_ENVOIS: Dict[str, Any] = {"email": None, "wa": None, "email_admin": ""}
_TACHES: Dict[str, asyncio.Task] = {}


def configurer(*, envoyer_email: Optional[Callable[..., Awaitable[bool]]] = None,
               envoyer_wa: Optional[Callable[..., Awaitable[dict]]] = None, email_admin: str = "") -> None:
    _ENVOIS.update(email=envoyer_email, wa=envoyer_wa, email_admin=(email_admin or "").strip())


def maintenant() -> datetime:
    """Horloge (remplaçable en test)."""
    return datetime.now(timezone.utc)


def _iso(d: Optional[datetime] = None) -> str:
    return (d or maintenant()).astimezone(timezone.utc).isoformat()


def _date_iso(v: Any) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date() if v else None
    except (TypeError, ValueError):
        try:
            return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None


def _fr(d: Optional[date]) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def _sc():
    """Module du lot 49 (R2, phrase, signature) : importé à la demande."""
    from routes import sauvegarde_complete as sc
    return sc


def borner_conservation(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return CONSERVATION_DEFAUT
    return min(CONSERVATION_MAX, max(CONSERVATION_MIN, n))


async def reglages() -> Dict[str, Any]:
    doc = await db.settings.find_one({"_id": "global"}, {
        "_id": 0, "cycle_vie_actif": 1, "cycle_vie_simulation": 1, "cycle_vie_conservation_jours": 1,
        "cycle_vie_frais_reouverture_montant": 1, "cycle_vie_frais_reouverture_devise": 1}) or {}
    montant = doc.get("cycle_vie_frais_reouverture_montant")
    try:
        montant = max(0.0, float(montant)) if montant is not None else 0.0
    except (TypeError, ValueError):
        montant = 0.0
    return {
        "actif": bool(doc.get("cycle_vie_actif", False)),                 # désactivé par défaut
        "simulation": bool(doc.get("cycle_vie_simulation", True)),        # simulation par défaut
        "conservation_jours": borner_conservation(doc.get("cycle_vie_conservation_jours", CONSERVATION_DEFAUT)),
        "frais_reouverture": {"montant": montant,
                              "devise": (doc.get("cycle_vie_frais_reouverture_devise") or DEVISE_DEFAUT).upper()[:8]},
    }


async def definir_reglages(**champs) -> Dict[str, Any]:
    maj: Dict[str, Any] = {}
    if champs.get("actif") is not None:
        maj["cycle_vie_actif"] = bool(champs["actif"])
    if champs.get("simulation") is not None:
        maj["cycle_vie_simulation"] = bool(champs["simulation"])
    if champs.get("conservation_jours") is not None:
        maj["cycle_vie_conservation_jours"] = borner_conservation(champs["conservation_jours"])
    if champs.get("frais_montant") is not None:
        maj["cycle_vie_frais_reouverture_montant"] = max(0.0, float(champs["frais_montant"]))
    if champs.get("frais_devise"):
        maj["cycle_vie_frais_reouverture_devise"] = str(champs["frais_devise"]).strip().upper()[:8]
    if maj:
        await db.settings.update_one({"_id": "global"}, {"$set": maj}, upsert=True)
    return await reglages()


async def assurer_index() -> None:
    try:
        await db[AVERTISSEMENTS].create_index("cle", unique=True)
        await db[JOURNAL].create_index([("client_id", 1), ("date", -1)])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cycle-vie] index non créés : %s", exc)


async def journaliser(action: str, client: Optional[dict], par: Optional[dict] = None, **extra) -> None:
    await db[JOURNAL].insert_one({
        "id": uuid.uuid4().hex, "action": action, "date": _iso(),
        "client_id": (client or {}).get("id"),
        "client_nom": (client or {}).get("company") or (client or {}).get("full_name"),
        "par": {"id": par.get("id"), "email": par.get("email")} if par else {"id": None, "email": "tâche automatique"},
        **extra})


async def journal(client_id: Optional[str] = None, limite: int = 100) -> list:
    filtre = {"client_id": client_id} if client_id else {}
    return await db[JOURNAL].find(filtre, {"_id": 0}).sort("date", -1).limit(limite).to_list(limite)


# ---------------------------------------------------------------------------
# Statut d'un client et contrôle de chaque requête
# ---------------------------------------------------------------------------
def cycle_de(client: Optional[dict]) -> dict:
    return (client or {}).get("cycle_vie") or {}


def statut_bloquant(client: Optional[dict], a: Optional[datetime] = None) -> Optional[str]:
    """SUSPENDU ou ARCHIVE si l'accès du client est fermé, sinon None.
    Une suspension prononcée pour une échéance qui a depuis été réglée (nouvelle échéance) ne bloque
    plus : le règlement saisi par l'Admin rend l'accès aussitôt."""
    cv = cycle_de(client)
    if cv.get("statut") == ARCHIVE:
        return ARCHIVE
    if cv.get("statut") == SUSPENDU:
        etat = abo.etat_client(client, a or maintenant())
        if etat.get("echeance") and etat["echeance"] == cv.get("echeance"):
            return SUSPENDU
    return None


def message_refus(client: dict, statut: str) -> str:
    nom = client.get("company") or client.get("full_name") or "votre client"
    if statut == ARCHIVE:
        return (f"Compte archivé : l'abonnement de {nom} n'a pas été renouvelé et ses données ont été archivées. "
                "Contactez SAWALI SMART SYSTEMS pour une réouverture.")
    ech = _date_iso(cycle_de(client).get("echeance"))
    return (f"Accès suspendu : l'abonnement de {nom} n'est pas renouvelé depuis l'échéance du {_fr(ech)}. "
            "Contactez SAWALI SMART SYSTEMS pour régulariser.")


async def controler(user: dict, jeton: dict, chemin: str = "") -> None:
    """Contrôle de chaque requête authentifiée (controle_acces) : 403 « abonnement_suspendu » pour tous
    les comptes d'un client suspendu ou archivé, sauf le super-admin et « Voir en tant que »."""
    if jeton.get("imp") or abo.est_super_admin(user):
        return
    cid = abo.client_id_de(user)
    if not cid:
        return
    client = await abo.fiche_client(cid, user)
    statut = statut_bloquant(client)
    if statut:
        raise RefusAcces(403, message_refus(client, statut), CODE_SUSPENDU)


async def refuser_connexion(user: dict) -> None:
    """Connexion (mot de passe, code e-mail, code WhatsApp) refusée pour un client suspendu ou archivé."""
    if not user or abo.est_super_admin(user):
        return
    cid = abo.client_id_de(user)
    if not cid:
        return
    client = await abo.fiche_client(cid, user, cache=False)
    statut = statut_bloquant(client)
    if statut:
        raise RefusAcces(403, message_refus(client, statut), CODE_SUSPENDU)


# ---------------------------------------------------------------------------
# Clients concernés
# ---------------------------------------------------------------------------
async def _domaines_internes() -> List[str]:
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "internal_domains": 1}) or {}
    return [d.strip().lower().lstrip("@") for d in (s.get("internal_domains") or "sawalismartsystems.com").split(",")
            if d.strip()]


def raison_exclusion(client: dict, domaines: List[str]) -> Optional[str]:
    email = (client.get("email") or "").strip().lower()
    if abo.est_super_admin(client):
        return "super-admin"
    if client.get("est_test"):
        return "client de test"
    if client.get("is_demo") or email == DEMO_EMAIL or client.get("source") == "wa_otp_login":
        return "compte de démonstration"
    if email.rsplit("@", 1)[-1] in domaines:
        return "compte interne"
    if client.get("role") not in ("client", "admin"):
        return f"rôle {client.get('role')}"
    return None


def _est_principal(u: dict) -> bool:
    parent = u.get("parent_client_id")
    return not parent or parent == u.get("id")


async def clients_suivis() -> List[dict]:
    """Comptes principaux sous contrat (périodicité + date) et clients déjà suspendus ou archivés."""
    filtre = {"$or": [
        {"contract_billing_period": {"$in": list(abo.PERIODES_JOURS)}},
        {"cycle_vie.statut": {"$in": [SUSPENDU, ARCHIVE]}},
    ]}
    docs = await db.users.find(filtre, {"_id": 0, "password_hash": 0}).to_list(10000)
    return [d for d in docs if _est_principal(d)]


def jours_depuis_echeance(client: dict, a: datetime) -> Optional[int]:
    etat = abo.etat_client(client, a)
    ech = _date_iso(etat.get("echeance"))
    return (a.date() - ech).days if ech else None


async def _avertissements(client_id: str, echeance: str) -> Dict[str, dict]:
    docs = await db[AVERTISSEMENTS].find({"client_id": client_id, "echeance": echeance}, {"_id": 0}).to_list(10)
    return {d["etape"]: d for d in docs}


def calendrier(client: dict, avertis: Dict[str, dict], a: datetime) -> Dict[str, Any]:
    """Dates prévues de chaque étape (au plus tôt), d'après l'échéance et ce qui a déjà été fait."""
    etat = abo.etat_client(client, a)
    ech = _date_iso(etat.get("echeance"))
    if not ech:
        return {}
    cv = cycle_de(client)
    auj = a.date()
    d103 = _date_iso((avertis.get("J103") or {}).get("le")) or max(ech + timedelta(days=J_AVERT_SUSPENSION), auj)
    d110 = _date_iso(cv.get("suspendu_le")) if cv.get("statut") in (SUSPENDU, ARCHIVE) and cv.get("echeance") == etat["echeance"] \
        else max(ech + timedelta(days=J_SUSPENSION), d103 + timedelta(days=PREAVIS_SUSPENSION_J))
    d112 = _date_iso((avertis.get("J112") or {}).get("le")) or max(ech + timedelta(days=J_AVERT_SUPPRESSION),
                                                                   d110 + timedelta(days=J_AVERT_SUPPRESSION - J_SUSPENSION))
    d113 = max(ech + timedelta(days=J_ARCHIVE), d110 + timedelta(days=DUREE_SUSPENSION_MIN_J),
               d112 + timedelta(days=PREAVIS_SUPPRESSION_J))
    return {"echeance": ech.isoformat(), "avertissement_suspension": d103.isoformat(), "suspension": d110.isoformat(),
            "avertissement_suppression": d112.isoformat(), "archivage": d113.isoformat()}


async def planifier(client: dict, a: datetime, domaines: List[str], conservation_jours: int) -> Dict[str, Any]:
    """Actions à faire aujourd'hui pour un client (sans rien faire)."""
    cv = cycle_de(client)
    nom = client.get("company") or client.get("full_name") or client.get("email")
    ligne: Dict[str, Any] = {"client_id": client["id"], "nom": nom, "email": client.get("email"),
                             "statut": cv.get("statut") or ACTIF, "actions": []}
    exclu = raison_exclusion(client, domaines)
    if exclu:
        ligne["exclu"] = exclu
        return ligne
    if cv.get("statut") == ARCHIVE:
        arch = cv.get("archive") or {}
        ligne["archive"] = arch
        le = _date_iso(arch.get("le"))
        if arch.get("cle") and not arch.get("effacee_le") and le and a.date() >= le + timedelta(days=conservation_jours):
            ligne["actions"].append("EFFACEMENT_ARCHIVE")
        return ligne
    etat = abo.etat_client(client, a)
    if etat["statut"] == abo.SANS_ECHEANCE:
        if cv.get("statut") == SUSPENDU:
            ligne["actions"].append("LEVEE_SANS_ECHEANCE")
        ligne["sans_echeance"] = True
        return ligne
    j = jours_depuis_echeance(client, a)
    ligne.update(echeance=etat["echeance"], jours=j)
    if cv.get("statut") == SUSPENDU and cv.get("echeance") != etat["echeance"]:
        ligne["actions"].append("LEVEE_PAIEMENT")
        return ligne
    if cv.get("leve_pour_echeance") == etat["echeance"]:
        ligne["leve_par_admin"] = True
        return ligne
    avertis = await _avertissements(client["id"], etat["echeance"])
    cal = calendrier(client, avertis, a)
    ligne["calendrier"] = cal
    ligne["avertissements"] = sorted(avertis)
    auj = a.date().isoformat()
    suspendu = cv.get("statut") == SUSPENDU
    if j is None or j < J_AVERT_SUSPENSION:
        return ligne
    if not suspendu:
        if "J103" not in avertis:
            ligne["actions"].append("AVERTISSEMENT_J103")
        elif j >= J_SUSPENSION and auj >= cal["suspension"]:
            ligne["actions"].append("SUSPENSION")
            if "J110" not in avertis:
                ligne["actions"].append("AVERTISSEMENT_J110")
        return ligne
    if "J110" not in avertis:
        ligne["actions"].append("AVERTISSEMENT_J110")
    if j >= J_AVERT_SUPPRESSION and "J112" not in avertis and auj >= cal["avertissement_suppression"]:
        ligne["actions"].append("AVERTISSEMENT_J112")
    elif j >= J_ARCHIVE and "J112" in avertis and auj >= cal["archivage"]:
        ligne["actions"].append("ARCHIVAGE")
    return ligne


# ---------------------------------------------------------------------------
# Avertissements à l'abonné (WhatsApp + e-mail, une seule fois chacun)
# ---------------------------------------------------------------------------
def texte_avertissement(etape: str, client: dict, cal: Dict[str, Any], reg: Dict[str, Any]) -> tuple:
    nom = client.get("full_name") or client.get("company") or client.get("email")
    societe = client.get("company") or nom
    ech = _fr(_date_iso(cal.get("echeance")))
    contrat = client.get("contract_number") or "—"
    frais = reg["frais_reouverture"]
    frais_txt = f"{frais['montant']:,.0f} {frais['devise']}".replace(",", " ") if frais["montant"] else "des frais de réouverture"
    if etape == "J103":
        sujet = f"[SAWALI] Abonnement impayé — suspension prévue le {_fr(_date_iso(cal['suspension']))}"
        corps = (f"Bonjour {nom},\n\nL'abonnement SAWALI de {societe} (contrat {contrat}) n'est pas réglé depuis "
                 f"l'échéance du {ech}.\nSans règlement, l'accès à votre espace sera SUSPENDU le "
                 f"{_fr(_date_iso(cal['suspension']))}, puis vos données seront archivées et supprimées de la "
                 f"plateforme le {_fr(_date_iso(cal['archivage']))}.\n\nPour régulariser, contactez "
                 "SAWALI SMART SYSTEMS.\n\nL'équipe SAWALI SMART SYSTEMS.")
    elif etape == "J110":
        sujet = "[SAWALI] Accès suspendu — abonnement non renouvelé"
        corps = (f"Bonjour {nom},\n\nL'abonnement SAWALI de {societe} (contrat {contrat}) n'est pas réglé depuis "
                 f"l'échéance du {ech} : l'accès à votre espace est SUSPENDU depuis aujourd'hui.\nVos données "
                 f"seront archivées puis supprimées de la plateforme le {_fr(_date_iso(cal['archivage']))}. "
                 "Un règlement avant cette date rétablit l'accès.\n\nL'équipe SAWALI SMART SYSTEMS.")
    else:
        sujet = "[SAWALI] Dernier avis — suppression de vos données demain"
        corps = (f"Bonjour {nom},\n\nDernier avis : l'abonnement SAWALI de {societe} (contrat {contrat}) n'est "
                 f"pas réglé depuis l'échéance du {ech}.\nDemain ({_fr(_date_iso(cal['archivage']))}), vos données "
                 "seront archivées (archive chiffrée) puis supprimées de la plateforme.\nAprès cette date, une "
                 f"réouverture restera possible pendant {reg['conservation_jours']} jours, moyennant {frais_txt}."
                 "\n\nL'équipe SAWALI SMART SYSTEMS.")
    return sujet, corps


async def envoyer_avertissement(etape: str, client: dict, echeance: str, cal: Dict[str, Any],
                                reg: Dict[str, Any]) -> Dict[str, Any]:
    """Envoi unique : la clé (client, échéance, étape) est réservée AVANT l'envoi."""
    cle = f"{client['id']}::{echeance}::{etape}"
    if await db[AVERTISSEMENTS].find_one({"cle": cle}, {"_id": 1}):
        return {"etape": etape, "deja_envoye": True}
    try:
        await db[AVERTISSEMENTS].insert_one({"cle": cle, "client_id": client["id"], "echeance": echeance,
                                             "etape": etape, "le": _iso()})
    except Exception:  # noqa: BLE001 — clé en double : un autre processus l'a envoyé
        return {"etape": etape, "deja_envoye": True}
    sujet, corps = texte_avertissement(etape, client, cal, reg)
    res: Dict[str, Any] = {"etape": etape, "email": False, "whatsapp": False}
    email = (client.get("email") or "").strip().lower()
    if email and _ENVOIS.get("email"):
        try:
            html = "<div style=\"font-family:Arial,sans-serif\">" + corps.replace("\n", "<br>") + "</div>"
            res["email"] = bool(await _ENVOIS["email"](email, sujet, html, corps))
        except Exception as exc:  # noqa: BLE001
            res["erreur_email"] = str(exc)[:200]
    numero = (client.get("whatsapp_number") or client.get("phone") or "").strip()
    if numero and _ENVOIS.get("wa"):
        try:
            r = await _ENVOIS["wa"](numero, corps)
            res["whatsapp"] = bool((r or {}).get("ok"))
            if not res["whatsapp"]:
                res["erreur_whatsapp"] = str((r or {}).get("error") or "")[:200]
        except Exception as exc:  # noqa: BLE001
            res["erreur_whatsapp"] = str(exc)[:200]
    await db[AVERTISSEMENTS].update_one({"cle": cle}, {"$set": {**res, "sujet": sujet, "texte": corps}})
    await journaliser(f"AVERTISSEMENT_{etape}", client, echeance=echeance, email=res["email"],
                      whatsapp=res["whatsapp"])
    return res


# ---------------------------------------------------------------------------
# Suspension et levée
# ---------------------------------------------------------------------------
async def comptes_du_client(client_id: str) -> Dict[str, List[str]]:
    """Comptes de connexion (users) et utilisateurs suivis (tracked_users) du client."""
    comptes = [u["id"] for u in await db.users.find(
        {"$or": [{"id": client_id}, {"parent_client_id": client_id}, {"client_id": client_id}]},
        {"_id": 0, "id": 1, "email": 1, "role": 1}).to_list(20000) if not abo.est_super_admin(u)]
    suivis = [t["id"] for t in await db.tracked_users.find(
        {"$or": [{"client_id": client_id}, {"parent_client_id": client_id}, {"user_account_id": {"$in": comptes}}]},
        {"_id": 0, "id": 1}).to_list(20000) if t.get("id")]
    return {"comptes": comptes, "suivis": suivis}


async def suspendre(client: dict, echeance: str, jours: int) -> None:
    import sessions_comptes as sess
    cv = {"statut": SUSPENDU, "echeance": echeance, "suspendu_le": _iso(), "jours_a_la_suspension": jours}
    await db.users.update_one({"id": client["id"]}, {"$set": {"cycle_vie": cv}})
    abo.vider_cache(client["id"])
    fermees = 0
    for uid in (await comptes_du_client(client["id"]))["comptes"]:
        fermees += await sess.fermer_compte(uid, sess.MOTIF_SUSPENSION)
    await journaliser("SUSPENSION", client, echeance=echeance, jours=jours, sessions_fermees=fermees)


async def lever_suspension(client: dict, motif: str, par: Optional[dict] = None) -> None:
    cv = cycle_de(client)
    etat = abo.etat_client(client)
    maj = {"cycle_vie": {"statut": ACTIF, "leve_le": _iso(), "motif_levee": motif,
                         "suspension_precedente": {k: cv.get(k) for k in ("echeance", "suspendu_le")},
                         **({"leve_pour_echeance": etat.get("echeance")} if par else {})}}
    await db.users.update_one({"id": client["id"]}, {"$set": maj})
    abo.vider_cache(client["id"])
    await journaliser("SUSPENSION_LEVEE", client, par, motif=motif)


# ---------------------------------------------------------------------------
# Archive du client : collecte, écriture chiffrée, relecture vérifiée
# ---------------------------------------------------------------------------
async def _collections() -> List[str]:
    return [n for n in await _sc()._collections() if n not in COLLECTIONS_CONSERVEES]


async def collecter(client_id: str) -> Dict[str, Any]:
    """Filtre de chaque collection qui contient des données du client, et nombres de documents."""
    cpt = await comptes_du_client(client_id)
    ids = sorted(set(cpt["comptes"]) | set(cpt["suivis"]) | {client_id})
    proprio = [{c: {"$in": ids}} for c in CHAMPS_PROPRIETAIRE]
    parents: Dict[str, List[str]] = {}
    for champ, coll in CHAMPS_ENFANTS.items():
        parents[champ] = [d["id"] for d in await db[coll].find({"$or": proprio}, {"_id": 0, "id": 1}).to_list(100000)
                          if d.get("id")]
    enfants = [{champ: {"$in": vals}} for champ, vals in parents.items() if vals]
    filtres: Dict[str, dict] = {}
    nombres: Dict[str, int] = {}
    for nom in await _collections():
        conditions = list(proprio) + list(enfants)
        if nom == "users":
            conditions.append({"id": {"$in": cpt["comptes"]}})
        elif nom == "tracked_users":
            conditions.append({"id": {"$in": cpt["suivis"]}})
        filtre = {"$or": conditions}
        n = await db[nom].count_documents(filtre)
        if n:
            filtres[nom], nombres[nom] = filtre, n
    return {"filtres": filtres, "nombres": nombres, "comptes": cpt["comptes"], "suivis": cpt["suivis"]}


def _empreinte(ids: List[Any]) -> str:
    cles = sorted(json_util.dumps(i, json_options=sf_canonique()) for i in ids)
    return hashlib.sha256("\n".join(cles).encode("utf-8")).hexdigest()


def sf_canonique():
    return json_util.CANONICAL_JSON_OPTIONS


def _serialiser(docs: List[dict]) -> bytes:
    return "".join(json_util.dumps(d, json_options=sf_canonique(), ensure_ascii=False) + "\n" for d in docs).encode("utf-8")


async def ecrire_archive(chemin: Path, client: dict, collecte: Dict[str, Any], phrase: str,
                         signature: Optional[bytes]) -> Dict[str, Any]:
    """Écrit l'archive chiffrée (format du lot 49). Renvoie le manifeste (nombres et empreintes)."""
    manifeste: Dict[str, Any] = {
        "format": FORMAT_ARCHIVE, "version": 1, "cree_le": _iso(), "client_id": client["id"],
        "client_nom": client.get("company") or client.get("full_name"), "client_email": client.get("email"),
        "echeance": cycle_de(client).get("echeance"), "base": os.environ.get("DB_NAME", ""),
        "signe": signature is not None, "collections": {}}

    def ouvrir():
        sortie = open(chemin, "wb")  # noqa: SIM115 — fermé plus bas
        try:
            os.chmod(chemin, 0o600)
        except OSError:
            pass
        ecrivain = sf.EcrivainChiffre(sortie, phrase, signature=signature)
        return sortie, ecrivain, zipfile.ZipFile(ecrivain, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6)

    sortie, ecrivain, archive = await asyncio.to_thread(ouvrir)
    try:
        for nom, filtre in collecte["filtres"].items():
            entree = await asyncio.to_thread(archive.open, f"collections/{nom}.jsonl", "w", force_zip64=True)
            ids, lot = [], []
            async for doc in db[nom].find(filtre, batch_size=LOT_LECTURE):
                lot.append(doc)
                ids.append(doc.get("_id"))
                if len(lot) >= LOT_LECTURE:
                    await asyncio.to_thread(entree.write, _serialiser(lot))
                    lot = []
            if lot:
                await asyncio.to_thread(entree.write, _serialiser(lot))
            await asyncio.to_thread(entree.close)
            manifeste["collections"][nom] = {"documents": len(ids), "empreinte": _empreinte(ids)}
        manifeste["total_documents"] = sum(c["documents"] for c in manifeste["collections"].values())
        await asyncio.to_thread(archive.writestr, "manifeste.json", json.dumps(manifeste, ensure_ascii=False, indent=1))

        def fermer():
            archive.close()
            ecrivain.close()
            sortie.close()
        await asyncio.to_thread(fermer)
    except BaseException:
        try:
            sortie.close()
        finally:
            _effacer(chemin)
        raise
    return manifeste


def relire_archive(chemin: Path, phrase: str, signature: Optional[bytes], avec_documents: bool = False) -> Dict[str, Any]:
    """Déchiffre et contrôle toute l'archive (intégrité GCM, signature), puis relit chaque collection.
    Renvoie {"manifeste", "ids": {collection: [_id]}, "signature"} (+ "documents" si demandé)."""
    lecteur = sf.LecteurChiffre(str(chemin), phrase)
    try:
        etat_sig = lecteur.verifier(signature)
        if etat_sig not in ("valide", "absente") or (signature is not None and etat_sig != "valide"):
            raise sf.FichierAltere(f"Signature de l'archive : {etat_sig}")
        with zipfile.ZipFile(lecteur) as archive:
            try:
                manifeste = json.loads(archive.read("manifeste.json"))
            except KeyError as exc:
                raise sf.FichierAltere("Manifeste absent de l'archive") from exc
            if manifeste.get("format") != FORMAT_ARCHIVE:
                raise sf.ErreurSauvegarde("Ce fichier n'est pas une archive de client SAWALI")
            ids: Dict[str, List[Any]] = {}
            documents: Dict[str, List[dict]] = {}
            for nom in manifeste.get("collections") or {}:
                try:
                    brut = archive.open(f"collections/{nom}.jsonl")
                except KeyError as exc:
                    raise sf.FichierAltere(f"Collection {nom} absente de l'archive") from exc
                with brut:
                    liste, docs = [], []
                    for ligne in io.TextIOWrapper(brut, encoding="utf-8"):
                        if ligne.strip():
                            d = json_util.loads(ligne, json_options=sf_canonique())
                            liste.append(d.get("_id"))
                            if avec_documents:
                                docs.append(d)
                    ids[nom] = liste
                    if avec_documents:
                        documents[nom] = docs
    finally:
        lecteur.close()
    res = {"manifeste": manifeste, "ids": ids, "signature": etat_sig}
    if avec_documents:
        res["documents"] = documents
    return res


def comparer(manifeste: Dict[str, Any], relu: Dict[str, Any]) -> List[str]:
    """Écarts entre ce qui a été écrit (manifeste de l'écriture) et ce qui a été relu."""
    ecarts = []
    attendu = manifeste.get("collections") or {}
    if set(attendu) != set(relu["ids"]):
        ecarts.append(f"collections différentes : {sorted(set(attendu) ^ set(relu['ids']))[:5]}")
    for nom, info in attendu.items():
        ids = relu["ids"].get(nom, [])
        if len(ids) != int(info.get("documents") or 0):
            ecarts.append(f"{nom} : {info.get('documents')} écrits, {len(ids)} relus")
        elif _empreinte(ids) != info.get("empreinte"):
            ecarts.append(f"{nom} : identifiants différents")
        if (relu["manifeste"].get("collections") or {}).get(nom, {}).get("empreinte") != info.get("empreinte"):
            ecarts.append(f"{nom} : manifeste relu différent")
    return ecarts


def _effacer(chemin: Path) -> None:
    try:
        chemin.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("[cycle-vie] fichier %s non effacé : %s", chemin, exc)


def _nom_cle(client_id: str) -> str:
    sur = re.sub(r"[^A-Za-z0-9_.-]", "_", client_id)[:80] or "client"
    return f"{PREFIXE_ARCHIVES}{sur}/sawali-client-{maintenant():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.sawali"


def raison_archive_impossible() -> Optional[str]:
    """Phrase SAUVEGARDE_AUTO_PHRASE et R2 obligatoires (mêmes règles que la sauvegarde du lot 49)."""
    return _sc().raison_auto_desactivee()


def _fiche_reduite(original: dict, cv: dict) -> dict:
    fiche = {k: original.get(k) for k in CHAMPS_FICHE if k in original}
    fiche.update({"_id": original["_id"], "account_status": "archive", "password_hash": "", "cycle_vie": cv,
                  "updated_at": _iso()})
    return fiche


async def _supprimer_par_id(nom: str, ids: List[Any], sauf: Any = None) -> int:
    n = 0
    liste = [i for i in ids if i != sauf] if sauf is not None else list(ids)
    for k in range(0, len(liste), LOT_ECRITURE):
        r = await db[nom].delete_many({"_id": {"$in": liste[k:k + LOT_ECRITURE]}})
        n += r.deleted_count
    return n


async def archiver(client: dict) -> Dict[str, Any]:
    """J+113 : archive chiffrée → R2 → relecture vérifiée → suppression. Rien n'est supprimé si une
    étape échoue. Renvoie {"ok": bool, ...}."""
    import sessions_comptes as sess
    sc = _sc()
    raison = raison_archive_impossible()
    if raison:
        return {"ok": False, "erreur": f"Archivage impossible : {raison}", "supprime": False}
    cfg = sc.config_r2()
    phrase, signature = sc._phrase_auto(), sc._cle_signature()
    original = await db.users.find_one({"id": client["id"]})
    if not original:
        return {"ok": False, "erreur": "Fiche du client introuvable", "supprime": False}
    cle = _nom_cle(client["id"])
    chemin = EXPORTS_DIR / f"archive-client-{secrets.token_hex(6)}.sawali"
    relecture = EXPORTS_DIR / f"archive-client-relue-{secrets.token_hex(6)}.sawali"
    debut = time.monotonic()
    try:
        collecte = await collecter(client["id"])
        manifeste = await ecrire_archive(chemin, client, collecte, phrase, signature)
        taille = chemin.stat().st_size
        r2 = sc._FABRIQUE_R2["client"](cfg)
        await asyncio.to_thread(r2.upload_file, str(chemin), cfg["bucket"], cle,
                                ExtraArgs={"ContentType": "application/octet-stream"})
        tete = await asyncio.to_thread(r2.head_object, Bucket=cfg["bucket"], Key=cle)
        if int(tete.get("ContentLength", -1)) != taille:
            raise sf.ErreurSauvegarde("Taille de l'archive dans R2 différente : envoi incomplet")
        # Relecture depuis R2 (et non depuis le disque local) : c'est cette copie qui sera conservée
        await asyncio.to_thread(r2.download_file, cfg["bucket"], cle, str(relecture))
        relu = await asyncio.to_thread(relire_archive, relecture, phrase, signature)
        ecarts = comparer(manifeste, relu)
        if ecarts:
            raise sf.ErreurSauvegarde("Vérification de l'archive en échec : " + " ; ".join(ecarts[:5]))
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cycle-vie] archivage du client %s en échec", client.get("id"))
        return {"ok": False, "erreur": str(exc)[:500], "supprime": False, "cle": cle}
    finally:
        _effacer(chemin)
        _effacer(relecture)
    # --- Vérification réussie : suppression des seuls documents relus dans l'archive ---
    supprimes: Dict[str, int] = {}
    for nom, ids in relu["ids"].items():
        sauf = original["_id"] if nom == "users" else None
        supprimes[nom] = await _supprimer_par_id(nom, ids, sauf=sauf)
    for uid in collecte["comptes"]:
        await sess.fermer_compte(uid, sess.MOTIF_SUSPENSION)
    await db.sessions_comptes.delete_many({"user_id": {"$in": collecte["comptes"]}})
    cv = {**cycle_de(client), "statut": ARCHIVE, "archive": {
        "cle": cle, "bucket": cfg["bucket"], "le": _iso(), "taille": taille,
        "documents": manifeste["total_documents"],
        "comptes": {n: c["documents"] for n, c in manifeste["collections"].items()},
        "signature": relu["signature"], "duree_s": round(time.monotonic() - debut, 1)}}
    await db.users.replace_one({"_id": original["_id"]}, _fiche_reduite(original, cv))
    abo.vider_cache(client["id"])
    return {"ok": True, "supprime": True, "cle": cle, "taille": taille, "documents": manifeste["total_documents"],
            "comptes": cv["archive"]["comptes"], "supprimes": supprimes}


async def effacer_archive(client: dict) -> Dict[str, Any]:
    """Fin de la conservation : effacement de l'archive dans R2 (seulement une clé du bon format)."""
    sc = _sc()
    arch = cycle_de(client).get("archive") or {}
    cle = arch.get("cle") or ""
    if not RE_CLE_ARCHIVE.fullmatch(cle):
        return {"ok": False, "erreur": "Référence d'archive inattendue : rien n'est effacé"}
    cfg = sc.config_r2()
    if not cfg:
        return {"ok": False, "erreur": "Cloudflare R2 non configuré"}
    try:
        r2 = sc._FABRIQUE_R2["client"](cfg)
        await asyncio.to_thread(r2.delete_objects, Bucket=arch.get("bucket") or cfg["bucket"],
                                Delete={"Objects": [{"Key": cle}], "Quiet": True})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erreur": str(exc)[:300]}
    await db.users.update_one({"id": client["id"]}, {"$set": {"cycle_vie.archive.effacee_le": _iso()}})
    await journaliser("ARCHIVE_EFFACEE", client, cle=cle)
    return {"ok": True, "cle": cle}


# ---------------------------------------------------------------------------
# Réouverture (super-admin) : frais de réouverture puis restauration de l'archive
# ---------------------------------------------------------------------------
async def reouvrir(client_id: str, adm: dict, reference: str = "") -> Dict[str, Any]:
    sc = _sc()
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client or abo.est_super_admin(client):
        raise RefusAcces(404, "Client introuvable")
    cv = cycle_de(client)
    if cv.get("statut") == SUSPENDU:
        raise RefusAcces(409, "Client suspendu mais pas archivé : utilisez « Lever la suspension » ou saisissez le règlement")
    if cv.get("statut") != ARCHIVE:
        raise RefusAcces(409, "Ce client n'est pas archivé")
    arch = cv.get("archive") or {}
    if arch.get("effacee_le") or not arch.get("cle"):
        raise RefusAcces(409, "L'archive de ce client a été effacée (fin de la conservation) : réouverture impossible")
    raison = raison_archive_impossible()
    if raison:
        raise RefusAcces(503, f"Réouverture impossible : {raison}")
    cfg = sc.config_r2()
    reg = await reglages()
    chemin = EXPORTS_DIR / f"reouverture-{secrets.token_hex(6)}.sawali"
    try:
        r2 = sc._FABRIQUE_R2["client"](cfg)
        await asyncio.to_thread(r2.download_file, arch.get("bucket") or cfg["bucket"], arch["cle"], str(chemin))
        relu = await asyncio.to_thread(relire_archive, chemin, sc._phrase_auto(), sc._cle_signature(), True)
    except Exception as exc:  # noqa: BLE001
        await journaliser("REOUVERTURE_ECHEC", client, adm, erreur=str(exc)[:300])
        raise RefusAcces(502, f"Archive illisible ou introuvable : {str(exc)[:300]}") from exc
    finally:
        _effacer(chemin)
    if relu["manifeste"].get("client_id") != client_id:
        raise RefusAcces(409, "Cette archive n'est pas celle de ce client")
    attendus = {n: c.get("documents") for n, c in (relu["manifeste"].get("collections") or {}).items()}
    if any(len(relu["ids"].get(n, [])) != int(v or 0) for n, v in attendus.items()):
        raise RefusAcces(409, "Archive incomplète : réouverture annulée, rien n'a été modifié")
    # --- Restauration : remplacement limité aux documents du client ---
    restaures: Dict[str, int] = {}
    for nom, docs in relu["documents"].items():
        ids = [d.get("_id") for d in docs]
        await _supprimer_par_id(nom, ids)
        for k in range(0, len(docs), LOT_ECRITURE):
            await db[nom].insert_many(docs[k:k + LOT_ECRITURE], ordered=False)
        restaures[nom] = await db[nom].count_documents({"_id": {"$in": ids}}) if ids else 0
    aujourdhui = maintenant().date().isoformat()
    frais = reg["frais_reouverture"]
    if frais["montant"] > 0:
        await db.tenant_payments.insert_one({
            "id": uuid.uuid4().hex, "tenant_id": client_id, "payment_date": aujourdhui,
            "invoice_ref": (reference or "").strip() or None, "amount_due": frais["montant"],
            "amount_paid": frais["montant"], "currency": frais["devise"], "type": "frais_reouverture",
            "notes": f"Frais de réouverture ({frais['montant']:g} {frais['devise']}) après archivage",
            "created_by_id": adm.get("id"), "created_by_email": adm.get("email"), "created_at": _iso()})
    nouveau_cv = {"statut": ACTIF, "reouvert_le": _iso(), "reouvert_par": adm.get("email"),
                  "archive_precedente": {**arch, "restauree_le": _iso()}}
    await db.users.update_one({"id": client_id}, {
        "$set": {"cycle_vie": nouveau_cv, "last_payment_at": aujourdhui, "account_status": "active",
                 "updated_at": _iso()},
        "$unset": {"abonnement_grace_renouvellements": ""}})
    abo.vider_cache(client_id)
    await journaliser("REOUVERTURE", client, adm, frais=frais, reference=reference or None,
                      documents=sum(restaures.values()), cle=arch.get("cle"))
    return {"ok": True, "restaures": restaures, "documents": sum(restaures.values()), "frais": frais,
            "nouvelle_reference_echeance": aujourdhui}


# ---------------------------------------------------------------------------
# Tâche quotidienne
# ---------------------------------------------------------------------------
async def _prendre_verrou(duree_s: int = 6 * 3600) -> bool:
    a = _iso()
    try:
        await db[ETAT].find_one_and_update(
            {"_id": "verrou", "$or": [{"jusqu_a": {"$lt": a}}, {"jusqu_a": {"$exists": False}}]},
            {"$set": {"jusqu_a": _iso(maintenant() + timedelta(seconds=duree_s))}}, upsert=True)
        return True
    except Exception:  # noqa: BLE001 — clé en double : tâche déjà en cours
        return False


async def _rendre_verrou() -> None:
    await db[ETAT].update_one({"_id": "verrou"}, {"$set": {"jusqu_a": _iso(maintenant() - timedelta(seconds=1))}})


async def executer(declencheur: str = "cron:quotidien", simulation: Optional[bool] = None) -> Dict[str, Any]:
    """Passe sur tous les clients suivis. `simulation=True` force la simulation (même interrupteur
    désactivé) ; sinon l'interrupteur et le mode simulation des réglages s'appliquent."""
    reg = await reglages()
    forcee = simulation is True
    if not reg["actif"] and not forcee:
        await db[ETAT].update_one({"_id": "derniere_execution"}, {"$set": {
            "le": _iso(), "statut": "DESACTIVE", "declencheur": declencheur}}, upsert=True)
        return {"statut": "DESACTIVE", "actions": [], "alertes": []}
    simuler = forcee or reg["simulation"]
    if not simuler and not await _prendre_verrou():
        return {"statut": "DEJA_EN_COURS", "actions": [], "alertes": []}
    a = maintenant()
    domaines = await _domaines_internes()
    rapport: Dict[str, Any] = {"le": _iso(a), "declencheur": declencheur, "simulation": simuler,
                               "actions": [], "alertes": [], "exclus": 0, "clients": 0}
    try:
        for client in await clients_suivis():
            ligne = await planifier(client, a, domaines, reg["conservation_jours"])
            rapport["clients"] += 1
            if ligne.get("exclu"):
                rapport["exclus"] += 1
                continue
            for action in ligne["actions"]:
                entree = {"client_id": client["id"], "nom": ligne["nom"], "action": action,
                          "jours": ligne.get("jours"), "echeance": ligne.get("echeance"), "effectuee": False}
                if not simuler:
                    try:
                        entree.update(await _faire(action, client, ligne, reg))
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("[cycle-vie] %s en échec pour %s", action, client.get("id"))
                        entree.update(effectuee=False, erreur=str(exc)[:300])
                    if entree.get("erreur"):
                        rapport["alertes"].append(f"{ligne['nom']} — {action} : {entree['erreur']}")
                rapport["actions"].append(entree)
        rapport["statut"] = "SIMULATION" if simuler else "TERMINE"
    finally:
        if not simuler:
            await _rendre_verrou()
    rapport["email_envoye"] = await rapport_email(rapport)
    await db[ETAT].update_one({"_id": "derniere_execution"}, {"$set": rapport}, upsert=True)
    if not simuler:
        await journaliser("EXECUTION", None, None, actions=len(rapport["actions"]), alertes=len(rapport["alertes"]),
                          declencheur=declencheur)
    return rapport


async def _faire(action: str, client: dict, ligne: Dict[str, Any], reg: Dict[str, Any]) -> Dict[str, Any]:
    cal = ligne.get("calendrier") or {}
    if action.startswith("AVERTISSEMENT_"):
        etape = action.split("_", 1)[1]
        res = await envoyer_avertissement(etape, client, ligne["echeance"], cal, reg)
        return {"effectuee": True, "email": res.get("email"), "whatsapp": res.get("whatsapp")}
    if action == "SUSPENSION":
        await suspendre(client, ligne["echeance"], ligne["jours"])
        return {"effectuee": True}
    if action in ("LEVEE_PAIEMENT", "LEVEE_SANS_ECHEANCE"):
        await lever_suspension(client, "règlement saisi (nouvelle échéance)" if action == "LEVEE_PAIEMENT"
                               else "client sans échéance")
        return {"effectuee": True}
    if action == "ARCHIVAGE":
        fiche = await db.users.find_one({"id": client["id"]}, {"_id": 0, "password_hash": 0}) or client
        res = await archiver(fiche)
        if res["ok"]:
            await journaliser("ARCHIVAGE", client, cle=res["cle"], documents=res["documents"],
                              comptes=res["comptes"], supprimes=res["supprimes"])
            return {"effectuee": True, "cle": res["cle"], "documents": res["documents"]}
        await journaliser("ARCHIVAGE_ECHEC", client, erreur=res["erreur"], rien_supprime=True)
        await alerter_super_admin(client, res["erreur"])
        return {"effectuee": False, "erreur": res["erreur"] + " — rien n'a été supprimé"}
    if action == "EFFACEMENT_ARCHIVE":
        res = await effacer_archive(client)
        return {"effectuee": res["ok"], **({"erreur": res["erreur"]} if not res["ok"] else {"cle": res["cle"]})}
    return {"effectuee": False, "erreur": f"action inconnue {action}"}


# ---------------------------------------------------------------------------
# Rapport et alertes au super-admin
# ---------------------------------------------------------------------------
LIBELLES = {
    "AVERTISSEMENT_J103": "Avertissement J+103 (suspension dans 7 jours)",
    "AVERTISSEMENT_J110": "Avertissement J+110 (accès suspendu)",
    "AVERTISSEMENT_J112": "Avertissement J+112 (suppression demain)",
    "SUSPENSION": "Suspension (J+110)", "ARCHIVAGE": "Archivage puis suppression (J+113)",
    "LEVEE_PAIEMENT": "Suspension levée (règlement saisi)", "LEVEE_SANS_ECHEANCE": "Suspension levée (sans échéance)",
    "EFFACEMENT_ARCHIVE": "Effacement de l'archive (fin de conservation)",
}


async def rapport_email(rapport: Dict[str, Any]) -> bool:
    envoyer, adresse = _ENVOIS.get("email"), _ENVOIS.get("email_admin")
    if not envoyer or not adresse:
        return False
    a = datetime.fromisoformat(rapport["le"])
    mode = " (SIMULATION : rien n'a été fait)" if rapport["simulation"] else ""
    alerte = " — ALERTE" if rapport["alertes"] else ""
    sujet = f"[SAWALI] Cycle de vie des abonnements — {a:%d/%m/%Y}{mode}{alerte}"
    lignes = [f"{LIBELLES.get(x['action'], x['action'])} — {x['nom']}"
              + (f" (J+{x['jours']})" if x.get("jours") is not None else "")
              + ("" if rapport["simulation"] else (" : fait" if x.get("effectuee") else f" : ÉCHEC {x.get('erreur', '')}"))
              for x in rapport["actions"]]
    texte = (f"Cycle de vie des abonnements — {a:%d/%m/%Y %H:%M} UTC{mode}\n"
             f"Clients examinés : {rapport['clients']} (dont {rapport['exclus']} exclus : test, démo, internes)\n\n"
             + ("\n".join(lignes) if lignes else "Aucune action aujourd'hui.")
             + ("\n\nALERTES :\n" + "\n".join(rapport["alertes"]) if rapport["alertes"] else ""))
    html = "<div style=\"font-family:Arial,sans-serif\">" + texte.replace("\n", "<br>") + "</div>"
    try:
        return bool(await envoyer(adresse, sujet, html, texte))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cycle-vie] rapport non envoyé : %s", exc)
        return False


async def alerter_super_admin(client: dict, erreur: str) -> bool:
    envoyer, adresse = _ENVOIS.get("email"), _ENVOIS.get("email_admin")
    nom = client.get("company") or client.get("full_name") or client.get("email")
    if not envoyer or not adresse:
        return False
    texte = (f"ALERTE : l'archivage du client « {nom} » a échoué. AUCUNE donnée n'a été supprimée.\n\n"
             f"Erreur : {erreur}\n\nL'archivage sera retenté à la prochaine exécution. Paramètres → "
             "Cycle de vie des abonnements.")
    try:
        return bool(await envoyer(adresse, f"[SAWALI] ALERTE — archivage du client {nom} en échec",
                                  "<div style=\"font-family:Arial,sans-serif\">" + texte.replace("\n", "<br>") + "</div>",
                                  texte))
    except Exception:  # noqa: BLE001
        return False


async def vue_admin() -> Dict[str, Any]:
    """Liste du super-admin : clients en retard, suspendus ou archivés, avec le calendrier."""
    reg = await reglages()
    a = maintenant()
    domaines = await _domaines_internes()
    lignes = []
    for client in await clients_suivis():
        ligne = await planifier(client, a, domaines, reg["conservation_jours"])
        cv = cycle_de(client)
        jours = jours_depuis_echeance(client, a)
        if cv.get("statut") not in (SUSPENDU, ARCHIVE) and (jours or 0) < 1:
            continue  # à jour, en avance ou sans échéance : rien à montrer
        ligne.setdefault("echeance", abo.etat_client(client, a).get("echeance"))
        ligne["jours"] = jours
        ligne["suspendu_le"] = cv.get("suspendu_le")
        if cv.get("statut") == ARCHIVE:
            arch = cv.get("archive") or {}
            le = _date_iso(arch.get("le"))
            ligne["archive"] = {**arch, "conservation_jusqu_au": (le + timedelta(days=reg["conservation_jours"])).isoformat()
                                if le else None}
        lignes.append(ligne)
    ordre = {ARCHIVE: 0, SUSPENDU: 1}
    lignes.sort(key=lambda x: (ordre.get(x["statut"], 2), -(x.get("jours") or 0), (x.get("nom") or "").lower()))
    derniere = await db[ETAT].find_one({"_id": "derniere_execution"}, {"_id": 0}) or None
    return {"reglages": reg, "clients": lignes, "derniere_execution": derniere,
            "archive_impossible": raison_archive_impossible(),
            "calendrier": {"avertissement_suspension": J_AVERT_SUSPENSION, "suspension": J_SUSPENSION,
                           "avertissement_suppression": J_AVERT_SUPPRESSION, "archivage": J_ARCHIVE},
            "conservation": {"min": CONSERVATION_MIN, "max": CONSERVATION_MAX, "defaut": CONSERVATION_DEFAUT}}


def lancer_en_fond(declencheur: str) -> bool:
    """« Lancer maintenant » : exécution réelle en tâche de fond (l'archivage peut être long)."""
    if any(not t.done() for t in _TACHES.values()):
        return False
    tache = asyncio.get_running_loop().create_task(executer(declencheur))
    _TACHES[uuid.uuid4().hex] = tache
    tache.add_done_callback(lambda t: [_TACHES.pop(k, None) for k, v in list(_TACHES.items()) if v is t])
    return True
