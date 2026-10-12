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

Lot 132 — un kit PAR PLATEFORME (beAuthentik, ZandGo, adLyn, bfmobility) : textes « À propos », visuels et
annonces de présentation au ton de chaque plateforme (dictionnaire KITS). Les routes prennent `?plateforme=<code>`
(beAuthentik par défaut, comme avant) ; chaque kit ne part que sur la Page propre de SA plateforme.
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

# ---------------------------------------------------------------------------
# Lot 132 — kits des nouvelles plateformes (« Produits + annonces de lancement »), chacun avec son ton :
#   ZandGo     : boutique en ligne, import et livraison ;
#   adLyn      : plateforme de services pour commerçants de tous secteurs, et vitrines de boutiques ;
#   bfmobility : location et transport de véhicules.
# Les textes ne promettent rien d'invérifiable (aucun prix, aucun délai chiffré) ; ils restent modifiables dans la
# file avant publication. Les visuels (profil, couverture, publications 1080 × 1350) sont aux couleurs de chaque
# plateforme, dans backend/static/kit_facebook/<code>/.
# ---------------------------------------------------------------------------
LIEN_ZANDGO = "https://zandgo.shop"
TAGS_ZANDGO = "#ZandGo #BoutiqueEnLigne #Livraison #Ouagadougou #BurkinaFaso"
KIT_ZANDGO: Dict[str, Any] = {
    "nom": "ZandGo", "couleurs": ["#03316E", "#FF7A0A"],
    "a_propos": {
        "nom": "ZandGo", "nom_utilisateur": "zandgo", "categorie": "Boutique en ligne",
        "presentation": "Votre boutique en ligne : des articles importés pour vous et livrés au Burkina Faso.",
        "description": (
            "ZandGo est la boutique en ligne qui fait venir pour vous des milliers d'articles et vous les livre au "
            "Burkina Faso.\n\n"
            "• Choisissez vos articles sur le site, avec leur prix en F CFA.\n"
            "• Payez simplement, en Mobile Money.\n"
            "• ZandGo s'occupe de la commande, de l'import et de la livraison.\n"
            "• Suivez votre commande étape par étape depuis votre compte.\n\n"
            f"Commandez sur {LIEN_ZANDGO}"
        ),
        "site_web": LIEN_ZANDGO, "bouton": {"libelle": "Acheter", "lien": LIEN_ZANDGO},
    },
    "publications": [
        {"fichier": "publication-1.jpg", "titre": "Bienvenue", "accroche": "Bienvenue chez ZandGo",
         "sous_titre": "Votre boutique en ligne, livrée au Burkina Faso",
         "texte": "Bienvenue sur la Page officielle de ZandGo 🛍️\n\n"
                  "ZandGo, c'est votre boutique en ligne : des milliers d'articles importés pour vous et livrés au "
                  "Burkina Faso, sans vous soucier des démarches.\n\n"
                  f"Abonnez-vous à la Page et découvrez le catalogue sur {LIEN_ZANDGO} 👉\n\n{TAGS_ZANDGO}"},
        {"fichier": "publication-2.jpg", "titre": "Comment commander", "accroche": "Commander, c'est simple",
         "sous_titre": "Choisir · Payer · Recevoir",
         "texte": "Comment commander sur ZandGo ? Trois étapes :\n\n"
                  "1️⃣ Choisissez vos articles sur le site.\n"
                  "2️⃣ Payez en Mobile Money.\n"
                  "3️⃣ Recevez votre commande au Burkina Faso.\n\n"
                  f"C'est parti : {LIEN_ZANDGO}\n\n{TAGS_ZANDGO}"},
        {"fichier": "publication-3.jpg", "titre": "L'import", "accroche": "On s'occupe de l'import",
         "sous_titre": "Vous choisissez, ZandGo fait venir",
         "texte": "L'import, c'est notre métier ✈️\n\n"
                  "Vous repérez un article, ZandGo le commande, le fait venir et vous le livre. Pas de démarches "
                  "compliquées, un seul interlocuteur.\n\n"
                  f"Faites votre choix sur {LIEN_ZANDGO}\n\n{TAGS_ZANDGO} #Import"},
        {"fichier": "publication-4.jpg", "titre": "Prix clairs", "accroche": "Des prix clairs",
         "sous_titre": "En F CFA, livraison au Burkina comprise",
         "texte": "Des prix clairs, en F CFA 💰\n\n"
                  "Le prix affiché sur ZandGo comprend la livraison au Burkina Faso : vous savez ce que vous payez "
                  "avant de commander.\n\n"
                  f"Voir les articles : {LIEN_ZANDGO}\n\n{TAGS_ZANDGO}"},
        {"fichier": "publication-5.jpg", "titre": "Suivi", "accroche": "Suivez votre colis",
         "sous_titre": "Chaque étape, depuis votre compte",
         "texte": "Où en est ma commande ? 📦\n\n"
                  "Depuis votre compte ZandGo, suivez votre commande étape par étape, de la validation à la "
                  "livraison. Une question ? Notre équipe vous répond sur WhatsApp.\n\n"
                  f"{LIEN_ZANDGO}\n\n{TAGS_ZANDGO}"},
        {"fichier": "publication-6.jpg", "titre": "À vous", "accroche": "Et vous, que cherchez-vous ?",
         "sous_titre": "De nouveaux articles arrivent régulièrement",
         "texte": "Mode, maison, high-tech, beauté… et vous, que cherchez-vous ? ✨\n\n"
                  "De nouveaux articles arrivent régulièrement sur ZandGo. Abonnez-vous à la Page pour les "
                  "découvrir ici en premier.\n\n"
                  f"Commandez sur {LIEN_ZANDGO} 👉\n\n{TAGS_ZANDGO}"},
    ],
}

LIEN_ADLYN = "https://adlynservice.com"
TAGS_ADLYN = "#adLyn #Commerce #Commerçants #Vitrine #BurkinaFaso"
KIT_ADLYN: Dict[str, Any] = {
    "nom": "adLyn", "couleurs": ["#0F2347", "#1668E3"],
    "a_propos": {
        "nom": "adLyn", "nom_utilisateur": "adlynservice", "categorie": "Service aux entreprises",
        "presentation": "La plateforme des commerçants de tous secteurs : caisse, stock et vitrine en ligne.",
        "description": (
            "adLyn est la plateforme de services des commerçants, quel que soit leur secteur.\n\n"
            "• Caisse, stock, factures et équipe au même endroit.\n"
            "• Une vitrine en ligne pour chaque boutique, à partager sur WhatsApp et Facebook.\n"
            "• Vos clients commandent depuis la vitrine et suivent leur commande.\n"
            "• Un QR code à afficher en boutique.\n\n"
            f"Inscrivez votre boutique sur {LIEN_ADLYN}"
        ),
        "site_web": LIEN_ADLYN, "bouton": {"libelle": "S'inscrire", "lien": LIEN_ADLYN},
    },
    "publications": [
        {"fichier": "publication-1.jpg", "titre": "Bienvenue", "accroche": "Bienvenue sur adLyn",
         "sous_titre": "La plateforme des commerçants",
         "texte": "Bienvenue sur la Page officielle d'adLyn 🏪\n\n"
                  "adLyn accompagne les commerçants de tous secteurs : gestion de la boutique, caisse, stock, et une "
                  "vitrine en ligne pour présenter vos articles.\n\n"
                  f"Abonnez-vous à la Page et découvrez adLyn sur {LIEN_ADLYN} 👉\n\n{TAGS_ADLYN}"},
        {"fichier": "publication-2.jpg", "titre": "La vitrine", "accroche": "Votre vitrine en ligne",
         "sous_titre": "Vos articles et vos prix, à partager partout",
         "texte": "Votre boutique a sa vitrine en ligne 🛒\n\n"
                  "Vos articles, leurs photos et leurs prix, sur une adresse à partager sur WhatsApp et Facebook, "
                  "avec un QR code à afficher dans votre boutique.\n\n"
                  f"Créez la vôtre : {LIEN_ADLYN}\n\n{TAGS_ADLYN}"},
        {"fichier": "publication-3.jpg", "titre": "La gestion", "accroche": "Caisse, stock, factures",
         "sous_titre": "Tout au même endroit",
         "texte": "Caisse, stock, factures : tout au même endroit 📊\n\n"
                  "Encaissez, suivez votre stock et éditez vos documents depuis un seul outil, sur ordinateur comme "
                  "sur téléphone.\n\n"
                  f"En savoir plus : {LIEN_ADLYN}\n\n{TAGS_ADLYN}"},
        {"fichier": "publication-4.jpg", "titre": "Tous secteurs", "accroche": "Pour tous les commerces",
         "sous_titre": "Téléphonie, mode, alimentation, beauté…",
         "texte": "Téléphonie, mode, alimentation, quincaillerie, beauté… 🧺\n\n"
                  "adLyn s'adapte à votre secteur : vos fiches articles, vos catégories et votre vitrine parlent le "
                  "langage de votre métier.\n\n"
                  f"{LIEN_ADLYN}\n\n{TAGS_ADLYN}"},
        {"fichier": "publication-5.jpg", "titre": "Les commandes", "accroche": "Vos clients commandent",
         "sous_titre": "Depuis la vitrine, et suivent leur commande",
         "texte": "Vos clients commandent depuis votre vitrine ✅\n\n"
                  "Ils choisissent, commandent et suivent leur commande ; vous la préparez depuis votre espace "
                  "adLyn.\n\n"
                  f"Ouvrez votre vitrine : {LIEN_ADLYN}\n\n{TAGS_ADLYN}"},
        {"fichier": "publication-6.jpg", "titre": "Les boutiques", "accroche": "Les boutiques adLyn",
         "sous_titre": "Bientôt présentées sur cette Page",
         "texte": "Bientôt sur cette Page : les articles des boutiques adLyn ✨\n\n"
                  "Les boutiques qui le souhaitent verront leurs articles présentés ici. Commerçant ? Inscrivez "
                  "votre boutique et faites-vous connaître.\n\n"
                  f"{LIEN_ADLYN} 👉\n\n{TAGS_ADLYN}"},
    ],
}

LIEN_BFMOBILITY = "https://bfmobility-frontend.onrender.com"
TAGS_BFMOBILITY = "#bfmobility #Location #Transport #Chauffeur #Ouagadougou"
KIT_BFMOBILITY: Dict[str, Any] = {
    "nom": "bfmobility", "couleurs": ["#1A1650", "#D62B63"],
    "a_propos": {
        "nom": "bfmobility", "nom_utilisateur": "bfmobility", "categorie": "Service de location de voitures",
        "presentation": "Location de véhicules et transport avec chauffeur au Burkina Faso : réservez en ligne.",
        "description": (
            "bfmobility, c'est la location de véhicules et le transport avec chauffeur au Burkina Faso.\n\n"
            "• Une classe de véhicule pour chaque besoin, avec ses tarifs affichés.\n"
            "• À la course, à l'heure ou à la journée.\n"
            "• Le prix estimé avant de réserver.\n"
            "• Paiement en Mobile Money ou par carte.\n\n"
            f"Réservez sur {LIEN_BFMOBILITY}"
        ),
        "site_web": LIEN_BFMOBILITY, "bouton": {"libelle": "Réserver", "lien": LIEN_BFMOBILITY},
    },
    "publications": [
        {"fichier": "publication-1.jpg", "titre": "Bienvenue", "accroche": "Bienvenue chez bfmobility",
         "sous_titre": "Location et transport de véhicules",
         "texte": "Bienvenue sur la Page officielle de bfmobility 🚗\n\n"
                  "Location de véhicules et transport avec chauffeur au Burkina Faso : choisissez votre véhicule, "
                  "voyez le tarif et réservez en ligne.\n\n"
                  f"Abonnez-vous à la Page et réservez sur {LIEN_BFMOBILITY} 👉\n\n{TAGS_BFMOBILITY}"},
        {"fichier": "publication-2.jpg", "titre": "Les classes", "accroche": "Un véhicule pour chaque besoin",
         "sous_titre": "Choisissez la classe, voyez le tarif",
         "texte": "Un véhicule pour chaque besoin 🚙\n\n"
                  "Citadine, berline, confort ou grand véhicule : chaque classe a ses tarifs affichés sur le site, "
                  "avec les photos des véhicules.\n\n"
                  f"Comparez sur {LIEN_BFMOBILITY}\n\n{TAGS_BFMOBILITY}"},
        {"fichier": "publication-3.jpg", "titre": "Le prix", "accroche": "Le prix avant de partir",
         "sous_titre": "Estimez votre trajet en ligne",
         "texte": "Le prix avant de partir 💰\n\n"
                  "Indiquez votre départ et votre arrivée : le site estime la distance, la durée et le prix de votre "
                  "trajet avant que vous réserviez.\n\n"
                  f"Estimez votre trajet : {LIEN_BFMOBILITY}\n\n{TAGS_BFMOBILITY}"},
        {"fichier": "publication-4.jpg", "titre": "La formule", "accroche": "À la course, à l'heure, à la journée",
         "sous_titre": "Vous choisissez la formule",
         "texte": "À la course, à l'heure ou à la journée ⏱️\n\n"
                  "Un trajet en ville, une demi-journée de rendez-vous ou une journée complète : choisissez la "
                  "formule qui vous convient.\n\n"
                  f"{LIEN_BFMOBILITY}\n\n{TAGS_BFMOBILITY}"},
        {"fichier": "publication-5.jpg", "titre": "Le paiement", "accroche": "Payez comme vous voulez",
         "sous_titre": "Mobile Money ou carte bancaire",
         "texte": "Payez comme vous voulez 📱\n\n"
                  "Réglez votre réservation en Mobile Money ou par carte bancaire, directement en ligne.\n\n"
                  f"Réservez sur {LIEN_BFMOBILITY}\n\n{TAGS_BFMOBILITY}"},
        {"fichier": "publication-6.jpg", "titre": "Les chauffeurs", "accroche": "Vous êtes chauffeur ?",
         "sous_titre": "Rejoignez l'équipe bfmobility",
         "texte": "Vous êtes chauffeur professionnel ? 🧑‍✈️\n\n"
                  "bfmobility recrute : déposez votre candidature directement sur le site, notre équipe vous "
                  "recontacte.\n\n"
                  f"Candidatez sur {LIEN_BFMOBILITY}\n\n{TAGS_BFMOBILITY} #Emploi"},
    ],
}

# Tous les kits, par code de plateforme (code de l'émetteur Liluvine)
KITS: Dict[str, Dict[str, Any]] = {
    "beauthentik": {"nom": "beAuthentik", "couleurs": ["#f4256a", "#ff7a45"], "a_propos": A_PROPOS,
                    "publications": PUBLICATIONS},
    "zandgo": KIT_ZANDGO,
    "adlyn": KIT_ADLYN,
    "bfmobility": KIT_BFMOBILITY,
}

# Liste blanche des fichiers servis publiquement, par plateforme
FICHIERS = {code: {"photo-profil.jpg", "couverture.jpg", *(p["fichier"] for p in k["publications"])}
            for code, k in KITS.items()}


def membre_id_kit(plateforme: str, rang: int) -> str:
    """Identifiant de la publication de kit n° rang (sert à ne jamais la charger deux fois)."""
    return f"kit-{plateforme}-{rang}"


async def url_fichier(db, plateforme: str, fichier: str) -> str:
    """Adresse publique d'un visuel du kit (Facebook la télécharge lors de la publication)."""
    from routes.liluvine_relais import url_publique
    return f"{await url_publique(db)}/api/facebook/kit/{plateforme}/{fichier}"


def kit_ou_404(plateforme: str) -> Dict[str, Any]:
    """Kit d'une plateforme connue (sinon 404)."""
    kit = KITS.get(plateforme)
    if not kit:
        raise HTTPException(status_code=404, detail=f"Aucun kit de lancement pour « {plateforme} »")
    return kit


async def charger_kit(db, plateforme: str = "beauthentik") -> Dict[str, Any]:
    """Met les publications du kit dans la file « à valider » (celles déjà chargées sont ignorées).
    Lot 132 : exige la Page PROPRE de cette plateforme (jamais la page de SAWALI)."""
    from routes.facebook_animation import page_de
    kit = kit_ou_404(plateforme)
    publications = kit["publications"]
    s = await db.settings.find_one({"_id": "global"}) or {}
    if not page_de(s, plateforme):
        raise HTTPException(status_code=400, detail=f"Choisissez d'abord la Page de la plateforme ({kit['nom']}) "
                                                    "dans « Page de publication » : le kit n'est jamais publié sur la page de SAWALI.")
    crees, debut = 0, datetime.now(timezone.utc)
    for rang, pub in enumerate(publications, start=1):
        mid = membre_id_kit(plateforme, rang)
        if await db.fb_publications.find_one({"membre_id": mid}, {"_id": 1}):
            continue   # déjà chargée (quel que soit son statut)
        await db.fb_publications.insert_one({
            "id": str(uuid.uuid4()), "type": "kit", "plateforme": plateforme, "membre_id": mid, "rang": rang,
            "total_kit": len(publications),
            "prenom": pub["titre"], "image_url": await url_fichier(db, plateforme, pub["fichier"]),
            "texte": pub["texte"], "statut": "a_valider",
            # cree_le décroissant avec le rang : la file (triée du plus récent au plus ancien) affiche 1 → N
            "cree_le": (debut - timedelta(seconds=rang)).isoformat(),
        })
        crees += 1
    return {"crees": crees, "total": len(publications)}


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
    async def lire_kit(plateforme: str = "beauthentik", _: dict = Depends(get_current_admin)):
        """Textes « À propos », adresses des visuels et nombre de publications du kit déjà chargées
        (lot 132 : `?plateforme=zandgo|adlyn|bfmobility`, beAuthentik par défaut)."""
        kit = kit_ou_404(plateforme)
        charges = await db.fb_publications.count_documents({"type": "kit", "plateforme": plateforme})
        publies = await db.fb_publications.count_documents({"type": "kit", "plateforme": plateforme, "statut": "publie"})
        return {
            "plateforme": plateforme, "nom": kit["nom"], "couleurs": kit["couleurs"], "a_propos": kit["a_propos"],
            "photo_profil": await url_fichier(db, plateforme, "photo-profil.jpg"),
            "couverture": await url_fichier(db, plateforme, "couverture.jpg"),
            "publications": [{"rang": i, "titre": p["titre"], "image_url": await url_fichier(db, plateforme, p["fichier"])}
                             for i, p in enumerate(kit["publications"], start=1)],
            "charges": charges, "publies": publies, "total": len(kit["publications"]),
        }

    @api.post("/admin/facebook/animation/kit/charger", tags=["Admin — Facebook"])
    async def charger(plateforme: str = "beauthentik", _: dict = Depends(get_current_admin)):
        """Met les publications de lancement de la plateforme dans la file de validation."""
        return await charger_kit(db, plateforme)
