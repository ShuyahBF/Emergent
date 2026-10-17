"""Lot 237 — Résumés de la presse pour les plateformes (Paiement Mobile…) : l'IA résume des articles déjà collectés.

Demande du propriétaire (17/10/2026) : « Pour les résumés de la presse, l'administrateur paramètre les liens. Chaque matin à 6 h
(heure paramétrable), un seul passage de collecte de tous ces liens et résumés. Les utilisateurs voient les résumés média par média,
avec le lien pour tout lire. »

Pour un développeur WinDev : la plateforme (Paiement Mobile) fait elle-même la COLLECTE des pages (une fois par jour) et envoie ici,
par la requête SIGNÉE habituelle, les titres et extraits d'UN média à la fois ; SAWALI ne fait que RÉSUMER (clé IA du serveur) et renvoie
un court résumé par article. Aucune page n'est lue par SAWALI, aucun résumé n'est gardé ici.

Route SIGNÉE (X-Emetteur, X-Timestamp, X-Signature) :
    POST /api/presse-plateformes/resumer  {media, articles: [{lien, titre, texte}]}  → {resumes: [{lien, resume}]}
Limites : 8 articles par appel, 2 500 caractères de texte par article, 40 appels par jour et par plateforme (maîtrise du coût IA).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.presse_plateformes")

# Résumeur de remplacement (tests) : async (media, articles) → texte brut JSON ; None = vrai client IA
_resumer: Optional[Callable] = None
APPELS_PAR_JOUR = 150
MAX_ARTICLES = 8
MAX_TEXTE = 2500


class ArticleIn(BaseModel):
    lien: str = Field(..., min_length=8, max_length=600)
    titre: str = Field(..., min_length=3, max_length=300)
    texte: str = Field("", max_length=MAX_TEXTE)


class ResumerIn(BaseModel):
    media: str = Field(..., min_length=2, max_length=80)
    articles: List[ArticleIn] = Field(..., min_length=1, max_length=MAX_ARTICLES)


def extraire_json(brut: str) -> Any:
    """Réponse de l'IA → JSON (retire les balises ``` éventuelles, sinon cherche le premier tableau/objet)."""
    t = (brut or "").strip()
    if t.startswith("```"):
        t = t.strip("`").lstrip("json").strip()
    try:
        return json.loads(t)
    except ValueError:
        m = re.search(r"(\[.*\]|\{.*\})", t, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except ValueError:
                pass
    return None


def resumes_valides(donnees: Any, liens: List[str]) -> Dict[str, str]:
    """Garde seulement les résumés qui correspondent à un lien envoyé (jamais d'article inventé), texte nettoyé et borné."""
    lignes = donnees.get("resumes") if isinstance(donnees, dict) else donnees
    out: Dict[str, str] = {}
    for x in lignes if isinstance(lignes, list) else []:
        if isinstance(x, dict) and x.get("lien") in liens and isinstance(x.get("resume"), str):
            r = re.sub(r"\s+", " ", x["resume"]).strip()[:600]
            if len(r) >= 20:
                out[x["lien"]] = r
    return out


async def resumer_ia(media: str, articles: List[ArticleIn]) -> str:
    from ia_client import LlmChat, UserMessage, cle_ia
    cle = cle_ia()
    if not cle:
        raise HTTPException(status_code=503, detail="Résumé indisponible pour le moment")
    blocs = "\n\n".join(f"LIEN: {a.lien}\nTITRE: {a.titre}\nEXTRAIT: {a.texte or '(non disponible)'}" for a in articles)
    consigne = (f"Média : {media}. Pour chaque article ci-dessous, écris un RÉSUMÉ NEUTRE en français de 2 à 3 phrases (350 caractères au plus), "
                "fidèle à l'extrait : n'ajoute aucun fait, aucun chiffre ni aucune opinion absents du texte. Si l'extrait manque, résume prudemment à partir du titre. "
                'Réponds uniquement par un tableau JSON : [{"lien": "...", "resume": "..."}], avec le lien copié à l\'identique.\n\n' + blocs)
    chat = LlmChat(api_key=cle, session_id=f"presse-{uuid.uuid4().hex[:8]}",
                   system_message="Tu es un journaliste de revue de presse. Tu réponds toujours en JSON valide, sans markdown.").with_model("anthropic", "claude-haiku-4-5-20251001")
    return await chat.send_message(UserMessage(text=consigne))


def make_presse_plateformes(*, db, outils: Any):
    router = APIRouter(tags=["Presse des plateformes (lot 237)"])

    @router.post("/presse-plateformes/resumer")
    async def resumer(request: Request):
        emetteur, corps = await outils.plateforme_signee(request)
        d = outils.lire(ResumerIn, corps)
        jour = datetime.now(timezone.utc).date().isoformat()
        # Plafond quotidien par plateforme (compteur incrémenté AVANT l'appel : un échec compte aussi, pour borner le coût)
        r = await db.presse_appels.find_one_and_update({"plateforme": emetteur["code"], "jour": jour}, {"$inc": {"n": 1}}, upsert=True, return_document=True)
        if (r or {}).get("n", 1) > APPELS_PAR_JOUR:
            raise HTTPException(status_code=429, detail="Limite quotidienne de résumés atteinte")
        try:
            brut = await (_resumer or resumer_ia)(d.media, d.articles)
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[presse] appel IA en échec")
            raise HTTPException(status_code=502, detail="Résumé indisponible pour le moment")
        resumes = resumes_valides(extraire_json(brut), [a.lien for a in d.articles])
        return {"resumes": [{"lien": lien, "resume": txt} for lien, txt in resumes.items()]}

    return router
