"""Lot 111 — page de présentation d'un carrousel WhatsApp (une position par carte) et carrousel SPONSORISÉ
piloté par la régie publicitaire existante (collection `ad_banners`).

Demande du propriétaire (11/10/2026) : « Permettre à une carte d'un carrousel WA d'afficher une page descriptive,
par exemple https://sawalismartsystems.com/presentation#cartex où cartex représente une position dans la page… et
implémenter la possibilité d'utiliser ce type de carrousel comme piloté par une régie publicitaire comptabilisant
les clics pour facturation. »

Ce module regroupe les fonctions partagées par routes/carrousel_whatsapp.py (lien court, page publique,
événements, envoi) et routes/ad_banners.py (rapport de l'annonceur, liste des carrousels) :

  A. Présentation
     - chaque campagne de carrousel reçoit un IDENTIFIANT PUBLIC aléatoire (`id_public`, non devinable) ;
     - le lien court du bouton (/api/public/carrousel/l/{code}) renvoie vers
       <site>/presentation/c/<id_public>?depuis=<code>#carte-<n> : le navigateur (y compris celui de WhatsApp)
       applique la position « #carte-n ». Le « # » n'est JAMAIS dans la variable du modèle Meta (seul le code court
       y passe), le modèle Meta reste donc inchangé ;
     - événements par carte (« vue » de la page arrivée sur la carte, clic « Je suis intéressé ») : dédupliqués
       par empreinte (IP + navigateur) sur 24 h (réglable), pour ne pas gonfler les chiffres.

  B. Régie publicitaire (carrousel sponsorisé)
     - une campagne de régie (`ad_banners`) de placement « carrousel_wa » est rattachée à une ou plusieurs
       campagnes de carrousel (`carrousel_campagne_ids` côté régie, `regie_id` côté carrousel) ;
     - chaque passage par le lien court d'un carrousel sponsorisé est compté (clic BRUT) ; il est FACTURÉ
       (total_clicks + 1, amount_spent + cost_per_click, daily_stats) seulement si :
         * c'est le premier clic de cet appareil (empreinte IP + navigateur) sur cette carte depuis 24 h ;
         * la campagne de régie est active, commencée, non expirée ;
         * le budget restant couvre le coût du clic (le budget n'est jamais dépassé).
       Les clics au-delà du budget (ou après l'échéance) restent comptés à part (« hors budget ») et les liens
       déjà envoyés continuent de fonctionner : le destinataire n'est jamais pénalisé ;
     - coût par envoi (cost_per_impression) : facturé pour chaque message ACCEPTÉ par Meta (réponse « ok » de
       l'API au moment de l'envoi). Le statut de remise (delivered) arrive plus tard par le webhook et n'est pas
       relié de façon sûre à la campagne : l'acceptation par Meta est le seul repère fiable et immédiat ;
     - à l'envoi, garde-fou : un carrousel rattaché à une campagne de régie épuisée, expirée, en pause ou pas
       encore commencée n'est PAS envoyé.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sawali.carrousel_regie")

PLACEMENT_CARROUSEL = "carrousel_wa"          # placement des campagnes de régie « Carrousel WhatsApp »
TYPES_EVENEMENT = ("vue", "interesse")         # événements comptés par carte sur la page de présentation
DEDUP_HEURES_DEFAUT = 24                       # fenêtre de déduplication par défaut (réglable dans Paramètres)
CHEMIN_PRESENTATION_CAMPAGNE = "/presentation/c/"   # page publique de toutes les cartes d'une campagne


# ---------------------------------------------------------------------------
# Fonctions pures (testées sans base)
# ---------------------------------------------------------------------------
def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _jour() -> str:
    """Date du jour (AAAA-MM-JJ, UTC) : clé des statistiques quotidiennes de la régie."""
    return _maintenant().date().isoformat()


def nouvel_id_public() -> str:
    """Identifiant public d'une campagne : 16 caractères aléatoires (base64 URL), impossible à deviner."""
    return secrets.token_urlsafe(12)


def ip_client(request) -> str:
    """Adresse IP du visiteur : Cloudflare, puis X-Forwarded-For (Render), puis l'adresse de la connexion."""
    if request is None:
        return ""
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else "") or ""


def empreinte(ip: str, agent: str) -> str:
    """Empreinte d'un appareil = hachage SHA-256 de l'IP et du navigateur. On ne garde jamais l'IP en clair :
    l'empreinte suffit à dédupliquer sans conserver de donnée personnelle lisible."""
    brut = f"{(ip or '').strip()}|{(agent or '').strip()[:300]}"
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:32]


def empreinte_requete(request) -> str:
    """Empreinte calculée directement depuis la requête HTTP (IP + en-tête User-Agent)."""
    agent = request.headers.get("user-agent", "") if request is not None else ""
    return empreinte(ip_client(request), agent)


def chemin_presentation(id_public: str, code: str, numero: int) -> str:
    """Adresse relative de la page de présentation positionnée sur la carte `numero` (1 = première carte).
    Le fragment « #carte-n » est ajouté ICI, par le serveur, dans l'en-tête Location : il n'apparaît jamais dans
    la variable du bouton du modèle Meta."""
    return f"{CHEMIN_PRESENTATION_CAMPAGNE}{id_public}?depuis={code}#carte-{max(1, int(numero))}"


def _date(valeur: Optional[str]):
    """« AAAA-MM-JJ » → date, ou None si vide / illisible."""
    from datetime import date
    try:
        return date.fromisoformat((valeur or "").strip()[:10]) if (valeur or "").strip() else None
    except ValueError:
        return None


def motif_non_facturable(b: Dict[str, Any]) -> Optional[str]:
    """Pourquoi une campagne de régie ne peut plus être facturée ni envoyée (None = elle peut l'être).
    Mêmes règles que les bannières : en pause, pas commencée, expirée, budget épuisé."""
    if not b:
        return "campagne de régie introuvable"
    if b.get("placement") != PLACEMENT_CARROUSEL:
        return "cette campagne de régie n'est pas de type « Carrousel WhatsApp »"
    aujourd_hui = _maintenant().date()
    debut, fin = _date(b.get("start_date")), _date(b.get("expiration_date"))
    budget, depense = float(b.get("budget_amount") or 0), float(b.get("amount_spent") or 0)
    if budget > 0 and depense >= budget:
        return "budget épuisé"
    if fin and fin < aujourd_hui:
        return f"campagne expirée le {fin.strftime('%d/%m/%Y')}"
    if debut and debut > aujourd_hui:
        return f"campagne pas encore commencée (début le {debut.strftime('%d/%m/%Y')})"
    if not b.get("active"):
        return "campagne de régie en pause"
    return None


def cout_dans_budget(b: Dict[str, Any], cout: float) -> bool:
    """Le budget restant couvre-t-il ce coût ? Budget à 0 = pas de plafond (comme les bannières)."""
    budget = float(b.get("budget_amount") or 0)
    if budget <= 0:
        return True
    return float(b.get("amount_spent") or 0) + float(cout or 0) <= budget + 1e-9


# ---------------------------------------------------------------------------
# Accès à la base
# ---------------------------------------------------------------------------
async def dedup_heures(db) -> int:
    """Fenêtre de déduplication (heures) réglée dans Paramètres → « 📣 Régie publicitaire — carrousels
    WhatsApp sponsorisés » (clé `carrousel_regie_dedup_heures`), 24 h par défaut, bornée de 1 à 168 h."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "carrousel_regie_dedup_heures": 1}) or {}
    try:
        return max(1, min(168, int(s.get("carrousel_regie_dedup_heures") or DEDUP_HEURES_DEFAUT)))
    except (TypeError, ValueError):
        return DEDUP_HEURES_DEFAUT


async def assurer_id_public(db, campagne_id: str) -> Optional[str]:
    """Identifiant public de la campagne ; créé à la volée pour les campagnes envoyées avant le lot 111."""
    c = await db.carrousel_campagnes.find_one({"id": campagne_id}, {"_id": 0, "id_public": 1})
    if c is None:
        return None
    if c.get("id_public"):
        return c["id_public"]
    # Écriture conditionnelle : si deux clics arrivent en même temps, un seul identifiant est retenu
    await db.carrousel_campagnes.update_one({"id": campagne_id, "id_public": {"$exists": False}},
                                            {"$set": {"id_public": nouvel_id_public()}})
    c = await db.carrousel_campagnes.find_one({"id": campagne_id}, {"_id": 0, "id_public": 1}) or {}
    return c.get("id_public")


async def _deja_vu(db, collection: str, filtre: Dict[str, Any], heures: int) -> bool:
    """Un enregistrement identique existe-t-il depuis moins de `heures` heures ?"""
    depuis = (_maintenant() - timedelta(hours=heures)).isoformat()
    return bool(await db[collection].find_one({**filtre, "cree_le": {"$gte": depuis}}, {"_id": 1}))


async def bump_jour(db, banner_id: str, champs: Dict[str, float]) -> None:
    """Ajoute des valeurs à la ligne du jour de daily_stats (même principe que _bump_daily_stat des bannières,
    en une seule fonction pour plusieurs champs)."""
    from routes.ad_banners import _bump_daily_stat
    for champ, valeur in champs.items():
        if valeur:
            await _bump_daily_stat(db, banner_id, champ, valeur)


async def _pause_si_epuise(db, banner_id: str) -> Optional[dict]:
    """Met la campagne de régie en pause quand son budget est épuisé (comme les bannières) ; renvoie la fiche."""
    from routes.ad_banners import _budget_exhausted
    b = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
    if b and _budget_exhausted(b) and b.get("active"):
        await db.ad_banners.update_one({"id": banner_id}, {"$set": {
            "active": False, "auto_paused_at": _maintenant().isoformat(), "auto_paused_reason": "budget_exhausted"}})
        b["active"] = False
    return b


async def enregistrer_clic(db, *, campagne_id: str, carte_index: int, regie_id: Optional[str],
                           emp: str) -> Dict[str, Any]:
    """Clic sur le bouton d'une carte d'un carrousel SPONSORISÉ (le clic brut du lien court est déjà compté
    par la route). Renvoie {"unique", "facture", "motif"}.
      - unique  : premier clic de cet appareil sur cette carte dans la fenêtre de déduplication ;
      - facture : clic unique ET campagne de régie facturable ET coût dans le budget."""
    if not regie_id:
        return {"unique": False, "facture": False, "motif": "carrousel non sponsorisé"}
    heures = await dedup_heures(db)
    unique = not await _deja_vu(db, "carrousel_clics",
                                {"campagne_id": campagne_id, "carte_index": carte_index, "empreinte": emp,
                                 "unique": True}, heures)
    b = await db.ad_banners.find_one({"id": regie_id}, {"_id": 0})
    motif = None if unique else f"déjà compté pour cet appareil (moins de {heures} h)"
    cpc = float((b or {}).get("cost_per_click") or 0)
    if unique:
        motif = motif_non_facturable(b) or (None if cout_dans_budget(b, cpc) else "budget épuisé")
    facture = unique and motif is None
    # Trace du clic (sans IP en clair) : sert à la déduplication et au détail du rapport
    await db.carrousel_clics.insert_one({
        "campagne_id": campagne_id, "carte_index": carte_index, "empreinte": emp, "regie_id": regie_id,
        "unique": unique, "facture": facture, "motif": motif, "montant": cpc if facture else 0.0,
        "jour": _jour(), "cree_le": _maintenant().isoformat()})
    if not b:
        return {"unique": unique, "facture": False, "motif": motif}
    # Compteurs de la campagne de régie : clics bruts toujours ; clics facturés et montant si facturé
    inc: Dict[str, Any] = {"carrousel_clics_bruts": 1}
    jour: Dict[str, float] = {"clics_bruts": 1}
    if facture:
        inc.update({"total_clicks": 1, "amount_spent": cpc})
        jour.update({"clicks": 1, "spent": cpc})
        await db.carrousel_liens.update_one({"campagne_id": campagne_id, "carte_index": carte_index},
                                            {"$inc": {"clics_factures": 1}})
    elif unique:
        inc["carrousel_clics_hors_budget"] = 1          # clic qui aurait été facturé : budget ou dates dépassés
        jour["clics_hors_budget"] = 1
    await db.ad_banners.update_one({"id": regie_id}, {"$inc": inc, "$set": {"updated_at": _maintenant().isoformat()}})
    await bump_jour(db, regie_id, jour)
    frais = await _pause_si_epuise(db, regie_id) if facture else None
    if frais:
        await diffuser(frais, "click")
    return {"unique": unique, "facture": facture, "motif": motif}


async def enregistrer_envoi(db, regie_id: Optional[str]) -> bool:
    """Message de carrousel ACCEPTÉ par Meta pour une campagne sponsorisée : compté comme un envoi
    (total_impressions) et facturé au coût par envoi (cost_per_impression) tant que le budget le permet."""
    if not regie_id:
        return False
    b = await db.ad_banners.find_one({"id": regie_id}, {"_id": 0})
    if not b:
        return False
    cpi = float(b.get("cost_per_impression") or 0)
    facture = cpi > 0 and cout_dans_budget(b, cpi)
    inc: Dict[str, Any] = {"total_impressions": 1, "carrousel_envois": 1}
    jour: Dict[str, float] = {"impressions": 1}
    if facture:
        inc["amount_spent"] = cpi
        jour["spent"] = cpi
    await db.ad_banners.update_one({"id": regie_id}, {"$inc": inc, "$set": {"updated_at": _maintenant().isoformat()}})
    await bump_jour(db, regie_id, jour)
    frais = await _pause_si_epuise(db, regie_id)
    if frais:
        await diffuser(frais, "impression")
    return facture


async def enregistrer_evenement(db, *, campagne: Dict[str, Any], carte_index: int, type_evt: str, emp: str) -> bool:
    """« vue » ou « interesse » sur une carte de la page de présentation. Un même appareil n'est compté
    qu'une fois par carte et par type dans la fenêtre de déduplication. Renvoie True si l'événement est compté."""
    heures = await dedup_heures(db)
    cle = {"campagne_id": campagne["id"], "carte_index": carte_index, "type": type_evt, "empreinte": emp}
    if await _deja_vu(db, "carrousel_evenements", cle, heures):
        return False
    await db.carrousel_evenements.insert_one({**cle, "jour": _jour(), "cree_le": _maintenant().isoformat()})
    champ = "vues" if type_evt == "vue" else "interesses"
    await db.carrousel_liens.update_one({"campagne_id": campagne["id"], "carte_index": carte_index},
                                        {"$inc": {champ: 1}})
    # Carrousel sponsorisé : chiffres repris dans le rapport de l'annonceur (totaux et ligne du jour)
    if campagne.get("regie_id"):
        await db.ad_banners.update_one({"id": campagne["regie_id"]}, {"$inc": {f"carrousel_{champ}": 1}})
        await bump_jour(db, campagne["regie_id"], {champ: 1})
    return True


async def diffuser(b: Dict[str, Any], evenement: str) -> None:
    """Panneau « temps réel » de la régie : le clic ou l'envoi du carrousel est diffusé comme ceux des bannières."""
    try:
        from routes import ad_banners
        await ad_banners.diffuser_live({
            "event": evenement, "banner_id": b.get("id"), "name": b.get("name"),
            "advertiser_name": b.get("advertiser_name") or "", "variant": "a", "source": PLACEMENT_CARROUSEL,
            "total_impressions": int(b.get("total_impressions") or 0), "total_clicks": int(b.get("total_clicks") or 0),
            "total_impressions_a": int(b.get("total_impressions") or 0), "total_impressions_b": 0,
            "total_clicks_a": int(b.get("total_clicks") or 0), "total_clicks_b": 0,
            "amount_spent": float(b.get("amount_spent") or 0), "ts": _maintenant().isoformat()})
    except Exception as exc:  # noqa: BLE001 — la diffusion est un plus, jamais bloquante
        logger.debug("diffusion temps réel du carrousel impossible : %s", exc)


async def regie_envoyable(db, regie_id: str, nb_destinataires: int) -> Dict[str, Any]:
    """Garde-fou à l'envoi d'un carrousel sponsorisé. Lève ValueError (message en français) si la campagne de
    régie ne permet pas l'envoi ; sinon renvoie sa fiche."""
    b = await db.ad_banners.find_one({"id": regie_id}, {"_id": 0})
    motif = motif_non_facturable(b)
    if motif:
        raise ValueError(f"Carrousel sponsorisé non envoyable : {motif}. Renouvelez ou modifiez la campagne dans "
                         "la Régie publicitaire.")
    cpi = float(b.get("cost_per_impression") or 0)
    if cpi > 0 and not cout_dans_budget(b, cpi * nb_destinataires):
        reste = max(0.0, float(b.get("budget_amount") or 0) - float(b.get("amount_spent") or 0))
        raise ValueError(f"Carrousel sponsorisé non envoyable : {nb_destinataires} envoi(s) à {cpi:g} "
                         f"{b.get('currency') or 'XOF'} dépassent le budget restant ({reste:g}).")
    return b


async def lier_campagnes(db, banner_id: str, campagne_ids: List[str]) -> List[str]:
    """Rattache à la campagne de régie la liste COMPLÈTE de ses campagnes de carrousel (administration SAWALI) :
    les campagnes retirées perdent leur `regie_id`, une campagne déjà rattachée à une autre régie change de régie."""
    voulues = [c for c in dict.fromkeys(campagne_ids or []) if c]
    existantes = [c["id"] async for c in db.carrousel_campagnes.find(
        {"id": {"$in": voulues}, "perimetre": "admin"}, {"_id": 0, "id": 1})]
    # Retrait des campagnes qui ne sont plus dans la liste
    await db.carrousel_campagnes.update_many({"regie_id": banner_id, "id": {"$nin": existantes}},
                                             {"$unset": {"regie_id": ""}})
    if existantes:
        # Une campagne passe d'une autre régie à celle-ci : on la retire de la liste de l'ancienne
        await db.ad_banners.update_many({"id": {"$ne": banner_id}, "carrousel_campagne_ids": {"$in": existantes}},
                                        {"$pull": {"carrousel_campagne_ids": {"$in": existantes}}})
        await db.carrousel_campagnes.update_many({"id": {"$in": existantes}}, {"$set": {"regie_id": banner_id}})
    await db.ad_banners.update_one({"id": banner_id}, {"$set": {"carrousel_campagne_ids": existantes}})
    return existantes


async def apercu_si_vide(db, regie_id: str, campagne_id: str) -> None:
    """Campagne de régie sans image : on prend la photo de la 1re carte du carrousel rattaché (aperçu de la liste
    de la régie et du rapport de l'annonceur)."""
    c = await db.carrousel_campagnes.find_one({"id": campagne_id}, {"_id": 0, "cartes": 1}) or {}
    image = ((c.get("cartes") or [{}])[0] or {}).get("image_url") or ""
    if image:
        await db.ad_banners.update_one({"id": regie_id, "image_url": {"$in": ["", None]}},
                                       {"$set": {"image_url": image, "media_kind": "image"}})


async def lier_une(db, campagne_id: str, regie_id: Optional[str]) -> None:
    """Rattache (ou détache, regie_id vide) UNE campagne de carrousel, depuis l'écran du carrousel."""
    await db.ad_banners.update_many({"carrousel_campagne_ids": campagne_id},
                                    {"$pull": {"carrousel_campagne_ids": campagne_id}})
    if regie_id:
        await db.carrousel_campagnes.update_one({"id": campagne_id}, {"$set": {"regie_id": regie_id}})
        await db.ad_banners.update_one({"id": regie_id}, {"$addToSet": {"carrousel_campagne_ids": campagne_id}})
        await apercu_si_vide(db, regie_id, campagne_id)
    else:
        await db.carrousel_campagnes.update_one({"id": campagne_id}, {"$unset": {"regie_id": ""}})


async def stats_cartes(db, campagne: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Chiffres de chaque carte d'une campagne : clics bruts, clics facturés, vues, « Je suis intéressé »."""
    liens = {x.get("carte_index"): x async for x in db.carrousel_liens.find(
        {"campagne_id": campagne["id"]}, {"_id": 0, "carte_index": 1, "clics": 1, "clics_factures": 1,
                                          "vues": 1, "interesses": 1})}
    lignes = []
    for i, c in enumerate(campagne.get("cartes") or []):
        x = liens.get(i) or {}
        lignes.append({"n": i + 1, "titre": c.get("titre") or "", "clics": int(x.get("clics") or 0),
                       "clics_factures": int(x.get("clics_factures") or 0), "vues": int(x.get("vues") or 0),
                       "interesses": int(x.get("interesses") or 0)})
    return lignes


async def rapport_carrousel(db, b: Dict[str, Any]) -> Dict[str, Any]:
    """Partie « Carrousel WhatsApp » du rapport public de l'annonceur : envois, clics (bruts, facturables, hors
    budget), vues, « Je suis intéressé », détail par campagne et par carte. Aucune donnée de destinataire."""
    ids = list(b.get("carrousel_campagne_ids") or [])
    campagnes = await db.carrousel_campagnes.find(
        {"$or": [{"regie_id": b.get("id")}, {"id": {"$in": ids}}]},
        {"_id": 0, "id": 1, "cree_le": 1, "message": 1, "cartes": 1, "compte": 1}).sort("cree_le", -1).to_list(50)
    detail, envois = [], 0
    for c in campagnes:
        cartes = await stats_cartes(db, c)
        envoyes = int((c.get("compte") or {}).get("envoyes") or 0)
        envois += envoyes
        detail.append({"date": c.get("cree_le"), "message": (c.get("message") or "")[:120],
                       "envois": envoyes, "cartes": cartes})
    return {
        "envois": envois,
        "clics_bruts": int(b.get("carrousel_clics_bruts") or 0),
        "clics_facturables": int(b.get("total_clicks") or 0),
        "clics_hors_budget": int(b.get("carrousel_clics_hors_budget") or 0),
        "vues": int(b.get("carrousel_vues") or 0),
        "interesses": int(b.get("carrousel_interesses") or 0),
        "cost_per_click": float(b.get("cost_per_click") or 0),
        "cost_per_impression": float(b.get("cost_per_impression") or 0),
        "campagnes": detail,
    }
