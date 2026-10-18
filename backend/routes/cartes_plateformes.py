"""Lot 242 — Cartes virtuelles pour les plateformes (Paiement Mobile…) : l'IA dessine le décor, SAWALI écrit le message dessus.

Demande du propriétaire (18/10/2026) : « Pour les anniversaires à souhaiter et heureux événements, on peut générer des cartes virtuelles
avec un texte à saisir par l'utilisateur et un thème aussi à saisir. L'IA génère et propose jusqu'à 3 variantes. Une fois OK, Liluvine
joue le facteur et envoie la carte avec son message au destinataire. Le coût est paramétré comme les autres formules d'abonnement. »

Pour un développeur WinDev (équivalent d'une procédure de génération, sans nouveau fichier de données) :
  - l'accès est une FONCTION de formule (`cartes_virtuelles`) : la plateforme crée la formule et son prix dans « Formules des plateformes » ;
    sans abonnement actif, refus 402 avec le NOM et le PRIX de la formule (même mécanisme que l'OCR et la voix) ;
  - l'IA (gpt-image-1) ne dessine QUE le décor du thème, SANS aucun texte (elle écrit mal en français) ; le message, le nom du
    destinataire et la signature sont ajoutés ICI, proprement, par Pillow sur un bandeau sombre en bas de l'image ;
  - aucune nouvelle collection : seul un compteur « cartes_jours » est tenu sur la fiche de l'utilisateur (comme l'OCR et la voix) ;
  - la limite de 3 variantes par carte est tenue par la plateforme, qui garde la carte ; SAWALI protège le coût par un plafond par jour ;
  - l'ENVOI WhatsApp n'est pas fait ici : la plateforme poste la carte validée sur la transmission universelle de Liluvine
    (/api/webhook/liluvine-send : modèle Meta, désinscription STOP, quotas, journal).

Modération (lot 244) : le thème, le message et le nom du destinataire sont contrôlés AVANT tout (liste de termes puis modération IA, voir
moderation_cartes.py). Un contenu sexuel, offensant, discriminant, pédophile, sexiste, rabaissant, insultant ou homophobe est refusé (422) même
si l'abonnement est payé ; le refus n'est pas décompté, il est tracé (incident) et signalé par e-mail à l'administrateur.

Lot 246 : l'utilisateur choisit la FORME ARTISTIQUE (photo réaliste, peinture à l'huile, aquarelle, dessin…) et le MOTEUR IA (modèle et
qualité). Les deux sont des listes fermées (STYLES, MOTEURS) : aucune saisie libre n'atteint l'IA. Chaque génération réussie note son COÛT
estimé en dollars dans le journal de l'IA (`journal_ia`, aucune nouvelle collection) ; l'administrateur les voit une par une dans les
Paramètres (« Formules des plateformes » → Cartes virtuelles — coût des générations), avec export CSV.

Route SIGNÉE (X-Emetteur, X-Timestamp, X-Signature) :
    POST /api/cartes-plateformes/generer  {utilisateur, theme, message, destinataire?, style?, moteur?}  → {image (data URL JPEG), restant_aujourdhui, style, moteur, cout_usd}
    GET  /api/cartes-plateformes/options  (signée) → listes des formes artistiques et des moteurs IA (pour les listes déroulantes)
    GET  /api/admin/cartes-plateformes/generations?jours=30[&format=csv]  (super-administrateur) → une ligne par génération avec son coût
"""
from __future__ import annotations

import base64
import io
import logging
import os
from datetime import timedelta
from typing import Any, Callable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from routes import moderation_cartes
from routes.formules_plateformes import Utilisateur, _maintenant

logger = logging.getLogger("sawali.cartes_plateformes")

FONCTION_CARTES = "cartes_virtuelles"
CARTES_PAR_JOUR_DEFAUT = 9            # images générées par jour et par utilisateur (réglable par l'administrateur)
LARGEUR, HAUTEUR = 1024, 1536         # carte « portrait » : s'affiche en grand sur un téléphone
POLICES = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
           "DejaVuSans-Bold.ttf", "DejaVuSans.ttf")

# Envoi d'e-mail à l'administrateur (tests : remplacé) : async (destinataire, sujet, html, texte) ; None = e-mail_service.send_email
_envoyer_alerte: Optional[Callable] = None
ALERTE_REFUS_MINUTES = 5            # au plus un e-mail par utilisateur et par tranche de 5 minutes (tous les refus restent tracés)

# Décor de remplacement (tests) : async (prompt, taille) → octets PNG ; None = vrai client IA (gpt-image-1)
_generer_decor: Optional[Callable] = None


class CarteIn(BaseModel):
    """Texte de la carte, saisi par l'utilisateur de la plateforme (déjà authentifié par elle)."""
    utilisateur: Utilisateur
    theme: str = Field(..., min_length=3, max_length=100)
    message: str = Field(..., min_length=2, max_length=300)
    destinataire: str = Field("", max_length=60)
    style: str = Field("illustration", max_length=20)    # clé de STYLES (forme artistique) ; inconnue → 422
    moteur: str = Field("standard", max_length=20)       # clé de MOTEURS (modèle et qualité de l'IA) ; inconnue → 422


# Formes artistiques proposées (liste fermée) : clé → (libellé affiché, consigne donnée à l'IA).
STYLE_DEFAUT = "illustration"
STYLES = {
    "illustration": ("Illustration / dessin", "Illustration soignée dessinée à la main, traits nets, couleurs vives et lumineuses."),
    "photo": ("Photo réaliste", "Photographie réaliste haute définition, vraie lumière naturelle, profondeur de champ, rendu professionnel. Ce n'est PAS un dessin."),
    "huile": ("Peinture à l'huile", "Peinture à l'huile sur toile, touches de pinceau visibles, matière épaisse, palette riche, esprit des maîtres classiques."),
    "aquarelle": ("Aquarelle", "Aquarelle délicate sur papier texturé, transparences, fondus de couleurs, bords légèrement coulants."),
    "pastel": ("Pastel", "Dessin au pastel tendre, grain de papier visible, couleurs douces et veloutées."),
    "gouache": ("Gouache / art naïf", "Peinture à la gouache d'inspiration naïve et africaine contemporaine, aplats de couleurs franches, motifs décoratifs."),
    "3d": ("Rendu 3D", "Rendu 3D de film d'animation, matières douces, éclairage de studio, personnages et objets arrondis et attachants."),
    "papier": ("Papier découpé", "Création en papier découpé multicouche (paper cut art), ombres portées douces, couleurs vives."),
    "vintage": ("Affiche rétro", "Affiche vintage des années 1950, lithographie, couleurs chaudes un peu passées, grain d'impression."),
    "fusain": ("Fusain / encre", "Dessin au fusain et à l'encre de Chine, contrastes marqués, hachures expressives, quelques touches de couleur."),
}

# Moteurs IA proposés (liste fermée) : clé → modèle, qualité, taille demandée au fournisseur, coût estimé en dollars PAR IMAGE
# (tarifs publics d'OpenAI pour une image portrait ; à ajuster ici si les tarifs changent).
MOTEUR_DEFAUT = "standard"
MOTEURS = {
    "eco": {"nom": "Économique — gpt-image-1, qualité basse", "modele": "gpt-image-1", "qualite": "low", "taille": "1024x1536", "cout_usd": 0.016},
    "standard": {"nom": "Standard — gpt-image-1, qualité moyenne", "modele": "gpt-image-1", "qualite": "medium", "taille": "1024x1536", "cout_usd": 0.063},
    "premium": {"nom": "Premium — gpt-image-1, haute qualité", "modele": "gpt-image-1", "qualite": "high", "taille": "1024x1536", "cout_usd": 0.25},
    "dalle3": {"nom": "DALL·E 3 — qualité standard", "modele": "dall-e-3", "qualite": "standard", "taille": "1024x1792", "cout_usd": 0.08},
    "dalle3hd": {"nom": "DALL·E 3 — haute définition", "modele": "dall-e-3", "qualite": "hd", "taille": "1024x1792", "cout_usd": 0.12},
}


def prompt_decor(theme: str, style: str = STYLE_DEFAUT) -> str:
    """Consigne donnée à l'IA : un décor de carte de vœux dans la forme artistique choisie, SANS texte, bas de l'image calme pour le message."""
    theme = " ".join(theme.split())
    consigne_style = STYLES.get(style, STYLES[STYLE_DEFAUT])[1]
    return ("Image pour une carte de vœux, sur le thème : " + theme + ". "
            "Forme artistique : " + consigne_style + " "
            "Ambiance chaleureuse, joyeuse et bienveillante. "
            "Aucun texte, aucune lettre, aucun chiffre, aucun logo, aucun filigrane dans l'image. "
            "Format portrait ; le sujet est dans les deux tiers du haut, le tiers du bas reste une zone calme et peu chargée.")


async def decor_ia(theme: str, style: str = STYLE_DEFAUT, moteur: str = MOTEUR_DEFAUT) -> bytes:
    """Décor créé par l'IA (octets de l'image) dans la forme artistique et avec le moteur choisis. Lève RuntimeError si l'IA ne renvoie rien."""
    m = MOTEURS.get(moteur) or MOTEURS[MOTEUR_DEFAUT]
    prompt = prompt_decor(theme, style)
    if _generer_decor:
        return await _generer_decor(prompt, m["taille"])
    from ia_client import OpenAIImageGeneration
    images = await OpenAIImageGeneration().generate_images(prompt, model=m["modele"], quality=m["qualite"], size=m["taille"])
    if not images:
        raise RuntimeError("L'IA n'a renvoyé aucune image")
    return images[0]


def _police(taille: int):
    from PIL import ImageFont
    for chemin in POLICES:
        try:
            return ImageFont.truetype(chemin, taille)
        except OSError:
            continue
    return ImageFont.load_default()


def decouper(texte: str, police, largeur_max: float) -> List[str]:
    """Coupe le texte en lignes qui tiennent dans `largeur_max` pixels (les retours à la ligne saisis sont respectés)."""
    lignes: List[str] = []
    for paragraphe in texte.replace("\r", "").split("\n"):
        courant = ""
        for mot in paragraphe.split():
            essai = f"{courant} {mot}".strip()
            if courant and police.getlength(essai) > largeur_max:
                lignes.append(courant)
                courant = mot
            else:
                courant = essai
        lignes.append(courant)
    return lignes


def composer_carte(octets_decor: bytes, message: str, destinataire: str, expediteur: str) -> bytes:
    """Décor + bandeau sombre dégradé en bas + « Pour <destinataire> », message et signature. Renvoie un JPEG.
    La taille du texte diminue jusqu'à ce que le message tienne entièrement dans le bandeau."""
    from PIL import Image, ImageDraw, ImageOps
    # Recadrage « cover » (ratio conservé) : DALL·E 3 renvoie 1024x1792, gpt-image-1 1024x1536
    image = ImageOps.fit(Image.open(io.BytesIO(octets_decor)).convert("RGB"), (LARGEUR, HAUTEUR))
    # Bandeau : dégradé du transparent vers un bleu nuit opaque (le texte blanc reste lisible quel que soit le décor)
    haut_bandeau = int(HAUTEUR * 0.50)
    voile = Image.new("RGBA", (LARGEUR, HAUTEUR), (0, 0, 0, 0))
    dessin_voile = ImageDraw.Draw(voile)
    for y in range(haut_bandeau, HAUTEUR):
        opacite = int(235 * min(1.0, (y - haut_bandeau) / (HAUTEUR * 0.18)))
        dessin_voile.line([(0, y), (LARGEUR, y)], fill=(10, 20, 60, opacite))
    image = Image.alpha_composite(image.convert("RGBA"), voile).convert("RGB")
    dessin = ImageDraw.Draw(image)
    marge = 70
    largeur_texte = LARGEUR - 2 * marge
    signature = f"— {expediteur}" if expediteur else ""
    pour = f"Pour {destinataire}" if destinataire else ""
    zone_haut, zone_bas = int(HAUTEUR * 0.64), HAUTEUR - 60
    # Plus grande taille de police pour laquelle « Pour… », le message et la signature tiennent dans la zone
    for taille in range(64, 23, -2):
        police, petite = _police(taille), _police(max(22, int(taille * 0.7)))
        lignes = decouper(message.strip(), police, largeur_texte)
        interligne = int(taille * 1.3)
        hauteur = len(lignes) * interligne + (int(taille * 1.3) if pour else 0) + (int(taille * 1.5) if signature else 0)
        if hauteur <= zone_bas - zone_haut:
            break
    y = zone_haut + max(0, (zone_bas - zone_haut - hauteur) // 2)
    if pour:
        dessin.text((LARGEUR / 2, y), pour, font=petite, fill=(255, 214, 102), anchor="ma")
        y += int(taille * 1.3)
    for ligne in lignes:
        dessin.text((LARGEUR / 2, y), ligne, font=police, fill=(255, 255, 255), anchor="ma")
        y += interligne
    if signature:
        dessin.text((LARGEUR / 2, y + int(taille * 0.3)), signature, font=petite, fill=(255, 214, 102), anchor="ma")
    sortie = io.BytesIO()
    image.save(sortie, format="JPEG", quality=86, optimize=True)
    return sortie.getvalue()


def _echapper(texte: str) -> str:
    return (texte or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def signaler_refus(db, emetteur: str, m: dict, utilisateur: Utilisateur, d: "CarteIn", refus: dict) -> None:
    """Trace le refus (incident, compteur du membre) et prévient l'administrateur par e-mail. Ne lève JAMAIS d'exception."""
    try:
        maintenant = _maintenant()
        motif = f"carte_refusee:{refus.get('categorie') or 'contenu'}"[:80]
        await db.liluvine_incidents.insert_one({"emetteur": emetteur, "motif": motif, "date": maintenant.isoformat(),
                                                "utilisateur_id": utilisateur.id, "source": refus.get("source")})
        await db.membres_plateformes.update_one({"id": m["id"]}, {"$inc": {"cartes_refus_total": 1}})
        cle = f"carte_refus:{m['id']}"
        deja = await db.liluvine_alertes.find_one({"_id": cle})
        limite = (maintenant - timedelta(minutes=ALERTE_REFUS_MINUTES)).isoformat()
        if deja and deja.get("date", "") >= limite:
            return
        await db.liluvine_alertes.update_one({"_id": cle}, {"$set": {"date": maintenant.isoformat()}}, upsert=True)
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "liluvine_transmission_email_alerte": 1, "admin_email": 1}) or {}
        destinataire = (s.get("liluvine_transmission_email_alerte") or s.get("admin_email") or os.environ.get("SUPER_ADMIN_EMAIL") or "").strip()
        if not destinataire:
            return
        total = int((m.get("cartes_refus_total") or 0)) + 1
        html = (f"<p>Une carte virtuelle a été <b>refusée</b> sur « {_echapper(emetteur)} » (aucune image générée, aucun décompte).</p><ul>"
                f"<li>Utilisateur : {_echapper(utilisateur.nom) or '—'} · {_echapper(utilisateur.telephone) or '—'} · identifiant {_echapper(utilisateur.id)}</li>"
                f"<li>Motif : {_echapper(refus.get('categorie') or '')} ({'liste de termes' if refus.get('source') == 'liste' else 'modération IA'})"
                f"{' · terme : ' + _echapper(refus['terme']) if refus.get('terme') else ''}</li>"
                f"<li>Refus de cet utilisateur : {total}</li></ul>"
                f"<p><b>Thème :</b> {_echapper(d.theme)}<br><b>Message :</b> {_echapper(d.message)}<br><b>Destinataire :</b> {_echapper(d.destinataire)}</p>"
                "<p>L'utilisateur a reçu un message de refus. Pour sanctionner un abus répété, bloquez son compte depuis la plateforme concernée.</p>")
        texte = f"Carte refusée ({refus.get('categorie')}) pour {utilisateur.nom} {utilisateur.telephone} : {d.theme} / {d.message}"
        envoyer = _envoyer_alerte
        if envoyer is None:
            from email_service import send_email as envoyer
        await envoyer(destinataire, f"⚠️ Carte virtuelle refusée ({emetteur}) : contenu inapproprié", html, texte)
    except Exception:  # noqa: BLE001 — un signalement ne bloque jamais le refus
        logger.warning("[cartes] signalement du refus impossible", exc_info=True)


async def noter_cout(db, emetteur: str, utilisateur: Utilisateur, d: "CarteIn") -> float:
    """Note la génération et son coût estimé dans le journal de l'IA (collection existante `journal_ia`). Ne lève JAMAIS d'exception."""
    m = MOTEURS[d.moteur]
    try:
        from datetime import datetime, timezone
        import time
        await db.journal_ia.insert_one({
            "le": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "le_dt": datetime.now(timezone.utc),
            "fonction": "cartes-plateformes", "fournisseur": "openai", "modele": m["modele"], "entree": 0, "sortie": 0,
            "cout_usd": m["cout_usd"], "qualite": m["qualite"], "moteur": d.moteur, "style": d.style, "emetteur": emetteur,
            "utilisateur_id": utilisateur.id, "utilisateur": (utilisateur.nom or "")[:60], "theme": " ".join(d.theme.split())[:100]})
    except Exception:  # noqa: BLE001 — le journal ne bloque jamais la livraison de la carte
        logger.warning("[cartes] coût non noté", exc_info=True)
    return m["cout_usd"]


async def lister_generations(db, jours: int = 30):
    """(lignes, total) des générations de cartes sur les N derniers jours, lues dans le journal de l'IA (index sur `le`)."""
    from datetime import datetime, timezone
    jours = max(1, min(int(jours or 30), 400))
    depuis = (datetime.now(timezone.utc) - timedelta(days=jours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lignes = []
    async for x in db.journal_ia.find({"fonction": "cartes-plateformes", "le": {"$gte": depuis}}, {"_id": 0, "le_dt": 0}).sort("le", -1).limit(2000):
        lignes.append({"date": x.get("le"), "plateforme": x.get("emetteur"), "utilisateur": x.get("utilisateur"), "theme": x.get("theme"),
                       "style": STYLES.get(x.get("style"), (x.get("style") or "",))[0], "moteur": (MOTEURS.get(x.get("moteur")) or {}).get("nom") or x.get("moteur"),
                       "modele": x.get("modele"), "qualite": x.get("qualite"), "cout_usd": x.get("cout_usd") or 0})
    total = {"generations": len(lignes), "cout_usd": round(sum(l["cout_usd"] for l in lignes), 3)}
    return lignes, total


def en_csv(lignes) -> str:
    """CSV (séparateur « ; », ouvrable dans Excel) des générations."""
    import csv
    sortie = io.StringIO()
    sortie.write("\ufeff")
    w = csv.writer(sortie, delimiter=";")
    w.writerow(["Date (UTC)", "Plateforme", "Utilisateur", "Thème", "Forme artistique", "Moteur", "Modèle", "Qualité", "Coût estimé (USD)"])
    for l in lignes:
        w.writerow([l["date"], l["plateforme"], l["utilisateur"], l["theme"], l["style"], l["moteur"], l["modele"], l["qualite"], str(l["cout_usd"]).replace(".", ",")])
    return sortie.getvalue()


def make_cartes_plateformes(*, db, outils: Any, get_super_admin: Optional[Callable] = None):
    """Construit le routeur. `outils` : signature des plateformes, fiche membre et contrôle d'abonnement (formules_plateformes)."""
    router = APIRouter(tags=["Cartes virtuelles des plateformes (lot 242)"])

    async def par_jour() -> int:
        s = await db.settings.find_one({"_id": "global"}, {"cartes_plateformes_par_jour": 1}) or {}
        return int(s.get("cartes_plateformes_par_jour") or CARTES_PAR_JOUR_DEFAUT)

    @router.post("/cartes-plateformes/generer")
    async def generer(request: Request):
        """Une image de carte (décor IA + message) pour l'utilisateur ; réservée aux abonnés d'une formule qui débloque les cartes."""
        emetteur, corps = await outils.plateforme_signee(request)
        d = outils.lire(CarteIn, corps)
        utilisateur = d.utilisateur
        if d.style not in STYLES or d.moteur not in MOTEURS:
            raise HTTPException(status_code=422, detail="Forme artistique ou moteur IA inconnu.")
        m = await outils.membre(emetteur["code"], utilisateur)
        # 0. Modération : refus même si l'abonnement est payé ; rien n'est décompté, l'administrateur est prévenu
        try:
            refus = await moderation_cartes.moderer(d.theme, d.message, d.destinataire)
        except moderation_cartes.ContenuIndisponible:
            raise HTTPException(status_code=503, detail=moderation_cartes.MESSAGE_INDISPONIBLE)
        if refus:
            await signaler_refus(db, emetteur["code"], m, utilisateur, d, refus)
            raise HTTPException(status_code=422, detail=moderation_cartes.MESSAGE_REFUS)
        # 1. Abonnement actif ? Sinon refus (402) avec le nom et le PRIX de la formule à prendre
        await outils.exiger_abonnement(emetteur["code"], m, FONCTION_CARTES, "Les cartes virtuelles", utilisateur.acces_libre)
        # 2. Plafond par jour et par utilisateur (protège le coût de l'IA)
        jour, limite = _maintenant().date().isoformat(), await par_jour()
        if int((m.get("cartes_jours") or {}).get(jour, 0)) >= limite:
            raise HTTPException(status_code=429, detail=f"Limite atteinte : {limite} images de cartes par jour. Réessayez demain.")
        # 3. Décor par l'IA, puis message écrit par nos soins
        try:
            decor = await decor_ia(d.theme, d.style, d.moteur)
            carte = composer_carte(decor, d.message, d.destinataire.strip(), utilisateur.nom.strip())
        except Exception:  # noqa: BLE001 — l'IA ou l'image peut échouer : message clair, rien n'est décompté
            logger.exception("[cartes] génération impossible")
            raise HTTPException(status_code=502, detail="La carte n'a pas pu être créée : reformulez le thème et réessayez.")
        # Génération réussie seulement : compte dans la limite du jour
        await db.membres_plateformes.update_one({"id": m["id"]}, {"$inc": {f"cartes_jours.{jour}": 1, "cartes_total": 1}})
        restant = max(0, limite - int((m.get("cartes_jours") or {}).get(jour, 0)) - 1)
        cout = await noter_cout(db, emetteur["code"], utilisateur, d)
        return {"ok": True, "image": "data:image/jpeg;base64," + base64.b64encode(carte).decode("ascii"), "restant_aujourdhui": restant,
                "style": d.style, "moteur": d.moteur, "cout_usd": cout}

    @router.get("/cartes-plateformes/options")
    async def options(request: Request):
        """Listes des formes artistiques et des moteurs IA, avec le coût estimé de chacun (alimente les listes déroulantes de la plateforme)."""
        await outils.plateforme_signee(request)
        return {"styles": [{"cle": k, "nom": v[0]} for k, v in STYLES.items()], "style_defaut": STYLE_DEFAUT,
                "moteurs": [{"cle": k, "nom": v["nom"]} for k, v in MOTEURS.items()], "moteur_defaut": MOTEUR_DEFAUT}

    if get_super_admin is not None:
        @router.get("/admin/cartes-plateformes/generations")
        async def admin_generations(jours: int = 30, format: str = "json", _: dict = Depends(get_super_admin)):
            """Une ligne par génération réussie avec son coût estimé (journal de l'IA), du plus récent au plus ancien ; `format=csv` pour l'export."""
            lignes, total = await lister_generations(db, jours)
            if format == "csv":
                return Response(content=en_csv(lignes), media_type="text/csv; charset=utf-8",
                                headers={"Content-Disposition": "attachment; filename=cartes-generations.csv"})
            return {"jours": max(1, min(int(jours or 30), 400)), "generations": lignes, "total": total}

    return router
