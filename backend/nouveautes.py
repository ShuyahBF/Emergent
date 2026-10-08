# nouveautes.py — cartes « Nouveautés de la semaine » de la page Paramètres (source UNIQUE).
#
# Règle permanente du propriétaire (06/10/2026, « Ça doit être systématique ! ») :
# à CHAQUE lot déployé (lot.py), ajouter ici au moins une entrée portant le MÊME numéro de lot.
# Un test (tests/test_regle_nouveautes.py) échoue si le lot courant de lot.py n'a pas sa carte.
#
# Champs de chaque entrée :
#   lot          : numéro du lot, identique à lot.py (ex. "68.3")
#   date         : date de mise en ligne, AAAA-MM-JJ (la carte reste affichée 7 jours)
#   titre        : titre court de la carte
#   description  : une ligne : ce que le lot apporte
#   rubrique     : titre EXACT de la rubrique de la page Paramètres où se règle la nouveauté (ouverte au clic)
#   lien         : seulement "/admin/settings" (nouveauté qui concerne la page Paramètres elle-même)
# Règle (07/10/2026) : une carte ne mène JAMAIS hors des Paramètres. Si la nouveauté n'a pas encore de rubrique,
# on la crée dans AdminSettings.jsx (réglages, état, bouton vers l'écran d'utilisation). Contrôlé par le test.
# Les plus récentes en premier.

NOUVEAUTES = [
    {
        "lot": "79.8", "date": "2026-10-08",
        "titre": "🗄️ Jauge des collections Atlas (500 par cluster)",
        "description": "Collections utilisées par base sur le cluster partagé, alerte WhatsApp avant le blocage.",
        "rubrique": "🗄️ Base Atlas — collections du cluster",
    },
    {
        "lot": "79.7", "date": "2026-10-08",
        "titre": "💰 Retards de paiement : un récapitulatif, vous choisissez qui relancer",
        "description": "Une liste numérotée chaque matin ; répondez « ok 1,2,5 » sur WhatsApp et Liluvine relance ces clients.",
        "rubrique": "Contrats — Seuil de retard de paiement (par défaut)",
    },
    {
        "lot": "79.6", "date": "2026-10-08",
        "titre": "🚧 Messages WhatsApp bloqués : nouvel écran dans le menu Liluvine",
        "description": "Tous les correspondants retenus par la barrière, remise dans la conversation en un clic ; serveur plus économe (réponses compressées).",
        "rubrique": "🚧 Barrière anti-rafale WhatsApp (messages sans réponse)",
    },
    {
        "lot": "79.5", "date": "2026-10-08",
        "titre": "💾 Sauvegarde complète R2 : erreur expliquée",
        "description": "Si R2 est illisible, la raison s'affiche clairement (identifiant de compte, accès…) sans jamais montrer de jeton.",
        "rubrique": "Sauvegarde complète (base de secours Atlas + R2)",
    },
    {
        "lot": "79.4", "date": "2026-10-08",
        "titre": "🔧 « Tout réaligner » : comptes rattachés par un parent",
        "description": "Les comptes liés à un ancien membre de l'entreprise rejoignent eux aussi le premier admin : plus aucun reste.",
        "rubrique": "Cohérence multi-utilisateurs (panoramique)",
    },
    {
        "lot": "79.3", "date": "2026-10-08",
        "titre": "🔧 « Tout réaligner » traite enfin tous les comptes",
        "description": "Les admins et superviseurs secondaires rejoignent le périmètre de leur entreprise ; les comptes démo restent isolés.",
        "rubrique": "Cohérence multi-utilisateurs (panoramique)",
    },
    {
        "lot": "79.2", "date": "2026-10-08",
        "titre": "📱 Abonnements Liluvine VIDAL : stockage R2 vérifié",
        "description": "Un identifiant de compte Cloudflare R2 mal saisi est signalé clairement ; aucun jeton n'apparaît plus dans les journaux.",
        "rubrique": "📱 S058f — Abonnements Liluvine VIDAL (essai, quota, formules)",
    },
    {
        "lot": "79.1", "date": "2026-10-08",
        "titre": "🔗 Carrousel partagé : envoi corrigé",
        "description": "Les cartes produit d'un carrousel partagé deviennent des cartes libres ; un envoi refusé affiche son motif.",
        "rubrique": "🖼️ Carrousel WhatsApp — modèles Meta et images IA",
    },
    {
        "lot": "79", "date": "2026-10-08",
        "titre": "✅ Carrousel : accord WhatsApp demandé d'un clic",
        "description": "Boutons Oui / Non envoyés au contact, accord noté dès qu'il clique ; lien et QR code d'accord à afficher.",
        "rubrique": "🖼️ Carrousel WhatsApp — modèles Meta et images IA",
    },
    {
        "lot": "79", "date": "2026-10-08",
        "titre": "🔗 Carrousels partagés entre comptes",
        "description": "L'admin ou un superviseur partage un carrousel par e-mail ; le destinataire le voit dans « Mes carrousels ».",
        "rubrique": "🖼️ Carrousel WhatsApp — modèles Meta et images IA",
    },
    {
        "lot": "78.3", "date": "2026-10-08",
        "titre": "🖼️ Carrousel : bouton d'envoi qui explique ce qu'il manque",
        "description": "Le lien par défaut suffit pour envoyer ; si le bouton est grisé, la liste de ce qui manque s'affiche à côté.",
        "rubrique": "🖼️ Carrousel WhatsApp — modèles Meta et images IA",
    },
    {
        "lot": "78.2", "date": "2026-10-07",
        "titre": "🖼️ Carrousel : statuts Meta à jour",
        "description": "« Actualiser les statuts Meta » relit l'approbation des modèles ; relecture automatique tant qu'un modèle est en attente.",
        "rubrique": "🖼️ Carrousel WhatsApp — modèles Meta et images IA",
    },
    {
        "lot": "78.1", "date": "2026-10-07",
        "titre": "🖼️ Carrousel : utilisateurs suivis et contacts destinataires",
        "description": "Clients, utilisateurs suivis et contacts se cochent par groupe ; les modèles Meta s'affichent par nombre de cartes.",
        "rubrique": "🖼️ Carrousel WhatsApp — modèles Meta et images IA",
    },
    {
        "lot": "78", "date": "2026-10-07",
        "titre": "🖼️ Carrousel : enregistrement automatique et rechargement",
        "description": "Le carrousel en cours est sauvegardé tout seul ; un envoi précédent se recharge d'un clic ; lien par défaut des cartes.",
        "rubrique": "🖼️ Carrousel WhatsApp — modèles Meta et images IA",
    },
    {
        "lot": "77", "date": "2026-10-07",
        "titre": "🖼️ Carrousels nommés, dupliqués, avec statut Meta",
        "description": "Enregistrez vos carrousels sous un nom, dupliquez-les, et voyez d'une pastille si Meta a approuvé leur modèle.",
        "rubrique": "🖼️ Carrousel WhatsApp — modèles Meta et images IA",
    },
    {
        "lot": "76.1", "date": "2026-10-07",
        "titre": "🖼️ Carrousel : App ID Meta retrouvé automatiquement",
        "description": "Plus besoin de saisir l'App ID : il est lu à partir du jeton WhatsApp pour créer les modèles du carrousel.",
        "rubrique": "🖼️ Carrousel WhatsApp — modèles Meta et images IA",
    },
    {
        "lot": "76", "date": "2026-10-07",
        "titre": "🖼️ Carrousel WhatsApp : modèles Meta créés d'un clic",
        "description": "Le bouton « Créer les modèles chez Meta » dépose les 9 modèles du carrousel (2 à 10 cartes) déjà conformes.",
        "rubrique": "🖼️ Carrousel WhatsApp — modèles Meta et images IA",
    },
    {
        "lot": "75", "date": "2026-10-07",
        "titre": "🖼️ Carrousel WhatsApp : images générées par l'IA",
        "description": "Pour chaque carte : une description, « Générer », puis « Utiliser cette image » remplit l'adresse de l'image.",
        "rubrique": "🖼️ Carrousel WhatsApp — modèles Meta et images IA",
    },
    {
        "lot": "74", "date": "2026-10-07",
        "titre": "🌙 Message d'absence WhatsApp",
        "description": "Texte fixe envoyé une fois par contact quand il écrit hors des heures d'ouverture (ou pendant les congés).",
        "rubrique": "🌙 Message d'absence WhatsApp",
    },
    {
        "lot": "74", "date": "2026-10-07",
        "titre": "🧾 Modèles Meta des contrats (paiement client, alerte de retard)",
        "description": "Confirmation de paiement client distincte du reçu de caisse ; modèle, langue et numéro de l'alerte de retard réglables.",
        "rubrique": "Contrats — Seuil de retard de paiement (par défaut)",
    },
    {
        "lot": "74", "date": "2026-10-07",
        "titre": "⏰ Rappels de RDV par modèle Meta",
        "description": "Le rappel 1 h avant le RDV peut partir par un modèle approuvé : il arrive même si le patient n'a pas écrit depuis 24 h.",
        "rubrique": "Webhook Planning consultations (RDV patients)",
    },
    {
        "lot": "73", "date": "2026-10-07",
        "titre": "🤖 Menu « Liluvine » et partage par superviseur",
        "description": "Tout Liluvine regroupé dans un menu dépliable ; choisissez ce que voit chaque superviseur (ex. support@).",
        "rubrique": "🤖 Liluvine — partage avec les superviseurs",
    },
    {
        "lot": "73", "date": "2026-10-07",
        "titre": "🔁 Demande d'autorisation d'appel renvoyée",
        "description": "Bouton « Renvoyer la demande » dans l'agenda et relance automatique après 24 h sans réponse (limites Meta).",
        "rubrique": "📅 Agenda d'appels de Liluvine et anniversaires",
    },
    {
        "lot": "73", "date": "2026-10-07",
        "titre": "🎙️ Voix clonée → voix de Liluvine",
        "description": "Dans Voice Studio, « 🤖 Transmettre à Liluvine » fait d'une voix clonée la voix de ses appels.",
        "rubrique": "🤖📞 Liluvine décroche les appels WhatsApp",
    },
    {
        "lot": "72", "date": "2026-10-07",
        "titre": "📞 Liluvine vous prévient quand elle appelle",
        "description": "Toast persistant (admin et superviseur) à chaque appel de l'agenda : contact, motif, puis résultat et résumé.",
        "rubrique": "📅 Agenda d'appels de Liluvine et anniversaires",
    },
    {
        "lot": "72", "date": "2026-10-07",
        "titre": "🚀 Écrans et webhook WhatsApp plus rapides",
        "description": "Meta reçoit sa réponse tout de suite ; Plateformes en temps réel et la roadmap s'ouvrent sans attente.",
        "rubrique": "⚡ Santé du serveur — blocages",
    },
    {
        "lot": "71.3", "date": "2026-10-07",
        "titre": "⚙️ Chaque nouveauté ouvre son paramétrage",
        "description": "Agenda et anniversaires, conversations WhatsApp, Loois, postes et serveurs, santé du serveur : nouvelles rubriques ici même.",
        "rubrique": "📅 Agenda d'appels de Liluvine et anniversaires",
    },
    {
        "lot": "71.3", "date": "2026-10-07",
        "titre": "↪ Modèle de repli par défaut pour les transferts",
        "description": "Le modèle approuvé choisi ici est proposé d'office dans « Transférer » pour les contacts hors fenêtre de 24 h.",
        "rubrique": "💬 Conversations WhatsApp — transfert et en-tête",
    },
    {
        "lot": "71.2", "date": "2026-10-07",
        "titre": "⚡ Premier message après redémarrage sans attente",
        "description": "Les modules d'IA (Claude, OpenAI, Gemini) se chargent en arrière-plan : le serveur ne se fige plus ~3 s au premier message WhatsApp.",
        "rubrique": "⚡ Santé du serveur — blocages",
    },
    {
        "lot": "71.1", "date": "2026-10-07",
        "titre": "⚡ Les Paramètres ne figent plus SAWALI",
        "description": "La première ouverture des Paramètres après un redémarrage ne bloque plus le serveur ~5 s ; tout blocage futur est noté dans les journaux.",
        "rubrique": "⚡ Santé du serveur — blocages",
    },
    {
        "lot": "71.1", "date": "2026-10-07",
        "titre": "🔘 En-tête de conversation en pictogrammes",
        "description": "Appeler, alerte propriétaire, journal des appels, sélectionner et actualiser : des icônes cliquables (libellé au survol).",
        "rubrique": "💬 Conversations WhatsApp — transfert et en-tête",
    },
    {
        "lot": "71", "date": "2026-10-06",
        "titre": "📋📞 Appels de Liluvine basés sur un formulaire",
        "description": "Dans l'agenda, « Mode de l'appel » : Liluvine pose les champs d'un formulaire et enregistre la réponse (badge « 📞 Appel »).",
        "rubrique": "📅 Agenda d'appels de Liluvine et anniversaires",
    },
    {
        "lot": "71", "date": "2026-10-06",
        "titre": "↪ Transférer des messages WhatsApp",
        "description": "Dans une conversation, « Transférer » un message ou une image à 10 contacts ; fenêtre de 24 h vérifiée avant l'envoi.",
        "rubrique": "💬 Conversations WhatsApp — transfert et en-tête",
    },
    {
        "lot": "70", "date": "2026-10-06",
        "titre": "📅 Agenda d'appels de Liluvine",
        "description": "Liluvine appelle à la date prévue (relance, prospection, suivi, compte rendu de maintenance…), pose vos questions et note les réponses.",
        "rubrique": "📅 Agenda d'appels de Liluvine et anniversaires",
    },
    {
        "lot": "70", "date": "2026-10-06",
        "titre": "🎂 Anniversaires des utilisateurs suivis",
        "description": "Date de naissance sur la fiche ; Liluvine appelle à l'heure réglée pour lire vos vœux (message WhatsApp si pas de réponse).",
        "rubrique": "📅 Agenda d'appels de Liluvine et anniversaires",
    },
    {
        "lot": "70", "date": "2026-10-06",
        "titre": "🗣️ Liluvine au téléphone : voix clonée et style oral",
        "description": "Voix clonée Story Studio utilisable ; plus de listes ni de « Bonjour » redit, une question à la fois, appelant reconnu par son nom.",
        "rubrique": "🤖📞 Liluvine décroche les appels WhatsApp",
    },
    {
        "lot": "69.2", "date": "2026-10-06",
        "titre": "🎧 Appels de Liluvine : son fluide et voix africaine",
        "description": "Plus de silences hachés pendant les appels ; voix à accent d'Afrique de l'Ouest au choix, « Écouter un essai » et ligne « Qualité audio » au journal.",
        "rubrique": "🤖📞 Liluvine décroche les appels WhatsApp",
    },
    {
        "lot": "69.1", "date": "2026-10-06",
        "titre": "⚡ Qdrant ne bloque plus SAWALI",
        "description": "La page Qdrant s'ouvre vite et ne fige plus le serveur (lecture en parallèle, gardée 60 s).",
        "rubrique": "RAG — Base de connaissance vectorielle (Qdrant) (S038)",
    },
    {
        "lot": "69", "date": "2026-10-06",
        "titre": "🤖📞 Liluvine décroche les appels WhatsApp",
        "description": "Réponse vocale automatique (toujours, après N s ou hors heures) avec son prompt système ; transcription et résumé au journal.",
        "rubrique": "🤖📞 Liluvine décroche les appels WhatsApp",
    },
    {
        "lot": "68.3", "date": "2026-10-06",
        "titre": "🆕 Nouveautés automatiques à chaque lot",
        "description": "Chaque lot déployé a désormais sa carte ici (contrôle automatique) ; flèches haut/bas sur fond gris.",
        "lien": "/admin/settings",
    },
    {
        "lot": "68.2", "date": "2026-10-06",
        "titre": "🗂️ Cartes « Nouveautés » remises à jour",
        "description": "Cartes des lots 65 à 68.1, y compris les écrans Plateformes et Loois → Synchro.",
        "lien": "/admin/settings",
    },
    {
        "lot": "68.1", "date": "2026-10-06",
        "titre": "🔑 Clés clients Loois et structures chiffrées",
        "description": "Une clé par client (montrée une seule fois), structure des tables téléchargée et gardée chiffrée sur le poste.",
        "rubrique": "🔄 Loois — synchronisation des tables et clés clients",
    },
    {
        "lot": "68", "date": "2026-10-06",
        "titre": "🔄 Plateformes → Loois → Synchro",
        "description": "Tables HFSQL remontées vers MongoDB (e-Kol : Paiements, ElèveEdu), état, resynchronisation, visionneuse.",
        "rubrique": "🔄 Loois — synchronisation des tables et clés clients",
    },
    {
        "lot": "67.1", "date": "2026-10-06",
        "titre": "📊 Historique des appels de Liluvine (durée et coût)",
        "description": "Date/heure, destinataire, durée, coût et synthèse par période ; export CSV.",
        "rubrique": "📊 Historique des appels de Liluvine (durée et coût)",
    },
    {
        "lot": "67", "date": "2026-10-06",
        "titre": "📞 Liluvine appelle le propriétaire à chaque message",
        "description": "Message relayé sur WhatsApp puis appel vocal de Liluvine, au plus un par client toutes les 30 min.",
        "rubrique": "📞 Liluvine appelle le propriétaire à chaque message",
    },
    {
        "lot": "66", "date": "2026-10-06",
        "titre": "🖥️ Postes et serveurs — lien « Détails »",
        "description": "Inventaire des postes Loois (système, mémoire, disques, réseau, tâches) et fiches du Parc créées automatiquement.",
        "rubrique": "🖥️ Postes et serveurs — signal de présence",
    },
    {
        "lot": "65", "date": "2026-10-06",
        "titre": "🖥️ Postes et serveurs — versions déployées",
        "description": "Signal de présence de Loois et des serveurs (Ster, adLyn, beAuthentik, ALBARKA) : version, poste, dernier signal.",
        "rubrique": "🖥️ Postes et serveurs — signal de présence",
    },
    {
        "lot": "63", "date": "2026-10-06",
        "titre": "🚧 Barrière anti-rafale WhatsApp (messages sans réponse)",
        "description": "Réponse automatique au n-ième message sans réponse, messages suivants retenus.",
        "rubrique": "🚧 Barrière anti-rafale WhatsApp (messages sans réponse)",
    },
    {
        "lot": "61", "date": "2026-10-06",
        "titre": "⛔ Liste noire des commandes « ! » (Liluvine WhatsApp)",
        "description": "Numéros interdits aux commandes « ! » avec message de refus de Liluvine.",
        "rubrique": "⛔ Liste noire des commandes « ! » (Liluvine WhatsApp)",
    },
]


def lot_courant() -> str:
    """Numéro du lot actuellement déployé (lot.py)."""
    from lot import LOT
    return str(LOT)


def nouveautes_valides() -> list[dict]:
    """Entrées bien formées seulement (une entrée abîmée ne doit jamais casser la page Paramètres)."""
    sortie = []
    for n in NOUVEAUTES:
        if not isinstance(n, dict) or not n.get("lot") or not n.get("titre") or not n.get("date"):
            continue
        sortie.append({
            "lot": str(n["lot"]),
            "date": str(n["date"]),
            "titre": str(n["titre"]),
            "description": str(n.get("description") or ""),
            "rubrique": n.get("rubrique") or None,
            "lien": n.get("lien") or None,
        })
    return sortie
