"""Lot 33 — Créer un formulaire ou un sondage depuis un document.

On dépose un questionnaire existant (Word, Excel, PDF, photos ou images de pages
imprimées) ; l'IA en déduit la STRUCTURE (pages, questions, types de champs,
choix, colonnes des tableaux) et la plateforme crée un BROUILLON modifiable :
  - formulaire (collection `forms`, éditeur /portal/forms/{id}/edit) : les 15
    types de champs de l'éditeur ;
  - sondage WhatsApp (collection `wa_surveys`) : les 6 types de questions.

Règles de reprise (voir SYSTEM_FORMULAIRE / SYSTEM_SONDAGE) :
  - « … ? Si oui, lesquels ? » → Oui/Non + zone de précision à côté ;
  - cases ☐ → Oui/Non, liste ou choix multiples ; zone « signature » → signature ;
  - « joindre / copie de … » → fichier joint ;
  - tableau → ses COLONNES ; ses LIGNES seulement si l'utilisateur coche « reprendre
    aussi les données des tableaux » (elles pré-remplissent alors le tableau, via la
    valeur par défaut du champ) ;
  - libellés fidèles (fautes de frappe évidentes corrigées et signalées).

Lecture des fichiers SANS nouvelle dépendance : Word (.docx) et Excel (.xlsx)
sont des archives ZIP de XML, lues avec la bibliothèque standard ; PDF et images
avec PyMuPDF / Pillow (déjà installés). Tout le contrôle de la réponse de l'IA
(types, choix, colonnes, une seule signature, doublons) est fait ici, sans IA,
et résumé dans un compte rendu remis à l'utilisateur.

Aucune modification du module commun `ocr_core` : on réutilise son catalogue de
modèles, son calcul de coût, sa lecture du JSON et sa réduction d'images.
"""
from __future__ import annotations

import base64
import difflib
import io
import re
import secrets
import unicodedata
import zipfile
from typing import Any, Callable, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import ocr_core
from ocr_core.engine import parse_json
from ocr_core.models import compute_cost, get_model
from ocr_core.prepare import shrink_image
from ia_client import cle_ia as _cle_ia  # noqa: E402 — lot 53 : clé du fournisseur IA

# ---------------------------------------------------------------------------
# Limites
# ---------------------------------------------------------------------------
EXTENSIONS_TEXTE = {"docx", "xlsx", "xlsm"}
EXTENSIONS_IMAGE = {"jpg", "jpeg", "png", "webp"}
EXTENSIONS = EXTENSIONS_TEXTE | EXTENSIONS_IMAGE | {"pdf"}
# Anciens formats binaires : refusés avec la marche à suivre.
ANCIENS_FORMATS = {"doc": "Word", "xls": "Excel"}
MAX_FICHIERS = 20
MAX_PAGES_IMAGES = 20           # pages envoyées en image à l'IA (coût maîtrisé)
MAX_TEXTE = 60_000              # caractères de texte envoyés à l'IA
MAX_LIGNES_EXCEL = 300          # lignes lues par feuille
PDF_DPI = 150
MIN_TEXTE_PAR_PAGE = 200        # en dessous : PDF considéré comme scanné
MAX_SORTIE_TOKENS = 16_000      # un grand formulaire en JSON peut dépasser 8 000 tokens

# Types de champs de l'éditeur de formulaires (FormEditor.jsx) et largeurs
# proposées dans sa grille de 12 colonnes.
TYPES_CHAMP = {"text", "textarea", "number", "boolean", "select", "multiselect", "date", "datetime",
               "email", "tel", "url", "location", "table", "file", "signature"}
TYPES_COLONNE = {"text", "number", "date"}
LARGEURS = (12, 9, 8, 6, 4, 3)
# Types de questions des sondages (routes/wa_surveys.QUESTION_TYPES).
TYPES_QUESTION = {"single", "multi", "yesno", "rating", "nps", "text"}
MAX_QUESTIONS = 30
SEUIL_DOUBLON = 0.90            # libellés presque identiques → signalés
MAX_LIGNES_TABLEAU = 100        # lignes reprises par tableau (option « avec données »)


# ---------------------------------------------------------------------------
# 1. Lecture des fichiers
# ---------------------------------------------------------------------------
def _ext(nom: str) -> str:
    return (nom.rsplit(".", 1)[-1] if "." in (nom or "") else "").lower()


def verifier_fichier(nom: str) -> None:
    """Refuse tôt (avant tout stockage ou appel IA) un format non pris en charge."""
    ext = _ext(nom)
    if ext in ANCIENS_FORMATS:
        raise ValueError(f"« {nom} » : ancien format {ANCIENS_FORMATS[ext]} (.{ext}). "
                         f"Ouvrez-le et enregistrez-le en .{ext}x, puis déposez-le à nouveau.")
    if ext not in EXTENSIONS:
        raise ValueError(f"« {nom} » : format non pris en charge. Formats acceptés : Word (.docx), "
                         "Excel (.xlsx), PDF, photos ou images (JPG, PNG, WEBP).")


def _local(tag: str) -> str:
    """Nom XML sans espace de noms : « {http://…}p » → « p »."""
    return tag.rsplit("}", 1)[-1]


def _texte_paragraphe_word(p: ET.Element) -> str:
    """Texte d'un paragraphe Word, cases à cocher comprises (☐ / ☒)."""
    morceaux: List[str] = []
    for el in p.iter():
        nom = _local(el.tag)
        if nom == "t" and el.text:
            morceaux.append(el.text)
        elif nom == "tab":
            morceaux.append("\t")
        elif nom in ("br", "cr"):
            morceaux.append("\n")
        elif nom == "sym":
            morceaux.append("☐")                         # case Wingdings insérée comme symbole
        elif nom == "checked":                           # case à cocher de contrôle de contenu
            val = next((v for k, v in el.attrib.items() if _local(k) == "val"), "0")
            morceaux.append("☒ " if val in ("1", "true") else "☐ ")
    texte = "".join(morceaux)
    # Liste numérotée / à puces : on garde l'information de liste
    if any(_local(e.tag) == "numPr" for e in p.iter()):
        texte = "• " + texte
    return texte


def lire_word(data: bytes) -> str:
    """Document Word (.docx) → texte dans l'ordre : paragraphes et tableaux (« | »)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            racine = ET.fromstring(z.read("word/document.xml"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Document Word illisible ou abîmé.") from exc
    corps = next((e for e in racine if _local(e.tag) == "body"), racine)
    lignes: List[str] = []
    for bloc in corps:
        nom = _local(bloc.tag)
        if nom == "p":
            t = _texte_paragraphe_word(bloc).strip()
            if t:
                lignes.append(t)
        elif nom == "tbl":
            lignes.append("[TABLEAU]")
            for tr in (e for e in bloc if _local(e.tag) == "tr"):
                cellules = []
                for tc in (e for e in tr if _local(e.tag) == "tc"):
                    cellules.append(" / ".join(t for t in (_texte_paragraphe_word(p).strip()
                                                           for p in tc.iter() if _local(p.tag) == "p") if t))
                lignes.append("| " + " | ".join(cellules) + " |")
            lignes.append("[FIN DU TABLEAU]")
    return "\n".join(lignes)


def _colonne_excel(ref: str) -> int:
    """« AB12 » → 28 (numéro de colonne, à partir de 1)."""
    n = 0
    for c in re.match(r"[A-Z]+", ref or "A").group(0):
        n = n * 26 + ord(c) - 64
    return n


def lire_excel(data: bytes) -> str:
    """Classeur Excel (.xlsx) → texte, feuille par feuille, une ligne « | » par ligne non vide."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        partages: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
                partages.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))
        classeur = ET.fromstring(z.read("xl/workbook.xml"))
        liens = {r.attrib["Id"]: r.attrib["Target"]
                 for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        feuilles = []
        for s in classeur.iter():
            if _local(s.tag) == "sheet":
                rid = next(v for k, v in s.attrib.items() if _local(k) == "id")
                cible = liens[rid].lstrip("/")
                feuilles.append((s.attrib.get("name", "Feuille"), cible if cible.startswith("xl/") else f"xl/{cible}"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Classeur Excel illisible ou abîmé.") from exc
    lignes: List[str] = []
    for nom, chemin in feuilles:
        feuille = ET.fromstring(z.read(chemin))
        rangs = [r for r in feuille.iter() if _local(r.tag) == "row"]
        contenu = []
        for r in rangs[:MAX_LIGNES_EXCEL]:
            valeurs: Dict[int, str] = {}
            for c in (e for e in r if _local(e.tag) == "c"):
                typ, v = c.attrib.get("t"), None
                if typ == "inlineStr":
                    v = "".join(t.text or "" for t in c.iter() if _local(t.tag) == "t")
                else:
                    ve = next((e for e in c if _local(e.tag) == "v"), None)
                    if ve is not None and ve.text is not None:
                        v = partages[int(ve.text)] if typ == "s" else ve.text
                if v not in (None, ""):
                    valeurs[_colonne_excel(c.attrib.get("r", "A"))] = v.strip()
            if valeurs:
                contenu.append("| " + " | ".join(valeurs.get(i, "") for i in range(1, max(valeurs) + 1)) + " |")
        if contenu:
            lignes.append(f"[FEUILLE « {nom} »]")
            lignes += contenu
            if len(rangs) > MAX_LIGNES_EXCEL:
                lignes.append(f"(… {len(rangs) - MAX_LIGNES_EXCEL} lignes suivantes non lues)")
    return "\n".join(lignes)


def lire_pdf(data: bytes) -> Tuple[str, List[bytes]]:
    """PDF → (texte, []) s'il a une vraie couche texte, sinon ("", [pages en image])."""
    import fitz  # PyMuPDF (même import que ocr_core)

    try:
        with fitz.open(stream=data, filetype="pdf") as pdf:
            textes = [p.get_text() for p in pdf]
            if sum(len(t.strip()) for t in textes) >= MIN_TEXTE_PAR_PAGE * max(1, len(textes)) * 0.5:
                return "\n".join(f"[PAGE {i}]\n{t.strip()}" for i, t in enumerate(textes, 1)), []
            return "", [shrink_image(p.get_pixmap(dpi=PDF_DPI).tobytes("png")) for p in pdf]
    except Exception as exc:  # noqa: BLE001
        raise ValueError("PDF illisible ou abîmé.") from exc


def preparer(fichiers: List[Tuple[str, bytes]]) -> Tuple[str, List[bytes], List[str]]:
    """Fichiers déposés (dans l'ordre) → (texte, images, remarques) à envoyer à l'IA."""
    if not fichiers:
        raise ValueError("Aucun fichier déposé.")
    if len(fichiers) > MAX_FICHIERS:
        raise ValueError(f"{len(fichiers)} fichiers : {MAX_FICHIERS} au maximum.")
    textes: List[str] = []
    images: List[bytes] = []
    remarques: List[str] = []
    for nom, data in fichiers:
        verifier_fichier(nom)
        ext = _ext(nom)
        try:
            if ext == "docx":
                t, imgs = lire_word(data), []
            elif ext in ("xlsx", "xlsm"):
                t, imgs = lire_excel(data), []
            elif ext == "pdf":
                t, imgs = lire_pdf(data)
            else:
                t, imgs = "", [shrink_image(data)]
        except ValueError as exc:
            raise ValueError(f"« {nom} » : {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — image illisible (HEIC…)
            raise ValueError(f"« {nom} » : image illisible (JPG, PNG ou WEBP attendu ; "
                             "le format HEIC de l'iPhone n'est pas pris en charge).") from exc
        if t.strip():
            textes.append(f"===== FICHIER « {nom} » =====\n{t.strip()}")
        images += imgs
        if not t.strip() and not imgs:
            remarques.append(f"« {nom} » ne contient aucun texte lisible : ignoré.")
    texte = "\n\n".join(textes)
    if len(texte) > MAX_TEXTE:
        texte = texte[:MAX_TEXTE]
        remarques.append(f"Document très long : seuls les {MAX_TEXTE} premiers caractères ont été analysés.")
    if len(images) > MAX_PAGES_IMAGES:
        remarques.append(f"{len(images)} pages en image : seules les {MAX_PAGES_IMAGES} premières ont été analysées.")
        images = images[:MAX_PAGES_IMAGES]
    if not texte and not images:
        raise ValueError("Aucun contenu lisible dans les fichiers déposés.")
    return texte, images, remarques


# ---------------------------------------------------------------------------
# 2. Consignes à l'IA
# ---------------------------------------------------------------------------
_COMMUN = (
    "Tu reçois un questionnaire existant (fichier Word ou Excel converti en texte, PDF, ou photos / "
    "images de pages imprimées, dans l'ordre). Il est destiné à des pharmacies et entreprises au "
    "Burkina Faso. Ta mission : en déduire la STRUCTURE d'un questionnaire à remplir en ligne. "
    "Règles :\n"
    "1. Reprends TOUTES les questions, dans l'ordre du document, sans en inventer ni en fusionner "
    "(sauf règle 4). Libellés fidèles : ne corrige que les fautes de frappe évidentes, sans changer "
    "le sens, et liste chaque correction dans « remarques ».\n"
    "2. Ignore les réponses déjà écrites (à la main ou tapées), les pointillés « ……… » et les "
    "numéros d'ordre décoratifs : seule la structure compte.\n"
    "3. Une question « … ? Si oui, lesquels / précisez » devient DEUX éléments : une question Oui/Non "
    "puis la précision.\n"
    "4. Deux questions presque identiques : garde-les et signale-le dans « remarques ».\n"
    "5. Tournure ambiguë (double négation…) : reformule au plus près et signale-le.\n"
    "6. Tout passage illisible ou incertain va dans « remarques ».\n"
    "Réponds UNIQUEMENT en JSON strict, sans texte autour."
)

SYSTEM_FORMULAIRE = _COMMUN + (
    "\n\nCible : un FORMULAIRE. Types de champ autorisés : text (réponse courte), textarea (réponse "
    "longue, pointillés sur plusieurs lignes), number, boolean (Oui/Non), select (un seul choix parmi "
    "une liste), multiselect (plusieurs choix), date, datetime, email, tel, url, location, table "
    "(tableau à remplir), file (pièce à joindre : « joindre », « copie de », « fournir la facture »), "
    "signature (zone « signature », « le responsable », « visa » : UNE seule par formulaire).\n"
    "{TABLEAUX}"
    "- Rubriques / titres de section → pages (« pages »). Sans rubrique : une seule page.\n"
    "- « largeur » (sur 12, valeurs possibles 12, 9, 8, 6, 4, 3) : 12 par défaut ; une question Oui/Non "
    "suivie de sa précision → 4 puis 8 ; petits champs côte à côte (nom, date, téléphone) → 6 ou 4.\n"
    "- « obligatoire » : true seulement si le document le marque (*, « obligatoire »).\n"
    'Format : {"titre": "...", "description": "...", "pages": [{"titre": "...", "champs": [{"type": '
    '"...", "libelle": "...", "obligatoire": false, "largeur": 12, "options": ["..."], "colonnes": '
    '[{"libelle": "...", "type": "text"}], "lignes": [{"libellé de colonne": "valeur"}], "aide": "..."}]}], '
    '"remarques": ["..."]}'
)
TABLEAUX_SANS_DONNEES = (
    "- Tableau du document → type table avec SEULEMENT ses colonnes (libellé + type text, number ou "
    "date). Ne reprends JAMAIS les lignes ni les valeurs du tableau (pas de « lignes ») : le "
    "formulaire sera rempli.\n")
TABLEAUX_AVEC_DONNEES = (
    "- Tableau du document → type table avec ses colonnes (libellé + type text, number ou date) ET "
    "ses lignes dans « lignes » : une entrée par ligne du tableau, clés = libellés exacts des "
    f"colonnes, valeurs recopiées telles qu'écrites ({MAX_LIGNES_TABLEAU} lignes au plus ; ignore les "
    "lignes de total et les lignes vides).\n")


def consignes_formulaire(avec_donnees: bool) -> str:
    """Consignes « formulaire », avec ou sans reprise des lignes des tableaux."""
    return SYSTEM_FORMULAIRE.replace("{TABLEAUX}", TABLEAUX_AVEC_DONNEES if avec_donnees else TABLEAUX_SANS_DONNEES)

SYSTEM_SONDAGE = _COMMUN + (
    "\n\nCible : un SONDAGE WhatsApp (liste simple de 30 questions au plus, sans pages). Types de "
    "question autorisés : single (un choix parmi 2 à 20), multi (plusieurs choix parmi 2 à 20), "
    "yesno (Oui/Non), rating (note de 1 à 5), nps (recommandation de 0 à 10), text (réponse libre).\n"
    "- Tableau, pièce jointe, signature, date… n'existent pas dans un sondage : remplace-les par une "
    "question text quand c'est utile, sinon ignore-les, et signale-le dans « remarques ».\n"
    'Format : {"titre": "...", "description": "...", "questions": [{"type": "...", "libelle": "...", '
    '"obligatoire": true, "options": ["..."], "aide": "..."}], "remarques": ["..."]}'
)


async def appeler_ia(model_id: str, system: str, texte: str, images: List[bytes]) -> Tuple[str, int, int]:
    """Envoie le texte ET les images au modèle ; renvoie (réponse, tokens entrée, tokens sortie).

    Appel direct au client IA (ia_client, lot 53 ; même construction que ocr_core.engine.call_llm), car
    call_llm n'envoie pas le texte quand il y a des images, et limite la réponse à 8 000 tokens."""
    import asyncio
    import os

    from ia_client import ImageContent, LlmChat, UserMessage

    model = get_model(model_id) or get_model(ocr_core.default_model_id())
    api_key = _cle_ia()
    if not api_key:
        raise RuntimeError("Clé LLM non configurée (ANTHROPIC_API_KEY)")
    chat = LlmChat(api_key=api_key, session_id=f"import-formulaire-{secrets.token_urlsafe(8)}",
                   system_message=system).with_model("anthropic", model.id).with_params(max_tokens=MAX_SORTIE_TOKENS)
    consigne = "Déduis la structure de ce questionnaire et réponds uniquement en JSON strict."
    if texte:
        consigne = f"Contenu extrait des fichiers :\n---\n{texte}\n---\n\n{consigne}"
    if images:
        consigne = f"{len(images)} page(s) en image, dans l'ordre.\n\n{consigne}"
    if images:
        message = UserMessage(text=consigne, file_contents=[
            ImageContent(image_base64=base64.b64encode(img).decode("ascii")) for img in images])
    else:
        message = UserMessage(text=consigne)          # même forme que call_llm pour un texte seul
    if hasattr(chat, "send_message_with_tools"):          # emergentintegrations 0.2.0
        rep = await chat.send_message_with_tools(message)
        return rep.content or "", int(rep.usage.input_tokens or 0), int(rep.usage.output_tokens or 0)
    messages = await chat.get_messages()                  # 0.1.0 : réponse brute avec usage
    await chat._add_user_message(messages, message)
    brut = await asyncio.to_thread(lambda: asyncio.run(chat._execute_completion(messages)))
    u = getattr(brut, "usage", None)
    tin = getattr(u, "prompt_tokens", None) or getattr(u, "input_tokens", 0) or 0
    tout = getattr(u, "completion_tokens", None) or getattr(u, "output_tokens", 0) or 0
    return brut.choices[0].message.content or "", int(tin), int(tout)


# ---------------------------------------------------------------------------
# 3. Contrôle de la réponse (sans IA)
# ---------------------------------------------------------------------------
def _txt(v: Any, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _options(v: Any) -> List[str]:
    out = [_txt(o, 200) for o in (v or []) if _txt(o, 200)]
    return list(dict.fromkeys(out))                       # sans doublons, ordre gardé


def _cle(libelle: str, prises: set) -> str:
    """Clé de colonne de tableau : « Date d'effet » → « date_d_effet » (unique)."""
    base = unicodedata.normalize("NFKD", libelle).encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")[:40] or "colonne"
    cle, n = base, 2
    while cle in prises:
        cle, n = f"{base}_{n}", n + 1
    prises.add(cle)
    return cle


def _normal(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def doublons(libelles: List[str]) -> List[Tuple[int, int]]:
    """Paires (n°a, n°b), numérotées à partir de 1, de libellés presque identiques."""
    norm = [_normal(l) for l in libelles]
    paires = []
    for i in range(len(norm)):
        for j in range(i + 1, len(norm)):
            if len(norm[i]) >= 15 and difflib.SequenceMatcher(None, norm[i], norm[j]).ratio() >= SEUIL_DOUBLON:
                paires.append((i + 1, j + 1))
    return paires


def _nombre(v: Any) -> Optional[float]:
    """« 258 700 », « 1 234,5 », 40000 → nombre ; None si ce n'est pas un nombre."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    t = re.sub(r"[\s\u00a0\u202f]", "", str(v)).replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?", t):
        return None
    f = float(t)
    return int(f) if f.is_integer() else f


def _date_iso(v: Any) -> Optional[str]:
    """« 05/03/2026 », « 5-3-26 », « 2026-03-05 » → « 2026-03-05 » (format du champ date) ; sinon None."""
    t = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return t
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})", t)
    if not m:
        return None
    j, mo, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
    a = a + 2000 if a < 100 else a
    return f"{a:04d}-{mo:02d}-{j:02d}" if 1 <= j <= 31 and 1 <= mo <= 12 else None


def lignes_tableau(libelle: str, cols: List[Dict[str, str]], lignes: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Lignes lues par l'IA → valeurs par défaut du tableau (clés = clés des colonnes).

    Nombres (« 258 700 ») et dates (« 05/03/2026 ») convertis au format des champs ; une colonne
    dont une valeur n'est pas convertible passe en texte (rien n'est perdu), et c'est signalé."""
    notes: List[str] = []
    par_libelle = {_normal(c["label"]): c for c in cols}
    brutes = [l for l in (lignes or []) if isinstance(l, dict)]
    if len(brutes) > MAX_LIGNES_TABLEAU:
        notes.append(f"Tableau « {libelle[:60]} » : {len(brutes)} lignes lues, seules les {MAX_LIGNES_TABLEAU} "
                     "premières sont reprises.")
        brutes = brutes[:MAX_LIGNES_TABLEAU]
    rangs = []
    for l in brutes:
        rang = {}
        for cle, v in l.items():
            col = par_libelle.get(_normal(str(cle)))
            if col is not None and v is not None and str(v).strip() != "":
                rang[col["key"]] = v if isinstance(v, (int, float)) else _txt(v, 300)
        if rang:
            rangs.append(rang)
    for col in cols:
        valeurs = [r[col["key"]] for r in rangs if col["key"] in r]
        conv = _nombre if col["type"] == "number" else _date_iso if col["type"] == "date" else None
        if conv is None or not valeurs:
            continue
        if all(conv(v) is not None for v in valeurs):
            for r in rangs:
                if col["key"] in r:
                    r[col["key"]] = conv(r[col["key"]])
        else:
            col["type"] = "text"
            nature = "nombres" if conv is _nombre else "dates"
            notes.append(f"Tableau « {libelle[:60]} », colonne « {col['label']} » : valeurs qui ne sont pas toutes "
                         f"des {nature}, colonne passée en texte.")
    for r in rangs:                                        # une valeur par colonne (vide si absente)
        for col in cols:
            r.setdefault(col["key"], "")
    if rangs:
        notes.append(f"Tableau « {libelle[:60]} » : {len(rangs)} ligne(s) reprise(s) du document, "
                     "à vérifier (elles pré-remplissent le tableau).")
    return rangs, notes


def normaliser_formulaire(brut: Dict[str, Any], new_id: Callable[[], str],
                          avec_donnees: bool = False) -> Tuple[Dict[str, Any], List[str]]:
    """Réponse de l'IA → {title, description, pages} au format des formulaires + corrections faites.
    Les lignes des tableaux ne sont reprises que si `avec_donnees` (choix de l'utilisateur)."""
    notes: List[str] = []
    pages, signature_vue, libelles = [], False, []
    for p_i, p in enumerate(brut.get("pages") or [], 1):
        champs = []
        for c in (p or {}).get("champs") or []:
            libelle = _txt(c.get("libelle"), 500)
            if not libelle:
                continue
            typ = _txt(c.get("type"), 20).lower()
            if typ not in TYPES_CHAMP:
                notes.append(f"« {libelle[:60]} » : type « {typ} » inconnu, remplacé par une réponse courte.")
                typ = "text"
            champ: Dict[str, Any] = {"id": new_id(), "type": typ, "label": libelle,
                                     "required": bool(c.get("obligatoire", False)), "col_start": 1,
                                     "col_span": min(LARGEURS, key=lambda l: abs(l - int(c.get("largeur") or 12)))
                                     if str(c.get("largeur") or "").isdigit() else 12,
                                     "row": len(champs)}
            if _txt(c.get("aide"), 200):
                champ["placeholder"] = _txt(c.get("aide"), 200)
            if typ in ("select", "multiselect"):
                opts = _options(c.get("options"))
                if len(opts) < 2:
                    notes.append(f"« {libelle[:60]} » : moins de 2 choix lus, transformé en réponse courte.")
                    champ["type"] = "text"
                else:
                    champ["options"] = opts
            elif typ == "table":
                prises: set = set()
                cols = []
                for col in c.get("colonnes") or []:
                    lb = _txt((col or {}).get("libelle"), 80)
                    if lb:
                        t = _txt(col.get("type"), 10).lower()
                        cols.append({"key": _cle(lb, prises), "label": lb, "type": t if t in TYPES_COLONNE else "text"})
                if not cols:
                    notes.append(f"« {libelle[:60] } » : tableau sans colonne lisible, transformé en réponse longue.")
                    champ["type"] = "textarea"
                else:
                    champ["columns"] = cols
                    if avec_donnees:                 # lignes pré-remplies (choix de l'utilisateur)
                        rangs, n_lignes = lignes_tableau(libelle, cols, c.get("lignes"))
                        if rangs:
                            champ["default_value"] = rangs
                        notes += n_lignes
            elif typ == "file":
                champ["accept"] = ".pdf,.jpg,.jpeg,.png"
            elif typ == "signature":
                if signature_vue:
                    notes.append(f"« {libelle[:60]} » : une seule signature par formulaire, "
                                 "celle-ci est devenue un champ texte (nom du signataire).")
                    champ["type"] = "text"
                signature_vue = True
            champs.append(champ)
            libelles.append(libelle)
        if champs:
            pages.append({"id": new_id(), "title": _txt((p or {}).get("titre"), 120) or f"Page {p_i}", "fields": champs})
    if not pages:
        raise ValueError("Aucune question n'a pu être reconnue dans le document.")
    return {"title": _txt(brut.get("titre"), 200) or "Formulaire importé",
            "description": _txt(brut.get("description"), 2000), "pages": pages}, notes + _notes_doublons(libelles)


def normaliser_sondage(brut: Dict[str, Any], new_id: Callable[[], str]) -> Tuple[Dict[str, Any], List[str]]:
    """Réponse de l'IA → {title, description, questions} au format des sondages + corrections faites."""
    notes: List[str] = []
    questions, libelles = [], []
    for q in brut.get("questions") or []:
        libelle = _txt((q or {}).get("libelle"), 500)
        if not libelle:
            continue
        typ = _txt(q.get("type"), 10).lower()
        if typ not in TYPES_QUESTION:
            notes.append(f"« {libelle[:60]} » : type « {typ} » inconnu, remplacé par une réponse libre.")
            typ = "text"
        opts: List[str] = []
        if typ in ("single", "multi"):
            opts = _options(q.get("options"))[:20]
            if len(opts) < 2:
                notes.append(f"« {libelle[:60]} » : moins de 2 choix lus, transformé en réponse libre.")
                typ, opts = "text", []
        questions.append({"id": new_id(), "type": typ, "label": libelle, "required": bool(q.get("obligatoire", True)),
                          "options": opts, "help": _txt(q.get("aide"), 300) or None})
        libelles.append(libelle)
    if not questions:
        raise ValueError("Aucune question n'a pu être reconnue dans le document.")
    if len(questions) > MAX_QUESTIONS:
        notes.append(f"{len(questions)} questions lues : un sondage en compte {MAX_QUESTIONS} au plus, "
                     f"les {len(questions) - MAX_QUESTIONS} dernières n'ont pas été reprises.")
        questions, libelles = questions[:MAX_QUESTIONS], libelles[:MAX_QUESTIONS]
    return {"title": _txt(brut.get("titre"), 200) or "Sondage importé",
            "description": _txt(brut.get("description"), 2000), "questions": questions}, notes + _notes_doublons(libelles)


def _notes_doublons(libelles: List[str]) -> List[str]:
    return [f"Question posée deux fois (presque à l'identique) : « {libelles[a - 1][:90]} ». Gardez-en une "
            "seule si c'est un doublon." for a, b in doublons(libelles)]


# Types en clair pour le compte rendu (mêmes mots que l'éditeur).
NOMS_TYPES = {"text": ("réponse courte", "réponses courtes"), "textarea": ("réponse longue", "réponses longues"),
              "number": ("nombre", "nombres"), "boolean": ("Oui/Non", "Oui/Non"),
              "select": ("liste de choix", "listes de choix"), "multiselect": ("choix multiples", "choix multiples"),
              "date": ("date", "dates"), "datetime": ("date et heure", "dates et heures"),
              "email": ("e-mail", "e-mails"), "tel": ("téléphone", "téléphones"), "url": ("lien", "liens"),
              "location": ("localisation", "localisations"), "table": ("tableau", "tableaux"),
              "file": ("pièce jointe", "pièces jointes"), "signature": ("signature", "signatures")}


def _nom_type(t: str, n: int) -> str:
    """« 2 pièces jointes », « 1 signature » (singulier ou pluriel)."""
    un, plusieurs = NOMS_TYPES.get(t, (t, t))
    return f"{n} {un if n == 1 else plusieurs}"


def compte_rendu(cible: str, structure: Dict[str, Any], remarques_ia: List[str], notes: List[str],
                 remarques_lecture: List[str], fichiers: List[str]) -> str:
    """Compte rendu remis à l'utilisateur (sans IA) : ce qui a été créé et ce qu'il faut vérifier."""
    if cible == "formulaire":
        champs = [c for p in structure["pages"] for c in p["fields"]]
        compte: Dict[str, int] = {}
        for c in champs:
            compte[c["type"]] = compte.get(c["type"], 0) + 1
        detail = ", ".join(_nom_type(t, n) for t, n in sorted(compte.items(), key=lambda x: -x[1]))
        tete = (f"Formulaire créé en brouillon : {len(champs)} champ(s) sur {len(structure['pages'])} page(s) "
                f"({detail}).")
    else:
        tete = f"Sondage créé en brouillon : {len(structure['questions'])} question(s)."
    lignes = [tete, f"Document(s) : {', '.join(fichiers)}."]
    a_verifier = [r for r in (remarques_lecture + [_txt(r, 400) for r in remarques_ia if _txt(r, 400)] + notes)]
    if a_verifier:
        lignes.append("")
        lignes.append("Points à vérifier :")
        lignes += [f"• {r}" for r in a_verifier]
    else:
        lignes.append("Aucun point particulier signalé.")
    lignes.append("")
    lignes.append("Relisez le brouillon dans l'éditeur (libellés, types, obligatoire) avant de le partager.")
    return "\n".join(lignes)


async def analyser(fichiers: List[Tuple[str, bytes]], cible: str, model_id: Optional[str],
                   new_id: Callable[[], str], avec_donnees: bool = False) -> Dict[str, Any]:
    """Fichiers → {structure, compte_rendu, usage}. Lève ValueError (message clair) en cas d'échec."""
    if cible not in ("formulaire", "sondage"):
        raise ValueError("Cible inconnue (formulaire ou sondage).")
    texte, images, remarques_lecture = preparer(fichiers)
    mid = model_id if get_model(model_id) else ocr_core.default_model_id()
    reponse, tin, tout = await appeler_ia(mid, consignes_formulaire(avec_donnees) if cible == "formulaire" else SYSTEM_SONDAGE,
                                          texte, images)
    try:
        brut = parse_json(reponse)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("La réponse de l'IA n'a pas pu être lue. Réessayez.") from exc
    if cible == "formulaire":
        structure, notes = normaliser_formulaire(brut, new_id, avec_donnees)
    else:
        structure, notes = normaliser_sondage(brut, new_id)
    cout_usd, cout_xof = compute_cost(get_model(mid), tin, tout)
    return {
        "structure": structure,
        "compte_rendu": compte_rendu(cible, structure, list(brut.get("remarques") or []), notes,
                                     remarques_lecture, [n for n, _ in fichiers]),
        "usage": {"model": mid, "input_tokens": tin, "output_tokens": tout, "pages_images": len(images),
                  "cost_usd": cout_usd, "cost_xof": cout_xof},
    }
