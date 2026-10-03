"""
backend/vidal_v2/journal_validation.py
--------------------------------------
Lot 56 — repris de Ster (app/utils/vidal_journal_validation.py) ; ajout en fin
de fichier d'un export XLSX écrit sans dépendance (openpyxl absent de SAWALI).

§ décision de l'utilisateur (validation VIDAL) : « Vrais appels (pas de
sandbox), avec des patients fictifs [...]. Tableau récapitulatif : date/
heure de l'appel, URL de la requête (identifiants anonymisés), body,
valeur du retour, délai avant réponse, observations et autres infos
utiles. »

Fonctions PURES (sans Mongo ni FastAPI) qui préparent une entrée du
journal de validation : URL avec app_id/app_key masqués, type d'appel,
réponse tronquée au-delà de 1 Mo, résumé des alertes par gravité,
observations automatiques. L'écriture en base est faite par
routes/vidal_appels.py (appeler_vidal, point de passage unique des
appels du module Sécurisation v2).
"""

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

TAILLE_MAX_REPONSE = 1_000_000  # 1 Mo
SEUIL_DELAI_MS = 3000
PARAMETRES_SECRETS = ("app_id", "app_key")

try:  # § heure locale du cabinet (Burkina Faso, UTC+0 sans heure d'été)
    from zoneinfo import ZoneInfo
    FUSEAU_LOCAL = ZoneInfo("Africa/Ouagadougou")
except Exception:  # noqa: BLE001 — base tz absente : UTC équivalent
    FUSEAU_LOCAL = timezone.utc


def url_masquee(url: str, params: Optional[dict]) -> str:
    """URL complète avec les identifiants remplacés par *** (jamais stockés en clair)."""
    propres = []
    for cle, valeur in (params or {}).items():
        valeurs = valeur if isinstance(valeur, (list, tuple)) else [valeur]
        for v in valeurs:
            propres.append((cle, "***" if cle in PARAMETRES_SECRETS else v))
    return f"{url}?{urlencode(propres, safe='*')}" if propres else url


def masquer_secrets(texte: Optional[str], secrets: list[str]) -> Optional[str]:
    """Filet de sécurité : retire toute occurrence des secrets d'un texte (corps, réponse, erreur)."""
    if not texte:
        return texte
    for s in secrets:
        if s and len(s) >= 4:
            texte = texte.replace(s, "***")
    return texte


def type_appel(methode: str, chemin: str) -> str:
    if chemin.startswith("/alerts/full/html"):
        return "Sécurisation (rapport HTML)"
    if chemin.startswith("/alerts/full"):
        return "Sécurisation (alertes structurées)"
    if chemin.startswith("/calculators/"):
        return "Calculateur fonction rénale"
    if "posology-descriptors" in chemin:
        return "Posologie"
    if chemin.startswith("/products") or chemin.startswith("/search"):
        return "Recherche médicament"
    if chemin.startswith(("/allergies", "/pathologies", "/alds")):
        return "Recherche référentielle"
    if chemin.startswith("/galenic-forms") or chemin.rsplit("/", 1)[-1] in ("units", "routes", "indications", "indicators"):
        return "Référentiel produit"
    if chemin.startswith(("/product/", "/vmp/", "/package/", "/ucd/")):
        return "Fiche produit"
    return f"Autre ({methode})"


def tronquer_reponse(texte: Optional[str]) -> tuple[Optional[str], bool, int]:
    """(réponse éventuellement tronquée, tronquée ?, taille en octets)."""
    if texte is None:
        return None, False, 0
    taille = len(texte.encode("utf-8"))
    if taille <= TAILLE_MAX_REPONSE:
        return texte, False, taille
    coupe = texte.encode("utf-8")[:TAILLE_MAX_REPONSE].decode("utf-8", errors="ignore")
    return coupe + "\n[… réponse tronquée au-delà de 1 Mo …]", True, taille


def observations_automatiques(*, statut: int, reponse: Optional[str], duree_ms: int, resume_gravites: Optional[dict],
                              alertes_attendues: Optional[list[str]], erreur: Optional[str] = None) -> list[str]:
    """Constat automatique lisible pour le tableau récapitulatif."""
    obs: list[str] = []
    if statut == 0:
        obs.append(f"VIDAL injoignable : {erreur or 'erreur réseau'}")
    elif statut >= 400:
        obs.append(f"{statut // 100}xx : {(reponse or '').strip()[:150] or 'sans détail'}")
    elif statut == 204 or not (reponse or "").strip():
        obs.append("Réponse vide (aucune donnée renvoyée)")
    if duree_ms > SEUIL_DELAI_MS:
        obs.append(f"Délai > {SEUIL_DELAI_MS // 1000} s ({duree_ms} ms)")
    if resume_gravites is not None:
        if resume_gravites:
            obs.append("Alertes : " + ", ".join(f"{g} × {n}" for g, n in sorted(resume_gravites.items())))
        else:
            obs.append("Aucune alerte détaillée")
    texte = (reponse or "").lower()
    for attendu in alertes_attendues or []:
        present = attendu.lower() in texte
        obs.append(f"Alerte attendue « {attendu} » {'présente' if present else 'ABSENTE'}")
    return obs


def horodatages() -> tuple[datetime, str]:
    """(UTC, heure locale Africa/Ouagadougou formatée)."""
    maintenant = datetime.now(timezone.utc)
    return maintenant.replace(tzinfo=None), maintenant.astimezone(FUSEAU_LOCAL).strftime("%d/%m/%Y %H:%M:%S")


# ---------------------------------------------------------------------------
# Lot 56 (SAWALI) — export XLSX SANS dépendance supplémentaire.
# Ster utilise openpyxl, absent des dépendances de SAWALI : plutôt que
# d'ajouter un paquet au déploiement, on écrit le classeur à la main. Un
# fichier .xlsx n'est qu'une archive ZIP de quelques fichiers XML ; les
# cellules sont écrites en « texte en ligne » (inlineStr) ou en nombre.
# ---------------------------------------------------------------------------
import io as _io
import zipfile as _zipfile
from xml.sax.saxutils import escape as _echapper_xml

LIMITE_CELLULE_XLSX = 32000  # une cellule Excel accepte au plus 32 767 caractères


def _nom_colonne(index: int) -> str:
    """0 -> "A", 25 -> "Z", 26 -> "AA" (nommage des colonnes Excel)."""
    nom = ""
    index += 1
    while index:
        index, reste = divmod(index - 1, 26)
        nom = chr(65 + reste) + nom
    return nom


def _cellule_xml(reference: str, valeur, gras: bool = False) -> str:
    style = ' s="1"' if gras else ""
    if isinstance(valeur, bool):
        valeur = "Oui" if valeur else "Non"
    if isinstance(valeur, (int, float)):
        return f'<c r="{reference}"{style}><v>{valeur}</v></c>'
    texte = "" if valeur is None else str(valeur)
    # Caractères de contrôle interdits en XML : retirés (sauf tabulation et retours à la ligne).
    texte = "".join(c for c in texte if c in "\t\n\r" or ord(c) >= 32)
    if len(texte) > LIMITE_CELLULE_XLSX:
        texte = texte[:LIMITE_CELLULE_XLSX] + "\n[… tronqué dans l'export : texte complet dans le détail de l'appel …]"
    return f'<c r="{reference}" t="inlineStr"{style}><is><t xml:space="preserve">{_echapper_xml(texte)}</t></is></c>'


def classeur_xlsx(titre_feuille: str, entetes: list[str], lignes: list[list]) -> bytes:
    """Classeur Excel minimal (une feuille, en-têtes en gras) — octets du fichier .xlsx."""
    rangees = []
    for numero, valeurs in enumerate([entetes] + lignes, start=1):
        cellules = "".join(_cellule_xml(f"{_nom_colonne(i)}{numero}", v, gras=numero == 1) for i, v in enumerate(valeurs))
        rangees.append(f'<row r="{numero}">{cellules}</row>')
    feuille = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
               f'<sheetData>{"".join(rangees)}</sheetData></worksheet>')
    fichiers = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '</Types>'),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{_echapper_xml(titre_feuille[:31])}" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>'),
        # Deux styles : 0 = normal, 1 = gras (en-têtes).
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border/></borders>'
            '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
            '<cellXfs count="2"><xf fontId="0"/><xf fontId="1" applyFont="1"/></cellXfs>'
            '</styleSheet>'),
        "xl/worksheets/sheet1.xml": feuille,
    }
    tampon = _io.BytesIO()
    with _zipfile.ZipFile(tampon, "w", _zipfile.ZIP_DEFLATED) as archive:
        for nom, contenu in fichiers.items():
            archive.writestr(nom, contenu)
    return tampon.getvalue()
