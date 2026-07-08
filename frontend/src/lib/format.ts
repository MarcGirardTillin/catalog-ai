// Small local formatting helpers (no external dependency).

/** "12 s", "1 min", "1 min 05 s" — same convention as JobDetailPage. */
export function formatDuration(seconds: number): string {
  const s = Math.round(seconds)
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  if (rem === 0) return `${m} min`
  return `${m} min ${String(rem).padStart(2, "0")} s`
}

/** French relative date: "à l'instant", "il y a 5 min", "il y a 2 h", "hier", else short date. */
export function formatRelativeDate(iso: string): string {
  const date = new Date(iso)
  const diffMs = Date.now() - date.getTime()
  if (Number.isNaN(diffMs)) return "—"
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 1) return "à l'instant"
  if (minutes < 60) return `il y a ${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `il y a ${hours} h`

  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const dayDiff = Math.round((startOfDay(new Date()) - startOfDay(date)) / 86_400_000)
  if (dayDiff === 1) return "hier"
  return date.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" })
}
