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
#   rubrique     : (facultatif) titre EXACT de la rubrique de la page Paramètres à atteindre au clic
#   lien         : (facultatif) écran à ouvrir au clic quand la nouveauté n'est pas dans les Paramètres
# Les plus récentes en premier.

NOUVEAUTES = [
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
        "lien": "/admin/loois-synchro",
    },
    {
        "lot": "68", "date": "2026-10-06",
        "titre": "🔄 Plateformes → Loois → Synchro",
        "description": "Tables HFSQL remontées vers MongoDB (e-Kol : Paiements, ElèveEdu), état, resynchronisation, visionneuse.",
        "lien": "/admin/loois-synchro",
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
        "lien": "/admin/plateformes-temps-reel",
    },
    {
        "lot": "65", "date": "2026-10-06",
        "titre": "🖥️ Postes et serveurs — versions déployées",
        "description": "Signal de présence de Loois et des serveurs (Ster, adLyn, beAuthentik, ALBARKA) : version, poste, dernier signal.",
        "lien": "/admin/plateformes-temps-reel",
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
