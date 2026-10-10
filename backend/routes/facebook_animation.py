"""Lot 96 — Liluvine anime la page Facebook de beAuthentik.

Demande du propriétaire (09/10/2026) : « Est-il possible pour Liluvine d'animer une page Facebook et y afficher des
posts ? Elle y publiera quelques photos de membres avec leur propre message. » Choix du propriétaire : « visage
masqué ; le texte est celui que le membre a mis dans sa bio, mais modéré par l'IA ».

Fonctionnement (pour un développeur WinDev : une « file de publications » avec une procédure planifiée) :
  1. Préparation (aux jours et à l'heure choisis, ou bouton « Préparer maintenant ») : SAWALI demande à la plateforme
     (beAuthentik) des membres CANDIDATS par le canal signé existant (même clé HMAC que les statistiques du lot 62).
     beAuthentik ne propose que des membres qui ont donné leur accord, avec leur photo MASQUÉE et leur bio.
  2. Modération : l'IA (Claude) relit chaque bio — refus si coordonnées, liens, propos sexuels, insultes,
     demandes d'argent… ; sinon corrections d'orthographe seulement, sans changer le sens.
  3. Chaque publication entre dans la file (collection fb_publications) :
       a_valider → (Valider) → publie | refuse   ;   refuse_ia (bio refusée par l'IA, gardée pour trace)
     Sans validation manuelle (réglage), elle est publiée directement.
  4. Publication sur la Page Facebook connectée dans SAWALI (routes/facebook.py) : photo masquée + légende ;
     beAuthentik est prévenue (le membre n'est plus proposé avant 60 jours).

Réglages (settings.global.fb_animation) : actif, plateforme (code de l'émetteur Liluvine), jours (0 = lundi),
heure « HH:MM » (heure de Ouagadougou = UTC), nombre de membres par préparation, validation manuelle,
modèle de légende, lien d'inscription.

Lot 97 — PAGE PROPRE À L'ANIMATION (« SAWALI a aussi besoin de sa page FB ») : la page de la plateforme (ex. page
beAuthentik) est choisie ici parmi les pages du compte Facebook connecté et rangée à part
(settings.global.fb_animation_page = {id, nom, jeton}) ; la « page active » de SAWALI reste celle de SAWALI.
Le jeton de la page n'est jamais renvoyé au navigateur.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, Depends, HTTPException

logger = logging.getLogger("sawali.facebook.animation")

CLE_REGLAGES = "fb_animation"
STATUTS = ("a_valider", "publie", "refuse", "refuse_ia", "echec")
LEGENDE_DEFAUT = ("💛 Rencontrez {prenom}{age_txt}{ville_txt}\n\n« {bio} »\n\n"
                  "Envie de faire sa connaissance ? Inscrivez-vous sur {lien} 👉 #beAuthentik #rencontre")
REGLAGES_DEFAUT: Dict[str, Any] = {
    "actif": False, "plateforme": "beauthentik", "jours": [1, 3, 5], "heure": "10:00",
    "nombre": 1, "validation_manuelle": True, "legende": LEGENDE_DEFAUT, "lien": "https://beauthentik.net",
}
PROMPT_MODERATION = (
    "Tu modères la bio d'un membre d'un site de rencontre sérieux (beAuthentik) avant sa publication PUBLIQUE sur "
    "la page Facebook du site, à côté de sa photo au visage masqué.\n"
    "REFUSE la bio si elle contient : numéro de téléphone, e-mail, adresse, lien, pseudo de réseau social, "
    "contenu sexuel ou suggestif, insulte, propos discriminatoires, demande d'argent ou de cadeaux, ou toute "
    "information permettant d'identifier la personne (nom de famille, lieu de travail précis).\n"
    "Sinon ACCEPTE-la en corrigeant seulement l'orthographe et la ponctuation, sans changer le sens ni le ton, "
    "en français, 400 caractères au plus, sans emoji ajouté.\n"
    'Réponds UNIQUEMENT par un JSON : {"conforme": true|false, "texte": "<bio corrigée ou vide>", '
    '"raison": "<raison courte si refusée>"}'
)


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _maintenant().isoformat()


# ---------------------------------------------------------------------------
# Fonctions isolées (remplacées par des imitations dans les tests)
# ---------------------------------------------------------------------------
async def appel_plateforme(emetteur: Dict[str, Any], corps: Dict[str, Any]) -> Dict[str, Any]:
    """Appel signé à la plateforme (même protocole que les statistiques du lot 62) ; renvoie la réponse JSON."""
    url = ((emetteur.get("url_stats") or "").strip() or (emetteur.get("url_retour") or "").strip())
    cle = (emetteur.get("secret") or "").encode()
    if not url or not cle:
        raise RuntimeError("plateforme sans adresse de retour ou sans clé")
    brut = json.dumps(corps, ensure_ascii=False)
    ts = str(int(time.time()))
    signature = hmac.new(cle, f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.post(url, content=brut.encode(), headers={
            "Content-Type": "application/json", "X-Emetteur": "sawali", "X-Timestamp": ts, "X-Signature": signature})
    if r.status_code >= 300:
        raise RuntimeError(f"plateforme : HTTP {r.status_code}")
    return r.json()


async def moderer_bio(bio: str) -> Dict[str, Any]:
    """Relecture de la bio par l'IA → {conforme, texte, raison}. En cas d'erreur : refus prudent (rien n'est publié)."""
    from ia_client import LlmChat, UserMessage, cle_ia
    if not cle_ia("anthropic"):
        return {"conforme": False, "texte": "", "raison": "clé de l'IA absente : modération impossible"}
    try:
        chat = LlmChat(session_id=f"fb-moderation-{uuid.uuid4()}", system_message=PROMPT_MODERATION,
                       initial_messages=[]).with_model("anthropic", "claude-haiku-4-5-20251001").with_params(max_tokens=600)
        texte = await chat.send_message(UserMessage(text=f"Bio :\n{bio[:600]}"))
        return lire_avis(texte)
    except Exception as exc:  # noqa: BLE001
        return {"conforme": False, "texte": "", "raison": f"modération impossible ({type(exc).__name__})"}


async def publier_sur_facebook(db, texte: str, image_url: str) -> str:
    """Publication photo + légende sur la page de l'animation (lot 97), à défaut sur la page active de SAWALI ;
    renvoie l'identifiant du post."""
    from routes.facebook import _post_to_page
    s = await db.settings.find_one({"_id": "global"}) or {}
    page = s.get("fb_animation_page") or {}
    pid = (page.get("id") or s.get("facebook_page_id") or "").strip()
    jeton = (page.get("jeton") or s.get("facebook_page_access_token") or "").strip()
    if not pid or not jeton:
        raise RuntimeError("aucune page Facebook choisie pour l'animation (rubrique « 📣 Page Facebook animée par Liluvine »)")
    r = await _post_to_page(pid, jeton, texte, image_url)
    return str(r.get("post_id") or r.get("id") or "")


# ---------------------------------------------------------------------------
# Logique
# ---------------------------------------------------------------------------
def lire_avis(texte: str) -> Dict[str, Any]:
    """Avis JSON de l'IA (tolère un texte autour du JSON) ; refus si illisible."""
    debut, fin = (texte or "").find("{"), (texte or "").rfind("}")
    try:
        d = json.loads(texte[debut:fin + 1]) if debut >= 0 and fin > debut else {}
    except ValueError:
        d = {}
    conforme = d.get("conforme") is True and bool(str(d.get("texte") or "").strip())
    return {"conforme": conforme, "texte": str(d.get("texte") or "").strip()[:400],
            "raison": str(d.get("raison") or ("" if conforme else "avis de l'IA illisible"))[:200]}


def legende(modele: str, cand: Dict[str, Any], bio: str, lien: str) -> str:
    """Légende du post à partir du modèle (variables : {prenom} {age_txt} {ville_txt} {bio} {lien})."""
    age = cand.get("age")
    valeurs = {
        "prenom": cand.get("prenom") or "un membre", "age_txt": f", {age} ans" if age else "",
        "ville_txt": f", {cand['ville']}" if cand.get("ville") else "", "bio": bio, "lien": lien,
    }
    try:
        return (modele or LEGENDE_DEFAUT).format(**valeurs)[:2000]
    except (KeyError, ValueError, IndexError):
        return LEGENDE_DEFAUT.format(**valeurs)


def message_erreur_facebook(r) -> str:
    """Lot 99 — message clair à partir de l'erreur de Facebook (avant : « Lecture des pages impossible (400) »).
    Code 190 (ou sous-codes 458-467) = connexion expirée ou révoquée : il suffit de reconnecter le compte Facebook."""
    try:
        err = (r.json() or {}).get("error") or {}
    except Exception:  # noqa: BLE001
        err = {}
    code, sous_code = err.get("code"), err.get("error_subcode")
    if code == 190 or sous_code in (458, 459, 460, 463, 464, 467):
        return ("La connexion Facebook de SAWALI a expiré : cliquez « Reconnecter Facebook » puis, dans la fenêtre de "
                "Facebook, cochez aussi la page de la plateforme.")
    if code in (10, 200) or "permission" in str(err.get("message", "")).lower():
        return ("Facebook refuse l'accès à la liste des pages (autorisation pages_show_list) : cliquez « Reconnecter "
                "Facebook » et acceptez toutes les autorisations demandées.")
    detail = str(err.get("message") or "")[:200]
    return f"Lecture des pages Facebook impossible ({r.status_code}){' : ' + detail if detail else ''}"


async def pages_du_compte(db) -> List[Dict[str, Any]]:
    """Pages Facebook gérées par le compte connecté dans SAWALI (avec leur jeton : usage serveur uniquement)."""
    from routes.facebook import DEFAULT_TIMEOUT, FB_API_BASE
    s = await db.settings.find_one({"_id": "global"}) or {}
    jeton_utilisateur = (s.get("facebook_user_access_token") or "").strip()
    if not jeton_utilisateur:
        raise HTTPException(status_code=400, detail="Connectez d'abord le compte Facebook (rubrique Facebook des Paramètres)")
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as http:
        r = await http.get(f"{FB_API_BASE}/me/accounts", params={"access_token": jeton_utilisateur, "fields": "id,name,access_token"})
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=message_erreur_facebook(r))
    return [{"id": p.get("id"), "nom": p.get("name"), "jeton": p.get("access_token")} for p in r.json().get("data", [])]


async def reglages(db) -> Dict[str, Any]:
    s = await db.settings.find_one({"_id": "global"}, {CLE_REGLAGES: 1}) or {}
    return {**REGLAGES_DEFAUT, **(s.get(CLE_REGLAGES) or {})}


async def preparer(db, declencheur: str = "manuel") -> Dict[str, Any]:
    """Demande des candidats à la plateforme, modération de leur bio, entrée dans la file (ou publication directe)."""
    regl = await reglages(db)
    emetteur = await db.liluvine_emetteurs.find_one({"code": regl["plateforme"]}, {"_id": 0})
    if not emetteur:
        raise HTTPException(status_code=400, detail=f"Plateforme « {regl['plateforme']} » inconnue (émetteurs Liluvine)")
    nombre = max(1, min(int(regl.get("nombre") or 1), 5))
    # On en demande davantage : les membres déjà dans la file ou refusés par l'IA sont sautés
    rep = await appel_plateforme(emetteur, {"type": "facebook_candidats", "nombre": nombre * 3})
    deja = set(await db.fb_publications.distinct("membre_id", {"plateforme": regl["plateforme"],
                                                               "statut": {"$in": ["a_valider", "refuse_ia", "refuse"]}}))
    crees: List[Dict[str, Any]] = []
    for cand in (rep.get("candidats") or []):
        if len([c for c in crees if c["statut"] != "refuse_ia"]) >= nombre:
            break
        if not isinstance(cand, dict) or not cand.get("membre_id") or not cand.get("photo_url") or cand["membre_id"] in deja:
            continue
        avis = await moderer_bio(str(cand.get("bio") or ""))
        doc = {
            "id": str(uuid.uuid4()), "plateforme": regl["plateforme"], "membre_id": cand["membre_id"],
            "prenom": cand.get("prenom"), "image_url": cand["photo_url"], "bio_origine": cand.get("bio"),
            "texte": legende(regl.get("legende"), cand, avis["texte"], regl.get("lien") or "") if avis["conforme"] else "",
            "avis_ia": avis, "statut": "a_valider" if avis["conforme"] else "refuse_ia",
            "cree_le": _iso(), "declencheur": declencheur,
        }
        await db.fb_publications.insert_one(dict(doc))
        crees.append(doc)
        if avis["conforme"] and not regl.get("validation_manuelle"):
            doc.update(await publier(db, doc["id"], "auto"))
    return {"crees": len(crees), "publications": [{k: v for k, v in c.items() if k != "_id"} for c in crees]}


async def publier(db, pid: str, par: str) -> Dict[str, Any]:
    """Publie une publication de la file sur Facebook et prévient la plateforme."""
    pub = await db.fb_publications.find_one({"id": pid}, {"_id": 0})
    if not pub:
        raise HTTPException(status_code=404, detail="Publication introuvable")
    if pub["statut"] not in ("a_valider", "echec"):
        raise HTTPException(status_code=409, detail="Cette publication n'est plus à publier")
    try:
        post_id = await publier_sur_facebook(db, pub["texte"], pub["image_url"])
    except Exception as exc:  # noqa: BLE001
        maj = {"statut": "echec", "erreur": str(getattr(exc, "detail", exc))[:300], "tente_le": _iso()}
        await db.fb_publications.update_one({"id": pid}, {"$set": maj})
        return maj
    maj = {"statut": "publie", "post_id": post_id, "publie_le": _iso(), "publie_par": par, "erreur": None}
    await db.fb_publications.update_one({"id": pid}, {"$set": maj})
    try:   # la plateforme note la publication (le membre n'est plus proposé avant 60 jours)
        emetteur = await db.liluvine_emetteurs.find_one({"code": pub["plateforme"]}, {"_id": 0})
        if emetteur:
            await appel_plateforme(emetteur, {"type": "facebook_publie", "membre_id": pub["membre_id"], "post_id": post_id})
    except Exception as exc:  # noqa: BLE001 — non bloquant
        logger.warning("[fb_animation] plateforme non prévenue : %s", exc)
    return maj


def doit_preparer(regl: Dict[str, Any], maintenant: datetime) -> bool:
    """Vrai si c'est un jour choisi, l'heure est passée, et rien n'a encore été préparé aujourd'hui."""
    if not regl.get("actif") or maintenant.weekday() not in (regl.get("jours") or []):
        return False
    try:
        h, m = (int(x) for x in str(regl.get("heure") or "10:00").split(":")[:2])
    except ValueError:
        h, m = 10, 0
    if (maintenant.hour, maintenant.minute) < (h, m):
        return False
    return regl.get("dernier_jour") != maintenant.date().isoformat()


async def tick(db) -> None:
    """Appelée toutes les 5 minutes par le planificateur : préparation automatique aux jours/heure choisis."""
    regl = await reglages(db)
    maintenant = _maintenant()
    if not doit_preparer(regl, maintenant):
        return
    await db.settings.update_one({"_id": "global"}, {"$set": {f"{CLE_REGLAGES}.dernier_jour": maintenant.date().isoformat()}},
                                 upsert=True)
    try:
        await preparer(db, "planifie")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fb_animation] préparation planifiée en échec : %s", exc)


# ---------------------------------------------------------------------------
# Routes d'administration
# ---------------------------------------------------------------------------
def attach_facebook_animation_routes(*, api, db, get_current_admin):

    @api.get("/admin/facebook/animation", tags=["Admin — Facebook"])
    async def lire(statut: Optional[str] = None, _: dict = Depends(get_current_admin)):
        """Réglages, état de la Page connectée et file des publications (les 50 plus récentes)."""
        s = await db.settings.find_one({"_id": "global"}) or {}
        filtre = {"statut": statut} if statut in STATUTS else {}
        pubs = await db.fb_publications.find(filtre, {"_id": 0}).sort("cree_le", -1).to_list(50)
        propre = s.get("fb_animation_page") or {}
        page = ({"connectee": True, "nom": propre.get("nom") or propre.get("id"), "propre": True} if propre.get("jeton") else
                {"connectee": bool(s.get("facebook_page_access_token")), "nom": s.get("facebook_page_name") or "", "propre": False})
        return {"reglages": await reglages(db), "publications": pubs, "page": page,
                "plateformes": [e["code"] async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "code": 1})]}

    @api.get("/admin/facebook/animation/pages", tags=["Admin — Facebook"])
    async def lister_pages(_: dict = Depends(get_current_admin)):
        """Lot 97 — pages du compte Facebook connecté (identifiant et nom seulement : jamais les jetons)."""
        return {"pages": [{"id": p["id"], "nom": p["nom"]} for p in await pages_du_compte(db)]}

    @api.put("/admin/facebook/animation/page", tags=["Admin — Facebook"])
    async def choisir_page(corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        """Lot 97 — page de l'animation (ex. page beAuthentik), distincte de la page active de SAWALI.
        Le serveur relit le jeton de la page auprès de Facebook (le navigateur ne le voit jamais)."""
        pid = str(corps.get("page_id") or "").strip()
        if not pid:   # page_id vide : retour à la page active de SAWALI
            await db.settings.update_one({"_id": "global"}, {"$unset": {"fb_animation_page": ""}})
            return {"ok": True, "page": None}
        page = next((p for p in await pages_du_compte(db) if p["id"] == pid), None)
        if not page or not page.get("jeton"):
            raise HTTPException(status_code=404, detail="Page introuvable dans le compte Facebook connecté")
        await db.settings.update_one({"_id": "global"}, {"$set": {"fb_animation_page": {
            "id": page["id"], "nom": page["nom"], "jeton": page["jeton"], "choisie_le": _iso(), "choisie_par": user.get("email")}}},
            upsert=True)
        return {"ok": True, "page": {"id": page["id"], "nom": page["nom"]}}

    @api.put("/admin/facebook/animation/reglages", tags=["Admin — Facebook"])
    async def enregistrer(corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        regl = await reglages(db)
        for cle in ("actif", "validation_manuelle"):
            if cle in corps:
                regl[cle] = bool(corps[cle])
        if "jours" in corps:
            regl["jours"] = sorted({int(j) for j in corps["jours"] if str(j).isdigit() and 0 <= int(j) <= 6})
        if "heure" in corps:
            h = str(corps["heure"] or "")
            if len(h) != 5 or h[2] != ":" or not (h[:2].isdigit() and h[3:].isdigit()) or int(h[:2]) > 23 or int(h[3:]) > 59:
                raise HTTPException(status_code=422, detail="Heure au format HH:MM")
            regl["heure"] = h
        if "nombre" in corps:
            regl["nombre"] = max(1, min(int(corps["nombre"] or 1), 5))
        for cle, maxi in (("plateforme", 40), ("lien", 200), ("legende", 2000)):
            if cle in corps and str(corps[cle] or "").strip():
                regl[cle] = str(corps[cle]).strip()[:maxi]
        regl["modifie_par"], regl["modifie_le"] = user.get("email"), _iso()
        await db.settings.update_one({"_id": "global"}, {"$set": {CLE_REGLAGES: regl}}, upsert=True)
        return regl

    @api.post("/admin/facebook/animation/preparer", tags=["Admin — Facebook"])
    async def preparer_maintenant(user: dict = Depends(get_current_admin)):
        try:
            return await preparer(db, f"manuel:{user.get('email')}")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Préparation impossible : {exc}")

    @api.put("/admin/facebook/animation/publications/{pid}", tags=["Admin — Facebook"])
    async def modifier_texte(pid: str, corps: Dict[str, Any] = Body(...), _: dict = Depends(get_current_admin)):
        """Retouche de la légende avant validation."""
        texte = str(corps.get("texte") or "").strip()[:2000]
        if not texte:
            raise HTTPException(status_code=422, detail="Légende vide")
        r = await db.fb_publications.update_one({"id": pid, "statut": {"$in": ["a_valider", "echec"]}}, {"$set": {"texte": texte}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Publication introuvable ou déjà traitée")
        return {"ok": True}

    @api.post("/admin/facebook/animation/publications/{pid}/valider", tags=["Admin — Facebook"])
    async def valider(pid: str, user: dict = Depends(get_current_admin)):
        """Valider = publier tout de suite sur la Page Facebook."""
        return await publier(db, pid, user.get("email") or "admin")

    @api.post("/admin/facebook/animation/publications/{pid}/refuser", tags=["Admin — Facebook"])
    async def refuser(pid: str, user: dict = Depends(get_current_admin)):
        r = await db.fb_publications.update_one({"id": pid, "statut": {"$in": ["a_valider", "echec"]}}, {
            "$set": {"statut": "refuse", "refuse_par": user.get("email"), "refuse_le": _iso()}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Publication introuvable ou déjà traitée")
        return {"ok": True}

    logger.info("[fb_animation] routes montées sous /api/admin/facebook/animation")
