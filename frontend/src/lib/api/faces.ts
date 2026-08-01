// Visages mannequins (face swap) : adaptateur fin au-dessus du client généré.
import {
  facesDeleteFace,
  facesListFaces,
  facesUploadFace,
} from "@/client"
import type { FaceReferencePublic } from "@/client"
import { client } from "@/client/client.gen"

export type { FaceReferencePublic }

export function listFaces() {
  return facesListFaces() as Promise<{
    data?: FaceReferencePublic[]
    error?: unknown
  }>
}

export function uploadFace(file: File, name: string) {
  return facesUploadFace({ body: { file, name } }) as Promise<{
    data?: FaceReferencePublic
    error?: unknown
  }>
}

export function deleteFace(id: number) {
  return facesDeleteFace({ path: { face_id: id } })
}

/** Prévisualisation (fichier authentifié) en object-URL — à révoquer. */
export async function fetchFacePreview(id: number): Promise<string | null> {
  const { data } = await client.get<{ 200: Blob }, unknown>({
    responseType: "blob",
    url: `/faces/${id}/file`,
  })
  return data instanceof Blob ? URL.createObjectURL(data) : null
}
