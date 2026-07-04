#!/bin/sh

set -eu

TEMPLATE_PATH="/usr/share/nginx/html/config.template.js"
CONFIG_PATH="/usr/share/nginx/html/config.js"
NGINX_TEMPLATE_DIR="/etc/nginx/templates"
NGINX_OUTPUT_PATH="/etc/nginx/conf.d/default.conf"

is_truthy() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    true|1|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

envsubst '
${FRONTEND_API_URL}
${FRONTEND_APP_NAME}
${FRONTEND_ENV}
${FRONTEND_MAINTENANCE_ENABLED}
${FRONTEND_VERSION_FULL}
' < "$TEMPLATE_PATH" > "$CONFIG_PATH"

if is_truthy "${FRONTEND_MAINTENANCE_ENABLED:-}"; then
  cp "$NGINX_TEMPLATE_DIR/default.maintenance.conf.template" "$NGINX_OUTPUT_PATH"
else
  cp "$NGINX_TEMPLATE_DIR/default.active.conf.template" "$NGINX_OUTPUT_PATH"
fi

exec nginx -g 'daemon off;'
