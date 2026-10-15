"""Lot 192 — Publier un carrousel WhatsApp sur une Page Facebook CHOISIE avant toute publication.

Demande du propriétaire : « Ne peut-on pas choisir la page avant toute publication ? Ainsi je peux remplacer les images
sur chacune des pages. » Un carrousel WhatsApp est un modèle de message propre à WhatsApp : il ne peut pas être posé tel
quel sur Facebook. SAWALI en fait une PUBLICATION de Page :
  - mode « photos » : les images des cartes (chacune remplaçable) forment une publication à plusieurs photos, avec le
    texte des cartes et le lien de la page de présentation ;
  - mode « lien »  : une publication avec le seul lien de la page de présentation (aperçu fourni par Facebook).
La Page est choisie parmi les Pages du compte Facebook connecté dans SAWALI (rubrique Facebook des Paramètres) ; le jeton de
la Page reste sur le serveur, jamais renvoyé au navigateur. Chaque publication est consignée sur l'envoi
(`carrousel_campagnes.publications_facebook`) : aucune nouvelle collection.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, Depends, HTTPException

logger = logging.getLogger("sawali.carrousel.facebook")

MAX_PHOTOS = 10            # limite d'une publication Facebook à plusieurs photos
MODES = ("photos", "lien")


def url_publique(url: Any) -> bool:
    """Facebook télécharge l'image lui-même : adresse absolue http / https obligatoire."""
    return isinstance(url, str) and url.strip().startswith(("https://", "http://"))


def images_retenues(cartes: List[Dict[str, Any]], remplacements: Any) -> List[str]:
    """Adresses des images publiées : celle de chaque carte, SAUF si une image de remplacement valide est donnée pour cette
    position. Les cartes sans image publique sont ignorées ; 10 images au plus. Fonction pure."""
    rempl = list(remplacements or [])
    sortie: List[str] = []
    for i, carte in enumerate(cartes or []):
        choix = rempl[i] if i < len(rempl) else None
        url = choix if url_publique(choix) else (carte or {}).get("image_url")
        if url_publique(url):
            sortie.append(str(url).strip())
    return sortie[:MAX_PHOTOS]


def texte_publication(message: str, cartes: List[Dict[str, Any]], lien: str, avec_cartes: bool) -> str:
    """Légende de la publication : le message, puis (mode photos) une ligne par carte, puis le lien de présentation. Pure."""
    blocs = [(message or "").strip()]
    if avec_cartes:
        lignes = []
        for i, c in enumerate(cartes or [], start=1):
            titre, texte = str((c or {}).get("titre") or "").strip(), str((c or {}).get("texte") or "").strip()
            if titre or texte:
                lignes.append(f"{i}. {titre}" + (f" — {texte}" if titre and texte else texte))
        if lignes:
            blocs.append("\n".join(lignes))
    if (lien or "").strip():
        blocs.append(f"👉 Tout voir : {lien.strip()}")
    return "\n\n".join(b for b in blocs if b)[:6000]


async def _page_choisie(db, page_id: str) -> Dict[str, Any]:
    """La Page demandée parmi celles du compte connecté (avec son jeton, usage serveur uniquement)."""
    from routes.facebook_animation import pages_du_compte
    for p in await pages_du_compte(db):
        if str(p.get("id")) == str(page_id):
            if not p.get("jeton"):
                raise HTTPException(status_code=400, detail="Facebook n'a pas donné l'accès à cette Page : reconnectez le compte et cochez-la")
            return p
    raise HTTPException(status_code=404, detail="Cette Page n'est pas gérée par le compte Facebook connecté")


async def _graph_post(chemin: str, donnees: Dict[str, Any]) -> Dict[str, Any]:
    from routes.facebook import FB_API_BASE
    from routes.facebook_animation import message_erreur_facebook
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(f"{FB_API_BASE}/{chemin}", data=donnees)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=message_erreur_facebook(r))
    return r.json()


async def publier(db, campagne: Dict[str, Any], page_id: str, message: str, mode: str, remplacements: Any, lien: str,
                  par: str) -> Dict[str, Any]:
    """Publie le carrousel sur la Page choisie et consigne la publication sur l'envoi. → {post_id, url, page, nb_images}."""
    if mode not in MODES:
        raise HTTPException(status_code=422, detail="Mode inconnu : « photos » ou « lien »")
    page = await _page_choisie(db, page_id)
    jeton = page["jeton"]
    cartes = campagne.get("cartes") or []
    lien = (lien or "").strip()
    if lien and not url_publique(lien):
        raise HTTPException(status_code=422, detail="Le lien doit commencer par http:// ou https://")
    nb_images = 0
    if mode == "photos":
        urls = images_retenues(cartes, remplacements)
        if not urls:
            raise HTTPException(status_code=422, detail="Aucune image publique : ajoutez ou remplacez au moins une image")
        corps: Dict[str, Any] = {"message": texte_publication(message, cartes, lien, True), "access_token": jeton}
        for i, u in enumerate(urls):
            # photo envoyée non publiée, puis rattachée à la publication
            photo = await _graph_post(f"{page['id']}/photos", {"url": u, "published": "false", "access_token": jeton})
            corps[f"attached_media[{i}]"] = json.dumps({"media_fbid": photo.get("id")})
        nb_images = len(urls)
        res = await _graph_post(f"{page['id']}/feed", corps)
    else:
        if not lien:
            raise HTTPException(status_code=422, detail="Le mode « lien » demande le lien de la page de présentation")
        res = await _graph_post(f"{page['id']}/feed", {"message": texte_publication(message, cartes, "", False),
                                                       "link": lien, "access_token": jeton})
    post_id = str(res.get("id") or res.get("post_id") or "")
    trace = {"id": uuid.uuid4().hex, "page_id": str(page["id"]), "page_nom": page.get("nom"), "post_id": post_id,
             "mode": mode, "nb_images": nb_images, "par": par, "le": datetime.now(timezone.utc).isoformat()}
    await db.carrousel_campagnes.update_one({"id": campagne["id"]}, {"$push": {"publications_facebook": trace}})
    return {**trace, "url": f"https://www.facebook.com/{post_id}" if post_id else ""}


def attach_carrousel_facebook_routes(*, api, db, get_current_admin):
    """Routes d'administration (la publication sur une Page est réservée à l'administration)."""

    @api.get("/admin/carrousel/facebook/pages", tags=["Admin — Carrousel WhatsApp"])
    async def pages_facebook(_: dict = Depends(get_current_admin)):
        """Pages du compte Facebook connecté (identifiant et nom seulement : jamais de jeton)."""
        from routes.facebook_animation import pages_du_compte
        return {"pages": [{"id": p["id"], "nom": p.get("nom")} for p in await pages_du_compte(db)]}

    @api.get("/admin/carrousel/facebook/{cid}/publications", tags=["Admin — Carrousel WhatsApp"])
    async def publications_facebook(cid: str, _: dict = Depends(get_current_admin)):
        c = await db.carrousel_campagnes.find_one({"id": cid}, {"_id": 0, "publications_facebook": 1}) or {}
        return {"publications": [{**p, "url": f"https://www.facebook.com/{p['post_id']}" if p.get("post_id") else ""}
                                 for p in reversed(c.get("publications_facebook") or [])]}

    @api.post("/admin/carrousel/facebook/{cid}/publier", tags=["Admin — Carrousel WhatsApp"])
    async def publier_facebook(cid: str, corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        """Publie l'envoi `cid` sur la Page choisie : {page_id, mode, message, images: [url|null…], lien}."""
        c = await db.carrousel_campagnes.find_one({"id": cid}, {"_id": 0, "id": 1, "cartes": 1, "message": 1, "id_public": 1})
        if not c:
            raise HTTPException(status_code=404, detail="Envoi introuvable")
        page_id = str(corps.get("page_id") or "").strip()
        if not page_id:
            raise HTTPException(status_code=422, detail="Choisissez d'abord la Page Facebook")
        message = str(corps.get("message") if corps.get("message") is not None else c.get("message") or "")
        return await publier(db, c, page_id, message, str(corps.get("mode") or "photos"), corps.get("images"),
                             str(corps.get("lien") or ""), user.get("email") or user.get("id") or "admin")
