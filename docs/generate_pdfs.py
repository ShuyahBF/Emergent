#!/usr/bin/env python3
"""Generate the 3 SAWALI / Loois documentation PDFs (in French)."""
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak,
    Table, TableStyle, KeepTogether, NextPageTemplate, PageTemplate,
    BaseDocTemplate, Frame,
)
from reportlab.pdfgen import canvas

SCR = Path("/app/docs/screenshots")
SCR_NS = Path("/app/docs/screenshots/nosidebar")
OUT = Path("/app/docs")
OUT.mkdir(exist_ok=True)

BRAND_PRIMARY = colors.HexColor("#1e40af")  # sawali blue
BRAND_ACCENT = colors.HexColor("#10b981")   # emerald
BRAND_BG = colors.HexColor("#f8fafc")
BRAND_DARK = colors.HexColor("#0f172a")
BRAND_MUTED = colors.HexColor("#64748b")

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], textColor=BRAND_PRIMARY, fontSize=20, spaceAfter=12, leading=24)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], textColor=BRAND_DARK, fontSize=14, spaceAfter=8, leading=18)
H3 = ParagraphStyle("H3", parent=styles["Heading3"], textColor=BRAND_PRIMARY, fontSize=12, spaceAfter=6, leading=15)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=14, alignment=TA_JUSTIFY, spaceAfter=6)
CAPTION = ParagraphStyle("Caption", parent=styles["Italic"], fontSize=8, textColor=BRAND_MUTED, alignment=TA_CENTER, spaceAfter=10)
TOC_ENTRY = ParagraphStyle("Toc", parent=styles["BodyText"], fontSize=10, leading=16)
COVER_TITLE = ParagraphStyle("CoverT", parent=styles["Title"], fontSize=28, textColor=BRAND_PRIMARY, alignment=TA_CENTER, leading=34, spaceAfter=8)
COVER_SUB = ParagraphStyle("CoverS", parent=styles["BodyText"], fontSize=14, textColor=BRAND_DARK, alignment=TA_CENTER, leading=18, spaceAfter=20)


def img(path: Path, width=15 * cm) -> Image:
    """Insert an image, scaled to a target width while preserving ratio."""
    from PIL import Image as PILImage
    im = PILImage.open(path)
    w_px, h_px = im.size
    ratio = h_px / w_px
    return Image(str(path), width=width, height=width * ratio)


def page_footer(c: canvas.Canvas, doc):
    c.saveState()
    c.setFont("Helvetica", 8)
    c.setFillColor(BRAND_MUTED)
    # Footer line
    c.setStrokeColor(colors.HexColor("#e2e8f0"))
    c.line(2 * cm, 1.6 * cm, A4[0] - 2 * cm, 1.6 * cm)
    c.drawString(2 * cm, 1.1 * cm, "SAWALI SMART SYSTEMS — Espace Loois")
    c.drawRightString(A4[0] - 2 * cm, 1.1 * cm, f"Page {doc.page}")
    c.restoreState()


SECTIONS = [
    ("Tableau de bord",
     "01_dashboard.jpeg",
     "Point d'entrée du portail Loois. Affiche une vue d'ensemble : rendez-vous du jour, briefing de bienvenue avec santé quotidienne (tickets clos hier, ouverts aujourd'hui, taux de réponse WA en 24h), notes récentes, messages non lus et synthèse d'activité.",
     [
         ("Briefing « Bienvenue »", "Synthèse à l'ouverture : rapports créés, notes, tâches, santé quotidienne. Cliquez « J'ai lu » pour masquer jusqu'à demain."),
         ("Synthèse de votre activité", "3 compteurs en temps réel : Rapports / Notes / Tâches sur la période courante."),
         ("Santé quotidienne", "4 indicateurs : Tickets clos hier, Ouverts aujourd'hui, Taux de réponse WA dans la fenêtre 24h, Messages envoyés."),
         ("Notes récentes", "Vos notes des 3 derniers jours (configurable dans AdminSettings)."),
         ("Sidebar — Tableau de bord", "Navigation principale, badges de notifications (rendez-vous, messages, tickets)."),
     ]),
    ("Caisse / Facturation",
     "02_cash.jpeg",
     "Module central de gestion financière : caisse, factures, dépenses, catalogue produits, clients en compte, modes de paiement, formes juridiques. Inclut un bouton « Payer (Mobile Money) » réservé aux Caissiers Admin/Superviseur.",
     [
         ("Onglet Caisse", "Reçus d'encaissement avec colonnes N°, Date, Client en compte, Montant, Paiement, Caissier, WhatsApp (statut envoi reçu)."),
         ("Onglet Facturation", "Création/édition des factures avec TVA, remises, paiements multiples."),
         ("Onglet Dépenses", "Suivi des dépenses caisse avec justificatifs et catégories."),
         ("Onglet Catalogue", "Produits/services facturables avec prix et taxes."),
         ("Clients en compte", "Gestion des comptes clients (créditeur/débiteur) avec relances automatiques."),
         ("Bouton Payer (Mobile Money)", "Visible uniquement pour les utilisateurs Caissiers ET Admin/Superviseur. Permet de déclencher des décaissements PawaPay (salaires, avances)."),
         ("CSV / PDF / Corbeille", "Export des reçus, impression PDF, accès à la corbeille des éléments supprimés."),
     ]),
    ("Tickets d'intervention",
     "03_tickets.jpeg",
     "Historique complet des interventions techniques. Chaque ticket porte une référence unique (INT-AAAA-NNNN) avec contact lié, technicien assigné, statut (Terminée / Annulée / En cours / Suspendue) et note vocale optionnelle.",
     [
         ("Référence", "Numérotation séquentielle par client et par année (TKT-2026-NNNN). Conservée même après archivage."),
         ("Titre du ticket", "Synthèse du motif : « Logiciel bloqué », « Demande de formation », etc. Configurable dans AdminSettings."),
         ("Client lié", "Sélection obligatoire du client à l'origine du ticket. Filtre disponible en haut de la liste."),
         ("Date", "Date de création/clôture du ticket."),
         ("Technicien", "Personne en charge (peut être réassignée à tout moment)."),
         ("Statut", "Terminée, Annulée, En cours, Suspendue, En attente."),
         ("Note vocale", "Enregistrement audio joint à la résolution (transcrit automatiquement)."),
         ("Bulle flottante « Nouveau ticket »", "Bouton accessible depuis toute page du portail (bas-droite). Ouvre une modale rapide pour saisir Client + Motif + Rapporteur + Date + numéro."),
     ]),
    ("Liluvine PRO — Assistant IA",
     "04_liluvine.jpeg",
     "Assistant interne propulsé par Claude Sonnet 4.6, avec accès en lecture seule à vos données : contacts, tickets, paiements, RDV, notes. Réponses contextualisées, prompt système personnalisable par tenant.",
     [
         ("Liste des conversations", "Toutes / Web / WA / FB / SMS. Conversations par canal et par contact, recherche full-text."),
         ("Zone de chat", "Posez des questions en langage naturel : « Combien de tickets ouverts cette semaine ? », « Liste mes 5 derniers paiements PawaPay », « Rédige un SMS de rappel RDV poli »."),
         ("Suggestions rapides", "3 chips de questions courantes (cliquables) pour démarrer instantanément."),
         ("Champ de saisie", "Entrée pour envoyer, Shift+Entrée pour saut de ligne. Détecte automatiquement les mots-clés métier (contacts, tickets, paiements, RDV, notes)."),
         ("Auto-réponse WhatsApp", "Liluvine peut répondre automatiquement aux WhatsApp entrants (configurable, avec escalade humaine si nécessaire)."),
         ("Personnalisation du prompt", "Section AdminSettings → « Liluvine PRO — Prompt système » pour adapter le ton et les règles à votre métier."),
     ]),
    ("Inbox unifiée (WA + Messages + SMS)",
     "05_inbox.jpeg",
     "Centre de messagerie omnichannel : conversations WhatsApp, Messenger, SMS regroupées dans une seule interface. Aperçu des messages non lus, recherche par contact, marquage lu/non-lu, réponse rapide.",
     [
         ("Onglets canaux", "Toutes / Web / WA / FB / SMS. Filtre instantané par canal."),
         ("Liste des conversations", "Triée par dernière activité. Badge WA / FB / SMS visible à droite, indicateur de message non-lu (point coloré)."),
         ("Recherche", "Filtrage des conversations par nom, numéro ou contenu."),
         ("Bouton « + Nouvelle »", "Démarrer une conversation manuellement (utile pour les contacts inconnus)."),
         ("Importer un contact inconnu", "Quand un WA arrive d'un numéro non enregistré, un bouton « Importer ce contact » apparaît pour l'ajouter au répertoire en 1 clic."),
     ]),
    ("Centre de Messagerie (Contacts)",
     "06_contacts.jpeg",
     "Répertoire centralisé de tous les contacts (téléphone, WhatsApp, email). Synchronisation avec les tickets et historique de messagerie. Gestion des doublons, tags, partage entre utilisateurs.",
     [
         ("Liste des contacts", "Affichage avec photo/initiales, nom, numéros, tags, propriétaire."),
         ("Recherche & filtres", "Par nom, numéro, tag, propriétaire, source (manuel / Ticket bubble / WA OTP, etc.)."),
         ("Détail d'un contact", "Historique complet : messages WA/SMS, tickets, paiements, notes. Bouton « Ouvrir un ticket » directement disponible."),
         ("Partage de contact", "Marquer un contact comme partagé pour qu'il soit visible par toute l'équipe (RGPD conforme)."),
         ("Anonymisation RGPD", "Bouton de suppression conforme au droit à l'oubli (anonymise les références sans casser les liens historiques)."),
     ]),
    ("Notes & Tâches",
     "07_notes.jpeg",
     "Système Keep-style de notes et checklists (tâches). Notes audio (voice memos) transcrites automatiquement, notes texte avec markdown, checklists avec cases à cocher persistées, partage public/privé.",
     [
         ("Note texte", "Markdown supporté, tags, partage, attachement de fichiers (images, PDF avec OCR automatique)."),
         ("Note vocale", "Enregistrement audio dans le navigateur, transcrit en français via Whisper."),
         ("Note avec checklist", "Liste de tâches à cocher (TODO). Synchro WhatsApp bidirectionnelle : marquer une tâche faite envoie une notification WA au contact concerné."),
         ("Partage", "Public (visible par toute l'équipe) ou Privé (vous seul)."),
         ("Recherche", "Full-text dans le contenu des notes, transcriptions et tags."),
     ]),
    ("AdminSettings — Configuration",
     "08_admin_settings.jpeg",
     "Centre névralgique de configuration : intégrations (WhatsApp Meta, SMS, Stripe, PawaPay, Google), templates de notifications, branding (logo, couleurs), modules activables par client, secrets, sécurité (OTP, captcha, blacklist IP).",
     [
         ("WhatsApp Business API", "Access token, phone_number_id, templates par cas d'usage (tickets, factures, OTP login)."),
         ("SMS multi-fournisseurs", "Orange, Moov, Telecel, OVH. Configuration des credentials, coût unitaire, fallback automatique."),
         ("Stripe Checkout & Webhook", "Clé API, secret webhook, URL à coller dans Stripe Dashboard. Coupons paramétrables (% ou XOF, expiration, max utilisations)."),
         ("PawaPay Payouts", "Mobile Money (Orange/Moov/Telecel) pour décaissements salaires et avances."),
         ("Liluvine PRO — Prompt système", "Personnalisation du ton de l'assistant IA par tenant."),
         ("Suivi des actions (audit)", "Historique des modifications avec filtre temporel (par défaut Aujourd'hui)."),
         ("RGPD & sécurité", "Captcha v2, blacklist IP, anonymisation, journaux d'audit, OTP par email/WhatsApp."),
     ]),
    ("Usage & Facturation",
     "09_admin_usage.jpeg",
     "Tableau de bord administrateur : consommation des services facturables (WA, SMS, IA, paiements), connexions/pages visitées, dernière activité par utilisateur, top pages, carte de chaleur des heures d'activité.",
     [
         ("Compteurs WA / SMS / Coût", "Compteurs par canal sur 7/30/90/180 jours, taux d'échec, coût estimé."),
         ("Visites de pages", "Volume de pages consultées par utilisateurs et sociétés actives."),
         ("Top pages visitées", "Classement des modules les plus consultés."),
         ("Carte de chaleur", "Heatmap des heures d'activité (UTC) par jour de la semaine."),
         ("Stats SMS par fournisseur", "Délai moyen d'envoi, coût estimé (XOF), dernier échec (timestamp + raison) par Orange/Moov/Telecel/OVH."),
         ("Export CSV", "Téléchargement du détail pour analyse externe."),
     ]),
    ("Régie publicitaire (Ad Banners) — Complète",
     "11_ad_banners.jpeg",
     "Module complet de gestion de bannières publicitaires : création/édition/A/B testing, mesure CTR, paiement self-service Stripe, mise à jour libre-service du visuel par l'annonceur, dashboard temps-réel (WebSocket), rappels d'expiration automatiques (Email + WhatsApp), plan d'optimisation IA via Claude Haiku 4.5. Disponible dans le menu Admin → Régie publicitaire.",
     [
         ("Liste & cartes statistiques", "Liste des bannières avec totaux (impressions, clics, CTR, dépense). Cartes en haut : nombre de bannières actives, total impressions, total clics, dépense cumulée."),
         ("Bouton « Nouvelle bannière »", "Ouvre le formulaire complet en bas de page. Tous les champs ci-dessous se trouvent dans ce formulaire."),
         ("Champs basiques", "Nom interne, nom de l'annonceur, URL média (image/vidéo via uploader 20 Mo max), URL de destination (où clique l'utilisateur), placement (Public / Portail interne / Les deux), bouton Animation (effet pulsé)."),
         ("Champs budget", "Budget total alloué (XOF), coût par impression (CPM divisé), coût par clic (CPC). Auto-pause de la bannière dès que le budget est épuisé."),
         ("Dates", "Date de démarrage (la bannière n'apparaît pas avant), date d'expiration (auto-pause à minuit ce jour-là). Si laissé vide, pas de limite."),
         ("Dimensions d'affichage (fix9z5)", "Section bleue. 4 modes au choix : Auto (responsive 64/80px de haut), Ratio (% largeur × aspect-ratio configurable 16:9/21:9/4:1/3:1/2:1/1:1/4:5/9:16/personnalisé), Pourcentage (% largeur + hauteur fixe en px), Fixe (largeur+hauteur exactes en px). Slider de largeur, choix object-fit (cover/contain/fill). APERÇU EN DIRECT mis à jour à chaque modification."),
         ("Test A/B (fix9z6)", "Section violette. Toggle « Activer le mode A/B ». Si activé, uploadez une variante B (média + URL cible distincts). Rotation aléatoire 50/50 à chaque affichage. Les statistiques distinguent les performances par variante. Badge 🏆 GAGNANTE automatique dès qu'une variante atteint un meilleur CTR (min. 30 impressions par variante)."),
         ("Contact annonceur + rappels (fix9z6+7)", "Section verte. Email + Téléphone (WhatsApp) de l'annonceur. Toggle 'Rappel par email' + Toggle 'Rappel par WhatsApp' (les deux indépendants). Délai en jours (1–30, défaut 3). Le cron quotidien 09h30 Africa/Abidjan envoie automatiquement un rappel avec le bilan campagne et un lien direct vers le rapport public."),
         ("Boutons par ligne", "Stats (modale détaillée avec graphique journalier + A/B breakdown si activé), Lien partageable (copie l'URL /ads/{slug}?token=... pour l'annonceur), Régénérer token (révoque l'ancien lien), Pause/Activer, Modifier, Supprimer."),
         ("Modale Statistiques", "Cartes Vues / Clics / CTR / Dépensé. Si A/B actif : panel comparatif côte à côte avec badge GAGNANTE. Historique journalier (date + impressions + clics + dépense)."),
         ("Inbox renouvellements", "Section fuchsia apparaît automatiquement quand un annonceur soumet une demande de renouvellement via le rapport public. Affiche le nom, contact, budget souhaité, durée demandée, message. Bouton 'Marquer traitée'."),
         ("Dashboard temps-réel (fix9z7)", "Panel 'Bannières actives en temps réel' en haut de page. WebSocket /api/ws/ad-banners-live. Badge 'Connecté' (vert) ou 'Hors-ligne — reconnexion…' (rouge). Compteurs animés (flash bleu sur impression, violet sur clic). Feed des 5 derniers événements (CLIC / VUE) avec variante (A ou B), nom de la bannière et heure."),
     ]),
    ("Rapport public annonceur — /ads/{slug}?token=…",
     "12_ad_report_public.jpeg",
     "Page publique sans login destinée à l'annonceur. Reçoit toutes les statistiques de SA campagne en temps réel + plusieurs actions self-service. URL unique générée à la création de la bannière (ou régénérable). Aucune donnée des autres campagnes/annonceurs n'est exposée.",
     [
         ("En-tête campagne", "Logo SAWALI, nom de la campagne, nom annonceur, badge 'Active' / 'Suspendue', date d'expiration."),
         ("Cartes KPI", "Affichages (icône œil bleue), Clics (souris violette), CTR (% emerald), Dépense (wallet sky). Mise à jour auto toutes les ~5 secondes (REFRESH_INTERVAL_MS)."),
         ("Section Budget", "Barre de progression colorée (vert <70% / orange 70-90% / rouge >90%) avec restant en mono."),
         ("Graphique tendance 30 jours (fix9z5)", "Sparkline SVG avec 2 courbes (sky=affichages, violet=clics) sur 30 jours. Totaux + CTR moyen + dépense affichés au-dessus du graphique."),
         ("Demande de renouvellement (fix9z5)", "Section fuchsia avec formulaire (nom, email, téléphone, budget souhaité, durée, message). À l'envoi, crée une demande visible dans l'inbox admin."),
         ("Paiement en ligne (fix9z8)", "Section bleue 'Payer en ligne · renouvellement instantané'. Formulaire montant XOF + durée + email reçu. Bouton 'Payer X XOF' → redirection Stripe Checkout (conversion XOF→EUR 655,957). Au retour : extension automatique de la date d'expiration + crédit du budget."),
         ("Mise à jour libre-service du visuel (fix9z8)", "Section ambre 'Mettre à jour mon visuel'. Aperçu avant/après côte à côte. Uploader (20 Mo max image/vidéo) + champ URL de destination modifiable. Bouton Enregistrer → PUT /api/public/ads-report/{slug}/media. Whitelist stricte : seuls image_url, media_kind, target_url et variant_b_* sont modifiables ; le budget, le placement, les dates restent admin-only. Audit log dans ad_self_service_updates."),
         ("Plan de campagne IA (fix9z9)", "Section violette 'Plan de campagne IA · Premium'. Bouton 'Générer mon plan IA' → POST /api/public/ads-report/{slug}/ai-plan. Claude Haiku 4.5 analyse les performances et renvoie 4 recommandations : (1) Idée de visuel (description prête à utiliser pour Gemini Nano Banana), (2) 3 slogans/CTA alternatifs, (3) Budget mensuel optimal en XOF, (4) Justification (selon CTR : <0.5% privilégie le visuel, 0.5-2% les slogans, >2% l'augmentation budget). Cache serveur 6h pour maîtriser les coûts IA. Boutons 'Copier' sur chaque suggestion."),
         ("Historique journalier", "Tableau date + impressions + clics + spent à droite de la page (les 30 derniers jours par défaut)."),
     ]),
    ("Sécurité — Déconnexion automatique par inactivité (S009 / fix9z10)",
     "13_idle_logout.jpeg",
     "Mécanisme de sécurité qui déconnecte automatiquement tout utilisateur (admin, superviseur, client, équipe) après N minutes d'inactivité (souris, clavier, scroll, tactile). Empêche les sessions ouvertes oubliées en fin de journée. Configurable dans Admin → Paramètres → Sécurité.",
     [
         ("Préréglages rapides", "Boutons : Désactivé, 5 min, 10 min, 15 min, 30 min, 1 h. Cliquer applique immédiatement après sauvegarde."),
         ("Valeur personnalisée", "Champ numérique 0-120 minutes (0 = désactivé). Le paramètre est lu à la connexion via GET /api/me/idle-config."),
         ("Modal de prévenance", "30 secondes avant l'expiration, une fenêtre modale rouge s'ouvre avec compte à rebours visible, bouton « Rester connecté(e) » (réarme le timer) et « Se déconnecter maintenant » (logout immédiat)."),
         ("Déconnexion effective", "À expiration : suppression du token côté navigateur, redirection vers /login, toast d'information « Session expirée par inactivité »."),
         ("Activité détectée", "mousemove, mousedown, keydown, scroll, touchstart, click — chaque événement réarme le timer."),
         ("Périmètre", "S'applique à toutes les sessions actives du système. Le changement de valeur dans /admin/settings prend effet à la prochaine connexion de chaque utilisateur."),
     ]),

    ("Site public — sawalismartsystems.com",
     "10_home_public.jpeg",
     "Vitrine marketing du portail. Sections principales : Missions, Spécialisations, Catalogue produits, Études de cas, Abonnements, Témoignages, Demande RDV, Contact, Politiques de confidentialité.",
     [
         ("Header / Navigation", "Logo, liens vers les sections, badge « Équipe joignable 24/7 » avec statut temps réel, bouton « Mon espace », CTA « Réserver un rendez-vous »."),
         ("Hero", "Compteur visites en temps réel + accroche « L'ingénierie logicielle au service de votre transformation »."),
         ("CTAs", "« Réserver un rendez-vous », « Découvrir nos spécialisations », « Espace Loois », « Découvrir en 30s via WhatsApp » (connexion OTP express)."),
         ("Statistiques", "10+ années d'expérience, 50+ projets livrés, 30+ clients satisfaits, 24/7 disponibilité."),
         ("Bandeau RGPD cookies", "Bannière granulaire (Nécessaires / Préférences / Analytics / Marketing) avec persistance localStorage."),
     ]),
]


def build_user_guide():
    """Document A — Guide utilisateur détaillé avec sommaire."""
    out = OUT / "A_Guide_Utilisateur_SAWALI_Loois.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=A4,
                             leftMargin=2 * cm, rightMargin=2 * cm,
                             topMargin=2 * cm, bottomMargin=2.2 * cm)
    story = []
    # COVER
    story.append(Spacer(1, 4 * cm))
    story.append(Paragraph("Guide Utilisateur", COVER_TITLE))
    story.append(Paragraph("SAWALI SMART SYSTEMS — Espace Loois", COVER_SUB))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        "Manuel complet d'utilisation du portail métier : tableau de bord, caisse, tickets, assistant IA Liluvine, messagerie unifiée, configuration administrateur.",
        ParagraphStyle("CoverDesc", parent=BODY, alignment=TA_CENTER, textColor=BRAND_MUTED, fontSize=11, leading=15)))
    story.append(Spacer(1, 4 * cm))
    story.append(Paragraph("Version 1.0 — Mai 2026", ParagraphStyle("Ver", parent=BODY, alignment=TA_CENTER, fontSize=10, textColor=BRAND_MUTED)))
    story.append(PageBreak())

    # SOMMAIRE
    story.append(Paragraph("Sommaire", H1))
    story.append(Spacer(1, 0.4 * cm))
    # Page numbers will be assigned manually based on layout (intro pg 3, section i at pg 4+i*2 roughly)
    toc_rows = []
    toc_rows.append(["Introduction", "3"])
    for i, (title, _, _, _) in enumerate(SECTIONS, start=1):
        page_num = 4 + (i - 1) * 2  # rough estimate
        toc_rows.append([f"{i}. {title}", str(page_num)])
    toc_rows.append(["Annexe — Glossaire & raccourcis", str(4 + len(SECTIONS) * 2)])
    tbl = Table(toc_rows, colWidths=[14 * cm, 2 * cm])
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 11),
        ("TEXTCOLOR", (0, 0), (-1, -1), BRAND_DARK),
        ("TEXTCOLOR", (1, 0), (1, -1), BRAND_PRIMARY),
        ("FONT", (1, 0), (1, -1), "Helvetica-Bold", 11),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#e2e8f0")),
    ]))
    story.append(tbl)
    story.append(PageBreak())

    # INTRODUCTION
    story.append(Paragraph("Introduction", H1))
    story.append(Paragraph(
        "L'<b>Espace Loois</b> est le portail métier de SAWALI SMART SYSTEMS. Il regroupe l'ensemble des outils nécessaires à la gestion quotidienne d'une PME africaine moderne : caisse et facturation, suivi clients (CRM), tickets d'intervention technique, communications multicanales (WhatsApp, SMS, Messenger), notes et tâches, assistant IA conversationnel, paiements Mobile Money, et bien plus.",
        BODY))
    story.append(Paragraph(
        "Ce guide vous accompagne dans la découverte de chaque module. Pour chaque section, vous trouverez : une <b>capture d'écran</b>, une <b>description</b> de la fonctionnalité, et un détail des <b>champs et boutons</b> avec leur rôle.",
        BODY))
    story.append(Paragraph("Conventions du document", H3))
    story.append(Paragraph("• <b>Texte gras</b> : noms d'éléments d'interface (boutons, onglets, champs)", BODY))
    story.append(Paragraph("• <i>Texte italique</i> : exemples ou valeurs saisies", BODY))
    story.append(Paragraph("• <font color='#1e40af'>Bleu Loois</font> : éléments cliquables, liens", BODY))
    story.append(PageBreak())

    # SECTIONS
    for i, (title, screenshot, intro, fields) in enumerate(SECTIONS, start=1):
        story.append(Paragraph(f"{i}. {title}", H1))
        story.append(Paragraph(intro, BODY))
        story.append(Spacer(1, 0.3 * cm))
        img_path = SCR / screenshot
        if img_path.exists():
            story.append(img(img_path, width=16 * cm))
            story.append(Paragraph(f"Figure {i} — Aperçu de la section <b>{title}</b>", CAPTION))
        story.append(Paragraph("Champs et fonctionnalités", H2))
        for fname, fdesc in fields:
            story.append(Paragraph(f"<b>{fname}</b> — {fdesc}", BODY))
        story.append(PageBreak())

    # ANNEXE
    story.append(Paragraph("Annexe — Glossaire & raccourcis", H1))
    story.append(Paragraph("Glossaire", H2))
    glossary = [
        ("Tenant", "Société/organisation cliente du portail. Chaque tenant a ses propres utilisateurs, contacts, tickets, données."),
        ("Tracked user", "Utilisateur invité par un client en compte (équipier). Hérite d'un rôle limité par défaut (Admin Limité, Caissier, Comptable, etc.)."),
        ("Liluvine PRO", "Assistant IA interne propulsé par Claude Sonnet 4.6. Accès lecture seule à vos données métier."),
        ("WA OTP", "Connexion par code à 6 chiffres envoyé sur WhatsApp (au lieu d'email)."),
        ("PawaPay", "Agrégateur Mobile Money supportant Orange, Moov, Telecel en Afrique de l'Ouest."),
        ("Webhook Stripe", "Endpoint serveur recevant les confirmations de paiement en temps réel (sans polling)."),
        ("Anonymisation RGPD", "Remplacement des données personnelles par des identifiants opaques (droit à l'oubli)."),
    ]
    for term, desc in glossary:
        story.append(Paragraph(f"<b>{term}</b> — {desc}", BODY))
    story.append(Paragraph("Raccourcis clavier", H2))
    story.append(Paragraph("• <b>Entrée</b> dans le chat Liluvine : envoyer le message", BODY))
    story.append(Paragraph("• <b>Shift+Entrée</b> dans le chat Liluvine : saut de ligne sans envoi", BODY))
    story.append(Paragraph("• <b>Échap</b> sur toute modale : fermer", BODY))
    story.append(Paragraph("Support", H2))
    story.append(Paragraph("Pour toute question, contactez l'équipe SAWALI via le formulaire de contact sur sawalismartsystems.com ou directement via la bulle « Liluvine — Support Technique » présente sur toutes les pages.", BODY))

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    print(f"Wrote {out}")
    return out


def build_presentation_brochure():
    """Document B — Brochure de présentation (avec sommaire)."""
    out = OUT / "B_Brochure_Presentation_SAWALI_Loois.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=A4,
                             leftMargin=2 * cm, rightMargin=2 * cm,
                             topMargin=2 * cm, bottomMargin=2.2 * cm)
    story = []
    # COVER
    story.append(Spacer(1, 5 * cm))
    story.append(Paragraph("SAWALI SMART SYSTEMS", COVER_TITLE))
    story.append(Paragraph("Espace Loois — Brochure de présentation", COVER_SUB))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        "Le portail métier tout-en-un pour les PME africaines : CRM, caisse, interventions, IA, paiements Mobile Money.",
        ParagraphStyle("CoverDesc", parent=BODY, alignment=TA_CENTER, textColor=BRAND_MUTED, fontSize=12, leading=16)))
    story.append(PageBreak())

    # SOMMAIRE
    story.append(Paragraph("Sommaire", H1))
    story.append(Spacer(1, 0.4 * cm))
    toc_rows = []
    toc_rows.append(["Pourquoi choisir SAWALI ?", "3"])
    for i, (title, _, _, _) in enumerate(SECTIONS, start=1):
        toc_rows.append([f"{i}. {title}", str(4 + i - 1)])
    toc_rows.append(["Tarifs & abonnements", str(4 + len(SECTIONS))])
    tbl = Table(toc_rows, colWidths=[14 * cm, 2 * cm])
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 11),
        ("TEXTCOLOR", (0, 0), (-1, -1), BRAND_DARK),
        ("TEXTCOLOR", (1, 0), (1, -1), BRAND_PRIMARY),
        ("FONT", (1, 0), (1, -1), "Helvetica-Bold", 11),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#e2e8f0")),
    ]))
    story.append(tbl)
    story.append(PageBreak())

    # POURQUOI SAWALI
    story.append(Paragraph("Pourquoi choisir SAWALI ?", H1))
    story.append(Paragraph(
        "Conçu pour répondre aux contraintes réelles du marché ouest-africain : faible bande passante, monnaie locale (XOF), Mobile Money omniprésent, WhatsApp Business comme canal principal de relation client.",
        BODY))
    advantages = [
        ("🌍 Pensé pour l'Afrique", "Multidevises XOF, intégration PawaPay (Orange/Moov/Telecel Money), Templates WhatsApp Meta natifs."),
        ("⚡ Tout-en-un", "Caisse + CRM + Tickets + IA + Paiements + Communications. Plus besoin de jongler entre 5 outils."),
        ("🤖 IA intégrée", "Assistant Liluvine répond aux questions métier en français et automatise les réponses WhatsApp."),
        ("🔒 Souverain & RGPD", "Données hébergées en Europe, anonymisation conforme, audit trail complet."),
        ("📱 Optimisé mobile", "Toutes les fonctionnalités accessibles depuis smartphone. PWA installable."),
        ("💸 Modèle économique transparent", "Abonnement par société, pas de coût caché. Coût SMS/WA visible en temps réel."),
    ]
    for title, desc in advantages:
        story.append(Paragraph(f"<b>{title}</b> — {desc}", BODY))
    story.append(PageBreak())

    # SECTIONS — version condensée (1 page = 1 module)
    for i, (title, screenshot, intro, fields) in enumerate(SECTIONS, start=1):
        story.append(Paragraph(f"{i}. {title}", H1))
        img_path = SCR / screenshot
        if img_path.exists():
            story.append(img(img_path, width=15 * cm))
            story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(intro, BODY))
        # Top 3 fields condensed
        story.append(Paragraph("Fonctionnalités phares", H3))
        for fname, fdesc in fields[:4]:
            story.append(Paragraph(f"• <b>{fname}</b> : {fdesc}", BODY))
        story.append(PageBreak())

    # TARIFS
    story.append(Paragraph("Tarifs & abonnements", H1))
    story.append(Paragraph(
        "Contactez l'équipe commerciale pour un devis personnalisé adapté à la taille de votre entreprise (nombre d'utilisateurs, volume WA/SMS, modules activés).",
        BODY))
    story.append(Paragraph("Contact", H2))
    story.append(Paragraph("🌐 sawalismartsystems.com", BODY))
    story.append(Paragraph("📧 contact@sawalismartsystems.com", BODY))
    story.append(Paragraph("📱 +226 XX XX XX XX (WhatsApp 24/7)", BODY))

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    print(f"Wrote {out}")
    return out


def build_features_brochure():
    """Document C — Brochure grandes fonctionnalités + capture sans sidebar."""
    out = OUT / "C_Brochure_Grandes_Fonctionnalites.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=A4,
                             leftMargin=2 * cm, rightMargin=2 * cm,
                             topMargin=2 * cm, bottomMargin=2.2 * cm)
    story = []
    # COVER
    story.append(Spacer(1, 5 * cm))
    story.append(Paragraph("Espace Loois", COVER_TITLE))
    story.append(Paragraph("Les grandes fonctionnalités en un coup d'œil", COVER_SUB))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        "Le portail tout-en-un pour piloter votre PME : caisse, CRM, IA, paiements Mobile Money.",
        ParagraphStyle("CoverDesc", parent=BODY, alignment=TA_CENTER, textColor=BRAND_MUTED, fontSize=12, leading=16)))
    story.append(PageBreak())

    # SECTIONS — 1 page par fonctionnalité avec capture SANS sidebar (sauf home)
    for i, (title, screenshot, intro, fields) in enumerate(SECTIONS, start=1):
        story.append(Paragraph(f"{i}. {title}", H1))
        story.append(Paragraph(intro, BODY))
        story.append(Spacer(1, 0.3 * cm))
        img_path = SCR_NS / screenshot
        if img_path.exists():
            # Cropped image (no sidebar): wider use of page width
            story.append(img(img_path, width=16.5 * cm))
            story.append(Paragraph(f"Figure {i} — {title}", CAPTION))
        # Just 3 top features as bullet list
        story.append(Paragraph("Points clés", H3))
        for fname, fdesc in fields[:3]:
            story.append(Paragraph(f"• <b>{fname}</b> : {fdesc}", BODY))
        story.append(PageBreak())

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    print(f"Wrote {out}")
    return out


if __name__ == "__main__":
    a = build_user_guide()
    b = build_presentation_brochure()
    c = build_features_brochure()
    print("=" * 60)
    print("Generated:")
    for p in (a, b, c):
        print(f"  {p}  ({p.stat().st_size // 1024} KB)")
