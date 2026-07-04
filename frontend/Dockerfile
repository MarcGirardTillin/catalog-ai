ARG BUN_VERSION=1.3.10
FROM oven/bun:${BUN_VERSION} AS bun-base

FROM node:22-bookworm-slim AS build-stage

COPY --from=bun-base /usr/local/bin/bun /usr/local/bin/bun

WORKDIR /app

COPY frontend/package.json /app/frontend/package.json
COPY frontend/bun.lock /app/frontend/bun.lock

WORKDIR /app/frontend
RUN bun install --frozen-lockfile

COPY frontend /app/frontend
RUN ./node_modules/.bin/vite build

FROM nginx:1

COPY --from=build-stage /app/frontend/dist/ /usr/share/nginx/html
COPY frontend/nginx/default.active.conf.template /etc/nginx/templates/default.active.conf.template
COPY frontend/nginx/default.maintenance.conf.template /etc/nginx/templates/default.maintenance.conf.template
COPY frontend/nginx/backend-not-found.conf /etc/nginx/extra-conf.d/backend-not-found.conf
COPY frontend/nginx/maintenance.html /usr/share/nginx/html/maintenance.html
COPY frontend/run.sh /run.sh

RUN chmod +x /run.sh

ENTRYPOINT ["/run.sh"]
