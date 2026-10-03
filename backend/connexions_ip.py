"""Lot 55 — Journal des connexions des comptes et blocage d'une adresse IP par compte.

POURQUOI UNE NOUVELLE COLLECTION `connexions_journal`
   Les collections existantes ne suffisent pas :
     - `access_logs` : pages visitées par le site (pas d'événement de connexion, pas d'échec) ;
     - `auth_checks` : contrôle de santé automatique de la connexion (pas des utilisateurs) ;
     - `sessions_comptes` (lot 50) : IP et date, mais seulement des connexions RÉUSSIES et
       effacées à l'expiration de la session (TTL 12 h) ;
     - `sessions_comptes_journal` : ouvertures et fermetures de sessions, sans les refus ;
     - `activity_events` : fil d'activité métier (contacts, rapports…).
   `connexions_journal` garde un événement par tentative de connexion d'un compte connu :
   date, IP, appareil (« Chrome · Windows »), méthode, résultat (réussie / refusée et pourquoi,
   dont « IP bloquée ») et session. Index (user_id, date) ; conservation 180 jours (index TTL).

MÉTHODES DE CONNEXION JOURNALISÉES
   - « mot_de_passe »  : étape 1 de /auth/login (seuls les REFUS sont notés : la connexion
                         n'est complète qu'après le code) ;
   - « code_email »    : étape 2, /auth/verify-otp (connexion réussie ou refusée) ;
   - « code_whatsapp » : /auth/wa-otp/verify (compte existant).
   « Voir en tant que » (lot 44) n'ouvre pas de session de compte et n'est pas journalisé ici.

BLOCAGE D'UNE IP (`connexions_ip_regles`)
   Une règle par (ip, compte) : statut « bloquee » ou « confiance ». Un blocage GLOBAL (toute la
   plateforme, réservé au super-admin) porte le compte « * ».
   Une IP bloquée pour un compte (ou globalement) :
     - refuse la connexion de ce compte par les 3 méthodes : « Connexion refusée depuis cette
       adresse. Contactez l'administrateur. » ;
     - ferme les sessions ouvertes de ce compte depuis cette IP (motif « ip_bloquee ») ;
     - fait répondre 401 aux requêtes suivantes de ce compte venant de cette IP (contrôle de
       session du lot 50, avec un petit cache de 10 s).
   Le super-admin (SUPER_ADMIN_EMAIL) n'est jamais bloqué.
   « Autoriser » lève le blocage et marque l'IP « de confiance » pour ce compte (badge vert).
   Une adresse IP correspond à un lieu ou à un réseau (Wi-Fi, box), pas à une personne : chaque
   règle peut porter un « libellé du site » (« Pharmacie X — Wi-Fi accueil »). Le super-admin voit
   la liste des « Sites bloqués (toute la plateforme) » avec le nombre de tentatives refusées.
   Chaque action est journalisée dans `connexions_ip_actions` (qui, quand, IP, compte, portée).
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

import sessions_comptes
from ip_client import ip_reelle

logger = logging.getLogger("sawali.connexions_ip")

JOURNAL = "connexions_journal"
REGLES = "connexions_ip_regles"
ACTIONS = "connexions_ip_actions"
CONSERVATION_JOURS = 180
PAR_PAGE = 50
DUREE_CACHE_S = 10.0
GLOBAL = "*"                       # compte « * » = blocage sur toute la plateforme

BLOQUEE, CONFIANCE = "bloquee", "confiance"
REUSSIE, REFUSEE = "reussie", "refusee"
MOT_DE_PASSE, CODE_EMAIL, CODE_WHATSAPP = "mot_de_passe", "code_email", "code_whatsapp"
MOTIF_IP_BLOQUEE = "IP bloquée"
MESSAGE_REFUS = "Connexion refusée depuis cette adresse. Contactez l'administrateur."

_cache: Dict[str, Any] = {"lu_a": 0.0, "comptes": set(), "globales": set()}
_index_ok = {"fait": False}


def _base():
    """Même base que les sessions du lot 50 (une seule base à remplacer dans les tests)."""
    return sessions_comptes.db


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(v: Any) -> Optional[str]:
    """Date ISO avec fuseau (+00:00) : Mongo rend des dates sans fuseau, lues comme UTC."""
    if not v:
        return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return str(v)


def vider_cache() -> None:
    _cache.update(lu_a=0.0, comptes=set(), globales=set())


def est_super_admin(user: Optional[dict]) -> bool:
    import auth
    return bool(user) and auth.est_super_admin(user)


async def assurer_index() -> None:
    if _index_ok["fait"]:
        return
    try:
        b = _base()
        await b[JOURNAL].create_index([("user_id", 1), ("date", -1)], name="user_date")
        await b[JOURNAL].create_index("date", expireAfterSeconds=CONSERVATION_JOURS * 86400, name="ttl_date")
        await b[REGLES].create_index([("ip", 1), ("user_id", 1)], unique=True, name="ip_compte")
        await b[ACTIONS].create_index("date", name="date")
        _index_ok["fait"] = True
    except Exception as exc:  # noqa: BLE001 — jamais bloquant pour une connexion
        logger.warning("[connexions] index non créés : %s", exc)


# ---------------------------------------------------------------------------
# Journal des connexions
# ---------------------------------------------------------------------------
async def noter(user: Optional[dict], request, methode: str, resultat: str,
                motif: Optional[str] = None, sid: Optional[str] = None) -> None:
    """Note une tentative de connexion d'un compte connu. Jamais bloquant."""
    if not user or not user.get("id"):
        return
    try:
        await assurer_index()
        ua = (request.headers.get("user-agent") if request is not None else "") or ""
        await _base()[JOURNAL].insert_one({
            "id": uuid.uuid4().hex, "user_id": user["id"], "user_email": user.get("email"),
            "client_id": sessions_comptes.client_de(user), "date": maintenant(),
            "ip": ip_reelle(request), "appareil": sessions_comptes.appareil_de(ua), "navigateur": ua[:300],
            "methode": methode, "resultat": resultat, "motif": motif, "sid": sid,
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("[connexions] journal non écrit : %s", exc)


def _vue(doc: dict) -> dict:
    return {"id": doc.get("id"), "date": iso_utc(doc.get("date")), "ip": doc.get("ip"),
            "appareil": doc.get("appareil"), "methode": doc.get("methode"), "resultat": doc.get("resultat"),
            "motif": doc.get("motif"), "sid": doc.get("sid")}


async def historique(user_id: str, page: int = 1, ip: Optional[str] = None) -> Dict[str, Any]:
    """Historique paginé (50 par page), les plus récentes d'abord ; filtre par IP (début de l'adresse)."""
    page = max(1, int(page or 1))
    q: Dict[str, Any] = {"user_id": user_id}
    if ip and ip.strip():
        q["ip"] = {"$regex": "^" + re.escape(ip.strip())}
    b = _base()
    total = await b[JOURNAL].count_documents(q)
    docs = await b[JOURNAL].find(q, {"_id": 0}).sort("date", -1).skip((page - 1) * PAR_PAGE) \
        .limit(PAR_PAGE).to_list(PAR_PAGE)
    return {"items": [_vue(d) for d in docs], "total": total, "page": page, "par_page": PAR_PAGE,
            "pages": max(1, -(-total // PAR_PAGE))}


async def dernieres_connexions(user_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Par compte : date et IP de la dernière connexion RÉUSSIE (repli : users.last_login, sans IP)."""
    ids = [u for u in dict.fromkeys(user_ids) if u]
    out: Dict[str, Dict[str, Any]] = {}
    if not ids:
        return out
    b = _base()
    pipeline = [{"$match": {"user_id": {"$in": ids}, "resultat": REUSSIE}}, {"$sort": {"date": -1}},
                {"$group": {"_id": "$user_id", "date": {"$first": "$date"}, "ip": {"$first": "$ip"},
                            "appareil": {"$first": "$appareil"}, "methode": {"$first": "$methode"}}}]
    async for r in b[JOURNAL].aggregate(pipeline):
        out[r["_id"]] = {"date": iso_utc(r.get("date")), "ip": r.get("ip"), "appareil": r.get("appareil"),
                         "methode": r.get("methode")}
    manquants = [u for u in ids if u not in out]
    if manquants:
        async for u in b.users.find({"id": {"$in": manquants}},
                                    {"_id": 0, "id": 1, "last_login": 1, "last_login_at": 1}):
            d = u.get("last_login") or u.get("last_login_at")
            if d:
                out[u["id"]] = {"date": iso_utc(d), "ip": None, "appareil": None, "methode": None}
    return out


# ---------------------------------------------------------------------------
# Règles (bloquée / de confiance)
# ---------------------------------------------------------------------------
async def _charger() -> None:
    if time.monotonic() - _cache["lu_a"] < DUREE_CACHE_S:
        return
    comptes, globales = set(), set()
    async for r in _base()[REGLES].find({"statut": BLOQUEE}, {"_id": 0, "ip": 1, "user_id": 1}):
        if r.get("user_id") == GLOBAL:
            globales.add(r.get("ip"))
        else:
            comptes.add((r.get("ip"), r.get("user_id")))
    _cache.update(lu_a=time.monotonic(), comptes=comptes, globales=globales)


async def est_bloquee(user: dict, ip: str) -> bool:
    """IP bloquée pour ce compte (ou sur toute la plateforme). Le super-admin n'est jamais bloqué."""
    if not ip or not user or est_super_admin(user):
        return False
    await _charger()
    return ip in _cache["globales"] or (ip, user.get("id")) in _cache["comptes"]


async def refuser_si_bloquee(user: dict, request, methode: str) -> None:
    """À la connexion (3 méthodes) : 403 avec un message clair si l'IP est bloquée ; refus journalisé."""
    try:
        bloquee = await est_bloquee(user, ip_reelle(request))
    except Exception as exc:  # noqa: BLE001 — base indisponible : on ne bloque pas la connexion
        logger.warning("[connexions] contrôle de l'IP impossible : %s", exc)
        return
    if bloquee:
        await noter(user, request, methode, REFUSEE, MOTIF_IP_BLOQUEE)
        raise HTTPException(status_code=403, detail=MESSAGE_REFUS)


async def controler_requete(user: dict, request) -> None:
    """À chaque requête authentifiée (contrôle de session du lot 50) : 401 si l'IP est bloquée."""
    if request is None:
        return
    if await est_bloquee(user, ip_reelle(request)):
        from controle_acces import RefusAcces
        raise RefusAcces(401, MESSAGE_REFUS, "session_ip_bloquee")


def _libelle(v: Optional[str]) -> Optional[str]:
    """Libellé du site (« Pharmacie X — Wi-Fi accueil ») : facultatif, 120 caractères au plus."""
    v = (v or "").strip()
    return v[:120] or None


async def regles_du_compte(user_id: str) -> Dict[str, List[dict]]:
    """IP bloquées (du compte + globales) et IP de confiance du compte, avec leur libellé de site."""
    b = _base()
    bloquees, confiance = [], []
    async for r in b[REGLES].find({"user_id": {"$in": [user_id, GLOBAL]}}, {"_id": 0}).sort("date", -1):
        vue = {"ip": r.get("ip"), "portee": "globale" if r.get("user_id") == GLOBAL else "compte",
               "libelle": r.get("libelle"), "date": iso_utc(r.get("date")), "par": (r.get("par") or {}).get("email")}
        if r.get("statut") == BLOQUEE:
            bloquees.append(vue)
        elif r.get("statut") == CONFIANCE and r.get("user_id") == user_id:
            confiance.append(vue)
    return {"bloquees": bloquees, "confiance": confiance}


async def statut_ips(paires: List[tuple]) -> Dict[tuple, dict]:
    """{(ip, compte): {"statut": "bloquee" | "confiance", "libelle", "portee"}} pour l'affichage de la page.
    Un blocage global l'emporte sur une règle du compte."""
    paires = [(ip, u) for ip, u in paires if ip and u]
    out: Dict[tuple, dict] = {}
    if not paires:
        return out
    ips = list({ip for ip, _ in paires})
    comptes = list({u for _, u in paires}) + [GLOBAL]
    regles = {}
    async for r in _base()[REGLES].find({"ip": {"$in": ips}, "user_id": {"$in": comptes}}, {"_id": 0}):
        regles[(r["ip"], r["user_id"])] = r
    for ip, u in paires:
        g, c = regles.get((ip, GLOBAL)), regles.get((ip, u))
        if g and g.get("statut") == BLOQUEE:
            out[(ip, u)] = {"statut": BLOQUEE, "libelle": g.get("libelle"), "portee": "globale"}
        elif c and c.get("statut") in (BLOQUEE, CONFIANCE):
            out[(ip, u)] = {"statut": c.get("statut"), "libelle": c.get("libelle"), "portee": "compte"}
    return out


async def _journaliser_action(action: str, par: dict, ip_admin: str, ip: str, compte: Optional[dict],
                              portee: str, **extra) -> None:
    await _base()[ACTIONS].insert_one({
        "id": uuid.uuid4().hex, "action": action, "date": maintenant(),
        "par": {"id": par.get("id"), "email": par.get("email"), "role": par.get("role")}, "ip_admin": ip_admin,
        "ip": ip, "user_id": (compte or {}).get("id"), "user_email": (compte or {}).get("email"),
        "portee": portee, **extra})


async def actions_recentes(user_id: str, limite: int = 20) -> List[dict]:
    docs = await _base()[ACTIONS].find({"$or": [{"user_id": user_id}, {"portee": "globale"}]}, {"_id": 0}) \
        .sort("date", -1).limit(limite).to_list(limite)
    return [{"action": d.get("action"), "date": iso_utc(d.get("date")), "ip": d.get("ip"), "portee": d.get("portee"),
             "libelle": d.get("libelle"), "par": (d.get("par") or {}).get("email"),
             "user_email": d.get("user_email")} for d in docs]


async def _fermer_sessions(ip: str, user_id: Optional[str], par: dict) -> int:
    """Ferme les sessions ouvertes depuis `ip` (d'un compte, ou de tous sauf le super-admin)."""
    b = _base()
    q = sessions_comptes._filtre_ouvertes(ip=ip)
    if user_id:
        q["user_id"] = user_id
    n = 0
    for s in await b[sessions_comptes.COLLECTION].find(q, {"_id": 0, "id": 1, "user_email": 1}).to_list(20000):
        if est_super_admin({"email": s.get("user_email")}):
            continue
        if await sessions_comptes.fermer(s["id"], sessions_comptes.MOTIF_IP_BLOQUEE, par):
            n += 1
    return n


async def _poser_regle(ip: str, cible: str, statut: str, par: dict, libelle: Optional[str]) -> None:
    champs = {"ip": ip, "user_id": cible, "statut": statut, "date": maintenant(),
              "par": {"id": par.get("id"), "email": par.get("email")}}
    if libelle:
        champs["libelle"] = libelle     # sans libellé saisi, on garde celui déjà connu
    await _base()[REGLES].update_one({"ip": ip, "user_id": cible}, {"$set": champs}, upsert=True)


async def bloquer(ip: str, compte: dict, par: dict, ip_admin: str, globale: bool = False,
                  libelle: Optional[str] = None) -> Dict[str, Any]:
    """Bloque `ip` pour `compte` (ou sur toute la plateforme). Les garde-fous sont vérifiés par la route."""
    await assurer_index()
    libelle = _libelle(libelle)
    await _poser_regle(ip, GLOBAL if globale else compte["id"], BLOQUEE, par, libelle)
    vider_cache()
    fermees = await _fermer_sessions(ip, None if globale else compte["id"], par)
    portee = "globale" if globale else "compte"
    await _journaliser_action("BLOQUER", par, ip_admin, ip, compte, portee, libelle=libelle, sessions_fermees=fermees)
    return {"ok": True, "ip": ip, "portee": portee, "libelle": libelle, "sessions_fermees": fermees}


async def autoriser(ip: str, compte: dict, par: dict, ip_admin: str, lever_globale: bool = False,
                    libelle: Optional[str] = None) -> Dict[str, Any]:
    """Lève le blocage de `ip` pour `compte` (et le blocage global si demandé) puis la marque
    « de confiance » pour ce compte."""
    await assurer_index()
    b = _base()
    libelle = _libelle(libelle)
    globale_levee = False
    if lever_globale:
        ancienne = await b[REGLES].find_one_and_delete({"ip": ip, "user_id": GLOBAL})
        globale_levee = bool(ancienne)
        libelle = libelle or (ancienne or {}).get("libelle")
    await _poser_regle(ip, compte["id"], CONFIANCE, par, libelle)
    vider_cache()
    portee = "globale" if globale_levee else "compte"
    await _journaliser_action("AUTORISER", par, ip_admin, ip, compte, portee, libelle=libelle)
    return {"ok": True, "ip": ip, "portee": portee, "libelle": libelle, "confiance": True}


async def blocage_global(ip: str) -> bool:
    return bool(await _base()[REGLES].find_one({"ip": ip, "user_id": GLOBAL, "statut": BLOQUEE}, {"_id": 1}))


# ---------------------------------------------------------------------------
# Sites bloqués sur toute la plateforme (super-admin)
# ---------------------------------------------------------------------------
async def sites_bloques() -> List[dict]:
    """Blocages globaux : IP, libellé, auteur, date et nombre de tentatives de connexion refusées
    depuis (journal des connexions, motif « IP bloquée »)."""
    b = _base()
    out = []
    async for r in b[REGLES].find({"user_id": GLOBAL, "statut": BLOQUEE}, {"_id": 0}).sort("date", -1):
        q: Dict[str, Any] = {"ip": r.get("ip"), "motif": MOTIF_IP_BLOQUEE}
        if r.get("date"):
            q["date"] = {"$gte": r["date"]}
        out.append({"ip": r.get("ip"), "libelle": r.get("libelle"), "par": (r.get("par") or {}).get("email"),
                    "date": iso_utc(r.get("date")), "tentatives_refusees": await b[JOURNAL].count_documents(q)})
    return out


async def lever_global(ip: str, par: dict, ip_admin: str) -> Dict[str, Any]:
    """« Autoriser » depuis la liste des sites bloqués : lève le blocage global (aucun compte visé)."""
    ancienne = await _base()[REGLES].find_one_and_delete({"ip": ip, "user_id": GLOBAL, "statut": BLOQUEE})
    if not ancienne:
        return {"ok": False}
    vider_cache()
    await _journaliser_action("AUTORISER", par, ip_admin, ip, None, "globale", libelle=ancienne.get("libelle"))
    return {"ok": True, "ip": ip, "portee": "globale", "libelle": ancienne.get("libelle")}
