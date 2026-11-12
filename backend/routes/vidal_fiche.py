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

import asyncio
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import Body, Depends, HTTPException, Query, Response

# Hôtes VIDAL publics autorisés pour /documents/proxy — jamais un proxy
# ouvert : uniquement les domaines vus dans les URLs renvoyées par
# /product/{id}/detail (confirmé par test réel côté site-meetafrican).
_ALLOWED_DOCUMENT_HOSTS = {"api.vidal.fr", "document-rcp.vidal.fr"}

_VIDAL_NS = "http://api.vidal.net/-/spec/vidal-api/1.0/"
_CATEGORIES_RE = re.compile(
    r'<entry\b[^>]*\bcategories="([^"]*)"[^>]*>(.*?)</entry>', re.DOTALL | re.IGNORECASE
)
# ATTENTION : ne PAS extraire le nom via un `<name>`/`<vidal:name>` générique.
# Confirmé par capture réelle (Mongo `site_meetafrican.maf_vidal_api_cache`,
# path `/product/5485`) : CHAQUE entrée Atom VIDAL (PRODUCT, ROUTE, DOCUMENT)
# commence par `<author><name>VIDAL</name></author>` (nom de la marque/API,
# pas de l'item) AVANT le vrai `<vidal:name>`/`<title>` — un `re.search` sur
# `<name>` tombe donc TOUJOURS sur "VIDAL" en premier. C'est la cause du bug
# "VIDAL" en voie d'administration remonté par l'utilisateur. Le SEUL tag fiable,
# unique par entrée et toujours correct, est `<title>` (même logique déjà
# utilisée et validée en réel par `_parse_atom_entries`/`!doc`/`!rech`).
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
            title_m = _TITLE_RE.search(block)
            name = title_m.group(1).strip() if title_m else name
            vmp_m = _VMP_RE.search(block)
            vmp_id = vmp_m.group(1) if vmp_m else vmp_id
        elif "ROUTE" in cats:
            id_m = _ID_RE.search(block)
            title_m = _TITLE_RE.search(block)
            routes.append({
                "id": id_m.group(1) if id_m else None,
                "name": title_m.group(1).strip() if title_m else None,
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
    from routes.vidal_sync import get_sync_config, has_cached_referentiel, search_cached_referentiel
    from routes.vidal_audit import log_call

    async def _call_and_log(cfg, method, path, params, user_email):
        """Wrapper autour de `_vidal_call` qui journalise l'appel (Suivi des
        logs) sans jamais bloquer ni faire échouer la requête réelle : la
        journalisation part en tâche de fond après la mesure du temps écoulé.
        Limité aux endpoints de ce lot — voir vidal_audit.py."""
        started = time.monotonic()
        error: Optional[str] = None
        try:
            data = await _vidal_call(cfg, method, path, params=params)
            status = "error" if (data or {}).get("_error") else "ok"
            if status == "error":
                error = ((data or {}).get("_error") or {}).get("message")
        except Exception as exc:  # noqa: BLE001
            status, error, data = "exception", str(exc)[:300], None
            asyncio.create_task(log_call(
                db, mode=cfg.get("mode", "?"), method=method, path=path, status=status,
                elapsed_ms=int((time.monotonic() - started) * 1000), user_email=user_email, error=error,
            ))
            raise
        asyncio.create_task(log_call(
            db, mode=cfg.get("mode", "?"), method=method, path=path, status=status,
            elapsed_ms=int((time.monotonic() - started) * 1000), user_email=user_email, error=error,
        ))
        return data

    # ---- Recherche structurée (title/vidal_id/vmp_id au lieu de l'Atom brut) ----
    def _filtrer_par_forme(results: List[Dict[str, Any]], forme: Optional[str]) -> List[Dict[str, Any]]:
        """Lot 56 (sécurisation v2, filtre « Forme recherchée ») — APRÈS lecture
        du cache : même requête VIDAL quel que soit le filtre (aucun appel de
        plus). Un filtre numérique est un identifiant de forme de
        /galenic-forms (correspondance exacte) ; un filtre texte, un code de
        la liste documentée d'abréviations (vidal_v2/referentiels.py)."""
        from vidal_v2.referentiels import correspond_forme_galenique
        if not forme:
            return results
        if forme.isdigit():
            return [r for r in results if r.get("galenic_form_id") == forme]
        return [r for r in results if correspond_forme_galenique(forme, r.get("title"), r.get("galenic_form"))]

    @api.get("/vidal/search/parsed", tags=["VIDAL"])
    async def search_parsed(
        q: str = Query(..., min_length=2, description="Terme de recherche"),
        filter: Optional[str] = Query(None, regex="^(product|package|ucd|vmp|all-packages)$"),
        forme: Optional[str] = Query(None, description="Lot 56 — code ou identifiant de forme galénique"),
        user: dict = Depends(get_current_user),
    ):
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        # Portage site-meetafrican — en mode "cache" (référentiel produits
        # synchronisé, voir vidal_sync.py) : recherche locale Mongo, aucun
        # appel réseau ni quota consommé. Repli automatique sur le temps réel
        # si le mode est "temps_reel" OU si le cache n'a encore jamais été
        # synchronisé — jamais de liste vide faute de cache peuplé.
        sync_config = await get_sync_config(db)
        if sync_config.get("mode") == "cache" and await has_cached_referentiel(db):
            results = await search_cached_referentiel(db, q)
            return {"query": q, "forme": forme, "results": _filtrer_par_forme(results, forme), "source": "cache"}
        await _quota_check_and_increment(db, user["id"], cfg)
        params: Dict[str, Any] = {"q": q}
        if filter:
            params["filter"] = filter
        ckey = _cache_key(cfg["mode"], "GET", "/products", params)
        cached = await _cache_get(db, ckey, cfg["cache_ttl_hours"])
        data = cached
        if data is None:
            data = await _call_and_log(cfg, "GET", "/products", params, user.get("email"))
            await _cache_set(db, ckey, data)
        # Lot 56 — lecture enrichie (vidal_v2/parseurs.py) : mêmes champs
        # title/vidal_id/vmp_id qu'avant, plus la forme galénique et
        # l'indicateur « spécialité sécurisée par VIDAL » (safety_alert).
        from vidal_v2.parseurs import parser_entrees_atom
        results = parser_entrees_atom((data or {}).get("raw"))
        return {"query": q, "forme": forme, "results": _filtrer_par_forme(results, forme), "source": "temps_reel"}

    # Lot 378 (remarque VIDAL n°8) — recherche PAR NOM d'une présentation, d'un VMP ou d'une UCD (collections /packages, /vmps, /ucds de l'API
    # REST VIDAL). Si la collection dédiée est refusée, repli sur /products?filter=<type>. Même forme de réponse que /vidal/search/parsed.
    COLLECTION_PAR_TYPE = {"package": "/packages", "vmp": "/vmps", "ucd": "/ucds"}

    @api.get("/vidal/recherche-element/{type_element}", tags=["VIDAL"])
    async def rechercher_element(
        type_element: str, q: str = Query(..., min_length=2), user: dict = Depends(get_current_user),
    ):
        if type_element not in COLLECTION_PAR_TYPE:
            raise HTTPException(status_code=400, detail="Type d'élément non valide (package, vmp ou ucd).")
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        from vidal_v2.parseurs import parser_entrees_atom
        chemin = COLLECTION_PAR_TYPE[type_element]
        data = await _call_and_log(cfg, "GET", chemin, {"q": q}, user.get("email"))
        if isinstance(data, dict) and data.get("_error"):
            # Repli : la recherche générale filtrée sur le type.
            data = await _call_and_log(cfg, "GET", "/products", {"q": q, "filter": type_element}, user.get("email"))
        if isinstance(data, dict) and data.get("_error"):
            raise HTTPException(status_code=502, detail="VIDAL n'a pas retourné de résultat pour cette recherche.")
        return {"query": q, "type": type_element, "results": parser_entrees_atom((data or {}).get("raw")), "source": "temps_reel"}

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
            data = await _call_and_log(cfg, "GET", path, params, user.get("email"))
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
            data = await _call_and_log(cfg, "GET", path, params, user.get("email"))
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
        return await _relayer_posologie(user, "product", product_id, route, indication)

    # Lot 376 (remarque VIDAL n°8) — le module Posologie accepte aussi une présentation (package), un VMP ou une UCD : même relais, ressource du
    # même type que l'élément choisi (comme pour les unités, voies et indications). EXPÉRIMENTAL comme la version « produit ».
    @api.get("/vidal/{ressource}/{ident}/posology-descriptors", tags=["VIDAL"])
    async def posology_descriptors_autre_type(
        ressource: str, ident: str,
        route: Optional[str] = Query(None), indication: Optional[str] = Query(None),
        user: dict = Depends(get_current_user),
    ):
        if ressource not in ("package", "vmp", "ucd") or not ident.isdigit():
            raise HTTPException(status_code=400, detail="Type d'élément (package, vmp, ucd) ou identifiant non valide.")
        return await _relayer_posologie(user, ressource, ident, route, indication)

    # Lot 377 (remarques VIDAL 5 et 8) — posologies proposées par VIDAL pour un élément (spécialité, présentation, VMP, UCD) ET un patient.
    # Appel validé par Ster : POST avec corps XML <posology-request><patient>. L'âge, le sexe et le poids NE BLOQUENT JAMAIS : s'ils manquent,
    # on ne sollicite pas VIDAL (qui répondrait 400) et on renvoie une alerte lisible à afficher à l'utilisateur.
    @api.post("/vidal/{ressource}/{ident}/posology-descriptors", tags=["VIDAL"])
    async def posologies_proposees(
        ressource: str, ident: str, payload: Dict[str, Any] = Body(default_factory=dict),
        user: dict = Depends(get_current_user),
    ):
        from vidal_v2.posologie import (
            construire_xml_posology_request, message_manquants, parser_descripteurs_posologie, patient_manquants,
        )
        if ressource not in ("product", "package", "vmp", "ucd") or not ident.isdigit():
            raise HTTPException(status_code=400, detail="Type d'élément (product, package, vmp, ucd) ou identifiant non valide.")
        patient = payload.get("patient") or {}
        manquants = patient_manquants(patient)
        if manquants:
            return {"descripteurs": [], "manquants": manquants, "message": message_manquants(manquants), "data": None}
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        from routes.vidal_appels import appeler_vidal
        corps = construire_xml_posology_request(patient, payload.get("route"))
        data = await appeler_vidal(db, cfg, user, "POST", f"/{ressource}/{ident}/posology-descriptors",
                                   corps_xml=corps, patient_id=payload.get("patient_id"))
        if data.get("_erreur"):
            # VIDAL n'a rien retourné (ex. aucune posologie référencée) : message clair, pas de page d'erreur brute.
            return {"descripteurs": [], "manquants": [], "data": None,
                    "message": "VIDAL ne propose aucune posologie pour cet élément et ce patient (vous pouvez saisir la posologie vous-même)."}
        descripteurs = parser_descripteurs_posologie(data.get("raw"))
        return {"descripteurs": descripteurs, "manquants": [], "data": data,
                "message": None if descripteurs else "VIDAL ne propose aucune posologie pour cet élément et ce patient (vous pouvez saisir la posologie vous-même)."}

    async def _relayer_posologie(user, ressource: str, ident: str, route: Optional[str], indication: Optional[str]):
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        params: Dict[str, Any] = {}
        if route:
            params["route"] = route
        if indication:
            params["indication"] = indication
        path = f"/{ressource}/{ident}/posology-descriptors"
        data = await _call_and_log(cfg, "GET", path, params, user.get("email"))
        # Lot 15 — `_vidal_call` ne lève jamais sur une erreur VIDAL (>= 400) :
        # elle attache `_error` à `data` et renvoie 200, pour l'usage
        # diagnostic admin (voir vidal.py). Ce endpoint praticien-facing ne
        # doit PAS afficher cette page d'erreur VIDAL brute (HTML "Oops!...")
        # comme si c'était un résultat — remonté par l'utilisateur (capture
        # d'écran). On la convertit ici en vraie erreur HTTP.
        if isinstance(data, dict) and data.get("_error"):
            raise HTTPException(
                status_code=502,
                detail="VIDAL n'a pas retourné de posologie pour cet élément (endpoint expérimental).",
            )
        return {"experimental": True, "data": data}

    # Lot 39 — réutilisées par la vérification des ordonnances (équivalents présents en stock) :
    # mêmes contrôles d'accès VIDAL, même cache et même quota que les routes ci-dessus.
    async def rechercher(user: dict, q: str) -> dict:
        return await search_parsed(q=q, filter=None, forme=None, user=user)

    async def equivalents(user: dict, vmp_id: str) -> dict:
        return await vmp_equivalents(vmp_id=vmp_id, exclude_product_id=None, user=user)

    return {"rechercher": rechercher, "equivalents": equivalents}
