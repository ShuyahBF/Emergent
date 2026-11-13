# lieux_balises.py — Lot 388 : « VOUS ÊTES ICI » — une page publique par lieu (rayon, couloir, salle…), ouverte par QR code ou par la balise la plus proche.
#
# Demande du propriétaire (14/11/2026) : les balises Estimote sont FIXES, exposées dans un lieu ; le visiteur utilise son téléphone pour être
# redirigé vers une page qui lui montre où il se trouve et ce qu'il peut y faire ou chercher. La gestion (création des lieux, contenu, balise
# associée, statistiques) est réservée à l'administrateur et au SUPERVISEUR ; la page du lieu, elle, est PUBLIQUE (le visiteur n'a pas de compte).
#
# COMMENT ÇA MARCHE (pour un développeur WinDev)
#   1. Le superviseur crée un LIEU : nom, texte d'information, liens utiles, et (facultatif) l'identifiant de la balise posée là
#      (celui que montre « Test balises Bluetooth » dans Personnel de maison : « ib:… », « mac:… » ou « ed:… »).
#      SAWALI lui donne un CODE court (6 caractères) = l'adresse publique  /lieu/<code>  et un QR code à imprimer et à coller près de la balise.
#   2. Le visiteur scanne le QR (tous les téléphones, rien à installer) → la page du lieu s'ouvre.
#   3. Option « Où suis-je ? » : l'application Android écoute les balises, prend la plus proche et demande à SAWALI de quel lieu il s'agit
#      (route de résolution ci-dessous), puis ouvre la même page. Même résultat, sans scanner.
#   4. Chaque ouverture est COMPTÉE (par jour, par provenance « qr » ou « app ») : les lieux les plus visités se lisent dans la liste de gestion.
#
# ROUTES (sous /api)
#   Publiques (aucun compte) :
#     GET  /lieux-balises/{code}              la page du lieu : nom, texte, liens, autres lieux du site
#     POST /lieux-balises/{code}/visite       compte une ouverture {"source": "qr" | "app"} (la page l'appelle UNE fois par session)
#     GET  /lieux-balises/{code}/qr.png       le QR code à imprimer
#     GET  /lieux-balises-resolution?balise=  quel lieu porte cette balise ? → {code, nom} (404 sinon) — utilisé par l'application
#   Gestion (administrateur ou superviseur) :
#     GET    /admin/lieux-balises             liste + statistiques de visites
#     POST   /admin/lieux-balises             crée un lieu
#     PUT    /admin/lieux-balises/{code}      modifie un lieu
#     DELETE /admin/lieux-balises/{code}      supprime un lieu
#
# STOCKAGE (sans nouvelle collection : le cluster MongoDB est plein) : un document par lieu dans `settings` (`_id` = « lieu-balise:<code> »).
# Seul point d'accès à la base : `_lire_lieu`, `_ecrire_lieu`, `_tous_les_lieux` (à remplacer pour une autre base).
from __future__ import annotations

import io
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request, Response

PREFIXE_ID = "lieu-balise:"
ALPHABET_CODE = "abcdefghjkmnpqrstuvwxyz23456789"      # sans caractères ambigus (0/o, 1/l/i)
LONGUEUR_CODE = 6
MAX_LIENS = 10
MAX_LIEUX = 300
JOURS_STATS = 30                                        # historique des visites gardé par lieu
SOURCES = ("qr", "app")
_CODE_RE = re.compile(r"^[a-z0-9]{4,12}$")
_BALISE_RE = re.compile(r"^[A-Za-z0-9:_\-.]{3,80}$")
_URL_RE = re.compile(r"^https?://[^\s]{3,500}$")


# =====================================================================================
# Logique pure (testée : tests/test_lot388_lieux_balises.py)
# =====================================================================================

def nouveau_code() -> str:
    """Code court aléatoire d'un lieu (6 caractères sans ambiguïté)."""
    return "".join(secrets.choice(ALPHABET_CODE) for _ in range(LONGUEUR_CODE))


def nettoyer_liens(liens: Any) -> List[Dict[str, str]]:
    """Liens utiles du lieu : {libelle, url}, http(s) seulement (jamais de javascript:), 10 au plus. Lève ValueError si un lien est invalide."""
    if liens in (None, ""):
        return []
    if not isinstance(liens, list):
        raise ValueError("« liens » doit être une liste")
    propres = []
    for item in liens[:MAX_LIENS]:
        if not isinstance(item, dict):
            raise ValueError("lien invalide")
        url = str(item.get("url") or "").strip()
        libelle = str(item.get("libelle") or "").strip()[:80]
        if not url and not libelle:
            continue
        if not _URL_RE.match(url):
            raise ValueError(f"adresse invalide : « {url[:40]} » (elle doit commencer par http:// ou https://)")
        propres.append({"libelle": libelle or url[:60], "url": url})
    return propres


def nettoyer_lieu(corps: Any, existant: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Valide et nettoie les champs saisis (nom, texte, liens, balise) ; sur une modification, les champs absents gardent leur valeur."""
    if not isinstance(corps, dict):
        raise ValueError("corps JSON attendu")
    base = existant or {}
    nom = str(corps.get("nom", base.get("nom", "")) or "").strip()[:80]
    if len(nom) < 2:
        raise ValueError("Donnez un nom au lieu (2 caractères au moins)")
    texte = str(corps.get("texte", base.get("texte", "")) or "").strip()[:2000]
    balise = str(corps.get("balise", base.get("balise", "")) or "").strip()
    if balise and not _BALISE_RE.match(balise):
        raise ValueError("Identifiant de balise invalide (3 à 80 caractères : lettres, chiffres, « : », « - », « _ », « . »)")
    liens = nettoyer_liens(corps["liens"]) if "liens" in corps else base.get("liens") or []
    return {"nom": nom, "texte": texte, "balise": balise or None, "liens": liens}


def jour_de(maintenant: float) -> str:
    """Jour (UTC) au format AAAA-MM-JJ d'un horodatage."""
    return datetime.fromtimestamp(maintenant, timezone.utc).strftime("%Y-%m-%d")


def compter_visite(lieu: Dict[str, Any], source: str, maintenant: float) -> None:
    """Ajoute une visite au lieu : compteur total, par source, et par jour (les jours de plus de 30 jours sont supprimés)."""
    source = source if source in SOURCES else "qr"
    lieu["visites_total"] = int(lieu.get("visites_total") or 0) + 1
    par_source = lieu.setdefault("visites_sources", {})
    par_source[source] = int(par_source.get(source) or 0) + 1
    jours = lieu.setdefault("visites_jours", {})
    j = jour_de(maintenant)
    jours[j] = int(jours.get(j) or 0) + 1
    limite = jour_de(maintenant - JOURS_STATS * 86400)
    for ancien in [k for k in jours if k < limite]:
        del jours[ancien]


def visites_recentes(lieu: Dict[str, Any], jours: int, maintenant: float) -> int:
    """Nombre de visites des `jours` derniers jours (aujourd'hui compris)."""
    limite = jour_de(maintenant - (jours - 1) * 86400)
    return sum(int(n) for j, n in (lieu.get("visites_jours") or {}).items() if j >= limite)


def vue_gestion(lieu: Dict[str, Any], maintenant: float) -> Dict[str, Any]:
    """Un lieu tel qu'affiché dans l'écran de gestion (avec statistiques)."""
    return {"code": lieu["code"], "nom": lieu["nom"], "texte": lieu.get("texte") or "", "balise": lieu.get("balise"),
            "liens": lieu.get("liens") or [], "adresse": adresse_publique(lieu["code"]),
            "visites_total": int(lieu.get("visites_total") or 0), "visites_7j": visites_recentes(lieu, 7, maintenant),
            "visites_sources": lieu.get("visites_sources") or {}, "cree_le": lieu.get("cree_le")}


def vue_publique(lieu: Dict[str, Any], autres: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ce que voit le visiteur : jamais la balise, ni les statistiques. `autres` = autres lieux (nom + code) pour naviguer."""
    return {"code": lieu["code"], "nom": lieu["nom"], "texte": lieu.get("texte") or "", "liens": lieu.get("liens") or [],
            "autres": [{"code": a["code"], "nom": a["nom"]} for a in autres if a["code"] != lieu["code"]][:30]}


def trouver_par_balise(lieux: List[Dict[str, Any]], balise: str) -> Optional[Dict[str, Any]]:
    """Le lieu qui porte cette balise (comparaison sans tenir compte de la casse), ou None."""
    cible = (balise or "").strip().lower()
    if not cible:
        return None
    return next((l for l in lieux if (l.get("balise") or "").lower() == cible), None)


def adresse_publique(code: str) -> str:
    """Adresse imprimée dans le QR code : page publique du lieu."""
    site = (os.environ.get("FRONTEND_PUBLIC_URL") or "https://sawalismartsystems.com").rstrip("/")
    return f"{site}/lieu/{code}"


def png_qr(adresse: str) -> bytes:
    """QR code (PNG, correction d'erreur moyenne) de l'adresse, prêt à imprimer."""
    import qrcode
    img = qrcode.make(adresse, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    tampon = io.BytesIO()
    img.save(tampon, format="PNG")
    return tampon.getvalue()


# =====================================================================================
# Routes
# =====================================================================================

def setup_lieux_balises_routes(*, db, api, get_current_user, maintenant=lambda: datetime.now(timezone.utc).timestamp()) -> None:
    """Branche les routes du lot 388 (appelée depuis server_parts/p20). `maintenant` est remplaçable par les tests."""
    from fastapi import Depends, HTTPException

    def _gestionnaire(user: dict) -> None:
        """Gestion des lieux : administrateur et superviseur (mêmes droits)."""
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur et au superviseur")

    # ---- Seul point d'accès à la base ----
    async def _lire_lieu(code: str) -> Optional[Dict[str, Any]]:
        return await db.settings.find_one({"_id": PREFIXE_ID + code}) if _CODE_RE.match(code or "") else None

    async def _ecrire_lieu(lieu: Dict[str, Any]) -> None:
        await db.settings.replace_one({"_id": lieu["_id"]}, lieu, upsert=True)

    async def _tous_les_lieux() -> List[Dict[str, Any]]:
        return [l async for l in db.settings.find({"_id": {"$regex": "^" + re.escape(PREFIXE_ID)}})]

    async def _lieu_ou_404(code: str) -> Dict[str, Any]:
        lieu = await _lire_lieu(code)
        if not lieu:
            raise HTTPException(status_code=404, detail="Lieu introuvable")
        return lieu

    async def _verifier_balise_libre(balise: Optional[str], sauf_code: Optional[str] = None) -> None:
        """Une balise ne peut marquer qu'un seul lieu (sinon l'application ne saurait pas lequel ouvrir)."""
        autre = trouver_par_balise([l for l in await _tous_les_lieux() if l["code"] != sauf_code], balise or "")
        if autre:
            raise HTTPException(status_code=409, detail=f"Cette balise marque déjà le lieu « {autre['nom']} »")

    # ------------------------------------------------------------------ publiques
    @api.get("/lieux-balises-resolution", tags=["Lieux (balises) — public"])
    async def resolution(balise: str = ""):
        """Application « Où suis-je ? » : quel lieu porte cette balise ? Ne révèle que le code et le nom."""
        lieu = trouver_par_balise(await _tous_les_lieux(), balise)
        if not lieu:
            raise HTTPException(status_code=404, detail="Aucun lieu n'est associé à cette balise")
        return {"code": lieu["code"], "nom": lieu["nom"]}

    @api.get("/lieux-balises/{code}", tags=["Lieux (balises) — public"])
    async def page_lieu(code: str):
        lieu = await _lieu_ou_404(code)
        return vue_publique(lieu, await _tous_les_lieux())

    @api.post("/lieux-balises/{code}/visite", tags=["Lieux (balises) — public"])
    async def visite(code: str, request: Request):
        """Compte une ouverture de la page (source « qr » ou « app »). Jamais d'erreur visible pour le visiteur."""
        lieu = await _lieu_ou_404(code)
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            corps = {}
        compter_visite(lieu, str((corps or {}).get("source") or "qr") if isinstance(corps, dict) else "qr", maintenant())
        await _ecrire_lieu(lieu)
        return {"ok": True}

    @api.get("/lieux-balises/{code}/qr.png", tags=["Lieux (balises) — public"])
    async def qr(code: str):
        await _lieu_ou_404(code)
        return Response(content=png_qr(adresse_publique(code)), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})

    # ------------------------------------------------------------------ gestion (administrateur, superviseur)
    @api.get("/admin/lieux-balises", tags=["Lieux (balises) — gestion"])
    async def lister(user: dict = Depends(get_current_user)):
        _gestionnaire(user)
        maint = maintenant()
        lieux = sorted((vue_gestion(l, maint) for l in await _tous_les_lieux()), key=lambda l: l["nom"].lower())
        return {"lieux": lieux, "total_visites": sum(l["visites_total"] for l in lieux)}

    @api.post("/admin/lieux-balises", tags=["Lieux (balises) — gestion"])
    async def creer(request: Request, user: dict = Depends(get_current_user)):
        _gestionnaire(user)
        try:
            champs = nettoyer_lieu(await request.json())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        existants = await _tous_les_lieux()
        if len(existants) >= MAX_LIEUX:
            raise HTTPException(status_code=409, detail=f"{MAX_LIEUX} lieux au plus")
        await _verifier_balise_libre(champs["balise"])
        codes = {l["code"] for l in existants}
        code = nouveau_code()
        while code in codes:
            code = nouveau_code()
        lieu = {"_id": PREFIXE_ID + code, "code": code, **champs, "visites_total": 0, "visites_sources": {}, "visites_jours": {},
                "cree_le": datetime.fromtimestamp(maintenant(), timezone.utc).isoformat()}
        await _ecrire_lieu(lieu)
        return vue_gestion(lieu, maintenant())

    @api.put("/admin/lieux-balises/{code}", tags=["Lieux (balises) — gestion"])
    async def modifier(code: str, request: Request, user: dict = Depends(get_current_user)):
        _gestionnaire(user)
        lieu = await _lieu_ou_404(code)
        try:
            champs = nettoyer_lieu(await request.json(), lieu)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        await _verifier_balise_libre(champs["balise"], sauf_code=code)
        lieu.update(champs)
        await _ecrire_lieu(lieu)
        return vue_gestion(lieu, maintenant())

    @api.delete("/admin/lieux-balises/{code}", tags=["Lieux (balises) — gestion"])
    async def supprimer(code: str, user: dict = Depends(get_current_user)):
        _gestionnaire(user)
        await _lieu_ou_404(code)
        await db.settings.delete_one({"_id": PREFIXE_ID + code})
        return {"ok": True}
