#!/usr/bin/env bash

set -euo pipefail

source "$(dirname "$0")/dev-common.sh"

print_tool_row() {
  local name="$1"
  local version="$2"
  local status="Missing"

  if [ -n "$version" ]; then
    status="OK"
  fi

  printf '%-18s %-10s %s\n' "$name" "$status" "${version:--}"
}

print_workspace_row() {
  local name="$1"
  local ready="$2"
  local detail="$3"
  local status="Pending"

  if [ "$ready" = "true" ]; then
    status="Ready"
  fi

  printf '%-24s %-10s %s\n' "$name" "$status" "$detail"
}

uv_binary="$(resolve_uv_binary 2>/dev/null || true)"
bun_binary="$(resolve_bun_binary 2>/dev/null || true)"
venv_bin="$(resolve_project_venv_bin 2>/dev/null || true)"
python_bin="$PYTHON_BIN"

if [ -n "$venv_bin" ]; then
  python_bin="$venv_bin/python"
fi

python_version="$(command_version "$python_bin" --version || true)"
uv_version=""
bun_version=""
docker_version=""
compose_version=""

if [ -n "$uv_binary" ]; then
  uv_version="$(command_version "$uv_binary" --version || true)"
fi

if [ -n "$bun_binary" ]; then
  bun_version="$(describe_bun_runtime "$bun_binary" || true)"
fi

if command -v docker >/dev/null 2>&1; then
  docker_version="$(command_version docker --version || true)"
  compose_version="$(command_version docker compose version || true)"
fi

backend_ready="false"
frontend_runtime="false"
frontend_dependencies="false"

if [ -n "$venv_bin" ]; then
  backend_ready="true"
fi

if frontend_runtime_ready "$bun_binary"; then
  frontend_runtime="true"
fi

if frontend_dependencies_installed; then
  frontend_dependencies="true"
fi

printf 'Template Doctor\n'
printf 'Current local tooling status for the backend and frontend template.\n'

print_section "Tools"
printf '%-18s %-10s %s\n' "Tool" "Status" "Version"
print_tool_row "Python" "$python_version"
print_tool_row "uv" "$uv_version"
print_tool_row "Bun" "$bun_version"
print_tool_row "Docker" "$docker_version"
print_tool_row "Docker Compose" "$compose_version"

print_section "Workspaces"
printf '%-24s %-10s %s\n' "Workspace" "Status" "How to fix"
print_workspace_row "Backend virtualenv" "$backend_ready" "Run \`make init\` to create or sync it."
print_workspace_row "Frontend runtime" "$frontend_runtime" "Use Bun with Node compatibility $FRONTEND_NODE_VERSION_HINT."
print_workspace_row "Frontend dependencies" "$frontend_dependencies" "Run \`make init\` to install them with Bun."
