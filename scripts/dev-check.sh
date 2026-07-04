#!/usr/bin/env bash

set -euo pipefail

source "$(dirname "$0")/dev-common.sh"

scope="${1:-all}"
MAKE_BIN="${MAKE_BIN:-make}"

declare -a scopes=()
declare -a steps=()
declare -a statuses=()

print_summary() {
  local title="$1"
  local index=0

  print_section "$title"
  printf '%-10s %-12s %s\n' "Scope" "Step" "Status"
  while [ "$index" -lt "${#steps[@]}" ]; do
    printf '%-10s %-12s %s\n' "${scopes[$index]}" "${steps[$index]}" "${statuses[$index]}"
    index=$((index + 1))
  done
}

run_step() {
  local step_scope="$1"
  local step_name="$2"
  shift 2

  printf 'Running %s %s...\n' "$step_scope" "$step_name"
  if "$@"; then
    scopes+=("$step_scope")
    steps+=("$step_name")
    statuses+=("OK")
    printf 'OK %s %s passed\n' "$step_scope" "$step_name"
    return 0
  fi

  scopes+=("$step_scope")
  steps+=("$step_name")
  statuses+=("FAILED")
  printf 'ERROR %s %s failed\n' "$step_scope" "$step_name" >&2
  return 1
}

run_backend_checks() {
  run_step back lint "$MAKE_BIN" --no-print-directory lint
  run_step back mypy "$MAKE_BIN" --no-print-directory mypy
  run_step back pytest "$MAKE_BIN" --no-print-directory pytest
}

run_frontend_checks() {
  run_step front runtime "$MAKE_BIN" --no-print-directory frontend-runtime-check
  run_step front lint "$MAKE_BIN" --no-print-directory frontend-lint
  run_step front build "$MAKE_BIN" --no-print-directory frontend-build
}

case "$scope" in
  back)
    printf 'Backend checks\n'
    if run_backend_checks; then
      print_summary "Backend validation summary"
      printf 'OK Validation checks passed\n'
    else
      print_summary "Backend validation summary"
      exit 1
    fi
    ;;
  front)
    printf 'Frontend checks\n'
    if run_frontend_checks; then
      print_summary "Frontend validation summary"
      printf 'OK Validation checks passed\n'
    else
      print_summary "Frontend validation summary"
      exit 1
    fi
    ;;
  all)
    printf 'Full-stack checks\n'
    if run_backend_checks && run_frontend_checks; then
      print_summary "Full-stack validation summary"
      printf 'OK Validation checks passed\n'
    else
      print_summary "Full-stack validation summary"
      exit 1
    fi
    ;;
  *)
    printf '❌ Unknown validation scope: %s\n' "$scope" >&2
    printf '   Supported scopes: back, front, all\n' >&2
    exit 1
    ;;
esac
