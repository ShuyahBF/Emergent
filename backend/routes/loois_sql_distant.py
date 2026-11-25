# loois_sql_distant.py — Lot 439 : REQUÊTES SQL À DISTANCE sur la base HFSQL d'un client, relayées par SAWALI.
#
# Demande du propriétaire (18/11/2026) : « Me permettre d'exécuter une requête SQL distante sur la base HFSQL distante sur laquelle le service est
# connecté [...] Dès que le service distant d'une machine distante ayant Loois se charge de la requête, plus aucune autre machine ne peut le faire.
# Le retour me dit quelle machine a exécuté. »
#
# En résumé (pour un développeur WinDev) :
#   1. Le propriétaire tape la requête dans Loois (Outils → « Requête SQL distante »). Loois l'envoie ici avec la CLÉ « SQL à distance »
#      (variable LOOIS_SQL_DISTANT_CLE saisie par le propriétaire dans Render, jamais dans le dépôt) ;
#   2. SAWALI la garde (état « attente ») dans db.loois_reglages {id: "sql_distant"} — aucune nouvelle collection (cluster plein) ;
#   3. le service Windows Loois de chaque machine demande toutes les 5 s « une requête pour mon client ? » (GET /loois-sql/poste/prochaine, clé CLIENT
#      Loois + code de sa base) : la PREMIÈRE machine qui la réclame la reçoit — l'opération est ATOMIQUE (une seule mise à jour conditionnelle) :
#      aucune autre machine ne peut plus la prendre ;
#   4. cette machine l'exécute sur sa base HFSQL et renvoie le résultat (POST /loois-sql/poste/resultat) : confirmation ou erreur HFSQL, base utilisée,
#      lignes (200 au plus). SAWALI y note le NOM de la machine ; Loois l'affiche.
#
# SÉCURITÉ (choix « Prudent ») : seulement SELECT / INSERT / UPDATE / DELETE, une instruction, UPDATE et DELETE avec WHERE, aucun mot de structure
# (DROP, ALTER, CREATE, TRUNCATE, EXEC…). Contrôle refait ICI (même règle que Loois et que le service). Une requête « prise » qui reste sans réponse
# n'est JAMAIS rejouée (une modification ne doit pas être exécutée deux fois) ; une requête qui attend trop longtemps expire. Le texte des requêtes
# n'est jamais écrit dans les journaux (il peut contenir des données de patients).
from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import unquote

from fastapi.responses import JSONResponse  # lot 449.1 : réponse 200 avec en-tête
from fastapi import Request, Response  # au niveau du module : les annotations des routes doivent être résolues (from __future__)

logger = logging.getLogger("sawali.loois_sql_distant")

# Lot 458 : fonctions INTERNES (dépôt, détail, clients en ligne) rendues disponibles aux autres modules du serveur (Commande HFSQL distante via Liluvine) : sans elles,
# Liluvine devrait passer par la clé « SQL à distance » ; ici elle utilise la même file, les mêmes contrôles (`verifier`) et les mêmes machines.
INTERNE: Dict[str, Any] = {}

ID_DOC = "sql_distant"
ID_INTERDITES = "sql_distant_interdites"   # lot 447 : machines INTERDITES par client (même collection, autre document : aucune nouvelle collection)
MACHINES_INTERDITES_MAX = 100              # par client
NOM_MACHINE_MAX = 80
MAX_REQUETES = 100                 # historique gardé dans le document (pas de nouvelle collection)
LONGUEUR_MAX = 4000
LIGNES_MAX = 200
CELLULE_MAX = 500
COLONNES_MAX = 100
RESULTAT_OCTETS_MAX = 200_000      # un résultat plus gros est tronqué (le document reste léger)
ATTENTE_MAX = timedelta(minutes=30)        # sans machine au bout de ce délai : requête expirée (jamais exécutée plus tard par surprise)
SANS_REPONSE = timedelta(minutes=10)       # machine qui a pris la requête mais ne répond plus
EN_LIGNE = timedelta(minutes=12)           # même seuil que « Postes Windows — versions déployées »
ESSAIS_CLE_MAX = 10                        # clés fausses par adresse IP et par 15 minutes
CREATIONS_PAR_HEURE = 600          # lot 444 : une session distante (écrans de données) envoie beaucoup de petites requêtes
ID_FAVORITES = "sql_distant_favorites"     # lot 449 : machines FAVORITES par client (même collection, autre document : aucune nouvelle collection)
FAVORITES_MAX = 20                         # par client
DELAI_FAVORITE_S = 4                       # lot 449 : une requête reste ce temps (secondes) réservée à une machine favorite EN LIGNE avant de passer à la suivante
FAVORITE_ACTIVE_S = 15                     # lot 449 : une favorite est « en ligne » si elle a interrogé SAWALI depuis moins de 15 secondes
SCRUTATION_VALIDE_S = 90           # lot 448.2 : une machine qui interroge SAWALI (« prochaine ») depuis moins de 90 s est « en ligne » pour les requêtes distantes
SESSION_VALIDE_S = 180             # lot 444 : une session « client distant » ouverte dans Loois reste active 3 minutes après son dernier signal

PREMIERS_MOTS = ("SELECT", "INSERT", "UPDATE", "DELETE")
MOTS_INTERDITS = ("DROP", "ALTER", "CREATE", "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE", "RENAME", "MERGE")
RE_CODE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


# ---------------------------------------------------------------------------
# Contrôle d'une requête (MÊME règle que Loois : RequeteSqlDistanteLogique.Verifier)
# ---------------------------------------------------------------------------
def verifier(sql: Optional[str]) -> Tuple[bool, str, str]:
    """(autorisee, nature « SELECT » ou « MODIF », raison du refus). Les textes entre apostrophes ou guillemets sont ignorés."""
    if not sql or not sql.strip():
        return False, "", "Saisissez la requête SQL."
    texte = sql.strip()
    while texte.endswith(";"):
        texte = texte[:-1].rstrip()
    if not texte:
        return False, "", "Saisissez la requête SQL."
    if len(texte) > LONGUEUR_MAX:
        return False, "", f"Requête trop longue ({len(texte)} caractères ; {LONGUEUR_MAX} au plus)."
    hors: List[str] = []
    ouvert: Optional[str] = None
    i = 0
    while i < len(texte):
        c = texte[i]
        if ouvert is None:
            if c in ("'", '"'):
                ouvert = c
                hors.append(" ")
            else:
                hors.append(c)
        else:
            if c == ouvert:
                if i + 1 < len(texte) and texte[i + 1] == ouvert:
                    i += 1
                else:
                    ouvert = None
            hors.append(" ")
        i += 1
    if ouvert is not None:
        return False, "", "Texte entre apostrophes ou guillemets non fermé."
    code = "".join(hors)
    if ";" in code:
        return False, "", "Une seule instruction à la fois (pas de « ; » au milieu)."
    if "--" in code or "/*" in code or "*/" in code:
        return False, "", "Les commentaires (-- et /* */) ne sont pas acceptés."
    m = re.match(r"^\s*([A-Za-z]+)\b", code)
    mot = m.group(1).upper() if m else ""
    if mot not in PREMIERS_MOTS:
        return False, "", "Seules les instructions SELECT, INSERT, UPDATE et DELETE sont autorisées."
    for interdit in MOTS_INTERDITS:
        if re.search(rf"\b{interdit}\b", code, re.IGNORECASE):
            return False, "", f"Le mot « {interdit} » n'est pas autorisé (aucune modification de structure ni exécution de procédure)."
    if mot in ("UPDATE", "DELETE") and not re.search(r"\bWHERE\b", code, re.IGNORECASE):
        return False, "", f"Un {mot} sans WHERE modifierait toute la table : ajoutez une condition WHERE."
    return True, ("SELECT" if mot == "SELECT" else "MODIF"), ""


def code_client(valeur: Any) -> str:
    """Code du client (ex. « ipm » → « IPM ») ; chaîne vide si invalide."""
    v = str(valeur or "").strip()
    return v.upper() if RE_CODE.match(v) else ""


def nom_machine(valeur: Any) -> str:
    """Nom de machine nettoyé (espaces retirés, 80 caractères au plus, aucun caractère de contrôle) ; chaîne vide si inutilisable."""
    t = re.sub(r"[\x00-\x1f\x7f]", "", str(valeur or "")).strip()
    return t[:NOM_MACHINE_MAX]


def normaliser_machines(valeurs: Any) -> List[str]:
    """Liste de noms de machines propre : sans vide ni doublon (la casse est ignorée, la première graphie est gardée), 100 au plus."""
    vus: set = set()
    res: List[str] = []
    for v in valeurs if isinstance(valeurs, list) else []:
        n = nom_machine(v)
        if n and n.casefold() not in vus:
            vus.add(n.casefold())
            res.append(n)
    return res[:MACHINES_INTERDITES_MAX]


def machine_interdite(machine: Any, interdites: Any) -> bool:
    """Vrai si ce nom de machine figure dans la liste des machines interdites du client (casse et espaces ignorés)."""
    m = nom_machine(machine).casefold()
    return bool(m) and any(nom_machine(x).casefold() == m for x in (interdites if isinstance(interdites, list) else []))


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _date(texte: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(texte) if texte else None
    except (TypeError, ValueError):
        return None


def vieillir(req: Dict[str, Any], maintenant: datetime) -> Dict[str, Any]:
    """Applique les délais : « attente » trop longue → expirée ; « prise » sans réponse → sans_reponse. Rend les champs à écrire (vide si rien ne change)."""
    if req.get("etat") == "attente":
        cree = _date(req.get("cree_le"))
        if cree and maintenant - cree > ATTENTE_MAX:
            return {"etat": "expiree", "fin_le": maintenant.isoformat(), "message": "Aucune machine du client ne s'est présentée à temps : requête expirée (non exécutée)."}
    elif req.get("etat") == "prise":
        prise = _date(req.get("prise_le"))
        if prise and maintenant - prise > SANS_REPONSE:
            return {"etat": "sans_reponse", "fin_le": maintenant.isoformat()}
    return {}


def resultat_borne(corps: Dict[str, Any]) -> Dict[str, Any]:
    """Résultat renvoyé par une machine, borné (colonnes, lignes, cellules, taille totale) avant d'être gardé."""
    colonnes = [str(c)[:100] for c in (corps.get("colonnes") or [])][:COLONNES_MAX]
    lignes: List[List[str]] = []
    taille = 0
    tronque = bool(corps.get("tronque"))
    for ligne in (corps.get("lignes") or []):
        if not isinstance(ligne, list):
            continue
        cellules = [("" if c is None else str(c))[:CELLULE_MAX] for c in ligne][:COLONNES_MAX]
        poids = sum(len(c) for c in cellules) + 4 * len(cellules)
        if len(lignes) >= LIGNES_MAX or taille + poids > RESULTAT_OCTETS_MAX:
            tronque = True
            break
        lignes.append(cellules)
        taille += poids
    try:
        affectees = int(corps.get("lignes_affectees") or 0)
        duree = int(corps.get("duree_ms") or 0)
    except (TypeError, ValueError):
        affectees, duree = 0, 0
    # Lot 443 — description des champs (clé primaire, automatique, calculé, type, table) : permet à Loois d'éditer une fiche sans toucher aux champs protégés
    schema = []
    for c in (corps.get("schema") or [])[:COLONNES_MAX]:
        if isinstance(c, dict):
            schema.append({"nom": str(c.get("nom") or "")[:100], "cle": bool(c.get("cle")), "auto": bool(c.get("auto")), "calcule": bool(c.get("calcule")), "memo": bool(c.get("memo")),
                           "type": str(c.get("type") or "")[:20], "table": str(c.get("table") or "")[:100]})
    return {"ok": bool(corps.get("ok")), "message": str(corps.get("message") or "")[:2000], "base": str(corps.get("base") or "")[:120],
            "colonnes": colonnes, "lignes": lignes, "tronque": tronque, "lignes_affectees": affectees, "duree_ms": duree, "schema": schema}


def vue_requete(req: Dict[str, Any], avec_lignes: bool = True) -> Dict[str, Any]:
    """Représentation envoyée à Loois (jamais l'adresse IP ni l'identifiant de clé)."""
    sortie = {k: req.get(k) for k in ("id", "client", "sql", "etat", "machine", "cree_le", "prise_le", "fin_le", "ok", "message", "base",
                                       "colonnes", "tronque", "lignes_affectees", "duree_ms", "schema", "machine_ip")}
    sortie["colonnes"] = sortie["colonnes"] or []
    sortie["schema"] = sortie["schema"] or []
    sortie["lignes"] = (req.get("lignes") or []) if avec_lignes else []
    return sortie


def rang_machine(machine: Any, favorites: Any) -> int:
    """Lot 449 : rang de préférence d'une machine (0 = la plus favorite). Une machine non favorite a le rang « nombre de favorites » (donc toutes les non favorites sont à égalité)."""
    liste = favorites if isinstance(favorites, list) else []
    m = nom_machine(machine).casefold()
    for i, f in enumerate(liste):
        if nom_machine(f).casefold() == m:
            return i
    return len(liste)


def doit_attendre(machine: Any, favorites: Any, interdites: Any, scrutations_client: Dict[str, float], maintenant: float, age_requete_s: float) -> bool:
    """Lot 449 : vrai si `machine` doit LAISSER la requête à une machine plus favorite.
    Condition : il existe une AUTRE machine, plus favorite, non interdite, EN LIGNE (a interrogé SAWALI depuis moins de FAVORITE_ACTIVE_S secondes),
    et la requête attend depuis moins de DELAI_FAVORITE_S secondes. Passé ce délai (favorite occupée ou lente), ou si aucune favorite n'est en ligne,
    la requête passe tout de suite à la première machine disponible."""
    if not isinstance(favorites, list) or not favorites or age_requete_s >= DELAI_FAVORITE_S:
        return False
    mon_rang = rang_machine(machine, favorites)
    moi = nom_machine(machine).casefold()
    for autre, instant in (scrutations_client or {}).items():
        if maintenant - instant > FAVORITE_ACTIVE_S or nom_machine(autre).casefold() == moi or machine_interdite(autre, interdites):
            continue
        if rang_machine(autre, favorites) < mon_rang:
            return True
    return False


def machines_qui_scrutent(table: Dict[str, Dict[str, float]], client: str, maintenant: float) -> List[str]:
    """Lot 448.2 : noms des machines d'un client qui ont interrogé SAWALI (« prochaine ») depuis moins de SCRUTATION_VALIDE_S secondes.
    `table` = {code client : {machine : instant monotone du dernier appel}}. Une machine qui répond réellement aux requêtes est « en ligne »,
    même si son signal de présence (toutes les 5 minutes) est en retard ou enregistré sous un autre nom."""
    return sorted(m for m, t in (table.get(client) or {}).items() if maintenant - t <= SCRUTATION_VALIDE_S)


def clients_en_ligne(fiches: List[Dict[str, Any]], maintenant: datetime) -> List[Dict[str, Any]]:
    """Regroupe les signaux de présence du service Windows par code de client : machines et état « en ligne » (vu depuis moins de 12 minutes)."""
    groupes: Dict[str, Dict[str, Any]] = {}
    for f in fiches:
        code = code_client(f.get("site"))
        if not code:
            continue
        g = groupes.setdefault(code, {"code": code, "machines": [], "en_ligne": False})
        vu = _date(f.get("vu_le"))
        en_ligne = bool(vu and maintenant - vu <= EN_LIGNE)
        machine = str(f.get("machine") or "").strip()
        if machine and machine not in g["machines"]:
            g["machines"].append(machine)
        g["en_ligne"] = g["en_ligne"] or en_ligne
    return sorted(groupes.values(), key=lambda g: g["code"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def setup_loois_sql_distant_routes(*, db, api, get_current_user=None, identifier_cle=None) -> None:
    """Branche les routes du lot 439 (appelée depuis server_parts/p20). `identifier_cle` injectable pour les tests."""
    from fastapi import Depends, HTTPException

    if identifier_cle is None:
        from routes.loois_cles_clients import identifier_cle as _identifier
        identifier_cle = _identifier

    echecs: Dict[str, Deque[float]] = defaultdict(deque)       # adresse IP → instants des clés fausses
    sessions: Dict[str, float] = {}                            # lot 444 : code client → instant (monotone) du dernier signal d'une session Loois
    creations: Deque[float] = deque()
    scrutations: Dict[str, Dict[str, float]] = defaultdict(dict)   # lot 448.2 : code client → {machine : instant du dernier « prochaine »} (mémoire seulement)

    def _ip(request: Request) -> str:
        return request.client.host if request.client else "inconnue"

    def _proprietaire(request: Request) -> None:
        """Clé « SQL à distance » du propriétaire exigée (comparaison à temps constant, essais limités par adresse IP)."""
        attendue = os.environ.get("LOOIS_SQL_DISTANT_CLE", "")
        if len(attendue) < 16:
            raise HTTPException(status_code=503, detail="Fonction non activée : saisissez LOOIS_SQL_DISTANT_CLE (16 caractères au moins) dans Render.")
        ip, maintenant = _ip(request), time.monotonic()
        file = echecs[ip]
        while file and maintenant - file[0] > 900:
            file.popleft()
        if len(file) >= ESSAIS_CLE_MAX:
            raise HTTPException(status_code=429, detail="Trop d'essais de clé : réessayez dans 15 minutes.")
        recue = request.headers.get("X-Loois-Sql-Cle", "")
        if not recue or not hmac.compare_digest(recue.encode(), attendue.encode()):
            file.append(maintenant)
            raise HTTPException(status_code=401, detail="Clé SQL à distance refusée.")

    async def _poste(request: Request) -> Dict[str, Any]:
        """Service Windows d'une machine : clé CLIENT Loois (la clé commune est refusée), nom de la machine, code de la base."""
        identite = await identifier_cle(db, request.headers.get("X-Loois-Cle"))
        if not identite or identite.get("type") != "client":
            raise HTTPException(status_code=401, detail="Clé client Loois requise")
        machine = unquote(request.headers.get("X-Loois-Poste", "")).strip()[:80]
        base = code_client(unquote(request.headers.get("X-Loois-Base", "")))
        if not machine or not base:
            raise HTTPException(status_code=422, detail="Machine et base requises")
        return {"identite": identite, "machine": machine, "base": base}

    async def _lire() -> Dict[str, Any]:
        return await db.loois_reglages.find_one({"id": ID_DOC}, {"_id": 0}) or {"id": ID_DOC, "requetes": []}

    async def _interdites_doc() -> Dict[str, List[str]]:
        """Machines interdites de TOUS les clients : {code client : [noms]}."""
        doc = await db.loois_reglages.find_one({"id": ID_INTERDITES}, {"_id": 0}) or {}
        return {c: normaliser_machines(m) for c, m in (doc.get("clients") or {}).items()}

    cache_favorites: Dict[str, Any] = {"instant": 0.0, "donnees": {}}      # lot 449 : relu au plus toutes les 5 s (les machines interrogent chaque seconde)

    async def _favorites_doc() -> Dict[str, List[str]]:
        """Machines favorites de TOUS les clients : {code client : [noms dans l'ordre de préférence]} (cache de 5 s)."""
        if time.monotonic() - cache_favorites["instant"] < 5:
            return cache_favorites["donnees"]
        doc = await db.loois_reglages.find_one({"id": ID_FAVORITES}, {"_id": 0}) or {}
        cache_favorites["donnees"] = {c: normaliser_machines(m)[:FAVORITES_MAX] for c, m in (doc.get("clients") or {}).items()}
        cache_favorites["instant"] = time.monotonic()
        return cache_favorites["donnees"]

    async def _favorites_definir(client_code: Any, machines: Any, auteur: str) -> Dict[str, Any]:
        """Remplace la liste (ORDONNÉE : la première est la plus favorite) des machines favorites d'UN client. Liste vide = plus de favorite."""
        client = code_client(client_code)
        if not client:
            raise HTTPException(status_code=422, detail="Client invalide (lettres, chiffres, « _ » ou « - », 20 au plus).")
        if not isinstance(machines, list):
            raise HTTPException(status_code=422, detail="Liste « machines » attendue.")
        propre = normaliser_machines(machines)[:FAVORITES_MAX]
        await db.loois_reglages.update_one({"id": ID_FAVORITES}, {"$set": {f"clients.{client}": propre, "modifie_le": _maintenant().isoformat(), "modifie_par": auteur}}, upsert=True)
        cache_favorites["instant"] = 0.0                                   # relecture immédiate
        logger.info("[loois-sql] machines favorites du client %s : %d machine(s)", client, len(propre))
        return {"client": client, "machines": propre}

    async def _interdites_definir(client_code: Any, machines: Any, auteur: str) -> Dict[str, Any]:
        """Remplace la liste des machines interdites d'UN client (liste vide = plus aucune interdiction). `auteur` = compte ou « Loois » (clé)."""
        client = code_client(client_code)
        if not client:
            raise HTTPException(status_code=422, detail="Client invalide (lettres, chiffres, « _ » ou « - », 20 au plus).")
        if not isinstance(machines, list):
            raise HTTPException(status_code=422, detail="Liste « machines » attendue.")
        propre = normaliser_machines(machines)
        await db.loois_reglages.update_one({"id": ID_INTERDITES}, {"$set": {f"clients.{client}": propre, "modifie_le": _maintenant().isoformat(), "modifie_par": auteur}}, upsert=True)
        logger.info("[loois-sql] machines interdites du client %s : %d machine(s)", client, len(propre))
        return {"client": client, "machines": propre}

    async def _vieillir_tout(doc: Dict[str, Any]) -> None:
        """Applique les délais à toutes les requêtes en cours (écriture seulement si quelque chose change)."""
        maintenant = _maintenant()
        for r in doc.get("requetes", []):
            maj = vieillir(r, maintenant)
            if maj:
                await db.loois_reglages.update_one({"id": ID_DOC, "requetes": {"$elemMatch": {"id": r["id"], "etat": r["etat"]}}},
                                                   {"$set": {f"requetes.$.{k}": v for k, v in maj.items()}})
                r.update(maj)

    # ----------------------------------------------------------------- propriétaire (Loois)
    async def _clients_impl():
        """Clients dont un service Windows Loois a donné signe de vie (code de la base, machines, en ligne ou non)."""
        seuil = (_maintenant() - timedelta(days=30)).isoformat()
        fiches = [f async for f in db.presences_logiciels.find(
            {"application": {"$regex": "^LooisSyncService", "$options": "i"}, "vu_le": {"$gte": seuil}},
            {"_id": 0, "site": 1, "machine": 1, "vu_le": 1})]
        liste = clients_en_ligne(fiches, _maintenant())
        # Lot 448.2 : une machine qui interroge SAWALI en ce moment répond aux requêtes : son client est « en ligne », même sans signal de présence récent
        instant = time.monotonic()
        par_code = {c["code"]: c for c in liste}
        for code_scrute in list(scrutations.keys()):
            actives = machines_qui_scrutent(scrutations, code_scrute, instant)
            if not actives:
                continue
            c = par_code.get(code_scrute)
            if c is None:
                c = {"code": code_scrute, "machines": [], "en_ligne": True}
                liste.append(c)
                par_code[code_scrute] = c
            c["en_ligne"] = True
            c["repond"] = True
            for m in actives:
                if m not in c["machines"]:
                    c["machines"].append(m)
        liste.sort(key=lambda g: g["code"])
        interdites = await _interdites_doc()
        vus = {c["code"] for c in liste}
        for c in liste:
            c["interdites"] = interdites.get(c["code"], [])                 # lot 447 : machines interdites de ce client
        # Un client qui a une liste d'interdictions mais dont aucune machine n'a été vue récemment reste visible (on doit pouvoir la modifier)
        for code, noms in sorted(interdites.items()):
            if code not in vus and noms:
                liste.append({"code": code, "machines": [], "en_ligne": False, "interdites": noms})
        # Lot 449 : machines favorites de chaque client (même traitement : un client avec des favorites reste visible)
        favorites = await _favorites_doc()
        deja = {c["code"] for c in liste}
        for c in liste:
            c["favorites"] = favorites.get(c["code"], [])
        for code, noms in sorted(favorites.items()):
            if code not in deja and noms:
                liste.append({"code": code, "machines": [], "en_ligne": False, "interdites": [], "favorites": noms})
        return {"clients": liste}

    async def _creer_impl(corps, ip: str, auteur: str = ""):
        """Dépose une requête : elle attend qu'UNE machine du client la prenne. `auteur` = compte SAWALI (page web / Android), vide pour Loois (clé)."""
        client = code_client((corps or {}).get("client"))
        if not client:
            raise HTTPException(status_code=422, detail="Client invalide (lettres, chiffres, « _ » ou « - », 20 au plus).")
        sql = str((corps or {}).get("sql") or "").strip()
        ok, nature, raison = verifier(sql)
        if not ok:
            raise HTTPException(status_code=422, detail=raison)
        maintenant = time.monotonic()
        while creations and maintenant - creations[0] > 3600:
            creations.popleft()
        if len(creations) >= CREATIONS_PAR_HEURE:
            raise HTTPException(status_code=429, detail="Trop de requêtes envoyées cette heure.")
        creations.append(maintenant)
        req = {"id": secrets.token_hex(6), "client": client, "sql": sql.rstrip(";").strip(), "nature": nature, "etat": "attente", "machine": None,
               "cree_le": _maintenant().isoformat(), "cree_ip": ip, "cree_par": auteur, "ok": None, "message": "", "base": "", "colonnes": [], "lignes": [],
               "tronque": False, "lignes_affectees": 0, "duree_ms": 0, "schema": [],
               "ephemere": bool((corps or {}).get("ephemere"))}
        sessions[client] = time.monotonic()                      # envoyer une requête vaut signal de session
        await db.loois_reglages.update_one({"id": ID_DOC}, {"$push": {"requetes": {"$each": [req], "$slice": -MAX_REQUETES}}}, upsert=True)
        logger.info("[loois-sql] requête %s déposée pour le client %s (%s)", req["id"], client, nature)
        return vue_requete(req)

    async def _historique_impl():
        """Les 30 dernières requêtes, de la plus récente à la plus ancienne (sans les lignes : voir le détail de chacune)."""
        doc = await _lire()
        await _vieillir_tout(doc)
        return {"requetes": [vue_requete(r, avec_lignes=False) for r in reversed(doc.get("requetes", [])[-30:])]}

    async def _detail_impl(requete_id: str):
        """État et résultat d'une requête (avec le nom de la machine qui l'a exécutée)."""
        doc = await _lire()
        await _vieillir_tout(doc)
        r = next((x for x in doc.get("requetes", []) if x.get("id") == requete_id), None)
        if not r:
            raise HTTPException(status_code=404, detail="Requête introuvable (l'historique garde les 100 dernières).")
        vue = vue_requete(r)
        # Lot 444 : une requête « éphémère » (lecture d'un écran) rend ses lignes UNE fois puis les efface : le document ne grossit pas
        if r.get("ephemere") and r.get("etat") in ("terminee", "echec") and r.get("lignes"):
            await db.loois_reglages.update_one({"id": ID_DOC, "requetes.id": requete_id}, {"$set": {"requetes.$.lignes": []}})
        return vue

    INTERNE.update(creer=_creer_impl, detail=_detail_impl, clients=_clients_impl)      # lot 458 : utilisés par `commande_hfsql_wa`

    # ----------------------------------------------------------------- routes avec la clé « SQL à distance » (Loois sous Windows)
    @api.get("/loois-sql/clients", tags=["Loois SQL à distance"])
    async def clients(request: Request):
        _proprietaire(request)
        return await _clients_impl()

    @api.post("/loois-sql/requetes", tags=["Loois SQL à distance"], status_code=201)
    async def creer(request: Request):
        _proprietaire(request)
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        return await _creer_impl(corps, _ip(request))

    @api.get("/loois-sql/requetes", tags=["Loois SQL à distance"])
    async def historique(request: Request):
        _proprietaire(request)
        return await _historique_impl()

    @api.get("/loois-sql/requetes/{requete_id}", tags=["Loois SQL à distance"])
    async def detail(requete_id: str, request: Request):
        _proprietaire(request)
        return await _detail_impl(requete_id)

    @api.get("/loois-sql/machines-interdites", tags=["Loois SQL à distance"])
    async def interdites_lire(request: Request):
        """Lot 447 : machines interdites de chaque client (clé « SQL à distance » : Loois sous Windows)."""
        _proprietaire(request)
        return {"clients": await _interdites_doc()}

    @api.put("/loois-sql/machines-interdites/{client}", tags=["Loois SQL à distance"])
    async def interdites_definir(client: str, request: Request):
        _proprietaire(request)
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        return await _interdites_definir(client, (corps or {}).get("machines"), "Loois")

    @api.get("/loois-sql/machines-favorites", tags=["Loois SQL à distance"])
    async def favorites_lire(request: Request):
        """Lot 449 : machines favorites de chaque client (clé « SQL à distance » : Loois sous Windows)."""
        _proprietaire(request)
        return {"clients": await _favorites_doc()}

    @api.put("/loois-sql/machines-favorites/{client}", tags=["Loois SQL à distance"])
    async def favorites_definir(client: str, request: Request):
        _proprietaire(request)
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        return await _favorites_definir(client, (corps or {}).get("machines"), "Loois")

    # ----------------------------------------------------------------- lot 446 : page d'administration SAWALI (navigateur, téléphone, application Android)
    # Le compte administrateur SAWALI (connexion avec code à usage unique) remplace la clé « SQL à distance » : AUCUNE clé n'est gardée sur le téléphone.
    # Toute MODIFICATION (INSERT / UPDATE / DELETE) exige en plus une confirmation renforcée explicite (« confirme_modification »).
    # Déjà exigés par SAWALI à la connexion : compte actif, session contrôlée (limite d'appareils, inactivité).
    if get_current_user is not None:      # (absent seulement dans certains tests : les routes de la page d'administration exigent un compte)
        def _admin(user: dict) -> str:
            if (user or {}).get("role") != "admin":
                raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
            return str(user.get("email") or user.get("id") or "admin")[:120]

        @api.get("/admin/loois-sql/clients", tags=["Loois SQL à distance"])
        async def admin_clients(user: dict = Depends(get_current_user)):
            _admin(user)
            return await _clients_impl()

        @api.post("/admin/loois-sql/requetes", tags=["Loois SQL à distance"], status_code=201)
        async def admin_creer(request: Request, user: dict = Depends(get_current_user)):
            auteur = _admin(user)
            try:
                corps = await request.json()
            except Exception:  # noqa: BLE001
                raise HTTPException(status_code=422, detail="corps JSON attendu")
            _, nature, _ = verifier(str((corps or {}).get("sql") or ""))
            if nature == "MODIF" and (corps or {}).get("confirme_modification") is not True:
                raise HTTPException(status_code=422, detail="Confirmation renforcée requise : une modification de données doit être confirmée explicitement.")
            logger.info("[loois-sql] page admin : dépôt par un administrateur (%s)", nature or "refusé")
            return await _creer_impl(corps, _ip(request), auteur)

        @api.get("/admin/loois-sql/machines-interdites", tags=["Loois SQL à distance"])
        async def admin_interdites_lire(user: dict = Depends(get_current_user)):
            _admin(user)
            return {"clients": await _interdites_doc()}

        @api.put("/admin/loois-sql/machines-interdites/{client}", tags=["Loois SQL à distance"])
        async def admin_interdites_definir(client: str, request: Request, user: dict = Depends(get_current_user)):
            auteur = _admin(user)
            try:
                corps = await request.json()
            except Exception:  # noqa: BLE001
                raise HTTPException(status_code=422, detail="corps JSON attendu")
            return await _interdites_definir(client, (corps or {}).get("machines"), auteur)

        @api.get("/admin/loois-sql/machines-favorites", tags=["Loois SQL à distance"])
        async def admin_favorites_lire(user: dict = Depends(get_current_user)):
            _admin(user)
            return {"clients": await _favorites_doc()}

        @api.put("/admin/loois-sql/machines-favorites/{client}", tags=["Loois SQL à distance"])
        async def admin_favorites_definir(client: str, request: Request, user: dict = Depends(get_current_user)):
            auteur = _admin(user)
            try:
                corps = await request.json()
            except Exception:  # noqa: BLE001
                raise HTTPException(status_code=422, detail="corps JSON attendu")
            return await _favorites_definir(client, (corps or {}).get("machines"), auteur)

        @api.get("/admin/loois-sql/requetes", tags=["Loois SQL à distance"])
        async def admin_historique(user: dict = Depends(get_current_user)):
            _admin(user)
            return await _historique_impl()

        @api.get("/admin/loois-sql/requetes/{requete_id}", tags=["Loois SQL à distance"])
        async def admin_detail(requete_id: str, user: dict = Depends(get_current_user)):
            _admin(user)
            return await _detail_impl(requete_id)

    @api.post("/loois-sql/session", tags=["Loois SQL à distance"])
    async def session(request: Request):
        """Lot 444 : Loois signale qu'une session « client distant » est ouverte pour ce client ; les services de ce client passent alors à une
        interrogation rapide (1 seconde au lieu de 5) pendant SESSION_VALIDE_S secondes après le dernier signal."""
        _proprietaire(request)
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        client = code_client((corps or {}).get("client"))
        if not client:
            raise HTTPException(status_code=422, detail="Client invalide")
        sessions[client] = time.monotonic()
        return {"ok": True, "valide_secondes": SESSION_VALIDE_S}

    def _rapide(client: str) -> bool:
        return time.monotonic() - sessions.get(client, -10 ** 9) < SESSION_VALIDE_S

    # ----------------------------------------------------------------- service Windows d'une machine
    @api.get("/loois-sql/poste/prochaine", tags=["Loois SQL à distance"])
    async def prochaine(request: Request):
        """Une machine réclame une requête pour son client : la première qui la réclame la reçoit (mise à jour conditionnelle atomique)."""
        poste = await _poste(request)
        # Lot 447 : une machine INTERDITE pour ce client ne reçoit jamais de requête (elle voit « rien à faire ») ; la requête reste pour les autres machines
        interdites_client = (await _interdites_doc()).get(poste["base"], [])
        if machine_interdite(poste["machine"], interdites_client):
            return Response(status_code=204)
        scrutations[poste["base"]][poste["machine"]] = time.monotonic()      # lot 448.2 : cette machine répond en ce moment (jamais écrit en base)
        doc = await _lire()
        await _vieillir_tout(doc)
        for r in doc.get("requetes", []):
            if r.get("etat") != "attente" or r.get("client") != poste["base"]:
                continue
            # Lot 449 : une machine FAVORITE en ligne a la priorité pendant DELAI_FAVORITE_S ; passé ce délai (ou sans favorite en ligne), la machine qui réclame la prend
            favorites_client = (await _favorites_doc()).get(poste["base"], [])
            if favorites_client:
                cree = _date(r.get("cree_le"))
                age = (_maintenant() - cree).total_seconds() if cree else DELAI_FAVORITE_S
                if doit_attendre(poste["machine"], favorites_client, interdites_client, scrutations[poste["base"]], time.monotonic(), age):
                    continue
            # Contrôle refait au moment de la remise (défense en profondeur) : une requête douteuse n'est jamais donnée
            ok, _, raison = verifier(r.get("sql"))
            if not ok:
                await db.loois_reglages.update_one({"id": ID_DOC, "requetes": {"$elemMatch": {"id": r["id"], "etat": "attente"}}},
                                                   {"$set": {"requetes.$.etat": "refusee", "requetes.$.message": raison, "requetes.$.fin_le": _maintenant().isoformat()}})
                continue
            res = await db.loois_reglages.update_one(
                {"id": ID_DOC, "requetes": {"$elemMatch": {"id": r["id"], "etat": "attente"}}},
                {"$set": {"requetes.$.etat": "prise", "requetes.$.machine": poste["machine"], "requetes.$.prise_le": _maintenant().isoformat(),
                          "requetes.$.cle_id": poste["identite"].get("id")}})
            if res.modified_count == 1:                      # une seule machine gagne ; les autres passent à la suivante
                logger.info("[loois-sql] requête %s prise par la machine %s (client %s)", r["id"], poste["machine"], poste["base"])
                # Lot 449.1 : la réponse « 200 » porte AUSSI l'en-tête X-Sql-Rapide (session ouverte) : sans lui, le service Windows retombait à 5 s d'attente
                # après CHAQUE requête exécutée (≈ 6 s par requête mesurées chez IPM le 18/11/2026) au lieu de 1 s.
                return JSONResponse({"id": r["id"], "sql": r["sql"]}, headers={"X-Sql-Rapide": "1"} if _rapide(poste["base"]) else {})
        # Lot 444 : rien à faire ; si une session Loois est ouverte pour ce client, on dit au service d'interroger toutes les secondes
        return Response(status_code=204, headers={"X-Sql-Rapide": "1"} if _rapide(poste["base"]) else {})

    @api.post("/loois-sql/poste/resultat", tags=["Loois SQL à distance"])
    async def resultat(request: Request):
        """La machine qui a pris la requête renvoie le résultat ; une autre machine, ou une requête déjà terminée, est refusée."""
        poste = await _poste(request)
        # Lot 447 : machine interdite après avoir pris la requête : son résultat est refusé (la requête finit « sans réponse », jamais rejouée)
        if machine_interdite(poste["machine"], (await _interdites_doc()).get(poste["base"], [])):
            raise HTTPException(status_code=403, detail="Machine interdite pour ce client.")
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        rid = str((corps or {}).get("id") or "")
        champs = resultat_borne(corps or {})
        # Lot 445 : adresse IP vue par SAWALI pour la machine qui répond (journal du client distant de Loois)
        maj = {"etat": "terminee" if champs["ok"] else "echec", "fin_le": _maintenant().isoformat(), "machine_ip": _ip(request), **champs}
        res = await db.loois_reglages.update_one(
            {"id": ID_DOC, "requetes": {"$elemMatch": {"id": rid, "etat": "prise", "machine": poste["machine"], "client": poste["base"]}}},
            {"$set": {f"requetes.$.{k}": v for k, v in maj.items()}})
        if res.modified_count != 1:
            raise HTTPException(status_code=409, detail="Requête inconnue, déjà terminée ou prise par une autre machine.")
        logger.info("[loois-sql] requête %s terminée par la machine %s (%s)", rid, poste["machine"], maj["etat"])
        return {"ok": True}
