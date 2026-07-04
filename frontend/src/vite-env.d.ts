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
