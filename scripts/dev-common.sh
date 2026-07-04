#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR_NAME="${BACKEND_DIR:-backend}"
if [[ "$BACKEND_DIR_NAME" = /* ]]; then
  BACKEND_PATH="$BACKEND_DIR_NAME"
else
  BACKEND_PATH="$REPO_ROOT/$BACKEND_DIR_NAME"
fi
FRONTEND_PATH="$REPO_ROOT/frontend"
PYTHON_BIN="${PYTHON:-python3}"
PREK_BIN="${PREK:-prek}"
PRE_COMMIT_HOME_DIR="${PRE_COMMIT_HOME:-/tmp/pre-commit-cache}"
UV_CACHE_DIR_PATH="${UV_CACHE_DIR:-/tmp/uv-cache}"
UV_LINK_MODE_VALUE="${UV_LINK_MODE:-copy}"
XDG_CACHE_HOME_DIR="${XDG_CACHE_HOME:-/tmp/xdg-cache}"
UV_INSTALL_DOCS="https://docs.astral.sh/uv/getting-started/installation/"
UV_INSTALL_SCRIPT_URL="https://astral.sh/uv/install.sh"
BUN_INSTALL_DOCS="https://bun.sh/docs/installation"
BUN_INSTALL_SCRIPT_URL="https://bun.com/install"
FRONTEND_NODE_VERSION_HINT=">=24.0.0"
RECOMMENDED_NODE_VERSION="24.0.0"
RECOMMENDED_BUN_VERSION="1.3.13"

print_section() {
  printf '\n%s\n' "$1"
}

resolve_project_venv_bin() {
  if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    printf '%s\n' "$REPO_ROOT/.venv/bin"
    return 0
  fi

  if [ -x "$BACKEND_PATH/.venv/bin/python" ]; then
    printf '%s\n' "$BACKEND_PATH/.venv/bin"
    return 0
  fi

  return 1
}

resolve_uv_binary() {
  local configured="${UV:-}"
  if [ -n "$configured" ] && [ -x "$configured" ]; then
    printf '%s\n' "$configured"
    return 0
  fi

  if [ -n "$configured" ] && command -v "$configured" >/dev/null 2>&1; then
    command -v "$configured"
    return 0
  fi

  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi

  if [ -x "$HOME/.local/bin/uv" ]; then
    printf '%s\n' "$HOME/.local/bin/uv"
    return 0
  fi

  return 1
}

resolve_bun_binary() {
  local configured="${BUN:-}"
  if [ -n "$configured" ] && [ -x "$configured" ]; then
    printf '%s\n' "$configured"
    return 0
  fi

  if [ -n "$configured" ] && command -v "$configured" >/dev/null 2>&1; then
    command -v "$configured"
    return 0
  fi

  if command -v bun >/dev/null 2>&1; then
    command -v bun
    return 0
  fi

  if [ -x "$HOME/.bun/bin/bun" ]; then
    printf '%s\n' "$HOME/.bun/bin/bun"
    return 0
  fi

  return 1
}

command_version() {
  "$@" 2>&1 | head -n 1 | tr -d '\r'
}

parse_version_supported() {
  "$PYTHON_BIN" - "$1" <<'PY'
import re
import sys

value = sys.argv[1].strip()
normalized = value.removeprefix("v")
match = re.match(r"^(\d+)\.(\d+)\.(\d+)", normalized)
if match is None:
    raise SystemExit(1)
parts = tuple(int(part) for part in match.groups())
supported = (parts[0] == 20 and parts >= (20, 19, 0)) or parts >= (22, 12, 0)
raise SystemExit(0 if supported else 1)
PY
}

get_bun_node_version() {
  local bun_binary="$1"
  command_version "$bun_binary" -e "console.log(process.versions.node)"
}

describe_bun_runtime() {
  local bun_binary="$1"
  local bun_version
  local node_version

  bun_version="$(command_version "$bun_binary" --version || true)"
  node_version="$(get_bun_node_version "$bun_binary" || true)"
  printf '%s (Node %s)\n' "${bun_version:-unknown}" "${node_version:-unknown}"
}

frontend_dependencies_installed() {
  [ -d "$FRONTEND_PATH/node_modules" ]
}

frontend_runtime_ready() {
  local bun_binary="${1:-}"
  local node_version=""

  if [ -z "$bun_binary" ]; then
    return 1
  fi

  node_version="$(get_bun_node_version "$bun_binary" || true)"
  if [ -z "$node_version" ]; then
    return 1
  fi

  parse_version_supported "$node_version"
}

confirm_install() {
  local prompt="$1"

  if [ ! -t 0 ]; then
    return 1
  fi

  printf '%s [y/N] ' "$prompt" >&2
  read -r answer
  case "$answer" in
    [yY]|[yY][eE][sS]) return 0 ;;
    *) return 1 ;;
  esac
}

install_uv() {
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf "$UV_INSTALL_SCRIPT_URL" | sh
    return 0
  fi

  if command -v wget >/dev/null 2>&1; then
    wget -qO- "$UV_INSTALL_SCRIPT_URL" | sh
    return 0
  fi

  printf '❌ Neither curl nor wget is available to install uv automatically.\n' >&2
  printf '   Install it manually: %s\n' "$UV_INSTALL_DOCS" >&2
  return 1
}

install_bun() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$BUN_INSTALL_SCRIPT_URL" | bash
    return 0
  fi

  if command -v wget >/dev/null 2>&1; then
    wget -qO- "$BUN_INSTALL_SCRIPT_URL" | bash
    return 0
  fi

  printf '❌ Neither curl nor wget is available to install Bun automatically.\n' >&2
  printf '   Install Bun manually: %s\n' "$BUN_INSTALL_DOCS" >&2
  return 1
}

ensure_uv_available() {
  local uv_binary=""

  if uv_binary="$(resolve_uv_binary 2>/dev/null)"; then
    printf '%s\n' "$uv_binary"
    return 0
  fi

  printf '⚠️  uv is not installed.\n' >&2
  if ! confirm_install "Install uv now using the official installer?"; then
    printf '❌ uv installation skipped.\n' >&2
    printf '   Install it manually: %s\n' "$UV_INSTALL_DOCS" >&2
    return 1
  fi

  install_uv >/dev/null

  if uv_binary="$(resolve_uv_binary 2>/dev/null)"; then
    printf '%s\n' "$uv_binary"
    return 0
  fi

  printf '❌ uv installation completed but uv is still not available in PATH.\n' >&2
  printf '   Reopen your shell or install it manually: %s\n' "$UV_INSTALL_DOCS" >&2
  return 1
}

ensure_bun_available() {
  local bun_binary=""

  if bun_binary="$(resolve_bun_binary 2>/dev/null)"; then
    if frontend_runtime_ready "$bun_binary"; then
      printf '%s\n' "$bun_binary"
      return 0
    fi

    printf '❌ Bun is installed but exposes an unsupported Node.js runtime for the frontend.\n' >&2
    printf '   Found Bun %s.\n' "$(describe_bun_runtime "$bun_binary")" >&2
    printf '   The frontend requires Node %s.\n' "$FRONTEND_NODE_VERSION_HINT" >&2
    printf '   Upgrade Bun (recommended: %s+) or switch to Node %s+.\n' "$RECOMMENDED_BUN_VERSION" "$RECOMMENDED_NODE_VERSION" >&2
    return 1
  fi

  printf '⚠️  Bun is not installed.\n' >&2
  if ! confirm_install "Install Bun now using the official installer?"; then
    printf '❌ Bun installation skipped.\n' >&2
    printf '   Install Bun manually: %s\n' "$BUN_INSTALL_DOCS" >&2
    return 1
  fi

  install_bun >/dev/null

  if bun_binary="$(resolve_bun_binary 2>/dev/null)"; then
    if frontend_runtime_ready "$bun_binary"; then
      printf '%s\n' "$bun_binary"
      return 0
    fi

    printf '❌ Bun installation completed but the runtime is still incompatible.\n' >&2
    printf '   Found Bun %s.\n' "$(describe_bun_runtime "$bun_binary")" >&2
    printf '   The frontend requires Node %s.\n' "$FRONTEND_NODE_VERSION_HINT" >&2
    return 1
  fi

  printf '❌ Bun installation completed but the executable is still unavailable.\n' >&2
  printf '   Reopen your shell or install Bun manually: %s\n' "$BUN_INSTALL_DOCS" >&2
  return 1
}
