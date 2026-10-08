# decouverte_reseau.py — Lot 80 : ÉQUIPEMENTS → découverte du réseau des clients par Loois.
#
# Demande du propriétaire (08/10/2026) : « Loois peut-il faire l'inventaire de toutes les machines sur un réseau
# informatique ? » — accord sur trois points : menu « Équipements », découverte du réseau avec VALIDATION MANUELLE
# des nouveaux appareils, SNMP en lecture seule (communauté « public » par défaut, modifiable dans les Paramètres).
#
# En résumé (pour un développeur WinDev) :
#   1. Un poste Loois du client (par défaut : un Windows Server ; sinon les machines listées dans les réglages)
#      demande régulièrement sa CONSIGNE : GET /api/loois/decouverte-reseau/consigne (clé client X-Cle-Loois).
#      SAWALI répond « lancer » à l'heure prévue (une fois par jour) ou quand l'administrateur a cliqué
#      « Lancer maintenant » ; la réponse donne aussi la communauté SNMP (gardée CHIFFRÉE dans SAWALI) ;
#   2. Loois balaie son réseau local (ping, table ARP, nom d'hôte, SNMP en LECTURE SEULE) puis envoie la liste :
#      POST /api/loois/decouverte-reseau ;
#   3. Chaque appareil est rangé par client Loois et par adresse MAC (à défaut : adresse IP) dans la collection
#      `reseau_appareils`. Un appareil dont la MAC est déjà dans le Parc informatique est « connu » et lié à sa fiche
#      (les champs VIDES de la fiche sont complétés : n° de série, modèle, fabricant…, jamais une saisie à la main) ;
#      un appareil inconnu arrive « À valider » : l'administrateur le VALIDE (fiche créée dans le parc, « À affecter »
#      comme les fiches créées par Loois au lot 66) ou l'IGNORE (téléphone de passage…) ;
#   4. ALERTES : nombre d'appareils à valider, et appareils connus qui n'ont plus été vus depuis N jours alors que
#      le réseau de leur client a été balayé depuis (un balayage arrêté ne déclenche donc pas de fausse alerte).
#
# Aucune donnée sensible : adresses, noms, modèles et compteurs seulement (ni mot de passe, ni contenu).
from __future__ import annotations

import ipaddress
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request  # au niveau du module : l'annotation de la route doit être résolue (from __future__)

logger = logging.getLogger("sawali.decouverte_reseau")

ID_REGLAGES = "decouverte_reseau"          # document de db.loois_reglages (même collection que le lot 79.11)
MAX_APPAREILS = 1024                       # appareils acceptés par balayage (un /22 au plus)
MAX_APPAREILS_TOTAL = 20000                # plafond global de la collection (protection contre l'abus)
MAX_TEXTE = 200                            # longueur maximale d'un texte reçu
STATUTS = ("a_valider", "connu", "valide", "ignore")
LIBELLES_STATUT = {"a_valider": "À valider", "connu": "Déjà dans le parc", "valide": "Validé", "ignore": "Ignoré"}
# Catégories proposées par Loois → catégories du Parc informatique (lot 47)
CATEGORIES = {
    "imprimante": "Imprimante", "onduleur": "Onduleur", "switch": "Switch", "routeur": "Routeur",
    "serveur": "Serveur", "pc": "PC de bureau", "portable": "PC portable", "camera": "Caméra",
    "borne_wifi": "Borne Wi-Fi", "telephone": "Téléphone", "autre": "Autre",
}
REGLAGES_DEFAUT = {
    "actif": True,             # découverte autorisée
    "heure": "02:30",          # heure (UTC = heure du Burkina) du balayage quotidien
    "jours_absence": 7,        # alerte quand un appareil connu n'est plus vu depuis N jours
    "postes": [],              # machines autorisées à balayer (vide = les Windows Server qui ont Loois)
    "demande_le": None,        # dernier clic « Lancer maintenant »
}
_HEURE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_MACHINE = re.compile(r"^[A-Za-z0-9._\-]{1,80}$")


def _maintenant() -> datetime:
    """Date et heure actuelles (UTC)."""
    return datetime.now(timezone.utc)


def _date(iso: Any) -> Optional[datetime]:
    """Texte ISO → date (UTC) ; None si absent ou illisible."""
    try:
        d = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# =====================================================================================
# Logique pure (testée : tests/test_lot80_equipements.py)
# =====================================================================================

def normaliser_mac(valeur: Any) -> Optional[str]:
    """« aa-bb-cc-dd-ee-ff » → « AA:BB:CC:DD:EE:FF » ; None si invalide, nulle ou diffusion."""
    hexa = re.sub(r"[\s:.\-]", "", str(valeur or ""))
    if not re.fullmatch(r"[0-9A-Fa-f]{12}", hexa) or set(hexa) in ({"0"}, {"F"}, {"f"}, {"F", "f"}):
        return None
    return ":".join(hexa[i:i + 2] for i in range(0, 12, 2)).upper()


def mac_aleatoire(mac: Optional[str]) -> bool:
    """Vrai si l'adresse MAC est « administrée localement » (bit 0x02 du 1er octet) : adresse ALÉATOIRE, typique des
    téléphones et tablettes qui changent d'adresse à chaque réseau (à ne pas confondre avec un poste fixe)."""
    if not mac:
        return False
    try:
        return bool(int(mac[:2], 16) & 0x02)
    except ValueError:
        return False


def normaliser_ipv4(valeur: Any) -> Optional[str]:
    """Adresse IPv4 privée canonique, ou None (publique, boucle locale, APIPA, multidiffusion : refusées)."""
    try:
        ip = ipaddress.ip_address(str(valeur or "").strip())
    except ValueError:
        return None
    if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return None
    return str(ip)


def _texte(valeur: Any, longueur: int = MAX_TEXTE) -> Optional[str]:
    """Texte court nettoyé (caractères de contrôle retirés), ou None."""
    if valeur is None or isinstance(valeur, (dict, list)):
        return None
    t = re.sub(r"[\x00-\x1f\x7f]+", " ", str(valeur)).strip()[:longueur]
    return t or None


def _entier(valeur: Any, maxi: int = 10**12) -> Optional[int]:
    """Entier positif borné, ou None."""
    try:
        n = int(valeur)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= maxi else None


def nettoyer_appareil(brut: Any) -> Optional[Dict[str, Any]]:
    """Un appareil envoyé par Loois, nettoyé. None s'il n'a ni IP privée valable ni MAC valable.

    Champs gardés : ip, mac, mac_aleatoire, nom_hote, categorie (proposée), temps_ms, snmp {description, nom,
    lieu, contact, fabricant, modele, numero_serie, firmware, uptime_s, pages, consommables [{nom, pct}]}."""
    if not isinstance(brut, dict):
        return None
    ip = normaliser_ipv4(brut.get("ip"))
    mac = normaliser_mac(brut.get("mac"))
    if not ip and not mac:
        return None
    categorie = str(brut.get("categorie") or "").strip().lower()
    propre: Dict[str, Any] = {
        "ip": ip, "mac": mac, "mac_aleatoire": mac_aleatoire(mac),
        "nom_hote": _texte(brut.get("nom_hote"), 120),
        "categorie": categorie if categorie in CATEGORIES else None,
        "temps_ms": _entier(brut.get("temps_ms"), 60000),
    }
    snmp = brut.get("snmp")
    if isinstance(snmp, dict):
        s = {
            "description": _texte(snmp.get("description"), 300), "nom": _texte(snmp.get("nom"), 120),
            "lieu": _texte(snmp.get("lieu"), 120), "contact": _texte(snmp.get("contact"), 120),
            "fabricant": _texte(snmp.get("fabricant"), 120), "modele": _texte(snmp.get("modele"), 160),
            "numero_serie": _texte(snmp.get("numero_serie"), 120), "firmware": _texte(snmp.get("firmware"), 120),
            "uptime_s": _entier(snmp.get("uptime_s")), "pages": _entier(snmp.get("pages")),
        }
        consommables = []
        for c in (snmp.get("consommables") or [])[:12]:
            if isinstance(c, dict) and _texte(c.get("nom"), 80):
                pct = _entier(c.get("pct"), 100)
                consommables.append({"nom": _texte(c.get("nom"), 80), "pct": pct})
        s["consommables"] = consommables
        propre["snmp"] = {k: v for k, v in s.items() if v not in (None, [], "")} or None
    else:
        propre["snmp"] = None
    return propre


def cle_appareil(appareil: Dict[str, Any]) -> str:
    """Clé d'un appareil dans le réseau d'un client : la MAC (stable), sinon « IP:<adresse> »."""
    return appareil.get("mac") or f"IP:{appareil.get('ip')}"


def nettoyer_envoi(corps: Any) -> Dict[str, Any]:
    """Corps de POST /api/loois/decouverte-reseau nettoyé. Lève ValueError si la machine manque ou si la liste est
    absente / trop longue. Les appareils illisibles sont ignorés ; les doublons (même clé) fusionnés."""
    if not isinstance(corps, dict):
        raise ValueError("objet JSON attendu")
    machine = _texte(corps.get("machine"), 80)
    if not machine or not _MACHINE.match(machine):
        raise ValueError("nom de machine manquant ou invalide")
    liste = corps.get("appareils")
    if not isinstance(liste, list):
        raise ValueError("liste « appareils » attendue")
    if len(liste) > MAX_APPAREILS:
        raise ValueError(f"trop d'appareils ({len(liste)} > {MAX_APPAREILS})")
    appareils: Dict[str, Dict[str, Any]] = {}
    for brut in liste:
        a = nettoyer_appareil(brut)
        if a:
            appareils.setdefault(cle_appareil(a), a)
    sous_reseaux = []
    for s in (corps.get("sous_reseaux") or [])[:8]:
        try:
            sous_reseaux.append(str(ipaddress.ip_network(str(s), strict=False)))
        except ValueError:
            continue
    return {"machine": machine, "sous_reseaux": sous_reseaux,
            "duree_s": _entier(corps.get("duree_s"), 86400), "appareils": list(appareils.values())}


def nettoyer_reglages(corps: Any) -> Dict[str, Any]:
    """Réglages saisis dans la rubrique des Paramètres, validés (ValueError avec message clair).
    Renvoie les champs à enregistrer ; la communauté SNMP est renvoyée en clair sous « communaute » (chiffrée ensuite)."""
    if not isinstance(corps, dict):
        raise ValueError("objet JSON attendu")
    propre: Dict[str, Any] = {}
    if "actif" in corps:
        propre["actif"] = bool(corps.get("actif"))
    if "heure" in corps:
        heure = str(corps.get("heure") or "").strip()
        if not _HEURE.match(heure):
            raise ValueError("heure attendue au format HH:MM (ex. 02:30)")
        propre["heure"] = heure
    if "jours_absence" in corps:
        jours = _entier(corps.get("jours_absence"), 365)
        if not jours:
            raise ValueError("nombre de jours d'absence attendu (1 à 365)")
        propre["jours_absence"] = jours
    if "postes" in corps:
        postes = corps.get("postes")
        if isinstance(postes, str):
            postes = re.split(r"[\s,;]+", postes)
        if not isinstance(postes, list):
            raise ValueError("liste de machines attendue")
        noms = []
        for p in postes[:50]:
            nom = str(p or "").strip().upper()
            if not nom:
                continue
            if not _MACHINE.match(nom):
                raise ValueError(f"nom de machine invalide : « {nom} »")
            if nom not in noms:
                noms.append(nom)
        propre["postes"] = noms
    if "communaute" in corps:
        communaute = str(corps.get("communaute") or "").strip()
        if communaute:   # vide = inchangée
            if len(communaute) > 64 or not re.fullmatch(r"[\x21-\x7e]+", communaute):
                raise ValueError("communauté SNMP invalide (1 à 64 caractères visibles, sans espace)")
            propre["communaute"] = communaute
    return propre


def doit_lancer(reglages: Dict[str, Any], machine: str, type_poste: Optional[str],
                derniere_execution: Optional[str], maintenant: datetime) -> Dict[str, Any]:
    """Consigne donnée à un poste Loois : {"lancer": bool, "raison": texte}.

    - découverte désactivée → non ;
    - machine non autorisée (liste « postes » vide : seulement les Windows Server) → non ;
    - « Lancer maintenant » cliqué après la dernière exécution de cette machine → oui ;
    - sinon une fois par jour, à partir de l'heure réglée (UTC), si la machine n'a pas encore balayé depuis."""
    r = {**REGLAGES_DEFAUT, **(reglages or {})}
    if not r.get("actif"):
        return {"lancer": False, "raison": "découverte désactivée dans SAWALI"}
    postes = [p.upper() for p in (r.get("postes") or [])]
    nom = (machine or "").upper()
    if postes and nom not in postes:
        return {"lancer": False, "raison": "machine non choisie pour la découverte"}
    if not postes and (type_poste or "").lower() != "serveur":
        return {"lancer": False, "raison": "découverte réservée aux Windows Server (aucune machine choisie)"}
    derniere = _date(derniere_execution)
    demande = _date(r.get("demande_le"))
    if demande and (derniere is None or demande > derniere):
        return {"lancer": True, "raison": "demandée depuis SAWALI"}
    try:
        h, m = (int(x) for x in str(r.get("heure") or "02:30").split(":"))
    except ValueError:
        h, m = 2, 30
    prevue = maintenant.replace(hour=h, minute=m, second=0, microsecond=0)
    if maintenant < prevue:
        prevue -= timedelta(days=1)          # avant l'heure du jour : le créneau en cours est celui de la veille
    if derniere is None or derniere < prevue:
        return {"lancer": True, "raison": f"balayage quotidien de {r.get('heure')}"}
    return {"lancer": False, "raison": "déjà fait aujourd'hui"}


def champs_parc_reseau(appareil: Dict[str, Any]) -> Dict[str, Any]:
    """Champs du Parc informatique (lot 47) qu'un appareil découvert peut remplir (valeurs non vides seulement)."""
    snmp = appareil.get("snmp") or {}
    champs = {
        "adresse_ip": appareil.get("ip"), "adresse_mac": appareil.get("mac"),
        "nom_hote": appareil.get("nom_hote") or snmp.get("nom"),
        "fabricant": snmp.get("fabricant"), "modele": snmp.get("modele"), "numero_serie": snmp.get("numero_serie"),
    }
    return {k: v for k, v in champs.items() if v not in (None, "")}


def completer_fiche(existant: Dict[str, Any], champs: Dict[str, Any]) -> Dict[str, Any]:
    """Champs à écrire sur une fiche EXISTANTE du parc : seulement ceux qui sont VIDES (jamais une saisie)."""
    return {k: v for k, v in champs.items() if existant.get(k) in (None, "")}


def appareils_absents(appareils: List[Dict[str, Any]], dernieres_decouvertes: Dict[str, str],
                      jours: int) -> List[Dict[str, Any]]:
    """Appareils CONNUS ou VALIDÉS qui n'ont plus été vus depuis `jours` jours ALORS QUE le réseau de leur client a
    été balayé depuis (sinon le balayage est simplement arrêté : pas d'alerte). Les plus anciens d'abord."""
    sortie = []
    for a in appareils:
        if a.get("statut") not in ("connu", "valide"):
            continue
        vu = _date(a.get("derniere_vue"))
        balayage = _date(dernieres_decouvertes.get(a.get("cle_client") or ""))
        if vu and balayage and balayage - vu >= timedelta(days=jours):
            sortie.append({**a, "absent_jours": (balayage - vu).days})
    sortie.sort(key=lambda a: a.get("derniere_vue") or "")
    return sortie


# =====================================================================================
# Routes
# =====================================================================================

def setup_decouverte_reseau_routes(*, db, api, get_current_user) -> None:
    """Branche les routes du lot 80 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException
    from routes import loois_cles_clients as cles
    from routes.loois_secrets_hfsql import chiffrer, dechiffrer
    from routes.parc_informatique import cle_serie
    from routes.versions_deployees import _numero_inventaire_loois

    def _admin(user: dict) -> None:
        """Réservé à l'administrateur (comme « Postes et serveurs »)."""
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    async def _reglages() -> Dict[str, Any]:
        """Réglages enregistrés (valeurs par défaut pour les champs absents)."""
        doc = await db.loois_reglages.find_one({"id": ID_REGLAGES}, {"_id": 0}) or {}
        return {**REGLAGES_DEFAUT, **doc}

    async def _client_loois(request: Request, machine: str) -> Dict[str, Any]:
        """Identité du client Loois (clé CLIENT obligatoire : le réseau doit être rattaché à un établissement)."""
        identite = await cles.identifier_cle(db, request.headers.get("X-Cle-Loois"), machine=machine)
        if not identite or identite.get("type") != "client":
            raise HTTPException(status_code=401, detail="clé client Loois absente ou refusée", headers=cles.EN_TETE_REFUS)
        return identite

    async def _dernieres_decouvertes() -> Dict[str, str]:
        """Date du dernier balayage reçu, par client Loois."""
        sortie: Dict[str, str] = {}
        async for d in db.reseau_decouvertes.find({}, {"_id": 0, "cle_client": 1, "recu_le": 1}).sort("recu_le", -1).limit(500):
            sortie.setdefault(d.get("cle_client") or "", d.get("recu_le"))
        return sortie

    # ---------------------------------------------------------------- Loois -----------------
    @api.get("/loois/decouverte-reseau/consigne", tags=["Loois"])
    async def consigne(request: Request, machine: str = "", type_poste: str = ""):
        """Consigne du poste Loois : faut-il balayer le réseau maintenant ? (avec la communauté SNMP)."""
        nom = (machine or "").strip()[:80]
        if not nom or not _MACHINE.match(nom):
            raise HTTPException(status_code=422, detail="machine attendue")
        identite = await _client_loois(request, nom)
        reglages = await _reglages()
        derniere = await db.reseau_decouvertes.find_one(
            {"cle_client": identite["id"], "machine": nom.upper()}, {"_id": 0, "recu_le": 1}, sort=[("recu_le", -1)])
        decision = doit_lancer(reglages, nom, type_poste, (derniere or {}).get("recu_le"), _maintenant())
        if decision["lancer"]:
            decision["communaute"] = dechiffrer(reglages.get("communaute_chiffree")) or "public"
        return decision

    @api.post("/loois/decouverte-reseau", tags=["Loois"])
    async def recevoir(request: Request):
        """Résultat d'un balayage : appareils rangés par client, liés au parc (connus) ou mis « À valider »."""
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        try:
            envoi = nettoyer_envoi(corps)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        identite = await _client_loois(request, envoi["machine"])
        maintenant = _maintenant().isoformat()
        nouveaux = connus = 0
        for a in envoi["appareils"]:
            cle = cle_appareil(a)
            filtre = {"cle_client": identite["id"], "cle": cle}
            existant = await db.reseau_appareils.find_one(filtre, {"_id": 0})
            if not existant and await db.reseau_appareils.count_documents({}) >= MAX_APPAREILS_TOTAL:
                continue
            # Fiche du parc portant la même MAC (déjà saisie à la main ou créée par Loois au lot 66)
            fiche = None
            if a.get("mac"):
                fiche = await db.parc_equipements.find_one({"adresse_mac": a["mac"]}, {"_id": 0})
            statut = (existant or {}).get("statut") or "a_valider"
            if fiche and statut in ("a_valider", "connu"):
                statut = "connu"
            maj = {**a, "cle": cle, "cle_client": identite["id"], "client_code": identite.get("code"),
                   "client_libelle": identite.get("libelle"), "derniere_vue": maintenant,
                   "vu_par": envoi["machine"], "statut": statut}
            if fiche:
                maj["equipement_id"] = fiche["id"]
                maj["numero_inventaire"] = fiche.get("numero_inventaire")
                # Champs VIDES de la fiche complétés (n° de série unique dans le parc du client)
                a_ecrire = completer_fiche(fiche, champs_parc_reseau(a))
                if a_ecrire.get("numero_serie"):
                    a_ecrire["numero_serie_cle"] = cle_serie(a_ecrire["numero_serie"])
                    if await db.parc_equipements.find_one({"tenant_id": fiche.get("tenant_id"), "id": {"$ne": fiche["id"]},
                                                           "numero_serie_cle": a_ecrire["numero_serie_cle"]}, {"_id": 1}):
                        a_ecrire.pop("numero_serie")
                        a_ecrire.pop("numero_serie_cle")
                a_ecrire.pop("adresse_mac", None)   # la MAC est déjà celle de la fiche
                await db.parc_equipements.update_one({"id": fiche["id"]}, {"$set": {
                    **a_ecrire, "reseau": {"ip": a.get("ip"), "vu_le": maintenant, "vu_par": envoi["machine"],
                                           "snmp": a.get("snmp")}}})
                connus += 1
            elif not existant:
                nouveaux += 1
            await db.reseau_appareils.update_one(filtre, {
                "$set": maj, "$setOnInsert": {"id": secrets.token_hex(8), "premiere_vue": maintenant}}, upsert=True)
        await db.reseau_decouvertes.insert_one({
            "id": secrets.token_hex(8), "cle_client": identite["id"], "client_code": identite.get("code"),
            "client_libelle": identite.get("libelle"), "machine": envoi["machine"].upper(),
            "sous_reseaux": envoi["sous_reseaux"], "duree_s": envoi["duree_s"], "recu_le": maintenant,
            "total": len(envoi["appareils"]), "nouveaux": nouveaux, "connus": connus})
        return {"ok": True, "total": len(envoi["appareils"]), "nouveaux": nouveaux, "connus": connus}

    # ---------------------------------------------------------------- Administration --------
    @api.get("/admin/equipements/reseau", tags=["Équipements"])
    async def liste(statut: str = "a_valider", client: str = "", user: dict = Depends(get_current_user)):
        """Appareils découverts (filtre par statut et par client Loois), alertes et derniers balayages."""
        _admin(user)
        q: Dict[str, Any] = {}
        if statut in STATUTS:
            q["statut"] = statut
        if client:
            q["cle_client"] = client
        appareils = [a async for a in db.reseau_appareils.find(q, {"_id": 0}).sort("derniere_vue", -1).limit(2000)]
        compteurs = {s: await db.reseau_appareils.count_documents({**({"cle_client": client} if client else {}), "statut": s})
                     for s in STATUTS}
        reglages = await _reglages()
        dernieres = await _dernieres_decouvertes()
        suivis = [a async for a in db.reseau_appareils.find(
            {"statut": {"$in": ["connu", "valide"]}, **({"cle_client": client} if client else {})}, {"_id": 0})]
        clients = {}
        async for d in db.reseau_appareils.find({}, {"_id": 0, "cle_client": 1, "client_libelle": 1, "client_code": 1}):
            clients.setdefault(d.get("cle_client"), d.get("client_libelle") or d.get("client_code"))
        balayages = [d async for d in db.reseau_decouvertes.find({}, {"_id": 0}).sort("recu_le", -1).limit(10)]
        return {
            "appareils": appareils, "compteurs": compteurs, "libelles_statut": LIBELLES_STATUT,
            "categories": CATEGORIES,
            "alertes": {"a_valider": compteurs["a_valider"],
                        "absents": appareils_absents(suivis, dernieres, int(reglages.get("jours_absence") or 7))[:200]},
            "clients": [{"id": k, "libelle": v} for k, v in clients.items() if k],
            "balayages": balayages,
        }

    @api.post("/admin/equipements/reseau/{appareil_id}/valider", tags=["Équipements"])
    async def valider(appareil_id: str, request: Request, user: dict = Depends(get_current_user)):
        """Valide un appareil : fiche créée dans le Parc informatique (« À affecter »), ou liée si la MAC y est déjà."""
        _admin(user)
        a = await db.reseau_appareils.find_one({"id": appareil_id}, {"_id": 0})
        if not a:
            raise HTTPException(status_code=404, detail="Appareil introuvable")
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            corps = {}
        categorie = CATEGORIES.get(str((corps or {}).get("categorie") or a.get("categorie") or "autre").lower(), "Autre")
        maintenant = _maintenant().isoformat()
        fiche = await db.parc_equipements.find_one({"adresse_mac": a["mac"]}, {"_id": 0, "id": 1, "numero_inventaire": 1}) \
            if a.get("mac") else None
        if not fiche:
            champs = champs_parc_reseau(a)
            if champs.get("numero_serie"):
                champs["numero_serie_cle"] = cle_serie(champs["numero_serie"])
            snmp = a.get("snmp") or {}
            note = (f"Découvert sur le réseau de {a.get('client_libelle') or a.get('client_code') or '—'} "
                    f"par {a.get('vu_par') or 'Loois'} le {maintenant[:10]}."
                    + (f" {snmp.get('description')}" if snmp.get("description") else ""))
            fiche = {
                "id": secrets.token_hex(8), "tenant_id": None, "client_nom": "",
                "numero_inventaire": await _numero_inventaire_loois(db), "categorie": categorie,
                "fabricant": None, "modele": None, "numero_serie": None, "numero_serie_cle": None, "adresse_ip": None,
                "adresse_mac": None, "nom_hote": None, "systeme_exploitation": None, "utilisateur_affecte": None,
                "site": a.get("client_libelle"), "service": None, "bureau": None, "date_achat": None,
                "fin_garantie": None, "fournisseur": None, "etat": "en_service", "notes": note[:4000], "photos": [],
                **champs, "reseau": {"ip": a.get("ip"), "vu_le": a.get("derniere_vue"), "vu_par": a.get("vu_par"),
                                     "snmp": a.get("snmp")},
                "source": "decouverte_reseau", "cree_par": f"{user.get('name') or user.get('email') or 'Administrateur'} (découverte réseau)",
                "cree_le": maintenant, "maj_le": maintenant,
            }
            await db.parc_equipements.insert_one(dict(fiche))
        await db.reseau_appareils.update_one({"id": appareil_id}, {"$set": {
            "statut": "valide", "equipement_id": fiche["id"], "numero_inventaire": fiche.get("numero_inventaire"),
            "valide_le": maintenant, "valide_par": user.get("email")}})
        return {"ok": True, "equipement_id": fiche["id"], "numero_inventaire": fiche.get("numero_inventaire")}

    @api.post("/admin/equipements/reseau/{appareil_id}/ignorer", tags=["Équipements"])
    async def ignorer(appareil_id: str, user: dict = Depends(get_current_user)):
        """Ignore un appareil (téléphone de passage…) : il ne revient plus « À valider »."""
        _admin(user)
        r = await db.reseau_appareils.update_one({"id": appareil_id}, {"$set": {
            "statut": "ignore", "ignore_le": _maintenant().isoformat(), "ignore_par": user.get("email")}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Appareil introuvable")
        return {"ok": True}

    @api.post("/admin/equipements/reseau/{appareil_id}/remettre", tags=["Équipements"])
    async def remettre(appareil_id: str, user: dict = Depends(get_current_user)):
        """Remet un appareil ignoré ou validé « À valider » (la fiche du parc éventuelle est conservée)."""
        _admin(user)
        r = await db.reseau_appareils.update_one({"id": appareil_id}, {"$set": {"statut": "a_valider"}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Appareil introuvable")
        return {"ok": True}

    def _vue_reglages(r: Dict[str, Any], derniers: List[Dict[str, Any]], a_valider: int) -> Dict[str, Any]:
        """Réglages renvoyés à l'écran : la communauté SNMP n'est JAMAIS réaffichée (seulement « personnalisée »)."""
        return {"actif": bool(r.get("actif")), "heure": r.get("heure"), "jours_absence": r.get("jours_absence"),
                "postes": r.get("postes") or [], "demande_le": r.get("demande_le"),
                "communaute_personnalisee": bool(r.get("communaute_chiffree")),
                "maj_le": r.get("maj_le"), "maj_par": r.get("maj_par"),
                "derniers_balayages": derniers, "a_valider": a_valider}

    async def _etat() -> Dict[str, Any]:
        derniers = [d async for d in db.reseau_decouvertes.find({}, {"_id": 0}).sort("recu_le", -1).limit(5)]
        return _vue_reglages(await _reglages(), derniers, await db.reseau_appareils.count_documents({"statut": "a_valider"}))

    @api.get("/admin/equipements/decouverte-reglages", tags=["Équipements"])
    async def lire_reglages(user: dict = Depends(get_current_user)):
        """Réglages de la découverte (rubrique des Paramètres) et derniers balayages."""
        _admin(user)
        return await _etat()

    @api.put("/admin/equipements/decouverte-reglages", tags=["Équipements"])
    async def enregistrer_reglages(request: Request, user: dict = Depends(get_current_user)):
        """Enregistre les réglages ; la communauté SNMP est chiffrée (« public » si elle est effacée)."""
        _admin(user)
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        try:
            propre = nettoyer_reglages(corps)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        a_ecrire = {k: v for k, v in propre.items() if k != "communaute"}
        if propre.get("communaute"):
            a_ecrire["communaute_chiffree"] = chiffrer(propre["communaute"])
        if (corps or {}).get("communaute_par_defaut"):
            a_ecrire["communaute_chiffree"] = None   # retour à « public »
        a_ecrire.update({"maj_le": _maintenant().isoformat(), "maj_par": user.get("email")})
        await db.loois_reglages.update_one({"id": ID_REGLAGES}, {"$set": {"id": ID_REGLAGES, **a_ecrire}}, upsert=True)
        return await _etat()

    @api.post("/admin/equipements/decouverte-lancer", tags=["Équipements"])
    async def lancer_maintenant(user: dict = Depends(get_current_user)):
        """« Lancer maintenant » : les postes autorisés balaient le réseau à leur prochaine consigne (≤ 15 min)."""
        _admin(user)
        await db.loois_reglages.update_one({"id": ID_REGLAGES}, {"$set": {
            "id": ID_REGLAGES, "demande_le": _maintenant().isoformat(), "demande_par": user.get("email")}}, upsert=True)
        return await _etat()
