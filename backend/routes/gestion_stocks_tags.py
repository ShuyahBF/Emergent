"""Lot 22 — Tags et recherche des documents de l'Explorateur Stockage R2
(Gestion de Stocks).

R2 ne sait lister un compartiment que par préfixe (chemin) : il ne peut pas
retrouver « tous les fichiers tagués facture ». Les tags vivent donc dans
MongoDB, dans la collection `stock_files` (une fiche par fichier R2), et la
recherche se fait côté serveur :
  - R2 reste la SOURCE DE VÉRITÉ des fichiers (un fichier supprimé dans
    Cloudflare disparaît des résultats, même si sa fiche existe encore) ;
  - la fiche porte : tags, description, auteur du dépôt, suggestions IA.

Fiche `stock_files` :
  id, client_code, key (clé R2 complète, unique), folder, name, size,
  content_type, tags [str], description, uploaded_by (id du compte ou None
  pour un fichier posé hors Sawali), uploaded_by_name, created_at,
  updated_at, ai_suggested_tags [str], ai_suggested_description, ai_model,
  ai_cost_xof (cumul), ai_at, ai_error.

Suggestions IA (facultatives, désactivées par défaut, activables par client
dans SMART Communications → « Espace de stockage R2 ») : on réutilise le
module commun `ocr_core` (lot 19) avec Claude Haiku 4.5, le modèle le moins
cher, et on déduit les tags de sa réponse (type de document, fournisseur,
mois/année). Les suggestions ne sont JAMAIS appliquées d'office : l'utilisateur
les ajoute d'un clic.

Ce module est importé en différé par routes/gestion_stocks.py (pas
d'import circulaire) et réutilise ses helpers de droits et de tenant.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import re
import unicodedata
import uuid
import zipfile
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional

from routes.gestion_stocks import ROOT_FOLDER, _now

logger = logging.getLogger("sawali.gestion_stocks.tags")

MAX_TAGS = 15              # tags par fichier
MAX_TAG_LEN = 40           # caractères par tag
MAX_DESCRIPTION = 500      # caractères de description
MAX_SEARCH_RESULTS = 200

# Lot 23 — recherche dans le texte intégral : texte extrait des documents
# (PDF avec couche texte, Word, Excel, PowerPoint, .txt, .csv), sans IA ni
# coût. Pour un scan ou une photo, c'est le texte lu par l'IA (si l'option est
# activée) qui est cherchable.
MAX_CONTENT_CHARS = 20000
TEXT_EXTRACT_MAX_BYTES = 15 * 1024 * 1024
TEXT_PDF_MAX_PAGES = 50
_OFFICE_XML = {  # fichier Office → parties XML qui portent le texte
    "docx": ("word/document.xml", "word/header", "word/footer"),
    "xlsx": ("xl/sharedStrings.xml", "xl/worksheets/sheet"),
    "pptx": ("ppt/slides/slide",),
}

# Suggestions IA : modèle le moins cher du catalogue ocr_core, fichiers
# lisibles par ocr_core uniquement, et pas au-delà de 10 Mo.
AI_TAGS_MODEL = "claude-haiku-4-5-20251001"
AI_MAX_BYTES = 10 * 1024 * 1024
AI_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "gif", "txt", "csv"}

# Consigne système propre à la Gestion de Stocks (le format de réponse JSON
# est celui, commun, de ocr_core).
def _ai_system_prompt() -> str:
    import ocr_core
    return ocr_core.build_system_prompt(
        organisation="SAWALI SMART SYSTEMS (gestion de stocks des pharmacies et officines, au Burkina Faso)",
        documents=(
            "dans l'espace documentaire de gestion de stocks d'une pharmacie : inventaire, état de stock, "
            "rapport, analyse, contrôle qualité, facture ou bon de livraison de grossiste-répartiteur, etc."
        ),
    )


_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
         "septembre", "octobre", "novembre", "décembre"]

# Tâches de suggestion IA lancées en arrière-plan après un dépôt (référence
# gardée pour qu'elles ne soient pas collectées avant la fin).
_PENDING: set = set()


# ----------------------------------------------------------------------
# Normalisation
# ----------------------------------------------------------------------
def norm_text(value: str) -> str:
    """Texte comparable : minuscules, sans accents, espaces réduits
    (« Contrôle  Qualité » → « controle qualite »)."""
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def clean_tags(raw: Any) -> List[str]:
    """Liste de tags propre à partir d'une liste ou d'un texte « a, b ; c » :
    minuscules, espaces réduits, caractères spéciaux retirés, 40 caractères
    max par tag, 15 tags max, sans doublon (ordre conservé)."""
    if raw is None:
        return []
    items: Iterable[Any] = re.split(r"[,;\n]", raw) if isinstance(raw, str) else raw
    out: List[str] = []
    seen = set()
    for item in items:
        tag = re.sub(r"[^\w\s\-.'&]", "", str(item or ""), flags=re.UNICODE)
        tag = re.sub(r"\s+", " ", tag).strip().lower()[:MAX_TAG_LEN].strip()
        key = norm_text(tag)
        if tag and key not in seen:
            seen.add(key)
            out.append(tag)
        if len(out) >= MAX_TAGS:
            break
    return out


def clean_description(raw: Any) -> str:
    return re.sub(r"\s+", " ", str(raw or "")).strip()[:MAX_DESCRIPTION]


def split_key(code: str, key: str) -> Dict[str, str]:
    """Dossier et nom d'un fichier à partir de sa clé R2 `<code>/<dossier>/<nom>`
    (ou `<code>/<nom>` pour un fichier posé à la racine → dossier `_racine`)."""
    rest = key[len(code) + 1:]
    if "/" in rest:
        folder, name = rest.split("/", 1)
        return {"folder": folder, "name": name}
    return {"folder": ROOT_FOLDER, "name": rest}


def is_ai_taggable(name: str, size: Optional[int]) -> bool:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in AI_EXTENSIONS and (size is None or size <= AI_MAX_BYTES)


def guess_content_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


# ----------------------------------------------------------------------
# Lot 23 — extraction du texte intégral (sans IA)
# ----------------------------------------------------------------------
def _xml_text(xml: bytes) -> str:
    """Texte d'une partie XML Office : balises retirées, entités de base décodées."""
    txt = re.sub(r"<(w:p|a:p|row)[ >/]", "\n<", xml.decode("utf-8", errors="ignore"))  # fins de paragraphe/ligne
    txt = re.sub(r"<[^>]+>", " ", txt)
    for ent, ch in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        txt = txt.replace(ent, ch)
    return txt


def extract_text(data: bytes, name: str, content_type: str = "") -> str:
    """Texte intégral d'un document (20 000 caractères au plus), ou "" si le
    format n'en porte pas (image, PDF scanné…). Ne lève jamais."""
    if not data or len(data) > TEXT_EXTRACT_MAX_BYTES:
        return ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    try:
        if ext == "pdf" or content_type == "application/pdf":
            import fitz  # PyMuPDF, déjà utilisé par ocr_core
            with fitz.open(stream=data, filetype="pdf") as pdf:
                text = "\n".join(pdf[i].get_text() for i in range(min(len(pdf), TEXT_PDF_MAX_PAGES)))
        elif ext in ("txt", "csv", "tsv", "md", "json", "xml") or content_type.startswith("text/"):
            text = data.decode("utf-8", errors="ignore")
        elif ext in _OFFICE_XML:
            parts = []
            with zipfile.ZipFile(BytesIO(data)) as z:
                for member in sorted(z.namelist()):
                    if member.startswith(_OFFICE_XML[ext]) and member.endswith(".xml"):
                        parts.append(_xml_text(z.read(member)))
            text = "\n".join(parts)
        else:
            return ""
    except Exception:  # noqa: BLE001 — fichier corrompu/protégé : pas de texte, pas d'erreur
        logger.info("[gestion_stocks.tags] extraction de texte impossible pour %s", name)
        return ""
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()[:MAX_CONTENT_CHARS]


async def index_content(db, *, key: str, data: bytes, name: str, content_type: str = "") -> int:
    """Extrait le texte d'un fichier et l'enregistre sur sa fiche
    (`content_text`, `text_indexed_at`). Renvoie le nombre de caractères."""
    text = await asyncio.to_thread(extract_text, data, name, content_type)
    await db.stock_files.update_one({"key": key}, {"$set": {"content_text": text, "text_indexed_at": _now()}})
    return len(text)


def schedule_index_content(db, *, key: str, name: str, content_type: str = "", size: Optional[int] = None) -> bool:
    """Indexe en arrière-plan un fichier déjà présent dans R2 (lu depuis R2).
    Renvoie False si le fichier est trop gros ou d'un format sans texte."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if (size or 0) > TEXT_EXTRACT_MAX_BYTES or ext not in ({"pdf", "txt", "csv", "tsv", "md", "json", "xml"} | set(_OFFICE_XML)):
        return False

    async def _run():
        try:
            from r2_stocks_client import get_bytes
            data = await asyncio.to_thread(get_bytes, key)
            await index_content(db, key=key, data=data, name=name, content_type=content_type)
        except Exception:  # noqa: BLE001
            logger.exception("[gestion_stocks.tags] indexation en arrière-plan échouée pour %s", key)
    task = asyncio.get_event_loop().create_task(_run())
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    return True


def snippet(text: str, words: List[str], width: int = 70) -> str:
    """Extrait du texte autour du premier mot trouvé (« …les 12 boîtes de DOLIPRANE… »)."""
    if not text or not words:
        return ""
    norm = norm_text(text)
    pos = -1
    for w in words:
        pos = norm.find(w)
        if pos >= 0:
            break
    if pos < 0:
        return ""
    # norm_text ne change pas la longueur à ±quelques caractères près (accents
    # retirés, espaces réduits) : l'extrait est pris sur le texte d'origine réduit.
    flat = re.sub(r"\s+", " ", text).strip()
    start = max(0, pos - width)
    return ("…" if start else "") + flat[start:pos + width].strip() + ("…" if pos + width < len(flat) else "")


def clean_folder_name(raw: Any) -> str:
    """Nom de dossier créé depuis la page : lettres, chiffres, espaces, - _ . ( ),
    60 caractères au plus, jamais « . », « .. », ni commençant par un point."""
    name = re.sub(r"[^\w\s\-.()]", "", str(raw or ""), flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip()[:60].strip()
    if not name or name.startswith(".") or name in (".", ".."):
        return ""
    return name


async def rename_tag(db, code: str, old: str, new: str) -> int:
    """Renomme un tag pour tous les fichiers du client (fusion si le nouveau
    tag existe déjà sur un fichier ; `new` vide = retirer le tag partout).
    Renvoie le nombre de fichiers modifiés."""
    old_norm = norm_text(old)
    new_tag = (clean_tags([new]) or [""])[0]
    changed = 0
    async for d in db.stock_files.find({"client_code": code, "tags.0": {"$exists": True}}, {"_id": 0, "key": 1, "tags": 1}):
        tags = d.get("tags") or []
        if not any(norm_text(t) == old_norm for t in tags):
            continue
        replaced = [new_tag if norm_text(t) == old_norm else t for t in tags]
        await db.stock_files.update_one({"key": d["key"]}, {"$set": {"tags": clean_tags([t for t in replaced if t]),
                                                                     "updated_at": _now()}})
        changed += 1
    return changed


# ----------------------------------------------------------------------
# Tags déduits de l'analyse ocr_core
# ----------------------------------------------------------------------
def tags_from_ocr(result: Dict[str, Any]) -> List[str]:
    """Tags proposés à partir d'un résultat ocr_core : type de document,
    fournisseur/émetteur, mois et année du document (6 au plus)."""
    tags: List[str] = []
    if result.get("document_type"):
        tags.append(str(result["document_type"]))
    fields = result.get("extracted_fields") or {}
    date_done = False
    for k, v in fields.items():
        kn = norm_text(k)
        if isinstance(v, str) and len(v.strip()) <= MAX_TAG_LEN and any(
            w in kn for w in ("fournisseur", "emetteur", "laboratoire", "grossiste", "vendeur", "repartiteur")
        ):
            tags.append(v)
        if not date_done and ("date" in kn or "periode" in kn):
            m = re.search(r"(20\d{2}|19\d{2})-(\d{2})", str(v))
            if m and 1 <= int(m.group(2)) <= 12:
                tags += [f"{_MOIS[int(m.group(2)) - 1]} {m.group(1)}", m.group(1)]
                date_done = True
    return clean_tags(tags)[:6]


# ----------------------------------------------------------------------
# Accès à l'index Mongo
# ----------------------------------------------------------------------
async def tenant_ai_enabled(db, code: str) -> bool:
    """Suggestions IA activées pour ce client (désactivées par défaut)."""
    tenant = await db.users.find_one(
        {"client_code": {"$in": [code, code.lower()]}, "tracked_user_id": {"$in": [None, ""]},
         "tracked_role": {"$in": [None, ""]}},
        {"_id": 0, "gestion_stocks_ai_tags": 1},
    )
    return bool((tenant or {}).get("gestion_stocks_ai_tags"))


async def index_upload(db, *, code: str, key: str, size: int, content_type: str, user: dict,
                       tags: Any = None, description: Any = None) -> Dict[str, Any]:
    """Crée ou met à jour la fiche d'un fichier qui vient d'être déposé
    (un dépôt sous le même nom remplace le fichier : la fiche est conservée,
    ses tags aussi sauf si de nouveaux tags sont fournis)."""
    parts = split_key(code, key)
    now = _now()
    set_doc: Dict[str, Any] = {
        "client_code": code, "folder": parts["folder"], "name": parts["name"], "size": size,
        "content_type": content_type, "updated_at": now,
        "uploaded_by": user.get("id"), "uploaded_by_name": user.get("full_name") or user.get("email") or "",
    }
    new_tags = clean_tags(tags)
    if new_tags:
        set_doc["tags"] = new_tags
    if description is not None and clean_description(description):
        set_doc["description"] = clean_description(description)
    on_insert = {"id": str(uuid.uuid4()), "key": key, "created_at": now,
                 "ai_suggested_tags": [], "ai_suggested_description": "", "ai_cost_xof": 0.0}
    if "tags" not in set_doc:
        on_insert["tags"] = []
    if "description" not in set_doc:
        on_insert["description"] = ""
    await db.stock_files.update_one({"key": key}, {"$set": set_doc, "$setOnInsert": on_insert}, upsert=True)
    return await db.stock_files.find_one({"key": key}, {"_id": 0})


async def ensure_docs(db, code: str, files: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Fiches des fichiers listés, créées au passage pour les fichiers qui
    n'en ont pas encore (fichiers déposés avant le lot 22 ou depuis Cloudflare).
    Renvoie {clé R2: fiche}."""
    keys = [f["key"] for f in files]
    docs = {d["key"]: d async for d in db.stock_files.find({"key": {"$in": keys}}, {"_id": 0})}
    now = _now()
    missing = []
    for f in files:
        if f["key"] in docs:
            continue
        parts = split_key(code, f["key"])
        doc = {"id": str(uuid.uuid4()), "client_code": code, "key": f["key"], "folder": parts["folder"],
               "name": parts["name"], "size": f.get("size"), "content_type": guess_content_type(parts["name"]),
               "tags": [], "description": "", "uploaded_by": None, "uploaded_by_name": "",
               "ai_suggested_tags": [], "ai_suggested_description": "", "ai_cost_xof": 0.0,
               "created_at": now, "updated_at": now}
        missing.append(doc)
        docs[f["key"]] = doc
    if missing:
        await db.stock_files.insert_many([dict(d) for d in missing])
    return docs


def can_edit(user: dict, doc: Optional[Dict[str, Any]], *, is_staff: bool, upload_allowed: bool) -> bool:
    """Admin/superviseur : tout. Utilisateur suivi : seulement s'il est
    autorisé à déposer ET que le fichier est le sien."""
    if is_staff:
        return True
    return bool(upload_allowed and doc and doc.get("uploaded_by") and doc.get("uploaded_by") == user.get("id"))


def public_meta(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Champs de la fiche renvoyés à l'écran."""
    doc = doc or {}
    return {
        "tags": doc.get("tags") or [],
        "description": doc.get("description") or "",
        "uploaded_by_name": doc.get("uploaded_by_name") or "",
        "ai_suggested_tags": [t for t in (doc.get("ai_suggested_tags") or []) if t not in (doc.get("tags") or [])],
        "ai_suggested_description": doc.get("ai_suggested_description") or "",
        "ai_error": doc.get("ai_error") or "",
    }


async def tag_counts(db, code: str) -> List[Dict[str, Any]]:
    """Tags utilisés par ce client avec leur nombre de fichiers (les plus
    fréquents d'abord) — suggestions de saisie et pastilles de filtre."""
    counts: Dict[str, int] = {}
    async for d in db.stock_files.find({"client_code": code, "tags.0": {"$exists": True}}, {"_id": 0, "tags": 1}):
        for t in d.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": t, "count": n} for t, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


def search(objects: List[Dict[str, Any]], docs: Dict[str, Dict[str, Any]], code: str,
           q: str = "", tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Recherche dans TOUS les dossiers du client : chaque mot de `q` doit
    figurer dans le nom, les tags, la description ou (lot 23) le texte intégral
    du document (sans tenir compte des accents ni des majuscules) ; chaque tag
    de `tags` doit être posé sur le fichier.
    `objects` = contenu réel de R2 (source de vérité), `docs` = fiches Mongo."""
    words = norm_text(q).split()
    wanted = [norm_text(t) for t in (tags or [])]
    out = []
    for o in objects:
        parts = split_key(code, o["key"])
        doc = docs.get(o["key"]) or {}
        file_tags = doc.get("tags") or []
        norm_tags = [norm_text(t) for t in file_tags]
        if any(t not in norm_tags for t in wanted):
            continue
        match_snippet = ""
        if words:
            meta_hay = norm_text(" ".join([parts["name"], parts["folder"], *file_tags, doc.get("description") or ""]))
            content = " ".join([doc.get("content_text") or "", doc.get("ai_text") or ""])
            hay = meta_hay + " " + norm_text(content)
            if any(w not in hay for w in words):
                continue
            # Lot 23 — trouvé grâce au contenu : on montre l'extrait correspondant.
            if any(w not in meta_hay for w in words):
                match_snippet = snippet(content, [w for w in words if w not in meta_hay])
        out.append({"key": o["key"], "name": parts["name"], "folder": parts["folder"],
                    "size": o.get("size"), "last_modified": o.get("last_modified"), **public_meta(doc),
                    "match_snippet": match_snippet})
    out.sort(key=lambda f: f.get("last_modified") or "", reverse=True)
    return out[:MAX_SEARCH_RESULTS]


# ----------------------------------------------------------------------
# Suggestions IA
# ----------------------------------------------------------------------
async def suggest_tags(db, *, code: str, key: str, data: bytes, content_type: str, filename: str) -> Dict[str, Any]:
    """Analyse le fichier avec ocr_core (Haiku 4.5) et enregistre les tags et
    la description suggérés sur sa fiche. Ne lève jamais : en cas d'échec, le
    motif est enregistré dans `ai_error`."""
    import ocr_core
    result = await ocr_core.analyze_document(
        data, content_type, filename, AI_TAGS_MODEL,
        system_prompt=_ai_system_prompt(), default_model=AI_TAGS_MODEL,
    )
    suggested = tags_from_ocr(result)
    description = clean_description(result.get("summary"))
    error = "" if (suggested or description) else ((result.get("flags") or ["Aucun tag trouvé"])[0])
    cost = float(result.get("cost_xof") or 0.0)
    await db.stock_files.update_one({"key": key}, {
        "$set": {"ai_suggested_tags": suggested, "ai_suggested_description": description,
                 "ai_model": result.get("model") or AI_TAGS_MODEL, "ai_at": _now(), "ai_error": error,
                 # Lot 23 — ce que l'IA a lu (synthèse + champs) est cherchable, utile pour les scans.
                 "ai_text": " ".join([description, *[f"{k} {v}" for k, v in (result.get("extracted_fields") or {}).items()
                                                     if isinstance(v, (str, int, float))]])[:MAX_CONTENT_CHARS]},
        "$inc": {"ai_cost_xof": cost},
    })
    logger.info("[gestion_stocks.tags] IA %s : %d tag(s), %.2f FCFA", key, len(suggested), cost)
    return {"ai_suggested_tags": suggested, "ai_suggested_description": description,
            "ai_error": error, "cost_xof": cost}


def schedule_suggest(db, **kwargs) -> None:
    """Lance `suggest_tags` en arrière-plan après un dépôt : le dépôt répond
    tout de suite, les suggestions apparaissent au rafraîchissement suivant."""
    async def _run():
        try:
            await suggest_tags(db, **kwargs)
        except Exception:  # noqa: BLE001 — ne jamais faire échouer un dépôt pour ça
            logger.exception("[gestion_stocks.tags] suggestion IA en arrière-plan échouée pour %s", kwargs.get("key"))
    task = asyncio.get_event_loop().create_task(_run())
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


async def maybe_schedule_after_upload(db, *, code: str, key: str, data: bytes, content_type: str) -> bool:
    """Après un dépôt : lance les suggestions IA si le client les a activées
    et que le fichier s'y prête. Renvoie True si une analyse est lancée."""
    name = split_key(code, key)["name"]
    if not is_ai_taggable(name, len(data)) or not await tenant_ai_enabled(db, code):
        return False
    schedule_suggest(db, code=code, key=key, data=data, content_type=content_type or guess_content_type(name),
                     filename=name)
    return True


__all__ = [
    "AI_TAGS_MODEL", "MAX_TAGS", "can_edit", "clean_description", "clean_tags", "ensure_docs",
    "index_upload", "is_ai_taggable", "maybe_schedule_after_upload", "norm_text", "public_meta",
    "search", "split_key", "suggest_tags", "tag_counts", "tags_from_ocr", "tenant_ai_enabled",
    # Lot 23
    "clean_folder_name", "extract_text", "index_content", "rename_tag", "schedule_index_content", "snippet",
]
