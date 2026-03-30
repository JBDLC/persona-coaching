# Deploy sur Render (Persona)

## 1) Préparer le repository

- Pousser le projet sur GitHub.
- Vérifier que `render.yaml` est à la racine.

## 2) Créer le service Render

- Render -> **New +** -> **Blueprint**.
- Sélectionner le repository.
- Render lit automatiquement `render.yaml` et crée:
  - 1 Web Service `persona-app`
  - 1 PostgreSQL `persona-db`

## 3) Variables importantes

Dans Render, renseigner au minimum:

- `ADMIN_PASSWORD` (obligatoire en production)

Les variables déjà prévues:

- `SECRET_KEY` (généré automatiquement)
- `DATABASE_URL` (connectée à la base Render)
- `ADMIN_USERNAME` (par défaut `adminpersona`)
- `ADMIN_EMAIL` (par défaut `adminpersona@persona.local`)

## 4) Initialisation automatique

Le déploiement exécute automatiquement:

- `python init_app.py`

Ce script:

- crée les tables si besoin,
- applique les mises à niveau de schéma simples,
- crée le compte admin par défaut s'il n'existe pas.

## 5) Connexion admin

- Identifiant: `adminpersona` (ou valeur de `ADMIN_USERNAME`)
- Mot de passe: valeur de `ADMIN_PASSWORD`

## 6) Notes prod

- Le stockage de fichiers contrats est local au container (`app/static/uploads`) et non persistant sur Render free.
- Pour la production, prévoir un stockage objet (S3/Cloudinary/Backblaze) pour les contrats.
