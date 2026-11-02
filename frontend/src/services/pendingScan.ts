/**
 * Token del QR escaneado antes de iniciar sesión (SRS RF-QR-05).
 * Vive SOLO en memoria: no se guarda en storage ni en Pinia.
 */
let pendingToken: string | null = null

export function setPendingScanToken(token: string): void {
  pendingToken = token
}

/** Devuelve el token pendiente y lo olvida (un solo uso). */
export function takePendingScanToken(): string | null {
  const token = pendingToken
  pendingToken = null
  return token
}
