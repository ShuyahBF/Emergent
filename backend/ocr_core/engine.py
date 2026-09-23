"""Appel au modèle Claude via la clé universelle EMERGENT_LLM_KEY.

Compatible avec les deux versions d'emergentintegrations en service :
  - 0.2.0 (Albarka) : `LlmChat.send_message_with_tools()` est la méthode
    publique qui renvoie l'usage réel en tokens (`ChatResponse.usage`) ;
  - 0.1.0 (Sawali) : `send_message()` ne renvoie que le texte ; on appelle
    donc `_execute_completion()` (réponse brute LiteLLM, avec `usage`) dans un
    thread dédié, car en 0.1.0 cet appel est synchrone et bloquerait le serveur.
Dans les deux cas, le coût est calculé sur les tokens RÉELLEMENT consommés.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from .models import OCR_MODELS, OcrModel, compute_cost, default_model_id, get_model
from .prepare import prepare_document

logger = logging.getLogger("ocr_core")

MODEL_PROVIDER = "anthropic"
MAX_OUTPUT_TOKENS = 8192

# Format de réponse imposé au modèle — identique sur tous les sites, pour
# que la précision et le tableau de bord se comparent d'un site à l'autre.
_RESPONSE_FORMAT = (
    "Analyse le document et réponds UNIQUEMENT avec un objet JSON strict, sans "
    "aucun texte avant ou après ni bloc de code, au format :\n"
    "{\n"
    '  "document_type": "<type précis en français>",\n'
    '  "summary": "<synthèse claire en 3-6 phrases, en français>",\n'
    '  "extracted_fields": { <clés/valeurs pertinents : numéro, date, émetteur, IFU, RCCM, client, '
    "lignes, sous-total, taxes, montant total, période... — montants en nombres sans séparateur "
    'de milliers, dates au format AAAA-MM-JJ> },\n'
    '  "flags": ["<alerte éventuelle : pièce illisible, information manquante, incohérence...>"],\n'
    '  "confidence": <nombre entre 0 et 1 : ta confiance globale dans l\'extraction>,\n'
    '  "uncertain_fields": ["<clés de extracted_fields dont tu n\'es pas sûr (écriture peu lisible, tampon...)>"]\n'
    "}\n"
    "Si une information est illisible, mets null plutôt que de la deviner et cite la clé dans "
    "\"uncertain_fields\". Si le document est illisible ou d'un type non reconnaissable, dis-le "
    "dans \"flags\" plutôt que d'inventer."
)


def build_system_prompt(organisation: str, documents: str) -> str:
    """Consigne système : seule partie propre à chaque site (qui on est, quelles pièces).

    organisation : ex. « le cabinet ALBARKA (cabinet d'assistance fiscale et
                   comptable au Burkina Faso) »
    documents    : ex. « facture, reçu, relevé bancaire, bulletin de paie… »
    """
    return (
        f"Tu es l'assistant d'analyse documentaire de {organisation}. On te soumet une pièce "
        f"téléversée ({documents}), souvent scannée ou photographiée, parfois manuscrite, avec "
        "tampon, cachet ou filigrane. Si le document a plusieurs pages, elles te sont transmises "
        "dans l'ordre. " + _RESPONSE_FORMAT
    )


# ---------------------------------------------------------------------
# Lecture de la réponse
# ---------------------------------------------------------------------
def parse_json(text: str) -> Dict[str, Any]:
    """Tolère un éventuel bloc ```json``` ou du texte parasite autour du JSON."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise
        return json.loads(text[start:end + 1])


def _clamp_confidence(value: Any) -> Optional[float]:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def empty_result(model_id: str, flag: str, error: Optional[str] = None) -> Dict[str, Any]:
    """Résultat vide (analyse impossible) — même forme qu'un résultat normal."""
    result: Dict[str, Any] = {
        "summary": "", "extracted_fields": {}, "document_type": None, "flags": [flag],
        "confidence": None, "uncertain_fields": [], "model": model_id, "input_mode": None,
        "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "cost_xof": 0.0,
        "pages_analyzed": 0, "duration_ms": 0,
    }
    if error:
        result["error"] = error
    return result


# ---------------------------------------------------------------------
# Appel au modèle
# ---------------------------------------------------------------------
def _usage_of(raw: Any) -> Tuple[int, int]:
    """Tokens (entrée, sortie) d'une réponse LiteLLM, noms OpenAI ou Anthropic."""
    u = getattr(raw, "usage", None)
    if u is None:
        return 0, 0
    tin = getattr(u, "prompt_tokens", None) or getattr(u, "input_tokens", 0) or 0
    tout = getattr(u, "completion_tokens", None) or getattr(u, "output_tokens", 0) or 0
    return int(tin), int(tout)


async def call_llm(model: OcrModel, system_prompt: str, text: str, images: List[bytes], filename: str) -> Tuple[str, int, int]:
    """Envoie texte ou images au modèle ; renvoie (réponse, tokens_entrée, tokens_sortie)."""
    from emergentintegrations.llm.chat import ImageContent, LlmChat, UserMessage

    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise RuntimeError("Clé LLM non configurée (EMERGENT_LLM_KEY)")
    chat = LlmChat(
        api_key=api_key,
        session_id=f"ocr-core-{secrets.token_urlsafe(8)}",
        system_message=system_prompt,
    ).with_model(MODEL_PROVIDER, model.id).with_params(max_tokens=MAX_OUTPUT_TOKENS)

    if images:
        message = UserMessage(
            text=f"Nom du fichier : {filename}. Analyse cette pièce ({len(images)} page(s)).",
            file_contents=[ImageContent(image_base64=base64.b64encode(img).decode("ascii")) for img in images],
        )
    else:
        message = UserMessage(text=(
            f"Nom du fichier : {filename}\n\nContenu extrait du document :\n---\n{text}\n---\n\n"
            "Analyse ce document et réponds uniquement en JSON strict."
        ))

    # emergentintegrations 0.2.0 : méthode publique avec usage réel
    if hasattr(chat, "send_message_with_tools"):
        response = await chat.send_message_with_tools(message)
        return response.content or "", int(response.usage.input_tokens or 0), int(response.usage.output_tokens or 0)

    # emergentintegrations 0.1.0 : même construction de message que send_message(),
    # puis réponse brute (avec usage) calculée dans un thread (appel synchrone en 0.1.0).
    messages = await chat.get_messages()
    await chat._add_user_message(messages, message)
    raw = await asyncio.to_thread(lambda: asyncio.run(chat._execute_completion(messages)))
    content = raw.choices[0].message.content or ""
    tin, tout = _usage_of(raw)
    return content, tin, tout


async def analyze_document(
    data: bytes,
    content_type: str,
    filename: str,
    model_id: Optional[str] = None,
    *,
    system_prompt: str,
    default_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyse une pièce ; ne lève jamais — retourne toujours un dict.

    Résultat : summary, extracted_fields, document_type, flags, confidence,
    uncertain_fields, model, input_mode ("texte"/"images"), input_tokens,
    output_tokens, cost_usd, cost_xof, pages_analyzed, duration_ms (+ error).
    """
    model = get_model(model_id) or get_model(default_model) or OCR_MODELS[default_model_id()]

    # 1. Préparation : texte, images ou refus (format non analysable)
    try:
        text, images, notes = prepare_document(data, content_type)
    except ValueError as exc:
        return empty_result(model.id, str(exc))
    except Exception as exc:  # noqa: BLE001 — image corrompue, PDF protégé...
        logger.exception("Préparation impossible pour %s", filename)
        return empty_result(model.id, f"Fichier illisible : {exc}", error=str(exc))

    # 2. Appel au modèle
    started = time.monotonic()
    try:
        reply, input_tokens, output_tokens = await call_llm(model, system_prompt, text, images, filename)
    except Exception as exc:  # noqa: BLE001 — réseau, quota, clé absente, modèle inconnu du proxy...
        logger.exception("Erreur analyse IA (%s) pour %s", model.id, filename)
        return empty_result(model.id, f"Erreur d'analyse : {exc}", error=str(exc))

    # 3. Coût calculé AVANT le parsing : les tokens sont facturés même si la
    #    réponse est inexploitable.
    cost_usd, cost_xof = compute_cost(model, input_tokens, output_tokens)
    metrics = {
        "model": model.id, "input_mode": "images" if images else "texte",
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "cost_usd": cost_usd, "cost_xof": cost_xof,
        "pages_analyzed": len(images) if images else 1,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    try:
        parsed = parse_json(reply)
    except json.JSONDecodeError as exc:
        logger.exception("Réponse IA non-JSON (%s) pour %s", model.id, filename)
        result = empty_result(model.id, "Réponse de l'IA au format inattendu", error=str(exc))
        result.update(metrics)
        return result

    fields = parsed.get("extracted_fields") or {}
    if not isinstance(fields, dict):
        fields = {"valeur": fields}
    return {
        "summary": parsed.get("summary", ""),
        "extracted_fields": fields,
        "document_type": parsed.get("document_type"),
        "flags": list(parsed.get("flags") or []) + notes,
        "confidence": _clamp_confidence(parsed.get("confidence")),
        "uncertain_fields": [k for k in (parsed.get("uncertain_fields") or []) if isinstance(k, str)],
        **metrics,
    }
