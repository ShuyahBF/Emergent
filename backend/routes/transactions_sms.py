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


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# NUMÉROS DE TÉLÉPHONE AVEC INDICATIFS DES PAYS (lot 389.2). Forme de référence (« canonique ») = chiffres internationaux sans « + » : indicatif + numéro national,
# ex. 22670112233 (Burkina Faso), 2250712345678 (Côte d'Ivoire), 33612345678 (France). Les deux côtés (SMS et association saisie) passent par la MÊME normalisation.
# ---------------------------------------------------------------------------------------------------------------------------------------------------
INDICATIF_DEFAUT = "226"      # Burkina Faso : pays des numéros écrits sans indicatif
# lg = longueurs acceptées du numéro national ; tronc0 = le « 0 » de tête (préfixe national) est supprimé (ex. France 06 12… → 6 12…)
PAYS: List[Dict[str, Any]] = [
    {"code": "BF", "nom": "Burkina Faso", "ind": "226", "lg": [8], "tronc0": False},
    {"code": "CI", "nom": "Côte d'Ivoire", "ind": "225", "lg": [8, 10], "tronc0": False},
    {"code": "ML", "nom": "Mali", "ind": "223", "lg": [8], "tronc0": False},
    {"code": "NE", "nom": "Niger", "ind": "227", "lg": [8], "tronc0": False},
    {"code": "TG", "nom": "Togo", "ind": "228", "lg": [8], "tronc0": False},
    {"code": "BJ", "nom": "Bénin", "ind": "229", "lg": [8, 10], "tronc0": False},
    {"code": "SN", "nom": "Sénégal", "ind": "221", "lg": [9], "tronc0": False},
    {"code": "GN", "nom": "Guinée", "ind": "224", "lg": [9], "tronc0": False},
    {"code": "GH", "nom": "Ghana", "ind": "233", "lg": [9], "tronc0": True},
    {"code": "NG", "nom": "Nigeria", "ind": "234", "lg": [10], "tronc0": True},
    {"code": "CM", "nom": "Cameroun", "ind": "237", "lg": [9], "tronc0": False},
    {"code": "GA", "nom": "Gabon", "ind": "241", "lg": [8, 9], "tronc0": False},
    {"code": "CG", "nom": "Congo", "ind": "242", "lg": [9], "tronc0": False},
    {"code": "CD", "nom": "RD Congo", "ind": "243", "lg": [9], "tronc0": True},
    {"code": "MA", "nom": "Maroc", "ind": "212", "lg": [9], "tronc0": True},
    {"code": "DZ", "nom": "Algérie", "ind": "213", "lg": [9], "tronc0": True},
    {"code": "TN", "nom": "Tunisie", "ind": "216", "lg": [8], "tronc0": False},
    {"code": "FR", "nom": "France", "ind": "33", "lg": [9], "tronc0": True},
    {"code": "BE", "nom": "Belgique", "ind": "32", "lg": [8, 9], "tronc0": True},
    {"code": "CH", "nom": "Suisse", "ind": "41", "lg": [9], "tronc0": True},
    {"code": "DE", "nom": "Allemagne", "ind": "49", "lg": [10, 11], "tronc0": True},
    {"code": "GB", "nom": "Royaume-Uni", "ind": "44", "lg": [10], "tronc0": True},
    {"code": "ES", "nom": "Espagne", "ind": "34", "lg": [9], "tronc0": False},
    {"code": "IT", "nom": "Italie", "ind": "39", "lg": [9, 10], "tronc0": False},
    {"code": "CA", "nom": "Canada / États-Unis", "ind": "1", "lg": [10], "tronc0": False},
    {"code": "CN", "nom": "Chine", "ind": "86", "lg": [11], "tronc0": False},
]
_PAYS_PAR_IND = {p["ind"]: p for p in PAYS}


def _pays_par_prefixe(chiffres: str) -> Optional[Dict[str, Any]]:
    """Pays dont l'indicatif commence ces chiffres (le plus long d'abord : 226 avant 22…, 1 en dernier)."""
    for n in (3, 2, 1):
        pays = _PAYS_PAR_IND.get(chiffres[:n])
        if pays:
            return pays
    return None


def _national(pays: Dict[str, Any], national: str) -> Optional[str]:
    """Numéro national nettoyé (« 0 » de tête retiré si le pays le veut) ; None si sa longueur n'est pas celle du pays."""
    if pays["tronc0"] and national.startswith("0"):
        national = national[1:]
    return national if len(national) in pays["lg"] else None


def normaliser_numero(texte: str, indicatif_defaut: str = INDICATIF_DEFAUT) -> Optional[str]:
    """Numéro saisi ou lu → forme canonique (indicatif + numéro national, chiffres seulement), ou None s'il est invalide.
    « +226 70 11 22 33 », « 00226 70112233 », « 226 70 11 22 33 », « 70 11 22 33 » (indicatif par défaut), « +33 6 12 34 56 78 », « 06 12 34 56 78 » avec indicatif_defaut=33…"""
    brut = (texte or "").strip()
    chiffres = re.sub(r"\D", "", brut)
    if not chiffres:
        return None
    if brut.startswith("+") or chiffres.startswith("00"):                       # indicatif écrit : international
        chiffres = chiffres[2:] if (not brut.startswith("+") and chiffres.startswith("00")) else chiffres
        pays = _pays_par_prefixe(chiffres)
        if pays:
            national = _national(pays, chiffres[len(pays["ind"]):])
            return pays["ind"] + national if national else None
        return chiffres if 8 <= len(chiffres) <= 15 else None                  # pays hors liste : accepté tel quel
    defaut = _PAYS_PAR_IND.get(indicatif_defaut) or _PAYS_PAR_IND[INDICATIF_DEFAUT]
    local = _national(defaut, chiffres)                                           # numéro du pays choisi, sans indicatif
    if local:
        return defaut["ind"] + local
    pays = _pays_par_prefixe(chiffres)                                            # sans « + » mais avec un indicatif connu (ex. 22670112233)
    if pays:
        national = _national(pays, chiffres[len(pays["ind"]):])
        if national:
            return pays["ind"] + national
    return None


def formater_numero(canon: Optional[str]) -> str:
    """22670112233 → « +226 70 11 22 33 » (groupes de deux chiffres en partant de la droite)."""
    if not canon:
        return ""
    pays = _pays_par_prefixe(canon)
    ind = pays["ind"] if pays else ""
    reste = canon[len(ind):]
    groupes: List[str] = []
    while reste:
        groupes.insert(0, reste[-2:])
        reste = reste[:-2]
    return "+" + ind + " " + " ".join(groupes)


_TRANSACTION = re.compile(r"trans(?:action)?\s*id\s*:?\s*\S+", re.I)
_SOLDE = re.compile(r"solde[^.\n]*", re.I)
# local (Burkina) : 8 chiffres, le premier entre 0 et 7, avec ou sans indicatif 226 (ex. 71828394, 70 11 22 33, +226 70 11 22 33)
_TELEPHONE = re.compile(r"(?<![\d.,])(?:(?:\+|00)?226[\s.\-]?)?([0-7]\d(?:[\s.\-]?\d\d){3})(?![\d])")
# international : « + » ou « 00 », puis indicatif et numéro (ex. +33 6 12 34 56 78, 00225 07 12 34 56 78)
_INTERNATIONAL = re.compile(r"(?<![\d.,])((?:\+|00)\d{1,3}(?:[\s.\-]?\d){7,12})(?![\d])")
_MONNAIE_APRES = re.compile(r"\s*(?:fcfa|f\s?cfa|xof|cfa)\b", re.I)


def numero_de(corps: str) -> Optional[str]:
    """Numéro de téléphone lu dans le texte du SMS, en forme canonique (indicatif + numéro), ou None. Un numéro écrit sans indicatif est celui du Burkina Faso (226).
    On écarte le numéro de transaction, la phrase du solde et tout nombre suivi de « FCFA » (un montant)."""
    t = _SOLDE.sub(" ", _TRANSACTION.sub(" ", corps or ""))
    trouves = []
    for m in _INTERNATIONAL.finditer(t):                                            # avec indicatif : prioritaire, s'il est valide
        canon = normaliser_numero(m.group(1))
        if canon and not _MONNAIE_APRES.match(t, m.end()):
            trouves.append((m.start(), canon))
    for m in _TELEPHONE.finditer(t):
        if not _MONNAIE_APRES.match(t, m.end()):
            trouves.append((m.start(), INDICATIF_DEFAUT + re.sub(r"\D", "", m.group(1))))
    return min(trouves)[1] if trouves else None


_DE_NUMERO_NOM = re.compile(r"\b(?:du|de|from)\s+(?:\+?226[\s.\-]?)?(\d{2}(?:[\s.\-]?\d\d){3})\s*[,;:\-]\s*([^.\n]{2,40})", re.I)


def tiers_de(corps: str, tiers: str) -> str:
    """Nom de l'expéditeur : si le SMS dit « … du 71828394,awa. » on prend « awa » (la lecture du téléphone peut avoir retenu un morceau de phrase) ; sinon le nom enregistré."""
    m = _DE_NUMERO_NOM.search(corps or "")
    return m.group(2).strip().rstrip(".,;") if m else tiers


def cle_lien(texte: str, indicatif: str = INDICATIF_DEFAUT) -> Tuple[str, str]:
    """Clé d'association saisie par l'administrateur : un NUMÉRO (forme canonique, avec l'indicatif du pays choisi si la saisie n'en porte pas) ou un NOM (normalisé).
    Lève ValueError si la saisie est vide ou si le numéro n'a pas la longueur de son pays."""
    brut = (texte or "").strip()
    chiffres = re.sub(r"\D", "", brut)
    if chiffres and re.fullmatch(r"[\d\s+().\-]+", brut):                      # que des chiffres et séparateurs : c'est un numéro
        canon = normaliser_numero(brut, indicatif)
        if not canon:
            raise ValueError("Numéro invalide pour ce pays : vérifiez le nombre de chiffres ou écrivez-le avec son indicatif (ex. +226 70 11 22 33)")
        return "numero", canon
    nom = normaliser(brut)
    if len(nom) < 3:
        raise ValueError("Saisissez un numéro (avec ou sans indicatif) ou un nom d'au moins 3 caractères")
    return "nom", nom[:80]


def cle_canonique(lien: Dict[str, Any]) -> str:
    """Clé d'un lien déjà enregistré : les anciens liens (lot 389) portent 8 chiffres sans indicatif = Burkina Faso."""
    cle = lien.get("cle") or ""
    return INDICATIF_DEFAUT + cle if lien.get("type") == "numero" and len(cle) == 8 else cle


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
    """Ajoute à une transaction son opérateur, le numéro lu dans le SMS et l'association éventuelle : une PLATEFORME (code d'émetteur) et / ou un CLIENT de SAWALI."""
    numero = numero_de(p.get("corps") or "")
    tiers = tiers_de(p.get("corps") or "", p.get("tiers") or "")
    nom = normaliser(tiers)
    lien = next((l for l in liens if (l["type"] == "numero" and numero and cle_canonique(l) == numero) or (l["type"] == "nom" and nom and l["cle"] == nom)), None)
    return {**p, "tiers": tiers, "operateur": operateur_de(p.get("adresse"), p.get("corps")), "numero": numero, "numero_affiche": formater_numero(numero),
            "plateforme": (lien or {}).get("plateforme") or None, "client_id": (lien or {}).get("client_id") or None,
            "client_nom": (lien or {}).get("client_nom") or None, "lien_libelle": lien["libelle"] if lien else None,
            "associe": bool(lien)}


def filtrer(items: List[Dict[str, Any]], du_ms: Optional[int] = None, au_ms: Optional[int] = None, operateur: str = "", genre: str = "",
            q: str = "", source: str = "", plateforme: str = "") -> List[Dict[str, Any]]:
    """Transactions (déjà enrichies) qui satisfont TOUS les critères, du plus récent au plus ancien. `au_ms` est exclu ; `plateforme` = code d'émetteur, « client:<id> » (client de SAWALI), « *lie » (toute
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
        if plateforme == "*lie" and not p.get("associe"):
            continue
        if plateforme == "*non_lie" and p.get("associe"):
            continue
        if plateforme.startswith("client:") and p.get("client_id") != plateforme[7:]:
            continue
        if plateforme and not plateforme.startswith(("*", "client:")) and p.get("plateforme") != plateforme:
            continue
        if mots:
            botte = normaliser(" ".join([p.get("tiers") or "", p.get("reference") or "", p.get("adresse") or "", p.get("numero") or "", p.get("numero_affiche") or "", p.get("corps") or ""]))
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
                    p["montant"], p.get("tiers") or "", p.get("numero_affiche") or "", p.get("solde") if p.get("solde") is not None else "", p.get("reference") or "",
                    p.get("plateforme") or "", p.get("client_nom") or p.get("lien_libelle") or ""])
    return "﻿" + sortie.getvalue()


def vue_plateforme(p: Dict[str, Any]) -> Dict[str, Any]:
    """Ce que reçoit une plateforme : champs structurés SEULEMENT (jamais le texte du SMS ni l'expéditeur brut)."""
    return {"id": p["k"], "recu_le": datetime.fromtimestamp(p["ms"] / 1000, timezone.utc).isoformat(), "sens": "entree" if p["genre"] == "RECETTE" else "sortie",
            "montant": p["montant"], "tiers": p.get("tiers") or "", "numero": p.get("numero_affiche") or None, "reference": p.get("reference"),
            "operateur": p["operateur"], "client": p.get("lien_libelle") or p.get("client_nom")}


def hacher_cle(cle: str) -> str:
    return hashlib.sha256((cle or "").encode()).hexdigest()


async def transactions_du_client(db, client_id: str) -> List[Dict[str, Any]]:
    """Lot 391 — paiements REÇUS (recettes) lus dans les SMS dont le numéro (ou le nom) est associé à ce CLIENT de SAWALI : de quoi alimenter son historique de
    paiements sans les ressaisir. Chaque élément porte `k` (identité de la transaction, sert à ne l'utiliser qu'une fois). Lecture seule, du plus récent au plus ancien."""
    config = await db.settings.find_one({"_id": PREFIXE_CONFIG}) or {}
    liens = [l for l in (config.get("liens") or []) if l.get("client_id") == client_id]
    if not liens:
        return []
    sortie: List[Dict[str, Any]] = []
    async for doc in db.settings.find({"_id": {"$regex": r"^transactions-sms:\d{4}-\d{2}$"}}):
        sortie += [enrichir(p, liens) for p in doc.get("items") or [] if p.get("genre") == "RECETTE"]
    return sorted((p for p in sortie if p.get("associe")), key=lambda p: p["ms"], reverse=True)


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

    async def _clients() -> List[Dict[str, Any]]:
        """Clients de SAWALI (liste de « Clients » du menu) : identifiant, nom affiché et numéros connus (téléphone, WhatsApp)."""
        sortie = []
        async for u in db.users.find({"role": {"$in": ["client", "admin"]}, "email": {"$nin": ["admin@sawalismartsystems.com"]}},
                                     {"_id": 0, "id": 1, "full_name": 1, "company": 1, "phone": 1, "whatsapp_number": 1}):
            if u.get("id"):
                sortie.append({"id": u["id"], "nom": (u.get("company") or u.get("full_name") or u["id"]).strip(), "numeros": [x for x in (u.get("phone"), u.get("whatsapp_number")) if x]})
        return sorted(sortie, key=lambda c: c["nom"].lower())

    @api.get("/admin/transactions-sms/etat", tags=["Transactions SMS — écran"])
    async def etat(user: dict = Depends(get_current_user)):
        _admin(user)
        cfg = await _lire_config()
        return {"sources": [{k: s.get(k) for k in ("id", "nom", "dernier_envoi", "recues")} for s in cfg["sources"]], "liens": [{**l, "cle_affichee": formater_numero(cle_canonique(l)) if l["type"] == "numero" else l["cle"]} for l in cfg["liens"]],
                "plateformes": await _emetteurs(), "clients": [{"id": c["id"], "nom": c["nom"]} for c in await _clients()],
                "operateurs": OPERATEURS, "mois": await _mois_existants(),
                "pays": [{"code": x["code"], "nom": x["nom"], "ind": x["ind"]} for x in PAYS]}

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
        """Associe un numéro (ou un nom) à une PLATEFORME (émetteur) et / ou à un CLIENT de SAWALI. Au moins l'un des deux. Une plateforme liée à un client
        (champ client_id de son fiche d'émetteur) retrouve aussi les paiements des numéros associés à ce client."""
        _admin(user)
        corps = (await request.json()) or {}
        try:
            type_, cle = cle_lien(str(corps.get("cle") or ""), str(corps.get("pays") or INDICATIF_DEFAUT).lstrip("+"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        plateforme = str(corps.get("plateforme") or "").strip().lower()
        client_id = str(corps.get("client_id") or "").strip()
        if not plateforme and not client_id:
            raise HTTPException(status_code=422, detail="Choisissez une plateforme ou un client de SAWALI")
        if plateforme and plateforme not in {e["code"] for e in await _emetteurs()}:
            raise HTTPException(status_code=422, detail="Choisissez une plateforme de la liste")
        client = next((c for c in await _clients() if c["id"] == client_id), None) if client_id else None
        if client_id and not client:
            raise HTTPException(status_code=422, detail="Choisissez un client de la liste de SAWALI")
        libelle = str(corps.get("libelle") or "").strip()[:80] or (client["nom"] if client else plateforme)
        cfg = await _lire_config()
        if any(l["type"] == type_ and l["cle"] == cle for l in cfg["liens"]):
            raise HTTPException(status_code=409, detail="Ce numéro (ou ce nom) est déjà associé")
        lien = {"id": uuid.uuid4().hex[:10], "type": type_, "cle": cle, "plateforme": plateforme or None, "libelle": libelle}
        if client:
            lien.update({"client_id": client["id"], "client_nom": client["nom"]})
        cfg["liens"].append(lien)
        await _ecrire_config(cfg)
        return lien

    @api.get("/admin/transactions-sms/suggestions", tags=["Transactions SMS — écran"])
    async def suggestions(user: dict = Depends(get_current_user)):
        """Payeurs de numéro CONNU : numéros lus dans les SMS, pas encore associés, qui sont le téléphone ou le WhatsApp d'un client de SAWALI."""
        _admin(user)
        cfg = await _lire_config()
        par_numero: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for c in await _clients():
            for n in c["numeros"]:
                canon = normaliser_numero(n)
                if canon:
                    par_numero[canon].append(c)
        sortie: Dict[str, Dict[str, Any]] = {}
        for p in await _toutes(None, None, cfg["liens"]):
            if p.get("associe") or not p.get("numero") or p["numero"] not in par_numero:
                continue
            for c in par_numero[p["numero"]]:
                x = sortie.setdefault(p["numero"] + c["id"], {"numero": p["numero"], "numero_affiche": p.get("numero_affiche"), "client_id": c["id"], "client_nom": c["nom"], "nombre": 0, "total": 0})
                x["nombre"] += 1
                x["total"] += p["montant"] if p["genre"] == "RECETTE" else 0
        return {"suggestions": sorted(sortie.values(), key=lambda x: x["nombre"], reverse=True)}

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
        client_de_la_plateforme = emetteur.get("client_id")
        items = [p for p in filtrer(await _toutes(du_ms, None, cfg["liens"]), du_ms, None, "", genre, "", "", "")
                 if p.get("plateforme") == code or (client_de_la_plateforme and p.get("client_id") == client_de_la_plateforme)]
        return {"plateforme": code, "total": len(items), "transactions": [vue_plateforme(p) for p in items[:limite]]}
