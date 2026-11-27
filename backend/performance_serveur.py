# performance_serveur.py — Lot 463 : MÉMOIRE du serveur et APPELS LES PLUS LENTS (règle 7 « mesurer d'abord »).
#
# Pourquoi : le 26/11/2026, le serveur SAWALI (offre Render à 512 Mo) utilisait 430 à 490 Mo, soit 84 à 92 % de sa limite, et le site était
# devenu lent. Rien dans SAWALI ne permettait de le voir ni de savoir QUELLE route est lente (les statistiques de latence de Render sont vides).
#
# Ce module :
#   1. LIT la mémoire réellement utilisée : celle du conteneur Render (cgroup, « mémoire de travail » = ce que Render compte) et celle du processus ;
#      la limite vient, dans l'ordre : du réglage `perf_memoire_limite_mo`, de la limite du conteneur, de 512 Mo ;
#   2. MESURE chaque appel de l'API (méthode, route, durée, code) dans un intergiciel ASGI (`MesureAppels`) : moyenne, 5 derniers, dernier, maximum,
#      nombre d'appels de plus d'1 seconde et d'erreurs 5xx, par ROUTE (« /api/clients/{id} », pas par adresse) ;
#   3. SURVEILLE toutes les heures : garde un échantillon de mémoire (72 au plus, soit 3 jours) et le relevé des appels les plus lents ; au-delà du seuil
#      (85 % par défaut) UN message WhatsApp par jour au super-admin (même canal que l'alerte des collections Atlas).
# Stockage : une fiche de `settings` (`performance_serveur`), aucune nouvelle collection (cluster plein). Les compteurs d'appels restent EN MÉMOIRE
# (aucune écriture par requête) : ils repartent de zéro à chaque redémarrage ; le relevé horaire conserve le dernier classement.
from __future__ import annotations

import asyncio
import contextvars
import inspect
import logging
import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("sawali.performance")

DOC_ID = "performance_serveur"
LIMITE_DEFAUT_MO = 512
SEUIL_DEFAUT_PCT = 85
MAX_HISTORIQUE = 72                # échantillons horaires gardés (3 jours)
MAX_ROUTES = 400                   # routes suivies au plus (au-delà : regroupées dans « autres »)
SEUIL_LENT_MS = 1000               # objectif de la règle 7 : toute route d'affichage répond en moins d'1 s
MO = 1024 * 1024
PART_ORANGE = 0.70                 # vert sous 70 % ; orange dès 70 % ; rouge dès 90 % (il reste 10 % ou moins)
PART_ROUGE = 0.90


# ----------------------------------------------------------------------------------------------------------------------- mémoire
def _lire(chemin: str) -> Optional[str]:
    """Contenu d'un fichier du système, ou None s'il n'existe pas (poste de développement, autre système)."""
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _entier(texte: Optional[str]) -> Optional[int]:
    try:
        return int(str(texte).strip())
    except (TypeError, ValueError):
        return None


def _stat(texte: Optional[str], cle: str) -> int:
    """Valeur d'une ligne « cle 1234 » d'un fichier memory.stat (0 si absente)."""
    for ligne in (texte or "").splitlines():
        morceaux = ligne.split()
        if len(morceaux) == 2 and morceaux[0] == cle:
            return _entier(morceaux[1]) or 0
    return 0


def lire_memoire(statut_processus: str = "/proc/self/status", cgroup: str = "/sys/fs/cgroup") -> Dict[str, Any]:
    """Mémoire en octets : {processus, conteneur, limite_conteneur}. Chaque valeur est None si elle ne peut pas être lue.
    Conteneur = « mémoire de travail » (utilisée moins le cache de fichiers récupérable), comme la compte Render ; cgroup v2 puis v1."""
    processus = None
    for ligne in (_lire(statut_processus) or "").splitlines():
        if ligne.startswith("VmRSS:"):
            processus = (_entier(ligne.split()[1]) or 0) * 1024            # VmRSS est en Ko
            break
    conteneur = limite = None
    courant = _entier(_lire(f"{cgroup}/memory.current"))                  # cgroup v2
    if courant is not None:
        conteneur = max(0, courant - _stat(_lire(f"{cgroup}/memory.stat"), "inactive_file"))
        maximum = _lire(f"{cgroup}/memory.max")
        limite = _entier(maximum) if maximum and maximum.strip() != "max" else None
    else:                                                                    # cgroup v1
        courant = _entier(_lire(f"{cgroup}/memory/memory.usage_in_bytes"))
        if courant is not None:
            conteneur = max(0, courant - _stat(_lire(f"{cgroup}/memory/memory.stat"), "total_inactive_file"))
            limite = _entier(_lire(f"{cgroup}/memory/memory.limit_in_bytes"))
    if limite is not None and limite > 64 * 1024 * MO:                      # « pas de limite » : valeur énorme
        limite = None
    return {"processus": processus, "conteneur": conteneur, "limite_conteneur": limite}


def reglages_memoire(s: Dict[str, Any]) -> Dict[str, Any]:
    """Limite (Mo) réglée par l'administrateur (None = automatique) et seuil d'alerte en % (1 à 100, 85 par défaut)."""
    def _nombre(v: Any) -> Optional[float]:
        try:
            n = float(v)
            return n if n > 0 else None
        except (TypeError, ValueError):
            return None
    seuil = _nombre((s or {}).get("perf_memoire_seuil_pct")) or SEUIL_DEFAUT_PCT
    return {"limite_mo": _nombre((s or {}).get("perf_memoire_limite_mo")), "seuil_pct": min(100.0, seuil)}


def niveau(pourcentage: float) -> str:
    """ok (vert) sous 70 % ; attention (orange) dès 70 % ; plein (rouge) dès 90 %."""
    part = pourcentage / 100
    return "plein" if part >= PART_ROUGE else ("attention" if part >= PART_ORANGE else "ok")


def calculer_mesure(brut: Dict[str, Any], reglages: Dict[str, Any], instant: Optional[datetime] = None) -> Dict[str, Any]:
    """Fonction PURE : transforme les octets lus en mesure affichable (Mo, %, niveau, seuil, mémoire restante, origine de la limite)."""
    utilise = brut.get("conteneur") if brut.get("conteneur") is not None else brut.get("processus")
    if reglages.get("limite_mo"):
        limite, origine = reglages["limite_mo"] * MO, "réglage"
    elif brut.get("limite_conteneur"):
        limite, origine = brut["limite_conteneur"], "conteneur"
    else:
        limite, origine = LIMITE_DEFAUT_MO * MO, "défaut"
    if utilise is None:
        return {"lisible": False, "le": (instant or datetime.now(timezone.utc)).isoformat()}
    pct = round(utilise * 100 / limite, 1) if limite else 0.0
    seuil_pct = reglages.get("seuil_pct") or SEUIL_DEFAUT_PCT
    return {"lisible": True, "le": (instant or datetime.now(timezone.utc)).isoformat(),
            "utilise_mo": round(utilise / MO, 1), "limite_mo": round(limite / MO, 1), "restant_mo": round(max(0, limite - utilise) / MO, 1),
            "processus_mo": round(brut["processus"] / MO, 1) if brut.get("processus") is not None else None,
            "pourcentage": pct, "niveau": niveau(pct), "seuil_pct": seuil_pct, "seuil_mo": round(limite * seuil_pct / 100 / MO, 1),
            "alerte": pct >= seuil_pct, "origine_limite": origine}


# ------------------------------------------------------------------------------------------------------------- appels les plus lents
RE_IDENTIFIANT = re.compile(r"^(?:\d+|[0-9a-fA-F]{8,}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$")


def normaliser_chemin(chemin: str) -> str:
    """Chemin sans identifiant : « /api/clients/5f3a9c2e7b/documents » -> « /api/clients/{id}/documents » (repli quand la route n'est pas connue)."""
    morceaux = [("{id}" if RE_IDENTIFIANT.match(m) else m) for m in str(chemin or "/").split("?")[0].split("/")]
    return "/".join(morceaux)[:200] or "/"


# ----------------------------------------------------------------------------------------------------------------------- requêtes à la base
# Lot 472 : combien de requêtes à MongoDB chaque appel fait-il, et combien de temps y passe-t-il ? Constat du 27/11/2026 : Atlas (Paris) et le serveur (Francfort)
# sont à ~10 ms l'un de l'autre ; ces 10 ms se paient À CHAQUE requête : une route qui en fait 30 l'une après l'autre perd 300 ms, une route qui en fait 3 reste à 40 ms.
# Pour savoir lesquelles corriger sans deviner, chaque requête à la base est comptée et chronométrée, PAR APPEL, grâce à un crochet posé sur la fonction par
# laquelle Motor (le pilote MongoDB asynchrone) envoie TOUTE opération au fil de travail. Le compteur est celui de l'appel EN COURS (variable de contexte) :
# les requêtes lancées en parallèle (asyncio.gather) sont toutes comptées ; le temps est CUMULÉ (il peut dépasser la durée de l'appel quand elles se chevauchent).
COMPTEUR_BASE: "contextvars.ContextVar[Optional[CompteurBase]]" = contextvars.ContextVar("compteur_base", default=None)


class CompteurBase:
    """Durées (ms) des requêtes à la base faites pendant UN appel. `append` d'une liste est atomique : les fils de travail n'ont pas besoin de verrou."""

    __slots__ = ("durees",)

    def __init__(self) -> None:
        self.durees: List[float] = []

    @property
    def ops(self) -> int:
        return len(self.durees)

    @property
    def ms(self) -> float:
        return float(sum(self.durees))


_CROCHET_POSE = False


def installer_mesure_base() -> bool:
    """Pose le crochet de comptage sur `motor.frameworks.asyncio.run_on_executor`. Prudent : si Motor n'a pas la forme attendue, RIEN n'est modifié et le serveur
    fonctionne comme avant (renvoie False). Idempotent. Aucun surcoût hors appel (compteur absent = appel direct à la fonction d'origine)."""
    global _CROCHET_POSE
    if _CROCHET_POSE:
        return True
    try:
        import motor.frameworks.asyncio as cadre
        origine = cadre.run_on_executor
        if getattr(origine, "_mesure_base", False):
            _CROCHET_POSE = True
            return True
        if list(inspect.signature(origine).parameters)[:2] != ["loop", "fn"]:
            logger.warning("[performance] Motor : forme inattendue, comptage des requêtes à la base désactivé")
            return False

        def run_on_executor(loop, fn, *args, **kwargs):
            compteur = COMPTEUR_BASE.get()                                   # compteur de l'appel en cours (lu dans le fil de la boucle d'événements)
            if compteur is None:
                return origine(loop, fn, *args, **kwargs)

            def chronometree(*a, **k):                                       # exécutée dans le fil de travail : durée de la requête, réseau compris
                debut = time.perf_counter()
                try:
                    return fn(*a, **k)
                finally:
                    compteur.durees.append((time.perf_counter() - debut) * 1000)
            return origine(loop, chronometree, *args, **kwargs)

        run_on_executor._mesure_base = True                                  # type: ignore[attr-defined]
        cadre.run_on_executor = run_on_executor
        _CROCHET_POSE = True
        return True
    except Exception:  # noqa: BLE001 — la mesure ne doit JAMAIS empêcher le serveur de démarrer
        logger.warning("[performance] comptage des requêtes à la base non installé", exc_info=True)
        return False


class SuiviAppels:
    """Compteurs EN MÉMOIRE par route (aucune écriture en base par requête) : appels, durée moyenne, 5 derniers, dernier, maximum, lents, erreurs."""

    def __init__(self, max_routes: int = MAX_ROUTES) -> None:
        self.max_routes = max_routes
        self.routes: Dict[str, Dict[str, Any]] = {}
        self.depuis = datetime.now(timezone.utc).isoformat()

    def enregistrer(self, methode: str, route: str, duree_ms: float, statut: int, ops: int = 0, base_ms: float = 0.0) -> None:
        cle = f"{methode} {route}"
        fiche = self.routes.get(cle)
        if fiche is None:
            if len(self.routes) >= self.max_routes:                              # trop de routes différentes : le reste est regroupé
                cle = f"{methode} autres"
                fiche = self.routes.get(cle)
            if fiche is None:
                fiche = {"methode": methode, "route": route if cle != f"{methode} autres" else "autres", "n": 0, "total": 0.0, "max": 0.0,
                         "dernier": 0.0, "derniers": deque(maxlen=5), "lents": 0, "erreurs": 0,
                         "ops": 0, "ops_max": 0, "base_ms": 0.0}
                self.routes[cle] = fiche
        fiche["n"] += 1
        fiche["total"] += duree_ms
        fiche["max"] = max(fiche["max"], duree_ms)
        fiche["dernier"] = duree_ms
        fiche["derniers"].append(round(duree_ms))
        fiche["lents"] += 1 if duree_ms >= SEUIL_LENT_MS else 0
        fiche["erreurs"] += 1 if statut >= 500 else 0
        fiche["ops"] += ops                                                     # requêtes à la base (lot 472)
        fiche["ops_max"] = max(fiche["ops_max"], ops)
        fiche["base_ms"] += base_ms

    def classement(self, limite: int = 40, minimum: int = 1) -> List[Dict[str, Any]]:
        """Routes triées par durée MOYENNE décroissante (celles qui ont au moins `minimum` appels)."""
        lignes = [{"methode": f["methode"], "route": f["route"], "appels": f["n"], "moyenne_ms": round(f["total"] / f["n"]), "dernier_ms": round(f["dernier"]),
                   "derniers_ms": list(f["derniers"]), "maximum_ms": round(f["max"]), "lents": f["lents"], "erreurs": f["erreurs"],
                   "ops_moy": round(f["ops"] / f["n"], 1), "ops_max": f["ops_max"], "base_ms_moy": round(f["base_ms"] / f["n"])}
                  for f in self.routes.values() if f["n"] >= minimum]
        lignes.sort(key=lambda x: (-x["moyenne_ms"], -x["appels"]))
        return lignes[:limite]

    def resume(self) -> Dict[str, Any]:
        total = sum(f["n"] for f in self.routes.values())
        return {"depuis": self.depuis, "routes": len(self.routes), "appels": total, "lents": sum(f["lents"] for f in self.routes.values()),
                "erreurs": sum(f["erreurs"] for f in self.routes.values())}

    def reinitialiser(self) -> None:
        self.routes.clear()
        self.depuis = datetime.now(timezone.utc).isoformat()


SUIVI = SuiviAppels()                      # un seul suivi par serveur


# ----------------------------------------------------------------------------------------------------------------------- réactivité du serveur
# Lot 474 : le serveur répond à toutes les requêtes avec UNE seule boucle d'événements. Si un calcul ou une lecture la bloque ne serait-ce que 2 secondes, TOUTES les routes
# prennent 2 secondes de plus en même temps (constat du 27/11/2026 : sept routes de l'écran des carrousels à ~2,4 s chacune alors qu'elles font 1 à 12 requêtes rapides).
# Un petit relevé mesure donc, toutes les 0,5 s, de combien la boucle est EN RETARD sur l'heure prévue : près de zéro = tout va bien ; plusieurs centaines de ms = quelque chose la bloque.
class RetardBoucle:
    """Retard de la boucle d'événements depuis le dernier démarrage ou la dernière remise à zéro (en mémoire, aucune écriture)."""

    def __init__(self) -> None:
        self.reinitialiser()

    def reinitialiser(self) -> None:
        self.n = 0
        self.total = 0.0
        self.max = 0.0
        self.blocages = 0                                   # relevés où le retard a dépassé 100 ms
        self.depuis = datetime.now(timezone.utc).isoformat()

    def noter(self, retard_ms: float) -> None:
        self.n += 1
        self.total += retard_ms
        self.max = max(self.max, retard_ms)
        self.blocages += 1 if retard_ms >= 100 else 0

    def resume(self) -> Dict[str, Any]:
        return {"depuis": self.depuis, "mesures": self.n, "retard_moy_ms": round(self.total / self.n, 1) if self.n else None,
                "retard_max_ms": round(self.max), "blocages_100ms": self.blocages}


RETARD = RetardBoucle()
_SURVEILLANCE_BOUCLE = {"tache": None}


async def _surveiller_boucle(retard: RetardBoucle, pas_s: float = 0.5) -> None:
    """Dort `pas_s` secondes et note de combien le réveil est en retard : ce retard est le temps pendant lequel la boucle était occupée à autre chose."""
    while True:
        debut = time.perf_counter()
        await asyncio.sleep(pas_s)
        retard.noter(max(0.0, (time.perf_counter() - debut - pas_s) * 1000))


def demarrer_surveillance_boucle(pas_s: float = 0.5) -> bool:
    """Lance le relevé dans la boucle en cours (une seule fois). À appeler depuis le démarrage du serveur."""
    if _SURVEILLANCE_BOUCLE["tache"] is not None and not _SURVEILLANCE_BOUCLE["tache"].done():
        return False
    _SURVEILLANCE_BOUCLE["tache"] = asyncio.get_running_loop().create_task(_surveiller_boucle(RETARD, pas_s))
    return True
IGNORES = ("/api/health",)                 # sondes de Render (toutes les quelques secondes) : sans intérêt


class MesureAppels:
    """Intergiciel ASGI PUR (pas de BaseHTTPMiddleware : aucun surcoût ni retard sur les flux) : note la durée de chaque appel /api/* jusqu'à la fin
    de la réponse. Ignorés : WebSocket, pré-requêtes OPTIONS, sondes /api/health, flux en continu (text/event-stream : longs par nature)."""

    def __init__(self, app, suivi: Optional[SuiviAppels] = None) -> None:
        self.app = app
        self.suivi = suivi or SUIVI

    async def __call__(self, scope, receive, send):
        chemin = scope.get("path") or ""
        if scope.get("type") != "http" or scope.get("method") == "OPTIONS" or not chemin.startswith("/api/") or chemin in IGNORES:
            await self.app(scope, receive, send)
            return
        debut = time.perf_counter()
        etat = {"statut": 0, "flux": False}
        compteur = CompteurBase()
        jeton = COMPTEUR_BASE.set(compteur)                                   # les requêtes à la base de CET appel s'y comptent (lot 472)

        async def envoyer(message):
            if message["type"] == "http.response.start":
                etat["statut"] = int(message.get("status") or 0)
                for nom, valeur in message.get("headers") or []:
                    if nom.lower() == b"content-type" and b"text/event-stream" in valeur.lower():
                        etat["flux"] = True
            await send(message)

        try:
            await self.app(scope, receive, envoyer)
        finally:
            try:
                COMPTEUR_BASE.reset(jeton)
            except ValueError:                                                 # contexte différent : sans importance, la variable disparaît avec l'appel
                pass
            try:
                if not etat["flux"]:
                    route = getattr(scope.get("route"), "path", None) or normaliser_chemin(chemin)   # route déclarée (« /api/x/{id} »), sinon chemin nettoyé
                    self.suivi.enregistrer(scope.get("method") or "GET", route, (time.perf_counter() - debut) * 1000, etat["statut"] or 500,
                                          compteur.ops, compteur.ms)
            except Exception:  # noqa: BLE001 — la mesure ne doit JAMAIS casser un appel
                logger.debug("[performance] appel non mesuré", exc_info=True)


# ------------------------------------------------------------------------------------------------------------------- suivi en base
async def _fiche(db) -> Dict[str, Any]:
    f = await db["settings"].find_one({"_id": DOC_ID}) or {}
    f.setdefault("historique", [])
    return f


async def mesurer(db, instant: Optional[datetime] = None, lecteur=None) -> Dict[str, Any]:
    """Mesure maintenant (lecture locale, instantanée) + les échantillons gardés. `lecteur` est injectable pour les tests."""
    g = await db["settings"].find_one({"_id": "global"}, {"_id": 0, "perf_memoire_limite_mo": 1, "perf_memoire_seuil_pct": 1}) or {}
    mesure = calculer_mesure((lecteur or lire_memoire)(), reglages_memoire(g), instant)
    mesure["historique"] = [{"le": h.get("le"), "utilise_mo": h.get("utilise_mo")} for h in (await _fiche(db))["historique"]][-MAX_HISTORIQUE:]
    return mesure


def texte_alerte(m: Dict[str, Any]) -> str:
    return (f"⚠️ Mémoire du serveur SAWALI : {m['utilise_mo']} Mo sur {m['limite_mo']} Mo ({m['pourcentage']} %, seuil {m['seuil_pct']} %). "
            "Près de la limite, le serveur ralentit puis redémarre : passez à une offre Render plus grande ou cherchez ce qui consomme "
            "(Paramètres → Performance du serveur).")


async def surveiller(db, maintenant: Optional[datetime] = None, lecteur=None, envoyer_alerte=None) -> Dict[str, Any]:
    """Tâche HORAIRE : garde un échantillon de mémoire et le classement des appels les plus lents ; au-delà du seuil, WhatsApp UNE fois par jour."""
    maintenant = maintenant or datetime.now(timezone.utc)
    m = await mesurer(db, maintenant, lecteur)
    if not m.get("lisible"):
        return {"mesure": m, "alerte": False}
    f = await _fiche(db)
    f["historique"] = (f["historique"] + [{"le": m["le"], "utilise_mo": m["utilise_mo"]}])[-MAX_HISTORIQUE:]
    maj = {"historique": f["historique"], "releve_appels": {"le": m["le"], **SUIVI.resume(), "classement": SUIVI.classement(30)}}
    envoye = False
    jour = maintenant.date().isoformat()
    if m["alerte"] and f.get("alerte_jour") != jour:
        if envoyer_alerte is None:
            from routes.quota_atlas import _envoyer_alerte
            async def envoyer_alerte(texte):                                  # noqa: E306 — même canal que l'alerte des collections Atlas
                return await _envoyer_alerte(db, texte, maintenant, titre="Liluvine — serveur SAWALI")
        logger.warning("[performance] mémoire %s Mo / %s Mo (%s %%)", m["utilise_mo"], m["limite_mo"], m["pourcentage"])
        envoye = bool(await envoyer_alerte(texte_alerte(m)))
        maj.update({"alerte_jour": jour, "alerte_envoyee": envoye})
    await db["settings"].update_one({"_id": DOC_ID}, {"$set": maj}, upsert=True)
    return {"mesure": m, "alerte": envoye}


async def appels(db, limite: int = 40) -> Dict[str, Any]:
    """Classement EN DIRECT ; juste après un redémarrage (rien de mesuré), le dernier relevé horaire gardé avant l'arrêt est rendu, clairement signalé."""
    direct = SUIVI.classement(limite)
    if direct:
        return {"source": "direct", **SUIVI.resume(), "classement": direct, "objectif_ms": SEUIL_LENT_MS, "boucle": RETARD.resume()}
    releve = (await _fiche(db)).get("releve_appels") or {}
    if releve:
        return {"source": "releve", "depuis": releve.get("depuis"), "releve_le": releve.get("le"), "routes": releve.get("routes", 0), "appels": releve.get("appels", 0),
                "lents": releve.get("lents", 0), "erreurs": releve.get("erreurs", 0), "classement": (releve.get("classement") or [])[:limite], "objectif_ms": SEUIL_LENT_MS}
    return {"source": "vide", **SUIVI.resume(), "classement": [], "objectif_ms": SEUIL_LENT_MS, "boucle": RETARD.resume()}
