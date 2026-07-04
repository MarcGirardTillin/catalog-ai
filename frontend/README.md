# Frontend (Svelte Starter Shell)

This workspace is the canonical frontend of the template.

It provides a minimal Svelte + Vite starter shell with:

- minimal home page (`/`) and a dedicated 404 page
- runtime config via `window.__ENV__` from `public/config.template.js`
- generated OpenAPI client under `src/client`
- shadcn-svelte theme tokens with JetBrains Mono as the application font
- a minimal TanStack Query example for backend version (`/version`)

## Local Commands

Run from repository root:

```bash
make frontend-start
make frontend-build
make frontend-lint
make check-front
```

Regenerate the backend client after OpenAPI changes:

```bash
bash ./scripts/generate-client.sh
```

## Environment

Configure `frontend/.env` for local Vite development:

```env
VITE_API_URL=http://localhost:8000
```

Optional:

```env
VITE_APP_NAME=Techlab starter
VITE_ENV=dev
VITE_VERSION_FULL=local
VITE_MAINTENANCE_ENABLED=false
```

## Runtime Config in Containers

The container startup script (`run.sh`) renders `/config.js` from environment variables.
The app reads those values first and falls back to `VITE_*` in local mode.

`index.html` must load `/config.js` before the Svelte bundle so the same image
can be reused across environments.
