# services_renouveler.py — Lot 170 : services à surveiller et renouveler (MongoDB Atlas, Render, Cloudflare R2, domaines…),
# avec le MONTANT par service, par FORMULE, par PLATEFORME et par CLUSTER à la date de lecture.
#
# Demande du propriétaire (15/10/2026) : « Pour tous ces services à renouveler (MongoDB Atlas, Render, Cloudflare R2, etc.)
# un module dans les paramètres de SAWALI pour afficher le montant par service et formule à la date de lecture […] Il faut
# aussi que ce soit par plateforme et/ou cluster. »
#
# En résumé (pour un développeur WinDev) :
#   - DONNÉES : un seul document db.settings {_id: "services_renouveler"} (AUCUNE nouvelle collection : le cluster est plein) :
#       services          : [{id, nom, fournisseur, formule, montant, devise, periodicite, prochaine_echeance, lien_paiement,
#                             plateformes[], cluster, source, actif, rappels_jours[]}]
#       clusters          : {nom du cluster Atlas: [plateformes]}   (répartition des lignes lues d'Atlas)
#       lectures          : {atlas: {...}, r2: {...}}               (dernières lectures automatiques, avec leur date)
#       rappels_envoyes   : clés « id|échéance|palier » déjà envoyées (jamais deux fois le même rappel)
#   - SOURCE d'un montant : « saisi » (par le propriétaire), « atlas » (facture en cours lue chez MongoDB Atlas, UNE ligne par
#     cluster), « r2 » (ESTIMATION d'après le stockage et les opérations lus chez Cloudflare). Chaque ligne affiche la date de lecture.
#   - PLATEFORMES : une ligne peut servir plusieurs plateformes ; son montant (ramené au mois) est alors réparti À PARTS ÉGALES
#     entre elles dans la vue « par plateforme ». Sans plateforme : « Commun ».
#   - CLÉS (variables d'environnement saisies par le propriétaire sur Render, jamais affichées) :
#       Atlas      : ATLAS_API_PUBLIC_KEY, ATLAS_API_PRIVATE_KEY, ATLAS_ORG_ID  (droit « Organization Billing Viewer »)
#       Cloudflare : CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID                (droit de lecture des analyses)
#   - RAPPELS : une fois par jour, WhatsApp au super-admin (relais de Liluvine) aux paliers 30, 7, 1 et 0 jour avant l'échéance.
# Routes (administrateur) : GET /api/admin/services-renouveler ; PUT idem (liste et clusters) ; POST …/lire ; POST …/{id}/renouveler.
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.services_renouveler")

DOC_ID = "services_renouveler"
MAX_SERVICES = 100
PERIODICITES = {"mensuel": 1, "trimestriel": 3, "semestriel": 6, "annuel": 12, "unique": 0}   # durée en mois (0 = sans reconduction)
SOURCES = ("saisi", "atlas", "r2")
COMMUN = "Commun"                 # ligne qui ne sert à aucune plateforme précise
RAPPELS_DEFAUT = [30, 7, 1, 0]
DUREE_LECTURE_H = 6               # une lecture automatique est gardée 6 heures
# Tarifs publics Cloudflare R2 (stockage standard), modifiables : 10 Go gratuits ; 0,015 $ / Go / mois ; classe A 4,50 $ / million
# au-delà de 1 million ; classe B 0,36 $ / million au-delà de 10 millions.
R2_GO_GRATUITS, R2_PRIX_GO, R2_PRIX_A, R2_PRIX_B = 10.0, 0.015, 4.50, 0.36
R2_GRATUIT_A, R2_GRATUIT_B = 1_000_000, 10_000_000
ACTIONS_CLASSE_B = {"GetObject", "HeadObject", "HeadBucket", "UsageSummary", "GetBucketEncryption", "GetBucketLocation",
                    "GetBucketCors", "GetBucketLifecycleConfiguration"}   # lectures ; toutes les autres actions comptent en classe A


# Conversion en FCFA (lot 175) : taux = nombre de FCFA pour 1 unité de la devise, saisis par l'administrateur.
# L'euro est à parité FIXE avec le FCFA (655,957) ; le dollar varie : la valeur par défaut n'est qu'un ordre de grandeur à actualiser.
DEVISES_FCFA = ("FCFA", "XOF", "XAF")
TAUX_DEFAUT = {"EUR": 655.957, "USD": 600.0}


def normaliser_taux(brut: Any) -> Dict[str, float]:
    """{devise: FCFA pour 1 unité} propre : valeurs positives seulement, complétées par les taux par défaut. Fonction pure."""
    sortie = dict(TAUX_DEFAUT)
    for d, v in (brut.items() if isinstance(brut, dict) else []):
        n = _nombre(v)
        if _texte(d, 6) and n > 0:
            sortie[_texte(d, 6).upper()] = round(n, 4)
    return sortie


def en_fcfa(montant: float, devise: str, taux: Dict[str, float]) -> Optional[float]:
    """Montant converti en FCFA (arrondi à l'unité) ; None si la devise n'a pas de taux. Fonction pure."""
    d = (devise or "").upper()
    if d in DEVISES_FCFA:
        return round(float(montant or 0))
    return round(float(montant or 0) * taux[d]) if d in taux else None


def _maintenant() -> datetime:
    """Horloge (remplaçable en test)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------------------------------------------------
# Normalisation, échéances, montants ramenés au mois
# ---------------------------------------------------------------------------------------------------------------------
def _texte(v: Any, n: int) -> str:
    return str(v or "").strip()[:n]


def _date(v: Any) -> Optional[str]:
    """« AAAA-MM-JJ » valide, sinon None."""
    try:
        return date.fromisoformat(str(v or "").strip()[:10]).isoformat()
    except ValueError:
        return None


def _nombre(v: Any) -> float:
    try:
        n = float(str(v).replace(",", ".").replace(" ", ""))
        return n if n >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def normaliser_services(brut: Any) -> List[Dict[str, Any]]:
    """Liste propre : nom obligatoire, textes bornés, périodicité et source connues, au plus MAX_SERVICES lignes."""
    sortie: List[Dict[str, Any]] = []
    vus = set()
    for s in (brut if isinstance(brut, list) else []):
        if not isinstance(s, dict) or not _texte(s.get("nom"), 120):
            continue
        ident = _texte(s.get("id"), 40)
        if not ident or ident in vus:
            ident = uuid.uuid4().hex[:12]
        vus.add(ident)
        periodicite = _texte(s.get("periodicite"), 20).lower()
        source = _texte(s.get("source"), 10).lower()
        plateformes = []
        for p in (s.get("plateformes") if isinstance(s.get("plateformes"), list) else []):
            p = _texte(p, 40)
            if p and p not in plateformes:
                plateformes.append(p)
        rappels = sorted({int(x) for x in (s.get("rappels_jours") if isinstance(s.get("rappels_jours"), list) else RAPPELS_DEFAUT)
                          if str(x).lstrip("-").isdigit() and 0 <= int(x) <= 365}, reverse=True)
        sortie.append({
            "id": ident, "nom": _texte(s.get("nom"), 120), "fournisseur": _texte(s.get("fournisseur"), 60),
            "formule": _texte(s.get("formule"), 80), "montant": round(_nombre(s.get("montant")), 2),
            "devise": (_texte(s.get("devise"), 6) or "USD").upper(),
            "periodicite": periodicite if periodicite in PERIODICITES else "mensuel",
            "prochaine_echeance": _date(s.get("prochaine_echeance")), "lien_paiement": _texte(s.get("lien_paiement"), 300),
            "plateformes": plateformes[:20], "cluster": _texte(s.get("cluster"), 60),
            "source": source if source in SOURCES else "saisi", "actif": s.get("actif") is not False,
            "rappels_jours": rappels or RAPPELS_DEFAUT,
        })
        if len(sortie) >= MAX_SERVICES:
            break
    return sortie


def normaliser_clusters(brut: Any) -> Dict[str, List[str]]:
    """{nom du cluster: [plateformes]} propre (noms bornés, sans doublon)."""
    sortie: Dict[str, List[str]] = {}
    for nom, plateformes in (brut.items() if isinstance(brut, dict) else []):
        nom = _texte(nom, 60)
        if nom:
            sortie[nom] = list(dict.fromkeys(_texte(p, 40) for p in (plateformes if isinstance(plateformes, list) else []) if _texte(p, 40)))[:20]
    return sortie


def mensualise(montant: float, periodicite: str) -> float:
    """Montant ramené au mois : annuel ÷ 12, trimestriel ÷ 3… ; « unique » (sans reconduction) ne compte pas dans le mensuel."""
    mois = PERIODICITES.get(periodicite, 1)
    return round(montant / mois, 2) if mois else 0.0


def jours_restants(echeance: Optional[str], aujourdhui: date) -> Optional[int]:
    return (date.fromisoformat(echeance) - aujourdhui).days if echeance else None


def niveau_echeance(jours: Optional[int]) -> str:
    """Couleur : echu (rouge, dépassée), urgent (orange foncé, ≤ 7 j), bientot (orange, ≤ 30 j), ok (vert), inconnu (pas de date)."""
    if jours is None:
        return "inconnu"
    if jours < 0:
        return "echu"
    return "urgent" if jours <= 7 else "bientot" if jours <= 30 else "ok"


def ajouter_mois(d: date, mois: int) -> date:
    """Même jour du mois, `mois` plus tard (le 31 devient le dernier jour d'un mois plus court)."""
    m = d.month - 1 + mois
    annee, mois_n = d.year + m // 12, m % 12 + 1
    dernier = (date(annee + (mois_n == 12), mois_n % 12 + 1, 1) - timedelta(days=1)).day
    return date(annee, mois_n, min(d.day, dernier))


def echeance_suivante(echeance: Optional[str], periodicite: str, aujourdhui: date) -> Optional[str]:
    """Échéance après un renouvellement : une période de plus (répétée si l'ancienne est loin dans le passé). None si « unique »."""
    mois = PERIODICITES.get(periodicite, 1)
    if not mois:
        return None
    d = date.fromisoformat(echeance) if echeance else aujourdhui
    d = ajouter_mois(d, mois)
    while d <= aujourdhui:
        d = ajouter_mois(d, mois)
    return d.isoformat()


# ---------------------------------------------------------------------------------------------------------------------
# Lignes affichées (les lectures automatiques remplacent le montant saisi) et totaux par plateforme / cluster
# ---------------------------------------------------------------------------------------------------------------------
def lignes_calculees(services: List[Dict[str, Any]], lectures: Dict[str, Any], clusters: Dict[str, List[str]],
                     aujourdhui: date) -> List[Dict[str, Any]]:
    """Lignes du tableau. Source « atlas » : UNE ligne par cluster de la facture lue (plateformes d'après `clusters`) ;
    source « r2 » : le montant ESTIMÉ remplace le montant saisi. Si la lecture manque ou a échoué, le montant saisi reste
    affiché et l'erreur est signalée. Chaque ligne : montant, mensuel (ramené au mois), origine, date de lecture."""
    lignes: List[Dict[str, Any]] = []
    for s in services:
        base = {**s, "origine": "saisi", "lu_le": None, "erreur": None, "estimation": False}
        lecture = (lectures or {}).get(s["source"]) if s["source"] in ("atlas", "r2") else None
        jours = jours_restants(s["prochaine_echeance"], aujourdhui)
        suivi = {"jours": jours, "niveau": niveau_echeance(jours) if s["actif"] else "inactif"}
        if lecture and lecture.get("erreur"):
            lignes.append({**base, **suivi, "erreur": lecture["erreur"], "lu_le": lecture.get("le"), "mensuel": mensualise(s["montant"], s["periodicite"])})
        elif s["source"] == "atlas" and lecture and lecture.get("clusters"):
            for c in lecture["clusters"]:
                montant = round(float(c.get("montant") or 0), 2)
                lignes.append({**base, **suivi, "id": f"{s['id']}:{c['nom']}", "nom": f"{s['nom']} — {c['nom']}", "cluster": c["nom"],
                               "plateformes": clusters.get(c["nom"]) or s["plateformes"], "montant": montant, "devise": lecture.get("devise") or s["devise"],
                               "origine": "atlas", "lu_le": lecture.get("le"), "mensuel": montant,   # facture du mois en cours = coût du mois
                               "detail": c.get("detail")})
        elif s["source"] == "r2" and lecture and lecture.get("montant") is not None:
            montant = round(float(lecture["montant"]), 2)
            lignes.append({**base, **suivi, "montant": montant, "devise": lecture.get("devise") or s["devise"], "origine": "r2",
                           "estimation": True, "lu_le": lecture.get("le"), "mensuel": montant, "detail": lecture.get("detail")})
        else:
            lignes.append({**base, **suivi, "mensuel": mensualise(s["montant"], s["periodicite"])})
    return lignes


def totaux(lignes: List[Dict[str, Any]], taux: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Totaux MENSUELS des lignes actives, par devise, par plateforme (répartition à parts égales) et par cluster.
    → {mensuel: {devise: montant}, annuel: {devise: montant}, plateformes: {nom: {devise: montant}}, clusters: {nom: {devise: montant}}}."""
    mensuel: Dict[str, float] = {}
    plateformes: Dict[str, Dict[str, float]] = {}
    clusters: Dict[str, Dict[str, float]] = {}

    def ajouter(cible: Dict[str, Any], cle: str, devise: str, montant: float) -> None:
        cible.setdefault(cle, {})
        cible[cle][devise] = round(cible[cle].get(devise, 0.0) + montant, 2)

    for l in lignes:
        if not l.get("actif", True):
            continue
        devise, m = l["devise"], float(l.get("mensuel") or 0)
        mensuel[devise] = round(mensuel.get(devise, 0.0) + m, 2)
        parts = l.get("plateformes") or [COMMUN]
        for p in parts:
            ajouter(plateformes, p, devise, m / len(parts))
        if l.get("cluster"):
            ajouter(clusters, l["cluster"], devise, m)
    resultat = {"mensuel": mensuel, "annuel": {d: round(v * 12, 2) for d, v in mensuel.items()}, "plateformes": plateformes, "clusters": clusters}
    if taux is not None:
        # Équivalents en FCFA (lot 175) ; les devises sans taux sont signalées au lieu d'être ignorées en silence
        def fcfa(par_devise: Dict[str, float]) -> float:
            return round(sum(en_fcfa(v, d, taux) or 0 for d, v in par_devise.items()))
        resultat["mensuel_fcfa"] = fcfa(mensuel)
        resultat["annuel_fcfa"] = round(resultat["mensuel_fcfa"] * 12)
        resultat["plateformes_fcfa"] = {n: fcfa(m) for n, m in plateformes.items()}
        resultat["clusters_fcfa"] = {n: fcfa(m) for n, m in clusters.items()}
        resultat["devises_sans_taux"] = sorted(d for d in mensuel if en_fcfa(1, d, taux) is None)
    return resultat


# ---------------------------------------------------------------------------------------------------------------------
# Lectures automatiques (jamais bloquantes : une erreur est gardée avec son message, sans clé ni identifiant)
# ---------------------------------------------------------------------------------------------------------------------
def analyser_facture_atlas(facture: Dict[str, Any]) -> Dict[str, Any]:
    """Facture en cours d'Atlas (montants en centimes) → montant par cluster. Tolérant : un champ absent vaut zéro."""
    par_cluster: Dict[str, float] = {}
    for it in facture.get("lineItems") or []:
        nom = _texte(it.get("clusterName"), 60) or _texte(it.get("groupName"), 60) or "Sans cluster"
        par_cluster[nom] = par_cluster.get(nom, 0.0) + float(it.get("totalPriceCents") or 0) / 100
    clusters = [{"nom": n, "montant": round(m, 2)} for n, m in sorted(par_cluster.items(), key=lambda x: -x[1])]
    total = round(sum(c["montant"] for c in clusters), 2)
    return {"devise": "USD", "total": total, "clusters": clusters, "periode_du": _texte(facture.get("startDate"), 25),
            "periode_au": _texte(facture.get("endDate"), 25)}


async def lire_atlas(client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """Facture EN COURS de l'organisation Atlas (clés d'API en variables d'environnement). Ne lève jamais."""
    pub, priv, org = (os.environ.get(k, "").strip() for k in ("ATLAS_API_PUBLIC_KEY", "ATLAS_API_PRIVATE_KEY", "ATLAS_ORG_ID"))
    le = _maintenant().isoformat()
    if not (pub and priv and org):
        return {"le": le, "erreur": "Clés Atlas non saisies (ATLAS_API_PUBLIC_KEY, ATLAS_API_PRIVATE_KEY, ATLAS_ORG_ID sur Render)"}
    propre = client is None
    http = client or httpx.AsyncClient(timeout=30)
    try:
        r = await http.get(f"https://cloud.mongodb.com/api/atlas/v2/orgs/{org}/invoices/pending",
                           headers={"Accept": "application/vnd.atlas.2023-01-01+json"}, auth=httpx.DigestAuth(pub, priv))
        if r.status_code >= 300:
            return {"le": le, "erreur": f"Atlas a refusé la lecture (HTTP {r.status_code}) : vérifiez les clés et le droit « Organization Billing Viewer »"}
        return {"le": le, "erreur": None, **analyser_facture_atlas(r.json() or {})}
    except Exception as exc:  # noqa: BLE001 — réseau, JSON illisible… : on le dit sans détail sensible
        return {"le": le, "erreur": f"Lecture d'Atlas impossible ({type(exc).__name__})"}
    finally:
        if propre:
            await http.aclose()


def estimer_r2(stockage_go: float, operations_a: int, operations_b: int) -> Dict[str, Any]:
    """Coût ESTIMÉ du mois en dollars d'après les tarifs publics de R2 (stockage au-delà de 10 Go, opérations au-delà des gratuites)."""
    stockage = max(0.0, stockage_go - R2_GO_GRATUITS) * R2_PRIX_GO
    ops_a = max(0, operations_a - R2_GRATUIT_A) / 1_000_000 * R2_PRIX_A
    ops_b = max(0, operations_b - R2_GRATUIT_B) / 1_000_000 * R2_PRIX_B
    return {"montant": round(stockage + ops_a + ops_b, 2), "devise": "USD",
            "detail": f"{stockage_go:.1f} Go (10 Go gratuits) · {operations_a:,} opérations A · {operations_b:,} opérations B".replace(",", " ")}


REQUETE_R2 = """query($compte: String!, $debut: Time!, $fin: Time!, $debutJour: Date!, $finJour: Date!) {
  viewer { accounts(filter: {accountTag: $compte}) {
    stockage: r2StorageAdaptiveGroups(limit: 1000, filter: {datetime_geq: $debut, datetime_leq: $fin}) {
      max { payloadSize metadataSize } dimensions { bucketName } }
    operations: r2OperationsAdaptiveGroups(limit: 1000, filter: {datetime_geq: $debut, datetime_leq: $fin}) {
      sum { requests } dimensions { actionType } } } } }"""


def analyser_reponse_r2(donnees: Dict[str, Any]) -> Dict[str, Any]:
    """Réponse GraphQL de Cloudflare → estimation (stockage : plus grande valeur du mois par bucket, additionnées)."""
    comptes = (((donnees or {}).get("data") or {}).get("viewer") or {}).get("accounts") or []
    compte = comptes[0] if comptes else {}
    par_bucket: Dict[str, float] = {}
    for g in compte.get("stockage") or []:
        nom = ((g.get("dimensions") or {}).get("bucketName")) or "?"
        m = g.get("max") or {}
        octets = float(m.get("payloadSize") or 0) + float(m.get("metadataSize") or 0)
        par_bucket[nom] = max(par_bucket.get(nom, 0.0), octets)
    classe_a = classe_b = 0
    for g in compte.get("operations") or []:
        action = ((g.get("dimensions") or {}).get("actionType")) or ""
        n = int((g.get("sum") or {}).get("requests") or 0)
        if action in ACTIONS_CLASSE_B:
            classe_b += n
        else:
            classe_a += n
    return {**estimer_r2(sum(par_bucket.values()) / 1024 ** 3, classe_a, classe_b), "buckets": len(par_bucket)}


async def lire_r2(client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """Estimation du mois pour Cloudflare R2 (jeton d'API et identifiant de compte en variables d'environnement). Ne lève jamais."""
    jeton, compte = (os.environ.get(k, "").strip() for k in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"))
    maintenant = _maintenant()
    le = maintenant.isoformat()
    if not (jeton and compte):
        return {"le": le, "erreur": "Clés Cloudflare non saisies (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID sur Render)"}
    debut = maintenant.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    propre = client is None
    http = client or httpx.AsyncClient(timeout=30)
    try:
        r = await http.post("https://api.cloudflare.com/client/v4/graphql", headers={"Authorization": f"Bearer {jeton}"},
                            json={"query": REQUETE_R2, "variables": {
                                "compte": compte, "debut": debut.strftime("%Y-%m-%dT%H:%M:%SZ"), "fin": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "debutJour": debut.date().isoformat(), "finJour": maintenant.date().isoformat()}})
        if r.status_code >= 300:
            return {"le": le, "erreur": f"Cloudflare a refusé la lecture (HTTP {r.status_code}) : vérifiez le jeton et son droit de lecture des analyses"}
        corps = r.json() or {}
        if corps.get("errors"):
            message = _texte((corps["errors"][0] or {}).get("message"), 120)
            # « not authorized for that account » : jeton sans le droit Analytics du compte, ou identifiant de compte inexact
            aide = (" — vérifiez que le jeton a le droit « Account Analytics : Read » sur CE compte (Ressources du compte : Inclure → ce compte) "
                    "et que CLOUDFLARE_ACCOUNT_ID est l'identifiant du même compte") if "not authorized" in message.lower() else ""
            return {"le": le, "erreur": "Cloudflare a refusé la requête : " + message + aide}
        return {"le": le, "erreur": None, **analyser_reponse_r2(corps)}
    except Exception as exc:  # noqa: BLE001
        return {"le": le, "erreur": f"Lecture de Cloudflare impossible ({type(exc).__name__})"}
    finally:
        if propre:
            await http.aclose()


# ---------------------------------------------------------------------------------------------------------------------
# Document, lecture groupée, rappels
# ---------------------------------------------------------------------------------------------------------------------
async def charger(db) -> Dict[str, Any]:
    d = await db.settings.find_one({"_id": DOC_ID}) or {}
    return {"services": normaliser_services(d.get("services")), "clusters": normaliser_clusters(d.get("clusters")),
            "taux": normaliser_taux(d.get("taux")), "lectures": d.get("lectures") or {}, "rappels_envoyes": list(d.get("rappels_envoyes") or [])}


async def lire_auto(db, forcer: bool = False, maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Relit les sources automatiques utilisées par la liste (Atlas, R2) si la lecture date de plus de 6 h (ou `forcer`)."""
    maintenant = maintenant or _maintenant()
    etat = await charger(db)
    lectures = dict(etat["lectures"])
    for source, lecteur in (("atlas", lire_atlas), ("r2", lire_r2)):
        if not any(s["source"] == source and s["actif"] for s in etat["services"]):
            continue
        ancienne = lectures.get(source) or {}
        try:
            recente = (maintenant - datetime.fromisoformat(ancienne["le"])) < timedelta(hours=DUREE_LECTURE_H) and not ancienne.get("erreur")
        except (KeyError, ValueError, TypeError):
            recente = False
        if forcer or not recente:
            lectures[source] = await lecteur()
    await db.settings.update_one({"_id": DOC_ID}, {"$set": {"lectures": lectures}}, upsert=True)
    return lectures


def texte_rappel(l: Dict[str, Any], jours: int) -> str:
    """Message de rappel (une ligne) : service, formule, échéance, montant, plateformes, lien de paiement."""
    quand = "aujourd'hui" if jours == 0 else f"dans {jours} jour(s)"
    cible = ", ".join(l.get("plateformes") or []) or COMMUN
    lien = f" Payer : {l['lien_paiement']}" if l.get("lien_paiement") else ""
    return (f"💳 À renouveler {quand} : {l['nom']}{' (' + l['formule'] + ')' if l.get('formule') else ''} — échéance le "
            f"{l['prochaine_echeance']}, {l['montant']:g} {l['devise']} ({l['periodicite']}). Plateformes : {cible}.{lien}")


async def rappeler(db, maintenant: Optional[datetime] = None, envoyer=None) -> int:
    """Tâche quotidienne : un WhatsApp au super-admin pour chaque service dont l'échéance tombe à un palier (30, 7, 1, 0 jour),
    une seule fois par service, échéance et palier. Renvoie le nombre de rappels envoyés. Ne lève jamais."""
    maintenant = maintenant or _maintenant()
    if envoyer is None:
        from routes import quota_atlas as qa
        envoyer = qa._envoyer_alerte
    etat = await charger(db)
    deja = set(etat["rappels_envoyes"])
    envoyes = 0
    for s in etat["services"]:
        if not s["actif"] or not s["prochaine_echeance"]:
            continue
        jours = jours_restants(s["prochaine_echeance"], maintenant.date())
        if jours not in s["rappels_jours"]:
            continue
        cle = f"{s['id']}|{s['prochaine_echeance']}|{jours}"
        if cle in deja:
            continue
        try:
            if await envoyer(db, texte_rappel(s, jours), maintenant):
                deja.add(cle)
                envoyes += 1
        except Exception:  # noqa: BLE001 — un rappel en échec ne doit rien casser
            logger.warning("[services_renouveler] rappel non envoyé", exc_info=True)
    if envoyes:
        await db.settings.update_one({"_id": DOC_ID}, {"$set": {"rappels_envoyes": sorted(deja)[-300:]}}, upsert=True)
    return envoyes


# ---------------------------------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------------------------------
class ServiceIn(BaseModel):
    id: Optional[str] = None
    nom: str = Field(default="", max_length=120)
    fournisseur: str = Field(default="", max_length=60)
    formule: str = Field(default="", max_length=80)
    montant: float = Field(default=0, ge=0)
    devise: str = Field(default="USD", max_length=6)
    periodicite: str = "mensuel"
    prochaine_echeance: Optional[str] = None
    lien_paiement: str = Field(default="", max_length=300)
    plateformes: List[str] = Field(default_factory=list, max_length=20)
    cluster: str = Field(default="", max_length=60)
    source: str = "saisi"
    actif: bool = True
    rappels_jours: List[int] = Field(default_factory=lambda: list(RAPPELS_DEFAUT), max_length=10)


class ListeIn(BaseModel):
    services: List[ServiceIn] = Field(default_factory=list, max_length=MAX_SERVICES)
    clusters: Dict[str, List[str]] = Field(default_factory=dict)
    taux: Dict[str, float] = Field(default_factory=dict)          # lot 175 : FCFA pour 1 unité de chaque devise


def setup_services_renouveler_routes(*, db, api, get_current_admin) -> None:
    """Branche les routes du lot 170 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException

    async def _vue(forcer: bool = False) -> Dict[str, Any]:
        lectures = await lire_auto(db, forcer)
        etat = await charger(db)
        lignes = lignes_calculees(etat["services"], lectures, etat["clusters"], _maintenant().date())
        for l in lignes:   # équivalent en FCFA de chaque ligne (None si la devise n'a pas de taux)
            l["montant_fcfa"] = en_fcfa(l["montant"], l["devise"], etat["taux"])
            l["mensuel_fcfa"] = en_fcfa(l.get("mensuel") or 0, l["devise"], etat["taux"])
        lignes.sort(key=lambda l: (l["jours"] is None, l["jours"] if l["jours"] is not None else 0, l["nom"].lower()))
        # Toutes les plateformes connues (lignes et clusters) : propose les cases de la liste et du tableau « par plateforme »
        plateformes = sorted({p for s in etat["services"] for p in s["plateformes"]} | {p for ps in etat["clusters"].values() for p in ps})
        return {"lignes": lignes, "totaux": totaux(lignes, etat["taux"]), "taux": etat["taux"], "services": etat["services"], "clusters": etat["clusters"],
                "plateformes": plateformes, "lectures": {k: {"le": v.get("le"), "erreur": v.get("erreur")} for k, v in lectures.items()},
                "periodicites": list(PERIODICITES), "le": _maintenant().isoformat()}

    @api.get("/admin/services-renouveler", tags=["Admin — Services à renouveler"])
    async def lire(_: dict = Depends(get_current_admin)):
        """Liste, montants (lus ou saisis), totaux par plateforme et par cluster, à la date de lecture."""
        return await _vue()

    @api.post("/admin/services-renouveler/lire", tags=["Admin — Services à renouveler"])
    async def relire(_: dict = Depends(get_current_admin)):
        """Force une nouvelle lecture d'Atlas et de Cloudflare (au lieu d'attendre les 6 heures)."""
        return await _vue(forcer=True)

    @api.put("/admin/services-renouveler", tags=["Admin — Services à renouveler"])
    async def ecrire(data: ListeIn, _: dict = Depends(get_current_admin)):
        """Remplace la liste des services et la répartition des clusters Atlas par plateforme."""
        services = normaliser_services([s.model_dump() for s in data.services])
        await db.settings.update_one({"_id": DOC_ID}, {"$set": {"services": services, "clusters": normaliser_clusters(data.clusters), "taux": normaliser_taux(data.taux)}}, upsert=True)
        return await _vue()

    @api.post("/admin/services-renouveler/{service_id}/renouveler", tags=["Admin — Services à renouveler"])
    async def renouveler(service_id: str, _: dict = Depends(get_current_admin)):
        """« Renouvelé » : l'échéance avance d'une période (la sortie « unique » est désactivée)."""
        etat = await charger(db)
        s = next((x for x in etat["services"] if x["id"] == service_id), None)
        if not s:
            raise HTTPException(status_code=404, detail="Service introuvable")
        suivante = echeance_suivante(s["prochaine_echeance"], s["periodicite"], _maintenant().date())
        s["prochaine_echeance"] = suivante
        if suivante is None:
            s["actif"] = False
        await db.settings.update_one({"_id": DOC_ID}, {"$set": {"services": etat["services"]}}, upsert=True)
        return await _vue()
