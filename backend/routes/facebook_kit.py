"""Lot 105 — Kit de lancement de la Page Facebook beAuthentik.

Demande du propriétaire (10/10/2026) : « Peux-tu me construire la page Facebook pour beAuthentik. Elle doit être
vide maintenant. »

Ce que SAWALI fournit (pour un développeur WinDev : un « jeu de fichiers + textes » prêt à l'emploi) :
  1. Les visuels de la Page, aux couleurs de beAuthentik (rose #f4256a → orange #ff7a45, cauris) :
       - photo de profil 720 × 720 et photo de couverture 1640 × 624, à TÉLÉCHARGER puis à poser à la main sur
         Facebook (l'API de Facebook ne permet plus de les modifier) ;
       - 8 publications de lancement 1080 × 1350 (format portrait du fil d'actualité).
  2. Les textes de la section « À propos » (catégorie, présentation courte, description, bouton d'action),
     à copier-coller dans Facebook.
  3. Le bouton « Charger le kit » : les 8 publications entrent dans la file de l'animation (collection
     fb_publications, type « kit », statut « à valider »). Le propriétaire les publie une par une, dans l'ordre,
     depuis la rubrique « 📣 Page Facebook animée par Liluvine » — sur la Page PROPRE de la plateforme uniquement
     (jamais sur la page de SAWALI).

Les images sont servies par une route PUBLIQUE (Facebook doit pouvoir les télécharger) limitée à une liste blanche
de fichiers : aucun autre fichier du serveur n'est accessible.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse

# Dossier des visuels : backend/static/kit_facebook/<plateforme>/
DOSSIER_KIT = Path(__file__).resolve().parents[1] / "static" / "kit_facebook"

LIEN = "https://beauthentik.net"
TAGS = "#beAuthentik #rencontre #Afrique #diaspora #célibataires"

# ---------------------------------------------------------------------------
# Textes de la section « À propos » (à copier dans Facebook)
# ---------------------------------------------------------------------------
A_PROPOS: Dict[str, Any] = {
    "nom": "beAuthentik",
    "nom_utilisateur": "beauthentik",
    "categorie": "Service de rencontres",
    # Présentation courte : 101 caractères au plus (limite de Facebook)
    "presentation": "Rencontres authentiques entre Africains et la diaspora : profils vérifiés, vidéos floutées.",
    "description": (
        "beAuthentik est le site de rencontre des Africains et de la diaspora qui cherchent une relation sincère.\n\n"
        "• Chaque profil est vérifié avant d'apparaître.\n"
        "• Vos vidéos « Moments » restent floues jusqu'au match.\n"
        "• Un match, c'est quand l'intérêt est réciproque.\n"
        "• Premium payable en Mobile Money (Orange Money, Moov Money, Telecel Money).\n"
        "• Un faux profil ? Un clic suffit pour le signaler.\n\n"
        "Inscription gratuite sur https://beauthentik.net"
    ),
    "site_web": LIEN,
    "bouton": {"libelle": "S'inscrire", "lien": LIEN},
}

# ---------------------------------------------------------------------------
# Les 8 publications de lancement (ordre conseillé de publication)
# ---------------------------------------------------------------------------
PUBLICATIONS: List[Dict[str, str]] = [
    {"fichier": "publication-1.jpg", "titre": "Bienvenue",
     "texte": "Bienvenue sur la Page officielle de beAuthentik 💛\n\n"
              "Ici, on se rencontre pour de vrai : des Africains et des membres de la diaspora qui cherchent une "
              "relation sincère, sans faux-semblants.\n\n"
              f"Abonnez-vous à la Page et inscrivez-vous gratuitement sur {LIEN} 👉\n\n{TAGS}"},
    {"fichier": "publication-2.jpg", "titre": "Confiance",
     "texte": "Ici, chaque profil est vérifié ✅\n\n"
              "Avant d'apparaître sur beAuthentik, chaque membre passe une vérification. Résultat : vous parlez à "
              "de vraies personnes, pas à des robots ni à des escrocs.\n\n"
              f"Rejoignez une communauté de confiance : {LIEN}\n\n{TAGS} #confiance"},
    {"fichier": "publication-3.jpg", "titre": "Les Moments",
     "texte": "Vos vidéos restent floues 🎥\n\n"
              "Avec les « Moments », vous partagez de courtes vidéos de votre quotidien. Elles restent floues pour "
              "les autres membres tant qu'il n'y a pas de match : votre intimité est protégée.\n\n"
              f"Découvrez les Moments sur {LIEN}\n\n{TAGS} #vieprivée"},
    {"fichier": "publication-4.jpg", "titre": "Comment ça marche",
     "texte": "Comment ça marche ? Trois étapes, c'est tout :\n\n"
              "1️⃣ Créez votre profil (gratuit).\n"
              "2️⃣ Faites vérifier votre profil.\n"
              "3️⃣ Découvrez les profils et faites des rencontres.\n\n"
              f"C'est parti : {LIEN}\n\n{TAGS}"},
    {"fichier": "publication-5.jpg", "titre": "Le match",
     "texte": "Un match, c'est quand c'est réciproque 💞\n\n"
              "Sur beAuthentik, la conversation s'ouvre quand l'intérêt est partagé. Pas de messages non désirés, "
              "seulement des échanges qui ont du sens.\n\n"
              f"Trouvez votre match sur {LIEN}\n\n{TAGS} #match"},
    {"fichier": "publication-6.jpg", "titre": "Paiement",
     "texte": "Premium, en Mobile Money 📱\n\n"
              "Passez Premium simplement, avec Orange Money, Moov Money ou Telecel Money. Pas besoin de carte "
              "bancaire.\n\n"
              f"Plus d'informations sur {LIEN}\n\n{TAGS} #MobileMoney"},
    {"fichier": "publication-7.jpg", "titre": "Sécurité",
     "texte": "Un faux profil ? Un clic suffit 🛡️\n\n"
              "Chaque profil peut être signalé en un clic. Notre équipe examine chaque signalement et retire les "
              "comptes douteux.\n\n"
              f"Rencontrez en toute sérénité sur {LIEN}\n\n{TAGS} #sécurité"},
    {"fichier": "publication-8.jpg", "titre": "À vous de jouer",
     "texte": "Votre prochaine belle histoire commence ici ✨\n\n"
              "Des milliers de belles rencontres commencent par un simple profil. Et si c'était votre tour ?\n\n"
              f"Inscrivez-vous gratuitement sur {LIEN} 👉\n\n{TAGS}"},
]

# Liste blanche des fichiers servis publiquement, par plateforme
FICHIERS = {"beauthentik": {"photo-profil.jpg", "couverture.jpg", *(p["fichier"] for p in PUBLICATIONS)}}


def membre_id_kit(plateforme: str, rang: int) -> str:
    """Identifiant de la publication de kit n° rang (sert à ne jamais la charger deux fois)."""
    return f"kit-{plateforme}-{rang}"


async def url_fichier(db, plateforme: str, fichier: str) -> str:
    """Adresse publique d'un visuel du kit (Facebook la télécharge lors de la publication)."""
    from routes.liluvine_relais import url_publique
    return f"{await url_publique(db)}/api/facebook/kit/{plateforme}/{fichier}"


async def charger_kit(db, plateforme: str = "beauthentik") -> Dict[str, Any]:
    """Met les 8 publications du kit dans la file « à valider » (celles déjà chargées sont ignorées)."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "fb_animation_page": 1}) or {}
    if not (s.get("fb_animation_page") or {}).get("jeton"):
        raise HTTPException(status_code=400, detail="Choisissez d'abord la Page de la plateforme (ex. beAuthentik) "
                                                    "dans « Page de publication » : le kit n'est jamais publié sur la page de SAWALI.")
    crees, debut = 0, datetime.now(timezone.utc)
    for rang, pub in enumerate(PUBLICATIONS, start=1):
        mid = membre_id_kit(plateforme, rang)
        if await db.fb_publications.find_one({"membre_id": mid}, {"_id": 1}):
            continue   # déjà chargée (quel que soit son statut)
        await db.fb_publications.insert_one({
            "id": str(uuid.uuid4()), "type": "kit", "plateforme": plateforme, "membre_id": mid, "rang": rang,
            "prenom": pub["titre"], "image_url": await url_fichier(db, plateforme, pub["fichier"]),
            "texte": pub["texte"], "statut": "a_valider",
            # cree_le décroissant avec le rang : la file (triée du plus récent au plus ancien) affiche 1 → 8
            "cree_le": (debut - timedelta(seconds=rang)).isoformat(),
        })
        crees += 1
    return {"crees": crees, "total": len(PUBLICATIONS)}


def attach_facebook_kit_routes(*, api, db, get_current_admin):

    @api.get("/facebook/kit/{plateforme}/{fichier}", tags=["Facebook — Kit"], include_in_schema=False)
    async def visuel(plateforme: str, fichier: str):
        """Route PUBLIQUE : un visuel du kit (liste blanche uniquement, jamais un autre fichier du serveur)."""
        if fichier not in FICHIERS.get(plateforme, set()):
            raise HTTPException(status_code=404, detail="Fichier introuvable")
        chemin = DOSSIER_KIT / plateforme / fichier
        if not chemin.is_file():
            raise HTTPException(status_code=404, detail="Fichier introuvable")
        return FileResponse(chemin, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})

    @api.get("/admin/facebook/animation/kit", tags=["Admin — Facebook"])
    async def lire_kit(_: dict = Depends(get_current_admin)):
        """Textes « À propos », adresses des visuels et nombre de publications du kit déjà chargées."""
        plateforme = "beauthentik"
        charges = await db.fb_publications.count_documents({"type": "kit", "plateforme": plateforme})
        publies = await db.fb_publications.count_documents({"type": "kit", "plateforme": plateforme, "statut": "publie"})
        return {
            "plateforme": plateforme, "a_propos": A_PROPOS,
            "photo_profil": await url_fichier(db, plateforme, "photo-profil.jpg"),
            "couverture": await url_fichier(db, plateforme, "couverture.jpg"),
            "publications": [{"rang": i, "titre": p["titre"], "image_url": await url_fichier(db, plateforme, p["fichier"])}
                             for i, p in enumerate(PUBLICATIONS, start=1)],
            "charges": charges, "publies": publies, "total": len(PUBLICATIONS),
        }

    @api.post("/admin/facebook/animation/kit/charger", tags=["Admin — Facebook"])
    async def charger(_: dict = Depends(get_current_admin)):
        """Met les 8 publications de lancement dans la file de validation."""
        return await charger_kit(db)
