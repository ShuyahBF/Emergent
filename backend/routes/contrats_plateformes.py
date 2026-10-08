# contrats_plateformes.py — Lot 81 : CONTRAT de chaque plateforme cliente (ALBARKA…) suivi dans SAWALI.
#
# Demande du propriétaire (08/10/2026) : « ALBARKA dispose d'un contrat d'un certain montant qui comprend les prestations
# (développement, maintenance, formation…) et les services (hébergement, messageries, coûts META/WA…). Tout commence au
# 15 octobre 2026. Dans admin/plateformes-temps-reel je veux suivre ses informations (n° de contrat, montant, historique
# des paiements, montant dû…). Les paramètres du contrat sont définis dans SAWALI comme client/tenant. 5 jours avant
# l'échéance le bandeau en haut de la page (chez le DG) est orange ; 5 jours après, une barre rouge lui rappelle le
# renouvellement, sinon certains services pourraient être suspendus. »
#
# En résumé (pour un développeur WinDev) :
#   - la plateforme (émetteur « Transmission WA Universelle », ex. code « albarka ») est RATTACHÉE à un client/tenant de
#     SAWALI (champ `client_id` de db.liluvine_emetteurs) ;
#   - le contrat vit sur la fiche de ce client (db.users), champs existants : contract_number, contract_amount,
#     contract_currency, contract_signed_at ; champs ajoutés : contract_start_at, contract_end_at, contract_lignes
#     (prestations / services : libellé + montant), contract_alerte_avant_jours (5), contract_alerte_apres_jours (5) ;
#   - les paiements sont ceux de l'historique existant (db.tenant_payments, POST /admin/clients/{id}/payments) ;
#     montant payé = paiements datés depuis le début du contrat ; montant dû = montant du contrat − payé ;
#   - ÉTAT (logique pure, testée) : « ok », « bientot » (orange, à partir de J−5), « expire » (orange, échéance passée
#     depuis moins de 5 jours), « critique » (rouge, à partir de J+5) [lot 81, remplacé ci-dessous] ;
#   - Lot 82 (08/10/2026) : « Le bandeau ne s'affiche qu'à ± 5 jours de la date d'expiration ; en dehors, pas de
#     bandeau. » → orange de J−5 à J, rouge de J+1 à J+5, puis « echu » SANS couleur (plus de bandeau) ;
#     « Services pouvant être suspendus : je coche ou décoche (CR, WA…) ; tous ceux qui sont cochés sont suspendus
#     automatiquement » → liste cochée sur le contrat (contract_services_suspendus), envoyée à la plateforme, qui
#     bloque ces services dès que le contrat est échu (au-delà de J+5) et les rouvre dès que l'échéance est repoussée.
#   - la plateforme lit SON état : POST /api/webhook/plateforme-contrat, signé comme la transmission universelle
#     (X-Emetteur, X-Timestamp, X-Signature = HMAC-SHA256(clé, "<timestamp>.<corps>")) : aucune nouvelle clé.
from __future__ import annotations

import hashlib
import json
import hmac
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request  # au niveau du module : l'annotation de la route doit être résolue (from __future__)

AVANT_DEFAUT = 5        # jours avant l'échéance : bandeau orange
APRES_DEFAUT = 5        # jours après l'échéance : barre rouge (puis plus de bandeau, services cochés suspendus)
TYPES_LIGNE = {"prestation": "Prestation", "service": "Service"}
LIBELLES_ETAT = {
    "aucun": "Pas de contrat", "a_venir": "Pas encore commencé", "ok": "À jour",
    "bientot": "Échéance proche", "expire": "Renouvellement urgent", "echu": "Contrat échu",
}

# Lot 82 — catalogue des services qu'une plateforme peut suspendre (cases à cocher sur le contrat).
# Le CODE est partagé avec la plateforme (ALBARKA…) qui sait quelles fonctions bloquer pour chacun.
SERVICES_SUSPENDABLES = [
    {"code": "wa", "libelle": "WhatsApp (envois)", "description": "Factures, documents, notifications et messages envoyés par WhatsApp (les codes de connexion restent envoyés)"},
    {"code": "email", "libelle": "E-mails (envois)", "description": "Envois d'e-mails aux clients et au personnel (les codes de connexion restent envoyés)"},
    {"code": "cr", "libelle": "Comptes rendus / rapports clients", "description": "Génération, modèles et envoi des rapports clients"},
    {"code": "conversations_wa", "libelle": "Conversations WhatsApp", "description": "Centre de conversations (les messages reçus restent enregistrés)"},
    {"code": "ia", "libelle": "Analyse IA (OCR) des pièces", "description": "Lecture automatique des pièces et relances d'analyse"},
    {"code": "espace_client", "libelle": "Espace client", "description": "Dépôts et consultation des documents de l'espace client"},
    {"code": "formulaires", "libelle": "Formulaires", "description": "Formulaires en ligne, envois et réponses"},
    {"code": "pispi", "libelle": "Encaissement PI-SPI", "description": "QR codes et réglages de paiement instantané"},
    {"code": "modeles", "libelle": "Documents & modèles", "description": "Courriers, attestations et documents à variables"},
    {"code": "paie", "libelle": "RH & Paie", "description": "Bulletins, livre et tableau de paie"},
    {"code": "compta", "libelle": "Comptabilité OHADA", "description": "Plan comptable, journaux et états"},
    {"code": "chat", "libelle": "Chat interne", "description": "Messagerie instantanée du personnel"},
    {"code": "push", "libelle": "Notifications push", "description": "Notifications sur les navigateurs et téléphones"},
]
CODES_SERVICES = [s["code"] for s in SERVICES_SUSPENDABLES]


def _jour(valeur: Any) -> Optional[date]:
    """« 2026-10-15 » (ou ISO complet) → date ; None si vide ou illisible."""
    try:
        return date.fromisoformat(str(valeur or "")[:10])
    except ValueError:
        return None


# =====================================================================================
# Logique pure (testée : tests/test_lot81_contrats_plateformes.py)
# =====================================================================================

def etat_contrat(debut: Any, fin: Any, aujourdhui: date, avant: int = AVANT_DEFAUT,
                 apres: int = APRES_DEFAUT) -> Dict[str, Any]:
    """État du contrat à une date : {niveau, couleur, jours_restants, libelle}.

    niveau : « aucun » (pas d'échéance), « a_venir » (avant le début), « ok », « bientot » (orange, de J−avant au jour
    J), « expire » (rouge, de J+1 à J+apres), « echu » (au-delà de J+apres : PAS de couleur, donc plus de bandeau ;
    les services cochés sont suspendus). Lot 82 : bandeau seulement à ± avant/apres jours de l'échéance."""
    d_fin = _jour(fin)
    if not d_fin:
        return {"niveau": "aucun", "couleur": None, "jours_restants": None, "libelle": LIBELLES_ETAT["aucun"]}
    d_debut = _jour(debut)
    restants = (d_fin - aujourdhui).days
    if d_debut and aujourdhui < d_debut:
        niveau = "a_venir"
    elif restants > max(0, avant):
        niveau = "ok"
    elif restants >= 0:
        niveau = "bientot"
    elif -restants <= max(1, apres):
        niveau = "expire"
    else:
        niveau = "echu"
    couleur = {"bientot": "orange", "expire": "rouge"}.get(niveau)
    return {"niveau": niveau, "couleur": couleur, "jours_restants": restants, "libelle": LIBELLES_ETAT[niveau]}


def date_suspension(fin: Any, apres: int = APRES_DEFAUT) -> Optional[str]:
    """Lot 82 : premier jour où les services cochés sont suspendus (lendemain de J+apres) ; None sans échéance."""
    d_fin = _jour(fin)
    return (d_fin + timedelta(days=max(1, apres) + 1)).isoformat() if d_fin else None


def nettoyer_catalogue(services: Any) -> List[Dict[str, str]]:
    """Lot 82.5 : services qu'une plateforme DÉCLARE savoir suspendre (chacune a les siens : ALBARKA, Ster…).
    Liste de {code, libelle, description} validée ; ValueError avec message clair sinon."""
    import re
    if not isinstance(services, list) or len(services) > 40:
        raise ValueError("services : liste de 40 éléments au plus attendue")
    propres, vus = [], set()
    for i, sv in enumerate(services, 1):
        if not isinstance(sv, dict):
            raise ValueError(f"service {i} illisible")
        code = str(sv.get("code") or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{1,40}", code):
            raise ValueError(f"service {i} : code « {code} » invalide (a-z, 0-9, _)")
        if code in vus:
            continue
        vus.add(code)
        propres.append({"code": code, "libelle": str(sv.get("libelle") or code).strip()[:80],
                        "description": str(sv.get("description") or "").strip()[:200]})
    return propres


def catalogue_de(emetteur: Dict[str, Any]) -> Optional[List[Dict[str, str]]]:
    """Lot 82.5 : catalogue déclaré par la plateforme, ou None si elle ne l'a pas encore déclaré."""
    cat = emetteur.get("services_catalogue")
    return cat if isinstance(cat, list) and cat else None


def nettoyer_services(services: Any, codes_permis: Optional[List[str]] = None) -> List[str]:
    """Lot 82 : codes cochés, connus du catalogue, sans doublon, dans l'ordre du catalogue ; ValueError sinon.
    Lot 82.5 : `codes_permis` = codes du catalogue de LA plateforme (défaut : catalogue générique)."""
    ordre = codes_permis if codes_permis is not None else CODES_SERVICES
    if services in (None, ""):
        return []
    if not isinstance(services, list):
        raise ValueError("services suspendus : liste de codes attendue")
    codes = {str(c or "").strip().lower() for c in services}
    inconnus = sorted(codes - set(ordre) - {""})
    if inconnus:
        raise ValueError(f"service(s) inconnu(s) : {', '.join(inconnus)}")
    return [c for c in ordre if c in codes]


def services_suspendus(etat: Dict[str, Any], coches: List[str]) -> List[str]:
    """Lot 82 : services à bloquer MAINTENANT — les cochés, seulement quand le contrat est échu (au-delà de J+apres)."""
    return list(coches or []) if (etat or {}).get("niveau") == "echu" else []


def nettoyer_lignes(lignes: Any) -> List[Dict[str, Any]]:
    """Lignes du contrat (prestations / services) validées ; ValueError avec message clair."""
    if lignes in (None, ""):
        return []
    if not isinstance(lignes, list) or len(lignes) > 40:
        raise ValueError("40 lignes au plus (prestations et services)")
    propres = []
    for i, l in enumerate(lignes, 1):
        if not isinstance(l, dict):
            raise ValueError(f"ligne {i} illisible")
        libelle = str(l.get("libelle") or "").strip()[:160]
        if not libelle:
            continue
        type_ = str(l.get("type") or "prestation").strip().lower()
        if type_ not in TYPES_LIGNE:
            raise ValueError(f"ligne {i} : type « {type_} » inconnu (prestation ou service)")
        try:
            montant = round(float(l.get("montant") or 0), 2)
        except (TypeError, ValueError):
            raise ValueError(f"ligne {i} : montant invalide")
        if montant < 0:
            raise ValueError(f"ligne {i} : montant négatif")
        propres.append({"type": type_, "libelle": libelle, "montant": montant})
    return propres


def resume_financier(montant_contrat: Any, lignes: List[Dict[str, Any]], paiements: List[Dict[str, Any]],
                     debut: Any) -> Dict[str, Any]:
    """Montant du contrat (saisi, sinon somme des lignes), payé depuis le début du contrat, dû, et détail par type."""
    try:
        montant = float(montant_contrat) if montant_contrat not in (None, "") else None
    except (TypeError, ValueError):
        montant = None
    somme_lignes = round(sum(l.get("montant") or 0 for l in lignes), 2)
    if montant is None:
        montant = somme_lignes
    d_debut = _jour(debut)
    retenus = [p for p in paiements if not d_debut or (_jour(p.get("payment_date")) or date.min) >= d_debut]
    paye = round(sum(float(p.get("amount_paid") or 0) for p in retenus), 2)
    return {
        "montant": round(montant, 2), "somme_lignes": somme_lignes, "paye": paye,
        "du": round(max(0.0, montant - paye), 2),
        "prestations": round(sum(l["montant"] for l in lignes if l["type"] == "prestation"), 2),
        "services": round(sum(l["montant"] for l in lignes if l["type"] == "service"), 2),
        "paiements_retenus": len(retenus),
    }


def signature_valide(secret: str, timestamp: str, corps: bytes, signature: str, maintenant: datetime) -> bool:
    """Même règle que la transmission universelle : fenêtre de ±300 s puis HMAC-SHA256(clé, "<ts>.<corps>")."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(maintenant.timestamp()) - ts) > 300 or not secret:
        return False
    attendu = hmac.new(secret.encode(), f"{ts}.{corps.decode('utf-8', errors='replace')}".encode(),
                       hashlib.sha256).hexdigest()
    return hmac.compare_digest(attendu, signature or "")


# =====================================================================================
# Routes
# =====================================================================================

# Lot 82.4 : champs du contrat. Ils sont désormais rangés PAR PLATEFORME (db.liluvine_emetteurs.contrat) et non plus
# sur la fiche du client : deux plateformes rattachées au même client (ex. ALBARKA et Ster) s'écrasaient l'une
# l'autre. La fiche du client ne sert plus que de valeur de départ (anciens contrats) et pour les paiements.
CLES_CONTRAT = ("contract_number", "contract_amount", "contract_currency", "contract_signed_at", "contract_start_at",
                "contract_end_at", "contract_lignes", "contract_alerte_avant_jours", "contract_alerte_apres_jours",
                "contract_services_suspendus")


def contrat_de(emetteur: Dict[str, Any], client: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Champs du contrat d'une plateforme : ceux rangés sur la plateforme, sinon (ancien contrat) ceux de la fiche client."""
    propre = emetteur.get("contrat")
    if isinstance(propre, dict):
        return propre
    return {k: (client or {}).get(k) for k in CLES_CONTRAT if (client or {}).get(k) is not None}


CHAMPS_CLIENT = {"_id": 0, "id": 1, "company": 1, "full_name": 1, "email": 1, "client_code": 1,
                 "contract_number": 1, "contract_amount": 1, "contract_currency": 1, "contract_signed_at": 1,
                 "contract_start_at": 1, "contract_end_at": 1, "contract_lignes": 1,
                 "contract_alerte_avant_jours": 1, "contract_alerte_apres_jours": 1, "last_payment_at": 1,
                 "contract_services_suspendus": 1}


def setup_contrats_plateformes_routes(*, db, api, get_current_user) -> None:
    """Branche les routes du lot 81 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException

    def _admin(user: dict) -> None:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    async def _contrat(emetteur: Dict[str, Any], avec_paiements: bool = True) -> Dict[str, Any]:
        """Vue complète du contrat d'une plateforme (client rattaché, état, finances, historique des paiements)."""
        base = {"code": emetteur.get("code"), "nom": emetteur.get("nom") or emetteur.get("code"),
                "client_id": emetteur.get("client_id"),
                # Lot 82.5 : services que CETTE plateforme sait suspendre (déclarés par elle ; None = pas encore)
                "services_catalogue": catalogue_de(emetteur), "services_declares_le": emetteur.get("services_declares_le")}
        client = await db.users.find_one({"id": emetteur.get("client_id")}, CHAMPS_CLIENT) \
            if emetteur.get("client_id") else None
        if not client:
            return {**base, "client": None, "etat": etat_contrat(None, None, date.today())}
        paiements = [p async for p in db.tenant_payments.find({"tenant_id": client["id"]}, {"_id": 0})
                     .sort("payment_date", -1).limit(500)]
        k = contrat_de(emetteur, client)   # lot 82.4 : contrat propre à la plateforme
        lignes = k.get("contract_lignes") or []
        # 0 est une valeur permise (alerte le jour même) : seul « absent » prend la valeur par défaut
        avant = int(k["contract_alerte_avant_jours"]) if k.get("contract_alerte_avant_jours") is not None else AVANT_DEFAUT
        apres = int(k["contract_alerte_apres_jours"]) if k.get("contract_alerte_apres_jours") is not None else APRES_DEFAUT
        etat = etat_contrat(k.get("contract_start_at"), k.get("contract_end_at"), date.today(), avant, apres)
        coches = k.get("contract_services_suspendus") or []
        return {
            **base,
            "client": {"id": client["id"], "nom": client.get("company") or client.get("full_name") or client.get("email"),
                       "code": client.get("client_code")},
            "numero": k.get("contract_number"), "devise": k.get("contract_currency") or "XOF",
            "signe_le": k.get("contract_signed_at"), "debut": k.get("contract_start_at"),
            "fin": k.get("contract_end_at"), "lignes": lignes,
            "alerte_avant_jours": avant, "alerte_apres_jours": apres,
            "finances": resume_financier(k.get("contract_amount"), lignes, paiements, k.get("contract_start_at")),
            "etat": etat,
            # Lot 82 : services cochés, ceux suspendus aujourd'hui et la date de début de suspension
            "services_a_suspendre": coches, "services_suspendus": services_suspendus(etat, coches),
            "suspension_le": date_suspension(k.get("contract_end_at"), apres) if coches else None,
            "paiements": paiements if avec_paiements else None,
        }

    @api.get("/admin/plateformes/contrats", tags=["Plateformes — contrats"])
    async def lister(user: dict = Depends(get_current_user)):
        """Contrat de chaque plateforme (page « Temps réel » et rubrique des Paramètres)."""
        _admin(user)
        sortie = []
        async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "secret": 0}).sort("nom", 1):
            sortie.append(await _contrat(e))
        return {"contrats": sortie, "libelles_etat": LIBELLES_ETAT, "services_catalogue": SERVICES_SUSPENDABLES}

    @api.put("/admin/plateformes/{code}/contrat", tags=["Plateformes — contrats"])
    async def enregistrer(code: str, request: Request, user: dict = Depends(get_current_user)):
        """Rattache la plateforme à un client SAWALI et enregistre les paramètres du contrat sur la fiche du client."""
        _admin(user)
        emetteur = await db.liluvine_emetteurs.find_one({"code": code.strip().lower()}, {"_id": 0, "secret": 0})
        if not emetteur:
            raise HTTPException(status_code=404, detail="Plateforme inconnue")
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        client_id = str(corps.get("client_id") or emetteur.get("client_id") or "").strip()
        if not client_id or not await db.users.find_one({"id": client_id}, {"_id": 1}):
            raise HTTPException(status_code=422, detail="Choisissez le client SAWALI de cette plateforme")
        champs: Dict[str, Any] = {}
        for cle, champ in (("numero", "contract_number"), ("devise", "contract_currency")):
            if cle in corps:
                champs[champ] = (str(corps.get(cle) or "").strip()[:60] or None)
        if champs.get("contract_currency"):
            champs["contract_currency"] = champs["contract_currency"].upper()
        for cle, champ in (("debut", "contract_start_at"), ("fin", "contract_end_at"), ("signe_le", "contract_signed_at")):
            if cle in corps:
                valeur = corps.get(cle)
                if valeur and not _jour(valeur):
                    raise HTTPException(status_code=422, detail=f"Date « {cle} » invalide (AAAA-MM-JJ)")
                champs[champ] = str(valeur)[:10] if valeur else None
        # Cohérence des dates, y compris avec celles déjà enregistrées sur la fiche du client
        client_doc = await db.users.find_one({"id": client_id}, {"_id": 0, **{c: 1 for c in CLES_CONTRAT}}) or {}
        existant = contrat_de(emetteur, client_doc)   # lot 82.4 : contrat de CETTE plateforme
        debut_final = champs.get("contract_start_at", existant.get("contract_start_at"))
        fin_finale = champs.get("contract_end_at", existant.get("contract_end_at"))
        if _jour(debut_final) and _jour(fin_finale) and _jour(fin_finale) <= _jour(debut_final):
            raise HTTPException(status_code=422, detail="L'échéance doit être après le début du contrat")
        if "lignes" in corps:
            try:
                champs["contract_lignes"] = nettoyer_lignes(corps.get("lignes"))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
        if "montant" in corps:
            m = corps.get("montant")
            try:
                champs["contract_amount"] = round(float(m), 2) if m not in (None, "") else None
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="Montant du contrat invalide")
        for cle, champ in (("alerte_avant_jours", "contract_alerte_avant_jours"),
                           ("alerte_apres_jours", "contract_alerte_apres_jours")):
            if cle in corps:
                try:
                    n = int(corps.get(cle))
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail="Nombre de jours d'alerte invalide")
                if not 0 <= n <= 90:
                    raise HTTPException(status_code=422, detail="Jours d'alerte : 0 à 90")
                champs[champ] = n
        if "services_suspendus" in corps:   # lot 82 : cases cochées
            try:
                cat = catalogue_de(emetteur) or SERVICES_SUSPENDABLES   # lot 82.5 : catalogue de la plateforme
                champs["contract_services_suspendus"] = nettoyer_services(corps.get("services_suspendus"),
                                                                          [x["code"] for x in cat])
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
        maintenant = datetime.now(timezone.utc).isoformat()
        # Lot 82.4 : enregistré sur la PLATEFORME (jamais sur la fiche client, partagée par d'autres plateformes)
        contrat = {**existant, **champs, "maj_le": maintenant}
        await db.liluvine_emetteurs.update_one({"code": emetteur["code"]},
                                               {"$set": {"client_id": client_id, "contrat": contrat}})
        emetteur["client_id"] = client_id
        emetteur["contrat"] = contrat
        return await _contrat(emetteur)

    @api.post("/webhook/plateforme-contrat", tags=["Plateformes — contrats"])
    async def etat_pour_la_plateforme(request: Request):
        """La plateforme (ALBARKA…) lit l'état de SON contrat — requête signée avec sa clé d'émetteur."""
        code = (request.headers.get("X-Emetteur") or "").strip().lower()
        emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0}) if code else None
        if not emetteur or not emetteur.get("actif", True):
            raise HTTPException(status_code=401, detail="Émetteur inconnu ou désactivé")
        corps = await request.body()
        if not signature_valide(emetteur.get("secret") or "", request.headers.get("X-Timestamp") or "", corps,
                                request.headers.get("X-Signature") or "", datetime.now(timezone.utc)):
            raise HTTPException(status_code=401, detail="Signature refusée")
        # Lot 82.5 : la plateforme déclare au passage les services qu'ELLE sait suspendre (corps {"services": [...]})
        try:
            donnees = json.loads(corps.decode("utf-8") or "{}") if corps else {}
        except ValueError:
            donnees = {}
        if isinstance(donnees, dict) and "services" in donnees:
            try:
                catalogue = nettoyer_catalogue(donnees.get("services"))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            if catalogue != emetteur.get("services_catalogue"):
                maintenant = datetime.now(timezone.utc).isoformat()
                await db.liluvine_emetteurs.update_one({"code": emetteur["code"]}, {"$set": {
                    "services_catalogue": catalogue, "services_declares_le": maintenant}})
                emetteur["services_catalogue"] = catalogue
        c = await _contrat(emetteur, avec_paiements=False)
        f = c.get("finances") or {}
        # Ce que la plateforme affiche à son DG : jamais les autres clients, ni l'historique détaillé
        return {"numero": c.get("numero"), "debut": c.get("debut"), "fin": c.get("fin"), "devise": c.get("devise"),
                "montant": f.get("montant"), "paye": f.get("paye"), "du": f.get("du"), "etat": c.get("etat"),
                "alerte_avant_jours": c.get("alerte_avant_jours"), "alerte_apres_jours": c.get("alerte_apres_jours"),
                # Lot 82 : la plateforme bloque « services_suspendus » (vide tant que le contrat n'est pas échu) et
                # annonce « services_a_suspendre » à partir de « suspension_le » dans la barre rouge
                "services_a_suspendre": c.get("services_a_suspendre") or [],
                "services_suspendus": c.get("services_suspendus") or [],
                "suspension_le": c.get("suspension_le"),
                "services_catalogue": [{"code": x["code"], "libelle": x["libelle"]}
                                       for x in (catalogue_de(emetteur) or SERVICES_SUSPENDABLES)]}
