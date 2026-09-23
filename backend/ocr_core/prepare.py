"""Préparation d'une pièce avant l'envoi au modèle (optimisation OCR).

  - PDF avec une vraie couche texte (généré par un logiciel) → texte extrait
    par PyMuPDF : le mode le moins cher ;
  - PDF scanné (pas ou peu de texte) → chaque page convertie en image ;
  - photo → redressée (EXIF) et réduite à 1568 px sur le grand côté, taille à
    laquelle Claude la réduit de toute façon (requête plus légère, même lisibilité) ;
  - txt / csv → texte brut ; Word / Excel → non analysable (ValueError).
"""
from __future__ import annotations

import io
from typing import List, Tuple

MAX_IMAGE_EDGE_PX = 1568       # au-delà, Claude réduit lui-même l'image
PDF_RENDER_DPI = 150           # suffisant pour lire un scan A4
MAX_PDF_PAGES = 10             # pages suivantes non analysées (une alerte le signale)
MIN_TEXT_CHARS_PER_PAGE = 200  # en dessous : PDF considéré comme scanné
MAX_TEXT_CHARS = 20000
JPEG_QUALITY = 85

IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
TEXT_MIMES = {"text/plain", "text/csv"}


def shrink_image(data: bytes) -> bytes:
    """Redresse (EXIF), réduit à MAX_IMAGE_EDGE_PX et ré-encode en JPEG."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)          # photos de téléphone prises « de côté »
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")                # JPEG : ni transparence ni palette
        img.thumbnail((MAX_IMAGE_EDGE_PX, MAX_IMAGE_EDGE_PX))  # proportions gardées, jamais agrandie
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue()


def prepare_pdf(data: bytes) -> Tuple[str, List[bytes], List[str]]:
    """PDF → (texte, [], notes) si la couche texte est exploitable, sinon
    ("", [pages en JPEG], notes) pour un PDF scanné."""
    import fitz  # PyMuPDF

    notes: List[str] = []
    with fitz.open(stream=data, filetype="pdf") as pdf:
        total = pdf.page_count
        pages = list(pdf.pages(0, min(total, MAX_PDF_PAGES)))
        if total > MAX_PDF_PAGES:
            notes.append(f"Seules les {MAX_PDF_PAGES} premières pages sur {total} ont été analysées.")
        text = "\n".join(p.get_text() for p in pages).strip()
        if pages and len(text) / len(pages) >= MIN_TEXT_CHARS_PER_PAGE:
            return text[:MAX_TEXT_CHARS], [], notes
        images = [shrink_image(p.get_pixmap(dpi=PDF_RENDER_DPI).tobytes("png")) for p in pages]
    if not images:
        raise ValueError("PDF vide ou illisible")
    return "", images, notes


def prepare_document(data: bytes, content_type: str) -> Tuple[str, List[bytes], List[str]]:
    """Pièce → (texte, images, alertes). Exactement l'un de texte/images est rempli.

    Lève ValueError pour un format non analysable (Word, Excel…)."""
    if content_type == "application/pdf":
        return prepare_pdf(data)
    if content_type in IMAGE_MIMES:
        return "", [shrink_image(data)], []
    if content_type in TEXT_MIMES or content_type.startswith("text/"):
        text = data.decode("utf-8", errors="ignore")[:MAX_TEXT_CHARS]
        if text.strip():
            return text, [], []
    raise ValueError(f"Type de fichier non pris en charge pour l'analyse : {content_type}")
