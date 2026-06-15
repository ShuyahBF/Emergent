"""Iter43-fix18 — Sitemap XML + robots.txt dynamiques.

Vérifie :
  - GET /api/sitemap.xml renvoie un XML valide conforme à sitemaps.org
  - Contient au moins les pages statiques principales + /privacy
  - GET /api/robots.txt renvoie une référence Sitemap
  - Le fichier statique /robots.txt (frontend) référence sawalismartsystems.com
"""
import os
import re
import requests
from xml.etree import ElementTree as ET
from dotenv import load_dotenv

# Le test doit toucher le DOMAINE PUBLIC (frontend ingress) pour vérifier
# le fichier statique /robots.txt. /app/backend/.env contient localhost:8001
# (uniquement le backend), donc on utilise /app/frontend/.env.
load_dotenv("/app/frontend/.env")
API_BASE = os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:3000"
API = API_BASE + "/api"


class TestSitemap:
    def test_sitemap_is_xml_and_200(self):
        r = requests.get(f"{API}/sitemap.xml", timeout=10)
        assert r.status_code == 200, r.text[:300]
        assert "xml" in r.headers.get("content-type", "").lower()
        # Doit parser sans erreur
        root = ET.fromstring(r.text)
        # Namespace sitemaps.org/0.9
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        urls = root.findall(f"{ns}url")
        assert len(urls) >= 10, f"trop peu d'URLs: {len(urls)}"

    def test_sitemap_supports_head(self):
        """Google Search Console envoie un HEAD avant le GET — si le HEAD
        renvoie 405 Method Not Allowed, Google marque le sitemap comme
        « Impossible de récupérer »."""
        r = requests.head(f"{API}/sitemap.xml", timeout=10)
        assert r.status_code == 200, f"HEAD doit retourner 200, reçu {r.status_code}"

    def test_sitemap_contains_main_pages(self):
        r = requests.get(f"{API}/sitemap.xml", timeout=10)
        body = r.text
        # Pages essentielles à indexer
        for path in ["/", "/missions", "/catalogue", "/blog", "/contact", "/privacy", "/garde"]:
            # On vérifie qu'au moins une `<loc>...path</loc>` matche
            assert re.search(rf"<loc>[^<]+{re.escape(path)}</loc>", body), f"absent: {path}"

    def test_sitemap_priorities_in_range(self):
        r = requests.get(f"{API}/sitemap.xml", timeout=10)
        priorities = re.findall(r"<priority>([\d.]+)</priority>", r.text)
        assert len(priorities) > 0
        for p in priorities:
            v = float(p)
            assert 0.0 <= v <= 1.0, f"priority hors bornes: {v}"

    def test_robots_via_api_has_sitemap(self):
        r = requests.get(f"{API}/robots.txt", timeout=10)
        assert r.status_code == 200
        assert "Sitemap:" in r.text
        # On accepte les deux URLs (legacy /api/sitemap.xml ou la nouvelle /sitemap.xml)
        assert ("/api/sitemap.xml" in r.text) or ("/sitemap.xml" in r.text)

    def test_robots_supports_head(self):
        r = requests.head(f"{API}/robots.txt", timeout=10)
        assert r.status_code == 200

    def test_static_robots_has_sitemap(self):
        """Frontend static /robots.txt (servi par CRA) doit aussi référencer
        le sitemap pour que Google le trouve à la racine du domaine."""
        r = requests.get(f"{API_BASE}/robots.txt", timeout=10)
        assert r.status_code == 200
        assert "Sitemap:" in r.text
        # Production URL canonique (statique, indépendante du host)
        assert "sawalismartsystems.com" in r.text

    def test_root_sitemap_index_serves(self):
        """Iter43-fix19 — /sitemap.xml à la racine du domaine renvoie un
        sitemap index qui pointe vers /api/sitemap.xml. Permet aux outils
        SEO (Google Search Console, Bing Webmaster) de découvrir le sitemap
        à l'URL canonique attendue."""
        r = requests.get(f"{API_BASE}/sitemap.xml", timeout=10)
        assert r.status_code == 200
        assert "xml" in r.headers.get("content-type", "").lower()
        assert "<sitemapindex" in r.text
        assert "/api/sitemap.xml" in r.text
