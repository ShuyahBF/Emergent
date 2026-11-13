# presence_balises.py — Lot 387 : PRÉSENCE ET PARCOURS PAR BALISES BLUETOOTH (cas 3 : suivre les visiteurs d'un site grâce à leurs badges).
#
# Demande du propriétaire (13/11/2026) : des balises Bluetooth (kit Estimote) servent de BADGES portés par les visiteurs ; des RÉCEPTEURS fixes
# (un téléphone Android, plus tard un PC Windows ou un petit boîtier) écoutent les badges et les signalent à SAWALI, qui montre qui est où et
# garde le parcours. Le tout doit être TRÈS MODULAIRE : un futur client doit pouvoir brancher son propre site Web ou une application Windows
# sans rien changer d'autre.
#
# ARCHITECTURE EN TROIS BRIQUES INDÉPENDANTES (seul le CONTRAT D'ÉCHANGE ci-dessous les relie)
#   1. RÉCEPTEURS  : tout ce qui entend des balises et envoie des détections (application Android « Personnel de maison », future application
#                    Windows, boîtier ESP32 / Raspberry…). Ils ne connaissent QUE la route /presence-balises/v1/detections.
#   2. SERVEUR     : ce module (logique pure testée + routes). Il ne connaît ni les récepteurs ni les écrans.
#   3. ÉCRANS      : tout ce qui affiche (rubrique des Paramètres de SAWALI, site Web du client, application Windows). Ils ne connaissent QUE les
#                    routes /admin/presence-balises/… (lecture de l'état, du parcours).
#
# CONTRAT D'ÉCHANGE v1 (stable : tout changement incompatible passera par /v2)
#   Récepteur → serveur   POST /api/presence-balises/v1/detections
#       en-têtes  X-Recepteur: <id_site>:<id_recepteur>      X-Cle: <clé remise une seule fois à la création du récepteur>
#       corps     {"detections": [{"badge": "ib:<uuid>:<major>:<minor>", "rssi": -67}, …]}     (200 détections au plus par envoi)
#       réponse   {"acceptees": 12, "ignorees": 0}
#       « badge » = identifiant stable de la balise tel que le produit déjà « Personnel de maison » (iBeacon « ib:… », Eddystone « ed:… », ou toute
#       chaîne de 3 à 80 caractères) ; « rssi » = puissance du signal reçu en dBm.
#   Écran ← serveur   GET /api/admin/presence-balises/sites/{id}/etat      qui est dans quelle zone, depuis quand, badges inconnus détectés
#                     GET /api/admin/presence-balises/sites/{id}/parcours  passages d'un badge (entrées, changements de zone, sorties)
#
# RÈGLES DE PRÉSENCE (logique pure, testée)
#   - Un badge est dans la ZONE du récepteur qui l'entend le plus fort, parmi ceux qui l'ont entendu depuis moins de `delai_absence_s` (60 s par défaut).
#   - Anti-rebond : le badge ne change de zone que si le nouveau récepteur est plus fort d'au moins MARGE_DB (6 dB) que l'actuel, ou si l'ancien ne l'entend plus.
#   - Plus aucun récepteur ne l'entend → ABSENT (sortie du site). Chaque changement est un évènement horodaté : {t, badge, de, vers}.
#
# VIE PRIVÉE (suivre des personnes demande leur accord)
#   - Un badge n'est lié à aucun nom : seulement un libellé choisi par le site (« Visiteur 12 »). Les évènements plus vieux que `conservation_jours`
#     (30 par défaut) sont supprimés à chaque envoi. Le site doit informer les visiteurs et recueillir leur consentement.
#
# STOCKAGE (démonstration, sans nouvelle collection : le cluster MongoDB est plein)
#   Un document par site dans la collection `settings` (`_id` = « presence-balises:<id_site> »), évènements limités à 2000. Pour un client en
#   production : remplacer les fonctions `_lire_site` / `_ecrire_site` (seul point d'accès à la base) par une autre base, sans toucher au reste.
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request  # au niveau du module : l'annotation de la route doit être résolue (from __future__)

PREFIXE_ID = "presence-balises:"
DELAI_ABSENCE_DEFAUT_S = 60
CONSERVATION_DEFAUT_JOURS = 30
MARGE_DB = 6                      # anti-rebond entre deux récepteurs voisins
MAX_DETECTIONS = 200              # par envoi
MAX_EVENEMENTS = 2000             # par site (démonstration)
MAX_INCONNUS = 200                # badges non enregistrés gardés par site
_BADGE_RE = re.compile(r"^[A-Za-z0-9:_\-.]{3,80}$")


# =====================================================================================
# Logique pure (testée : tests/test_lot387_presence_balises.py)
# =====================================================================================

def badge_valide(brut: Any) -> Optional[str]:
    """Identifiant de badge nettoyé (3 à 80 caractères sûrs) ou None."""
    texte = str(brut or "").strip()
    return texte if _BADGE_RE.match(texte) else None


def rssi_valide(brut: Any) -> Optional[int]:
    """Puissance en dBm entre -127 et 0, ou None."""
    try:
        v = int(brut)
    except (TypeError, ValueError):
        return None
    return v if -127 <= v <= 0 else None


def zone_courante(vus: Dict[str, Dict[str, Any]], recepteurs: Dict[str, str], maintenant: float, delai_s: float,
                  zone_actuelle: Optional[str] = None) -> Optional[str]:
    """Zone du badge : celle du récepteur qui l'entend le plus fort parmi ceux qui l'ont entendu depuis moins de `delai_s`.
    `vus` = {id_recepteur: {"t": secondes, "rssi": dBm}} ; `recepteurs` = {id_recepteur: id_zone}. Anti-rebond : on ne quitte la zone actuelle que si
    un récepteur d'une autre zone est plus fort d'au moins MARGE_DB, ou si aucun récepteur de la zone actuelle n'entend plus le badge."""
    frais = [(v["rssi"], rid) for rid, v in (vus or {}).items() if rid in recepteurs and maintenant - v["t"] <= delai_s]
    if not frais:
        return None
    meilleur_rssi, meilleur_rid = max(frais)
    meilleure_zone = recepteurs[meilleur_rid]
    if zone_actuelle and meilleure_zone != zone_actuelle:
        dans_actuelle = [rssi for rssi, rid in frais if recepteurs[rid] == zone_actuelle]
        if dans_actuelle and meilleur_rssi - max(dans_actuelle) < MARGE_DB:
            return zone_actuelle
    return meilleure_zone


def appliquer_detections(site: Dict[str, Any], id_recepteur: str, detections: List[Dict[str, Any]], maintenant: float) -> Dict[str, Any]:
    """Applique un envoi du récepteur à l'état du site (modifié sur place) et rend {acceptees, ignorees, evenements}."""
    etat = site.setdefault("etat", {})
    badges = etat.setdefault("badges", {})
    recepteurs = {r["id"]: r["zone_id"] for r in site.get("recepteurs") or []}
    delai = float(site.get("delai_absence_s") or DELAI_ABSENCE_DEFAUT_S)
    acceptees = ignorees = 0
    for d in (detections or [])[:MAX_DETECTIONS]:
        if not isinstance(d, dict):                  # un élément qui n'est pas un objet est simplement ignoré (jamais d'erreur 500)
            ignorees += 1
            continue
        badge, rssi = badge_valide(d.get("badge")), rssi_valide(d.get("rssi"))
        if badge is None or rssi is None:
            ignorees += 1
            continue
        b = badges.setdefault(badge, {"vus": {}, "zone": None, "depuis": None})
        b["vus"][id_recepteur] = {"t": maintenant, "rssi": rssi}
        acceptees += 1
    evenements = []
    for badge in list(badges):                      # on recalcule tous les badges : un badge peut être devenu absent
        evenements += _recalculer(badges, badge, recepteurs, maintenant, delai)
    _limiter_inconnus(site, badges)
    return {"acceptees": acceptees, "ignorees": ignorees, "evenements": evenements}


def balayer(site: Dict[str, Any], maintenant: float) -> List[Dict[str, Any]]:
    """Détecte les sorties (aucun récepteur n'entend plus le badge) sans nouvel envoi : appelé à chaque lecture de l'état."""
    badges = (site.get("etat") or {}).get("badges") or {}
    recepteurs = {r["id"]: r["zone_id"] for r in site.get("recepteurs") or []}
    delai = float(site.get("delai_absence_s") or DELAI_ABSENCE_DEFAUT_S)
    evenements: List[Dict[str, Any]] = []
    for badge in list(badges):
        evenements += _recalculer(badges, badge, recepteurs, maintenant, delai)
    return evenements


def _recalculer(badges: Dict[str, Any], badge: str, recepteurs: Dict[str, str], maintenant: float, delai: float) -> List[Dict[str, Any]]:
    """Met à jour la zone d'un badge ; rend l'évènement de changement (liste vide si rien ne change)."""
    b = badges[badge]
    nouvelle = zone_courante(b["vus"], recepteurs, maintenant, delai, b.get("zone"))
    if nouvelle == b.get("zone"):
        return []
    ancienne = b.get("zone")
    b["zone"], b["depuis"] = nouvelle, maintenant
    return [{"t": maintenant, "badge": badge, "de": ancienne, "vers": nouvelle}]


def _limiter_inconnus(site: Dict[str, Any], badges: Dict[str, Any]) -> None:
    """Garde au plus MAX_INCONNUS badges non enregistrés (les plus récemment vus) : le site ne grossit pas sans limite."""
    connus = {b["id"] for b in site.get("badges") or []}
    inconnus = [(max((v["t"] for v in badges[x]["vus"].values()), default=0), x) for x in badges if x not in connus]
    for _, x in sorted(inconnus)[:max(0, len(inconnus) - MAX_INCONNUS)]:
        badges.pop(x, None)


def purger_evenements(evenements: List[Dict[str, Any]], maintenant: float, conservation_jours: int) -> List[Dict[str, Any]]:
    """Supprime les évènements plus vieux que la durée de conservation puis garde les MAX_EVENEMENTS plus récents."""
    limite = maintenant - max(1, int(conservation_jours)) * 86400
    return [e for e in evenements if e["t"] >= limite][-MAX_EVENEMENTS:]


def vue_etat(site: Dict[str, Any], maintenant: float) -> Dict[str, Any]:
    """État affiché : pour chaque zone les badges présents (libellé, depuis quand, dernier signal), badges inconnus, absents connus."""
    zones = {z["id"]: z["nom"] for z in site.get("zones") or []}
    libelles = {b["id"]: b.get("libelle") or b["id"] for b in site.get("badges") or []}
    badges = (site.get("etat") or {}).get("badges") or {}
    par_zone = {zid: [] for zid in zones}
    inconnus, absents = [], []
    for badge, b in badges.items():
        dernier = max((v["t"] for v in b["vus"].values()), default=0)
        ligne = {"badge": badge, "libelle": libelles.get(badge), "depuis_s": int(maintenant - b["depuis"]) if b.get("depuis") else None,
                 "dernier_signal_s": int(maintenant - dernier)}
        if badge not in libelles:
            inconnus.append(ligne)
        elif b.get("zone") in par_zone:
            par_zone[b["zone"]].append(ligne)
        else:
            absents.append(ligne)
    deja = {x["badge"] for x in absents}
    absents += [{"badge": i, "libelle": l, "depuis_s": None, "dernier_signal_s": None} for i, l in libelles.items() if i not in badges and i not in deja]
    return {"zones": [{"id": z, "nom": n, "presents": sorted(par_zone[z], key=lambda x: x["libelle"] or "")} for z, n in zones.items()],
            "absents": absents, "inconnus": sorted(inconnus, key=lambda x: x["dernier_signal_s"])}


def parcours(site: Dict[str, Any], badge: str) -> List[Dict[str, Any]]:
    """Passages d'un badge, du plus récent au plus ancien : {t, de, vers} avec les NOMS des zones (None = hors du site)."""
    zones = {z["id"]: z["nom"] for z in site.get("zones") or []}
    sortie = []
    for e in site.get("evenements") or []:
        if e["badge"] == badge:
            sortie.append({"t": datetime.fromtimestamp(e["t"], timezone.utc).isoformat(), "de": zones.get(e["de"]), "vers": zones.get(e["vers"])})
    return sortie[::-1]


def hacher_cle(cle: str) -> str:
    return hashlib.sha256(cle.encode()).hexdigest()


# =====================================================================================
# Routes
# =====================================================================================

def setup_presence_balises_routes(*, db, api, get_current_user, maintenant=lambda: datetime.now(timezone.utc).timestamp()) -> None:
    """Branche les routes du lot 387 (appelée depuis server_parts/p20). `maintenant` est remplaçable par les tests."""
    from fastapi import Depends, HTTPException

    def _admin(user: dict) -> None:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    # ---- Seul point d'accès à la base (à remplacer pour une autre base de stockage) ----
    async def _lire_site(site_id: str) -> Optional[Dict[str, Any]]:
        return await db.settings.find_one({"_id": PREFIXE_ID + site_id})

    async def _ecrire_site(site: Dict[str, Any]) -> None:
        await db.settings.replace_one({"_id": site["_id"]}, site, upsert=True)

    async def _site_ou_404(site_id: str) -> Dict[str, Any]:
        site = await _lire_site(site_id)
        if not site:
            raise HTTPException(status_code=404, detail="Site introuvable")
        return site

    def _vue_site(site: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": site["id"], "nom": site["nom"], "delai_absence_s": site.get("delai_absence_s", DELAI_ABSENCE_DEFAUT_S),
                "conservation_jours": site.get("conservation_jours", CONSERVATION_DEFAUT_JOURS), "zones": site.get("zones") or [],
                "badges": site.get("badges") or [],
                "recepteurs": [{"id": r["id"], "nom": r["nom"], "zone_id": r["zone_id"]} for r in site.get("recepteurs") or []]}

    # ------------------------------------------------------------------ récepteurs
    @api.post("/presence-balises/v1/detections", tags=["Présence par balises — récepteurs"])
    async def recevoir(request: Request):
        """Contrat v1 : un récepteur envoie les badges entendus. Authentification par X-Recepteur (« site:recepteur ») et X-Cle."""
        ident = (request.headers.get("X-Recepteur") or "").strip()
        cle = request.headers.get("X-Cle") or ""
        site_id, _, rid = ident.partition(":")
        site = await _lire_site(site_id) if site_id and rid else None
        recepteur = next((r for r in (site or {}).get("recepteurs") or [] if r["id"] == rid), None)
        if not site or not recepteur or not hmac.compare_digest(recepteur["cle_hash"], hacher_cle(cle)):
            raise HTTPException(status_code=401, detail="Récepteur inconnu ou clé refusée")
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        detections = corps.get("detections") if isinstance(corps, dict) else None
        if not isinstance(detections, list):
            raise HTTPException(status_code=422, detail="« detections » doit être une liste")
        maint = maintenant()
        res = appliquer_detections(site, rid, detections, maint)
        recepteur["dernier_envoi"] = maint
        site["evenements"] = purger_evenements((site.get("evenements") or []) + res["evenements"], maint, site.get("conservation_jours") or CONSERVATION_DEFAUT_JOURS)
        await _ecrire_site(site)
        return {"acceptees": res["acceptees"], "ignorees": res["ignorees"]}

    # ------------------------------------------------------------------ écrans (administrateur)
    @api.get("/admin/presence-balises/sites", tags=["Présence par balises — écrans"])
    async def lister(user: dict = Depends(get_current_user)):
        _admin(user)
        sites = [_vue_site(s) async for s in db.settings.find({"_id": {"$regex": "^" + re.escape(PREFIXE_ID)}})]
        return {"sites": sorted(sites, key=lambda s: s["nom"].lower())}

    @api.post("/admin/presence-balises/sites", tags=["Présence par balises — écrans"])
    async def creer(request: Request, user: dict = Depends(get_current_user)):
        _admin(user)
        corps = await request.json()
        nom = str((corps or {}).get("nom") or "").strip()[:80]
        if not nom:
            raise HTTPException(status_code=422, detail="Nom du site obligatoire")
        site_id = uuid.uuid4().hex[:12]
        site = {"_id": PREFIXE_ID + site_id, "id": site_id, "nom": nom, "zones": [], "badges": [], "recepteurs": [], "evenements": [], "etat": {"badges": {}},
                "delai_absence_s": DELAI_ABSENCE_DEFAUT_S, "conservation_jours": CONSERVATION_DEFAUT_JOURS}
        await _ecrire_site(site)
        return _vue_site(site)

    @api.put("/admin/presence-balises/sites/{site_id}", tags=["Présence par balises — écrans"])
    async def configurer(site_id: str, request: Request, user: dict = Depends(get_current_user)):
        """Remplace la configuration : nom, délai d'absence, conservation, zones [{id?, nom}] et badges [{id, libelle}]."""
        _admin(user)
        site = await _site_ou_404(site_id)
        corps = await request.json()
        if not isinstance(corps, dict):
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        if "nom" in corps:
            site["nom"] = str(corps["nom"]).strip()[:80] or site["nom"]
        for cle, bas, haut in (("delai_absence_s", 10, 3600), ("conservation_jours", 1, 365)):
            if cle in corps:
                try:
                    v = int(corps[cle])
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"{cle} invalide")
                if not bas <= v <= haut:
                    raise HTTPException(status_code=422, detail=f"{cle} : de {bas} à {haut}")
                site[cle] = v
        if "zones" in corps:
            zones = [{"id": str(z.get("id") or uuid.uuid4().hex[:8]), "nom": str(z.get("nom") or "").strip()[:60]} for z in corps["zones"] if str(z.get("nom") or "").strip()]
            ids = {z["id"] for z in zones}
            if any(r["zone_id"] not in ids for r in site["recepteurs"]):
                raise HTTPException(status_code=422, detail="Une zone encore utilisée par un récepteur ne peut pas être supprimée")
            site["zones"] = zones
        if "badges" in corps:
            badges, vus = [], set()
            for b in corps["badges"]:
                ident = badge_valide(b.get("id"))
                if ident is None or ident in vus:
                    raise HTTPException(status_code=422, detail=f"Identifiant de badge invalide ou en double : {b.get('id')}")
                vus.add(ident)
                badges.append({"id": ident, "libelle": str(b.get("libelle") or "").strip()[:60] or ident})
            site["badges"] = badges
        await _ecrire_site(site)
        return _vue_site(site)

    @api.post("/admin/presence-balises/sites/{site_id}/recepteurs", tags=["Présence par balises — écrans"])
    async def ajouter_recepteur(site_id: str, request: Request, user: dict = Depends(get_current_user)):
        """Crée un récepteur dans une zone ; sa clé n'est montrée QU'UNE FOIS dans cette réponse (seul son hachage est gardé)."""
        _admin(user)
        site = await _site_ou_404(site_id)
        corps = await request.json()
        nom, zone_id = str((corps or {}).get("nom") or "").strip()[:60], (corps or {}).get("zone_id")
        if not nom or zone_id not in {z["id"] for z in site["zones"]}:
            raise HTTPException(status_code=422, detail="Nom du récepteur et zone existante obligatoires")
        rid, cle = uuid.uuid4().hex[:8], secrets.token_urlsafe(24)
        site["recepteurs"].append({"id": rid, "nom": nom, "zone_id": zone_id, "cle_hash": hacher_cle(cle), "dernier_envoi": None})
        await _ecrire_site(site)
        return {"id": rid, "nom": nom, "zone_id": zone_id, "identifiant": f"{site_id}:{rid}", "cle": cle}

    @api.delete("/admin/presence-balises/sites/{site_id}/recepteurs/{rid}", tags=["Présence par balises — écrans"])
    async def supprimer_recepteur(site_id: str, rid: str, user: dict = Depends(get_current_user)):
        _admin(user)
        site = await _site_ou_404(site_id)
        avant = len(site["recepteurs"])
        site["recepteurs"] = [r for r in site["recepteurs"] if r["id"] != rid]
        if len(site["recepteurs"]) == avant:
            raise HTTPException(status_code=404, detail="Récepteur introuvable")
        for b in site["etat"]["badges"].values():
            b["vus"].pop(rid, None)
        await _ecrire_site(site)
        return {"ok": True}

    @api.get("/admin/presence-balises/sites/{site_id}/etat", tags=["Présence par balises — écrans"])
    async def etat(site_id: str, user: dict = Depends(get_current_user)):
        """Qui est dans quelle zone MAINTENANT (les sorties sont détectées ici même si aucun récepteur n'a écrit)."""
        _admin(user)
        site = await _site_ou_404(site_id)
        maint = maintenant()
        nouveaux = balayer(site, maint)
        if nouveaux:
            site["evenements"] = purger_evenements((site.get("evenements") or []) + nouveaux, maint, site.get("conservation_jours") or CONSERVATION_DEFAUT_JOURS)
            await _ecrire_site(site)
        recepteurs = [{"id": r["id"], "nom": r["nom"], "zone_id": r["zone_id"],
                       "dernier_envoi_s": int(maint - r["dernier_envoi"]) if r.get("dernier_envoi") else None} for r in site["recepteurs"]]
        return {**vue_etat(site, maint), "recepteurs": recepteurs}

    @api.get("/admin/presence-balises/sites/{site_id}/parcours", tags=["Présence par balises — écrans"])
    async def parcours_badge(site_id: str, badge: str, user: dict = Depends(get_current_user)):
        _admin(user)
        site = await _site_ou_404(site_id)
        return {"badge": badge, "passages": parcours(site, badge)[:500]}

    @api.delete("/admin/presence-balises/sites/{site_id}", tags=["Présence par balises — écrans"])
    async def supprimer_site(site_id: str, user: dict = Depends(get_current_user)):
        _admin(user)
        res = await db.settings.delete_one({"_id": PREFIXE_ID + site_id})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Site introuvable")
        return {"ok": True}
