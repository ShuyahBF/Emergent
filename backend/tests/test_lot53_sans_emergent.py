"""Lot 53 — Indépendance d'Emergent : client IA local (SDK officiel anthropic), équivalents
OpenAI (images, vidéos, dictée), paiement Stripe officiel, fichiers dans Cloudflare R2 avec la
convention de clés de l'outil « Migration vers Render », et parcours OCR complet d'une liste
de pointage.

Aucun réseau, aucune clé réelle : le SDK anthropic est le VRAI SDK, branché sur un transport
HTTP simulé (on vérifie la requête exacte envoyée à l'API Messages) ; R2 est un bucket en
mémoire qui répond comme boto3 ; MongoDB est simulé (mongomock-motor).

Lancer : cd backend && python -m pytest tests/test_lot53_sans_emergent.py -q
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import os
import re
import subprocess
import sys
import time
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot53")

httpx2 = pytest.importorskip("httpx2")
anthropic = pytest.importorskip("anthropic")

import ia_client  # noqa: E402
import paiement_stripe  # noqa: E402
import storage  # noqa: E402

pytest.importorskip("mongomock_motor")
# Fixture `env` (application OCR sur Pièces + stockage + base simulés) des tests OCR existants
from test_ocr_pieces import env  # noqa: E402,F401


# ===========================================================================
# Outils : API Anthropic simulée (vrai SDK, transport HTTP simulé)
# ===========================================================================
def _png(largeur=40, hauteur=30) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (largeur, hauteur), "white").save(b, format="PNG")
    return b.getvalue()


def _jpeg(largeur=1200, hauteur=1600) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (largeur, hauteur), "white").save(b, format="JPEG")
    return b.getvalue()


def _image(fmt: str) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(b, format=fmt)
    return b.getvalue()


def _reponse_messages(texte: str, model: str = "claude-sonnet-5", tin: int = 1200, tout: int = 300,
                      stop: str = "end_turn") -> dict:
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "text", "text": texte}], "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": tin, "output_tokens": tout}}


class FausseApiAnthropic:
    """Retient chaque requête POST /v1/messages ; la réponse est calculée par `repondre(corps)`."""

    def __init__(self, repondre=None, statut: int = 200):
        self.requetes: list = []
        self.entetes: list = []
        self.repondre = repondre or (lambda corps: _reponse_messages("Bonjour"))
        self.statut = statut

    def __call__(self, requete):
        corps = json.loads(requete.content.decode("utf-8"))
        self.requetes.append(corps)
        self.entetes.append(dict(requete.headers))
        if self.statut != 200:
            return httpx2.Response(self.statut, json={"type": "error", "error": {
                "type": "api_error", "message": "panne simulée"}})
        return httpx2.Response(200, json=self.repondre(corps))


@pytest.fixture()
def api_anthropic(monkeypatch):
    """Branche le vrai AsyncAnthropic sur un transport simulé ; clé de test."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-lot53")
    api = FausseApiAnthropic()

    def client(cle):
        return anthropic.AsyncAnthropic(api_key=cle, max_retries=0,
                                        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api)))

    monkeypatch.setattr(ia_client, "_nouveau_client_anthropic", client)
    return api


# ===========================================================================
# 1. Client IA : texte, image, historique, erreurs
# ===========================================================================
def test_texte_format_exact_de_la_requete(api_anthropic):
    chat = ia_client.LlmChat(api_key="sk-emergent-ignoree", session_id="s1",
                             system_message="Tu réponds en français.") \
        .with_model("anthropic", "claude-haiku-4-5-20251001")
    texte = asyncio.run(chat.send_message(ia_client.UserMessage(text="Bonjour ?")))
    assert texte == "Bonjour"
    corps = api_anthropic.requetes[0]
    assert corps == {"model": "claude-haiku-4-5-20251001", "max_tokens": ia_client.MAX_TOKENS_DEFAUT,
                     "system": "Tu réponds en français.",
                     "messages": [{"role": "user", "content": [{"type": "text", "text": "Bonjour ?"}]}]}
    # La clé envoyée est celle d'ANTHROPIC_API_KEY, jamais la clé Emergent passée par l'appelant
    assert api_anthropic.entetes[0]["x-api-key"] == "sk-ant-test-lot53"


def test_image_base64_et_media_type(api_anthropic):
    for fmt, attendu in (("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp"), ("GIF", "image/gif")):
        b64 = base64.b64encode(_image(fmt)).decode("ascii")
        chat = ia_client.LlmChat(api_key="x", session_id="s", system_message="Vision") \
            .with_model("anthropic", "claude-sonnet-4-6").with_params(max_tokens=1024)
        asyncio.run(chat.send_message(ia_client.UserMessage(
            text="Décris l'image.", file_contents=[ia_client.ImageContent(image_base64=b64)])))
        corps = api_anthropic.requetes[-1]
        assert corps["model"] == "claude-sonnet-4-6" and corps["max_tokens"] == 1024
        contenu = corps["messages"][0]["content"]
        # Image d'abord (conseillé pour la vision), puis la consigne
        assert contenu[0] == {"type": "image", "source": {"type": "base64", "media_type": attendu, "data": b64}}
        assert contenu[1] == {"type": "text", "text": "Décris l'image."}


def test_image_prefixe_data_url_et_pdf_en_document(api_anthropic):
    b64 = base64.b64encode(_image("PNG")).decode("ascii")
    pdf = base64.b64encode(b"%PDF-1.4\n%test\n").decode("ascii")
    chat = ia_client.LlmChat(api_key=None, session_id="s", system_message="")
    asyncio.run(chat.send_message(ia_client.UserMessage(text="Lis.", file_contents=[
        ia_client.ImageContent(f"data:image/png;base64,{b64[:20]}\n{b64[20:]}"),
        ia_client.ImageContent(pdf)])))
    corps = api_anthropic.requetes[-1]
    assert "system" not in corps                       # consigne système vide : champ absent
    contenu = corps["messages"][0]["content"]
    assert contenu[0]["source"] == {"type": "base64", "media_type": "image/png", "data": b64}
    assert contenu[1] == {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                         "data": pdf}}


def test_historique_conserve_par_instance(api_anthropic):
    api_anthropic.repondre = lambda corps: _reponse_messages(f"Réponse {len(corps['messages'])}")
    chat = ia_client.LlmChat(api_key="", session_id="conv", system_message="S") \
        .with_model("anthropic", "claude-haiku-4-5-20251001")
    assert asyncio.run(chat.send_message(ia_client.UserMessage(text="Q1"))) == "Réponse 1"
    assert asyncio.run(chat.send_message(ia_client.UserMessage(text="Q2"))) == "Réponse 3"
    assert api_anthropic.requetes[1]["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Q1"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Réponse 1"}]},
        {"role": "user", "content": [{"type": "text", "text": "Q2"}]},
    ]
    # Une autre instance repart d'une conversation vide
    autre = ia_client.LlmChat(api_key="", session_id="conv", system_message="S")
    asyncio.run(autre.send_message(ia_client.UserMessage(text="Q")))
    assert len(api_anthropic.requetes[2]["messages"]) == 1


def test_usage_reel_send_message_with_tools(api_anthropic):
    api_anthropic.repondre = lambda corps: _reponse_messages('{"ok": true}', tin=4321, tout=123)
    chat = ia_client.LlmChat(api_key="", session_id="s", system_message="S")
    rep = asyncio.run(chat.send_message_with_tools(ia_client.UserMessage(text="x")))
    assert (rep.content, rep.usage.input_tokens, rep.usage.output_tokens) == ('{"ok": true}', 4321, 123)
    # Compatibilité 0.1.0 (réponse brute au format LiteLLM)
    brut = asyncio.run(chat._execute_completion([{"role": "user", "parts": [{"type": "text", "text": "y"}]}]))
    assert brut.choices[0].message.content == '{"ok": true}' and brut.usage.prompt_tokens == 4321


def test_erreurs_cle_absente_et_api_en_panne(api_anthropic, monkeypatch):
    chat = ia_client.LlmChat(api_key="sk-emergent-xxx", session_id="s", system_message="S")
    api_anthropic.statut = 500
    with pytest.raises(ia_client.ChatError, match="Échec de l'appel IA"):
        asyncio.run(chat.send_message(ia_client.UserMessage(text="x")))
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert ia_client.cle_ia() == ""
    with pytest.raises(ia_client.ChatError, match="ANTHROPIC_API_KEY"):
        asyncio.run(ia_client.LlmChat("k", "s", "S").send_message(ia_client.UserMessage(text="x")))


def test_grand_max_tokens_en_flux(api_anthropic):
    """Au-delà de 16 000 tokens de sortie, la réponse est reçue en flux (SSE) : même texte, même usage."""
    def repondre_flux(requete):
        corps = json.loads(requete.content.decode("utf-8"))
        api_anthropic.requetes.append(corps)
        evenements = [
            ("message_start", {"type": "message_start", "message": {**_reponse_messages(""), "content": [],
                                                                    "usage": {"input_tokens": 10, "output_tokens": 1}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                     "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "text_delta", "text": "Formulaire "}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "text_delta", "text": "lu"}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                               "usage": {"output_tokens": 42}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        texte = "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in evenements)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=texte.encode())

    def client(cle):
        return anthropic.AsyncAnthropic(api_key=cle, max_retries=0,
                                        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(repondre_flux)))

    ia_client._nouveau_client_anthropic, ancien = client, ia_client._nouveau_client_anthropic
    try:
        chat = ia_client.LlmChat("", "s", "S").with_params(max_tokens=20000)
        rep = asyncio.run(chat.send_message_with_tools(ia_client.UserMessage(text="x")))
    finally:
        ia_client._nouveau_client_anthropic = ancien
    assert rep.content == "Formulaire lu" and rep.usage.output_tokens == 42
    assert api_anthropic.requetes[-1]["stream"] is True and api_anthropic.requetes[-1]["max_tokens"] == 20000


def test_openai_et_gemini_routes_vers_leur_sdk(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "gem-test")
    vus = {}

    class FauxOpenAI:
        def __init__(self):
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

        async def create(self, **kw):
            vus["openai"] = kw
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="Hello"))],
                                         usage=types.SimpleNamespace(prompt_tokens=5, completion_tokens=2))

        async def close(self):
            pass

    monkeypatch.setattr(ia_client, "_nouveau_client_openai", lambda cle: (vus.__setitem__("cle_openai", cle), FauxOpenAI())[1])
    chat = ia_client.LlmChat("sk-emergent", "s", "Translate").with_model("openai", "gpt-4o-mini")
    assert asyncio.run(chat.send_message(ia_client.UserMessage(text="Bonjour"))) == "Hello"
    assert vus["cle_openai"] == "sk-openai-test" and vus["openai"]["model"] == "gpt-4o-mini"
    assert vus["openai"]["messages"][0] == {"role": "system", "content": "Translate"}

    from google.genai import types as gt
    image = base64.b64encode(_png()).decode()

    class FauxGemini:
        def __init__(self):
            self.aio = types.SimpleNamespace(models=types.SimpleNamespace(generate_content=self.generate))

        async def generate(self, model, contents, config=None):
            vus["gemini"] = (model, contents, config)
            part_txt = types.SimpleNamespace(text="Voici", inline_data=None)
            part_img = types.SimpleNamespace(text=None, inline_data=types.SimpleNamespace(data=_png(), mime_type="image/png"))
            return types.SimpleNamespace(
                candidates=[types.SimpleNamespace(content=types.SimpleNamespace(parts=[part_txt, part_img]))],
                usage_metadata=types.SimpleNamespace(prompt_token_count=7, candidates_token_count=3))

    monkeypatch.setattr(ia_client, "_nouveau_client_gemini", lambda cle: FauxGemini())
    chat = ia_client.LlmChat("k", "s", "Images").with_model("gemini", "gemini-3.1-flash-image-preview") \
        .with_params(modalities=["image", "text"])
    texte, images = asyncio.run(chat.send_message_multimodal_response(
        ia_client.UserMessage(text="Un logo", file_contents=[ia_client.ImageContent(image)])))
    assert texte == "Voici" and images[0]["mime_type"] == "image/png"
    assert base64.b64decode(images[0]["data"]) == _png()
    modele, contenus, config = vus["gemini"]
    assert modele == "gemini-3.1-flash-image-preview" and config.response_modalities == ["IMAGE", "TEXT"]
    assert isinstance(contenus[0], gt.Content) and contenus[0].parts[0].inline_data.mime_type == "image/png"


# ===========================================================================
# 2. Équivalents OpenAI : images, vidéos (REST), dictée
# ===========================================================================
def test_generation_images_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    import openai
    vus = {}

    class Faux:
        def __init__(self, api_key=None, timeout=None):
            vus["cle"] = api_key
            self.images = types.SimpleNamespace(generate=self.generate)

        async def generate(self, **kw):
            vus["kw"] = kw
            return types.SimpleNamespace(data=[types.SimpleNamespace(b64_json=base64.b64encode(b"IMG").decode(), url=None)])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(openai, "AsyncOpenAI", Faux)
    images = asyncio.run(ia_client.OpenAIImageGeneration(api_key="sk-emergent").generate_images(
        "Un chat", model="gpt-image-1", quality="standard"))
    assert images == [b"IMG"] and vus["cle"] == "sk-openai-test"
    assert vus["kw"] == {"model": "gpt-image-1", "prompt": "Un chat", "n": 1, "quality": "medium"}


def test_generation_video_rest_et_indisponible(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ia_client.ChatError, match="Génération vidéo indisponible"):
        ia_client.OpenAIVideoGeneration(api_key="sk-emergent").text_to_video("x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    import httpx
    appels = []
    etats = iter(["in_progress", "completed"])

    def repondre(req):
        appels.append((req.method, str(req.url), req.headers.get("authorization")))
        if req.method == "POST":
            assert json.loads(req.content) == {"model": "sora-2", "prompt": "Un lever de soleil",
                                               "size": "1280x720", "seconds": "4"}
            return httpx.Response(200, json={"id": "video_1", "status": "queued"})
        if req.url.path.endswith("/content"):
            return httpx.Response(200, content=b"\x00" * 5000, headers={"content-type": "video/mp4"})
        return httpx.Response(200, json={"id": "video_1", "status": next(etats)})

    vrai_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: vrai_client(transport=httpx.MockTransport(repondre), **kw))
    monkeypatch.setattr(ia_client.time, "sleep", lambda s: None)
    video = ia_client.OpenAIVideoGeneration().text_to_video("Un lever de soleil", model="sora-2", duration=4)
    assert video == b"\x00" * 5000
    assert appels[0] == ("POST", "https://api.openai.com/v1/videos", "Bearer sk-openai-test")
    assert appels[-1][1] == "https://api.openai.com/v1/videos/video_1/content"


def test_dictee_whisper(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    import openai
    vus = {}

    class Faux:
        def __init__(self, api_key=None, timeout=None):
            self.audio = types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=self.create))

        async def create(self, **kw):
            vus.update(kw)
            return types.SimpleNamespace(text="bonjour l'équipe")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(openai, "AsyncOpenAI", Faux)
    audio = tmp_path / "voix.webm"
    audio.write_bytes(b"son")
    with open(audio, "rb") as fh:
        rep = asyncio.run(ia_client.OpenAISpeechToText(api_key="x").transcribe(
            file=fh, model="whisper-1", response_format="json", language="fr"))
    assert rep.text == "bonjour l'équipe" and vus["language"] == "fr" and vus["model"] == "whisper-1"


# ===========================================================================
# 3. Paiement Stripe (bibliothèque officielle)
# ===========================================================================
class FauxSessions:
    def __init__(self):
        self.crees = []

    def create(self, params):
        self.crees.append(params)
        return types.SimpleNamespace(id="cs_test_1", url="https://checkout.stripe.com/c/pay/cs_test_1")

    def retrieve(self, session_id):
        import stripe
        return stripe.checkout.Session.construct_from({
            "id": session_id, "status": "complete", "payment_status": "paid", "amount_total": 1500,
            "currency": "eur", "metadata": {"kind": "formation", "formation_id": "F1"}}, "sk_test")


def _stripe(monkeypatch, **kw):
    sessions = FauxSessions()
    client = paiement_stripe.StripeCheckout(api_key="sk_test_123", **kw)
    monkeypatch.setattr(client, "_client", lambda: types.SimpleNamespace(
        v1=types.SimpleNamespace(checkout=types.SimpleNamespace(sessions=sessions))))
    return client, sessions


def test_stripe_session_statut_et_devise_sans_decimales(monkeypatch):
    client, sessions = _stripe(monkeypatch, webhook_url="https://sawalismartsystems.com/api/webhook/stripe")
    req = paiement_stripe.CheckoutSessionRequest(amount=15.0, currency="eur", success_url="https://s/ok",
                                                 cancel_url="https://s/ko", metadata={"kind": "formation"})
    session = asyncio.run(client.create_checkout_session(req))
    assert (session.session_id, session.url) == ("cs_test_1", "https://checkout.stripe.com/c/pay/cs_test_1")
    p = sessions.crees[0]
    assert p["line_items"][0]["price_data"]["unit_amount"] == 1500 and p["mode"] == "payment"
    assert p["metadata"] == {"kind": "formation", "webhook_url": "https://sawalismartsystems.com/api/webhook/stripe"}
    assert p["payment_method_types"] == ["card"]
    # XOF : devise sans décimales, montant envoyé tel quel
    asyncio.run(client.create_checkout_session(paiement_stripe.CheckoutSessionRequest(
        amount=25000.0, currency="xof", success_url="https://s/ok", cancel_url="https://s/ko")))
    assert sessions.crees[1]["line_items"][0]["price_data"]["unit_amount"] == 25000
    statut = asyncio.run(client.get_checkout_status("cs_test_1"))
    assert (statut.status, statut.payment_status, statut.amount_total, statut.currency) == ("complete", "paid", 1500, "eur")
    assert statut.metadata == {"kind": "formation", "formation_id": "F1"}
    with pytest.raises(ValueError):
        paiement_stripe.CheckoutSessionRequest(currency="eur")   # ni montant ni prix


def test_stripe_webhook_signature(monkeypatch):
    secret = "whsec_test_lot53"
    corps = json.dumps({"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {
        "id": "cs_test_1", "payment_status": "paid", "metadata": {"order_id": "O1"}}}}).encode()
    t = int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + corps, hashlib.sha256).hexdigest()
    client = paiement_stripe.StripeCheckout(api_key="sk_test", webhook_secret=secret)
    ev = asyncio.run(client.handle_webhook(corps, f"t={t},v1={sig}"))
    assert (ev.event_type, ev.event_id, ev.session_id, ev.payment_status, ev.metadata) == (
        "checkout.session.completed", "evt_1", "cs_test_1", "paid", {"order_id": "O1"})
    with pytest.raises(paiement_stripe.CheckoutError):
        asyncio.run(client.handle_webhook(corps, f"t={t},v1={'0' * 64}"))
    # Sans secret : JSON lu tel quel (même logique qu'avant)
    ev = asyncio.run(paiement_stripe.StripeCheckout(api_key="sk_test").handle_webhook(corps))
    assert ev.payment_status == "paid"


# ===========================================================================
# 4. Stockage R2 : convention de la migration, repli Emergent paresseux
# ===========================================================================
class FauxR2:
    """Bucket R2 en mémoire : méthodes boto3 utilisées par la migration ET par storage.py."""

    def __init__(self):
        self.objets, self.types = {}, {}

    def put_object(self, Bucket, Key, Body, ContentType=None, **_):  # noqa: N803
        self.objets[Key] = Body if isinstance(Body, bytes) else Body.read()
        self.types[Key] = ContentType

    def upload_fileobj(self, Fileobj, Bucket, Key, ExtraArgs=None, Callback=None):  # noqa: N803
        self.objets[Key] = Fileobj.read()
        self.types[Key] = (ExtraArgs or {}).get("ContentType")

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None, Callback=None):  # noqa: N803
        self.objets[Key] = Path(Filename).read_bytes()

    def head_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objets:
            raise self._absent()
        return {}

    def head_bucket(self, Bucket):  # noqa: N803
        return {}

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objets:
            raise self._absent()
        return {"Body": io.BytesIO(self.objets[Key]), "ContentType": self.types.get(Key) or "application/octet-stream"}

    @staticmethod
    def _absent():
        from botocore.exceptions import ClientError
        return ClientError({"Error": {"Code": "NoSuchKey", "Message": "absent"},
                            "ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject")


@pytest.fixture()
def r2(monkeypatch, tmp_path):
    seau = FauxR2()
    for nom in list(os.environ):
        if nom.startswith(("R2_FICHIERS_", "R2_SAUVEGARDES_", "R2_STOCKS_")):
            monkeypatch.delenv(nom)
    monkeypatch.setenv("R2_FICHIERS_BUCKET", "sawali-fichiers")
    monkeypatch.setenv("R2_FICHIERS_PREFIXE", "migration-20261003-190000")
    # Identifiants : repli sur ceux des sauvegardes (lot 49)
    monkeypatch.setenv("R2_SAUVEGARDES_ACCOUNT_ID", "compte")
    monkeypatch.setenv("R2_SAUVEGARDES_ACCESS_KEY_ID", "cle")
    monkeypatch.setenv("R2_SAUVEGARDES_SECRET_ACCESS_KEY", "secret")
    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
    monkeypatch.setattr(storage, "EMERGENT_KEY", None)
    monkeypatch.setattr(storage, "_storage_key", None)
    monkeypatch.setattr(storage, "_r2_client", None)
    configs = []
    monkeypatch.setattr(storage, "_nouveau_client_r2", lambda cfg: (configs.append(cfg), seau)[1])
    storage._missing.clear()
    seau.configs = configs
    return seau


def test_ecriture_et_lecture_r2(r2):
    assert storage.storage_available()
    chemin = storage.upload_bytes("chat/abc.png", b"PNG", "image/png")
    assert chemin == "sawali/chat/abc.png"                               # même valeur en base qu'avant
    assert r2.objets["migration-20261003-190000/objets/sawali/chat/abc.png"] == b"PNG"
    assert storage.fetch_bytes(chemin) == (b"PNG", "image/png")
    assert storage.fetch_bytes("chat/abc.png")[0] == b"PNG"             # forme sans préfixe
    assert r2.configs[0]["endpoint"] == "https://compte.r2.cloudflarestorage.com"
    with pytest.raises(FileNotFoundError):
        storage.fetch_bytes("sawali/absent.png")


def test_object_storage_save_and_log_et_lecture(r2):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    import object_storage
    base = mongomock_motor.AsyncMongoMockClient()["lot53_os"]
    rec = asyncio.run(object_storage.save_and_log(base, data=b"%PDF", kind="ocr_pieces", tenant_id="pharma_a",
                                                  ext="pdf", content_type="application/pdf"))
    assert rec["path"].startswith("sawali/pharma_a/ocr_pieces/") and rec["url"] == f"/api/files/{rec['path']}"
    assert r2.objets[f"migration-20261003-190000/objets/{rec['path']}"] == b"%PDF"
    assert asyncio.run(object_storage.get_object(rec["path"])) == (b"%PDF", "application/pdf")
    assert object_storage.is_enabled() and asyncio.run(object_storage.init_storage())


def test_sans_r2_ni_emergent_rien_ne_bloque(monkeypatch, tmp_path):
    for nom in list(os.environ):
        if nom.startswith(("R2_FICHIERS_", "R2_SAUVEGARDES_", "R2_STOCKS_")) or nom == "EMERGENT_LLM_KEY":
            monkeypatch.delenv(nom)
    monkeypatch.setattr(storage, "EMERGENT_KEY", None)
    monkeypatch.setattr(storage, "_nouveau_client_r2", lambda cfg: pytest.fail("aucun appel R2 attendu"))
    monkeypatch.setattr(storage.httpx, "post", lambda *a, **k: pytest.fail("aucun appel Emergent attendu"))
    monkeypatch.setattr(storage.httpx, "get", lambda *a, **k: pytest.fail("aucun appel Emergent attendu"))
    assert not storage.storage_available()
    local, chemin, erreur = storage.save_upload_and_cache(upload_dir=tmp_path, filename="a.txt", data=b"A")
    assert local.read_bytes() == b"A" and chemin is None and erreur is None
    assert storage.rehydrate_from_storage(local_path=tmp_path / "b.txt", remote_path="sawali/b.txt") is False
    with pytest.raises(RuntimeError):
        storage.fetch_bytes("sawali/b.txt")


def test_repli_emergent_paresseux_recopie_dans_r2(r2, monkeypatch):
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-test")
    appels = []

    def faux_post(url, json=None, timeout=None):
        appels.append(("init", url))
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"storage_key": "sk-stockage"})

    def faux_get(url, headers=None, timeout=None):
        appels.append(("get", url, headers.get("X-Storage-Key")))
        return types.SimpleNamespace(status_code=200, content=b"ANCIEN", headers={"Content-Type": "image/jpeg"},
                                     raise_for_status=lambda: None)

    monkeypatch.setattr(storage.httpx, "post", faux_post)
    monkeypatch.setattr(storage.httpx, "get", faux_get)
    monkeypatch.setattr(storage, "_storage_key_attempts", 0)
    assert storage.fetch_bytes("sawali/t1/avatars/x.jpg") == (b"ANCIEN", "image/jpeg")
    assert appels[1] == ("get", f"{storage.STORAGE_URL}/objects/sawali/t1/avatars/x.jpg", "sk-stockage")
    # Recopié avec la clé de la migration : la lecture suivante vient de R2, sans Emergent
    assert r2.objets["migration-20261003-190000/objets/sawali/t1/avatars/x.jpg"] == b"ANCIEN"
    monkeypatch.setattr(storage.httpx, "get", lambda *a, **k: pytest.fail("Emergent ne doit plus être appelé"))
    assert storage.fetch_bytes("sawali/t1/avatars/x.jpg")[0] == b"ANCIEN"


def test_convention_identique_a_la_migration_render(r2, monkeypatch, tmp_path):
    """Preuve de bout en bout : l'outil « Migration vers Render » (code réel, lots 44-47) copie les
    fichiers d'Emergent dans R2 ; le nouveau stockage les relit ensuite SANS retraitement."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    import routes.migration_render as mr
    base = mongomock_motor.AsyncMongoMockClient()["lot53_migration"]
    monkeypatch.setattr(mr, "db", base)
    monkeypatch.setattr(mr, "ATTENTES_ESSAIS", (0, 0))
    uploads, snapshots = tmp_path / "uploads", tmp_path / "snapshots"
    (uploads / "ai" / "pharma_a").mkdir(parents=True)
    (uploads / "ai" / "pharma_a" / "img.png").write_bytes(b"IMAGE-DISQUE")
    (uploads / "doc-1.pdf").write_bytes(b"DOC-DISQUE")
    monkeypatch.setattr(mr, "DOSSIER_UPLOADS", uploads)
    monkeypatch.setattr(mr, "DOSSIER_SNAPSHOTS", snapshots)
    emergent = {"sawali/pharma_a/ocr_pieces/2026-10/a1.pdf": b"SCAN", "sawali/files/u1.pdf": b"FICHIER",
                "sawali/chat/voix.ogg": b"VOIX", "files/sans-prefixe.png": b"SANS"}

    @contextmanager
    def flux(chemin):
        yield iter([emergent[chemin]]), "application/octet-stream", len(emergent[chemin])

    monkeypatch.setattr(mr, "_flux_objet_emergent", flux)

    async def migrer():
        await base.stored_objects.insert_many([{"storage_path": "sawali/pharma_a/ocr_pieces/2026-10/a1.pdf"},
                                               {"storage_path": "files/sans-prefixe.png"}])
        await base.files.insert_one({"id": "u1", "storage_path": "sawali/files/u1.pdf"})
        await base.internal_chat_messages.insert_one({"id": "m1", "storage_path": "sawali/chat/voix.ogg"})
        await base.migration_jobs.insert_one({"id": "J", "statut": "EN_COURS", "journal": []})
        cible = mr.Cible(r2_account_id="compte", r2_access_key_id="cle1", r2_secret_access_key="secret",
                         r2_bucket="sawali-fichiers", copier_base=True, copier_fichiers=True, sauver_secrets=False,
                         copier_medias=True)
        await mr._executer("J", cible, types.SimpleNamespace(), r2, "migration-20261003-190000")
        return await base.migration_jobs.find_one({"id": "J"}, {"_id": 0})

    async def copier_base_sans_cible(*a, **k):
        # La copie MongoDB n'est pas l'objet du test : on relève seulement les références de fichiers
        references = a[5]
        async for doc in base.internal_chat_messages.find({}, {"_id": 0}):
            references[("stockage", doc["storage_path"])] = "internal_chat_messages"
        return 0

    monkeypatch.setattr(mr, "_copier_base", copier_base_sans_cible)
    job = asyncio.run(migrer())
    assert job["statut"] == "TERMINEE", job.get("journal")
    # Lecture par le NOUVEAU stockage, avec les chemins tels qu'ils sont en base
    for chemin, contenu in emergent.items():
        assert storage.fetch_bytes(chemin)[0] == contenu, chemin
    assert storage.fetch_bytes("sawali/files/sans-prefixe.png")[0] == b"SANS"   # autre forme du même chemin
    # Fichiers du disque d'Emergent (uploads/) : restaurés à la demande sur le disque de Render
    import chemins
    monkeypatch.setattr(chemins, "UPLOAD_DIR", tmp_path / "render_uploads")
    monkeypatch.setattr(chemins, "SNAPSHOTS_DIR", tmp_path / "render_snapshots")
    cible_img = tmp_path / "render_uploads" / "ai" / "pharma_a" / "img.png"
    assert storage.restaurer_fichier_local(cible_img) and cible_img.read_bytes() == b"IMAGE-DISQUE"
    cible_doc = tmp_path / "render_uploads" / "doc-1.pdf"
    assert storage.rehydrate_from_storage(local_path=cible_doc, remote_path="files/doc-1.pdf")
    assert cible_doc.read_bytes() == b"DOC-DISQUE"


# ===========================================================================
# 5. OCR des listes de pointage : parcours complet avec le SDK anthropic simulé
# ===========================================================================
def _lecture_page(n_page: int) -> dict:
    from test_ocr_pointage import _lu, _page
    pages = {
        1: _page([_lu(1, "ARGESUN INJ 120MG [B/1]", mag=5, sv=3, per="06/28"),
                  _lu(3, "ACETYL SALICLYLATE [B/1]", sv=40)]),
        2: _page([_lu(70, "BANDELETTE CODEFREE [B/50]"), _lu(77, "BAVETTE [B/50]", mag=2)], titre=None, pied=4),
    }
    return {k: v for k, v in pages[n_page].items() if k != "page"}


def _repondre_ocr(corps: dict) -> dict:
    """Répond comme Claude : la page est reconnue au texte « … p.N » envoyé avec l'image."""
    texte = next(b["text"] for b in corps["messages"][0]["content"] if b["type"] == "text")
    n_page = int(re.search(r"p\.(\d+)", texte).group(1))
    # Réponse entourée d'un bloc ```json``` : tolérée par parse_json
    return _reponse_messages("```json\n" + json.dumps(_lecture_page(n_page), ensure_ascii=False) + "\n```",
                             model=corps["model"], tin=1500, tout=400)


def _verifier_requete_ocr(corps: dict) -> None:
    import ocr_core
    import ocr_pointage as op
    assert corps["model"] == ocr_core.default_model_id()
    assert corps["max_tokens"] == 8192 and corps["system"] == op.SYSTEM_PROMPT
    contenu = corps["messages"][0]["content"]
    assert [b["type"] for b in contenu] == ["image", "text"]           # UNE image par requête
    src = contenu[0]["source"]
    assert src["type"] == "base64" and src["media_type"] == "image/jpeg"
    assert base64.b64decode(src["data"])[:3] == b"\xff\xd8\xff"        # vrai JPEG, type cohérent


def test_ocr_pointage_bout_en_bout_fonction(api_anthropic):
    import ocr_pointage as op
    from test_ocr_pointage import _inventaire
    api_anthropic.repondre = _repondre_ocr
    scan = op.photos_en_pdf([_jpeg(), _jpeg()])                        # deux photos de téléphone
    res = asyncio.run(op.traiter_liste_pointage(scan, "application/pdf", "Liste_pointage_2_photos.pdf",
                                                json.dumps(_inventaire()).encode(),
                                                "InventaireSélectionné_PPH_INV067.json", "claude-sonnet-5"))
    assert len(api_anthropic.requetes) == 2
    for corps in api_anthropic.requetes:
        _verifier_requete_ocr(corps)
    assert res["error"] is None and res["pages_analyzed"] == 2
    assert (res["input_tokens"], res["output_tokens"]) == (3000, 800)  # usage réel cumulé
    assert res["extracted_fields"]["lignes_completees"] == 3 and res["extracted_fields"]["inventaire"] == "INV067"
    assert res["summary"].startswith("Liste de pointage INV067 : 4 lignes lues")
    assert "JSON réimportable dans Aizenta" in res["summary"] and res["compte_rendu"]
    complet = json.loads(res["json_complete"].decode("latin-1") if isinstance(res["json_complete"], bytes)
                         else res["json_complete"])
    lignes = {l["Chrono"]: l for l in complet[op.CLE_TABLE]}
    assert (lignes[1]["IMagasin"], lignes[1]["ISalle"], lignes[1]["Peremption1"]) == (5, 3, "20280601")
    assert lignes[3]["ISalle"] == 40 and lignes[77]["IMagasin"] == 2


def test_ocr_pointage_bout_en_bout_api_photos(api_anthropic, env):
    """Dépôt de 2 photos + JSON sur /api/ocr-pieces (route réelle), analyse en tâche de fond par
    ocr_core → ia_client → SDK anthropic ; JSON complété téléchargeable, e-mail de fin en français."""
    from test_ocr_pieces import _h, _wait_analysed
    from test_ocr_pointage import _inventaire
    api_anthropic.repondre = _repondre_ocr
    files = [("photos", ("IMG_0001.jpg", _jpeg(), "image/jpeg")), ("photos", ("IMG_0002.jpg", _jpeg(), "image/jpeg")),
             ("inventaire_json", ("InventaireSélectionné_PPH_INV067.json", json.dumps(_inventaire()).encode(),
                                  "application/json"))]
    r = env.client.post("/api/ocr-pieces", headers=_h("pharma_a"), files=files, data={"kind": "liste_pointage"})
    assert r.status_code == 200, r.text
    piece = r.json()
    assert piece["original_filename"] == "Liste_pointage_2_photos.pdf"
    done = _wait_analysed(env, "pharma_a", piece["id"])
    assert done["status"] == "analyse", done
    assert done["extracted_fields"]["lignes_completees"] == 3
    assert len(api_anthropic.requetes) == 2
    for corps in api_anthropic.requetes:
        _verifier_requete_ocr(corps)
    dl = env.client.get(f"/api/ocr-pieces/{piece['id']}/json-complete", headers=_h("pharma_a"))
    assert dl.status_code == 200
    assert "InventaireS%C3%A9lectionn%C3%A9_PPH_INV067_" in dl.headers["content-disposition"]
    complet = json.loads(dl.content)
    assert {l["Chrono"]: l["ISalle"] for l in complet["REQ_DétailInventaire"]}[3] == 40
    assert env.emails and env.emails[-1]["subject"].startswith("[PPH] Inventaire INV067 — liste de pointage traitée")


# ===========================================================================
# 6. Plus aucune dépendance à emergentintegrations
# ===========================================================================
def test_aucun_import_emergentintegrations_dans_le_backend():
    fautifs = []
    for f in BACKEND.rglob("*.py"):
        if "tests" in f.relative_to(BACKEND).parts or "venv" in f.parts:
            continue
        for n, ligne in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if re.match(r"\s*(from|import)\s+emergentintegrations", ligne):
                fautifs.append(f"{f.relative_to(BACKEND)}:{n}")
    assert fautifs == []
    exigences = (BACKEND / "requirements.txt").read_text()
    assert "emergentintegrations" not in exigences and "extra-index-url" not in exigences
    assert re.search(r"^anthropic==\d", exigences, re.M)


def test_modules_importables_sans_emergentintegrations():
    """Import des modules modifiés dans un interpréteur où emergentintegrations est INTERDIT."""
    code = (
        "import sys, importlib.abc\n"
        "class Bloque(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, nom, *a):\n"
        "        if nom.split('.')[0] == 'emergentintegrations': raise ImportError('interdit')\n"
        "sys.meta_path.insert(0, Bloque())\n"
        "import ia_client, paiement_stripe, storage, object_storage, ocr_core.engine, ocr_pointage, import_formulaire\n"
        "import routes.payments_stripe, routes.product_checkout_9n, routes.llm_health, routes.ai_media\n"
        "import routes.story_studio, routes.internal_chat, routes.migration_render, routes.ocr_pieces\n"
        "print('ok')\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "EMERGENT_LLM_KEY"}
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), r.stderr[-2000:]
