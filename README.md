# Here are your Instructions

## Lot 369 — Connexion par empreinte digitale (passkeys / WebAuthn)

- Se connecter d'un doigt, sans mot de passe ni code : l'empreinte est vérifiée par l'appareil (lecteur d'empreintes avec Windows Hello, téléphone Android / iPhone, clé de sécurité à empreinte) ; SAWALI ne reçoit qu'une **signature** vérifiée avec la clé publique enregistrée, jamais l'empreinte.
- **Désactivée par défaut** : Paramètres › « 🔐 Connexion par empreinte digitale (passkeys) » (interrupteur, domaine, comptes, révocation). Le mot de passe reste toujours possible.
- Chaque personne enregistre sa passkey dans **Mon compte** après une connexion normale (8 au plus par compte). Page de connexion : bouton « Se connecter avec mon empreinte » (si activée et si le navigateur la gère).
- Aucune nouvelle collection MongoDB : clés publiques dans `users.passkeys`, défis éphémères dans `otps` (usage unique, 3 min). Dépendances : `webauthn` et `cbor2` (`backend/requirements.txt`).
- Mêmes refus que les autres connexions (compte inactif, maintenance, client suspendu ou archivé, IP bloquée) ; journal des connexions, méthode « empreinte ». Limite : 30 demandes par minute et par adresse IP.
- Domaine (RP ID) : réglage, sinon variable `WEBAUTHN_RP_ID`, sinon `sawalismartsystems.com` (et ses sous-domaines) ou l'hôte du site. Une passkey ne marche que sur son domaine d'enregistrement.
- Limite : Windows Hello est lié au compte Windows ; sur un poste partagé par un seul compte Windows, préférer le téléphone ou une clé de sécurité personnelle. Une passkey ne dit pas « qui » parmi N (le pointage du personnel reste dans Loois).
