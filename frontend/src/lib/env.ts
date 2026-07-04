type RuntimeEnv = {
  FRONTEND_API_URL?: string
  FRONTEND_APP_NAME?: string
  FRONTEND_ENV?: string
  FRONTEND_MAINTENANCE_ENABLED?: string
  FRONTEND_VERSION_FULL?: string
}

declare global {
  interface Window {
    __ENV__?: RuntimeEnv
  }
}

const runtimeEnv = (): RuntimeEnv => {
  if (typeof window === "undefined" || !window.__ENV__) {
    return {}
  }

  return window.__ENV__
}

const getEnvValue = (
  runtimeKey: keyof RuntimeEnv,
  viteValue: string | undefined,
): string | undefined => {
  const runtimeValue = runtimeEnv()[runtimeKey]?.trim()
  if (runtimeValue) {
    return runtimeValue
  }

  const fallbackValue = viteValue?.trim()
  return fallbackValue || undefined
}

const isEnabled = (value: string | undefined): boolean =>
  value?.trim().toLowerCase() === "true"

export const frontendEnv = {
  apiUrl: () => getEnvValue("FRONTEND_API_URL", import.meta.env.VITE_API_URL),
  appName: () => getEnvValue("FRONTEND_APP_NAME", import.meta.env.VITE_APP_NAME),
  environment: () => getEnvValue("FRONTEND_ENV", import.meta.env.VITE_ENV),
  maintenanceEnabled: () =>
    isEnabled(
      getEnvValue(
        "FRONTEND_MAINTENANCE_ENABLED",
        import.meta.env.VITE_MAINTENANCE_ENABLED,
      ),
    ),
  versionFull: () => getEnvValue("FRONTEND_VERSION_FULL", import.meta.env.VITE_VERSION_FULL),
}
