"""Fiche produit VIDAL + recherche structurée + Posologie (portage depuis la
maquette `site-meetafrican`, voir PORTAGE-SAWALI-VIDAL.md).

Ce module NE réimplémente PAS le client HTTP VIDAL (auth app_id/app_key,
cache Mongo, quota) : tout ça existe déjà dans `routes/vidal.py`
(`_vidal_call`, `_ensure_tenant_can_access`, `_cache_key`/`_cache_get`/
`_cache_set`, `_quota_check_and_increment`) et fonctionne déjà en réel
(`!doc`/`!rech` sur WhatsApp, voir vidal_riche.py). Ce module ajoute
uniquement le PARSING structuré (Atom → JSON) et les endpoints qui en ont
besoin :

  1. `/vidal/search/parsed`      — recherche → liste {title, vidal_id, vmp_id}
     au lieu du XML Atom brut (`_parse_atom_entries`, déjà utilisé par
     vidal_riche.py pour `!doc`/`!rech` — même parseur, réutilisé ici).
  2. `/vidal/product/{id}/detail` — un seul appel VIDAL agrégé
     (`?aggregate=ROUTE&aggregate=DOCUMENTS`, confirmé par test réel côté
     site-meetafrican) → {name, vmp_id, routes[], documents[]}. Alimente la
     page "Fiche produit VIDAL" ET la liste "Voie d'administration" de
     Posologie.
  3. `/vidal/vmp/{vmp_id}/equivalents` — produits équivalents (même DCI +
     dosage), regroupement VMP officiel VIDAL.
  4. `/vidal/documents/proxy` — relaie un document VIDAL public (RCP PDF
     notamment) qui répond avec `X-Frame-Options: SAMEORIGIN` (confirmé par
     test réel) et ne peut donc pas être chargé en iframe depuis son URL
     VIDAL d'origine. Liste d'hôtes limitée : jamais un proxy ouvert.
  5. `/vidal/product/{id}/posology-descriptors` — EXPÉRIMENTAL. Cet endpoint
     VIDAL n'a JAMAIS été testé en réel (ni ici, ni dans site-meetafrican où
     la page Posologie était 100% simulée) — contrairement à search/detail/
     molecules/vmp qui ont chacun été validés par un appel réel. On relaie
     les paramètres tels quels et on renvoie la réponse brute VIDAL avec un
     flag `experimental: true` — à ne jamais présenter comme un résultat
     fiable côté UI.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import Depends, HTTPException, Query, Response

# Hôtes VIDAL publics autorisés pour /documents/proxy — jamais un proxy
# ouvert : uniquement les domaines vus dans les URLs renvoyées par
# /product/{id}/detail (confirmé par test réel côté site-meetafrican).
_ALLOWED_DOCUMENT_HOSTS = {"api.vidal.fr", "document-rcp.vidal.fr"}

_VIDAL_NS = "http://api.vidal.net/-/spec/vidal-api/1.0/"
_CATEGORIES_RE = re.compile(
    r'<entry\b[^>]*\bcategories="([^"]*)"[^>]*>(.*?)</entry>', re.DOTALL | re.IGNORECASE
)
_NAME_RE = re.compile(r"<(?:[a-z][a-z0-9]*:)?name>([^<]*)</(?:[a-z][a-z0-9]*:)?name>", re.IGNORECASE)
_ID_RE = re.compile(r"<(?:[a-z][a-z0-9]*:)?id>\s*(\d+)\s*</(?:[a-z][a-z0-9]*:)?id>", re.IGNORECASE)
_VMP_RE = re.compile(r'<(?:[a-z][a-z0-9]*:)?vmp\b[^>]*\bvidalId="(\d+)"', re.IGNORECASE)
_ITEM_TYPE_RE = re.compile(r'<(?:[a-z][a-z0-9]*:)?itemType\b[^>]*\bname="([^"]*)"', re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]*)</title>", re.IGNORECASE)
_DOC_LINK_RE = re.compile(
    r'<link\b[^>]*\brel="related"[^>]*\btype="application/xhtml\+xml"[^>]*\bhref="([^"]*)"',
    re.IGNORECASE,
)


def parse_product_detail(raw: Optional[str]) -> Dict[str, Any]:
    """Parse la réponse Atom de GET /product/{id}?aggregate=ROUTE&aggregate=DOCUMENTS.

    Chaque `<entry categories="PRODUCT|ROUTE|DOCUMENT">` est réparti selon cet
    attribut plutôt que de deviner l'ordre (même logique que
    `vidal_client.parse_product_detail` de site-meetafrican, portée ici en
    regex pour rester cohérente avec `_parse_atom_entries` déjà utilisé par
    vidal_riche.py plutôt que d'introduire xml.etree dans ce backend).
    """
    name: Optional[str] = None
    vmp_id: Optional[str] = None
    routes: List[Dict[str, Any]] = []
    documents: Dict[str, Dict[str, Any]] = {}  # dédupliqué par item_type (1ère occurrence = la + récente)

    if not isinstance(raw, str) or "<entry" not in raw:
        return {"name": name, "vmp_id": vmp_id, "routes": routes, "documents": []}

    for categories, block in _CATEGORIES_RE.findall(raw):
        cats = categories.upper()
        if "PRODUCT" in cats:
            name_m = _NAME_RE.search(block)
            name = name_m.group(1).strip() if name_m else name
            vmp_m = _VMP_RE.search(block)
            vmp_id = vmp_m.group(1) if vmp_m else vmp_id
        elif "ROUTE" in cats:
            id_m = _ID_RE.search(block)
            name_m = _NAME_RE.search(block)
            routes.append({
                "id": id_m.group(1) if id_m else None,
                "name": name_m.group(1).strip() if name_m else None,
            })
        elif "DOCUMENT" in cats:
            type_m = _ITEM_TYPE_RE.search(block)
            item_type = type_m.group(1) if type_m else None
            if not item_type or item_type in documents:
                continue
            title_m = _TITLE_RE.search(block)
            link_m = _DOC_LINK_RE.search(block)
            doc_url = link_m.group(1) if link_m else None
            documents[item_type] = {
                "item_type": item_type,
                "title": title_m.group(1).strip() if title_m else None,
                "url": doc_url,
                # HTML public directement affichable en iframe (confirmé par test
                # réel : api.vidal.fr/data/mono/... répond sans auth, sans
                # X-Frame-Options). Le reste (PDF sur document-rcp.vidal.fr
                # notamment) doit passer par /vidal/documents/proxy.
                "is_html": bool(doc_url and doc_url.lower().endswith((".html", ".htm"))),
            }

    return {"name": name, "vmp_id": vmp_id, "routes": routes, "documents": list(documents.values())}


def attach_vidal_fiche_routes(*, api, db, get_current_user):
    """Monte les endpoints "Fiche produit VIDAL" + Posologie sous `/api/vidal/*`.

    Appelé directement depuis server.py (même pattern que
    `attach_vidal_favorites_routes`), juste après `attach_vidal_routes` —
    `get_current_user` est passé en paramètre plutôt qu'importé depuis
    `server`, pour éviter tout import circulaire.

    Importe ses dépendances internes depuis `routes.vidal`/`routes.vidal_riche`
    au moment de l'appel (et non en haut de fichier) : à ce stade du
    chargement, ces deux modules sont déjà pleinement importés par server.py
    (attach_vidal_routes tourne avant), donc pas de risque de cycle.
    """
    from routes.vidal import (
        _vidal_call, _ensure_tenant_can_access, _ensure_active,
        _quota_check_and_increment, _cache_key, _cache_get, _cache_set,
    )
    from routes.vidal_riche import _parse_atom_entries

    # ---- Recherche structurée (title/vidal_id/vmp_id au lieu de l'Atom brut) ----
    @api.get("/vidal/search/parsed", tags=["VIDAL"])
    async def search_parsed(
        q: str = Query(..., min_length=2, description="Terme de recherche"),
        filter: Optional[str] = Query(None, regex="^(product|package|ucd|vmp|all-packages)$"),
        user: dict = Depends(get_current_user),
    ):
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        params: Dict[str, Any] = {"q": q}
        if filter:
            params["filter"] = filter
        ckey = _cache_key(cfg["mode"], "GET", "/products", params)
        cached = await _cache_get(db, ckey, cfg["cache_ttl_hours"])
        data = cached
        if data is None:
            data = await _vidal_call(cfg, "GET", "/products", params=params)
            await _cache_set(db, ckey, data)
        results = _parse_atom_entries((data or {}).get("raw"))
        return {"query": q, "results": results}

    # ---- Fiche produit : voies d'administration + documents + vmp_id ----
    @api.get("/vidal/product/{product_id}/detail", tags=["VIDAL"])
    async def product_detail(product_id: str, user: dict = Depends(get_current_user)):
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        path = f"/product/{product_id}"
        params = {"aggregate": ["ROUTE", "DOCUMENTS"]}
        ckey = _cache_key(cfg["mode"], "GET", path, params)
        cached = await _cache_get(db, ckey, cfg["cache_ttl_hours"])
        data = cached
        if data is None:
            data = await _vidal_call(cfg, "GET", path, params=params)
            await _cache_set(db, ckey, data)
        return parse_product_detail((data or {}).get("raw"))

    # ---- Équivalences (regroupement VMP officiel) ----
    @api.get("/vidal/vmp/{vmp_id}/equivalents", tags=["VIDAL"])
    async def vmp_equivalents(
        vmp_id: str,
        exclude_product_id: Optional[str] = None,
        user: dict = Depends(get_current_user),
    ):
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        path = f"/vmp/{vmp_id}/products"
        params = {"page-size": 50}
        ckey = _cache_key(cfg["mode"], "GET", path, params)
        cached = await _cache_get(db, ckey, cfg["cache_ttl_hours"])
        data = cached
        if data is None:
            data = await _vidal_call(cfg, "GET", path, params=params)
            await _cache_set(db, ckey, data)
        equivalents = _parse_atom_entries((data or {}).get("raw"))
        if exclude_product_id:
            equivalents = [e for e in equivalents if e.get("vidal_id") != exclude_product_id]
        return {"vmp_id": vmp_id, "equivalents": equivalents}

    # ---- Proxy documents (X-Frame-Options SAMEORIGIN) ----
    @api.get("/vidal/documents/proxy", tags=["VIDAL"])
    async def documents_proxy(
        url: str = Query(..., min_length=1),
        user: dict = Depends(get_current_user),
    ):
        """Relaie un document VIDAL public depuis notre propre origine.

        URLs publiques (aucun app_id/app_key requis, donc aucun quota VIDAL
        consommé ici) — on exige seulement une session portail valide
        (`get_current_user`) pour éviter qu'un lien traîne en clair, et on
        limite les hôtes cibles pour ne jamais devenir un proxy ouvert.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in _ALLOWED_DOCUMENT_HOSTS:
            raise HTTPException(status_code=400, detail="URL de document VIDAL non autorisée")
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                r = await client.get(url)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Délai dépassé en récupérant le document VIDAL")
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Erreur en récupérant le document : {str(exc)[:200]}") from exc
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Document VIDAL introuvable ({r.status_code})")
        return Response(content=r.content, media_type=r.headers.get("content-type", "application/octet-stream"))

    # ---- Posologie (EXPÉRIMENTAL — endpoint jamais validé en réel) ----
    @api.get("/vidal/product/{product_id}/posology-descriptors", tags=["VIDAL"])
    async def posology_descriptors(
        product_id: str,
        route: Optional[str] = Query(None, description="Référence VIDAL de la voie d'administration (id renvoyé par /detail)"),
        indication: Optional[str] = Query(None, description="Libellé indication — non confirmé côté schéma VIDAL"),
        user: dict = Depends(get_current_user),
    ):
        """Relaie `/product/{id}/posology-descriptors`.

        ⚠️ Contrairement à search/detail/molecules/vmp (validés par appel
        réel), cet endpoint n'a JAMAIS été testé contre l'API VIDAL de
        production — ni dans ce lot, ni dans la maquette site-meetafrican
        d'origine où la recherche de posologie était 100% simulée (résultats
        en dur). On relaie tel quel et on renvoie `experimental: true` pour
        que l'UI affiche systématiquement un avertissement plutôt que de
        présenter le résultat comme fiable.
        """
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        params: Dict[str, Any] = {}
        if route:
            params["route"] = route
        if indication:
            params["indication"] = indication
        data = await _vidal_call(cfg, "GET", f"/product/{product_id}/posology-descriptors", params=params)
        return {"experimental": True, "data": data}
