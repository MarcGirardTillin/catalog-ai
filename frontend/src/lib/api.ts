import { frontendEnv } from "./env"

export type BackendVersion = {
  app: string
  environment: string
  version: string
}

const apiBase = (): string => (frontendEnv.apiUrl() || "").replace(/\/$/, "")

async function apiFetch(path: string): Promise<Response> {
  return fetch(`${apiBase()}${path}`, { method: "GET" })
}

export async function fetchBackendVersion(): Promise<BackendVersion | null> {
  try {
    const response = await apiFetch("/version")
    if (!response.ok) {
      return null
    }

    return (await response.json()) as BackendVersion
  } catch {
    return null
  }
}
