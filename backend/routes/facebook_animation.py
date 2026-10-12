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

Lot 132 — ANIMATION MULTI-PLATEFORMES (demande du propriétaire : « Publication Facebook pour ZandGo, adLyn et
bfmobility comme nous l'avons fait pour beAuthentik » ; choix : « Produits + annonces de lancement »).
  - Une configuration PAR PLATEFORME (settings.global.fb_animation_plateformes.<code>) : actif, page Facebook propre,
    jours et heure, nombre, validation manuelle, modèle de légende, lien.
  - Type de contenu selon la plateforme :
        membre   (beAuthentik)   : photo masquée + bio du membre, logique des lots 96-97 INCHANGÉE ;
        produit  (ZandGo, adLyn) : photo, nom, prix, lien de l'article ;
        vehicule (bfmobility)    : photo, nom, tarif, lien de la page du véhicule.
  - Modération par l'IA selon le type : pour un produit / véhicule, l'IA vérifie le texte (pas de coordonnées
    personnelles, pas de promesse trompeuse) et corrige l'orthographe ; elle n'écrit JAMAIS de prix (le prix vient
    toujours de la plateforme ; un montant ajouté par l'IA fait refuser la publication).
  - MIGRATION DOUCE de beAuthentik : ses anciens réglages (fb_animation) et sa page (fb_animation_page) restent lus
    tels quels ; une modification les recopie aussi à l'ancien emplacement (retour arrière possible). Aucune
    reprise de données n'est nécessaire au déploiement.
  - Une plateforme autre que beAuthentik ne publie JAMAIS sur la page de SAWALI : sans page propre, échec clair.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, Depends, HTTPException

logger = logging.getLogger("sawali.facebook.animation")

CLE_REGLAGES = "fb_animation"                     # anciens réglages (beAuthentik, lots 96-97)
CLE_PLATEFORMES = "fb_animation_plateformes"      # lot 132 : réglages par plateforme {code: {...}}
PLATEFORME_HISTORIQUE = "beauthentik"             # plateforme des lots 96-97 (migration douce)
CODE_VALIDE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,29}$")   # même règle que les codes des émetteurs Liluvine
STATUTS = ("a_valider", "publie", "refuse", "refuse_ia", "echec")
CONTENUS = ("membre", "produit", "vehicule")
LEGENDE_DEFAUT = ("💛 Rencontrez {prenom}{age_txt}{ville_txt}\n\n« {bio} »\n\n"
                  "Envie de faire sa connaissance ? Inscrivez-vous sur {lien} 👉 #beAuthentik #rencontre")
REGLAGES_DEFAUT: Dict[str, Any] = {
    "actif": False, "plateforme": "beauthentik", "jours": [1, 3, 5], "heure": "10:00",
    "nombre": 1, "validation_manuelle": True, "legende": LEGENDE_DEFAUT, "lien": "https://beauthentik.net",
}

# ---------------------------------------------------------------------------
# Lot 132 — profils des plateformes connues : nom affiché, type de contenu, légende et lien par défaut.
# Les légendes restent modifiables dans la rubrique (variables entre accolades ; une variable inconnue reste vide).
#   produit  : {nom} {prix_txt} {description} {lien_article} {boutique} {boutique_txt} {lien}
#   vehicule : {nom} {classe} {classe_txt} {tarif_txt} {description} {lien_article} {lien}
# ---------------------------------------------------------------------------
LEGENDE_ZANDGO = ("🛍️ {nom}\n\n{description}\n\n💰 {prix_txt}\n🚚 Importé pour vous et livré au Burkina Faso\n\n"
                  "👉 Commandez-le ici : {lien_article}\n\n"
                  "#ZandGo #BoutiqueEnLigne #Livraison #Ouagadougou #BurkinaFaso")
LEGENDE_ADLYN = ("🏪 {nom}{boutique_txt}\n\n{description}\n\n💰 {prix_txt}\n\n👉 Voir l'article : {lien_article}\n\n"
                 "Commerçant ? Ouvrez vous aussi votre vitrine sur {lien}\n\n"
                 "#adLyn #Commerce #Vitrine #AchatLocal #BurkinaFaso")
LEGENDE_BFMOBILITY = ("🚗 {nom}{classe_txt}\n\n{description}\n\n💰 {tarif_txt}\n\n👉 Réservez ce véhicule : {lien_article}\n\n"
                      "#bfmobility #Location #Transport #Chauffeur #Ouagadougou")
PROFILS: Dict[str, Dict[str, Any]] = {
    "beauthentik": {"nom": "beAuthentik", "contenu": "membre", "legende": LEGENDE_DEFAUT, "lien": "https://beauthentik.net"},
    "zandgo": {"nom": "ZandGo", "contenu": "produit", "legende": LEGENDE_ZANDGO, "lien": "https://zandgo.shop"},
    "adlyn": {"nom": "adLyn", "contenu": "produit", "legende": LEGENDE_ADLYN, "lien": "https://adlynservice.com"},
    "bfmobility": {"nom": "bfmobility", "contenu": "vehicule", "legende": LEGENDE_BFMOBILITY,
                   "lien": "https://bfmobility-frontend.onrender.com"},
}
# Profil d'une plateforme inconnue (ajoutée plus tard) : publication de produits
PROFIL_GENERIQUE: Dict[str, Any] = {"contenu": "produit", "lien": "",
                                    "legende": "{nom}\n\n{description}\n\n💰 {prix_txt}\n\n👉 {lien_article}"}
# Champs d'une configuration de plateforme (la page est rangée à part : son jeton ne sort jamais du serveur)
CHAMPS_CONFIG = ("actif", "jours", "heure", "nombre", "validation_manuelle", "legende", "lien", "contenu", "dernier_jour",
                 "modifie_par", "modifie_le")

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
# Lot 132 — modération d'un produit (ZandGo, adLyn) ou d'un véhicule (bfmobility)
PROMPT_MODERATION_PRODUIT = (
    "Tu relis la fiche d'un {genre} avant sa publication PUBLIQUE sur la page Facebook de la plateforme {plateforme}.\n"
    "REFUSE la fiche si le nom ou la description contient : numéro de téléphone, e-mail, adresse personnelle, lien, "
    "pseudo de réseau social, nom d'une personne privée, promesse trompeuse ou invérifiable (« garanti à vie », "
    "« le moins cher du pays », « 100 % gratuit », guérison, gain d'argent…), contenu choquant ou illégal.\n"
    "Sinon ACCEPTE-la en corrigeant seulement l'orthographe et la ponctuation, sans changer le sens, en français. "
    "La description fait 300 caractères au plus (raccourcis-la proprement si besoin ; elle peut rester vide).\n"
    "N'écris JAMAIS de prix, de montant ni de remise : le prix est ajouté ensuite par la plateforme.\n"
    'Réponds UNIQUEMENT par un JSON : {{"conforme": true|false, "nom": "<nom corrigé>", '
    '"description": "<description corrigée, éventuellement vide>", "raison": "<raison courte si refusée>"}}'
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


async def moderer_produit(nom: str, description: str, contenu: str, plateforme: str) -> Dict[str, Any]:
    """Lot 132 — relecture d'un produit / véhicule par l'IA → {conforme, nom, description, raison}.
    En cas d'erreur : refus prudent (rien n'est publié)."""
    from ia_client import LlmChat, UserMessage, cle_ia
    if not cle_ia("anthropic"):
        return {"conforme": False, "nom": "", "description": "", "raison": "clé de l'IA absente : modération impossible"}
    genre = "véhicule proposé à la location" if contenu == "vehicule" else "produit en vente"
    try:
        chat = LlmChat(session_id=f"fb-moderation-{uuid.uuid4()}",
                       system_message=PROMPT_MODERATION_PRODUIT.format(genre=genre, plateforme=plateforme),
                       initial_messages=[]).with_model("anthropic", "claude-haiku-4-5-20251001").with_params(max_tokens=700)
        texte = await chat.send_message(UserMessage(text=f"Nom :\n{nom[:200]}\n\nDescription :\n{description[:800]}"))
        return lire_avis_produit(texte, nom, description)
    except Exception as exc:  # noqa: BLE001
        return {"conforme": False, "nom": "", "description": "", "raison": f"modération impossible ({type(exc).__name__})"}


async def publier_sur_facebook(db, texte: str, image_url: str, plateforme: Optional[str] = None) -> str:
    """Publication photo + légende sur la page PROPRE de la plateforme ; renvoie l'identifiant du post.
    beAuthentik (plateforme historique, comportement des lots 96-97 inchangé) : à défaut de page propre, page active
    de SAWALI. Lot 132 : toute autre plateforme exige sa page propre (jamais la page de SAWALI)."""
    from routes.facebook import _post_to_page
    s = await db.settings.find_one({"_id": "global"}) or {}
    historique = _historique_de(s)
    code = plateforme or historique
    page = page_de(s, code)
    pid, jeton = (page.get("id") or "").strip(), (page.get("jeton") or "").strip()
    if not jeton and code == historique:
        pid = (s.get("facebook_page_id") or "").strip()
        jeton = (s.get("facebook_page_access_token") or "").strip()
    if not pid or not jeton:
        raise RuntimeError(f"aucune page Facebook choisie pour {nom_plateforme(code)} "
                           "(rubrique « 📣 Page Facebook animée par Liluvine »)")
    r = await _post_to_page(pid, jeton, texte, image_url)
    return str(r.get("post_id") or r.get("id") or "")


# ---------------------------------------------------------------------------
# Lecture des avis de l'IA et garde-fous
# ---------------------------------------------------------------------------
def _json_dans(texte: str) -> Dict[str, Any]:
    """Premier objet JSON trouvé dans la réponse de l'IA ({} si illisible)."""
    debut, fin = (texte or "").find("{"), (texte or "").rfind("}")
    try:
        d = json.loads(texte[debut:fin + 1]) if debut >= 0 and fin > debut else {}
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


def lire_avis(texte: str) -> Dict[str, Any]:
    """Avis JSON de l'IA (tolère un texte autour du JSON) ; refus si illisible."""
    d = _json_dans(texte)
    conforme = d.get("conforme") is True and bool(str(d.get("texte") or "").strip())
    return {"conforme": conforme, "texte": str(d.get("texte") or "").strip()[:400],
            "raison": str(d.get("raison") or ("" if conforme else "avis de l'IA illisible"))[:200]}


# Lot 132 — garde-fous indépendants de l'IA (règles fixes, testables)
# Téléphone : 8 chiffres, collés ou par groupes de 2 avec le même séparateur (ex. 70 12 34 56), indicatif facultatif
_TELEPHONE = re.compile(r"(?<![\d])(?:\+|00)?(?:\d{3}[\s.-]?)?\d{2}([\s.-]?)\d{2}\1\d{2}\1\d{2}(?![\d])")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_LIEN = re.compile(r"(?:https?://|www\.|wa\.me/)", re.I)
# Montant suivi d'une devise (F CFA, FCFA, francs, XOF, €, $, USD…)
_MONTANT = re.compile(r"(\d[\d\s.,]*?)\s*(?:f\s?cfa|fcfa|cfa|francs?|xof|euros?|eur|usd|€|\$)(?![a-z])", re.I)


def coordonnees_detectees(texte: str) -> str:
    """Raison du refus si le texte contient un téléphone, un e-mail ou un lien ; sinon chaîne vide."""
    if _EMAIL.search(texte or ""):
        return "adresse e-mail dans le texte"
    if _LIEN.search(texte or ""):
        return "lien dans le texte"
    if _TELEPHONE.search(texte or ""):
        return "numéro de téléphone dans le texte"
    return ""


def _montants(texte: str) -> set:
    """Montants écrits dans un texte (chiffres seuls), ex. « 12 500 F CFA » → {"12500"}."""
    sortie = set()
    for m in _MONTANT.finditer(texte or ""):
        chiffres = re.sub(r"\D", "", m.group(1))
        if chiffres:
            sortie.add(chiffres)
    return sortie


def lire_avis_produit(texte: str, nom_origine: str, description_origine: str) -> Dict[str, Any]:
    """Avis JSON de l'IA pour un produit / véhicule (lot 132) ; refus si illisible, si l'IA a écrit un prix absent
    de la fiche d'origine, ou si une coordonnée personnelle subsiste."""
    d = _json_dans(texte)
    nom = str(d.get("nom") or "").strip()[:150]
    description = str(d.get("description") or "").strip()[:300]
    conforme = d.get("conforme") is True and bool(nom)
    raison = str(d.get("raison") or ("" if conforme else "avis de l'IA illisible"))[:200]
    if conforme and _montants(f"{nom} {description}") - _montants(f"{nom_origine} {description_origine}"):
        conforme, raison = False, "l'IA a ajouté un prix : publication refusée par prudence"
    if conforme:
        detecte = coordonnees_detectees(f"{nom}\n{description}")
        if detecte:
            conforme, raison = False, detecte
    return {"conforme": conforme, "nom": nom if conforme else "", "description": description if conforme else "",
            "raison": "" if conforme else raison}


# ---------------------------------------------------------------------------
# Légendes
# ---------------------------------------------------------------------------
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


class _Valeurs(dict):
    """Variables d'une légende : une variable inconnue du modèle est remplacée par du vide (jamais d'erreur)."""

    def __missing__(self, cle):
        return ""


def prix_txt(cand: Dict[str, Any]) -> str:
    """Prix affiché : celui de la plateforme (texte prêt, sinon montant en F CFA) ; jamais inventé."""
    if str(cand.get("prix_txt") or "").strip():
        return str(cand["prix_txt"]).strip()[:80]
    try:
        n = int(round(float(cand.get("prix_fcfa"))))
    except (TypeError, ValueError):
        return "Prix sur demande"
    return f"{n:,}".replace(",", " ") + " F CFA" if n > 0 else "Prix sur demande"


def legende_element(modele: str, defaut: str, cand: Dict[str, Any], avis: Dict[str, Any], lien: str) -> str:
    """Lot 132 — légende d'un produit / véhicule : nom et description relus par l'IA, prix et lien de la plateforme."""
    boutique = str(cand.get("boutique") or "").strip()[:80]
    classe = str(cand.get("classe") or "").strip()[:60]
    valeurs = _Valeurs(
        nom=avis.get("nom") or cand.get("nom") or "", description=avis.get("description") or "",
        prix_txt=prix_txt(cand), tarif_txt=str(cand.get("tarif_txt") or "").strip()[:120] or prix_txt(cand),
        lien_article=str(cand.get("lien") or lien or ""), lien=lien or "",
        boutique=boutique, boutique_txt=f" — chez {boutique}" if boutique else "",
        classe=classe, classe_txt=f" ({classe})" if classe else "",
    )
    try:
        texte = (modele or defaut).format_map(valeurs)
    except (ValueError, IndexError, AttributeError, KeyError):
        texte = defaut.format_map(valeurs)
    # Description vide : pas de lignes blanches en trop
    return re.sub(r"\n{3,}", "\n\n", texte).strip()[:2000]


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


# ---------------------------------------------------------------------------
# Lot 132 — réglages par plateforme (avec migration douce de beAuthentik)
# ---------------------------------------------------------------------------
def nom_plateforme(code: str) -> str:
    """Nom affiché d'une plateforme (ex. « ZandGo ») ; à défaut son code."""
    return (PROFILS.get(code) or {}).get("nom") or code


def _historique_de(s: Dict[str, Any]) -> str:
    """Code de la plateforme des lots 96-97 (celle des anciens réglages ; beauthentik par défaut)."""
    code = str((s.get(CLE_REGLAGES) or {}).get("plateforme") or PLATEFORME_HISTORIQUE).strip()
    return code if CODE_VALIDE.match(code) else PLATEFORME_HISTORIQUE


async def plateforme_historique(db) -> str:
    s = await db.settings.find_one({"_id": "global"}, {CLE_REGLAGES: 1}) or {}
    return _historique_de(s)


def page_de(s: Dict[str, Any], code: str) -> Dict[str, Any]:
    """Page propre d'une plateforme {id, nom, jeton} ({} si aucune). beAuthentik : à défaut, la page du lot 97."""
    page = ((s.get(CLE_PLATEFORMES) or {}).get(code) or {}).get("page") or {}
    if not page.get("jeton") and code == _historique_de(s):
        page = s.get("fb_animation_page") or {}
    return page if page.get("jeton") else {}


def config_de(s: Dict[str, Any], code: str) -> Dict[str, Any]:
    """Réglages complets d'une plateforme : profil par défaut, puis anciens réglages (beAuthentik, lots 96-97),
    puis réglages enregistrés au lot 132. Jamais le jeton de la page."""
    profil = PROFILS.get(code) or PROFIL_GENERIQUE
    regl: Dict[str, Any] = {**REGLAGES_DEFAUT, "legende": profil["legende"], "lien": profil["lien"],
                            "contenu": profil["contenu"]}
    if code == _historique_de(s):
        regl.update({k: v for k, v in (s.get(CLE_REGLAGES) or {}).items() if k in CHAMPS_CONFIG})
    regl.update({k: v for k, v in ((s.get(CLE_PLATEFORMES) or {}).get(code) or {}).items() if k in CHAMPS_CONFIG})
    if regl.get("contenu") not in CONTENUS:
        regl["contenu"] = profil["contenu"]
    regl["plateforme"] = code
    regl["nom"] = nom_plateforme(code)
    return regl


async def reglages(db, plateforme: Optional[str] = None) -> Dict[str, Any]:
    """Réglages d'une plateforme (par défaut : celle des lots 96-97, beAuthentik)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    return config_de(s, plateforme or _historique_de(s))


def codes_configures(s: Dict[str, Any]) -> List[str]:
    """Plateformes affichées : les profils connus, la plateforme historique et celles déjà réglées."""
    codes = list(PROFILS)
    for c in [_historique_de(s), *((s.get(CLE_PLATEFORMES) or {}).keys())]:
        if c not in codes and CODE_VALIDE.match(str(c)):
            codes.append(c)
    return codes


async def _enregistrer_config(db, code: str, regl: Dict[str, Any]) -> None:
    """Enregistre les réglages d'une plateforme ; pour beAuthentik, recopie aussi à l'ancien emplacement
    (fb_animation) : un retour arrière éventuel retrouverait les mêmes réglages."""
    propre = {k: v for k, v in regl.items() if k in CHAMPS_CONFIG}
    maj = {f"{CLE_PLATEFORMES}.{code}.{k}": v for k, v in propre.items()}
    if code == await plateforme_historique(db):
        maj.update({f"{CLE_REGLAGES}.{k}": v for k, v in propre.items() if k != "contenu"})
    await db.settings.update_one({"_id": "global"}, {"$set": maj}, upsert=True)


def _code_ou_422(code: Any) -> str:
    """Code de plateforme reçu du navigateur, contrôlé (minuscules, chiffres, - et _)."""
    code = str(code or "").strip().lower()
    if not CODE_VALIDE.match(code):
        raise HTTPException(status_code=422, detail="Code de plateforme invalide")
    return code


# ---------------------------------------------------------------------------
# Préparation et publication
# ---------------------------------------------------------------------------
def _ident(doc: Dict[str, Any]) -> str:
    """Identifiant de l'élément publié (membre beAuthentik, produit, véhicule)."""
    return str(doc.get("element_id") or doc.get("membre_id") or "")


def _url_publique(url: Any) -> bool:
    """Facebook télécharge l'image lui-même : l'adresse doit être absolue (http/https)."""
    return isinstance(url, str) and url.startswith(("https://", "http://"))


async def preparer(db, declencheur: str = "manuel", plateforme: Optional[str] = None) -> Dict[str, Any]:
    """Demande des candidats à la plateforme, modération par l'IA, entrée dans la file (ou publication directe)."""
    regl = await reglages(db, plateforme)
    code, contenu = regl["plateforme"], regl["contenu"]
    emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0})
    if not emetteur:
        raise HTTPException(status_code=400, detail=f"Plateforme « {code} » inconnue (émetteurs Liluvine)")
    nombre = max(1, min(int(regl.get("nombre") or 1), 5))
    # On en demande davantage : les éléments déjà dans la file ou refusés sont sautés
    rep = await appel_plateforme(emetteur, {"type": "facebook_candidats", "nombre": nombre * 3})
    filtre = {"plateforme": code, "statut": {"$in": ["a_valider", "refuse_ia", "refuse"]}}
    deja = (set(await db.fb_publications.distinct("membre_id", filtre))
            | set(await db.fb_publications.distinct("element_id", filtre)))
    crees: List[Dict[str, Any]] = []
    for cand in (rep.get("candidats") or []):
        if len([c for c in crees if c["statut"] != "refuse_ia"]) >= nombre:
            break
        if not isinstance(cand, dict):
            continue
        if contenu == "membre":
            # Lots 96-97 : membre de beAuthentik (photo masquée + bio), logique inchangée
            if not cand.get("membre_id") or not cand.get("photo_url") or cand["membre_id"] in deja:
                continue
            avis = await moderer_bio(str(cand.get("bio") or ""))
            doc = {
                "id": str(uuid.uuid4()), "plateforme": code, "membre_id": cand["membre_id"],
                "prenom": cand.get("prenom"), "image_url": cand["photo_url"], "bio_origine": cand.get("bio"),
                "texte": legende(regl.get("legende"), cand, avis["texte"], regl.get("lien") or "") if avis["conforme"] else "",
                "avis_ia": avis, "statut": "a_valider" if avis["conforme"] else "refuse_ia",
                "cree_le": _iso(), "declencheur": declencheur,
            }
        else:
            # Lot 132 : produit (ZandGo, adLyn) ou véhicule (bfmobility) — photo à adresse publique obligatoire
            eid = str(cand.get("element_id") or "").strip()
            nom = str(cand.get("nom") or "").strip()
            if not eid or eid in deja or not nom or not _url_publique(cand.get("photo_url")):
                continue
            description = str(cand.get("description") or "").strip()
            avis = await moderer_produit(nom, description, contenu, nom_plateforme(code))
            defaut = (PROFILS.get(code) or PROFIL_GENERIQUE)["legende"]
            doc = {
                "id": str(uuid.uuid4()), "type": contenu, "plateforme": code, "element_id": eid,
                "prenom": nom[:80], "image_url": cand["photo_url"], "lien_article": cand.get("lien"),
                "prix_txt": prix_txt(cand), "bio_origine": description[:800],
                "texte": legende_element(regl.get("legende"), defaut, cand, avis, regl.get("lien") or "") if avis["conforme"] else "",
                "avis_ia": avis, "statut": "a_valider" if avis["conforme"] else "refuse_ia",
                "cree_le": _iso(), "declencheur": declencheur,
            }
        await db.fb_publications.insert_one(dict(doc))
        crees.append(doc)
        deja.add(_ident(doc))
        if avis["conforme"] and not regl.get("validation_manuelle"):
            doc.update(await publier(db, doc["id"], "auto"))
    return {"crees": len(crees), "plateforme": code,
            "publications": [{k: v for k, v in c.items() if k != "_id"} for c in crees]}


async def publier(db, pid: str, par: str) -> Dict[str, Any]:
    """Publie une publication de la file sur la page Facebook de SA plateforme et prévient la plateforme."""
    pub = await db.fb_publications.find_one({"id": pid}, {"_id": 0})
    if not pub:
        raise HTTPException(status_code=404, detail="Publication introuvable")
    if pub["statut"] not in ("a_valider", "echec"):
        raise HTTPException(status_code=409, detail="Cette publication n'est plus à publier")
    historique = await plateforme_historique(db)
    code = pub.get("plateforme") or historique
    try:
        # Lot 105 — une publication du kit de lancement ne part QUE sur la page propre de la plateforme
        if pub.get("type") == "kit":
            s = await db.settings.find_one({"_id": "global"}) or {}
            if not page_de(s, code):
                raise RuntimeError("choisissez d'abord la Page de la plateforme (le kit n'est jamais publié sur la page de SAWALI)")
        if code == historique:   # beAuthentik : appel identique aux lots 96-97
            post_id = await publier_sur_facebook(db, pub["texte"], pub["image_url"])
        else:
            post_id = await publier_sur_facebook(db, pub["texte"], pub["image_url"], code)
    except Exception as exc:  # noqa: BLE001
        maj = {"statut": "echec", "erreur": str(getattr(exc, "detail", exc))[:300], "tente_le": _iso()}
        await db.fb_publications.update_one({"id": pid}, {"$set": maj})
        return maj
    maj = {"statut": "publie", "post_id": post_id, "publie_le": _iso(), "publie_par": par, "erreur": None}
    await db.fb_publications.update_one({"id": pid}, {"$set": maj})
    if pub.get("type") == "kit":   # lot 105 : publication de lancement, aucun élément à signaler à la plateforme
        return maj
    try:   # la plateforme note la publication (l'élément n'est plus proposé pendant quelque temps)
        emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0})
        if emetteur:
            corps = ({"type": "facebook_publie", "membre_id": pub["membre_id"], "post_id": post_id} if pub.get("membre_id")
                     else {"type": "facebook_publie", "element_id": pub.get("element_id"), "post_id": post_id})
            await appel_plateforme(emetteur, corps)
    except Exception as exc:  # noqa: BLE001 — non bloquant
        logger.warning("[fb_animation] plateforme %s non prévenue : %s", code, exc)
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
    """Appelée toutes les 5 minutes par le planificateur : chaque plateforme ACTIVE est préparée à ses jours / heure."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    maintenant = _maintenant()
    for code in codes_configures(s):
        regl = config_de(s, code)
        if not doit_preparer(regl, maintenant):
            continue
        # Noté AVANT la préparation : une plateforme injoignable n'est pas rappelée toutes les 5 minutes
        await _enregistrer_config(db, code, {"dernier_jour": maintenant.date().isoformat()})
        try:
            await preparer(db, "planifie", code)
        except Exception as exc:  # noqa: BLE001 — une plateforme en échec n'empêche pas les autres
            logger.warning("[fb_animation] préparation planifiée de %s en échec : %s", code, exc)


def _etat_page(s: Dict[str, Any], code: str, historique: str) -> Dict[str, Any]:
    """État de la page de publication d'une plateforme (jamais le jeton)."""
    propre = page_de(s, code)
    if propre:
        return {"connectee": True, "nom": propre.get("nom") or propre.get("id"), "propre": True}
    if code == historique:   # beAuthentik : la page active de SAWALI servirait (comportement du lot 97)
        return {"connectee": bool(s.get("facebook_page_access_token")), "nom": s.get("facebook_page_name") or "", "propre": False}
    return {"connectee": False, "nom": "", "propre": False}


# ---------------------------------------------------------------------------
# Routes d'administration
# ---------------------------------------------------------------------------
def attach_facebook_animation_routes(*, api, db, get_current_admin):

    @api.get("/admin/facebook/animation", tags=["Admin — Facebook"])
    async def lire(statut: Optional[str] = None, plateforme: Optional[str] = None, filtre: Optional[str] = None,
                   _: dict = Depends(get_current_admin)):
        """Réglages et page de la plateforme choisie (`plateforme`, beAuthentik par défaut), réglages de toutes les
        plateformes (`configurations`) et file des publications (les 50 plus récentes), filtrable par statut et par
        plateforme (`filtre`, lot 132)."""
        s = await db.settings.find_one({"_id": "global"}) or {}
        historique = _historique_de(s)
        code = plateforme if plateforme and CODE_VALIDE.match(plateforme) else historique
        requete: Dict[str, Any] = {"statut": statut} if statut in STATUTS else {}
        if filtre and CODE_VALIDE.match(filtre):
            requete["plateforme"] = filtre
        pubs = await db.fb_publications.find(requete, {"_id": 0}).sort("cree_le", -1).to_list(50)
        configurations = [{"code": c, "nom": nom_plateforme(c), "reglages": config_de(s, c),
                           "page": _etat_page(s, c, historique)} for c in codes_configures(s)]
        emetteurs = [e["code"] async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "code": 1})]
        return {"reglages": config_de(s, code), "publications": pubs, "page": _etat_page(s, code, historique),
                "plateformes": emetteurs, "configurations": configurations, "historique": historique}

    @api.get("/admin/facebook/animation/pages", tags=["Admin — Facebook"])
    async def lister_pages(_: dict = Depends(get_current_admin)):
        """Lot 97 — pages du compte Facebook connecté (identifiant et nom seulement : jamais les jetons)."""
        return {"pages": [{"id": p["id"], "nom": p["nom"]} for p in await pages_du_compte(db)]}

    @api.put("/admin/facebook/animation/page", tags=["Admin — Facebook"])
    async def choisir_page(corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        """Page propre d'une plateforme (`plateforme`, beAuthentik par défaut), distincte de la page active de SAWALI.
        Le serveur relit le jeton de la page auprès de Facebook (le navigateur ne le voit jamais)."""
        historique = await plateforme_historique(db)
        code = _code_ou_422(corps.get("plateforme")) if corps.get("plateforme") else historique
        pid = str(corps.get("page_id") or "").strip()
        if not pid:   # page_id vide : plus de page propre (beAuthentik : retour à la page active de SAWALI)
            retrait = {f"{CLE_PLATEFORMES}.{code}.page": ""}
            if code == historique:
                retrait["fb_animation_page"] = ""
            await db.settings.update_one({"_id": "global"}, {"$unset": retrait})
            return {"ok": True, "page": None}
        page = next((p for p in await pages_du_compte(db) if p["id"] == pid), None)
        if not page or not page.get("jeton"):
            raise HTTPException(status_code=404, detail="Page introuvable dans le compte Facebook connecté")
        fiche = {"id": page["id"], "nom": page["nom"], "jeton": page["jeton"], "choisie_le": _iso(), "choisie_par": user.get("email")}
        maj = {f"{CLE_PLATEFORMES}.{code}.page": fiche}
        if code == historique:
            maj["fb_animation_page"] = fiche     # ancien emplacement (lot 97) gardé à jour
        await db.settings.update_one({"_id": "global"}, {"$set": maj}, upsert=True)
        return {"ok": True, "plateforme": code, "page": {"id": page["id"], "nom": page["nom"]}}

    @api.put("/admin/facebook/animation/reglages", tags=["Admin — Facebook"])
    async def enregistrer(corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        """Réglages d'UNE plateforme (`plateforme` dans le corps ; beAuthentik par défaut)."""
        historique = await plateforme_historique(db)
        code = _code_ou_422(corps.get("plateforme")) if corps.get("plateforme") else historique
        regl = await reglages(db, code)
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
        for cle, maxi in (("lien", 200), ("legende", 2000)):
            if cle in corps and str(corps[cle] or "").strip():
                regl[cle] = str(corps[cle]).strip()[:maxi]
        regl["modifie_par"], regl["modifie_le"] = user.get("email"), _iso()
        await _enregistrer_config(db, code, regl)
        return await reglages(db, code)

    @api.post("/admin/facebook/animation/preparer", tags=["Admin — Facebook"])
    async def preparer_maintenant(plateforme: Optional[str] = None, user: dict = Depends(get_current_admin)):
        """Préparation immédiate d'une plateforme (`?plateforme=zandgo` ; beAuthentik par défaut)."""
        code = _code_ou_422(plateforme) if plateforme else None
        try:
            return await preparer(db, f"manuel:{user.get('email')}", code)
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
        """Valider = publier tout de suite sur la Page Facebook de la plateforme."""
        return await publier(db, pid, user.get("email") or "admin")

    @api.post("/admin/facebook/animation/publications/{pid}/refuser", tags=["Admin — Facebook"])
    async def refuser(pid: str, user: dict = Depends(get_current_admin)):
        r = await db.fb_publications.update_one({"id": pid, "statut": {"$in": ["a_valider", "echec"]}}, {
            "$set": {"statut": "refuse", "refuse_par": user.get("email"), "refuse_le": _iso()}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Publication introuvable ou déjà traitée")
        return {"ok": True}

    logger.info("[fb_animation] routes montées sous /api/admin/facebook/animation")
