# server_parts — découpage physique de server.py (lot 28)

`server.py` faisait plus de 26 000 lignes. Il est maintenant découpé en
20 morceaux thématiques, **recopiés à l'identique**. Rien n'a changé dans le
comportement : mêmes routes, même schéma OpenAPI, mêmes tâches de démarrage.

## Comment ça marche

`server.py` garde le début (imports, application FastAPI, aides communes :
rôles, base de données…) puis, à la place de chaque ancien bloc, une ligne :

```python
_inclure_partie("p11_whatsapp.py")  # WhatsApp Business API : …
```

`_inclure_partie()` exécute le fichier **dans l'espace de noms de server.py**
(`exec(..., globals())`). Conséquences :

- les noms utilisés dans une partie (`db`, `api`, `get_current_user`, aides…)
  sont ceux de server.py, comme avant le découpage ;
- l'ordre d'exécution est inchangé (les parties sont incluses dans l'ordre) ;
- `from server import xxx` continue de fonctionner pour tout nom défini dans
  une partie ;
- les erreurs affichent le nom de la partie et sa ligne (plus facile à lire).

## Règles

- **Ne jamais importer une partie directement** (`import server_parts...`) :
  elle ne fonctionne qu'exécutée par server.py.
- Une partie ne peut utiliser que des noms définis **avant** elle (dans
  server.py ou dans une partie précédente), comme dans l'ancien fichier unique.
- Pour ajouter une route, l'écrire dans la partie de son thème, avant
  `p20_branchement_routeurs.py` (le routeur `api` est branché sur l'application
  à la fin de server.py).
- Les tests qui lisent le texte de server.py utilisent
  `tests/_source_serveur.py`, qui recolle les parties à leur place.

## Parties

| Fichier | Contenu |
|---|---|
| p01_sante_auth_public.py | Santé, authentification, pages publiques, jauge support, redirection Liluvine |
| p02_portail_client_paiements.py | Portail client, agenda n8n, PawaPay, paiements, liens de paiement, facturation des interventions |
| p03_admin_clients_usage.py | Portail superviseur, Admin → Clients, SMART Communications, usage, activité |
| p04_admin_sauvegardes_diagnostics.py | Instantanés et sauvegardes, feuille de route, coffre de secrets, diagnostics, campagnes |
| p05_admin_crm_documents.py | CRM, paiements des tenants, rendez-vous, interventions, documents, téléversement, politiques |
| p06_medias_ia_version_cms.py | Médiathèque, transcription, synthèse IA, version de la plateforme, CMS |
| p07_admin_utilisateurs_suivis.py | Utilisateurs suivis, messages reçus, liste noire IP, logo |
| p08_notes_portail_journaux.py | Rapports & suivis, note de service, portail, notes étoilées, journaux, traces API |
| p09_supervision_parametres.py | Supervision, contrôle d'authentification, disponibilité, Paramètres, audit des secrets |
| p10_site_public_marketing.py | Témoignages, sitemap, études de cas, blog, newsletter, pastilles, fil d'activité |
| p11_whatsapp.py | WhatsApp Business API (répertoire, envois, médias, statistiques) |
| p12_sms.py | Passerelle SMS, Orange, envois groupés et planifiés |
| p13_whatsapp_supervision.py | Détecteur de silence, santé des intégrations, simulation de message entrant |
| p14_whatsapp_admin_automations.py | Messagerie groupée (admin), automatisations, envois planifiés |
| p15_formulaires.py | Formulaires dynamiques et statistiques |
| p16_liens_visiteurs_formations.py | Liens cryptés, suivi des visiteurs, formations |
| p17_demarrage_planificateur.py | Démarrage, alertes contrats, rappels de facturation, planificateur |
| p18_abonnements_tickets.py | Abonnements, tickets d'intervention et exports |
| p19_briefing_accueil.py | Briefing d'accueil après connexion |
| p20_branchement_routeurs.py | Branchement des routeurs des modules routes/* |
