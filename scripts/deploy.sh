#!/usr/bin/env bash
# Deploy CatalogAI on the production host (build-on-instance model).
#
# Run FROM THE REPO ROOT on the Scaleway instance:
#   ./scripts/deploy.sh
#
# It pulls the latest main, rebuilds the images, runs Alembic migrations (the
# one-shot `migrate` service the backend depends on), and restarts the stack.
# `.env` must already exist on the host (see .env.production.example) and is
# never touched here.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="compose.prod.yml"
BRANCH="${DEPLOY_BRANCH:-main}"

if [[ ! -f .env ]]; then
  echo "ERROR: .env is missing on this host. Copy .env.production.example to .env and fill it in." >&2
  exit 1
fi

echo "==> Fetching $BRANCH"
git fetch --quiet origin "$BRANCH"
git checkout --quiet "$BRANCH"
git reset --hard --quiet "origin/$BRANCH"

echo "==> Building images"
docker compose -f "$COMPOSE_FILE" build

# `up` brings the one-shot migrate service to completion first (the backend
# depends on service_completed_successfully), then (re)starts everything.
echo "==> Migrating + starting"
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

echo "==> Pruning dangling images"
docker image prune -f >/dev/null || true

echo "==> Deployed. Current state:"
docker compose -f "$COMPOSE_FILE" ps
