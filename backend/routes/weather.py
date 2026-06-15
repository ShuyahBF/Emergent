"""Iter43-fix20 (2026-06) — Météo widget (Open-Meteo + IP geolocation).

Routes :
  GET  /api/public/weather/settings          → flags publics (enabled, units, défaut)
  GET  /api/public/weather/ip-locate         → résout IP du client en ville (ipwho.is)
  GET  /api/public/weather/geocode?q=…       → ville → lat/lon (Open-Meteo geocoding)
  GET  /api/public/weather/current?lat=&lon= → météo actuelle (Open-Meteo)

Spécifications :
  - Open-Meteo : 100% gratuit, sans clé API, ~10k req/jour gratuit.
  - ipwho.is : IP→ville gratuit, sans clé, HTTPS.
  - Cache mémoire 10 min pour réduire la charge sur les APIs externes.
  - L'IP du client est anonymisée dans les logs (last octet masqué).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger("sawali.weather")

# ---- Cache mémoire simple (TTL 10 min) ----
_CACHE: Dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 600  # 10 minutes


def _cache_get(key: str):
    item = _CACHE.get(key)
    if not item:
        return None
    ts, val = item
    if time.time() - ts > _CACHE_TTL:
        _CACHE.pop(key, None)
        return None
    return val


def _cache_set(key: str, val: Any):
    _CACHE[key] = (time.time(), val)


def _anonymize_ip(ip: str) -> str:
    if ":" in ip:  # IPv6
        parts = ip.split(":")
        return ":".join(parts[:3] + ["xx"] * (len(parts) - 3))
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.x"
    return ip


def _client_ip(request: Request) -> str:
    # Cloudflare puis X-Forwarded-For puis client.host
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else "") or ""


# ---- Open-Meteo "weather code" → label FR/EN + icône (lucide) ----
# Source : https://open-meteo.com/en/docs (WMO Weather interpretation codes)
WEATHER_CODE_MAP: Dict[int, Dict[str, str]] = {
    0:  {"fr": "Ciel dégagé",          "en": "Clear sky",         "icon": "sun"},
    1:  {"fr": "Principalement clair", "en": "Mainly clear",      "icon": "sun"},
    2:  {"fr": "Partiellement nuageux","en": "Partly cloudy",     "icon": "cloud-sun"},
    3:  {"fr": "Couvert",              "en": "Overcast",          "icon": "cloud"},
    45: {"fr": "Brouillard",           "en": "Fog",               "icon": "cloud-fog"},
    48: {"fr": "Brouillard givrant",   "en": "Depositing rime fog","icon": "cloud-fog"},
    51: {"fr": "Bruine légère",        "en": "Light drizzle",     "icon": "cloud-drizzle"},
    53: {"fr": "Bruine modérée",       "en": "Moderate drizzle",  "icon": "cloud-drizzle"},
    55: {"fr": "Bruine dense",         "en": "Dense drizzle",     "icon": "cloud-drizzle"},
    56: {"fr": "Bruine verglaçante",   "en": "Freezing drizzle",  "icon": "cloud-drizzle"},
    57: {"fr": "Bruine verglaçante",   "en": "Freezing drizzle",  "icon": "cloud-drizzle"},
    61: {"fr": "Pluie légère",         "en": "Slight rain",       "icon": "cloud-rain"},
    63: {"fr": "Pluie modérée",        "en": "Moderate rain",     "icon": "cloud-rain"},
    65: {"fr": "Pluie forte",          "en": "Heavy rain",        "icon": "cloud-rain"},
    66: {"fr": "Pluie verglaçante",    "en": "Freezing rain",     "icon": "cloud-rain"},
    67: {"fr": "Pluie verglaçante",    "en": "Freezing rain",     "icon": "cloud-rain"},
    71: {"fr": "Neige légère",         "en": "Slight snow",       "icon": "cloud-snow"},
    73: {"fr": "Neige modérée",        "en": "Moderate snow",     "icon": "cloud-snow"},
    75: {"fr": "Neige forte",          "en": "Heavy snow",        "icon": "cloud-snow"},
    77: {"fr": "Grains de neige",      "en": "Snow grains",       "icon": "cloud-snow"},
    80: {"fr": "Averses légères",      "en": "Slight showers",    "icon": "cloud-rain"},
    81: {"fr": "Averses modérées",     "en": "Moderate showers",  "icon": "cloud-rain"},
    82: {"fr": "Averses violentes",    "en": "Violent showers",   "icon": "cloud-rain-wind"},
    85: {"fr": "Averses de neige",     "en": "Snow showers",      "icon": "cloud-snow"},
    86: {"fr": "Averses de neige",     "en": "Snow showers",      "icon": "cloud-snow"},
    95: {"fr": "Orage",                "en": "Thunderstorm",      "icon": "cloud-lightning"},
    96: {"fr": "Orage avec grêle",     "en": "Thunderstorm + hail","icon": "cloud-lightning"},
    99: {"fr": "Orage violent + grêle","en": "Severe thunderstorm","icon": "cloud-lightning"},
}


def _interpret_code(code: int) -> Dict[str, str]:
    return WEATHER_CODE_MAP.get(code) or {"fr": "Conditions inconnues", "en": "Unknown", "icon": "cloud"}


def setup_weather_routes(*, db, api):
    """Mount weather routes on the provided api router."""

    @api.get("/public/weather/settings", tags=["Public — Météo"])
    async def get_weather_settings():
        """Lit la config météo publique depuis db.settings. Retourne au moins
        `enabled=False` si rien n'est configuré.
        """
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {
            "enabled": bool(s.get("weather_widget_enabled")),
            "show_public": bool(s.get("weather_widget_show_public", True)),
            "show_portal": bool(s.get("weather_widget_show_portal", True)),
            "default_city": s.get("weather_widget_default_city") or "",
            "default_country": s.get("weather_widget_default_country") or "",
        }

    @api.get("/public/weather/ip-locate", tags=["Public — Météo"])
    async def ip_locate(request: Request):
        """Tente de résoudre l'IP de la requête en ville/lat/lon.

        Stratégie :
          1. Si Cloudflare nous renvoie `cf-iplatitude`/`cf-iplongitude` →
             on utilise directement (ultra-rapide, gratuit, RGPD-friendly).
          2. Sinon, on appelle ipwho.is (gratuit, sans clé).
          3. En dernier recours, on renvoie un fallback configurable.
        """
        ip = _client_ip(request)
        cache_key = f"iploc:{ip}"
        cached = _cache_get(cache_key)
        if cached:
            return cached

        out: Dict[str, Any] = {"ip": _anonymize_ip(ip), "source": None}

        # Stratégie 1 — Cloudflare headers
        try:
            lat = request.headers.get("cf-iplatitude")
            lon = request.headers.get("cf-iplongitude")
            city = request.headers.get("cf-ipcity")
            country = request.headers.get("cf-ipcountry")
            if lat and lon:
                out.update({
                    "lat": float(lat),
                    "lon": float(lon),
                    "city": city or None,
                    "country": country or None,
                    "source": "cloudflare",
                })
                _cache_set(cache_key, out)
                return out
        except (TypeError, ValueError):
            pass

        # Stratégie 2 — ipwho.is (gratuit, sans clé)
        if ip and not ip.startswith(("10.", "127.", "192.168.", "172.")):
            try:
                async with httpx.AsyncClient(timeout=4.0) as http:
                    r = await http.get(f"https://ipwho.is/{ip}")
                    if r.status_code < 300:
                        d = r.json()
                        if d.get("success"):
                            out.update({
                                "lat": d.get("latitude"),
                                "lon": d.get("longitude"),
                                "city": d.get("city"),
                                "country": d.get("country_code"),
                                "source": "ipwho.is",
                            })
                            _cache_set(cache_key, out)
                            return out
            except Exception as exc:  # noqa: BLE001
                logger.warning("[weather] ipwho.is failed: %s", exc)

        # Stratégie 3 — fallback ville par défaut du tenant
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0,
            "weather_widget_default_city": 1, "weather_widget_default_country": 1}) or {}
        default_city = s.get("weather_widget_default_city") or "Ouagadougou"
        default_country = s.get("weather_widget_default_country") or "BF"
        out.update({
            "city": default_city, "country": default_country,
            "source": "fallback_default",
        })
        # Résoudre la lat/lon de cette ville via geocoding
        try:
            geo = await _geocode(default_city)
            if geo:
                out["lat"] = geo["lat"]
                out["lon"] = geo["lon"]
        except Exception:  # noqa: BLE001
            pass
        _cache_set(cache_key, out)
        return out

    @api.get("/public/weather/geocode", tags=["Public — Météo"])
    async def geocode(q: str = Query(..., min_length=2, max_length=120)):
        """Recherche une ville par nom et renvoie lat/lon + variantes.
        Source : Open-Meteo Geocoding API (gratuit, multilingue)."""
        result = await _geocode(q)
        if not result:
            raise HTTPException(status_code=404, detail="Ville introuvable")
        return result

    @api.get("/public/weather/current", tags=["Public — Météo"])
    async def current(
        lat: float = Query(..., ge=-90, le=90),
        lon: float = Query(..., ge=-180, le=180),
        units: str = Query("celsius", pattern="^(celsius|fahrenheit)$"),
    ):
        """Renvoie la météo actuelle (temp, ressenti, humidité, vent, condition)
        + prochaines 24 h en données horaires basiques."""
        cache_key = f"weather:{round(lat,2)}:{round(lon,2)}:{units}"
        cached = _cache_get(cache_key)
        if cached:
            return cached
        temp_unit = "celsius" if units == "celsius" else "fahrenheit"
        wind_unit = "kmh"
        try:
            async with httpx.AsyncClient(timeout=8.0) as http:
                r = await http.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                                   "weather_code,wind_speed_10m,is_day",
                        "hourly": "temperature_2m,weather_code",
                        "forecast_days": 1,
                        "temperature_unit": temp_unit,
                        "wind_speed_unit": wind_unit,
                        "timezone": "auto",
                    },
                )
                if r.status_code >= 300:
                    raise HTTPException(status_code=502, detail=f"Open-Meteo HTTP {r.status_code}")
                d = r.json() or {}
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Open-Meteo erreur réseau: {exc}") from exc

        cur = d.get("current") or {}
        code = int(cur.get("weather_code") or 0)
        interp = _interpret_code(code)
        is_day = bool(cur.get("is_day", 1))
        # Adjust icon: clear sky at night → moon
        if is_day is False and interp["icon"] == "sun":
            interp = {**interp, "icon": "moon"}

        result = {
            "lat": lat,
            "lon": lon,
            "units": {"temp": "°C" if units == "celsius" else "°F", "wind": "km/h"},
            "temperature": cur.get("temperature_2m"),
            "feels_like": cur.get("apparent_temperature"),
            "humidity_pct": cur.get("relative_humidity_2m"),
            "wind_kmh": cur.get("wind_speed_10m"),
            "weather_code": code,
            "is_day": is_day,
            "label_fr": interp["fr"],
            "label_en": interp["en"],
            "icon": interp["icon"],
            "timezone": d.get("timezone"),
            "fetched_at": int(time.time()),
        }
        _cache_set(cache_key, result)
        return result


async def _geocode(name: str) -> Optional[Dict[str, Any]]:
    cache_key = f"geo:{name.lower()}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            r = await http.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": name, "count": 1, "language": "fr"},
            )
            if r.status_code >= 300:
                return None
            d = r.json() or {}
            results = d.get("results") or []
            if not results:
                return None
            top = results[0]
            out = {
                "name": top.get("name"),
                "lat": top.get("latitude"),
                "lon": top.get("longitude"),
                "country": top.get("country_code"),
                "country_name": top.get("country"),
                "admin1": top.get("admin1"),
                "timezone": top.get("timezone"),
            }
            _cache_set(cache_key, out)
            return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("[weather] geocode failed: %s", exc)
        return None
