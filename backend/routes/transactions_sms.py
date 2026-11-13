# transactions_sms.py — Lot 389 : TRANSACTIONS SMS (paiements lus dans les SMS d'un téléphone, vus dans SAWALI, associés à un client / plateforme).
#
# Demande du propriétaire (14/11/2026) : l'application « Concentration » lit tous les SMS de paiement d'un téléphone. Il veut les VISUALISER dans SAWALI (super-admin)
# sans passer par les Paramètres : une nouvelle option de menu « Transactions SMS » avec les mêmes filtres que l'historique d'auRor ; et pouvoir ASSOCIER un numéro
# à un client / une plateforme (ex. ALBARKA) pour que la plateforme retrouve l'historique de ses paiements sans les ressaisir (ex. Services Web d'ALBARKA).
#
# EN RÉSUMÉ (pour un développeur WinDev)
#   1. TÉLÉPHONE SOURCE : l'administrateur en crée un (nom) → SAWALI donne un identifiant et une clé, MONTRÉS UNE SEULE FOIS. Le téléphone les saisit dans Concentration.
#   2. ENVOI : Concentration envoie ses paiements par lots :  POST /api/transactions-sms/v1/envoi   en-têtes X-Source: <identifiant>, X-Cle: <clé>
#         corps {"paiements":[{"adresse","recu_le_ms","genre":"DEPENSE|RECETTE","montant","tiers","solde","reference","corps"}, …]}   (300 au plus par envoi)
#         réponse {"acceptees","doublons","ignorees"}. Un même SMS envoyé deux fois n'est gardé qu'une fois (clé = numéro de transaction, sinon source + instant + texte).
#   3. ÉCRAN « Transactions SMS » (menu, administrateur) : filtres (période, opérateur, sens, téléphone, plateforme liée, texte), chiffres clés, opérateurs,
#      histogramme jour / mois, classements, camembert, liste, export CSV. Toucher un élément filtre l'écran dessus.
#   4. ASSOCIATIONS : un numéro (8 chiffres, lu dans le SMS) ou un nom (tel qu'écrit dans le SMS) est lié à une PLATEFORME (liste des émetteurs : ALBARKA…).
#   5. PLATEFORMES : la plateforme relit ses transactions par  POST /api/webhook/plateforme-paiements  SIGNÉ comme ses autres échanges (X-Emetteur, X-Timestamp,
#      X-Signature = HMAC-SHA256(clé, "<horodatage>.<corps>")) : elle ne reçoit QUE les transactions des numéros qui lui sont associés, champs structurés
#      seulement (jamais le texte du SMS).
#
# STOCKAGE (sans nouvelle collection : le cluster MongoDB est plein) : documents de `settings` — `transactions-sms:config` (téléphones, associations) et un
# document par mois `transactions-sms:AAAA-MM` (8000 transactions au plus par mois). Seuls points d'accès à la base : les fonctions `_lire_*` / `_ecrire_*`.
#
# VIE PRIVÉE : le texte des SMS de paiement est conservé (il contient des noms et des numéros) ; seul l'administrateur le voit.
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import re
import secrets
import unicodedata
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Request, Response

from routes.contrats_plateformes import signature_valide

PREFIXE_CONFIG = "transactions-sms:config"
PREFIXE_MOIS = "transactions-sms:"
MAX_PAR_ENVOI = 300
MAX_PAR_MOIS = 8000
MAX_RESULTATS = 20000
OPERATEURS = ["Orange Money", "Moov Money", "Telecel Money", "Banque", "Autre"]
GENRES = ("DEPENSE", "RECETTE")


# =====================================================================================
# Logique pure (testée : tests/test_lot389_transactions_sms.py)
# =====================================================================================

def normaliser(texte: str) -> str:
    """Sans accents ni majuscules, espaces simples : « Pharmacie Étoile » → « pharmacie etoile »."""
    sans = "".join(c for c in unicodedata.normalize("NFD", texte or "") if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sans.lower()).strip()


def operateur_de(adresse: str, corps: str) -> str:
    """Opérateur deviné d'après l'expéditeur du SMS puis son texte (liste finie : Orange Money, Moov Money, Telecel Money, Banque, Autre)."""
    t = normaliser((adresse or "") + " " + (corps or ""))
    if "orange" in t:
        return "Orange Money"
    if "moov" in t:
        return "Moov Money"
    if "telecel" in t:
        return "Telecel Money"
    if re.search(r"banque|bank|coris|ecobank|sgbf|\bboa\b|bicia|\buba\b|bdm|cbao|sonibank|societe generale", t):
        return "Banque"
    return "Autre"


_TRANSACTION = re.compile(r"trans(?:action)?\s*id\s*:?\s*\S+", re.I)
_SOLDE = re.compile(r"solde[^.\n]*", re.I)
_TELEPHONE = re.compile(r"(?<![\d.,])(?:(?:\+|00)?226[\s.\-]?)?((?:[0-7]\d[\s.\-]?){3}\d\d)(?![\d])")
_MONNAIE_APRES = re.compile(r"\s*(?:fcfa|f\s?cfa|xof|cfa)\b", re.I)


def numero_de(corps: str) -> Optional[str]:
    """Numéro de téléphone (8 chiffres, sans l'indicatif 226) lu dans le texte du SMS, ou None. On écarte le numéro de transaction, la phrase du solde et tout nombre
    suivi de « FCFA » (un montant). Écritures reconnues : 70112233, 70 11 22 33, 70-11-22-33, +226 70 11 22 33, 00226 70112233."""
    t = _SOLDE.sub(" ", _TRANSACTION.sub(" ", corps or ""))
    for m in _TELEPHONE.finditer(t):
        if _MONNAIE_APRES.match(t, m.end()):
            continue
        return re.sub(r"\D", "", m.group(1))
    return None


def cle_lien(texte: str) -> Tuple[str, str]:
    """Clé d'association saisie par l'administrateur : un NUMÉRO (≥ 8 chiffres → les 8 derniers) ou un NOM (normalisé). Lève ValueError si vide."""
    brut = (texte or "").strip()
    chiffres = re.sub(r"\D", "", brut)
    if len(chiffres) >= 8 and re.fullmatch(r"[\d\s+().\-]+", brut):
        return "numero", chiffres[-8:]
    nom = normaliser(brut)
    if len(nom) < 3:
        raise ValueError("Saisissez un numéro (8 chiffres) ou un nom d'au moins 3 caractères")
    return "nom", nom[:80]


def nettoyer_paiement(d: Any) -> Optional[Dict[str, Any]]:
    """Un paiement reçu du téléphone, nettoyé ; None s'il est inutilisable (sens inconnu, montant ≤ 0, instant absent)."""
    if not isinstance(d, dict) or d.get("genre") not in GENRES:
        return None
    try:
        montant = int(d.get("montant"))
        ms = int(d.get("recu_le_ms"))
    except (TypeError, ValueError):
        return None
    if montant <= 0 or ms <= 0:
        return None
    solde = d.get("solde")
    try:
        solde = int(solde) if solde not in (None, "") else None
    except (TypeError, ValueError):
        solde = None
    return {"adresse": str(d.get("adresse") or "").strip()[:40], "ms": ms, "genre": d["genre"], "montant": montant,
            "tiers": str(d.get("tiers") or "").strip()[:80], "solde": solde, "reference": (str(d.get("reference") or "").strip()[:60] or None),
            "corps": str(d.get("corps") or "").strip()[:1000]}


def cle_dedoublonnage(source: str, p: Dict[str, Any]) -> str:
    """Identité d'une transaction : son numéro de transaction s'il existe, sinon source + instant + texte (le même SMS envoyé deux fois = une seule ligne)."""
    if p.get("reference"):
        return "ref:" + p["reference"]
    return "sms:" + hashlib.sha1(f"{source}|{p['ms']}|{p['adresse']}|{p['corps']}".encode()).hexdigest()[:24]


def mois_de(ms: int) -> str:
    """Mois (UTC, = heure du Burkina) d'un instant, « AAAA-MM »."""
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m")


def jour_de(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def enrichir(p: Dict[str, Any], liens: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ajoute à une transaction son opérateur, le numéro lu dans le SMS et, s'il existe, la plateforme à laquelle elle est associée."""
    numero = numero_de(p.get("corps") or "")
    nom = normaliser(p.get("tiers") or "")
    lien = next((l for l in liens if (l["type"] == "numero" and numero and l["cle"] == numero) or (l["type"] == "nom" and nom and l["cle"] == nom)), None)
    return {**p, "operateur": operateur_de(p.get("adresse"), p.get("corps")), "numero": numero,
            "plateforme": lien["plateforme"] if lien else None, "lien_libelle": lien["libelle"] if lien else None}


def filtrer(items: List[Dict[str, Any]], du_ms: Optional[int] = None, au_ms: Optional[int] = None, operateur: str = "", genre: str = "",
            q: str = "", source: str = "", plateforme: str = "") -> List[Dict[str, Any]]:
    """Transactions (déjà enrichies) qui satisfont TOUS les critères, du plus récent au plus ancien. `au_ms` est exclu ; `plateforme` = code d'émetteur, ou « *lie » (toute
    transaction associée) ou « *non_lie ». Chaque mot du texte cherché doit se trouver dans le bénéficiaire, la référence, l'expéditeur, le numéro ou le SMS."""
    mots = [m for m in normaliser(q).split(" ") if m]
    sortie = []
    for p in items:
        if du_ms is not None and p["ms"] < du_ms:
            continue
        if au_ms is not None and p["ms"] >= au_ms:
            continue
        if genre and p["genre"] != genre:
            continue
        if operateur and p["operateur"] != operateur:
            continue
        if source and p.get("source") != source:
            continue
        if plateforme == "*lie" and not p.get("plateforme"):
            continue
        if plateforme == "*non_lie" and p.get("plateforme"):
            continue
        if plateforme and not plateforme.startswith("*") and p.get("plateforme") != plateforme:
            continue
        if mots:
            botte = normaliser(" ".join([p.get("tiers") or "", p.get("reference") or "", p.get("adresse") or "", p.get("numero") or "", p.get("corps") or ""]))
            if not all(m in botte for m in mots):
                continue
        sortie.append(p)
    sortie.sort(key=lambda p: p["ms"], reverse=True)
    return sortie


def statistiques(items: List[Dict[str, Any]], par_mois: bool = False, genre_classement: str = "DEPENSE") -> Dict[str, Any]:
    """Tout ce que l'écran affiche en dehors de la liste : chiffres clés, opérateurs, histogramme jour / mois, classements, parts du camembert."""
    dep = [p for p in items if p["genre"] == "DEPENSE"]
    rec = [p for p in items if p["genre"] == "RECETTE"]
    d, r = sum(p["montant"] for p in dep), sum(p["montant"] for p in rec)
    totaux = {"nombre": len(items), "depenses": d, "recettes": r, "net": r - d, "nb_depenses": len(dep), "nb_recettes": len(rec),
              "depense_moyenne": d // len(dep) if dep else 0, "plus_grosse": max((p["montant"] for p in dep), default=0)}
    ops: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"nombre": 0, "depenses": 0, "recettes": 0})
    barres: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"nombre": 0, "depenses": 0, "recettes": 0})
    for p in items:
        o = ops[p["operateur"]]
        o["nombre"] += 1
        o["depenses" if p["genre"] == "DEPENSE" else "recettes"] += p["montant"]
        b = barres[mois_de(p["ms"]) if par_mois else jour_de(p["ms"])]
        b["nombre"] += 1
        b["depenses" if p["genre"] == "DEPENSE" else "recettes"] += p["montant"]
    choisis = [p for p in items if p["genre"] == genre_classement]
    tiers: Dict[str, Dict[str, Any]] = {}
    for p in choisis:
        nom = p.get("tiers") or "(sans nom)"
        t = tiers.setdefault(normaliser(nom), {"nom": nom, "nombre": 0, "total": 0})
        t["nombre"] += 1
        t["total"] += p["montant"]
    top_tiers = sorted(tiers.values(), key=lambda t: t["total"], reverse=True)[:10]
    total_genre = sum(p["montant"] for p in choisis)
    parts = [[t["nom"], t["total"]] for t in top_tiers[:6]]
    reste = total_genre - sum(x[1] for x in parts)
    if reste > 0:
        parts.append(["Autres", reste])
    return {"totaux": totaux,
            "par_operateur": sorted(({"operateur": k, **v} for k, v in ops.items()), key=lambda o: o["nombre"], reverse=True),
            "barres": [{"cle": k, **v} for k, v in sorted(barres.items())],
            "top_tiers": top_tiers,
            "top_montants": [{"ms": p["ms"], "tiers": p.get("tiers"), "operateur": p["operateur"], "montant": p["montant"]} for p in sorted(choisis, key=lambda p: p["montant"], reverse=True)[:10]],
            "parts": parts, "total_classement": total_genre}


def csv_de(items: List[Dict[str, Any]]) -> str:
    """Export CSV (séparateur « ; », accents conservés, BOM pour Excel) des transactions affichées."""
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";", quoting=csv.QUOTE_ALL)
    w.writerow(["Date", "Opérateur", "Sens", "Montant (FCFA)", "Bénéficiaire / expéditeur", "Numéro", "Solde après", "Transaction", "Plateforme", "Client"])
    for p in items:
        w.writerow([datetime.fromtimestamp(p["ms"] / 1000, timezone.utc).strftime("%d/%m/%Y %H:%M"), p["operateur"], "Recette" if p["genre"] == "RECETTE" else "Dépense",
                    p["montant"], p.get("tiers") or "", p.get("numero") or "", p.get("solde") if p.get("solde") is not None else "", p.get("reference") or "",
                    p.get("plateforme") or "", p.get("lien_libelle") or ""])
    return "﻿" + sortie.getvalue()


def vue_plateforme(p: Dict[str, Any]) -> Dict[str, Any]:
    """Ce que reçoit une plateforme : champs structurés SEULEMENT (jamais le texte du SMS ni l'expéditeur brut)."""
    return {"id": p["k"], "recu_le": datetime.fromtimestamp(p["ms"] / 1000, timezone.utc).isoformat(), "sens": "entree" if p["genre"] == "RECETTE" else "sortie",
            "montant": p["montant"], "tiers": p.get("tiers") or "", "numero": p.get("numero"), "reference": p.get("reference"),
            "operateur": p["operateur"], "client": p.get("lien_libelle")}


def hacher_cle(cle: str) -> str:
    return hashlib.sha256((cle or "").encode()).hexdigest()


# =====================================================================================
# Routes
# =====================================================================================

def setup_transactions_sms_routes(*, db, api, get_current_user, maintenant=lambda: datetime.now(timezone.utc)) -> None:
    """Branche les routes du lot 389 (appelée depuis server_parts/p20). `maintenant` (datetime UTC) est remplaçable par les tests."""
    from fastapi import Depends, HTTPException

    def _admin(user: dict) -> None:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    # ---- Seuls points d'accès à la base ----
    async def _lire_config() -> Dict[str, Any]:
        doc = await db.settings.find_one({"_id": PREFIXE_CONFIG}) or {}
        return {"_id": PREFIXE_CONFIG, "sources": doc.get("sources") or [], "liens": doc.get("liens") or []}

    async def _ecrire_config(cfg: Dict[str, Any]) -> None:
        await db.settings.replace_one({"_id": PREFIXE_CONFIG}, cfg, upsert=True)

    async def _lire_mois(mois: str) -> Dict[str, Any]:
        return await db.settings.find_one({"_id": PREFIXE_MOIS + mois}) or {"_id": PREFIXE_MOIS + mois, "mois": mois, "items": []}

    async def _ecrire_mois(doc: Dict[str, Any]) -> None:
        await db.settings.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    async def _mois_existants() -> List[str]:
        return sorted([d["_id"][len(PREFIXE_MOIS):] async for d in db.settings.find({"_id": {"$regex": r"^transactions-sms:\d{4}-\d{2}$"}}, {"_id": 1})])

    async def _toutes(du_ms: Optional[int], au_ms: Optional[int], liens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Transactions enrichies des mois concernés par la période."""
        bas = mois_de(du_ms) if du_ms else "0000-00"
        haut = mois_de(au_ms) if au_ms else "9999-99"
        sortie = []
        for mois in await _mois_existants():
            if bas <= mois <= haut:
                sortie += [enrichir(p, liens) for p in (await _lire_mois(mois)).get("items") or []]
        return sortie

    def _bornes(du: str, au: str) -> Tuple[Optional[int], Optional[int]]:
        """Dates « AAAA-MM-JJ » (au inclus) → millisecondes UTC."""
        def ms(texte: str, plus_un: bool) -> Optional[int]:
            if not texte:
                return None
            try:
                d = datetime.strptime(texte[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                raise HTTPException(status_code=422, detail="Date attendue : AAAA-MM-JJ")
            return int(d.timestamp() * 1000) + (86_400_000 if plus_un else 0)
        return ms(du, False), ms(au, True)

    # ------------------------------------------------------------------ téléphone source → SAWALI
    @api.post("/transactions-sms/v1/envoi", tags=["Transactions SMS — téléphone"])
    async def recevoir(request: Request):
        """Contrat v1 : le téléphone envoie ses paiements. Authentification par X-Source (identifiant) et X-Cle."""
        ident = (request.headers.get("X-Source") or "").strip()
        cle = request.headers.get("X-Cle") or ""
        cfg = await _lire_config()
        source = next((s for s in cfg["sources"] if s["id"] == ident), None)
        if not source or not hmac.compare_digest(source["cle_hash"], hacher_cle(cle)):
            raise HTTPException(status_code=401, detail="Téléphone inconnu ou clé refusée")
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        brut = corps.get("paiements") if isinstance(corps, dict) else None
        if not isinstance(brut, list):
            raise HTTPException(status_code=422, detail="« paiements » doit être une liste")
        propres = [p for p in (nettoyer_paiement(d) for d in brut[:MAX_PAR_ENVOI]) if p]
        par_mois: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for p in propres:
            par_mois[mois_de(p["ms"])].append(p)
        acceptees = doublons = 0
        ignorees = len(brut) - len(propres)
        for mois, liste in par_mois.items():
            doc = await _lire_mois(mois)
            connus = {i["k"] for i in doc["items"]}
            for p in liste:
                k = cle_dedoublonnage(ident, p)
                if k in connus:
                    doublons += 1
                elif len(doc["items"]) >= MAX_PAR_MOIS:
                    ignorees += 1
                else:
                    doc["items"].append({"k": k, "source": ident, **p})
                    connus.add(k)
                    acceptees += 1
            await _ecrire_mois(doc)
        source["dernier_envoi"] = maintenant().isoformat()
        source["recues"] = int(source.get("recues") or 0) + acceptees
        await _ecrire_config(cfg)
        return {"acceptees": acceptees, "doublons": doublons, "ignorees": ignorees}

    # ------------------------------------------------------------------ écran (administrateur)
    async def _emetteurs() -> List[Dict[str, str]]:
        return [{"code": e["code"], "nom": e.get("nom") or e["code"]} async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "code": 1, "nom": 1}) if e.get("code")]

    @api.get("/admin/transactions-sms/etat", tags=["Transactions SMS — écran"])
    async def etat(user: dict = Depends(get_current_user)):
        _admin(user)
        cfg = await _lire_config()
        return {"sources": [{k: s.get(k) for k in ("id", "nom", "dernier_envoi", "recues")} for s in cfg["sources"]], "liens": cfg["liens"],
                "plateformes": await _emetteurs(), "operateurs": OPERATEURS, "mois": await _mois_existants()}

    @api.post("/admin/transactions-sms/sources", tags=["Transactions SMS — écran"])
    async def creer_source(request: Request, user: dict = Depends(get_current_user)):
        """Crée un téléphone source ; l'identifiant et la clé ne sont montrés qu'UNE FOIS."""
        _admin(user)
        nom = str(((await request.json()) or {}).get("nom") or "").strip()[:60]
        if len(nom) < 2:
            raise HTTPException(status_code=422, detail="Donnez un nom au téléphone (ex. Téléphone du bureau)")
        cfg = await _lire_config()
        ident, cle = secrets.token_hex(4), secrets.token_urlsafe(24)
        cfg["sources"].append({"id": ident, "nom": nom, "cle_hash": hacher_cle(cle), "dernier_envoi": None, "recues": 0})
        await _ecrire_config(cfg)
        return {"id": ident, "nom": nom, "cle": cle}

    @api.delete("/admin/transactions-sms/sources/{ident}", tags=["Transactions SMS — écran"])
    async def supprimer_source(ident: str, user: dict = Depends(get_current_user)):
        """Retire le téléphone (il ne peut plus envoyer) ; les transactions déjà reçues sont conservées."""
        _admin(user)
        cfg = await _lire_config()
        cfg["sources"] = [s for s in cfg["sources"] if s["id"] != ident]
        await _ecrire_config(cfg)
        return {"ok": True}

    @api.post("/admin/transactions-sms/liens", tags=["Transactions SMS — écran"])
    async def creer_lien(request: Request, user: dict = Depends(get_current_user)):
        """Associe un numéro (ou un nom) à une plateforme (émetteur) avec un libellé de client."""
        _admin(user)
        corps = (await request.json()) or {}
        try:
            type_, cle = cle_lien(str(corps.get("cle") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        plateforme = str(corps.get("plateforme") or "").strip().lower()
        if plateforme not in {e["code"] for e in await _emetteurs()}:
            raise HTTPException(status_code=422, detail="Choisissez une plateforme de la liste")
        libelle = str(corps.get("libelle") or "").strip()[:80] or plateforme
        cfg = await _lire_config()
        if any(l["type"] == type_ and l["cle"] == cle for l in cfg["liens"]):
            raise HTTPException(status_code=409, detail="Ce numéro (ou ce nom) est déjà associé")
        lien = {"id": uuid.uuid4().hex[:10], "type": type_, "cle": cle, "plateforme": plateforme, "libelle": libelle}
        cfg["liens"].append(lien)
        await _ecrire_config(cfg)
        return lien

    @api.delete("/admin/transactions-sms/liens/{lien_id}", tags=["Transactions SMS — écran"])
    async def supprimer_lien(lien_id: str, user: dict = Depends(get_current_user)):
        _admin(user)
        cfg = await _lire_config()
        cfg["liens"] = [l for l in cfg["liens"] if l["id"] != lien_id]
        await _ecrire_config(cfg)
        return {"ok": True}

    async def _filtrees(du: str, au: str, operateur: str, genre: str, q: str, source: str, plateforme: str) -> List[Dict[str, Any]]:
        du_ms, au_ms = _bornes(du, au)
        cfg = await _lire_config()
        return filtrer(await _toutes(du_ms, au_ms, cfg["liens"]), du_ms, au_ms, operateur, genre, q, source, plateforme)

    @api.get("/admin/transactions-sms", tags=["Transactions SMS — écran"])
    async def lister(du: str = "", au: str = "", operateur: str = "", genre: str = "", q: str = "", source: str = "", plateforme: str = "",
                     par_mois: bool = False, classement: str = "DEPENSE", decalage: int = 0, limite: int = 50, user: dict = Depends(get_current_user)):
        """Transactions filtrées + statistiques calculées sur TOUTES les transactions filtrées (la liste est paginée)."""
        _admin(user)
        items = await _filtrees(du, au, operateur, genre, q, source, plateforme)
        limite = max(1, min(limite, 200))
        retire = [{k: v for k, v in p.items() if k != "k"} for p in items[max(0, decalage):max(0, decalage) + limite]]
        return {"total": len(items), "transactions": retire, "stats": statistiques(items, par_mois, classement if classement in GENRES else "DEPENSE")}

    @api.get("/admin/transactions-sms/export.csv", tags=["Transactions SMS — écran"])
    async def exporter(du: str = "", au: str = "", operateur: str = "", genre: str = "", q: str = "", source: str = "", plateforme: str = "",
                       user: dict = Depends(get_current_user)):
        _admin(user)
        items = (await _filtrees(du, au, operateur, genre, q, source, plateforme))[:MAX_RESULTATS]
        return Response(content=csv_de(items), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="transactions_sms.csv"'})

    # ------------------------------------------------------------------ plateformes (signé)
    @api.post("/webhook/plateforme-paiements", tags=["Transactions SMS — plateformes"])
    async def pour_plateforme(request: Request):
        """La plateforme relit les transactions des numéros qui lui sont associés. Requête signée avec sa clé d'émetteur. Corps facultatif : {"depuis": "AAAA-MM-JJ", "sens": "entree|sortie", "limite": 200}."""
        code = (request.headers.get("X-Emetteur") or "").strip().lower()
        emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0}) if code else None
        if not emetteur or not emetteur.get("actif", True):
            raise HTTPException(status_code=401, detail="Émetteur inconnu ou désactivé")
        corps = await request.body()
        if not signature_valide(emetteur.get("secret") or "", request.headers.get("X-Timestamp") or "", corps, request.headers.get("X-Signature") or "", maintenant()):
            raise HTTPException(status_code=401, detail="Signature refusée")
        try:
            donnees = json.loads(corps.decode("utf-8") or "{}") if corps else {}
        except ValueError:
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        donnees = donnees if isinstance(donnees, dict) else {}
        du_ms, _ = _bornes(str(donnees.get("depuis") or ""), "")
        genre = {"entree": "RECETTE", "sortie": "DEPENSE"}.get(str(donnees.get("sens") or ""), "")
        limite = max(1, min(int(donnees.get("limite") or 200), 500))
        cfg = await _lire_config()
        items = filtrer(await _toutes(du_ms, None, cfg["liens"]), du_ms, None, "", genre, "", "", code)
        return {"plateforme": code, "total": len(items), "transactions": [vue_plateforme(p) for p in items[:limite]]}
