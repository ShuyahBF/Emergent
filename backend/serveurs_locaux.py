# serveurs_locaux.py — SERVEURS LOCAUX REMONTÉS PAR LOOIS et accès hors Internet de « Loois Mobile » (logique pure + stockage, sans accès réseau).
#
# Demande du propriétaire (27/11/2026) : l'adresse du serveur local est connue de Loois (fichier .ini du logiciel selon la zone, ou saisie au premier lancement) ; SAWALI la conserve
# pour la donner aux téléphones, qui n'ont ainsi rien à saisir. Quand Internet manque, le téléphone parle à la PASSERELLE du service Windows Loois, sur le réseau local.
#
# En résumé (pour un développeur WinDev) :
#   1. Le service Windows Loois de chaque machine signale à SAWALI (POST /api/loois/serveur-local, clé client Loois) : serveur HFSQL (nom:port), adresses IP locales de la machine,
#      port de sa passerelle, zone, base. JAMAIS de mot de passe. SAWALI garde cela dans UNE fiche de `loois_reglages` (id « serveurs_locaux »), par client et par machine.
#   2. SAWALI remet au service un SECRET DE PASSERELLE propre au client (aléatoire, gardé chiffré). Le service le garde ; SAWALI s'en sert pour signer deux sortes de jetons :
#        - le TICKET LOCAL d'un appareil (72 h) : prouve que l'administrateur a autorisé cet appareil, vérifiable par la passerelle SANS Internet ;
#        - la SESSION d'un utilisateur (8 h) : la même session marche donc sur SAWALI et sur la passerelle.
#      Les clés de signature sont DÉRIVÉES du secret (SHA-256 d'une étiquette + du secret) : la passerelle fait le même calcul.
#   3. Le téléphone reçoit, dans son statut, la liste des adresses locales du client et son ticket local ; hors Internet il appelle ces adresses avec le ticket.
# Limite assumée : un appareil interdit n'est refusé hors Internet qu'à l'expiration de son ticket (72 h au plus) ; avec Internet, c'est immédiat.
from __future__ import annotations

import hashlib
import ipaddress
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt

ID_FICHE = "serveurs_locaux"
TICKET_TTL_H = 72
SESSION_TTL_H = 8
MAX_MACHINES_PAR_CLIENT = 30
MAX_IPS = 8
ACTUALITE_J = 7                         # une machine non vue depuis 7 jours n'est plus proposée aux téléphones
MAX_URLS = 6
_RE_POSTE = re.compile(r"^[\w .-]{1,80}$", re.UNICODE)
_RE_HFSQL = re.compile(r"^[\w.\-]{1,100}(:\d{1,5})?$")
_RE_NOM = re.compile(r"^[\w.\- ]{1,60}$", re.UNICODE)


# ---------------------------------------------------------------------------------------------------------------------------- clés dérivées
def cle_session(secret: str) -> str:
    """Clé de signature des SESSIONS d'utilisateurs (même calcul dans la passerelle)."""
    return hashlib.sha256(f"loois-android-session|{secret}".encode()).hexdigest()


def cle_ticket(secret: str) -> str:
    """Clé de signature des TICKETS LOCAUX d'appareils (même calcul dans la passerelle)."""
    return hashlib.sha256(f"loois-android-ticket|{secret}".encode()).hexdigest()


def creer_ticket(secret: str, appareil_id: str, client: str, zone: str, base: str, maintenant: Optional[datetime] = None) -> str:
    """Ticket local : appareil autorisé pour ce client, cette zone et cette base, 72 h."""
    t = maintenant or datetime.now(timezone.utc)
    return jwt.encode({"typ": "ticket", "aid": appareil_id, "client": client, "zone": zone, "base": base, "exp": t + timedelta(hours=TICKET_TTL_H)}, cle_ticket(secret), algorithm="HS256")


def lire_ticket(secret: str, ticket: str) -> Optional[Dict[str, Any]]:
    try:
        d = jwt.decode(ticket or "", cle_ticket(secret), algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        return None
    return d if d.get("typ") == "ticket" else None


def creer_session(secret: str, appareil_id: str, login: str, groupe: str, droits: Dict[str, Any], maintenant: Optional[datetime] = None) -> str:
    t = maintenant or datetime.now(timezone.utc)
    return jwt.encode({"typ": "session", "aid": appareil_id, "login": login, "groupe": groupe, "d": droits, "exp": t + timedelta(hours=SESSION_TTL_H)}, cle_session(secret), algorithm="HS256")


def lire_session(secret: str, session: str) -> Optional[Dict[str, Any]]:
    try:
        d = jwt.decode(session or "", cle_session(secret), algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        return None
    return d if d.get("typ") == "session" else None


# ---------------------------------------------------------------------------------------------------------------------------- contrôle des informations remontées
def adresse_privee(ip: Any) -> bool:
    """Adresse IPv4 du réseau local (10.x, 172.16-31.x, 192.168.x) : jamais une adresse publique."""
    try:
        a = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return False
    return a.version == 4 and a.is_private and not a.is_loopback and not a.is_link_local


def valider_infos(corps: Any) -> (Dict[str, Any], str):
    """(informations propres, message d'erreur) pour le corps remonté par le service."""
    if not isinstance(corps, dict):
        return {}, "Corps JSON attendu."
    ips = [str(i).strip() for i in (corps.get("ips_locales") or []) if str(i).strip()]
    ips = list(dict.fromkeys(i for i in ips if adresse_privee(i)))[:MAX_IPS]
    if not ips:
        return {}, "Au moins une adresse IP du réseau local (10.x, 172.16-31.x, 192.168.x) est requise."
    try:
        port = int(corps.get("port_passerelle"))
    except (TypeError, ValueError):
        return {}, "Port de la passerelle invalide."
    if not 1024 <= port <= 65535:
        return {}, "Port de la passerelle invalide (1024 à 65535)."
    hfsql = str(corps.get("serveur_hfsql") or "").strip()
    if hfsql and not _RE_HFSQL.match(hfsql):
        return {}, "Serveur HFSQL invalide (nom ou adresse, port facultatif)."
    zone = str(corps.get("zone") or "").strip()[:40]
    base = str(corps.get("base") or "").strip()
    if base and not _RE_NOM.match(base):
        return {}, "Nom de base invalide."
    return {"serveur_hfsql": hfsql, "ips": ips, "port": port, "zone": zone, "base": base, "version": str(corps.get("version") or "")[:30]}, ""


def nom_poste(valeur: Any) -> str:
    v = str(valeur or "").strip()
    return v if _RE_POSTE.match(v) else ""


def urls_locales(client_doc: Dict[str, Any], maintenant: Optional[datetime] = None) -> List[Dict[str, str]]:
    """Adresses de passerelle à proposer aux téléphones : machines vues depuis moins de 7 jours, la plus récente d'abord ; sans doublon, 6 au plus."""
    t = maintenant or datetime.now(timezone.utc)
    limite = (t - timedelta(days=ACTUALITE_J)).isoformat()
    machines = [(p, m) for p, m in (client_doc.get("machines") or {}).items() if isinstance(m, dict) and str(m.get("vu_le") or "") >= limite]
    machines.sort(key=lambda x: str(x[1].get("vu_le") or ""), reverse=True)
    sortie, vus = [], set()
    for cle, m in machines:
        for ip in m.get("ips") or []:
            url = f"http://{ip}:{m.get('port')}"
            if url not in vus:
                vus.add(url)
                sortie.append({"url": url, "poste": m.get("poste") or cle, "serveur_hfsql": m.get("serveur_hfsql") or ""})
    return sortie[:MAX_URLS]


# ---------------------------------------------------------------------------------------------------------------------------- stockage
def _chiffrer(clair: str) -> str:
    from routes.loois_secrets_hfsql import chiffrer
    return chiffrer(clair) or ""


def _dechiffrer(chiffre: Optional[str]) -> Optional[str]:
    from routes.loois_secrets_hfsql import dechiffrer
    return dechiffrer(chiffre)


async def lire_fiche(db) -> Dict[str, Any]:
    return await db.loois_reglages.find_one({"id": ID_FICHE}, {"_id": 0}) or {"id": ID_FICHE, "clients": {}}


async def lire_client(db, code: str) -> Dict[str, Any]:
    return ((await lire_fiche(db)).get("clients") or {}).get(code) or {}


async def secret_client(db, code: str, creer: bool = False) -> Optional[str]:
    """Secret de passerelle du client (clair), créé au besoin. La création est atomique : deux machines qui se signalent en même temps reçoivent le MÊME secret."""
    existant = _dechiffrer((await lire_client(db, code)).get("secret"))
    if existant or not creer:
        return existant
    await db.loois_reglages.update_one({"id": ID_FICHE}, {"$setOnInsert": {"clients": {}}}, upsert=True)
    nouveau = secrets.token_urlsafe(32)
    await db.loois_reglages.update_one({"id": ID_FICHE, f"clients.{code}.secret": {"$exists": False}},
                                       {"$set": {f"clients.{code}.secret": _chiffrer(nouveau), f"clients.{code}.secret_cree_le": datetime.now(timezone.utc).isoformat()}})
    return _dechiffrer((await lire_client(db, code)).get("secret"))


async def regenerer_secret(db, code: str) -> str:
    """Nouveau secret : tous les tickets et sessions signés avec l'ancien deviennent invalides (appareil perdu, doute)."""
    nouveau = secrets.token_urlsafe(32)
    await db.loois_reglages.update_one({"id": ID_FICHE}, {"$set": {f"clients.{code}.secret": _chiffrer(nouveau), f"clients.{code}.secret_cree_le": datetime.now(timezone.utc).isoformat()}}, upsert=True)
    return nouveau


async def enregistrer_machine(db, code: str, poste: str, infos: Dict[str, Any], maintenant: Optional[str] = None) -> bool:
    """Note ce que la machine vient de signaler. Rend faux si le client a déjà trop de machines (nouvelle machine refusée)."""
    client = await lire_client(db, code)
    machines = client.get("machines") or {}
    if poste not in machines and len(machines) >= MAX_MACHINES_PAR_CLIENT:
        return False
    await db.loois_reglages.update_one({"id": ID_FICHE}, {"$set": {f"clients.{code}.machines.{_cle_poste(poste)}": {**infos, "poste": poste, "vu_le": maintenant or datetime.now(timezone.utc).isoformat()}}}, upsert=True)
    return True


def _cle_poste(poste: str) -> str:
    """Nom de machine utilisable comme clé de document (points remplacés : MongoDB lit « a.b » comme un chemin)."""
    return poste.replace(".", "_")
