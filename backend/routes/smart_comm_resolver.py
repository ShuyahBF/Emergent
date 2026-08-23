"""2026-02 fork (P0.5 wiring extended) — Centralised Smart Communications
credential resolver.

Every outbound channel (WhatsApp, Meta/Facebook, Instagram, LinkedIn, X,
TikTok) now goes through a single resolver that picks per-tenant credentials
from `db.tenant_smart_comm` **when they are complete** (all required fields
non-empty) and falls back to `db.settings.global` otherwise. This matches
Q3=b (strict override, no partial merge).

Each channel exposes:
  - `required_fields`: minimum viable set (all must be non-empty to activate
    the tenant override).
  - `all_fields`: full set that gets copied when picking a tenant config.
  - `global_map`: mapping of the same fields in `db.settings.global` when the
    key names differ (they don't at the moment; kept for future safety).

Usage:
  resolver = build_smart_comm_resolver(db)
  creds = await resolver.resolve("linkedin", tenant_id)
  # creds = {source: "tenant"|"global", tenant_id, linkedin_access_token: ...}
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ChannelSchema:
    key: str
    required_fields: List[str]
    all_fields: List[str]


# NB: kept small on purpose — each sender knows what it needs; we only care
# about detecting "tenant fully configured" vs "must fall back to global".
_CHANNELS: Dict[str, ChannelSchema] = {
    "wa": ChannelSchema(
        key="wa",
        required_fields=["wa_access_token", "wa_phone_number_id"],
        all_fields=["wa_access_token", "wa_phone_number_id", "wa_waba_id", "wa_verify_token"],
    ),
    "meta": ChannelSchema(
        key="meta",
        required_fields=["meta_page_id", "meta_page_access_token"],
        all_fields=[
            "meta_app_id", "meta_app_secret", "meta_page_id", "meta_page_access_token",
        ],
    ),
    "instagram": ChannelSchema(
        key="instagram",
        required_fields=["instagram_business_id", "instagram_access_token"],
        all_fields=["instagram_business_id", "instagram_access_token"],
    ),
    "linkedin": ChannelSchema(
        key="linkedin",
        required_fields=["linkedin_access_token"],
        all_fields=[
            "linkedin_client_id", "linkedin_client_secret", "linkedin_access_token",
            "linkedin_organization_id",
        ],
    ),
    "x": ChannelSchema(
        key="x",
        required_fields=["x_api_key", "x_api_secret", "x_access_token", "x_access_secret"],
        all_fields=["x_api_key", "x_api_secret", "x_access_token", "x_access_secret"],
    ),
    "tiktok": ChannelSchema(
        key="tiktok",
        required_fields=["tiktok_access_token"],
        all_fields=["tiktok_client_id", "tiktok_client_secret", "tiktok_access_token"],
    ),
}


class SmartCommResolver:
    """Async resolver. Bind once at server startup with the shared `db`."""

    def __init__(self, db):
        self._db = db

    def channels(self) -> List[str]:
        return list(_CHANNELS.keys())

    async def resolve(self, channel: str, tenant_id: Optional[str]) -> Dict[str, Any]:
        """Return `{source, tenant_id, <field>: <value>...}` for a channel.

        - `source="tenant"` when the tenant Smart Comm doc has all
          `required_fields` filled.
        - `source="global"` otherwise (fall back to `db.settings.global`).
        - Value strings are stripped. Empty strings are treated as unset.
        """
        schema = _CHANNELS.get(channel)
        if schema is None:
            raise ValueError(f"Unknown Smart Comm channel: {channel}")
        tid = (tenant_id or "").strip()
        # --- 1) Try tenant override -------------------------------------------------
        if tid:
            try:
                doc = await self._db.tenant_smart_comm.find_one({"tenant_id": tid}, {"_id": 0}) or {}
            except Exception:  # noqa: BLE001
                doc = {}
            values = {f: (doc.get(f) or "").strip() if isinstance(doc.get(f), str) else doc.get(f) for f in schema.all_fields}
            if all(bool((values.get(f) or "")) for f in schema.required_fields):
                return {"source": "tenant", "tenant_id": tid, **values}
        # --- 2) Fall back to global settings ----------------------------------------
        try:
            s = await self._db.settings.find_one({"_id": "global"}) or {}
        except Exception:  # noqa: BLE001
            s = {}
        values = {f: (s.get(f) or "").strip() if isinstance(s.get(f), str) else s.get(f) for f in schema.all_fields}
        return {"source": "global", "tenant_id": None, **values}


def build_smart_comm_resolver(db) -> SmartCommResolver:
    return SmartCommResolver(db)


__all__ = ["SmartCommResolver", "build_smart_comm_resolver"]
