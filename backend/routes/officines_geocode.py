"""Iter43-fix24aw (2026-02-26) — Officines GPS geocoding (Google Maps + OSM).

Resolves the GPS coordinates of selected officines by querying a geocoding
provider with the officine's name + city + country.

Two providers supported (chosen automatically based on settings) :
  - **Google Maps Places API** (best precision) — requires
    `settings.global.google_maps_api_key`. Free tier : 5000 requests/month.
  - **OpenStreetMap Nominatim** (free fallback) — no key required, but the
    accuracy for pharmacy names in West Africa is limited. Rate-limited to
    1 req/sec by Nominatim policy.

Endpoints (admin only) :
  - `POST /api/admin/officines-registry/geocode-batch`
       Body: {officine_ids: [str], overwrite_existing: bool}
       Returns: {processed, succeeded, failed, results: [{id, name, status, lat, lng, source, error}]}
  - `POST /api/admin/officines-registry/{id}/geocode`
       Single-officine convenience endpoint (same fields in result).
  - `GET /api/admin/geocode/config`
       Returns the provider currently in use + count of officines without GPS.

Storage : the result is written directly to `db.officines` via the fields
already used by the UI (`latitude` + `longitude`) plus three audit fields :
  - `latitude_source` (str: "google_places" | "osm_nominatim" | "manual")
  - `latitude_resolved_at` (ISO datetime)
  - `latitude_resolved_query` (the query string used)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.officines.geocode")

# Default country bias when the officine has no explicit country.
# Adjustable via settings.global.geocode_country_bias.
DEFAULT_COUNTRY_BIAS = "Burkina Faso"

# Nominatim politeness — we MUST set a real User-Agent + max 1 req/sec.
NOMINATIM_USER_AGENT = "SAWALI-SMART-SYSTEMS/1.0 (contact: jfrancois.ouoba@gmail.com)"
NOMINATIM_BASE = "https://nominatim.openstreetmap.org/search"
NOMINATIM_DELAY = 1.05  # seconds between calls

GOOGLE_PLACES_BASE = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
GOOGLE_GEOCODE_BASE = "https://maps.googleapis.com/maps/api/geocode/json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GeocodeBatchPayload(BaseModel):
    officine_ids: List[str] = Field(..., min_length=1, max_length=200)
    overwrite_existing: bool = Field(False, description="Re-géolocaliser même si lat/lng déjà présents")


def _build_query(officine: Dict[str, Any], country_bias: str) -> str:
    """Build the geocoding query string from an officine doc, adaptively :
      - If `address` is present: use full address + city + country
      - Else: use name + city + country
    """
    name = (officine.get("name") or "").strip()
    address = (officine.get("address") or "").strip()
    city = (officine.get("city") or "").strip()
    country = (officine.get("country") or country_bias).strip()
    parts: List[str] = []
    # Ensure the word "pharmacie" or "officine" is present for better matching
    name_lower = name.lower()
    if "pharmacie" not in name_lower and "officine" not in name_lower:
        parts.append(f"Pharmacie {name}")
    else:
        parts.append(name)
    if address:
        parts.append(address)
    if city:
        parts.append(city)
    if country:
        parts.append(country)
    return ", ".join(p for p in parts if p)


async def _geocode_via_google_places(api_key: str, query: str) -> Optional[Dict[str, Any]]:
    """Try Find Place From Text first (best for named places like pharmacies)."""
    async with httpx.AsyncClient(timeout=15) as cli:
        # 1) Find Place
        r = await cli.get(
            GOOGLE_PLACES_BASE,
            params={
                "input": query,
                "inputtype": "textquery",
                "fields": "geometry,formatted_address,name,place_id",
                "language": "fr",
                "key": api_key,
            },
        )
        data = r.json() if r.status_code == 200 else {}
        candidates = data.get("candidates") or []
        if candidates:
            c = candidates[0]
            loc = ((c.get("geometry") or {}).get("location") or {})
            if loc.get("lat") and loc.get("lng"):
                return {
                    "lat": float(loc["lat"]),
                    "lng": float(loc["lng"]),
                    "formatted_address": c.get("formatted_address") or "",
                    "name": c.get("name") or "",
                    "place_id": c.get("place_id") or "",
                    "source": "google_places",
                }
        # 2) Fallback to Geocoding API (more lenient)
        r2 = await cli.get(
            GOOGLE_GEOCODE_BASE,
            params={"address": query, "language": "fr", "key": api_key},
        )
        data2 = r2.json() if r2.status_code == 200 else {}
        results = data2.get("results") or []
        if results:
            res = results[0]
            loc = ((res.get("geometry") or {}).get("location") or {})
            if loc.get("lat") and loc.get("lng"):
                return {
                    "lat": float(loc["lat"]),
                    "lng": float(loc["lng"]),
                    "formatted_address": res.get("formatted_address") or "",
                    "name": "",
                    "place_id": res.get("place_id") or "",
                    "source": "google_geocode",
                }
    return None


async def _geocode_via_nominatim(query: str) -> Optional[Dict[str, Any]]:
    """OSM Nominatim — free fallback. Politeness : 1 req/sec, real User-Agent."""
    headers = {"User-Agent": NOMINATIM_USER_AGENT, "Accept-Language": "fr"}
    async with httpx.AsyncClient(timeout=15, headers=headers) as cli:
        r = await cli.get(
            NOMINATIM_BASE,
            params={
                "q": query,
                "format": "json",
                "limit": 1,
                "addressdetails": 1,
            },
        )
    if r.status_code != 200:
        return None
    arr = r.json() or []
    if not arr:
        return None
    hit = arr[0]
    try:
        lat = float(hit.get("lat"))
        lng = float(hit.get("lon"))
    except (TypeError, ValueError):
        return None
    return {
        "lat": lat,
        "lng": lng,
        "formatted_address": hit.get("display_name") or "",
        "name": "",
        "place_id": str(hit.get("place_id") or ""),
        "source": "osm_nominatim",
    }


async def _geocode_one(api_key: Optional[str], query: str) -> Optional[Dict[str, Any]]:
    """Try Google first if a key is set, fallback to Nominatim."""
    if api_key:
        try:
            r = await _geocode_via_google_places(api_key, query)
            if r:
                return r
        except Exception as exc:  # noqa: BLE001
            logger.warning("[geocode] Google failed for %r: %s", query, exc)
    try:
        return await _geocode_via_nominatim(query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[geocode] Nominatim failed for %r: %s", query, exc)
        return None


# --------------------------------------------------------------------------- #
# Route mounting
# --------------------------------------------------------------------------- #
def attach_officines_geocode_routes(*, api, db, get_current_admin):

    @api.get("/admin/geocode/config", tags=["Admin — Officines Registry"])
    async def get_geocode_config(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        google_key = (s.get("google_maps_api_key") or "").strip()
        country_bias = s.get("geocode_country_bias") or DEFAULT_COUNTRY_BIAS
        # Counts: how many officines miss GPS ?
        missing = await db.officines.count_documents({
            "$or": [
                {"latitude": {"$exists": False}},
                {"latitude": None},
                {"latitude": ""},
                {"longitude": {"$exists": False}},
                {"longitude": None},
                {"longitude": ""},
            ]
        })
        total = await db.officines.count_documents({})
        return {
            "provider": "google_places" if google_key else "osm_nominatim",
            "has_google_key": bool(google_key),
            "country_bias": country_bias,
            "missing_gps_count": missing,
            "total_officines": total,
            "rate_limit_msg": "Google: 5000 req/mois (free tier). OSM Nominatim: 1 req/sec.",
        }

    @api.post("/admin/officines-registry/geocode-batch", tags=["Admin — Officines Registry"])
    async def geocode_batch(
        payload: GeocodeBatchPayload = Body(...),
        user: dict = Depends(get_current_admin),
    ) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        api_key = (s.get("google_maps_api_key") or "").strip() or None
        country_bias = s.get("geocode_country_bias") or DEFAULT_COUNTRY_BIAS

        results: List[Dict[str, Any]] = []
        succeeded = 0
        failed = 0
        for idx, oid in enumerate(payload.officine_ids):
            officine = await db.officines.find_one({"id": oid}, {"_id": 0})
            if not officine:
                results.append({"id": oid, "name": "", "status": "not_found", "error": "Officine introuvable"})
                failed += 1
                continue
            # Skip if already has GPS and overwrite_existing=False
            has_gps = officine.get("latitude") and officine.get("longitude")
            if has_gps and not payload.overwrite_existing:
                results.append({
                    "id": oid, "name": officine.get("name", ""),
                    "status": "skipped_has_gps",
                    "lat": officine.get("latitude"), "lng": officine.get("longitude"),
                })
                continue

            query = _build_query(officine, country_bias)
            geo = await _geocode_one(api_key, query)
            if not geo:
                results.append({
                    "id": oid, "name": officine.get("name", ""),
                    "status": "not_resolved",
                    "query": query,
                    "error": "Aucun résultat sur la carte",
                })
                failed += 1
            else:
                # Persist
                await db.officines.update_one(
                    {"id": oid},
                    {"$set": {
                        "latitude": geo["lat"],
                        "longitude": geo["lng"],
                        "latitude_source": geo["source"],
                        "latitude_resolved_at": _now_iso(),
                        "latitude_resolved_query": query,
                        "latitude_resolved_formatted_address": geo.get("formatted_address", ""),
                        "latitude_resolved_by": user.get("email"),
                    }},
                )
                results.append({
                    "id": oid, "name": officine.get("name", ""),
                    "status": "ok",
                    "lat": geo["lat"], "lng": geo["lng"],
                    "formatted_address": geo.get("formatted_address", ""),
                    "source": geo["source"],
                    "query": query,
                })
                succeeded += 1

            # Politeness : if using OSM Nominatim, sleep 1.05s between calls
            if not api_key and idx < len(payload.officine_ids) - 1:
                await asyncio.sleep(NOMINATIM_DELAY)

        return {
            "processed": len(payload.officine_ids),
            "succeeded": succeeded,
            "failed": failed,
            "skipped": len(payload.officine_ids) - succeeded - failed,
            "provider": "google_places" if api_key else "osm_nominatim",
            "results": results,
        }

    @api.post("/admin/officines-registry/{officine_id}/geocode", tags=["Admin — Officines Registry"])
    async def geocode_single(
        officine_id: str = Path(..., min_length=1),
        overwrite_existing: bool = Query(True, description="Re-géolocaliser même si lat/lng déjà présents"),
        user: dict = Depends(get_current_admin),
    ) -> Dict[str, Any]:
        """Convenience wrapper for single-officine geocoding."""
        payload = GeocodeBatchPayload(officine_ids=[officine_id], overwrite_existing=overwrite_existing)
        # Reuse the batch logic by calling its inner body
        res = await geocode_batch(payload=payload, user=user)
        return res["results"][0] if res["results"] else {"id": officine_id, "status": "no_result"}

    logger.info("[officines.geocode] routes mounted under /api/admin/officines-registry/{geocode-batch,{id}/geocode} + /api/admin/geocode/config")
