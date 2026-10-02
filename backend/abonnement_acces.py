"""Lot 50 — A. Période de grâce après une échéance impayée, puis coupure côté serveur.

Abonnement d'un client SAWALI (logique existante, inchangée) : la fiche client porte la
périodicité `contract_billing_period` (monthly 30 j / quarterly 90 j / annual 365 j) et la
date du dernier règlement `last_payment_at` (à défaut la date de signature
`contract_signed_at`). Échéance = date de référence + période (même calcul que les rappels de
facturation du planificateur). Un règlement enregistré par l'Admin (Admin → Clients → paiement)
met `last_payment_at` à jour et repousse donc l'échéance.

- Le jour de l'échéance est payable ; dès le lendemain 00:00 (UTC, heure de Ouagadougou et
  d'Abidjan), l'échéance est impayée : période de grâce de N jours (3 par défaut, réglable par
  client par l'Admin, de 0 à 30 j). Pendant la grâce : accès normal + bandeau rouge
  « Abonnement expiré — N jour(s) de grâce restant(s) — Renouveler ».
- L'Admin peut « Renouveler la grâce (+3 j) » sur un abonnement en échec, au plus 3 fois par
  échéance impayée. Le compteur est lié à l'échéance : il repart de zéro au paiement (nouvelle
  échéance). Chaque action est journalisée (`abonnements_grace_journal`).
- Après la grâce : coupure CÔTÉ SERVEUR, à chaque requête (petit cache de 30 s sur la fiche
  du client, l'heure est comparée à chaque requête : la coupure tombe à l'heure exacte), pour
  tous les comptes du client (compte principal, y compris un compte client de rôle `admin`,
  et utilisateurs suivis) — jamais pour le super-admin SAWALI (SUPER_ADMIN_EMAIL), ni pour une
  session « Voir en tant que ». Les comptes internes de SAWALI n'ont pas d'échéance : ils ne
  sont jamais coupés. Réponse
  402, code « abonnement_expire ». Seules restent ouvertes les routes de l'écran
  « Abonnement expiré » : profil minimal (/api/auth/me), état de l'abonnement, sessions,
  déconnexion (ROUTES_OUVERTES).
- Un client sans périodicité ou sans date de référence n'a pas d'échéance : jamais coupé.
- La suspension manuelle et la suspension automatique existantes (account_status
  « suspended ») ne changent pas.

INTERRUPTEUR GÉNÉRAL `abonnement_coupure_active` (Paramètres, désactivé par défaut) : même
prudence qu'au lot 27 pour la suspension automatique — des règlements ont pu ne pas être saisis.
Tant qu'il est désactivé, l'Admin voit l'état de chaque client (liste « Abonnements ») mais les
clients ne voient ni bandeau ni coupure.
"""
from __future__ import annotations

import math
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from db import db
from controle_acces import RefusAcces

PERIODES_JOURS = {"monthly": 30, "quarterly": 90, "annual": 365}
LIBELLES_PERIODES = {"monthly": "mensuel", "quarterly": "trimestriel", "annual": "annuel"}
GRACE_DEFAUT, GRACE_MIN, GRACE_MAX = 3, 0, 30
RENOUVELLEMENT_JOURS = 3
RENOUVELLEMENTS_MAX = 3
JOURNAL = "abonnements_grace_journal"
CODE_EXPIRE = "abonnement_expire"
DUREE_CACHE_S = 30.0

A_JOUR, GRACE, EXPIRE, SANS_ECHEANCE = "a_jour", "grace", "expire", "sans_echeance"

# Routes laissées ouvertes après la grâce (préfixes de chemin, sans barre finale)
ROUTES_OUVERTES = (
    "/api/auth/",                       # profil minimal (/auth/me), déconnexion, mot de passe
    "/api/me/abonnement",               # état de l'abonnement (écran « Renouveler »)
    "/api/me/sessions",                 # sessions du compte
    "/api/me/activite",
    "/api/me/idle-config",
    "/api/me/derniere-sauvegarde",
    "/api/me/tenant-meta",
    "/api/me/access-log",               # journaux techniques du navigateur
    "/api/me/api-trace",
    "/api/voir-en-tant-que/",
)

_cache_clients: Dict[str, tuple] = {}
_cache_reglages: Dict[str, Any] = {"lu_a": 0.0, "doc": None}


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def vider_cache(client_id: Optional[str] = None) -> None:
    if client_id:
        _cache_clients.pop(client_id, None)
    else:
        _cache_clients.clear()
    _cache_reglages.update(lu_a=0.0, doc=None)


async def reglages() -> dict:
    if _cache_reglages["doc"] is not None and time.monotonic() - _cache_reglages["lu_a"] < DUREE_CACHE_S:
        return _cache_reglages["doc"]
    doc = await db.settings.find_one({"_id": "global"}, {"_id": 0, "abonnement_coupure_active": 1}) or {}
    _cache_reglages.update(lu_a=time.monotonic(), doc=doc)
    return doc


async def coupure_active() -> bool:
    return bool((await reglages()).get("abonnement_coupure_active"))


async def definir_coupure(active: bool) -> bool:
    await db.settings.update_one({"_id": "global"}, {"$set": {"abonnement_coupure_active": bool(active)}},
                                 upsert=True)
    vider_cache()
    return bool(active)


def est_super_admin(user: dict) -> bool:
    """Super-admin SAWALI (même règle que server._is_super_admin)."""
    from auth import est_super_admin as _est
    return _est(user)


def client_id_de(user: dict) -> Optional[str]:
    """Client (locataire) d'un compte : son client parent, sinon le compte lui-même."""
    return user.get("parent_client_id") or user.get("client_id") or user.get("id")


def borner_grace(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return GRACE_DEFAUT
    return min(GRACE_MAX, max(GRACE_MIN, n))


def _date_ref(client: dict) -> Optional[date]:
    ref = str(client.get("last_payment_at") or client.get("contract_signed_at") or "")[:10]
    try:
        return datetime.strptime(ref, "%Y-%m-%d").date() if ref else None
    except ValueError:
        return None


def _minuit(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def etat_client(client: dict, a: Optional[datetime] = None) -> Dict[str, Any]:
    """État de l'abonnement d'un client (fiche `users` du compte principal) à l'instant `a`."""
    a = a or maintenant()
    periode = (client.get("contract_billing_period") or "").lower()
    jours = PERIODES_JOURS.get(periode)
    ref = _date_ref(client)
    grace = borner_grace(client.get("abonnement_grace_jours")) \
        if client.get("abonnement_grace_jours") is not None else GRACE_DEFAUT
    base = {"periodicite": periode or None, "periodicite_libelle": LIBELLES_PERIODES.get(periode),
            "grace_jours": grace, "renouvellements": 0, "renouvellements_max": RENOUVELLEMENTS_MAX,
            "contrat": {"numero": client.get("contract_number") or None, "montant": client.get("contract_amount"),
                        "devise": client.get("contract_currency") or None}}
    if not jours or not ref:
        return {**base, "statut": SANS_ECHEANCE, "echeance": None, "impayee_depuis": None, "fin_grace": None,
                "jours_restants": None, "secondes_restantes": None}
    echeance = ref + timedelta(days=jours)
    impayee = _minuit(echeance + timedelta(days=1))
    ren = client.get("abonnement_grace_renouvellements") or {}
    nb = int(ren.get("nombre") or 0) if ren.get("echeance") == echeance.isoformat() else 0
    fin = impayee + timedelta(days=grace + RENOUVELLEMENT_JOURS * nb)
    if a < impayee:
        statut = A_JOUR
    elif a < fin:
        statut = GRACE
    else:
        statut = EXPIRE
    reste = max(0.0, (fin - a).total_seconds())
    return {**base, "statut": statut, "echeance": echeance.isoformat(), "impayee_depuis": impayee.isoformat(),
            "fin_grace": fin.isoformat(), "renouvellements": nb,
            "jours_restants": (math.ceil(reste / 86400) if statut == GRACE else 0 if statut == EXPIRE else None),
            "secondes_restantes": int(reste) if statut == GRACE else None}


async def fiche_client(client_id: str, user: Optional[dict] = None, cache: bool = True) -> Optional[dict]:
    if user is not None and user.get("id") == client_id:
        return user
    c = _cache_clients.get(client_id)
    if cache and c and time.monotonic() - c[0] < DUREE_CACHE_S:
        return c[1]
    doc = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if len(_cache_clients) > 5000:
        _cache_clients.clear()
    _cache_clients[client_id] = (time.monotonic(), doc)
    return doc


def route_ouverte(chemin: str) -> bool:
    return any(chemin == p.rstrip("/") or chemin.startswith(p.rstrip("/") + "/") for p in ROUTES_OUVERTES)


def message_expire(etat: Dict[str, Any]) -> str:
    ech = etat.get("echeance") or ""
    try:
        ech = datetime.strptime(ech, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        pass
    return (f"Abonnement expiré : l'échéance du {ech} n'a pas été réglée et la période de grâce est terminée. "
            "Renouvelez votre abonnement pour retrouver l'accès.")


async def controler(user: dict, jeton: dict, chemin: str) -> None:
    """Coupure après la grâce (402), sauf super-admin, « Voir en tant que » et routes ouvertes."""
    if jeton.get("imp") or est_super_admin(user):
        return
    if route_ouverte(chemin):
        return
    if not await coupure_active():
        return
    cid = client_id_de(user)
    if not cid:
        return
    client = await fiche_client(cid, user)
    if not client:
        return
    etat = etat_client(client)
    if etat["statut"] == EXPIRE:
        raise RefusAcces(402, message_expire(etat), CODE_EXPIRE)


async def etat_pour(user: dict, jeton: Optional[dict] = None) -> Dict[str, Any]:
    """État affiché au compte connecté (bandeau, écran « Abonnement expiré »)."""
    jeton = jeton or {}
    actif = await coupure_active()
    cid = client_id_de(user)
    if not cid or not actif or est_super_admin(user):
        return {"actif": False, "statut": None}
    client = await fiche_client(cid, user, cache=False)
    if not client:
        return {"actif": False, "statut": None}
    etat = etat_client(client)
    apercu = bool(jeton.get("imp"))
    return {"actif": True, **etat, "client_nom": client.get("company") or client.get("full_name"),
            "bloque": etat["statut"] == EXPIRE and not apercu, "apercu_admin": apercu,
            "message": message_expire(etat) if etat["statut"] == EXPIRE else None,
            "maintenant_serveur": maintenant().isoformat()}


# ---------------------------------------------------------------------------
# Actions de l'Admin
# ---------------------------------------------------------------------------
async def _journaliser(action: str, client: dict, adm: dict, **extra) -> None:
    await db[JOURNAL].insert_one({
        "id": str(uuid.uuid4()), "action": action, "date": maintenant().isoformat(),
        "client_id": client.get("id"), "client_nom": client.get("company") or client.get("full_name"),
        "par": {"id": adm.get("id"), "email": adm.get("email")}, **extra})


async def _client_ou_404(client_id: str) -> dict:
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client or est_super_admin(client):
        raise RefusAcces(404, "Client introuvable")
    return client


async def definir_grace(client_id: str, jours: int, adm: dict) -> Dict[str, Any]:
    client = await _client_ou_404(client_id)
    n = borner_grace(jours)
    await db.users.update_one({"id": client_id}, {"$set": {"abonnement_grace_jours": n}})
    vider_cache(client_id)
    await _journaliser("GRACE_REGLEE", client, adm, avant=client.get("abonnement_grace_jours"), apres=n)
    return etat_client({**client, "abonnement_grace_jours": n})


async def renouveler_grace(client_id: str, adm: dict) -> Dict[str, Any]:
    client = await _client_ou_404(client_id)
    etat = etat_client(client)
    if etat["statut"] not in (GRACE, EXPIRE):
        raise RefusAcces(409, "Abonnement à jour (ou sans échéance) : aucune grâce à renouveler")
    if etat["renouvellements"] >= RENOUVELLEMENTS_MAX:
        raise RefusAcces(409, f"Grâce déjà renouvelée {RENOUVELLEMENTS_MAX} fois pour cette échéance")
    nb = etat["renouvellements"] + 1
    ren = {"echeance": etat["echeance"], "nombre": nb}
    await db.users.update_one({"id": client_id}, {"$set": {"abonnement_grace_renouvellements": ren}})
    vider_cache(client_id)
    nouveau = etat_client({**client, "abonnement_grace_renouvellements": ren})
    await _journaliser("GRACE_RENOUVELEE", client, adm, echeance=etat["echeance"], renouvellement=nb,
                       fin_grace=nouveau["fin_grace"])
    return nouveau


async def journal(client_id: Optional[str] = None, limite: int = 50) -> list:
    filtre = {"client_id": client_id} if client_id else {}
    return await db[JOURNAL].find(filtre, {"_id": 0}).sort("date", -1).limit(limite).to_list(limite)
