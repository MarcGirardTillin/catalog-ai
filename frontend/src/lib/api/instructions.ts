// Appels typés vers la bibliothèque d'instructions éditoriales.
//
// Ces endpoints sont plus récents que le client généré (src/client) : on
// réutilise son instance axios configurée (baseURL + cookies) via `client`
// et on appelle les chemins bruts. À remplacer par les fonctions générées
// après régénération OpenAPI.
import { client } from "@/client/client.gen"

export type InstructionPublic = {
  id: number
  name: string
  content: string
  categories: string[]
  created_at: string
  updated_at: string
}

export type InstructionUpsert = {
  name: string
  content: string
  categories: string[]
}

// Le client généré attend TData sous forme de map { statut: type } et
// renvoie `{ data, error }` (throwOnError = false par défaut).
export function listInstructions() {
  return client.get<{ 200: InstructionPublic[] }, unknown>({
    responseType: "json",
    url: "/instructions",
  })
}

export function createInstruction(body: InstructionUpsert) {
  return client.post<{ 201: InstructionPublic }, unknown>({
    responseType: "json",
    url: "/instructions",
    body,
    headers: { "Content-Type": "application/json" },
  })
}

export function updateInstruction(id: number, body: InstructionUpsert) {
  return client.put<{ 200: InstructionPublic }, unknown>({
    responseType: "json",
    url: `/instructions/${id}`,
    body,
    headers: { "Content-Type": "application/json" },
  })
}

export function deleteInstruction(id: number) {
  return client.delete<{ 204: unknown }, unknown>({
    url: `/instructions/${id}`,
  })
}
