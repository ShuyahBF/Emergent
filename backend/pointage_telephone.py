# pointage_telephone.py — Lot 496 : POINTAGE D'INVENTAIRE PAR TÉLÉPHONE (logique pure, sans accès réseau ni base : testable seule).
#
# Demande du propriétaire (28/11/2026) : « Le pointage est manuel, ce qui est fastidieux… Les utilisateurs, depuis leur téléphone, donnent un
# numéro de ligne + quantité + date de péremption et disent "suivant" ; tu enregistres et attends la prochaine communication. »
#
# Déroulé (pour un développeur WinDev : c'est l'équivalent d'une saisie en table sur plusieurs postes, consolidée à la fin) :
#   1. CRÉATION (administrateur, Paramètres) : structure = fiche « clé client » de SAWALI (clé de suivi), export JSON d'Aizenta
#      (REQ_DétailInventaire), lieux de stockage. Chaque lieu est rattaché, au choix, à la colonne Aizenta « INV SV » (ISalle) ou
#      « INV Mag » (IMagasin) : Aizenta n'a que ces deux colonnes. SAWALI attribue un numéro (PT-0001…) et garde le code INVxxx.
#   2. POINTAGE (téléphones) : QR code → page /pointage/<jeton> ; prénom + lieu ; chaque saisie = {ligne, quantité, péremption ?}.
#      La même ligne saisie deux fois dans le même lieu S'ADDITIONNE (choix du propriétaire), avec une alerte.
#   3. CLÔTURE : export JSON au format WinDev, réimportable dans Aizenta (IMagasin, ISalle, Peremption1, Diff recalculé).
#
# Stockage : UNE fiche de la collection `settings` par inventaire (`_id = "pointage_inv:<id>"`) — aucune nouvelle collection
# (cluster MongoDB plein, règle 9). Les saisies sont gardées une à une (jamais de total écrasé) : les totaux sont recalculés.
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

PREFIXE_ID = "pointage_inv:"          # _id des fiches d'inventaire dans `settings`
ID_COMPTEUR = "pointage_inv_compteur"  # fiche du compteur des numéros PT-0001…
CLE_TABLE = "REQ_DétailInventaire"
COLONNES = {"SV": "ISalle", "MG": "IMagasin"}   # colonne choisie pour un lieu → champ du JSON Aizenta
MAX_LIGNES = 5000          # garde-fou : taille d'une fiche MongoDB (16 Mo)
MAX_SAISIES = 30000
MAX_LIEUX = 8
MAX_QUANTITE = 1_000_000
DUREE_JETON_JOURS = 3      # le QR code expire de lui-même (et à la clôture)
LIEUX_DEFAUT = [{"nom": "Salle de vente", "colonne": "SV"}, {"nom": "Magasin", "colonne": "MG"}]


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Création
# ---------------------------------------------------------------------------
def valider_lieux(lieux: Any) -> List[Dict[str, str]]:
    """Lieux de stockage saisis à la création : 1 à 8 noms distincts, chacun rattaché à SV ou MG. Lève ValueError (message clair)."""
    if not lieux:
        lieux = LIEUX_DEFAUT
    if not isinstance(lieux, list) or len(lieux) > MAX_LIEUX:
        raise ValueError(f"1 à {MAX_LIEUX} lieux de stockage attendus")
    propres, vus = [], set()
    for i, l in enumerate(lieux):
        nom = re.sub(r"\s+", " ", str((l or {}).get("nom") or "")).strip()[:40]
        colonne = str((l or {}).get("colonne") or "").upper()
        if not nom:
            raise ValueError(f"lieu n° {i + 1} sans nom")
        if colonne not in COLONNES:
            raise ValueError(f"lieu « {nom} » : colonne Aizenta SV (salle de vente) ou MG (magasin) attendue")
        if nom.lower() in vus:
            raise ValueError(f"lieu « {nom} » en double")
        vus.add(nom.lower())
        propres.append({"id": f"L{i + 1}", "nom": nom, "colonne": colonne})
    return propres


def code_inventaire(nom_fichier: Optional[str]) -> Optional[str]:
    """« InventaireSélectionné_PPH_INV069.json » → « INV069 »."""
    m = re.search(r"INV\s*0*(\d+)", nom_fichier or "", re.IGNORECASE)
    return f"INV{int(m.group(1)):03d}" if m else None


def code_base(nom_fichier: Optional[str]) -> Optional[str]:
    """« InventaireSélectionné_PPH_INV069.json » → « PPH » (base HFSQL du client)."""
    m = re.search(r"_([A-Za-z]{2,6})_INV\d+", nom_fichier or "")
    return m.group(1).upper() if m else None


def valider_export(export: Any) -> List[dict]:
    """Contrôle l'export Aizenta : tableau REQ_DétailInventaire, Chrono entiers et uniques. Lève ValueError."""
    lignes = export.get(CLE_TABLE) if isinstance(export, dict) else None
    if not isinstance(lignes, list) or not lignes:
        raise ValueError(f"JSON d'inventaire attendu : tableau « {CLE_TABLE} » absent ou vide")
    if len(lignes) > MAX_LIGNES:
        raise ValueError(f"{len(lignes)} lignes : {MAX_LIGNES} au plus")
    vus = set()
    for x in lignes:
        if not isinstance(x, dict) or not isinstance(x.get("Chrono"), int) or isinstance(x.get("Chrono"), bool):
            raise ValueError("chaque ligne du JSON doit avoir un « Chrono » (N° d'ordre) entier")
        if x["Chrono"] in vus:
            raise ValueError(f"N° d'ordre {x['Chrono']} en double dans le JSON")
        vus.add(x["Chrono"])
    return lignes


def nouveau_jeton() -> Tuple[str, str]:
    """Jeton du QR code (long, aléatoire) et sa date d'expiration ISO."""
    return secrets.token_urlsafe(24), (maintenant() + timedelta(days=DUREE_JETON_JOURS)).isoformat()


def creer_inventaire(*, ident: str, numero: str, structure: Dict[str, Any], lieux: Any, export: Any,
                     nom_fichier: Optional[str], par: str) -> Dict[str, Any]:
    """Fiche complète d'un nouvel inventaire (prête à être insérée dans `settings`)."""
    lignes = valider_export(export)
    jeton, expire = nouveau_jeton()
    return {
        "_id": PREFIXE_ID + ident, "id": ident, "numero": numero,
        "code_inv": code_inventaire(nom_fichier), "base": code_base(nom_fichier), "nom_fichier": (nom_fichier or "")[:160],
        "structure": {"id": structure.get("id"), "code": structure.get("code"), "libelle": structure.get("libelle")},
        "lieux": valider_lieux(lieux), "etat": "ouvert",
        "jeton": jeton, "jeton_expire": expire,
        "cree_le": maintenant().isoformat(), "cree_par": par,
        "lignes_total": len(lignes),      # gardé à part : la liste des inventaires ne relit jamais l'export complet
        "export": export,                 # export d'origine, rendu complété à la clôture (jamais modifié)
        "saisies": [],                    # une entrée par saisie validée au téléphone
    }


def numero_suivant(valeur: int) -> str:
    return f"PT-{int(valeur):04d}"


# ---------------------------------------------------------------------------
# Saisie au téléphone
# ---------------------------------------------------------------------------
def peremption_hfsql(texte: Any) -> Optional[str]:
    """« 2027-03 », « 03/2027 », « 3/27 », « 202703 », « 20270301 » → « 20270301 ». None si vide ; ValueError si invalide."""
    if texte in (None, ""):
        return None
    t = str(texte).strip()
    # Trois écritures admises, essayées dans l'ordre : année-mois, mois/année, AAAAMM(JJ)
    if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})", t):
        annee, mois = int(m.group(1)), int(m.group(2))
    elif m := re.fullmatch(r"(\d{1,2})[-/. ](\d{2}|\d{4})", t):
        mois, annee = int(m.group(1)), int(m.group(2))
    elif m := re.fullmatch(r"(\d{4})(\d{2})(?:\d{2})?", t):
        annee, mois = int(m.group(1)), int(m.group(2))
    else:
        raise ValueError(f"péremption « {t} » illisible (mois/année attendus)")
    if annee < 100:
        annee += 2000
    if not (1 <= mois <= 12 and 2000 <= annee <= 2099):
        raise ValueError(f"péremption « {t} » invalide")
    return f"{annee:04d}{mois:02d}01"


def nettoyer_prenom(prenom: Any) -> str:
    """Prénom déclaré par l'auxiliaire (non vérifiable : simple indication, affichée comme telle)."""
    p = re.sub(r"[^\w\s'\-]", "", str(prenom or ""), flags=re.UNICODE)
    p = re.sub(r"\s+", " ", p).strip()[:30]
    if len(p) < 2:
        raise ValueError("prénom de 2 lettres au moins attendu")
    return p


def nettoyer_saisie(s: Any, *, lieux: List[dict], chronos: set) -> Dict[str, Any]:
    """Valide UNE saisie reçue du téléphone. Lève ValueError (message clair, renvoyé au téléphone)."""
    if not isinstance(s, dict):
        raise ValueError("saisie illisible")
    uid = str(s.get("uid") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{8,64}", uid):
        raise ValueError("identifiant de saisie manquant")
    lieu = str(s.get("lieu") or "")
    if lieu not in {l["id"] for l in lieux}:
        raise ValueError("lieu de stockage inconnu")
    try:
        chrono = int(s.get("chrono"))
        qte = int(s.get("qte"))
    except (TypeError, ValueError):
        raise ValueError("ligne et quantité doivent être des nombres entiers")
    if chrono not in chronos:
        raise ValueError(f"ligne {chrono} absente de cet inventaire")
    if not (0 <= qte <= MAX_QUANTITE):
        raise ValueError("quantité hors limites")
    return {"uid": uid, "chrono": chrono, "qte": qte, "lieu": lieu,
            "peremption": peremption_hfsql(s.get("peremption")),
            "texte": str(s.get("texte") or "")[:120]}   # phrase dictée, gardée pour le contrôle


# ---------------------------------------------------------------------------
# Consolidation (lecture seule) : totaux par ligne, avancement, alertes
# ---------------------------------------------------------------------------
def _actives(doc: dict) -> List[dict]:
    return [s for s in (doc.get("saisies") or []) if not s.get("annulee")]


def totaux_par_ligne(doc: dict) -> Dict[int, Dict[str, Any]]:
    """{chrono: {"SV": n, "MG": n, "par_lieu": {L1: n}, "peremption": "AAAAMM01" la plus proche, "nb": saisies, "par": {prénoms}}}."""
    colonne = {l["id"]: l["colonne"] for l in doc.get("lieux") or []}
    t: Dict[int, Dict[str, Any]] = {}
    for s in _actives(doc):
        x = t.setdefault(s["chrono"], {"SV": 0, "MG": 0, "par_lieu": {}, "peremption": None, "nb": 0, "par": set(), "doublon": False})
        if s["lieu"] in x["par_lieu"]:
            x["doublon"] = True                       # même ligne, même lieu : additionnée (choix du propriétaire), signalée
        x["par_lieu"][s["lieu"]] = x["par_lieu"].get(s["lieu"], 0) + s["qte"]
        x[colonne.get(s["lieu"], "MG")] += s["qte"]
        x["nb"] += 1
        x["par"].add(s.get("prenom") or "?")
        p = s.get("peremption")
        if p and (x["peremption"] is None or p < x["peremption"]):
            x["peremption"] = p                       # deux péremptions : on garde la plus proche (règle client du 29/09/2026)
    return t


def etat(doc: dict, *, aujourd_hui: Optional[datetime] = None) -> Dict[str, Any]:
    """Avancement et alertes affichés au responsable (aucune écriture)."""
    jour = (aujourd_hui or maintenant()).strftime("%Y%m01")
    dans_3_mois = ((aujourd_hui or maintenant()) + timedelta(days=92)).strftime("%Y%m01")
    lignes = (doc.get("export") or {}).get(CLE_TABLE) or []
    t = totaux_par_ligne(doc)
    actives = _actives(doc)
    lieux = doc.get("lieux") or []
    par_lieu = {l["id"]: {"lieu": l["nom"], "colonne": l["colonne"], "lignes": 0, "saisies": 0, "quantite": 0} for l in lieux}
    for s in actives:
        p = par_lieu.get(s["lieu"])
        if p:
            p["saisies"] += 1
            p["quantite"] += s["qte"]
    for x in t.values():
        for lid in x["par_lieu"]:
            if lid in par_lieu:
                par_lieu[lid]["lignes"] += 1
    par_auxiliaire: Dict[str, Dict[str, Any]] = {}
    for s in actives:
        a = par_auxiliaire.setdefault(s.get("prenom") or "?", {"prenom": s.get("prenom") or "?", "saisies": 0, "derniere": None})
        a["saisies"] += 1
        a["derniere"] = max(a["derniere"] or "", s.get("le") or "")
    detail, alertes = [], []
    for x in lignes:
        c = x["Chrono"]
        tot = t.get(c)
        avant = int(x.get("StockAvant_SV") or 0) + int(x.get("StockAvant_MG") or 0)
        compte = (tot["SV"] + tot["MG"]) if tot else None
        ligne = {"chrono": c, "libelle": x.get("Libellé"), "mesure": x.get("Mesure"), "avant": avant,
                 "sv": tot["SV"] if tot else None, "mg": tot["MG"] if tot else None, "compte": compte,
                 "ecart": (compte - avant) if tot else None, "peremption": tot["peremption"] if tot else None,
                 "saisies": tot["nb"] if tot else 0, "par": sorted(tot["par"]) if tot else []}
        detail.append(ligne)
        if not tot:
            continue
        if tot["doublon"]:
            alertes.append({"type": "doublon", "chrono": c, "libelle": x.get("Libellé"),
                            "message": "saisie plusieurs fois dans le même lieu : quantités additionnées, à vérifier"})
        if tot["peremption"] and tot["peremption"] < jour:
            alertes.append({"type": "perime", "chrono": c, "libelle": x.get("Libellé"), "message": "produit PÉRIMÉ"})
        elif tot["peremption"] and tot["peremption"] < dans_3_mois:
            alertes.append({"type": "proche", "chrono": c, "libelle": x.get("Libellé"), "message": "péremption dans moins de 3 mois"})
        if abs(compte - avant) >= max(10, abs(avant) // 2):
            alertes.append({"type": "ecart", "chrono": c, "libelle": x.get("Libellé"),
                            "message": f"écart important : {compte} compté(s) pour {avant} attendu(s)"})
    comptees = sum(1 for d in detail if d["compte"] is not None)
    return {
        "lignes_total": len(lignes), "lignes_comptees": comptees,
        "progression": round(100 * comptees / len(lignes), 1) if lignes else 0,
        "saisies": len(actives), "annulees": len(doc.get("saisies") or []) - len(actives),
        "par_lieu": list(par_lieu.values()), "par_auxiliaire": sorted(par_auxiliaire.values(), key=lambda a: -a["saisies"]),
        "alertes": alertes, "lignes": detail,
    }


# ---------------------------------------------------------------------------
# Export au format WinDev (réimportable dans Aizenta)
# ---------------------------------------------------------------------------
def exporter(doc: dict, *, quand: Optional[datetime] = None) -> Dict[str, Any]:
    """JSON complété : IMagasin / ISalle = sommes des lieux rattachés, Peremption1 = la plus proche, Diff recalculé,
    Saisie_par / DH_Saisie sur les lignes pointées. Les lignes non pointées restent STRICTEMENT identiques à l'export d'origine."""
    import copy
    sortie = copy.deepcopy(doc.get("export") or {})
    t = totaux_par_ligne(doc)
    horodatage = (quand or maintenant()).strftime("%Y%m%d%H%M%S%f")[:17]   # AAAAMMJJHHMMSSmmm, comme WinDev
    for x in sortie.get(CLE_TABLE) or []:
        tot = t.get(x["Chrono"])
        if not tot:
            continue
        x["IMagasin"] = tot["MG"]
        x["ISalle"] = tot["SV"]
        if tot["peremption"]:
            existante = str(x.get("Peremption1") or "").strip()
            if not (re.fullmatch(r"\d{8}", existante) and existante < tot["peremption"]):
                x["Peremption1"] = tot["peremption"]
        x["Diff"] = (x.get("IMagasin") or 0) + (x.get("ISalle") or 0) - (x.get("StockAvant_SV") or 0) - (x.get("StockAvant_MG") or 0)
        x["Saisie_par"] = ", ".join(sorted(tot["par"]))[:50]
        x["DH_Saisie"] = horodatage
    return sortie


def nom_export(doc: dict) -> str:
    """Nom du fichier rendu : celui d'origine suivi de « .pointe.json » (l'export d'origine n'est jamais écrasé)."""
    base = re.sub(r"\.json$", "", doc.get("nom_fichier") or "", flags=re.IGNORECASE) or f"Inventaire_{doc.get('numero')}"
    return f"{base}.pointe.json"


def fiche_liste(doc: dict) -> Dict[str, Any]:
    """Résumé d'un inventaire pour la liste (sans l'export ni les saisies)."""
    total = doc.get("lignes_total") or len((doc.get("export") or {}).get(CLE_TABLE) or [])
    comptees = len({s["chrono"] for s in _actives(doc)})
    return {k: doc.get(k) for k in ("id", "numero", "code_inv", "base", "structure", "lieux", "etat", "cree_le", "cree_par", "cloture_le", "jeton_expire")} | {
        "lignes_total": total, "lignes_comptees": comptees,
        "progression": round(100 * comptees / total, 1) if total else 0,
    }


def jeton_valide(doc: Optional[dict], *, quand: Optional[datetime] = None) -> bool:
    """Le QR code n'ouvre le pointage que si l'inventaire est ouvert et le jeton non expiré."""
    if not doc or doc.get("etat") != "ouvert":
        return False
    try:
        return datetime.fromisoformat(doc.get("jeton_expire")) > (quand or maintenant())
    except (TypeError, ValueError):
        return False
