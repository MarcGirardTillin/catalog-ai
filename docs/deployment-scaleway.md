# Déploiement — Scaleway (Instance + PostgreSQL managé)

Runbook de mise en production de CatalogAI sur une **Instance Scaleway** à
Paris (`fr-par`), avec **PostgreSQL managé** à côté. Les images Docker sont
**construites sur l'instance** (pas de registry ni de secret CI). Reverse
proxy et HTTPS automatique via **Caddy**.

## Vue d'ensemble

```
  navigateur ──HTTPS──▶ Caddy (443) ──▶ frontend (nginx :8080)   SPA
                              └────────▶ backend  (uvicorn :8000) API
  backend ──TLS──▶ PostgreSQL managé Scaleway (sslmode=require)
  backend ──▶ volume app-var-data (images stagées + fichiers d'import)
```

Deux sous-domaines de `tillin.fr` :

- `catalog.tillin.fr` → l'application (frontend)
- `api-catalog.tillin.fr` → l'API (backend)

Ils partagent le domaine enregistré `tillin.fr`, donc le cookie de session
(`SameSite=Lax`, `Secure`) circule bien entre les deux.

## Fichiers de déploiement (dans le repo)

| Fichier | Rôle |
|---|---|
| `compose.prod.yml` | Stack de prod : `migrate` (one-shot), `backend`, `frontend`, `caddy`. Pas de `db` (managé). |
| `Caddyfile` | Reverse proxy + TLS auto pour les deux sous-domaines. |
| `.env.production.example` | Gabarit d'environnement. À copier en `.env` **sur le serveur**. |
| `scripts/deploy.sh` | Pull + build + migrate + restart. |

## Prérequis (une fois)

1. **Base managée** : créer un PostgreSQL managé Scaleway (DEV-S suffit pour
   démarrer), noter host / port / db / user / password. Autoriser l'IP de
   l'instance (ACL) ou passer par un VPC privé.
2. **Instance** : une Instance Scaleway (2 vCPU / 4 Go recommandé — Pillow
   traite des canevas 1600×2000), Ubuntu, Docker + plugin Compose installés,
   IP publique fixe.
3. **DNS** : deux enregistrements A, `catalog` et `api-catalog`, pointant vers
   l'IP publique de l'instance.
4. **Repo** : cloner le repo sur l'instance (`git clone …`).

## Configuration (une fois, sur l'instance)

```bash
cd catalog-ai
cp .env.production.example .env
# Éditer .env : domaines, ACME_EMAIL, secrets, base managée, clés providers.
# APP_SECRET : python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Points de vigilance dans `.env` :

- `POSTGRES_SSLMODE=require` (obligatoire vers une base managée).
- `AUTH_COOKIE_SECURE=true` et `BACKEND_CORS_ORIGINS=https://catalog.tillin.fr`.
- `FRONTEND_API_URL=https://api-catalog.tillin.fr` (le navigateur appelle
  l'API en direct).
- `.env` n'est **jamais** commité (déjà dans `.gitignore`).

## Déploiement

```bash
./scripts/deploy.sh
```

Le script : `git reset --hard origin/main` → `docker compose build` → `up -d`
(le service `migrate` lance `alembic upgrade head` et le backend attend sa
réussite) → prune des images orphelines. Idempotent ; relançable à chaque
mise à jour.

### Premier admin (une seule fois)

Après le premier déploiement, créer le compte opérateur :

```bash
# Soit via les variables FIRST_SUPERUSER* du .env, exécutées une fois :
docker compose -f compose.prod.yml run --rm backend python -m app.initial_data
```

## Vérifications post-déploiement

```bash
# API en ligne (depuis l'instance) :
curl -fsS https://api-catalog.tillin.fr/healthcheck        # {"status":"ok",...}
# Version déployée :
curl -fsS https://api-catalog.tillin.fr/version
# Frontend servi :
curl -fsS -o /dev/null -w '%{http_code}\n' https://catalog.tillin.fr
```

Puis, en conditions réelles : se connecter, lancer une normalisation studio
(vérifie Photoroom + le volume `var`), et confirmer que le solde de crédits
se décrémente.

## Persistance & sauvegardes

- **PostgreSQL** : sauvegardes automatiques + point-in-time recovery gérés par
  Scaleway (rien à faire côté app).
- **Volume `app-var-data`** : images stagées en attente de vérification et
  fichiers d'import en cours. Contenu **transitoire** (purgé après
  enregistrement dans Tillin), mais un `docker compose down -v` le
  détruirait — ne jamais utiliser `-v` en prod. Un redéploiement normal
  (`up -d`) le conserve.

> État futur (multi-instances / serverless) : déporter le staging (`var/`)
> vers du stockage objet (Scaleway Object Storage, compatible S3) en
> réécrivant `app/imaging/staging.py`. Non requis pour une instance unique.

## Souveraineté des données

L'hébergement applicatif (base, crédits, consommation, images en transit) est
**en France** (Scaleway `fr-par`). La chaîne de traitement reste partiellement
hors UE : Xano/Tillin, Anthropic, FASHN et Firecrawl sont hors UE ; seul
Photoroom est français. L'argument à porter est « données applicatives
hébergées en France », pas « chaîne entièrement européenne ».

## Dépannage

- **Certificat TLS non émis** : vérifier que les A records résolvent bien vers
  l'IP et que les ports 80/443 sont ouverts (Caddy a besoin du :80 pour le
  challenge ACME). Logs : `docker compose -f compose.prod.yml logs caddy`.
- **Backend qui ne démarre pas** : regarder d'abord `logs migrate` (échec de
  migration = backend jamais lancé, par dépendance).
- **500 « l'opérateur n'existe pas : json = json »** : bug déjà corrigé, mais
  rappel — les tests SQLite ne voient pas ce cas Postgres.
