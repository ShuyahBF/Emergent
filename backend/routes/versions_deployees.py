# versions_deployees.py — Lot 65 : versions déployées de chaque solution et postes où elles tournent.
#
# Deux sources :
#
# 1. LOGICIELS DE BUREAU (Loois.exe, LooisSyncService…) : chaque programme envoie toutes les
#    5 minutes un « signal de présence » :
#      POST /api/presence-logiciel
#      corps : {"application": "Loois", "version": "1.2610.610.44", "deploye_le": "<ISO>",
#               "machine": "POSTE-ACCUEIL", "utilisateur": "secretariat", "site": "Clinique X",
#               "systeme": "Windows 10.0.19045", "demarre_le": "<ISO>"}
#      en-tête facultatif : X-Cle-Loois = CLÉ CLIENT Loois (lot 68.1, une par client) ou, à défaut, la clé
#      commune LOOIS_SUPPORT_CLE (variable d'environnement Render, toujours acceptée ici pour les anciens postes).
#      Un signal signé par une clé client est affiché « vérifié · <client> » (champ « verifie_client »).
#    La clé est FACULTATIVE (le service Windows tourne sous le compte Système, qui n'a pas la clé
#    enregistrée par l'utilisateur) : un signal sans clé est accepté mais marqué « non vérifié ».
#    Une seule fiche par (application, machine, composant) : la collection ne grossit pas avec le
#    temps ; au-delà de MAX_POSTES fiches, un poste INCONNU est refusé (protection contre l'abus).
#    « En ligne » = signal reçu depuis moins de EN_LIGNE_MINUTES minutes.
#
# 2. PLATEFORMES WEB (Ster, adLyn, beAuthentik, ALBARKA…) : la version arrive avec leurs
#    statistiques internes (champs facultatifs « version » et « deploye_le » de la réponse, voir
#    stats_plateformes.py). SAWALI lui-même : backend/lot.py + compteur de déploiements.
#
#   GET /api/admin/versions-deployees  (administrateur) → {sawali, plateformes, logiciels}
#
# Lot 66 — INVENTAIRE DES POSTES (demande du propriétaire, 06/10/2026) :
#   - le signal peut porter un objet facultatif « inventaire » (système, processeur, mémoire, disques,
#     cartes réseau avec MAC / IP, tâches en cours…), envoyé par Loois au premier signal puis au plus
#     toutes les 30 minutes. Il est nettoyé (types simples, textes et listes bornés), refusé s'il dépasse
#     MAX_INVENTAIRE_OCTETS, et gardé (le dernier reçu) dans la collection `inventaires_postes`, une fiche
#     par machine : un signal léger ne l'efface pas ;
#   - à chaque inventaire, la fiche de l'équipement est créée ou complétée dans « Parc informatique »
#     (collection `parc_equipements`, lot 47) : clé = nom de la machine (puis adresse MAC). Seuls les
#     champs AUTOMATIQUES sont écrits (nom d'hôte, système, fabricant, modèle, MAC, IP, site), et
#     seulement s'ils sont vides ou encore égaux à la valeur que Loois y avait mise : une saisie à la main
#     (client, lieu, notes, utilisateur…) n'est JAMAIS écrasée. Une fiche créée ainsi n'est rattachée à
#     aucun compte client (« À affecter ») : l'administrateur l'affecte ensuite depuis le parc ;
#   GET /api/admin/versions-deployees/poste-details?machine=…&application=…  (administrateur)
#     → tous les composants vus sur la machine, dernier inventaire, fiche du parc liée (lien « Détails »).
from __future__ import annotations

import hmac
import json
import math
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request  # au niveau du module : l'annotation de la route doit être résolue (from __future__)

EN_LIGNE_MINUTES = 12          # 2 signaux manqués (toutes les 5 min) → hors ligne
MAX_POSTES = 2000              # plafond de fiches (protection contre l'envoi massif de faux postes)
_CHAMPS = {                    # champ → longueur maximale conservée
    "application": 40, "composant": 40, "version": 40, "deploye_le": 40, "machine": 80,
    "utilisateur": 80, "site": 120, "systeme": 120, "demarre_le": 40,
}
_NOM_APPLICATION = re.compile(r"^[A-Za-z0-9 ._\-]{2,40}$")

# ---- Lot 66 : inventaire des postes ----
MAX_INVENTAIRE_OCTETS = 200_000   # au-delà, l'inventaire est ignoré (le signal reste accepté)
_INV_PROFONDEUR = 5               # profondeur maximale des objets imbriqués
_INV_MAX_CLES = 60                # nombre maximal de clés par objet
_INV_MAX_LISTE = 300              # nombre maximal d'éléments par liste
_INV_MAX_TEXTE = 300              # longueur maximale d'un texte
_CLE_INVENTAIRE = re.compile(r"^[A-Za-z0-9_]{1,40}$")   # clés sûres pour MongoDB (ni « $ » ni « . »)
# Champs de la fiche du parc remplis automatiquement (jamais s'ils ont été modifiés à la main)
CHAMPS_PARC_AUTO = ("nom_hote", "systeme_exploitation", "fabricant", "modele", "adresse_mac", "adresse_ip", "site",
                    "numero_serie")   # lot 80 : n° de série lu dans le BIOS (SMBIOS) par Loois
# Lot 80 — n° de série « de remplissage » laissés par les fabricants : ignorés (ils ne désignent aucune machine)
_SERIES_BIDON = {"", "0", "NONE", "N/A", "NA", "DEFAULT", "DEFAULTSTRING", "TOBEFILLEDBYO.E.M.", "TOBEFILLEDBYOEM",
                 "SYSTEMSERIALNUMBER", "CHASSISSERIALNUMBER", "123456789", "0123456789", "XXXXXXXXXX", "NOTAPPLICABLE",
                 "NOTSPECIFIED", "OEM", "INVALID"}


def serie_valable(valeur: Any) -> Optional[str]:
    """Lot 80 — n° de série du BIOS gardé seulement s'il est réel (pas « To be filled by O.E.M. », « Default string »…)."""
    texte = str(valeur or "").strip()[:120]
    cle = re.sub(r"\s+", "", texte).upper()
    if cle in _SERIES_BIDON or set(cle) <= {"0", "F", "X", "-", "."}:
        return None
    return texte
CATEGORIES_PARC = {"serveur": "Serveur", "portable": "PC portable", "poste": "PC de bureau"}


def _maintenant() -> datetime:
    """Date et heure actuelles (UTC)."""
    return datetime.now(timezone.utc)


def nettoyer_presence(corps: Any) -> Dict[str, str]:
    """Logique pure (testée) : garde seulement les champs connus, en texte court.

    Lève ValueError si l'application, la version ou la machine manquent."""
    if not isinstance(corps, dict):
        raise ValueError("corps JSON attendu")
    propre: Dict[str, str] = {}
    for champ, longueur in _CHAMPS.items():
        valeur = corps.get(champ)
        if valeur is None or isinstance(valeur, (dict, list)):
            continue
        texte = str(valeur).strip()[:longueur]
        if texte:
            propre[champ] = texte
    for obligatoire in ("application", "version", "machine"):
        if not propre.get(obligatoire):
            raise ValueError(f"champ « {obligatoire} » manquant")
    if not _NOM_APPLICATION.match(propre["application"]):
        raise ValueError("nom d'application invalide")
    propre.setdefault("composant", propre["application"])
    return propre


def _nettoyer_valeur(valeur: Any, profondeur: int) -> Any:
    """Copie sûre d'une valeur d'inventaire : objets et listes bornés, textes coupés, nombres finis.
    Renvoie None pour tout type inattendu (ou trop profond)."""
    if valeur is None or isinstance(valeur, bool):
        return valeur
    if isinstance(valeur, int):
        return valeur if abs(valeur) < 10**15 else None
    if isinstance(valeur, float):
        return valeur if math.isfinite(valeur) else None
    if isinstance(valeur, str):
        return valeur.strip()[:_INV_MAX_TEXTE]
    if profondeur >= _INV_PROFONDEUR:
        return None
    if isinstance(valeur, list):
        return [_nettoyer_valeur(v, profondeur + 1) for v in valeur[:_INV_MAX_LISTE]]
    if isinstance(valeur, dict):
        propre: Dict[str, Any] = {}
        for cle, v in list(valeur.items())[:_INV_MAX_CLES]:
            if isinstance(cle, str) and _CLE_INVENTAIRE.match(cle):
                propre[cle] = _nettoyer_valeur(v, profondeur + 1)
        return propre
    return None


def nettoyer_inventaire(inventaire: Any) -> Optional[Dict[str, Any]]:
    """Logique pure (testée) : inventaire du poste nettoyé, ou None s'il est absent, n'est pas un
    objet ou dépasse MAX_INVENTAIRE_OCTETS (protection contre l'envoi massif)."""
    if not isinstance(inventaire, dict) or not inventaire:
        return None
    try:
        taille = len(json.dumps(inventaire, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return None
    if taille > MAX_INVENTAIRE_OCTETS:
        return None
    return _nettoyer_valeur(inventaire, 0) or None


def _normaliser_mac(valeur: Any) -> Optional[str]:
    """« aa-bb-cc-dd-ee-ff » → « AA:BB:CC:DD:EE:FF » (même règle que le parc) ; None si invalide ou nulle."""
    hexa = re.sub(r"[\s:.\-]", "", str(valeur or ""))
    if not re.fullmatch(r"[0-9A-Fa-f]{12}", hexa) or set(hexa) == {"0"}:
        return None
    return ":".join(hexa[i:i + 2] for i in range(0, 12, 2)).upper()


def _ipv4_valide(valeur: Any) -> Optional[str]:
    """Adresse IPv4 canonique, ou None (adresses APIPA 169.254.x.x ignorées)."""
    import ipaddress
    try:
        ip = ipaddress.ip_address(str(valeur or "").strip())
    except ValueError:
        return None
    if ip.version != 4 or ip.is_link_local or ip.is_loopback:
        return None
    return str(ip)


def cartes_principales(inventaire: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Logique pure (testée) : cartes réseau avec MAC valide, la carte « principale » d'abord
    (une IPv4 ET une passerelle, puis une IPv4 seulement)."""
    cartes = []
    for c in (inventaire.get("reseau") or []):
        if not isinstance(c, dict):
            continue
        mac = _normaliser_mac(c.get("mac"))
        if not mac:
            continue
        ips = [ip for ip in (_ipv4_valide(x) for x in (c.get("ipv4") or [])) if ip]
        rang = 0 if ips and (c.get("passerelles") or []) else (1 if ips else 2)
        cartes.append({"mac": mac, "ip": ips[0] if ips else None, "rang": rang, "nom": c.get("nom")})
    cartes.sort(key=lambda c: c["rang"])
    return cartes


def champs_parc_auto(fiche: Dict[str, Any], inventaire: Dict[str, Any], maintenant: str,
                     verifie: bool = False) -> Dict[str, Any]:
    """Logique pure (testée) : valeurs AUTOMATIQUES de la fiche du parc tirées du signal + inventaire.

    Renvoie {"champs": {nom_hote, systeme_exploitation, …}, "categorie": …, "loois": {résumé technique}}."""
    systeme = inventaire.get("systeme") if isinstance(inventaire.get("systeme"), dict) else {}
    processeur = inventaire.get("processeur") if isinstance(inventaire.get("processeur"), dict) else {}
    memoire = inventaire.get("memoire") if isinstance(inventaire.get("memoire"), dict) else {}
    cartes = cartes_principales(inventaire)
    nom_systeme = " ".join(x for x in (systeme.get("nom"), systeme.get("version")) if x) or fiche.get("systeme")
    champs = {
        "nom_hote": fiche.get("machine"),
        "systeme_exploitation": (nom_systeme or "")[:120] or None,
        "fabricant": (systeme.get("fabricant") or "")[:120] or None,
        "modele": (systeme.get("modele") or "")[:160] or None,
        "adresse_mac": cartes[0]["mac"] if cartes else None,
        "adresse_ip": next((c["ip"] for c in cartes if c["ip"]), None),
        "site": (fiche.get("site") or "")[:120] or None,
        "numero_serie": serie_valable(systeme.get("numero_serie")),   # lot 80
    }
    type_poste = inventaire.get("type_poste") if inventaire.get("type_poste") in CATEGORIES_PARC else "poste"
    disques = [{"lettre": d.get("lettre"), "total_go": d.get("total_go"), "libre_go": d.get("libre_go"),
                "libre_pct": d.get("libre_pct")}
               for d in (inventaire.get("disques") or []) if isinstance(d, dict)][:26]
    loois = {
        "source": "Loois",
        "machine": fiche.get("machine"),
        "type_poste": type_poste,
        "processeur": processeur.get("nom"),
        "coeurs_logiques": processeur.get("coeurs_logiques"),
        "ram_go": memoire.get("totale_go"),
        "logiciels": len(inventaire.get("logiciels") or []),   # lot 80 : nombre de logiciels installés relevés
        "disques": disques,
        "macs": [c["mac"] for c in cartes][:16],
        "ips": [c["ip"] for c in cartes if c["ip"]][:16],
        "utilisateur": fiche.get("utilisateur"),
        "site": fiche.get("site"),
        "verifie": bool(verifie),
        "inventaire_le": maintenant,
        "vu_le": maintenant,
    }
    return {"champs": champs, "categorie": CATEGORIES_PARC[type_poste], "loois": loois}


def fusion_parc(existant: Dict[str, Any], champs: Dict[str, Any]) -> Dict[str, Any]:
    """Logique pure (testée) : champs automatiques à écrire sur une fiche EXISTANTE du parc.

    Un champ n'est écrit que s'il est vide ou encore égal à la valeur que Loois y avait mise la
    dernière fois (`loois_auto`) : toute saisie à la main est conservée. Renvoie le $set à appliquer
    (champs écrits + nouveau `loois_auto`)."""
    precedent = existant.get("loois_auto") or {}
    a_ecrire: Dict[str, Any] = {}
    auto = dict(precedent)
    for champ in CHAMPS_PARC_AUTO:
        nouveau = champs.get(champ)
        if nouveau in (None, ""):
            continue
        actuel = existant.get(champ)
        if actuel in (None, "") or actuel == precedent.get(champ):
            if actuel != nouveau:
                a_ecrire[champ] = nouveau
            auto[champ] = nouveau
    a_ecrire["loois_auto"] = auto
    return a_ecrire


def cle_valide(cle_recue: Optional[str]) -> bool:
    """Vrai si la clé reçue est la clé COMMUNE LOOIS_SUPPORT_CLE (comparaison à temps constant). Lot 68.1 : la
    présence utilise désormais loois_cles_clients.identifier_cle (clé client OU clé commune)."""
    attendue = (os.environ.get("LOOIS_SUPPORT_CLE") or "").strip()
    recue = (cle_recue or "").strip()
    return bool(attendue and recue) and hmac.compare_digest(attendue, recue)


def regrouper_logiciels(fiches: List[Dict[str, Any]], maintenant: datetime) -> List[Dict[str, Any]]:
    """Logique pure (testée) : une entrée par application, avec ses postes (en ligne d'abord),
    la version la plus récente vue et le nombre de postes à jour."""
    limite = maintenant - timedelta(minutes=EN_LIGNE_MINUTES)
    par_application: Dict[str, Dict[str, Any]] = {}
    for f in fiches:
        try:
            vu = datetime.fromisoformat(f.get("vu_le") or "")
        except ValueError:
            continue
        poste = {k: f.get(k) for k in ("machine", "composant", "version", "deploye_le", "utilisateur",
                                       "site", "systeme", "demarre_le", "vu_le", "premiere_fois", "verifie",
                                       "verifie_client")}
        poste["en_ligne"] = vu >= limite
        app = par_application.setdefault(f["application"], {"application": f["application"], "postes": []})
        app["postes"].append(poste)
    sortie = []
    for app in par_application.values():
        postes = app["postes"]
        # Version la plus récente = comparaison numérique 1.2610.610.44 (repli : texte)
        derniere = max((p["version"] for p in postes if p.get("version")), key=_cle_version, default="")
        for p in postes:
            p["a_jour"] = p.get("version") == derniere
        postes.sort(key=lambda p: (not p["en_ligne"], (p.get("machine") or "").lower(), p.get("composant") or ""))
        sortie.append({
            "application": app["application"],
            "derniere_version": derniere,
            "deploye_le": next((p.get("deploye_le") for p in postes if p.get("version") == derniere and p.get("deploye_le")), None),
            "postes": postes,
            "en_ligne": sum(1 for p in postes if p["en_ligne"]),
            "a_jour": sum(1 for p in postes if p["a_jour"]),
        })
    sortie.sort(key=lambda a: a["application"].lower())
    return sortie


def _cle_version(version: str):
    """Clé de tri d'un numéro de version : (1, 2610, 610, 44) ; texte non numérique en dernier recours."""
    try:
        return (1, tuple(int(x) for x in version.split(".")))
    except ValueError:
        return (0, (version,))


async def _numero_inventaire_loois(db) -> str:
    """Numéro d'inventaire d'une fiche créée par Loois (pas encore de client) : PARC-LOOIS-0001."""
    c = await db.compteurs.find_one_and_update({"_id": "parc:loois"}, {"$inc": {"n": 1}}, upsert=True,
                                               return_document=True)
    return f"PARC-LOOIS-{((c or {}).get('n') or 1):04d}"


async def synchroniser_parc(db, fiche: Dict[str, Any], inventaire: Dict[str, Any], maintenant: str,
                            verifie: bool = False) -> Optional[str]:
    """Crée ou complète la fiche « Parc informatique » de la machine. Renvoie l'id de la fiche.

    Clé : le nom de la machine (`loois_machine`), sinon une adresse MAC déjà saisie dans le parc
    (la fiche existante est alors liée à la machine). Seuls les champs automatiques sont écrits."""
    auto = champs_parc_auto(fiche, inventaire, maintenant, verifie)
    cle_machine = fiche["machine"].upper()
    existant = await db.parc_equipements.find_one({"loois_machine": cle_machine}, {"_id": 0})
    if not existant and auto["loois"]["macs"]:
        existant = await db.parc_equipements.find_one(
            {"adresse_mac": {"$in": auto["loois"]["macs"]}, "loois_machine": {"$exists": False}}, {"_id": 0})
    if existant:
        a_ecrire = fusion_parc(existant, auto["champs"])
        # Adresse MAC unique dans le parc d'un client : ne pas l'écrire si une autre fiche la porte déjà
        if a_ecrire.get("adresse_mac") and await db.parc_equipements.find_one(
                {"tenant_id": existant.get("tenant_id"), "adresse_mac": a_ecrire["adresse_mac"],
                 "id": {"$ne": existant["id"]}}, {"_id": 1}):
            a_ecrire.pop("adresse_mac")
            a_ecrire["loois_auto"].pop("adresse_mac", None)
        # Lot 80 : n° de série unique dans le parc d'un client (clé de comparaison comme au lot 47)
        if a_ecrire.get("numero_serie"):
            from routes.parc_informatique import cle_serie   # import tardif (évite une boucle d'imports)
            a_ecrire["numero_serie_cle"] = cle_serie(a_ecrire["numero_serie"])
            if await db.parc_equipements.find_one(
                    {"tenant_id": existant.get("tenant_id"), "numero_serie_cle": a_ecrire["numero_serie_cle"],
                     "id": {"$ne": existant["id"]}}, {"_id": 1}):
                a_ecrire.pop("numero_serie")
                a_ecrire.pop("numero_serie_cle")
                a_ecrire["loois_auto"].pop("numero_serie", None)
        await db.parc_equipements.update_one({"id": existant["id"]}, {"$set": {
            **a_ecrire, "loois": auto["loois"], "loois_machine": cle_machine, "maj_le": maintenant}})
        return existant["id"]
    # Nouvelle fiche (plafond identique à celui des postes : protection contre les faux signaux)
    if await db.parc_equipements.count_documents({"loois_machine": {"$exists": True}}) >= MAX_POSTES:
        return None
    champs = {k: v for k, v in auto["champs"].items() if v not in (None, "")}
    if champs.get("numero_serie"):   # lot 80 : clé de comparaison du n° de série (lot 47)
        from routes.parc_informatique import cle_serie   # import tardif (évite une boucle d'imports)
        champs_cle = {"numero_serie_cle": cle_serie(champs["numero_serie"])}
    else:
        champs_cle = {}
    doc = {
        "id": secrets.token_hex(8), "tenant_id": None, "client_nom": "",
        "numero_inventaire": await _numero_inventaire_loois(db), "categorie": auto["categorie"],
        # Champs du formulaire du parc (lot 47) : vides tant que le propriétaire ne les a pas saisis
        "fabricant": None, "modele": None, "numero_serie": None, "numero_serie_cle": None, "adresse_ip": None,
        "adresse_mac": None, "nom_hote": None, "systeme_exploitation": None, "utilisateur_affecte": None,
        "site": None, "service": None, "bureau": None, "date_achat": None, "fin_garantie": None,
        "fournisseur": None, "etat": "en_service", "notes": None, "photos": [],
        **champs, **champs_cle, "loois_auto": champs, "loois": auto["loois"], "loois_machine": cle_machine,
        "source": "loois", "cree_par": "Loois (automatique)", "cree_le": maintenant, "maj_le": maintenant,
    }
    await db.parc_equipements.insert_one(dict(doc))
    return doc["id"]


def setup_versions_deployees_routes(*, db, api, get_current_user, lire_version=None) -> None:
    """Branche les routes du lot 65 (appelée depuis server_parts/p20).

    lire_version : la fonction de /api/version (p01), pour la version de SAWALI lui-même."""
    from fastapi import Depends, HTTPException

    @api.post("/presence-logiciel", tags=["Versions déployées"])
    async def presence_logiciel(request: Request):
        """Signal de présence d'un logiciel de bureau (Loois…) : version + machine. Jamais de secret renvoyé."""
        try:
            corps = await request.json()
            fiche = nettoyer_presence(corps)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception:  # noqa: BLE001 — corps illisible
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        cle = {"application": fiche["application"], "machine": fiche["machine"], "composant": fiche["composant"]}
        existe = await db.presences_logiciels.find_one(cle, {"_id": 1})
        if not existe and await db.presences_logiciels.count_documents({}) >= MAX_POSTES:
            raise HTTPException(status_code=429, detail="trop de postes enregistrés")
        maintenant = _maintenant().isoformat()
        # Lot 68.1 : clé client (→ client identifié) ou clé commune ; sans clé valable le signal reste accepté (« non vérifié »)
        from routes import loois_cles_clients as cles   # import tardif (évite une boucle d'imports)
        identite = await cles.identifier_cle(db, request.headers.get("X-Cle-Loois"), machine=fiche["machine"])
        verifie = bool(identite)
        verifie_client = cles.libelle_identite(identite)
        # Lot 66 : inventaire facultatif (ignoré s'il est trop gros ou illisible ; le signal reste accepté)
        inventaire = nettoyer_inventaire(corps.get("inventaire"))
        en_plus: Dict[str, Any] = {"inventaire_le": maintenant} if inventaire else {}
        await db.presences_logiciels.update_one(cle, {
            "$set": {**fiche, "vu_le": maintenant, "verifie": verifie, "verifie_client": verifie_client,
                     "adresse_ip": (request.client.host if request.client else None), **en_plus},
            "$setOnInsert": {"premiere_fois": maintenant},
        }, upsert=True)
        if inventaire:
            # Dernier inventaire de la MACHINE (une fiche par machine, quel que soit le composant qui l'envoie)
            await db.inventaires_postes.update_one({"machine_cle": fiche["machine"].upper()}, {"$set": {
                "machine": fiche["machine"], "machine_cle": fiche["machine"].upper(), "inventaire": inventaire,
                "inventaire_le": maintenant, "application": fiche["application"], "composant": fiche["composant"],
                "verifie": verifie, "adresse_ip_publique": (request.client.host if request.client else None),
            }}, upsert=True)
            # Fiche du parc informatique créée ou complétée (jamais bloquant pour le signal)
            try:
                await synchroniser_parc(db, fiche, inventaire, maintenant, verifie)
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "inventaire": bool(inventaire)}

    @api.get("/admin/versions-deployees/poste-details", tags=["Versions déployées"])
    async def poste_details(machine: str, application: Optional[str] = None, user: dict = Depends(get_current_user)):
        """Lien « Détails » d'un poste : tous ses composants, son dernier inventaire et sa fiche du parc."""
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        nom = (machine or "").strip()[:80]
        if not nom:
            raise HTTPException(status_code=422, detail="machine attendue")
        # Recherche sans tenir compte de la casse (nom exact, caractères spéciaux neutralisés)
        motif = {"$regex": f"^{re.escape(nom)}$", "$options": "i"}
        fiches = [f async for f in db.presences_logiciels.find({"machine": motif}, {"_id": 0, "adresse_ip": 0})]
        inv = await db.inventaires_postes.find_one({"machine_cle": nom.upper()}, {"_id": 0})
        if not fiches and not inv:
            raise HTTPException(status_code=404, detail="Poste inconnu")
        limite = _maintenant() - timedelta(minutes=EN_LIGNE_MINUTES)
        composants = []
        for f in fiches:
            try:
                en_ligne = datetime.fromisoformat(f.get("vu_le") or "") >= limite
            except ValueError:
                en_ligne = False
            composants.append({**f, "en_ligne": en_ligne})
        # Application demandée d'abord, puis par application et composant
        composants.sort(key=lambda c: (c.get("application") != application, c.get("application") or "", c.get("composant") or ""))
        equipement = await db.parc_equipements.find_one(
            {"loois_machine": nom.upper()},
            {"_id": 0, "id": 1, "numero_inventaire": 1, "client_nom": 1, "tenant_id": 1, "categorie": 1, "etat": 1})
        return {
            "machine": (fiches[0]["machine"] if fiches else inv.get("machine")),
            "composants": composants,
            "inventaire": (inv or {}).get("inventaire"),
            "inventaire_le": (inv or {}).get("inventaire_le"),
            "inventaire_composant": (inv or {}).get("composant"),
            "adresse_ip_publique": (inv or {}).get("adresse_ip_publique"),
            "equipement": ({**equipement, "a_affecter": not equipement.get("tenant_id")} if equipement else None),
            "en_ligne_minutes": EN_LIGNE_MINUTES,
        }

    @api.get("/admin/versions-deployees", tags=["Versions déployées"])
    async def versions_deployees(user: dict = Depends(get_current_user)):
        """Versions de SAWALI, des plateformes web et des logiciels de bureau (avec leurs postes)."""
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        # SAWALI : même calcul que /api/version (lot.py + compteur de déploiements)
        sawali = None
        try:
            if lire_version is not None:
                sawali = await lire_version()
        except Exception:  # noqa: BLE001
            pass
        # Plateformes web : dernière réponse de statistiques réussie (version facultative)
        plateformes = []
        async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "code": 1, "nom": 1, "actif": 1}).sort("nom", 1):
            derniere = await db.plateformes_stats.find_one(
                {"code": e.get("code"), "resultat.ok": True}, {"_id": 0, "resultat": 1}, sort=[("recu_le", -1)])
            res = (derniere or {}).get("resultat") or {}
            plateformes.append({"code": e.get("code"), "nom": e.get("nom") or e.get("code"),
                                "actif": bool(e.get("actif", True)), "version": res.get("version"),
                                "deploye_le": res.get("deploye_le"), "recu_le": res.get("recu_le")})
        fiches = [f async for f in db.presences_logiciels.find({}, {"_id": 0, "adresse_ip": 0})]
        return {"sawali": sawali, "plateformes": plateformes,
                "logiciels": regrouper_logiciels(fiches, _maintenant()),
                "en_ligne_minutes": EN_LIGNE_MINUTES}
