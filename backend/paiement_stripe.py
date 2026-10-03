"""Paiement Stripe Checkout (lot 53 : indépendance d'Emergent).

Remplace `emergentintegrations.payments.stripe.checkout` par la bibliothèque
officielle `stripe`, avec la MÊME interface et la même logique :

    client = StripeCheckout(api_key=..., webhook_url=..., webhook_secret=...)
    session = await client.create_checkout_session(CheckoutSessionRequest(amount=..., currency=..., ...))
    statut  = await client.get_checkout_status(session_id)
    evenement = await client.handle_webhook(corps_brut, signature)

Différences volontaires :
  - aucune redirection vers le proxy Emergent ; la clé est passée à chaque appel
    (StripeClient), jamais posée dans la variable globale `stripe.api_key` ;
  - les appels Stripe (bloquants) partent dans un thread : le serveur ne fige pas ;
  - devises SANS décimales (XOF, XAF, JPY…) : le montant est envoyé tel quel
    (Stripe attend des unités entières) et non multiplié par 100.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import stripe
from pydantic import BaseModel, Field, validator

# Devises sans décimales chez Stripe (montant en unités entières).
DEVISES_SANS_DECIMALES = {
    "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "ugx", "vnd", "vuv",
    "xaf", "xof", "xpf",
}


class CheckoutError(Exception):
    """Erreur du paiement Stripe (même nom que dans emergentintegrations)."""


class CheckoutSessionRequest(BaseModel):
    amount: Optional[float] = Field(None)
    currency: str = Field("usd")
    stripe_price_id: Optional[str] = Field(None)
    quantity: int = Field(1)
    success_url: Optional[str] = Field(None)
    cancel_url: Optional[str] = Field(None)
    metadata: Optional[Dict[str, str]] = Field(None)
    payment_methods: Optional[List[str]] = Field(default_factory=lambda: ["card"])

    @validator("amount")
    def _montant(cls, v, values):  # noqa: N805
        if v is not None and v <= 0:
            raise ValueError("Amount must be greater than 0")
        return v

    @validator("quantity")
    def _quantite(cls, v):  # noqa: N805
        if v < 1:
            raise ValueError("Quantity must be greater than 0")
        return v

    @validator("stripe_price_id", always=True)
    def _prix(cls, v, values):  # noqa: N805
        if v is None and values.get("amount") is None:
            raise ValueError("Either amount or stripe_price_id must be provided")
        if v is not None and values.get("amount") is not None:
            raise ValueError("Cannot provide both amount and stripe_price_id")
        return v

    @validator("payment_methods")
    def _moyens(cls, v):  # noqa: N805
        if v is None:
            return None
        if isinstance(v, str):
            v = [v]
        return list(dict.fromkeys(v)) or None


class CheckoutSessionResponse(BaseModel):
    url: str
    session_id: str


class CheckoutStatusResponse(BaseModel):
    status: str
    payment_status: str
    amount_total: int
    currency: str
    metadata: Dict[str, str]


class WebhookEventResponse(BaseModel):
    event_type: str
    event_id: str
    session_id: Optional[str] = None
    payment_status: Optional[str] = None
    metadata: Dict[str, str]


def montant_stripe(montant: float, devise: str) -> int:
    """Montant en plus petite unité Stripe : ×100, sauf devises sans décimales."""
    if (devise or "").lower() in DEVISES_SANS_DECIMALES:
        return int(round(montant))
    return int(round(montant * 100))


def _en_dict(objet: Any) -> Dict[str, Any]:
    """StripeObject (ou dict) -> dict Python."""
    if objet is None:
        return {}
    if hasattr(objet, "to_dict"):
        return objet.to_dict()
    return dict(objet)


def _meta(valeur: Any) -> Dict[str, str]:
    return {str(k): "" if v is None else str(v) for k, v in _en_dict(valeur).items()}


class StripeCheckout:
    def __init__(self, api_key: str, webhook_secret: Optional[str] = None, webhook_url: Optional[str] = None):
        self.api_key = api_key
        self.webhook_secret = webhook_secret
        self.webhook_url = webhook_url

    def _client(self) -> "stripe.StripeClient":
        """Client Stripe (fonction séparée pour pouvoir la simuler en test)."""
        return stripe.StripeClient(self.api_key)

    async def create_checkout_session(self, request: CheckoutSessionRequest) -> CheckoutSessionResponse:
        try:
            if request.amount is not None:
                lignes = [{"price_data": {"currency": request.currency, "product_data": {"name": "Payment"},
                                          "unit_amount": montant_stripe(request.amount, request.currency)},
                           "quantity": 1}]
            else:
                lignes = [{"price": request.stripe_price_id, "quantity": request.quantity}]
            metadata = dict(request.metadata or {})
            if self.webhook_url:
                metadata["webhook_url"] = self.webhook_url
            params = {
                "payment_method_types": request.payment_methods or ["card"],
                "line_items": lignes, "mode": "payment",
                "success_url": request.success_url, "cancel_url": request.cancel_url,
                "metadata": metadata,
            }
            params = {k: v for k, v in params.items() if v is not None}
            session = await asyncio.to_thread(self._client().v1.checkout.sessions.create, params)
            return CheckoutSessionResponse(url=session.url, session_id=session.id)
        except stripe.StripeError as exc:
            raise CheckoutError(f"Failed to create checkout session: {exc}") from exc
        except CheckoutError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CheckoutError(f"Unexpected error creating checkout session: {exc}") from exc

    async def get_checkout_status(self, checkout_session_id: str) -> CheckoutStatusResponse:
        try:
            s = await asyncio.to_thread(self._client().v1.checkout.sessions.retrieve, checkout_session_id)
            return CheckoutStatusResponse(
                status=s.status or "", payment_status=s.payment_status or "",
                amount_total=int(s.amount_total or 0), currency=s.currency or "",
                metadata=_meta(s.metadata))
        except stripe.StripeError as exc:
            raise CheckoutError(f"Failed to retrieve session status: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise CheckoutError(f"Unexpected error retrieving session status: {exc}") from exc

    async def handle_webhook(self, payload: bytes, signature: Optional[str] = None) -> WebhookEventResponse:
        try:
            if self.webhook_secret:
                # Signature vérifiée par la bibliothèque officielle (lève si invalide ou trop ancienne)
                stripe.WebhookSignature.verify_header(
                    payload.decode("utf-8") if isinstance(payload, bytes) else payload,
                    signature or "", self.webhook_secret, stripe.Webhook.DEFAULT_TOLERANCE)
            corps = payload.decode("utf-8") if isinstance(payload, bytes) else payload
            event = json.loads(corps)
            type_ev, id_ev = event["type"], event["id"]
            objet = (event.get("data") or {}).get("object") or {}
            session_id = payment_status = None
            if type_ev in ("checkout.session.completed", "checkout.session.expired"):
                session_id, payment_status = objet.get("id"), objet.get("payment_status")
            elif type_ev == "payment_intent.succeeded":
                session_id, payment_status = (objet.get("metadata") or {}).get("checkout_session_id"), "paid"
            elif type_ev == "payment_intent.payment_failed":
                session_id, payment_status = (objet.get("metadata") or {}).get("checkout_session_id"), "failed"
            return WebhookEventResponse(event_type=type_ev, event_id=id_ev, session_id=session_id,
                                        payment_status=payment_status, metadata=_meta(objet.get("metadata")))
        except json.JSONDecodeError as exc:
            raise CheckoutError(f"Invalid JSON payload: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — signature invalide, champ manquant…
            raise CheckoutError(f"Unexpected error processing webhook: {exc}") from exc
