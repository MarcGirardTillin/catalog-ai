// Configure the generated typed client (src/client) once at app startup.
// Auth is an httpOnly session cookie, so requests must carry credentials.
import { toast } from "svelte-sonner"
import { navigate } from "svelte5-router"

import { client } from "@/client/client.gen"

import { frontendEnv } from "./env"

// Un seul toast même si plusieurs requêtes échouent en rafale au même moment.
let expiredToastShown = false

export function setupApiClient(): void {
  client.setConfig({
    baseURL: (frontendEnv.apiUrl() || "").replace(/\/$/, ""),
    withCredentials: true,
  })

  // Session Tillin expirée : le token Xano de l'utilisateur (72 h) est mort,
  // le backend répond 401 xano_token_expired sur les appels catalogue. Se
  // reconnecter est la seule issue (le login recapture un token frais) — on
  // l'annonce et on renvoie au login, quel que soit l'écran.
  client.instance.interceptors.response.use(
    (response) => response,
    (error: { response?: { data?: { code?: string } } }) => {
      if (error.response?.data?.code === "xano_token_expired") {
        if (!expiredToastShown) {
          expiredToastShown = true
          toast.error("Session Tillin expirée — reconnectez-vous.")
          setTimeout(() => (expiredToastShown = false), 5000)
        }
        navigate("/login")
      }
      return Promise.reject(error)
    },
  )
}
