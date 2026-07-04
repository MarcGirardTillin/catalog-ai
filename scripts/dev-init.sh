#!/usr/bin/env bash

set -euo pipefail

source "$(dirname "$0")/dev-common.sh"

printf 'Template onboarding\n'
printf 'This command prepares the local backend and frontend environments.\n'
printf 'It does not start the database, backend, or frontend services.\n'

print_section "System checks"
bash "$REPO_ROOT/scripts/dev-doctor.sh"

uv_binary="$(ensure_uv_available)"
printf '\nOK Using uv: %s\n' "$uv_binary"

print_section "Backend setup"
(
  cd "$BACKEND_PATH"
  UV_CACHE_DIR="$UV_CACHE_DIR_PATH" \
    UV_LINK_MODE="$UV_LINK_MODE_VALUE" \
    "$uv_binary" sync --all-groups --frozen --no-progress --no-install-project
)
printf 'OK Backend dependencies synchronized\n'

venv_bin="$(resolve_project_venv_bin 2>/dev/null || true)"
if [ -z "$venv_bin" ]; then
  printf '❌ Unable to locate the project virtualenv after uv sync.\n' >&2
  exit 1
fi

(
  cd "$BACKEND_PATH"
    PATH="$venv_bin:$PATH" \
    PRE_COMMIT_HOME="$PRE_COMMIT_HOME_DIR" \
    XDG_CACHE_HOME="$XDG_CACHE_HOME_DIR" \
    "$PREK_BIN" install -f --hook-type pre-commit
)
printf 'OK Pre-commit hooks installed\n'

bun_binary="$(ensure_bun_available)"

print_section "Frontend setup"
(
  cd "$FRONTEND_PATH"
  "$bun_binary" install --frozen-lockfile
)
printf 'OK Frontend dependencies synchronized\n'

print_section "Final doctor"
bash "$REPO_ROOT/scripts/dev-doctor.sh"

print_section "Next steps"
printf '%s\n' \
  "- make db-up" \
  "- make migrate-upgrade" \
  "- make backend-start" \
  "- make frontend-start" \
  "- make check"
