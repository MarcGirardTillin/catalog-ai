// Bibliothèque d'instructions éditoriales : adaptateur fin au-dessus du
// client OpenAPI généré — types et appels viennent de src/client.
import {
  instructionsCreateInstruction,
  instructionsDeleteInstruction,
  instructionsListInstructions,
  instructionsUpdateInstruction,
} from "@/client"
import type {
  InstructionCreate,
  InstructionPublic as GenInstructionPublic,
} from "@/client"

// `categories` a un default serveur : toujours émis (raffinement requis).
export type InstructionPublic = GenInstructionPublic & { categories: string[] }
// Alias historique : création et mise à jour partagent la même forme.
export type InstructionUpsert = InstructionCreate

export function listInstructions() {
  return instructionsListInstructions() as Promise<{
    data?: InstructionPublic[]
    error?: unknown
  }>
}

export function createInstruction(body: InstructionUpsert) {
  return instructionsCreateInstruction({ body }) as Promise<{
    data?: InstructionPublic
    error?: unknown
  }>
}

export function updateInstruction(id: number, body: InstructionUpsert) {
  return instructionsUpdateInstruction({
    path: { instruction_id: id },
    body,
  }) as Promise<{ data?: InstructionPublic; error?: unknown }>
}

export function deleteInstruction(id: number) {
  return instructionsDeleteInstruction({ path: { instruction_id: id } })
}
