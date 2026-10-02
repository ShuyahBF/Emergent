# Service d'envoi des e-mails (lot 52 — spécification validée le 02/10/2026)

Paramètres (Admin) › onglet **Communications** › **Service d'envoi des e-mails (Resend, ZeptoMail, Brevo, SMTP)** (super-admin `SUPER_ADMIN_EMAIL` uniquement ; un Admin de client reçoit 403).
Code : `backend/email_fournisseurs.py`, envoi `backend/email_service.py` (`send_email`, signature inchangée), routes `backend/routes/fournisseurs_email.py`.

## Pourquoi

Render bloque les ports SMTP 25, 465 et 587 sur les services gratuits (depuis septembre 2025) ; le port 25 est bloqué partout. SMTP ne fonctionne donc qu'avec une offre payante (Starter). Resend, ZeptoMail et Brevo passent par HTTPS (port 443).

## Choix

| Service | Champs | Appel |
|---------|--------|-------|
| Resend | clé API | `POST https://api.resend.com/emails`, `Authorization: Bearer <clé>` |
| ZeptoMail (Zoho) | clé API, région .com / .eu / .in | `POST https://<hôte>/v1.1/email`, `Authorization: Zoho-enczapikey <clé>` (préfixe jamais doublé) |
| Brevo | clé API | `POST https://api.brevo.com/v3/smtp/email`, `api-key: <clé>` |
| SMTP | hôte, port, utilisateur, mot de passe, STARTTLS | code existant (avertissement Render affiché) |
| Désactivé | — | aucun envoi, aucun repli |

Champs communs : adresse d'expéditeur (domaine validé chez le fournisseur), nom affiché (sans `<` `>` ni retour à la ligne, 60 caractères au plus), interrupteur actif. Le corps texte est toujours envoyé (tiré du HTML s'il manque), le HTML et les pièces jointes aussi (rapports, sauvegardes). Délai : 20 s.

## Secrets

- Clés API et mot de passe SMTP chiffrés en base (Fernet dérivé de `JWT_SECRET`, comme Story Studio). L'API ne renvoie que `a_cle: true/false`.
- Champ secret vide = valeur conservée.
- Ancien mot de passe SMTP en clair (`settings.global.smtp_password`) : chiffré au démarrage puis effacé des réglages globaux. Un mot de passe SMTP envoyé par l'ancien `PUT /api/admin/settings` est aussi chiffré ; les champs `smtp_*` y sont ignorés pour un autre compte que le super-admin.
- Changer `JWT_SECRET` rend les clés illisibles : il faut alors les saisir de nouveau.

## Ordre de choix du service

1. Réglages de l'écran (`email_fournisseur`, `_id: "plateforme"`). « Désactivé » ou interrupteur coupé : aucun envoi.
2. Ancien document sans `fournisseur` : anciens réglages SMTP (`smtp_host`, `smtp_port`, `smtp_user`, `smtp_from_email`, `smtp_from_name`, `smtp_use_tls`).
3. Rien de réglé : variables d'environnement, dans cet ordre : `RESEND_API_KEY` + `RESEND_EXPEDITEUR` ; `PLATEFORME_SMTP_*` puis `SMTP_*` (HOST, PORT, USER, PASSWORD, FROM_EMAIL, FROM_NAME, USE_TLS) ; `BREVO_API_KEY` ; `ZEPTOMAIL_API_KEY` (+ `ZEPTOMAIL_HOTE`) ; avec `EMAIL_EXPEDITEUR` (« Nom <adresse> » accepté).

## Erreurs et journaux

- Erreur : « <Fournisseur> <code HTTP> : <message du fournisseur> » (250 caractères au plus, jamais la clé). `send_email` renvoie `False` sans lever d'exception : l'action en cours (OTP, rapport, sauvegarde…) n'est jamais bloquée.
- `email_envois_journal` : chaque envoi (ENVOYE / ECHEC / NON_CONFIGURE), effacé au bout de 90 jours.
- `email_fournisseur_journal` : chaque modification (qui, quand, quel fournisseur, noms des champs ; jamais une clé).
- « Envoyer un essai » utilise les réglages **enregistrés** et affiche le message du fournisseur.

## Routes

- `GET /api/admin/email-fournisseur` — réglages, service effectif, aides, avertissement SMTP.
- `PUT /api/admin/email-fournisseur` — `{fournisseur, actif, expediteur, nom_affiche, cle, zeptomail_hote, smtp: {hote, port, utilisateur, mot_de_passe, starttls}}`.
- `POST /api/admin/email-fournisseur/essai` — `{destinataire?}` (par défaut : l'adresse du super-admin).
- `GET /api/admin/email-fournisseur/journal` — modifications et derniers envois.

## Locataires

SAWALI n'a pas de messagerie propre à chaque client : tous les e-mails partent avec le service de la plateforme. Le niveau « locataire » de la spécification ne s'applique donc pas.
