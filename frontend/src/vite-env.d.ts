/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string
  readonly VITE_APP_NAME?: string
  readonly VITE_ENV?: string
  readonly VITE_MAINTENANCE_ENABLED?: string
  readonly VITE_VERSION_FULL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/** Identifiant du build courant (vite.config.ts) — comparé à /version.json. */
declare const __BUILD_ID__: string
