"""OCR des « Listes de pointage » d'inventaire → complétion du JSON HFSQL.

Type de pièce « liste_pointage » de la page OCR sur Pièces.

Contexte : en début d'inventaire, WinDev imprime la « Liste pointage n° INVxxx
du JJ/MM/AAAA » et exporte le JSON de l'inventaire
(InventaireSélectionné_<BASE>_INVxxx.json, tableau « REQ_DétailInventaire »,
champs tels qu'en base HFSQL). Pendant le comptage, trois colonnes de la liste
sont remplies AU STYLO. On dépose ensuite le scan de la liste + le JSON, et ce
module reporte les valeurs lues dans le JSON :

    colonne de la liste (manuscrite)  →  champ du JSON
    INV Mag                           →  IMagasin     (entier)
    INV SV                            →  ISalle       (entier)
    Pérempt° (« __/__ »)              →  Peremption1  (« AAAAMM01 », vide = " ")
    N°Ordre (imprimé, dernière col.)  →  Chrono       (clé de rapprochement)

Sur chaque ligne complétée : Diff recalculé = (IMagasin + ISalle) −
(StockAvant_SV + StockAvant_MG) (formule vérifiée sur 100 % des lignes de deux
exports réels), Saisie_par = « Claude », DH_Saisie = date/heure du traitement
(format WinDev AAAAMMJJHHMMSSmmm) — choix du client (29/09/2026).

Rapprochement ligne lue → ligne du JSON. La liste déposée n'est pas toujours
celle exportée avec ce JSON (liste d'un autre inventaire, réimprimée…) : même
structure, presque les mêmes produits, mais des N° d'ordre décalés. Le N° seul
n'est donc pas fiable ; dans l'ordre :
  1. libellé + conditionnement identiques à une ligne du JSON → cette ligne
     (si le libellé existe plusieurs fois, le N° d'ordre départage) ;
  2. N° d'ordre dont le libellé est quasi identique (faute d'OCR) → cette ligne ;
  3. libellé approché d'UN seul produit, nettement devant le 2e → cette ligne,
     signalée à vérifier ;
  4. sinon : ligne non appliquée (produit absent du JSON, ou ambiguïté).

Garde-fous (un chiffre mal lu fausse directement le stock en base) :
  - aucune ligne appliquée sans concordance du libellé (voir ci-dessus) ;
  - cellule vide → champ inchangé (jamais 0 à la place d'un oubli) ;
  - péremption illisible / mois invalide → non reportée ; rature → reportée
    mais signalée ;
  - N° inconnu, N° lu deux fois, lignes absentes des scans (page oubliée),
    code INV du titre ≠ code du JSON, pied « Nombre de lignes » ≠ nombre de
    lignes du JSON, lignes rapprochées par libellé → signalés.
Validé sur INV067 (PPH) : 490 lignes imprimées, 490 Chrono, 100 % des
libellés concordants. Logique identique à scripts/inventaire/ocr_pointage.py
du dépôt ShuyahBF/Aizenta-Analyse-Qualit-Gestion-Stocks.

Aucune modification du module commun `ocr_core` : on réutilise son appel IA
(clé EMERGENT_LLM_KEY), son calcul de coût et son redimensionnement d'image,
mais la préparation diffère (toutes les pages, toujours en image : le PDF
d'origine contient du texte imprimé, mais c'est l'écriture manuscrite qu'on lit).

Sans scanner (lot 32) : les pages peuvent être photographiées au téléphone et
déposées ensemble ; `photos_en_pdf` les assemble en un seul PDF, analysé ensuite
comme un scan.
"""
from __future__ import annotations

import asyncio
import copy
import difflib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import ocr_core
from ocr_core.engine import call_llm, parse_json
from ocr_core.models import compute_cost, get_model
from ocr_core.prepare import IMAGE_MIMES, shrink_image

logger = logging.getLogger("sawali.ocr_pointage")

# Tableau racine de l'export WinDev.
CLE_TABLE = "REQ_DétailInventaire"
# Valeur HFSQL d'une péremption vide (un seul espace, constaté sur l'export).
PEREMPTION_VIDE = " "
# Valeur écrite dans Saisie_par sur chaque ligne complétée (choix du client).
SAISIE_PAR = "Claude"
# Rapprochement approché (faute d'OCR sur le libellé, ex. « ING » lu pour « INJ ») :
# similarité minimale, et écart minimal avec le 2e meilleur produit — sans cet
# écart, des voisins comme « SONDE D'INTUBATION N°6 » / « N°6,5 » seraient confondus.
SEUIL_APPROCHE = 0.90
MARGE_APPROCHE = 0.05
# Rendu des pages de PDF (redimensionnées ensuite par ocr_core à 1568 px).
PDF_RENDER_DPI = 200
# Garde-fou de coût : une liste de pointage fait ~15 pages pour 500 lignes.
MAX_PAGES = 60
# Pages analysées en parallèle (limite la charge sur le proxy IA).
PARALLELE = 4
# Photos de téléphone assemblées en PDF (lot 32) : plus grand côté conservé et
# qualité JPEG — assez pour relire l'écriture à l'écran, ~0,5 Mo par page.
PHOTO_MAX_PX = 2400
PHOTO_QUALITE = 85


# ---------------------------------------------------------------------------
# Consigne envoyée au modèle pour UNE page scannée
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """Tu es l'assistant OCR de SAWALI SMART SYSTEMS. Tu lis une page
scannée d'une « Liste pointage » d'inventaire de pharmacie, imprimée par un
logiciel puis complétée À LA MAIN pendant le comptage.

Colonnes imprimées, de gauche à droite :
  Libellé [Mesure/Cond.] | CIP | INV Mag | Px Public | INV SV | Pérempt° | N°Ordre

Libellé, Px Public et N°Ordre sont IMPRIMÉS. « INV Mag », « INV SV » et
« Pérempt° » (modèle imprimé « __/__ ») sont remplies au stylo.

Réponds UNIQUEMENT avec un objet JSON strict, sans texte avant ou après ni bloc
de code, au format :
{
  "titre": "<titre imprimé en haut de la page, ou null>",
  "compteur": "<nom(s) écrit(s) à la main en haut de la page (ex. « Dr Gacko / Inès »), ou null>",
  "nombre_de_lignes_pied": <nombre après « Nombre de lignes : » s'il figure sur la page, sinon null>,
  "annotations": ["<toute note manuscrite HORS des cellules du tableau, recopiée telle quelle (ex. « Sonde armée 7,5 => 9 »)>"],
  "lignes": [
    {"n_ordre": <entier imprimé en DERNIÈRE colonne, ou null si illisible>,
     "libelle": "<libellé imprimé, recopié tel quel avec [Mesure/Cond.]>",
     "inv_mag": <entier écrit à la main dans INV Mag, ou null>,
     "inv_sv": <entier écrit à la main dans INV SV, ou null>,
     "peremption": "<ce qui est écrit dans Pérempt°, format MM/AA, ou null si « __/__ » vide>",
     "incertain": <true si rature, surcharge ou chiffre douteux, sinon false>,
     "note": "<explication si incertain, sinon null>"}
  ]
}

Règles strictes :
- Une entrée par ligne du tableau, dans l'ordre, MÊME si rien n'y est écrit.
- Le N°Ordre est la clé de la ligne : lis-le avec le plus grand soin.
- Ne confonds pas les colonnes : le Px Public (imprimé, entre INV Mag et INV SV)
  n'est JAMAIS une quantité comptée.
- Cellule vide → null (pas 0).
- Conventions d'écriture des compteurs (constatées sur de vraies listes) :
  · ZÉRO (article compté, aucun en stock) s'écrit « 0 », « O », un cercle,
    « 00 », « ∞ » ou « OO » (deux zéros collés), un tiret « — » ou une barre
    « / » tracée dans la cellule de quantité → 0 ;
  · zéro en tête : « 07 » → 7, « 01 » → 1 ;
  · addition écrite « 8+1 » ou « 1+1 » → renvoie le TOTAL (9, 2) avec
    incertain=true et la note « écrit 8+1 » ;
  · péremption écrite « 2.27 », « 2/27 », « 12/29 », « 03.22 » → « MM/AA »
    (« 02/27 », « 12/29 », « 03/22 ») ; une barre tracée sur le modèle
    « __/__ » sans date → null ; une date déjà passée se recopie telle quelle ;
  · ignore les coches ✓ après le N°Ordre et les tampons.
- Un chiffre qui déborde sur la ligne voisine appartient à la ligne où il
  commence ; s'il y a un doute, incertain=true.
- Ne devine rien. Valeur raturée puis réécrite : prends la valeur FINALE,
  incertain=true, et explique dans note (ex. « 12 raturé en 15 »). Chiffre
  illisible : null, incertain=true, note."""


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------
@dataclass
class RapportPointage:
    lignes_json: int = 0
    lignes_lues: int = 0
    lignes_modifiees: int = 0
    code_inventaire: Optional[str] = None
    # {"page": "p.1", "compteur": "Dr Gacko / Inès"} — traçabilité de qui a compté quoi.
    compteurs: List[dict] = field(default_factory=list)
    # {"gravite": "bloquant" | "a_verifier", "type", "chrono", "page", "message", "details"}
    # type : absent, ambigu, homonymes, doublon, quantite_invalide, page_non_lue, titre,
    #        note, incertain, approche, conditionnement, peremption_invalide, couple,
    #        pied, par_libelle, manquantes (sert à regrouper le compte rendu détaillé).
    anomalies: List[dict] = field(default_factory=list)
    # {"chrono", "libelle", "champ", "avant", "apres", "page", "incertain", "n_ordre_liste", "rapprochement"}
    modifications: List[dict] = field(default_factory=list)
    # Chrono des lignes pointées (une valeur au moins a été lue et reportée).
    chronos_pointes: List[int] = field(default_factory=list)

    def ajouter(self, gravite: str, message: str, chrono=None, page=None, type: str = "autre",
                **details: Any) -> None:
        self.anomalies.append({"gravite": gravite, "type": type, "chrono": chrono, "page": page,
                               "message": message, "details": details})

    @property
    def nb_bloquants(self) -> int:
        return sum(1 for a in self.anomalies if a["gravite"] == "bloquant")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "lignes_json": self.lignes_json, "lignes_lues": self.lignes_lues,
            "lignes_modifiees": self.lignes_modifiees, "code_inventaire": self.code_inventaire,
            "compteurs": self.compteurs, "chronos_pointes": self.chronos_pointes,
            "nb_bloquants": self.nb_bloquants, "anomalies": self.anomalies,
            "modifications": self.modifications,
        }


# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    """Libellé normalisé : majuscules, sans « [Mesure] » imprimé, sans ponctuation."""
    s = re.sub(r"\s*\[.*$", "", s or "")
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _mesure_imprimee(libelle_lu: str) -> Optional[str]:
    """« SERINGUE 5ML [UNITE] » → « UNITE » (conditionnement imprimé entre crochets)."""
    m = re.search(r"\[([^\]]*)\]\s*$", libelle_lu or "")
    return m.group(1) if m else None


def _norm_mesure(mesure: Optional[str]) -> str:
    """Conditionnement normalisé ; « - » (non renseigné dans HFSQL) → ""."""
    return re.sub(r"[^A-Z0-9]", "", (mesure or "").upper())


def _mesures_compatibles(lue: Optional[str], json_mesure: Optional[str]) -> bool:
    """Conditionnements égaux, ou l'un des deux non renseigné."""
    a, b = _norm_mesure(lue), _norm_mesure(json_mesure)
    return not a or not b or a == b


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


class IndexInventaire:
    """Retrouve la ligne du JSON correspondant à une ligne lue sur la liste
    (règles 1 à 4 de la docstring du module)."""

    def __init__(self, lignes: List[dict]):
        self.lignes = lignes
        self.par_chrono = {l["Chrono"]: l for l in lignes}
        self.par_libelle: Dict[str, List[dict]] = {}
        for l in lignes:
            self.par_libelle.setdefault(_norm(l.get("Libellé", "")), []).append(l)

    def trouver(self, libelle_lu: str, n_ordre: Optional[int]) -> Tuple[Optional[dict], str, dict]:
        """Renvoie (ligne, méthode) avec méthode « numero », « libelle », « conditionnement »
        ou « approche »,
        ou (None, raison, infos) si aucune ligne ne peut être retenue sans risque ; infos =
        {"type": "absent"|"ambigu"|"homonymes"|"illisible", "candidats": [lignes du JSON]}."""
        cle, mesure = _norm(libelle_lu), _mesure_imprimee(libelle_lu)
        if not cle:
            return None, "libellé illisible", {"type": "illisible", "candidats": []}

        # 1. Libellé + conditionnement identiques.
        exacts = [l for l in self.par_libelle.get(cle, []) if _mesures_compatibles(mesure, l.get("Mesure"))]
        if len(exacts) > 1:
            exacts = [l for l in exacts if l["Chrono"] == n_ordre] or exacts
        if len(exacts) == 1:
            ligne = exacts[0]
            return ligne, "numero" if ligne["Chrono"] == n_ordre else "libelle", {}
        if len(exacts) > 1:
            numeros = ", ".join(str(l["Chrono"]) for l in exacts)
            return None, (f"libellé présent plusieurs fois dans le JSON (N° {numeros}), N° d'ordre lu "
                          "non concordant"), {"type": "homonymes", "candidats": exacts}
        # 1 bis. Libellé identique, conditionnement lu différent : le conditionnement est
        # souvent mal lu sur un scan (« [3/1] » pour « [B/1] ») ; accepté seulement si UN
        # seul produit porte ce libellé (sinon c'est lui qui départage, ex. AMPOULE 1.20M / 60CM).
        homonymes = self.par_libelle.get(cle, [])
        if len(homonymes) == 1:
            return homonymes[0], "conditionnement", {}

        # Scores de similarité (conditionnement compatible uniquement).
        scores = []
        for l in self.lignes:
            if not _mesures_compatibles(mesure, l.get("Mesure")):
                continue
            autre = _norm(l.get("Libellé", ""))
            if difflib.SequenceMatcher(None, cle, autre).quick_ratio() >= SEUIL_APPROCHE:
                scores.append((_ratio(cle, autre), l))
        scores.sort(key=lambda t: -t[0])
        meilleur = scores[0][0] if scores else 0.0

        # 2. N° d'ordre confirmé par un libellé quasi identique (et pas moins bon qu'un autre).
        par_numero = self.par_chrono.get(n_ordre) if n_ordre is not None else None
        if par_numero is not None and _mesures_compatibles(mesure, par_numero.get("Mesure")):
            r = _ratio(cle, _norm(par_numero.get("Libellé", "")))
            if r >= SEUIL_APPROCHE and r >= meilleur:
                return par_numero, "numero", {}

        # 3. Libellé approché d'un seul produit, nettement devant le 2e.
        if scores and meilleur >= SEUIL_APPROCHE:
            second = scores[1][0] if len(scores) > 1 else 0.0
            if meilleur - second >= MARGE_APPROCHE:
                return scores[0][1], "approche", {}
            candidats = " / ".join(f"N° {l['Chrono']} « {l.get('Libellé')} »" for _, l in scores[:2])
            return None, f"plusieurs produits proches dans le JSON ({candidats})", \
                {"type": "ambigu", "candidats": [l for _, l in scores[:3]]}

        # 4. Rien de sûr.
        return None, "aucun produit correspondant dans le JSON (nouveau produit ou libellé mal lu ?)", \
            {"type": "absent", "candidats": []}


def peremption_vers_hfsql(texte: Optional[str]) -> Optional[str]:
    """« 06/28 », « 6/28 », « 06-2028 », « 0628 » → « 20280601 ». None si invalide."""
    if not texte:
        return None
    t = str(texte).strip()
    m = re.fullmatch(r"(\d{1,2})\s*[/\-.\s]\s*(\d{2}|\d{4})", t) or re.fullmatch(r"(\d{2})(\d{2})", t)
    if not m:
        return None
    mois, annee = int(m.group(1)), int(m.group(2))
    if annee < 100:
        annee += 2000
    if not (1 <= mois <= 12 and 2000 <= annee <= 2099):
        return None
    return f"{annee:04d}{mois:02d}01"


def recalculer_diff(ligne: dict) -> None:
    """Diff = (IMagasin + ISalle) − (StockAvant_SV + StockAvant_MG), comme dans l'export."""
    ligne["Diff"] = (ligne.get("IMagasin") or 0) + (ligne.get("ISalle") or 0) \
        - (ligne.get("StockAvant_SV") or 0) - (ligne.get("StockAvant_MG") or 0)


def code_inventaire(texte: Optional[str]) -> Optional[str]:
    """« Liste pointage n° INV067 du … » ou « …_PPH_INV067.json » → « INV067 »."""
    m = re.search(r"INV\s*0*(\d+)", texte or "", re.IGNORECASE)
    return f"INV{int(m.group(1)):03d}" if m else None


def _entier(v: Any) -> Optional[int]:
    """Quantité lue → entier (le modèle peut renvoyer "12", 12.0 ou une addition
    écrite telle quelle « 8+1 » → 9) ; None si inexploitable."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, str) and re.fullmatch(r"\s*\d+(\s*\+\s*\d+)+\s*", v):
        return sum(int(x) for x in v.split("+"))
    try:
        f = float(str(v).replace(" ", "").replace(",", "."))
    except ValueError:
        return None
    return int(f) if f == int(f) else None


# ---------------------------------------------------------------------------
# JSON de l'inventaire : lecture / validation / écriture au format WinDev
# ---------------------------------------------------------------------------
def charger_json_inventaire(data: bytes) -> dict:
    """Décode et valide l'export WinDev. Lève ValueError avec un message clair."""
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Fichier JSON illisible : {exc}") from exc
    lignes = doc.get(CLE_TABLE) if isinstance(doc, dict) else None
    if not isinstance(lignes, list) or not lignes:
        raise ValueError(f"JSON d'inventaire attendu : tableau « {CLE_TABLE} » absent ou vide")
    if not all(isinstance(l, dict) and isinstance(l.get("Chrono"), int) for l in lignes):
        raise ValueError("Chaque ligne du JSON doit avoir un « Chrono » entier")
    return doc


def json_windev(doc: dict) -> bytes:
    """Même style que l'export WinDev : ASCII pur (accents en \\u00e9), ordre conservé."""
    return json.dumps(doc, ensure_ascii=True, separators=(", ", ":")).encode("ascii")


# ---------------------------------------------------------------------------
# Report des valeurs lues dans le JSON (aucun appel IA : testable seul)
# ---------------------------------------------------------------------------
def appliquer_lectures(data: dict, pages: List[dict], code_attendu: Optional[str] = None,
                       saisie_par: Optional[str] = SAISIE_PAR,
                       maintenant: Optional[datetime] = None) -> Tuple[dict, RapportPointage]:
    """Renvoie une COPIE du JSON complétée + le rapport. `data` n'est jamais modifié.

    pages : [{"page": "p.1", "titre", "nombre_de_lignes_pied", "lignes": [...]}]
    """
    data = copy.deepcopy(data)
    lignes = data[CLE_TABLE]
    index = IndexInventaire(lignes)
    rapport = RapportPointage(lignes_json=len(lignes))
    par_libelle = 0   # lignes retrouvées par libellé alors que le N° d'ordre diffère
    horodatage = (maintenant or datetime.now()).strftime("%Y%m%d%H%M%S%f")[:17]

    # --- En-tête / pied de page ---------------------------------------------
    titres = [p["titre"] for p in pages if p.get("titre")]
    if titres and not any("pointage" in t.lower() for t in titres):
        rapport.ajouter("bloquant", f"Le document ne semble pas être une liste de pointage (titre lu : « {titres[0]} »).",
                        type="titre")
    code_lu = next((code_inventaire(t) for t in titres if code_inventaire(t)), None)
    rapport.code_inventaire = code_lu or code_inventaire(code_attendu)
    if code_attendu and code_lu and code_inventaire(code_attendu) and code_lu != code_inventaire(code_attendu):
        # Pas bloquant : les lignes sont rapprochées par libellé (même structure, mêmes produits).
        rapport.ajouter("a_verifier", f"Liste {code_lu} ≠ JSON {code_inventaire(code_attendu)} : vérifier que "
                        "c'est bien le bon couple liste/JSON.", type="couple", liste=code_lu,
                        json=code_inventaire(code_attendu))
    pied = next((p["nombre_de_lignes_pied"] for p in pages if p.get("nombre_de_lignes_pied")), None)
    if pied is not None and pied != len(lignes):
        rapport.ajouter("a_verifier", f"Pied de page : {pied} lignes, JSON : {len(lignes)} lignes.", type="pied")

    # --- Compteurs et annotations libres (hors tableau) ------------------------
    for page in pages:
        if page.get("compteur"):
            rapport.compteurs.append({"page": page.get("page"), "compteur": page["compteur"]})
        for note in page.get("annotations") or []:
            if str(note).strip():
                rapport.ajouter("a_verifier", f"Note manuscrite hors tableau : « {note} » (à traiter à la main).",
                                page=page.get("page"), type="note", texte=str(note))

    # --- Report ligne à ligne -------------------------------------------------
    vus: Dict[int, str] = {}
    for page in pages:
        nom_page = page.get("page")
        for lu in page.get("lignes") or []:
            rapport.lignes_lues += 1
            libelle_lu = str(lu.get("libelle") or "")
            n_lu = _entier(lu.get("n_ordre"))
            cible, methode, echec = index.trouver(libelle_lu, n_lu)
            if cible is None:
                rapport.ajouter("bloquant", f"« {libelle_lu} » (N° {n_lu if n_lu is not None else '?'} sur la "
                                f"liste) non appliqué : {methode}.", n_lu, nom_page, type=echec["type"],
                                lu=libelle_lu, candidats=[{"chrono": c["Chrono"], "libelle": c.get("Libellé"),
                                                           "mesure": c.get("Mesure")} for c in echec["candidats"]])
                continue
            chrono = cible["Chrono"]
            if chrono in vus:
                rapport.ajouter("bloquant", f"« {cible.get('Libellé')} » lu deux fois ({vus[chrono]} et {nom_page}) : "
                                "seule la première lecture est appliquée.", chrono, nom_page, type="doublon",
                                lu=libelle_lu, pages=[vus[chrono], nom_page])
                continue
            vus[chrono] = nom_page
            if methode == "libelle":
                par_libelle += 1
            elif methode == "conditionnement":
                rapport.ajouter("a_verifier", f"« {libelle_lu} » : conditionnement différent du JSON "
                                f"(« {cible.get('Mesure')} ») — produit retenu car seul de ce nom, à confirmer.",
                                chrono, nom_page, type="conditionnement", lu=libelle_lu, mesure_json=cible.get("Mesure"))
            elif methode == "approche":
                rapport.ajouter("a_verifier", f"Libellé lu « {libelle_lu} » rapproché de « {cible.get('Libellé')} » "
                                f"(N° {n_lu} sur la liste) : à confirmer.", chrono, nom_page, type="approche",
                                lu=libelle_lu, libelle_json=cible.get("Libellé"))

            # Valeurs manuscrites → champs HFSQL. Cellule vide (None) = inchangé.
            nouvelles: Dict[str, Any] = {}
            invalide = False
            for cle_lue, champ in (("inv_mag", "IMagasin"), ("inv_sv", "ISalle")):
                if lu.get(cle_lue) is None:
                    continue
                q = _entier(lu[cle_lue])
                if q is None or q < 0:
                    rapport.ajouter("bloquant", f"Quantité {champ} invalide « {lu[cle_lue]} » : "
                                    "ligne non appliquée.", chrono, nom_page, type="quantite_invalide",
                                    lu=libelle_lu)
                    invalide = True
                    break
                nouvelles[champ] = q
            if invalide:
                continue
            if lu.get("peremption"):
                per = peremption_vers_hfsql(lu["peremption"])
                if per is None:
                    rapport.ajouter("a_verifier", f"Péremption illisible/invalide « {lu['peremption']} » : "
                                    "non reportée.", chrono, nom_page, type="peremption_invalide",
                                    libelle=cible.get("Libellé"), texte=lu["peremption"])
                else:
                    nouvelles["Peremption1"] = per

            for champ, valeur in nouvelles.items():
                if cible.get(champ) != valeur:
                    rapport.modifications.append({
                        "chrono": chrono, "libelle": cible.get("Libellé"), "champ": champ,
                        "avant": cible.get(champ), "apres": valeur, "page": nom_page,
                        "incertain": bool(lu.get("incertain")), "n_ordre_liste": n_lu,
                        "rapprochement": methode,
                    })
                    cible[champ] = valeur
            if lu.get("incertain"):
                rapport.ajouter("a_verifier", f"Lecture incertaine : {lu.get('note') or 'voir la liste'}.",
                                chrono, nom_page, type="incertain", libelle=cible.get("Libellé"),
                                note=lu.get("note"), valeurs=dict(nouvelles))
            # Ligne POINTÉE dès qu'une valeur a été lue, même identique à celle du JSON (un
            # « 0 » compté sur un JSON déjà à 0) : horodatée comme une saisie WinDev, sinon
            # « compté 0 » et « pas compté » seraient indiscernables.
            if nouvelles:
                rapport.lignes_modifiees += 1
                rapport.chronos_pointes.append(chrono)
                recalculer_diff(cible)
                if saisie_par:
                    cible["Saisie_par"] = saisie_par
                    cible["DH_Saisie"] = horodatage

    if par_libelle:
        rapport.ajouter("a_verifier", f"{par_libelle} ligne(s) retrouvée(s) par leur libellé : N° d'ordre de la "
                        "liste différents de ceux du JSON (liste d'un autre inventaire ?).", type="par_libelle",
                        nombre=par_libelle)

    # --- Lignes du JSON jamais retrouvées sur les scans -------------------------
    manquants = sorted(set(index.par_chrono) - set(vus))
    if manquants:
        extrait = ", ".join(map(str, manquants[:20])) + (" …" if len(manquants) > 20 else "")
        rapport.ajouter("a_verifier", f"{len(manquants)} ligne(s) du JSON non retrouvée(s) sur les scans "
                        f"(page manquante ?) : N° {extrait}.", type="manquantes", nombre=len(manquants))
    return data, rapport


# ---------------------------------------------------------------------------
# Compte rendu détaillé (texte), affiché en fin de traitement
# ---------------------------------------------------------------------------
# Au-delà, une rubrique est tronquée (le détail complet reste dans les alertes / le rapport).
MAX_PAR_RUBRIQUE = 15
# Champs affichés dans l'exemple de ligne complétée, dans cet ordre.
_CHAMPS_EXEMPLE = ("IMagasin", "ISalle", "Peremption1")


def _nom(texte: Optional[str]) -> str:
    """Libellé nettoyé pour l'affichage : sans « [Mesure] » ni espaces superflus."""
    return re.sub(r"\s+", " ", re.sub(r"\s*\[.*$", "", texte or "")).strip()


def _puces(lignes: List[str]) -> List[str]:
    """Liste à puces, tronquée à MAX_PAR_RUBRIQUE éléments."""
    out = [f"• {l}" for l in lignes[:MAX_PAR_RUBRIQUE]]
    if len(lignes) > MAX_PAR_RUBRIQUE:
        out.append(f"• … et {len(lignes) - MAX_PAR_RUBRIQUE} autre(s) (voir les alertes détaillées).")
    return out


def _valeurs(valeurs: Dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in valeurs.items()) or "rien reporté"


def synthese_detaillee(rapport: RapportPointage, avant: dict, apres: dict,
                       nb_pages: Optional[int] = None) -> str:
    """Compte rendu en français, rédigé à partir du rapport (sans appel IA : reproductible) :
    résultat global, lignes bloquées avec leur raison, points à vérifier regroupés par nature,
    et verdict sur la réimportation du JSON dans Aizenta."""
    lignes_avant = {l["Chrono"]: l for l in avant[CLE_TABLE]}
    lignes_apres = {l["Chrono"]: l for l in apres[CLE_TABLE]}
    pointes = set(rapport.chronos_pointes)
    par_type: Dict[str, List[dict]] = {}
    for a in rapport.anomalies:
        par_type.setdefault(a.get("type", "autre"), []).append(a)
    bloquants = [a for a in rapport.anomalies if a["gravite"] == "bloquant"]
    a_verifier = [a for a in rapport.anomalies if a["gravite"] == "a_verifier"]
    code = rapport.code_inventaire or "de l'inventaire"

    # --- Résultat ---------------------------------------------------------------
    txt = ["Résultat :"]
    sur = f" sur {nb_pages} page(s)" if nb_pages else ""
    res = [f"{rapport.lignes_lues} lignes lues{sur} : {len(pointes)} pointées "
           f"({len(rapport.modifications)} champs modifiés), {len(bloquants)} bloquée(s), "
           f"{len(a_verifier)} point(s) à vérifier."]
    n_lib = sum(a["details"].get("nombre", 0) for a in par_type.get("par_libelle", []))
    if n_lib:
        res.append(f"La liste ne porte pas les mêmes N° d'ordre que le JSON (liste d'un autre inventaire ?) : "
                   f"{n_lib} ligne(s) retrouvée(s) par leur libellé.")
    else:
        res.append("Rapprochement direct : les N° d'ordre de la liste correspondent au JSON.")
    intactes = all(lignes_apres.get(c) == l for c, l in lignes_avant.items() if c not in pointes)
    diff_ok = all(l.get("Diff") == (l.get("IMagasin") or 0) + (l.get("ISalle") or 0)
                  - (l.get("StockAvant_SV") or 0) - (l.get("StockAvant_MG") or 0)
                  for c, l in lignes_apres.items() if c in pointes)
    non_pointees = len(lignes_avant) - len(pointes)
    if intactes and diff_ok:
        res.append(f"Les {non_pointees} ligne(s) du JSON non pointées sont strictement intactes, et Diff "
                   "est cohérent sur toutes les lignes pointées.")
    else:
        res.append("⚠ Contrôle d'intégrité en échec (lignes non pointées modifiées ou Diff incohérent) : "
                   "NE PAS réimporter, signaler le problème.")
    # Exemple : la ligne pointée qui a le plus de champs renseignés.
    exemples = sorted((lignes_apres[c] for c in pointes if c in lignes_apres),
                      key=lambda l: -sum(bool(str(l.get(k) or "").strip() and l.get(k) != 0)
                                         for k in _CHAMPS_EXEMPLE))
    if exemples:
        e = exemples[0]
        champs = ", ".join(f"{k}={e.get(k)}" for k in _CHAMPS_EXEMPLE
                           if str(e.get(k) or "").strip() and e.get(k) != 0)
        res.append(f"Exemple : « {_nom(e.get('Libellé'))} » → {champs or 'compté 0'}, "
                   f"Saisie_par={e.get('Saisie_par') or '—'}.")
    if rapport.compteurs:
        res.append("Comptage : " + " ; ".join(f"{c['page']} {c['compteur']}" for c in rapport.compteurs) + ".")
    txt += _puces(res)

    # --- Lignes bloquées ------------------------------------------------------------
    if bloquants:
        txt += ["", f"Lignes bloquées ({len(bloquants)}) — NON reportées dans le JSON :"]
        items = []
        for a in bloquants:
            d, t = a["details"], a.get("type")
            lu = _nom(d.get("lu"))
            cands = d.get("candidats") or []
            noms = " / ".join(f"« {_nom(c['libelle'])} » (N° {c['chrono']})" for c in cands)
            if t == "absent":
                items.append(f"« {lu} » n'existe pas dans le JSON {code} (nouveau produit, ou libellé mal lu).")
            elif t == "ambigu":
                items.append(f"« {lu} » : plusieurs produits proches dans le JSON — {noms}. Le choix vous revient.")
            elif t == "homonymes":
                items.append(f"« {lu} » existe plusieurs fois dans le JSON — {noms}. Préciser lequel.")
            elif t == "doublon":
                items.append(f"« {lu} » lu deux fois ({' et '.join(d.get('pages') or [])}) : seule la première "
                             "lecture est reportée.")
            elif t == "quantite_invalide":
                items.append(f"« {lu} » : quantité illisible ou négative — {a['message']}")
            else:
                items.append(a["message"])
        txt += _puces(items)

    # --- Points à vérifier ------------------------------------------------------------
    if a_verifier:
        txt += ["", f"Points à vérifier ({len(a_verifier)}) :"]
        rubriques: List[Tuple[str, List[str]]] = []
        notes = [f"« {a['details'].get('texte')} » ({a['page']})" for a in par_type.get("note", [])]
        rubriques.append(("Notes manuscrites hors tableau", notes))
        incertains = par_type.get("incertain", [])
        additions = [a for a in incertains if "+" in (a["details"].get("note") or "")]
        autres = [a for a in incertains if a not in additions]
        rubriques.append(("Additions écrites", [
            f"« {_nom(a['details'].get('libelle'))} » : {a['details'].get('note')} → "
            f"{_valeurs(a['details'].get('valeurs') or {})}" for a in additions]))
        rubriques.append(("Chiffres surchargés, raturés ou peu lisibles", [
            f"« {_nom(a['details'].get('libelle'))} » : {a['details'].get('note') or 'lecture douteuse'} → "
            + (f"reporté {_valeurs(a['details']['valeurs'])}" if a["details"].get("valeurs")
               else "rien reporté (champ laissé tel quel)") for a in autres]))
        rubriques.append(("Libellés approchés (faute de lecture probable)", [
            f"« {_nom(a['details'].get('lu'))} » lu pour « {_nom(a['details'].get('libelle_json'))} »"
            for a in par_type.get("approche", [])]))
        rubriques.append(("Conditionnements différents du JSON", [
            f"« {_nom(a['details'].get('lu'))} » : lu « {_mesure_imprimee(a['details'].get('lu')) or '?'} », "
            f"« {a['details'].get('mesure_json')} » dans le JSON" for a in par_type.get("conditionnement", [])]))
        rubriques.append(("Péremptions illisibles (non reportées)", [
            f"« {_nom(a['details'].get('libelle'))} » : « {a['details'].get('texte')} »"
            for a in par_type.get("peremption_invalide", [])]))
        divers = [a["message"] for a in a_verifier if a.get("type") in ("couple", "pied", "manquantes", "autre")]
        rubriques.append(("Autres", divers))
        for titre, items in rubriques:
            if items:
                txt.append(f"{titre} :")
                txt += _puces(items)

    # --- Verdict ----------------------------------------------------------------
    txt.append("")
    if not (intactes and diff_ok):
        txt.append("⛔ JSON à NE PAS réimporter dans Aizenta (contrôle d'intégrité en échec).")
    elif bloquants:
        txt.append(f"✅ JSON réimportable dans Aizenta. Les {len(bloquants)} ligne(s) bloquée(s) ci-dessus n'y "
                   "sont pas reportées (laissées telles quelles) : les saisir directement dans l'inventaire "
                   "sous Aizenta en suivant les remarques.")
    else:
        txt.append("✅ JSON réimportable dans Aizenta (après contrôle des points à vérifier).")
    return "\n".join(txt)


# ---------------------------------------------------------------------------
# Lecture IA des pages scannées
# ---------------------------------------------------------------------------
def pages_en_images(data: bytes, content_type: str) -> List[bytes]:
    """Scan → une image JPEG par page. Contrairement à ocr_core.prepare, TOUTES les
    pages (jusqu'à MAX_PAGES) et TOUJOURS en image, même si le PDF a du texte."""
    if content_type == "application/pdf":
        import fitz  # PyMuPDF (même import que ocr_core)

        with fitz.open(stream=data, filetype="pdf") as pdf:
            if pdf.page_count > MAX_PAGES:
                raise ValueError(f"Liste de {pdf.page_count} pages : maximum {MAX_PAGES}.")
            return [shrink_image(p.get_pixmap(dpi=PDF_RENDER_DPI).tobytes("png")) for p in pdf]
    if content_type in IMAGE_MIMES:
        return [shrink_image(data)]
    raise ValueError("Liste de pointage attendue en PDF ou en photo (JPG/PNG/WEBP).")


def photos_en_pdf(photos: List[bytes]) -> bytes:
    """Photos des pages prises au téléphone (dans l'ordre) → UN PDF d'une page par photo.

    Sans scanner, on photographie chaque page : le PDF assemblé est ensuite stocké et
    analysé exactement comme un scan (relance, téléchargement et suppression inchangés).
    Chaque photo est redressée (EXIF), réduite à PHOTO_MAX_PX et ré-encodée en JPEG ;
    la taille de page est calculée pour qu'un rendu à PDF_RENDER_DPI redonne la photo
    à sa résolution (ni perte, ni agrandissement inutile)."""
    import io

    import fitz  # PyMuPDF (même import que ocr_core)
    from PIL import Image, ImageOps

    if not photos:
        raise ValueError("Aucune photo reçue.")
    if len(photos) > MAX_PAGES:
        raise ValueError(f"{len(photos)} photos : maximum {MAX_PAGES} pages.")
    pdf = fitz.open()
    try:
        for n, brut in enumerate(photos, 1):
            try:
                with Image.open(io.BytesIO(brut)) as img:
                    img = ImageOps.exif_transpose(img)           # photo prise « de côté »
                    if img.mode != "RGB":
                        img = img.convert("RGB")                 # JPEG : ni transparence ni palette
                    img.thumbnail((PHOTO_MAX_PX, PHOTO_MAX_PX))  # proportions gardées, jamais agrandie
                    largeur, hauteur = img.size
                    sortie = io.BytesIO()
                    img.save(sortie, format="JPEG", quality=PHOTO_QUALITE, optimize=True)
            except Exception as exc:  # noqa: BLE001 — photo illisible (HEIC, fichier abîmé…)
                raise ValueError(f"Photo n°{n} illisible : envoyez des photos JPG, PNG ou WEBP "
                                 "(le format HEIC de l'iPhone n'est pas pris en charge).") from exc
            # 1 point PDF = 1/72 pouce : la page mesure (pixels / DPI) pouces.
            page = pdf.new_page(width=largeur * 72 / PDF_RENDER_DPI, height=hauteur * 72 / PDF_RENDER_DPI)
            page.insert_image(page.rect, stream=sortie.getvalue())
        return pdf.tobytes(garbage=3, deflate=True)
    finally:
        pdf.close()


async def lire_pages(images: List[bytes], filename: str, model_id: str) -> Tuple[List[dict], Dict[str, Any]]:
    """Analyse chaque page (en parallèle, par lots) ; renvoie (pages lues, métriques).
    Une page en erreur n'arrête pas les autres : elle est signalée dans les métriques."""
    model = get_model(model_id) or get_model(ocr_core.default_model_id())
    sem = asyncio.Semaphore(PARALLELE)
    started = time.monotonic()

    async def une_page(i: int, img: bytes):
        nom = f"p.{i}"
        async with sem:
            try:
                reply, tin, tout = await call_llm(model, SYSTEM_PROMPT, "", [img], f"{filename} {nom}")
            except Exception as exc:  # noqa: BLE001 — réseau, quota, proxy…
                logger.exception("[ocr_pointage] appel IA impossible %s %s", filename, nom)
                return nom, None, 0, 0, f"{nom} : erreur d'analyse ({exc})"
        try:
            lu = parse_json(reply)
            if not isinstance(lu.get("lignes"), list):
                raise ValueError("clé « lignes » absente")
        except (json.JSONDecodeError, ValueError, AttributeError) as exc:
            return nom, None, tin, tout, f"{nom} : réponse de l'IA inexploitable ({exc})"
        lu["page"] = nom
        return nom, lu, tin, tout, None

    resultats = await asyncio.gather(*(une_page(i, img) for i, img in enumerate(images, start=1)))
    pages = [r[1] for r in resultats if r[1] is not None]
    tin = sum(r[2] for r in resultats)
    tout = sum(r[3] for r in resultats)
    erreurs = [r[4] for r in resultats if r[4]]
    cost_usd, cost_xof = compute_cost(model, tin, tout)
    return pages, {
        "model": model.id, "input_mode": "images", "input_tokens": tin, "output_tokens": tout,
        "cost_usd": cost_usd, "cost_xof": cost_xof, "pages_analyzed": len(images),
        "duration_ms": int((time.monotonic() - started) * 1000), "erreurs_pages": erreurs,
    }


async def traiter_liste_pointage(scan: bytes, content_type: str, filename: str, json_bytes: bytes,
                                 json_filename: str, model_id: str) -> Dict[str, Any]:
    """Enchaînement complet ; ne lève jamais. Résultat au format d'une analyse
    ocr_core (summary, extracted_fields, flags… + métriques), plus :
      - json_complete (bytes, format WinDev) si au moins une page a été lue ;
      - pointage_rapport (dict : anomalies + modifications)."""
    base = {"document_type": "Liste de pointage d'inventaire", "uncertain_fields": [],
            "model": model_id, "input_mode": "images", "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "cost_xof": 0.0, "pages_analyzed": 0, "duration_ms": 0}
    try:
        doc = charger_json_inventaire(json_bytes)
        images = pages_en_images(scan, content_type)
    except ValueError as exc:
        return {**base, "summary": "", "extracted_fields": {}, "flags": [str(exc)],
                "confidence": None, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — PDF protégé, image corrompue…
        logger.exception("[ocr_pointage] préparation impossible pour %s", filename)
        return {**base, "summary": "", "extracted_fields": {}, "flags": [f"Fichier illisible : {exc}"],
                "confidence": None, "error": str(exc)}

    pages, metrics = await lire_pages(images, filename, model_id)
    erreurs = metrics.pop("erreurs_pages")
    if not pages:
        msg = "Aucune page n'a pu être lue."
        return {**base, **metrics, "summary": "", "extracted_fields": {}, "flags": [msg] + erreurs,
                "confidence": None, "error": msg}

    complet, rapport = appliquer_lectures(doc, pages, code_attendu=json_filename)
    for e in erreurs:
        rapport.ajouter("bloquant", f"Page non lue — {e}", type="page_non_lue")
    ordre = {"bloquant": 0, "a_verifier": 1}
    def _lieu(a: dict) -> str:
        if a["chrono"] is not None:
            return f"N° {a['chrono']} — "
        return f"{a['page']} — " if a.get("page") else ""

    flags = [("⛔ " if a["gravite"] == "bloquant" else "⚠ ") + _lieu(a) + a["message"]
             for a in sorted(rapport.anomalies, key=lambda a: ordre[a["gravite"]])]
    a_verifier = len(rapport.anomalies) - rapport.nb_bloquants
    # Deux textes : un RÉSUMÉ d'une ligne (colonne « Synthèse » de la liste et panneau commun des
    # analyses ocr_core, qui n'affiche pas les retours à la ligne) et le COMPTE RENDU complet,
    # affiché mis en forme par l'encadré « Compte rendu » de la page.
    compte_rendu = synthese_detaillee(rapport, doc, complet, nb_pages=len(images))
    summary = (
        f"Liste de pointage {rapport.code_inventaire or ''} : {rapport.lignes_lues} lignes lues, "
        f"{len(rapport.chronos_pointes)} pointées, {rapport.nb_bloquants} bloquée(s), {a_verifier} point(s) à vérifier — "
        + ("JSON réimportable dans Aizenta." if "⛔" not in compte_rendu else "JSON à NE PAS réimporter (voir le compte rendu).")
    ).replace("  ", " ")
    return {
        **base, **metrics,
        "summary": summary,
        "compte_rendu": compte_rendu,
        "extracted_fields": {
            "inventaire": rapport.code_inventaire,
            "lignes_json": rapport.lignes_json,
            "lignes_lues": rapport.lignes_lues,
            "lignes_completees": rapport.lignes_modifiees,
            "champs_modifies": len(rapport.modifications),
            "anomalies_bloquantes": rapport.nb_bloquants,
            "points_a_verifier": a_verifier,
        },
        "flags": flags,
        "confidence": None,       # pas de note globale : le rapport détaille chaque anomalie
        "uncertain_fields": [],
        "error": None,
        "json_complete": json_windev(complet),
        "pointage_rapport": rapport.as_dict(),
    }
