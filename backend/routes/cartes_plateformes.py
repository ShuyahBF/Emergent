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

Route SIGNÉE (X-Emetteur, X-Timestamp, X-Signature) :
    POST /api/cartes-plateformes/generer  {utilisateur, theme, message, destinataire?}  → {image (data URL JPEG), restant_aujourdhui}
"""
from __future__ import annotations

import base64
import io
import logging
import os
from datetime import timedelta
from typing import Any, Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
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


def prompt_decor(theme: str) -> str:
    """Consigne donnée à l'IA : un décor de carte de vœux, SANS texte, avec le bas de l'image calme pour recevoir le message."""
    theme = " ".join(theme.split())
    return ("Illustration soignée pour une carte de vœux, sur le thème : " + theme + ". "
            "Style chaleureux, couleurs vives et lumineuses, ambiance joyeuse et bienveillante. "
            "Aucun texte, aucune lettre, aucun chiffre, aucun logo, aucun filigrane dans l'image. "
            "Format portrait ; le sujet est dans les deux tiers du haut, le tiers du bas reste une zone calme et peu chargée.")


async def decor_ia(theme: str) -> bytes:
    """Décor dessiné par l'IA (octets de l'image). Lève RuntimeError si l'IA ne renvoie rien."""
    taille = f"{LARGEUR}x{HAUTEUR}"
    if _generer_decor:
        return await _generer_decor(prompt_decor(theme), taille)
    from ia_client import OpenAIImageGeneration
    images = await OpenAIImageGeneration().generate_images(prompt_decor(theme), model="gpt-image-1", quality="medium", size=taille)
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
    from PIL import Image, ImageDraw
    image = Image.open(io.BytesIO(octets_decor)).convert("RGB").resize((LARGEUR, HAUTEUR))
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


def make_cartes_plateformes(*, db, outils: Any):
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
            decor = await decor_ia(d.theme)
            carte = composer_carte(decor, d.message, d.destinataire.strip(), utilisateur.nom.strip())
        except Exception:  # noqa: BLE001 — l'IA ou l'image peut échouer : message clair, rien n'est décompté
            logger.exception("[cartes] génération impossible")
            raise HTTPException(status_code=502, detail="La carte n'a pas pu être créée : reformulez le thème et réessayez.")
        # Génération réussie seulement : compte dans la limite du jour
        await db.membres_plateformes.update_one({"id": m["id"]}, {"$inc": {f"cartes_jours.{jour}": 1, "cartes_total": 1}})
        restant = max(0, limite - int((m.get("cartes_jours") or {}).get(jour, 0)) - 1)
        return {"ok": True, "image": "data:image/jpeg;base64," + base64.b64encode(carte).decode("ascii"), "restant_aujourdhui": restant}

    return router
