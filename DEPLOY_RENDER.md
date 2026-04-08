# Deploy sur Render (Persona + base SQL)

## 1) Préparer le repository

- Pousser le projet sur GitHub.
- Vérifier que `render.yaml` est à la racine.

## 2) Créer les services Render

- Render -> **New +** -> **Blueprint**.
- Sélectionner le repository.
- Render lit automatiquement `render.yaml` et crée:
  - 1 Web Service `persona-app`
  - 1 PostgreSQL `persona-db` (base SQL)
  - 1 Cron `persona-reminders` (rappels automatiques J-1)

## 3) Variables importantes

Dans Render, renseigner au minimum:

- `ADMIN_PASSWORD` (obligatoire en production)

Les variables déjà prévues:

- `SECRET_KEY` (généré automatiquement)
- `DATABASE_URL` (connectée à la base Render)
- `ADMIN_USERNAME` (par défaut `adminpersona`)
- `ADMIN_EMAIL` (par défaut `adminpersona@persona.local`)

Variables SMTP globales (fallback si le coach n'a pas son SMTP):

- `MAIL_SERVER`
- `MAIL_PORT` (ex: `587`)
- `MAIL_USE_TLS` (`true` / `false`)
- `MAIL_USERNAME`
- `MAIL_PASSWORD`
- `MAIL_DEFAULT_SENDER`
- `DATA_ENCRYPTION_KEY` (clé Fernet urlsafe base64 pour chiffrer les secrets en base)

Variables Stripe Connect (obligatoires pour les paiements):

- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_CONNECT_REFRESH_URL` (URL de retour si onboarding interrompu)
- `STRIPE_CONNECT_RETURN_URL` (URL de retour après onboarding)

Variables visio automatique Google Meet (optionnelles):

- `meeting_auto_enabled` (gere via adminpersona, pas obligatoire en env)
- `meeting_provider` (google_meet)
- `google_oauth_client_id`
- `google_oauth_client_secret`
- `google_oauth_refresh_token`
- `google_calendar_id` (ex: `primary`)

Webhook Stripe à configurer:

- Endpoint: `https://<ton-domaine>/stripe/webhook`
- Événements minimum:
  - `account.updated`
  - `checkout.session.completed`
  - `payment_intent.succeeded`
  - `payment_intent.payment_failed`

## 4) Initialisation automatique

Le service Web exécute automatiquement:

- `python init_app.py`

Ce script:

- crée les tables si besoin,
- applique les mises à niveau de schéma simples,
- crée le compte admin par défaut s'il n'existe pas.

Le service Cron exécute chaque jour:

- `python -m flask --app wsgi:app send-reminders`

Ce job envoie les rappels J-1 pour les coachs correctement paramétrés.

Tu peux ajouter un second cron hebdomadaire pour la purge RGPD:

- `python -m flask --app wsgi:app purge-data`

## 5) Connexion admin

- Identifiant: `adminpersona` (ou valeur de `ADMIN_USERNAME`)
- Mot de passe: valeur de `ADMIN_PASSWORD`

## 6) Notes production

- Le `render.yaml` active un disque persistant monté sur `app/static/uploads` pour:
  - contrats,
  - factures,
  - images de présentation coach.
- Si tu veux rester en offre free, retire le bloc `disk` de `render.yaml` (fichiers non persistants).
