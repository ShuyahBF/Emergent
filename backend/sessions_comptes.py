"""Lot 50 — Sessions des comptes : au plus N appareils connectés par compte, contrôle serveur
de l'inactivité.

B. SESSIONS SIMULTANÉES LIMITÉES (spécification commune du 02/10/2026)
   - Chaque connexion (mot de passe + code OTP, ou connexion WhatsApp) ouvre une session :
     identifiant `sid` placé dans le jeton + document dans la collection `sessions_comptes`
     (index TTL sur `expire_a` : la base efface seule les sessions périmées).
   - Au plus `sessions_max_par_compte` sessions ouvertes par compte (réglage de l'Admin,
     1 à 20, 5 par défaut). À la connexion suivante, la session dont la DERNIÈRE ACTIVITÉ est
     la plus ancienne est fermée ; l'appareil fermé reçoit 401 avec le message
     « Session fermée : nombre maximal d'appareils atteint pour ce compte. »
   - « Mon compte » liste les sessions actives (appareil, navigateur, IP, ouverture, dernière
     activité) avec « Fermer » ; l'Admin voit le nombre de sessions par compte d'un client et
     peut les fermer. Ouvertures et fermetures sont journalisées (`sessions_comptes_journal`).
   - Les sessions « Voir en tant que » (lot 44) n'ouvrent pas de session : elles ne comptent pas
     dans la limite du client et ne lui ferment jamais une session.
   - Les jetons émis avant ce lot (sans `sid`) restent valables jusqu'à leur expiration
     habituelle (JWT_EXPIRE_HOURS) : personne n'est déconnecté par la mise à jour.

DÉCONNEXION APRÈS INACTIVITÉ — contrôle serveur (le réglage existant ne change pas)
   Le réglage existant `auto_logout_minutes` (en MINUTES, 0 = désactivé) et la fenêtre
   d'avertissement du navigateur (AutoLogoutGate) restent tels quels. Ce module ajoute le
   contrôle côté serveur qui manquait : la dernière activité de chaque session est notée
   (au plus une écriture par minute) ; au-delà de `auto_logout_minutes` + 2 minutes de marge
   sans activité, la session est fermée et la requête reçoit 401 (« Session expirée par
   inactivité »). Les requêtes automatiques marquées (en-tête `X-Requete-Fond: 1`) ne comptent
   pas comme une activité ; le navigateur signale l'activité de l'utilisateur (souris,
   clavier) au plus une fois par minute (POST /api/me/activite).
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from db import db
from controle_acces import RefusAcces, requete_de_fond

logger = logging.getLogger("sawali.sessions")

COLLECTION = "sessions_comptes"
JOURNAL = "sessions_comptes_journal"
MAX_DEFAUT, MAX_MIN, MAX_MAX = 5, 1, 20
DUREE_SESSION_H_DEFAUT = 12          # comme JWT_EXPIRE_HOURS
ECRITURE_ACTIVITE_S = 60             # au plus une écriture de « dernière activité » par minute
MARGE_INACTIVITE_S = 120             # marge au-delà du délai d'inactivité réglé
DUREE_CACHE_SESSION_S = 5.0
DUREE_CACHE_REGLAGES_S = 30.0

MOTIF_LIMITE = "limite_appareils"
MOTIF_FERMEE_UTILISATEUR = "fermee_par_utilisateur"
MOTIF_FERMEE_ADMIN = "fermee_par_admin"
MOTIF_INACTIVITE = "inactivite"
MOTIF_DECONNEXION = "deconnexion"
MOTIF_MAINTENANCE = "maintenance"
MOTIF_SUSPENSION = "abonnement_suspendu"   # lot 51 : client suspendu (J+110) ou archivé (J+113)

MESSAGES = {
    MOTIF_LIMITE: ("Session fermée : nombre maximal d'appareils atteint pour ce compte.", "session_limite"),
    MOTIF_FERMEE_UTILISATEUR: ("Session fermée depuis un autre appareil : reconnectez-vous.", "session_fermee"),
    MOTIF_FERMEE_ADMIN: ("Session fermée par l'administrateur : reconnectez-vous.", "session_fermee"),
    MOTIF_INACTIVITE: ("Session expirée par inactivité — merci de vous reconnecter.", "session_inactive"),
    MOTIF_DECONNEXION: ("Session terminée : reconnectez-vous.", "session_fermee"),
    MOTIF_MAINTENANCE: ("Session fermée par la maintenance de la plateforme : reconnectez-vous.", "session_maintenance"),
    MOTIF_SUSPENSION: ("Accès suspendu : abonnement non renouvelé. Contactez SAWALI SMART SYSTEMS.",
                       "session_abonnement_suspendu"),
}
MESSAGE_INCONNUE = ("Session fermée : reconnectez-vous.", "session_fermee")

_cache_sessions: Dict[str, tuple] = {}     # sid -> (lu_a, doc)
_cache_reglages: Dict[str, Any] = {"lu_a": 0.0, "doc": None}
_index_ok = {"fait": False}


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: Optional[datetime] = None) -> str:
    return (d or maintenant()).isoformat()


def _date(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def vider_caches() -> None:
    _cache_sessions.clear()
    _cache_reglages.update(lu_a=0.0, doc=None)


# ---------------------------------------------------------------------------
# Réglages (document `settings` global, lus avec un petit cache)
# ---------------------------------------------------------------------------
async def reglages() -> dict:
    if _cache_reglages["doc"] is not None and time.monotonic() - _cache_reglages["lu_a"] < DUREE_CACHE_REGLAGES_S:
        return _cache_reglages["doc"]
    doc = await db.settings.find_one({"_id": "global"}, {"_id": 0, "sessions_max_par_compte": 1,
                                                           "auto_logout_minutes": 1}) or {}
    _cache_reglages.update(lu_a=time.monotonic(), doc=doc)
    return doc


def borner_max(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return MAX_DEFAUT
    return min(MAX_MAX, max(MAX_MIN, n))


async def max_sessions() -> int:
    v = (await reglages()).get("sessions_max_par_compte")
    return MAX_DEFAUT if v in (None, "") else borner_max(v)


async def delai_inactivite_s() -> int:
    """Délai d'inactivité réglé (minutes → secondes) ; 0 = désactivé."""
    try:
        minutes = int((await reglages()).get("auto_logout_minutes") or 0)
    except (TypeError, ValueError):
        minutes = 0
    return max(0, minutes) * 60


async def definir_max(valeur: int) -> int:
    n = borner_max(valeur)
    await db.settings.update_one({"_id": "global"}, {"$set": {"sessions_max_par_compte": n}}, upsert=True)
    _cache_reglages.update(lu_a=0.0, doc=None)
    return n


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------
async def assurer_index() -> None:
    if _index_ok["fait"]:
        return
    try:
        await db[COLLECTION].create_index("expire_a", expireAfterSeconds=0, name="ttl_expire_a")
        await db[COLLECTION].create_index("id", unique=True, name="id_unique")
        await db[COLLECTION].create_index([("user_id", 1), ("fermee_le", 1)], name="user_ouvertes")
        await db[JOURNAL].create_index("date", name="date")
        _index_ok["fait"] = True
    except Exception as exc:  # noqa: BLE001 — jamais bloquant pour une connexion
        logger.warning("[sessions] index non créés : %s", exc)


def ip_de(request) -> str:
    if request is None:
        return ""
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if getattr(request, "client", None) else ""


def appareil_de(ua: str) -> str:
    """« Chrome · Windows », « Safari · iPhone »… (lecture simple de l'agent du navigateur)."""
    ua = ua or ""
    if re.search(r"Edg/", ua):
        nav = "Edge"
    elif re.search(r"OPR/|Opera", ua):
        nav = "Opera"
    elif re.search(r"Firefox/", ua):
        nav = "Firefox"
    elif re.search(r"Chrome/|CriOS/", ua):
        nav = "Chrome"
    elif re.search(r"Safari/", ua):
        nav = "Safari"
    else:
        nav = "Navigateur"
    if re.search(r"iPhone", ua):
        os_ = "iPhone"
    elif re.search(r"iPad", ua):
        os_ = "iPad"
    elif re.search(r"Android", ua):
        os_ = "Android"
    elif re.search(r"Windows", ua):
        os_ = "Windows"
    elif re.search(r"Mac OS X|Macintosh", ua):
        os_ = "macOS"
    elif re.search(r"Linux", ua):
        os_ = "Linux"
    else:
        os_ = "appareil inconnu"
    return f"{nav} · {os_}"


def client_de(user: dict) -> Optional[str]:
    """Client (locataire) d'un compte : son client parent, sinon le compte lui-même."""
    return user.get("parent_client_id") or user.get("client_id") or user.get("id")


async def _journaliser(action: str, session: dict, motif: Optional[str] = None,
                       par: Optional[dict] = None, **extra) -> None:
    try:
        await db[JOURNAL].insert_one({
            "id": str(uuid.uuid4()), "action": action, "motif": motif, "date": _iso(),
            "sid": session.get("id"), "user_id": session.get("user_id"), "user_email": session.get("user_email"),
            "client_id": session.get("client_id"), "ip": session.get("ip"), "appareil": session.get("appareil"),
            "par": ({"id": par.get("id"), "email": par.get("email")} if par else None), **extra})
    except Exception:  # noqa: BLE001
        pass


def _vue(doc: dict, courante: Optional[str] = None) -> dict:
    return {"id": doc.get("id"), "appareil": doc.get("appareil"), "navigateur": doc.get("navigateur"),
            "ip": doc.get("ip"), "ouverte_le": doc.get("ouverte_le"), "derniere_activite": doc.get("derniere_activite"),
            "courante": bool(courante and doc.get("id") == courante)}


def _filtre_ouvertes(**extra) -> dict:
    return {"fermee_le": None, "expire_a": {"$gt": maintenant()}, **extra}


# ---------------------------------------------------------------------------
# Ouverture (à la connexion) et fermeture
# ---------------------------------------------------------------------------
async def ouvrir_session(user: dict, request=None, duree_h: Optional[float] = None) -> Dict[str, Any]:
    """Ouvre une session pour `user` ; ferme d'abord les plus anciennes au-delà de la limite.
    Renvoie {"sid", "iat"} à placer dans le jeton."""
    await assurer_index()
    a = maintenant()
    if duree_h is None:
        import auth
        duree_h = auth.JWT_EXPIRE_HOURS
    limite = await max_sessions()
    ouvertes = await db[COLLECTION].find(_filtre_ouvertes(user_id=user["id"]), {"_id": 0}) \
        .sort("derniere_activite", 1).to_list(500)
    # La nouvelle session prend une place : on garde au plus (limite - 1) anciennes sessions.
    a_fermer = ouvertes[:max(0, len(ouvertes) - (limite - 1))]
    for s in a_fermer:
        await fermer(s["id"], MOTIF_LIMITE)
    ua = (request.headers.get("user-agent") if request is not None else "") or ""
    doc = {
        "id": uuid.uuid4().hex, "user_id": user["id"], "user_email": user.get("email"),
        "user_nom": user.get("full_name"), "role": user.get("role"), "client_id": client_de(user),
        "ouverte_le": _iso(a), "derniere_activite": _iso(a), "expire_a": a + timedelta(hours=float(duree_h)),
        "ip": ip_de(request), "navigateur": ua[:400], "appareil": appareil_de(ua),
        "fermee_le": None, "motif": None,
    }
    await db[COLLECTION].insert_one(dict(doc))
    await _journaliser("OUVERTURE", doc, fermees_limite=len(a_fermer))
    return {"sid": doc["id"], "iat": int(a.timestamp())}


async def fermer(sid: str, motif: str, par: Optional[dict] = None) -> bool:
    doc = await db[COLLECTION].find_one({"id": sid, "fermee_le": None}, {"_id": 0})
    if not doc:
        return False
    await db[COLLECTION].update_one({"id": sid, "fermee_le": None},
                                    {"$set": {"fermee_le": _iso(), "motif": motif}})
    _cache_sessions.pop(sid, None)
    await _journaliser("FERMETURE", doc, motif, par)
    return True


async def fermer_compte(user_id: str, motif: str, par: Optional[dict] = None, sauf: Optional[str] = None) -> int:
    n = 0
    for s in await db[COLLECTION].find(_filtre_ouvertes(user_id=user_id), {"_id": 0, "id": 1}).to_list(500):
        if s["id"] != sauf and await fermer(s["id"], motif, par):
            n += 1
    return n


async def fermer_avant(seuil: Optional[datetime], motif: str) -> int:
    """Ferme les sessions (hors Admin) ouvertes avant `seuil` (fin d'une maintenance)."""
    if seuil is None:
        return 0
    n = 0
    for s in await db[COLLECTION].find(_filtre_ouvertes(role={"$ne": "admin"}), {"_id": 0}).to_list(20000):
        d = _date(s.get("ouverte_le"))
        if d and d < seuil and await fermer(s["id"], motif):
            n += 1
    return n


async def lister(user_id: str, courante: Optional[str] = None) -> List[dict]:
    docs = await db[COLLECTION].find(_filtre_ouvertes(user_id=user_id), {"_id": 0}) \
        .sort("derniere_activite", -1).to_list(100)
    return [_vue(d, courante) for d in docs]


async def compter_par_compte(user_ids: List[str]) -> Dict[str, int]:
    res: Dict[str, int] = {u: 0 for u in user_ids}
    for d in await db[COLLECTION].find(_filtre_ouvertes(user_id={"$in": user_ids}), {"_id": 0, "user_id": 1}) \
            .to_list(20000):
        res[d["user_id"]] = res.get(d["user_id"], 0) + 1
    return res


async def session(sid: str) -> Optional[dict]:
    return await db[COLLECTION].find_one({"id": sid}, {"_id": 0})


# ---------------------------------------------------------------------------
# Contrôle de chaque requête authentifiée
# ---------------------------------------------------------------------------
async def _lire(sid: str) -> Optional[dict]:
    c = _cache_sessions.get(sid)
    if c and time.monotonic() - c[0] < DUREE_CACHE_SESSION_S:
        return c[1]
    doc = await db[COLLECTION].find_one({"id": sid}, {"_id": 0})
    if len(_cache_sessions) > 5000:
        _cache_sessions.clear()
    _cache_sessions[sid] = (time.monotonic(), doc)
    return doc


def refus(motif: Optional[str]) -> RefusAcces:
    message, code = MESSAGES.get(motif or "", MESSAGE_INCONNUE)
    return RefusAcces(401, message, code)


async def controler(user: dict, jeton: dict, request=None) -> None:
    sid = jeton.get("sid")
    if jeton.get("imp") or not sid:
        return  # « Voir en tant que » ou jeton émis avant le lot 50
    doc = await _lire(sid)
    if not doc or doc.get("user_id") != user.get("id"):
        raise refus(None)
    if doc.get("fermee_le"):
        raise refus(doc.get("motif"))
    a = maintenant()
    derniere = _date(doc.get("derniere_activite")) or a
    delai = await delai_inactivite_s()
    if delai and (a - derniere).total_seconds() > delai + MARGE_INACTIVITE_S:
        await fermer(sid, MOTIF_INACTIVITE)
        raise refus(MOTIF_INACTIVITE)
    if not requete_de_fond(request) and (a - derniere).total_seconds() >= ECRITURE_ACTIVITE_S:
        await noter_activite(sid, a, doc)


async def noter_activite(sid: str, a: Optional[datetime] = None, doc: Optional[dict] = None) -> None:
    a = a or maintenant()
    await db[COLLECTION].update_one({"id": sid, "fermee_le": None}, {"$set": {"derniere_activite": _iso(a)}})
    if doc is not None:
        _cache_sessions[sid] = (time.monotonic(), {**doc, "derniere_activite": _iso(a)})
    else:
        _cache_sessions.pop(sid, None)
