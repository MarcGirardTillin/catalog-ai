// Configure the generated typed client (src/client) once at app startup.
// Auth is an httpOnly session cookie, so requests must carry credentials.
import { client } from "@/client/client.gen"

import { frontendEnv } from "./env"

export function setupApiClient(): void {
  client.setConfig({
    baseURL: (frontendEnv.apiUrl() || "").replace(/\/$/, ""),
    withCredentials: true,
  })
}
