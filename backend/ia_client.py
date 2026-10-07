"""Client IA local de SAWALI (lot 53 : indépendance d'Emergent).

Remplace la bibliothèque privée « emergentintegrations » (index Emergent,
clé universelle EMERGENT_LLM_KEY) par les SDK officiels, avec la MÊME
interface que celle utilisée dans le code :

    chat = LlmChat(api_key=..., session_id=..., system_message=...)
    chat = chat.with_model("anthropic", "claude-haiku-4-5-20251001").with_params(max_tokens=8192)
    texte = await chat.send_message(UserMessage(text=..., file_contents=[ImageContent(image_base64=...)]))
    rep = await chat.send_message_with_tools(message)        # rep.content, rep.usage.input_tokens / output_tokens
    texte, images = await chat.send_message_multimodal_response(message)   # images Gemini

Fournisseurs et clés (le paramètre `api_key` des appelants est IGNORÉ : c'était
souvent EMERGENT_LLM_KEY ; on lit la clé du fournisseur) :
    anthropic -> ANTHROPIC_API_KEY        (SDK officiel `anthropic`, AsyncAnthropic)
    openai    -> OPENAI_API_KEY           (SDK officiel `openai`)
    gemini    -> GOOGLE_GEMINI_API_KEY    (SDK `google-genai`, déjà présent)
`cle_ia(fournisseur)` renvoie cette clé ("" si absente) : les appelants qui
testent `if not api_key` continuent de fonctionner.

Également ici, mêmes interfaces que l'usage réel du code :
    OpenAIImageGeneration (images), OpenAIVideoGeneration (Sora, REST httpx),
    OpenAISpeechToText (dictée, Whisper).

L'historique de la conversation est conservé par instance de LlmChat (plusieurs
send_message successifs sur la même instance = même conversation).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import importlib
import logging
import os
import pathlib
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sawali.ia_client")

# ---------------------------------------------------------------------------
# Clés des fournisseurs
# ---------------------------------------------------------------------------
# Variables lues pour chaque fournisseur, dans l'ordre (la première non vide gagne).
VARIABLES_CLES: Dict[str, Tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GOOGLE_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
}
FOURNISSEUR_DEFAUT = "anthropic"
MAX_TOKENS_DEFAUT = 8192
# Au-delà, la réponse est reçue en flux (évite le délai maximal d'un appel simple).
SEUIL_FLUX_TOKENS = 16000
DELAI_SECONDES = 600.0


def _fournisseur(provider: Optional[str]) -> str:
    p = (provider or FOURNISSEUR_DEFAUT).strip().lower()
    if p in ("google", "gemeni", "vertex"):
        return "gemini"
    if p in ("claude",):
        return "anthropic"
    return p


def cle_ia(provider: str = FOURNISSEUR_DEFAUT) -> str:
    """Clé API du fournisseur IA ("" si elle n'est pas définie)."""
    for nom in VARIABLES_CLES.get(_fournisseur(provider), ()):
        valeur = (os.environ.get(nom) or "").strip()
        if valeur:
            return valeur
    return ""


def variable_cle(provider: str = FOURNISSEUR_DEFAUT) -> str:
    """Nom de la variable d'environnement attendue (pour les messages d'erreur)."""
    noms = VARIABLES_CLES.get(_fournisseur(provider), ("ANTHROPIC_API_KEY",))
    return noms[0]


class ChatError(Exception):
    """Erreur d'un appel IA (même nom que dans emergentintegrations)."""


# ---------------------------------------------------------------------------
# Contenus des messages
# ---------------------------------------------------------------------------
class FileContent:
    def __init__(self, content_type: str, file_content_base64: str) -> None:
        self.content_type = content_type
        self.file_content_base64 = file_content_base64


def _nettoyer_b64(donnees: str) -> Tuple[str, Optional[str]]:
    """Retire un éventuel préfixe « data:<type>;base64, » et les blancs -> (base64, type du préfixe)."""
    s = (donnees or "").strip()
    type_prefixe = None
    m = re.match(r"^data:([\w.+/-]+);base64,", s)
    if m:
        type_prefixe = m.group(1).lower()
        s = s[m.end():]
    return re.sub(r"\s+", "", s), type_prefixe


def type_mime_base64(donnees_b64: str) -> str:
    """Type MIME d'un contenu base64 d'après ses premiers octets (jpeg, png, gif, webp, pdf)."""
    b64, type_prefixe = _nettoyer_b64(donnees_b64)
    try:
        tete = base64.b64decode(b64[:64] + "=" * (-len(b64[:64]) % 4), validate=False)
    except (binascii.Error, ValueError):
        tete = b""
    if tete.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if tete.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if tete[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if tete[:4] == b"RIFF" and tete[8:12] == b"WEBP":
        return "image/webp"
    if tete.startswith(b"%PDF"):
        return "application/pdf"
    return type_prefixe or "image/png"   # même défaut qu'emergentintegrations


class ImageContent(FileContent):
    def __init__(self, image_base64: str) -> None:
        super().__init__("image", image_base64)

    @staticmethod
    def get_mime_type(file_content_base64: str) -> str:
        return type_mime_base64(file_content_base64)


class FileContentWithMimeType(FileContent):
    def __init__(self, mime_type: str, file_path: str) -> None:
        donnees = pathlib.Path(file_path).read_bytes()
        super().__init__(mime_type, base64.b64encode(donnees).decode("ascii"))


class UserMessage:
    def __init__(self, text: Optional[str] = None, file_contents: Optional[List[FileContent]] = None) -> None:
        self.text = text
        self.file_contents = file_contents or []


class Usage:
    def __init__(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.input_tokens = int(input_tokens or 0)
        self.output_tokens = int(output_tokens or 0)
        # Noms OpenAI / LiteLLM (lus par certains appelants)
        self.prompt_tokens = self.input_tokens
        self.completion_tokens = self.output_tokens


class ChatResponse:
    """Réponse avec l'usage réel en tokens (comme send_message_with_tools d'emergentintegrations 0.2.0)."""

    def __init__(self, content: str, usage: Usage, images: Optional[List[Dict[str, str]]] = None) -> None:
        self.content = content
        self.usage = usage
        self.images = images or []


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class ReponseBrute:
    """Réponse au format LiteLLM (choices[0].message.content + usage) pour _execute_completion."""

    def __init__(self, reponse: ChatResponse) -> None:
        self.choices = [_Choice(reponse.content)]
        self.usage = reponse.usage


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------
# Format interne neutre d'un message : {"role": "user"|"assistant", "parts": [...]}
#   part = {"type": "text", "text": ...}
#        | {"type": "image", "media_type": ..., "data": <base64>}
#        | {"type": "document", "media_type": ..., "data": <base64>}


def _parts_du_message(message: UserMessage) -> List[Dict[str, str]]:
    """Images et documents d'abord, puis le texte (ordre conseillé pour la vision)."""
    parts: List[Dict[str, str]] = []
    for contenu in message.file_contents or []:
        b64, type_prefixe = _nettoyer_b64(contenu.file_content_base64)
        if not b64:
            continue
        if contenu.content_type == "image":
            mt = type_mime_base64(contenu.file_content_base64)
        else:
            mt = (contenu.content_type or type_prefixe or "application/octet-stream").lower()
        genre = "image" if mt.startswith("image/") else "document"
        parts.append({"type": genre, "media_type": mt, "data": b64})
    if message.text:
        parts.append({"type": "text", "text": message.text})
    if not parts:
        parts.append({"type": "text", "text": " "})
    return parts


class LlmChat:
    """Même interface que emergentintegrations.llm.chat.LlmChat (SDK officiels en dessous)."""

    def __init__(self, api_key: Optional[str] = None, session_id: Optional[str] = None,
                 system_message: str = "", initial_messages: Optional[List[Dict[str, Any]]] = None,
                 custom_headers: Optional[Dict[str, str]] = None) -> None:
        # api_key est ignorée : la clé vient de la variable du fournisseur (voir cle_ia).
        self.api_key = api_key
        self.session_id = session_id
        self.system_message = system_message or ""
        self.provider = FOURNISSEUR_DEFAUT
        self.model = "claude-sonnet-4-5-20250929"
        self.extra_params: Dict[str, Any] = {}
        self.custom_headers = custom_headers or {}
        self.messages: List[Dict[str, Any]] = []
        for m in initial_messages or []:
            role = m.get("role")
            if role == "system":
                if not self.system_message and isinstance(m.get("content"), str):
                    self.system_message = m["content"]
                continue
            if role in ("user", "assistant") and isinstance(m.get("content"), str):
                self.messages.append({"role": role, "parts": [{"type": "text", "text": m["content"]}]})

    # --- configuration -------------------------------------------------------
    def with_model(self, provider: str, model: str) -> "LlmChat":
        self.provider = _fournisseur(provider)
        self.model = model
        return self

    def with_params(self, **params: Any) -> "LlmChat":
        self.extra_params.update(params)
        return self

    def with_max_tokens(self, max_tokens: int) -> "LlmChat":
        self.extra_params["max_tokens"] = int(max_tokens)
        return self

    # --- historique (mêmes noms qu'emergentintegrations) ----------------------
    async def get_messages(self) -> List[Dict[str, Any]]:
        return self.messages

    async def _add_user_message(self, messages: List[Dict[str, Any]], message: UserMessage) -> None:
        messages.append({"role": "user", "parts": _parts_du_message(message)})
        self.messages = messages

    async def _add_assistant_message(self, messages: List[Dict[str, Any]], texte: str) -> None:
        messages.append({"role": "assistant", "parts": [{"type": "text", "text": texte or ""}]})
        self.messages = messages

    async def _execute_completion(self, messages: List[Dict[str, Any]]) -> ReponseBrute:
        """Appel brut sur un historique déjà construit (compatibilité 0.1.0)."""
        return ReponseBrute(await self._appeler(messages))

    # --- envoi ----------------------------------------------------------------
    async def send_message(self, user_message: UserMessage) -> str:
        return (await self.send_message_with_tools(user_message)).content

    async def send_message_with_tools(self, user_message: UserMessage) -> ChatResponse:
        """Envoie le message, garde la réponse dans l'historique ; renvoie contenu + usage réel."""
        messages = await self.get_messages()
        await self._add_user_message(messages, user_message)
        reponse = await self._appeler(messages)
        await self._add_assistant_message(messages, reponse.content)
        return reponse

    async def send_message_multimodal_response(self, user_message: UserMessage) -> Tuple[Optional[str],
                                                                                          List[Dict[str, str]]]:
        """(texte, images) ; images = [{"mime_type", "data" (base64)}] (génération d'images Gemini)."""
        messages = await self.get_messages()
        await self._add_user_message(messages, user_message)
        reponse = await self._appeler(messages, multimodal=True)
        if reponse.content:
            await self._add_assistant_message(messages, reponse.content)
        return (reponse.content or None), reponse.images

    # --- répartition par fournisseur -------------------------------------------
    async def _appeler(self, messages: List[Dict[str, Any]], multimodal: bool = False) -> ChatResponse:
        cle = cle_ia(self.provider)
        if not cle:
            raise ChatError(f"Clé IA absente : définir {variable_cle(self.provider)} "
                            f"(fournisseur « {self.provider} »).")
        try:
            if self.provider == "anthropic":
                return await _appel_anthropic(cle, self.model, self.system_message, messages, self.extra_params)
            if self.provider == "openai":
                return await _appel_openai(cle, self.model, self.system_message, messages, self.extra_params)
            if self.provider == "gemini":
                return await _appel_gemini(cle, self.model, self.system_message, messages, self.extra_params,
                                           multimodal)
        except ChatError:
            raise
        except Exception as exc:  # noqa: BLE001 — réseau, quota, clé refusée, modèle inconnu…
            raise ChatError(f"Échec de l'appel IA ({self.provider}/{self.model}) : {exc}") from exc
        raise ChatError(f"Fournisseur IA inconnu : « {self.provider} »")


# ---------------------------------------------------------------------------
# Lot 71.2 — SDK d'IA importés HORS de la boucle principale
# ---------------------------------------------------------------------------
# Le premier `from anthropic import …` (ou openai, google.genai) coûte ~3 s : fait directement dans une
# fonction async, il figeait tout le serveur (sentinelle du lot 71.1 : « [boucle-bloquee] … anthropic »).
_SDK_PRETS: set = set()


async def _sdk_pret(module: str) -> None:
    """Importe `module` dans un fil séparé la première fois ; ensuite, ne coûte plus rien."""
    if module in _SDK_PRETS:
        return
    try:
        await asyncio.to_thread(importlib.import_module, module)
    except Exception:  # noqa: BLE001 — module absent : l'appel suivant lèvera l'erreur habituelle
        return
    _SDK_PRETS.add(module)


def prechauffer_sdk() -> None:
    """Lot 71.2 — importe les SDK d'IA à l'avance (appelé dans un fil au démarrage du serveur)."""
    for module in ("anthropic", "openai", "google.genai"):
        try:
            importlib.import_module(module)
            _SDK_PRETS.add(module)
        except Exception:  # noqa: BLE001 — SDK non installé : ignoré
            pass


# ---------------------------------------------------------------------------
# Anthropic (SDK officiel)
# ---------------------------------------------------------------------------
def _nouveau_client_anthropic(cle: str):
    """Client asynchrone Anthropic (fonction séparée pour pouvoir la simuler en test)."""
    from anthropic import AsyncAnthropic
    return AsyncAnthropic(api_key=cle, timeout=DELAI_SECONDES, max_retries=2)


def messages_anthropic(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Historique interne -> `messages` de l'API Anthropic (rôles consécutifs identiques fusionnés)."""
    sortie: List[Dict[str, Any]] = []
    for m in messages:
        blocs: List[Dict[str, Any]] = []
        for p in m["parts"]:
            if p["type"] == "text":
                blocs.append({"type": "text", "text": p["text"]})
            elif p["type"] == "image":
                blocs.append({"type": "image", "source": {"type": "base64", "media_type": p["media_type"],
                                                          "data": p["data"]}})
            elif p["media_type"] == "application/pdf":
                blocs.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                             "data": p["data"]}})
            else:
                # Autre fichier (texte brut…) : contenu décodé en texte quand c'est possible
                try:
                    blocs.append({"type": "text", "text": base64.b64decode(p["data"]).decode("utf-8")})
                except (binascii.Error, ValueError, UnicodeDecodeError):
                    raise ChatError(f"Type de fichier non pris en charge par Claude : {p['media_type']}")
        if sortie and sortie[-1]["role"] == m["role"]:
            sortie[-1]["content"].extend(blocs)
        else:
            sortie.append({"role": m["role"], "content": blocs})
    return sortie


async def _appel_anthropic(cle: str, modele: str, systeme: str, messages: List[Dict[str, Any]],
                           params: Dict[str, Any]) -> ChatResponse:
    max_tokens = int(params.get("max_tokens") or MAX_TOKENS_DEFAUT)
    requete: Dict[str, Any] = {"model": modele, "max_tokens": max_tokens, "messages": messages_anthropic(messages)}
    if systeme:
        requete["system"] = systeme
    for nom in ("temperature", "top_p", "top_k"):
        if params.get(nom) is not None:
            requete[nom] = params[nom]
    if params.get("stop"):
        stop = params["stop"]
        requete["stop_sequences"] = [stop] if isinstance(stop, str) else list(stop)
    await _sdk_pret("anthropic")   # lot 71.2 : import hors de la boucle
    client = _nouveau_client_anthropic(cle)
    try:
        if max_tokens > SEUIL_FLUX_TOKENS:
            async with client.messages.stream(**requete) as flux:
                reponse = await flux.get_final_message()
        else:
            reponse = await client.messages.create(**requete)
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass
    if getattr(reponse, "stop_reason", None) == "refusal":
        raise ChatError("Requête refusée par le modèle (refusal).")
    texte = "".join(getattr(b, "text", "") or "" for b in (reponse.content or [])
                    if getattr(b, "type", None) == "text")
    if getattr(reponse, "stop_reason", None) == "max_tokens":
        logger.warning("[ia] réponse tronquée (max_tokens=%s, modèle %s)", max_tokens, modele)
    u = getattr(reponse, "usage", None)
    return ChatResponse(texte, Usage(getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0)))


# ---------------------------------------------------------------------------
# OpenAI (SDK officiel)
# ---------------------------------------------------------------------------
def _nouveau_client_openai(cle: str):
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=cle, timeout=DELAI_SECONDES, max_retries=2)


def messages_openai(systeme: str, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sortie: List[Dict[str, Any]] = [{"role": "system", "content": systeme}] if systeme else []
    for m in messages:
        if m["role"] == "assistant":
            sortie.append({"role": "assistant", "content": "".join(p.get("text", "") for p in m["parts"])})
            continue
        contenu: List[Dict[str, Any]] = []
        for p in m["parts"]:
            if p["type"] == "text":
                contenu.append({"type": "text", "text": p["text"]})
            elif p["type"] == "image":
                contenu.append({"type": "image_url",
                                "image_url": {"url": f"data:{p['media_type']};base64,{p['data']}"}})
            else:
                contenu.append({"type": "file", "file": {"filename": "document.pdf",
                                                         "file_data": f"data:{p['media_type']};base64,{p['data']}"}})
        sortie.append({"role": "user", "content": contenu})
    return sortie


async def _appel_openai(cle: str, modele: str, systeme: str, messages: List[Dict[str, Any]],
                        params: Dict[str, Any]) -> ChatResponse:
    requete: Dict[str, Any] = {"model": modele, "messages": messages_openai(systeme, messages)}
    if params.get("max_tokens"):
        requete["max_tokens"] = int(params["max_tokens"])
    for nom in ("temperature", "top_p", "stop"):
        if params.get(nom) is not None:
            requete[nom] = params[nom]
    await _sdk_pret("openai")   # lot 71.2 : import hors de la boucle
    client = _nouveau_client_openai(cle)
    try:
        reponse = await client.chat.completions.create(**requete)
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass
    texte = (reponse.choices[0].message.content or "") if reponse.choices else ""
    u = getattr(reponse, "usage", None)
    return ChatResponse(texte, Usage(getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0)))


# ---------------------------------------------------------------------------
# Gemini (SDK google-genai)
# ---------------------------------------------------------------------------
def _nouveau_client_gemini(cle: str):
    from google import genai
    return genai.Client(api_key=cle)


async def _appel_gemini(cle: str, modele: str, systeme: str, messages: List[Dict[str, Any]],
                        params: Dict[str, Any], multimodal: bool) -> ChatResponse:
    await _sdk_pret("google.genai")   # lot 71.2 : import hors de la boucle
    from google.genai import types

    contenus = []
    for m in messages:
        parts = []
        for p in m["parts"]:
            if p["type"] == "text":
                parts.append(types.Part.from_text(text=p["text"]))
            else:
                parts.append(types.Part.from_bytes(data=base64.b64decode(p["data"]), mime_type=p["media_type"]))
        contenus.append(types.Content(role="model" if m["role"] == "assistant" else "user", parts=parts))
    config: Dict[str, Any] = {}
    if systeme:
        config["system_instruction"] = systeme
    if params.get("max_tokens"):
        config["max_output_tokens"] = int(params["max_tokens"])
    if params.get("temperature") is not None:
        config["temperature"] = params["temperature"]
    modalites = params.get("modalities")
    if multimodal and modalites:
        config["response_modalities"] = [str(x).upper() for x in modalites]
    client = _nouveau_client_gemini(cle)
    reponse = await client.aio.models.generate_content(
        model=modele, contents=contenus, config=types.GenerateContentConfig(**config) if config else None)
    textes: List[str] = []
    images: List[Dict[str, str]] = []
    for cand in (getattr(reponse, "candidates", None) or [])[:1]:
        for part in (getattr(getattr(cand, "content", None), "parts", None) or []):
            if getattr(part, "text", None):
                textes.append(part.text)
            donnees = getattr(part, "inline_data", None)
            if donnees is not None and getattr(donnees, "data", None):
                brut = donnees.data
                images.append({"mime_type": getattr(donnees, "mime_type", None) or "image/png",
                               "data": base64.b64encode(brut).decode("ascii") if isinstance(brut, bytes) else brut})
    u = getattr(reponse, "usage_metadata", None)
    return ChatResponse("".join(textes), Usage(getattr(u, "prompt_token_count", 0) or 0,
                                               getattr(u, "candidates_token_count", 0) or 0), images)


# ---------------------------------------------------------------------------
# OpenAI : images, vidéos (Sora), dictée (Whisper)
# ---------------------------------------------------------------------------
class OpenAIImageGeneration:
    """Génération d'images OpenAI (même interface qu'emergentintegrations + text_to_image / generate)."""

    def __init__(self, api_key: Optional[str] = None, custom_headers: Optional[Dict[str, str]] = None) -> None:
        self.api_key = cle_ia("openai")      # le paramètre api_key (Emergent) est ignoré

    def _verifier(self) -> None:
        if not self.api_key:
            raise ChatError("Clé IA absente : définir OPENAI_API_KEY (génération d'images).")

    @staticmethod
    def _qualite(model: str, quality: str) -> str:
        if model == "dall-e-3":
            return {"low": "standard", "medium": "standard", "high": "hd"}.get(quality, quality)
        if model == "gpt-image-1":
            return {"standard": "medium", "hd": "high"}.get(quality, quality)
        return quality

    @staticmethod
    def _octets(reponse: Any) -> List[bytes]:
        import httpx
        sortie: List[bytes] = []
        for img in reponse.data or []:
            if getattr(img, "b64_json", None):
                sortie.append(base64.b64decode(img.b64_json))
            elif getattr(img, "url", None):
                sortie.append(httpx.get(img.url, timeout=120).content)
        return sortie

    async def generate_images(self, prompt: str, model: str = "gpt-image-1", number_of_images: int = 1,
                              quality: str = "low") -> List[bytes]:
        self._verifier()
        await _sdk_pret("openai")   # lot 71.2
        from openai import AsyncOpenAI
        params: Dict[str, Any] = {"model": model, "prompt": prompt, "n": number_of_images}
        if model in ("dall-e-3", "gpt-image-1"):
            params["quality"] = self._qualite(model, quality)
        async with AsyncOpenAI(api_key=self.api_key, timeout=DELAI_SECONDES) as client:
            reponse = await client.images.generate(**params)
        return self._octets(reponse)

    def text_to_image(self, prompt: str, size: str = "1024x1024", model: str = "gpt-image-1",
                      quality: str = "medium") -> Optional[bytes]:
        """Version synchrone (appelée dans un thread) : une image, en octets."""
        self._verifier()
        from openai import OpenAI
        with OpenAI(api_key=self.api_key, timeout=DELAI_SECONDES) as client:
            reponse = client.images.generate(model=model, prompt=prompt, n=1, size=size,
                                             quality=self._qualite(model, quality))
        images = self._octets(reponse)
        return images[0] if images else None

    def generate(self, prompt: str) -> Optional[bytes]:
        return self.text_to_image(prompt=prompt)


class OpenAIVideoGeneration:
    """Vidéos Sora 2 par l'API REST OpenAI (/v1/videos), httpx synchrone (appelée dans un thread).

    Le SDK openai==1.99.9 n'expose pas encore les vidéos : on appelle l'API directement.
    Renvoie les octets MP4, ou None en cas d'échec (même contrat qu'emergentintegrations)."""

    MODELS = ["sora-2", "sora-2-pro"]
    DURATIONS = [4, 8, 12]
    BASE_URL = "https://api.openai.com/v1"

    def __init__(self, api_key: Optional[str] = None, custom_headers: Optional[Dict[str, str]] = None) -> None:
        self.api_key = cle_ia("openai")
        self.base_url = os.environ.get("OPENAI_BASE_URL", self.BASE_URL).rstrip("/")
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
        self.derniere_erreur: Optional[str] = None

    def text_to_video(self, prompt: str, model: str = "sora-2", size: str = "1280x720", duration: int = 4,
                      max_wait_time: int = 600, image_path: Optional[str] = None,
                      mime_type: str = "image/jpeg") -> Optional[bytes]:
        if not self.api_key:
            raise ChatError("Génération vidéo indisponible : définir OPENAI_API_KEY.")
        if model not in self.MODELS:
            raise ValueError(f"Modèle vidéo invalide : {model} (attendu : {', '.join(self.MODELS)})")
        if int(duration) not in self.DURATIONS:
            raise ValueError(f"Durée invalide : {duration} s (attendu : 4, 8 ou 12)")
        import httpx
        try:
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=20.0), headers=self.headers) as http:
                donnees = {"model": model, "prompt": prompt, "size": size, "seconds": str(int(duration))}
                if image_path:
                    with open(image_path, "rb") as f:
                        r = http.post(f"{self.base_url}/videos", data=donnees,
                                      files={"input_reference": (pathlib.Path(image_path).name, f, mime_type)})
                else:
                    r = http.post(f"{self.base_url}/videos", json=donnees)
                if r.status_code >= 400:
                    self.derniere_erreur = f"OpenAI {r.status_code} : {r.text[:300]}"
                    logger.warning("[ia] création vidéo refusée : %s", self.derniere_erreur)
                    return None
                ident = r.json().get("id")
                if not ident:
                    self.derniere_erreur = "réponse sans identifiant de vidéo"
                    return None
                debut, attente = time.time(), 10.0
                while time.time() - debut < max_wait_time:
                    etat = http.get(f"{self.base_url}/videos/{ident}").json()
                    statut = str(etat.get("status") or "").lower()
                    if statut == "completed":
                        contenu = http.get(f"{self.base_url}/videos/{ident}/content", follow_redirects=True)
                        if contenu.status_code != 200 or len(contenu.content) < 1000:
                            self.derniere_erreur = f"téléchargement impossible ({contenu.status_code})"
                            return None
                        return contenu.content
                    if statut in ("failed", "cancelled", "error"):
                        self.derniere_erreur = str(etat.get("error") or statut)[:300]
                        logger.warning("[ia] vidéo en échec : %s", self.derniere_erreur)
                        return None
                    time.sleep(attente)
                    attente = min(attente * 1.2, 30.0)
                self.derniere_erreur = f"délai dépassé ({max_wait_time} s)"
                return None
        except httpx.HTTPError as exc:
            self.derniere_erreur = str(exc)[:300]
            logger.warning("[ia] génération vidéo : %s", exc)
            return None

    def save_video(self, video_bytes: bytes, output_path: Optional[str] = None) -> str:
        chemin = output_path or f"openai_video_{int(time.time())}.mp4"
        pathlib.Path(chemin).write_bytes(video_bytes)
        return chemin


class OpenAISpeechToText:
    """Dictée (Whisper) par le SDK officiel openai ; même interface qu'emergentintegrations."""

    MODELS = ["whisper-1"]
    RESPONSE_FORMATS = {"whisper-1": ["json", "text", "srt", "verbose_json", "vtt"]}
    MAX_FILE_SIZE = 25 * 1024 * 1024

    def __init__(self, api_key: Optional[str] = None, custom_headers: Optional[Dict[str, str]] = None) -> None:
        self.api_key = cle_ia("openai")

    async def transcribe(self, file, model: str = "whisper-1", response_format: str = "json",
                         prompt: Optional[str] = None, language: Optional[str] = None,
                         temperature: Optional[float] = None, timestamp_granularities: Optional[list] = None):
        if not self.api_key:
            raise ChatError("Dictée indisponible : définir OPENAI_API_KEY.")
        if model not in self.MODELS:
            raise ValueError(f"Modèle invalide : {model}")
        if response_format not in self.RESPONSE_FORMATS[model]:
            raise ValueError(f"Format de réponse invalide : {response_format}")
        if isinstance(file, (str, pathlib.Path)):
            file = open(file, "rb")  # noqa: SIM115 — fermé par le SDK après envoi
        params: Dict[str, Any] = {"model": model, "file": file, "response_format": response_format}
        if prompt:
            params["prompt"] = prompt
        if language:
            params["language"] = language
        if temperature is not None:
            params["temperature"] = temperature
        if timestamp_granularities:
            params["timestamp_granularities"] = timestamp_granularities
        await _sdk_pret("openai")   # lot 71.2 : import hors de la boucle (transcription pendant les appels)
        from openai import AsyncOpenAI
        async with AsyncOpenAI(api_key=self.api_key, timeout=DELAI_SECONDES) as client:
            reponse = await client.audio.transcriptions.create(**params)
        if isinstance(reponse, str):        # formats text / srt / vtt
            return _Texte(reponse)
        return reponse


class _Texte:
    def __init__(self, text: str) -> None:
        self.text = text
