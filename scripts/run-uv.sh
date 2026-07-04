#!/usr/bin/env bash

set -euo pipefail

CWD=""
if [ "${1:-}" = "--cwd" ]; then
  CWD="${2:-}"
  shift 2
fi

if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
elif [ -x "${HOME}/.local/bin/uv" ]; then
  UV_BIN="${HOME}/.local/bin/uv"
else
  echo "uv not found in PATH and not present at \$HOME/.local/bin/uv" >&2
  exit 127
fi

if [ -n "$CWD" ]; then
  cd "$CWD"
fi

exec "${UV_BIN}" run --frozen "$@"
