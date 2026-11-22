const TIME_ZONE = 'America/Bogota'

const formatter = new Intl.DateTimeFormat('es-CO', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: TIME_ZONE,
})

/** Fecha ISO 8601 (UTC) del servidor → "04/11/2026, 09:15" en hora de Colombia. */
export function formatDateTime(iso: string): string {
  return formatter.format(new Date(iso))
}
