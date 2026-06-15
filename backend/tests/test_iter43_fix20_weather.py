"""Iter43-fix20 — Tests pour le widget Météo (Open-Meteo).

Vérifie :
  - GET /api/public/weather/settings → flags publics
  - GET /api/public/weather/geocode?q=Ouagadougou → lat/lon
  - GET /api/public/weather/current?lat=&lon= → météo + interprétation icône
  - GET /api/public/weather/ip-locate → résolution (au moins ville par défaut en fallback)
  - PUT /api/admin/settings accepte les nouveaux champs weather_*
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001") + "/api"


def _admin_token() -> str:
    r1 = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@sawalismartsystems.com", "password": "Admin@Sawali2026"},
        timeout=10,
    )
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    if not d1.get("needs_otp"):
        return d1["access_token"]
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": d1["session_token"], "code": d1["dev_otp"]},
        timeout=10,
    )
    assert r2.status_code == 200, r2.text
    return r2.json()["access_token"]


class TestWeather:
    def test_settings_endpoint_responds(self):
        r = requests.get(f"{API}/public/weather/settings", timeout=10)
        assert r.status_code == 200
        d = r.json()
        for k in ("enabled", "show_public", "show_portal", "default_city", "default_country"):
            assert k in d, f"missing key: {k}"

    def test_geocode_finds_known_city(self):
        r = requests.get(f"{API}/public/weather/geocode", params={"q": "Ouagadougou"}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"]
        assert -90 <= d["lat"] <= 90
        assert -180 <= d["lon"] <= 180
        assert d["country"] == "BF" or "BF" in str(d.get("country_name", ""))

    def test_geocode_404_for_garbage(self):
        r = requests.get(f"{API}/public/weather/geocode", params={"q": "Zzz999impossible"}, timeout=10)
        assert r.status_code in (404, 422)

    def test_current_weather_basic_shape(self):
        # Ouagadougou approx
        r = requests.get(f"{API}/public/weather/current", params={"lat": 12.37, "lon": -1.52}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("temperature", "feels_like", "humidity_pct", "wind_kmh", "weather_code", "label_fr", "label_en", "icon"):
            assert k in d, f"missing field: {k}"
        assert d["units"]["temp"] in ("°C", "°F")
        # Sanity: température dans des bornes physiques
        assert -80 <= float(d["temperature"]) <= 70

    def test_current_weather_fahrenheit(self):
        r = requests.get(
            f"{API}/public/weather/current",
            params={"lat": 12.37, "lon": -1.52, "units": "fahrenheit"},
            timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["units"]["temp"] == "°F"

    def test_current_weather_rejects_invalid_units(self):
        r = requests.get(
            f"{API}/public/weather/current",
            params={"lat": 12.37, "lon": -1.52, "units": "kelvin"},
            timeout=10,
        )
        assert r.status_code == 422

    def test_ip_locate_returns_at_least_fallback(self):
        r = requests.get(f"{API}/public/weather/ip-locate", timeout=10)
        assert r.status_code == 200
        d = r.json()
        # Au minimum on doit avoir une source et une ville (même si fallback)
        assert d.get("source")
        assert d.get("city") or (d.get("lat") and d.get("lon"))

    def test_admin_settings_accepts_weather_fields(self):
        tok = _admin_token()
        r = requests.put(
            f"{API}/admin/settings",
            json={
                "weather_widget_enabled": True,
                "weather_widget_show_public": True,
                "weather_widget_show_portal": False,
                "weather_widget_default_city": "Ouagadougou",
                "weather_widget_default_country": "BF",
            },
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        # Vérifier que la lecture publique reflète le changement
        r2 = requests.get(f"{API}/public/weather/settings", timeout=10)
        d = r2.json()
        assert d["enabled"] is True
        assert d["show_public"] is True
        assert d["show_portal"] is False
        assert d["default_city"] == "Ouagadougou"
        assert d["default_country"] == "BF"
