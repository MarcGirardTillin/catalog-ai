// Aperçu CSV côté client (avant upload) : sniff du délimiteur + parse
// minimal mais quote-aware des premières lignes. L'aperçu fidèle (xlsx
// compris) vient du backend une fois le fichier importé.

const DELIMITERS = [";", ",", "\t"] as const

function sniffDelimiter(text: string): string {
  const firstLine = text.slice(0, 4096).split(/\r?\n/, 1)[0] ?? ""
  let best: string = DELIMITERS[0]
  let bestCount = 0
  for (const delimiter of DELIMITERS) {
    const count = firstLine.split(delimiter).length - 1
    if (count > bestCount) {
      best = delimiter
      bestCount = count
    }
  }
  return best
}

/** Parse les `maxRows` premières lignes d'un CSV (guillemets gérés). */
export function parseCsvPreview(text: string, maxRows = 50): string[][] {
  const delimiter = sniffDelimiter(text)
  const rows: string[][] = []
  let row: string[] = []
  let cell = ""
  let inQuotes = false

  const pushCell = () => {
    row.push(cell)
    cell = ""
  }
  const pushRow = () => {
    pushCell()
    // Ignore les lignes entièrement vides (fin de fichier, lignes blanches).
    if (row.some((value) => value !== "")) rows.push(row)
    row = []
  }

  for (let i = 0; i < text.length && rows.length < maxRows; i++) {
    const char = text[i]
    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          cell += '"'
          i++
        } else {
          inQuotes = false
        }
      } else {
        cell += char
      }
    } else if (char === '"' && cell === "") {
      inQuotes = true
    } else if (char === delimiter) {
      pushCell()
    } else if (char === "\n") {
      pushRow()
    } else if (char !== "\r") {
      cell += char
    }
  }
  if (rows.length < maxRows && (cell !== "" || row.length > 0)) pushRow()
  return rows
}

/** Lit un fichier texte en UTF-8, avec repli latin-1 si le décodage échoue. */
export async function readTextWithFallback(file: File): Promise<string> {
  const buffer = await file.arrayBuffer()
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer)
  } catch {
    return new TextDecoder("iso-8859-1").decode(buffer)
  }
}
