#!/usr/bin/env python3
"""Generate the AdminSettings technical reference PDF (in French).

Document D — `D_Documentation_Technique_AdminSettings.pdf`. Lists every
configurable section in `/admin/settings` with the parameters it exposes
and a 1–2 line explanation. Values are NOT included — only the schema and
intent of each parameter, so the user can complete them later as needed.
"""
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, KeepTogether,
)
from reportlab.pdfgen import canvas


OUT = Path("/app/docs")
OUT.mkdir(exist_ok=True)

BRAND_PRIMARY = colors.HexColor("#1e40af")
BRAND_ACCENT = colors.HexColor("#10b981")
BRAND_BG = colors.HexColor("#f8fafc")
BRAND_DARK = colors.HexColor("#0f172a")
BRAND_MUTED = colors.HexColor("#64748b")
BRAND_VIOLET = colors.HexColor("#7c3aed")

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], textColor=BRAND_PRIMARY, fontSize=18, spaceAfter=10, leading=22)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], textColor=BRAND_DARK, fontSize=12, spaceAfter=6, leading=15)
H3 = ParagraphStyle("H3", parent=styles["Heading3"], textColor=BRAND_PRIMARY, fontSize=10, spaceAfter=4, leading=13)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9, leading=12, alignment=TA_JUSTIFY, spaceAfter=4)
PARAM = ParagraphStyle("Param", parent=styles["BodyText"], fontSize=8.5, leading=11, leftIndent=10, spaceAfter=2, textColor=BRAND_DARK)
CAPTION = ParagraphStyle("Cap", parent=styles["Italic"], fontSize=8, textColor=BRAND_MUTED, alignment=TA_CENTER, spaceAfter=8)
COVER_TITLE = ParagraphStyle("CT", parent=styles["Title"], fontSize=26, textColor=BRAND_PRIMARY, alignment=TA_CENTER, leading=30, spaceAfter=6)
COVER_SUB = ParagraphStyle("CS", parent=styles["BodyText"], fontSize=12, textColor=BRAND_DARK, alignment=TA_CENTER, leading=16, spaceAfter=14)


def page_footer(c: canvas.Canvas, doc):
    c.saveState()
    c.setFont("Helvetica", 7.5)
    c.setFillColor(BRAND_MUTED)
    c.setStrokeColor(colors.HexColor("#e2e8f0"))
    c.line(2 * cm, 1.6 * cm, A4[0] - 2 * cm, 1.6 * cm)
    c.drawString(2 * cm, 1.1 * cm, "SAWALI Smart Systems — Référence technique AdminSettings")
    c.drawRightString(A4[0] - 2 * cm, 1.1 * cm, f"Page {doc.page}")
    c.restoreState()


# ----------------------------------------------------------------------
# Catalogue of sections. Each entry = (anchor, title, summary, [(param, type, description), ...]).
# Kept concise and grouped by topical area. Values are intentionally omitted.
# ----------------------------------------------------------------------
SECTIONS = [
    ("Identité & branding", "Configuration de l'identité visuelle et SEO de l'instance.", [
        ("brand_name", "string", "Nom de marque affiché dans le portail, les emails et les PDFs."),
        ("brand_tagline", "string", "Slogan court accompagnant le nom dans les en-têtes."),
        ("brand_logo_url", "URL", "Logo principal (utilisé dans header, login, briefings)."),
        ("brand_favicon_url", "URL", "Favicon servi sous /favicon.ico."),
        ("public_meta_description", "string", "<meta name=\"description\"> pour le SEO."),
        ("public_og_image_url", "URL", "Image Open Graph (partage social)."),
        ("public_phone", "E.164", "Téléphone affiché sur la page Contact publique."),
        ("public_email", "email", "Email public affiché sur la page Contact."),
        ("public_address", "string", "Adresse postale affichée publiquement."),
    ]),

    ("URL publique & sécurité globale", "Configuration des URLs absolues et secrets globaux.", [
        ("public_base_url", "URL", "URL publique utilisée pour les liens absolus dans les cron-jobs (emails, WhatsApp, OAuth)."),
        ("recaptcha_enabled", "bool", "Active reCAPTCHA v3 sur les formulaires publics."),
        ("recaptcha_site_key", "string", "Clé publique reCAPTCHA."),
        ("recaptcha_secret_key", "secret", "Clé secrète reCAPTCHA (masquée à l'affichage)."),
        ("auto_logout_minutes", "int 0–120", "Délai d'inactivité avant déconnexion automatique. 0 = désactivé. Préréglages 5/10/15/30/60."),
    ]),

    ("Approbation WhatsApp des téléchargements (S025)", "Workflow d'approbation pour téléchargements externes par utilisateurs non-admin.", [
        ("download_approval_enabled", "bool", "Active le workflow : demande WA + jauge d'attente côté utilisateur."),
        ("download_approval_whatsapp", "E.164", "Numéro de l'approbateur (recevra les demandes)."),
        ("download_pending_message", "string", "Texte affiché dans la jauge en attente (défaut : « En attente d'approbation… »)."),
        ("download_approval_template_name", "string", "Nom du template Meta WhatsApp interactif avec 2 boutons QUICK_REPLY. Vide ⇒ fallback texte avec liens magiques."),
        ("download_approval_template_lang", "code lang", "Langue du template Meta (par défaut « fr »)."),
        ("download_approval_text_body", "string", "Corps du message texte de fallback. Variables : {requester}, {label}, {approve}, {deny}."),
    ]),

    ("Notification des signataires de PV (S026)", "Notification automatique des signataires obligatoires d'un PV à sa création.", [
        ("meeting_signers_notify_channel", "enum", "Canal de notification : none | email | wa | both. Le PV est envoyé aux signataires de la ligne 1 du formulaire."),
    ]),

    ("Briefing de bienvenue", "Comportement du briefing affiché à la connexion.", [
        ("welcome_unread_mode", "enum", "bounded (recommandé) = ne compte que les messages reçus depuis la dernière visite (ou 7 jours). cumulative = compte tous les messages non lus depuis le début."),
        ("welcome_briefing_days_back", "int", "Période en jours pour les notes/rapports récents (défaut 3)."),
        ("welcome_show_liluvine_card", "bool", "Affiche la carte « WhatsApp pris en charge par Liluvine aujourd'hui ». Visible aux admin/superviseur/modérateurs."),
    ]),

    ("Caisse / Facturation", "Module financier (reçus, factures, dépenses, catalogue).", [
        ("cash_currency_code", "ISO 4217", "Devise par défaut (XOF, EUR, USD…)."),
        ("cash_tax_rate_default", "float", "Taux de TVA par défaut appliqué aux factures."),
        ("cash_legal_form_options", "list[string]", "Formes juridiques affichées dans le formulaire client (SARL, SA, SAS, EI, …)."),
        ("cash_payment_methods", "list[string]", "Modes de paiement disponibles dans les reçus."),
        ("cash_invoice_prefix", "string", "Préfixe des numéros de facture (par ex. FA-)."),
        ("cash_receipt_prefix", "string", "Préfixe des numéros de reçu (par ex. RE-)."),
        ("cash_company_legal_info", "string", "Mentions légales reproduites en pied de chaque facture (RCCM, IDU…)."),
    ]),

    ("Caissier / RBAC", "Droits d'accès au module Caisse et au mobile money.", [
        ("cash_payout_enabled", "bool", "Active le bouton « Payer (Mobile Money) » dans Caisse pour les Caissiers Admin/Superviseur."),
        ("cash_payout_provider", "enum", "pawapay | stripe — fournisseur de décaissement."),
    ]),

    ("PawaPay (Mobile Money)", "Intégration PawaPay pour les décaissements.", [
        ("pawapay_environment", "enum", "sandbox | production."),
        ("pawapay_api_token", "secret", "Token API courant (selon environnement)."),
        ("pawapay_api_token_sandbox", "secret", "Token sandbox."),
        ("pawapay_api_token_production", "secret", "Token production."),
        ("pawapay_callback_secret", "secret", "Secret signant les callbacks PawaPay."),
    ]),

    ("Stripe", "Intégration Stripe Checkout pour les abonnements et la Régie publicitaire.", [
        ("stripe_publishable_key", "string", "Clé publique Stripe."),
        ("stripe_secret_key", "secret", "Clé secrète Stripe (test ou live)."),
        ("stripe_webhook_secret", "secret", "Secret de signature des webhooks Stripe."),
    ]),

    ("Emails (SMTP)", "Serveur SMTP pour OTP, notifications et brochures.", [
        ("smtp_host", "string", "Hôte SMTP (ex: smtp.resend.com)."),
        ("smtp_port", "int", "Port (587 STARTTLS, 465 SSL)."),
        ("smtp_username", "string", "Identifiant SMTP."),
        ("smtp_password", "secret", "Mot de passe SMTP (masqué)."),
        ("smtp_from_email", "email", "Adresse expéditeur par défaut."),
        ("smtp_from_name", "string", "Nom expéditeur affiché."),
    ]),

    ("WhatsApp Cloud API", "Intégration Meta WhatsApp Business Cloud.", [
        ("wa_phone_number_id", "string", "Phone Number ID Meta."),
        ("wa_business_account_id", "string", "WABA ID (compte business)."),
        ("wa_access_token", "secret", "Token d'accès permanent."),
        ("wa_verify_token", "secret", "Token de vérification du webhook Meta."),
        ("wa_app_id", "string", "App ID Facebook Developer."),
        ("wa_app_secret", "secret", "App Secret (signature webhook X-Hub-Signature-256)."),
    ]),

    ("SMS — Orange / Moov / Telecel / OVH", "Routeurs SMS multi-opérateurs.", [
        ("sms_default_provider", "enum", "orange | moov | telecel | ovh."),
        ("sms_orange_*", "secrets", "Identifiants Orange CI (token, basic_pass, header_value, client_secret)."),
        ("sms_moov_*", "secrets", "Identifiants Moov Africa."),
        ("sms_telecel_*", "secrets", "Identifiants Telecel."),
        ("sms_ovh_*", "secrets", "Identifiants OVH (application_secret, consumer_key)."),
    ]),

    ("Liluvine PRO (Assistant IA)", "Configuration de l'assistant IA conversationnel.", [
        ("liluvine_pro_enabled", "bool", "Active Liluvine PRO globalement."),
        ("liluvine_model", "string", "Modèle utilisé (Claude Sonnet 4.5, Claude Haiku 4.5…)."),
        ("liluvine_system_prompt", "string", "Prompt système global appliqué à toutes les conversations."),
        ("liluvine_wa_autoreply_enabled", "bool", "Active l'autoréponse WhatsApp pilotée par Liluvine."),
        ("liluvine_wa_human_takeover_minutes", "int", "Durée du verrou « Reprendre la main » (défaut 120 min)."),
        ("liluvine_remote_secret", "secret", "Secret de l'API console de support distante."),
    ]),

    ("Régie publicitaire (Ad Banners)", "Module monétisation des bannières publicitaires.", [
        ("ad_banners_enabled", "bool", "Active la régie publicitaire."),
        ("ad_banners_default_placement", "enum", "public | portal | both."),
        ("ad_banners_expiration_reminder_days", "int", "Jours avant expiration pour envoyer le rappel email + WhatsApp."),
    ]),

    ("Object Storage (S3)", "Stockage objet pour documents et médias.", [
        ("storage_bucket", "string", "Nom du bucket S3."),
        ("storage_region", "string", "Région AWS (eu-west-1, …)."),
        ("storage_access_key_id", "string", "Access Key ID."),
        ("storage_secret_access_key", "secret", "Secret Access Key."),
        ("storage_public_url_prefix", "URL", "Préfixe public utilisé pour servir les assets."),
    ]),

    ("Voice Notifications (Voice Monkey)", "Notifications vocales via Alexa Echo / Voice Monkey.", [
        ("alexa_enabled", "bool", "Active les notifications vocales."),
        ("alexa_webhook_url", "URL", "URL du webhook Voice Monkey."),
        ("alexa_events", "list[enum]", "Événements déclencheurs : sms_inbound, wa_inbound, appointment_due, support_load_critical."),
    ]),

    ("Audit secrets & sécurité avancée", "Audit des modifications de secrets et alertes sécurité.", [
        ("secret_audit_email_enabled", "bool", "Email à chaque modification de secret (jamais la valeur, juste WHO/WHEN/WHICH)."),
        ("secret_audit_email_to", "email", "Destinataire des notifications d'audit."),
        ("incident_banner_enabled", "bool", "Affiche un bandeau d'incident global en tête du portail."),
        ("incident_banner_severity", "enum", "info | warning | critical."),
        ("incident_banner_message", "string", "Texte du bandeau d'incident."),
        ("incident_banner_link_url", "URL", "Lien d'information complémentaire."),
        ("incident_banner_link_label", "string", "Libellé du bouton du bandeau."),
    ]),

    ("RGPD & Anonymisation", "Conformité RGPD et purge automatique des données.", [
        ("gdpr_auto_anonymize_enabled", "bool", "Lance un cron quotidien qui anonymise les comptes inactifs."),
        ("gdpr_inactive_days_threshold", "int", "Nombre de jours d'inactivité avant anonymisation (défaut 365)."),
        ("gdpr_data_retention_days", "int", "Durée maximale de conservation des logs et messages."),
    ]),

    ("Webhooks entrants / sortants", "Endpoints webhooks personnalisés (notes, santé, paie n8n).", [
        ("notes_webhook_url", "URL", "URL d'un système externe recevant chaque note créée."),
        ("notes_webhook_token", "secret", "Token Bearer pour notes_webhook_url."),
        ("notes_webhook_basic_pass", "secret", "Mot de passe HTTP Basic (alternatif au Bearer)."),
        ("health_webhook_url", "URL", "Webhook recevant les rapports de santé quotidiens."),
        ("health_webhook_token", "secret", "Token du webhook santé."),
        ("payroll_webhooks_n8n_*", "URLs/secrets", "Webhooks paie n8n pour bons de paie et IBAN."),
    ]),

    ("OpenAI / Gemini / Claude (IA externe)", "Clés API IA (compatibles Emergent LLM Key universelle).", [
        ("openai_api_key", "secret", "Clé OpenAI (text + vision + Whisper)."),
        ("openai_chat_api_key", "secret", "Clé OpenAI dédiée au chat (séparée pour quotas)."),
        ("emergent_llm_key", "secret", "Clé universelle Emergent (couvre Claude, Gemini, OpenAI). Si présente, prime sur les clés individuelles."),
    ]),

    ("Quotas IA & coûts", "Limitation de la consommation IA par tenant.", [
        ("ai_monthly_budget_eur", "float", "Budget IA mensuel (en EUR) au-delà duquel l'IA est désactivée."),
        ("ai_monthly_warning_threshold_pct", "int 0–100", "Pourcentage du budget déclenchant un email d'alerte."),
    ]),

    ("Voice Studio (TTS/STT)", "Studio de notifications vocales internes.", [
        ("voice_studio_default_voice", "string", "Voix par défaut pour la synthèse (ElevenLabs)."),
        ("voice_studio_default_lang", "code lang", "Langue par défaut (fr, en, …)."),
    ]),

    ("Intégration Meta (Facebook / Messenger / Ads)", "Connexion à l'écosystème Meta complet.", [
        ("meta_app_id", "string", "App ID Meta Business."),
        ("meta_app_secret", "secret", "App Secret Meta."),
        ("meta_page_id", "string", "Page Facebook par défaut."),
        ("meta_ad_account_id", "string", "Compte publicitaire Meta pour les rapports Ads."),
    ]),

    ("Google Calendar / Gmail", "Intégration des agendas et emails Google.", [
        ("google_client_id", "string", "OAuth Client ID."),
        ("google_client_secret", "secret", "OAuth Client Secret."),
        ("google_calendar_id_primary", "string", "Calendrier cible pour les RDV synchronisés."),
    ]),

    ("Suivi du registre des suggestions (S021)", "Visualisation interne du fichier SUGGESTIONS.md.", [
        ("(pas de paramètres)", "—", "Page consultable depuis Admin → Suggestions (registre S###). Fichier source : /app/memory/SUGGESTIONS.md. Géré directement par modification du fichier (ou via prompts au support agent)."),
    ]),

    ("Diagnostics & maintenance", "Outils de réparation et de cohérence DB.", [
        ("(plusieurs sections)", "—", "Sections « Données orphelines », « Cohérence clients », « Diagnostic client », « Revert retag », « Backfill caissier tenant ». Boutons d'action one-shot — pas de paramètres persistants."),
    ]),
]


def build_admin_settings_doc():
    out = OUT / "D_Documentation_Technique_AdminSettings.pdf"
    pdf = SimpleDocTemplate(
        str(out), pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title="Documentation technique — AdminSettings",
        author="SAWALI Smart Systems",
    )
    story = []
    # ---- Cover ----
    story.append(Spacer(1, 2 * cm))
    story.append(Paragraph("Documentation technique", COVER_TITLE))
    story.append(Paragraph("Référence des paramètres <b>AdminSettings</b>", COVER_SUB))
    story.append(Paragraph("Liste exhaustive des sections, des paramètres exposés<br/>et de leur signification.", CAPTION))
    story.append(Spacer(1, 1 * cm))
    intro = Table(
        [[Paragraph(
            "<b>À propos de ce document</b><br/><br/>"
            "Cette référence présente <b>toutes les sections</b> de la page Administration → Paramètres "
            "de la plate-forme Loois / SAWALI Smart Systems, ainsi que les paramètres qu'elles exposent "
            "et leur effet attendu. <b>Les valeurs ne sont pas fournies</b> : ce document sert de "
            "guide d'auto-remplissage. Vous pouvez configurer chaque paramètre au fil de l'eau, "
            "selon les modules que vous activez réellement.<br/><br/>"
            "<b>Conventions :</b><br/>"
            "• <i>secret</i> : champ masqué à l'affichage (********)<br/>"
            "• <i>E.164</i> : format international du numéro de téléphone (ex. 225XXXXXXXXXX)<br/>"
            "• <i>bool</i> : case à cocher<br/>"
            "• <i>enum</i> : choix dans une liste fermée<br/>",
            BODY,
        )]],
        colWidths=[15.5 * cm],
    )
    intro.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, BRAND_PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(intro)
    story.append(PageBreak())

    # ---- Table of contents ----
    story.append(Paragraph("Sommaire", H1))
    toc_rows = [[
        Paragraph(f"<b>{i+1}.</b>", BODY),
        Paragraph(title, BODY),
        Paragraph(f"{len(fields)} param.", BODY),
    ] for i, (title, _summary, fields) in enumerate(SECTIONS)]
    toc = Table(toc_rows, colWidths=[1.2 * cm, 12.5 * cm, 2.3 * cm])
    toc.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.2, colors.HexColor("#e2e8f0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(toc)
    story.append(PageBreak())

    # ---- Body: one section per page (or grouped) ----
    for i, (title, summary, fields) in enumerate(SECTIONS, start=1):
        kt = []
        kt.append(Paragraph(f"{i}. {title}", H1))
        kt.append(Paragraph(summary, BODY))
        kt.append(Spacer(1, 0.3 * cm))
        # Param table
        rows = [["Paramètre", "Type", "Description"]]
        for pname, ptype, pdesc in fields:
            rows.append([
                Paragraph(f"<b>{pname}</b>", PARAM),
                Paragraph(ptype, PARAM),
                Paragraph(pdesc, PARAM),
            ])
        tbl = Table(rows, colWidths=[4.4 * cm, 2.8 * cm, 8.8 * cm], repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_PRIMARY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_BG]),
            ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#e2e8f0")),
        ]))
        kt.append(tbl)
        kt.append(Spacer(1, 0.5 * cm))
        story.append(KeepTogether(kt))
        story.append(Spacer(1, 0.3 * cm))

    pdf.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    print(f"Wrote {out}  ({out.stat().st_size // 1024} KB)")
    return out


if __name__ == "__main__":
    build_admin_settings_doc()
