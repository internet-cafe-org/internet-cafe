/**
 * Correo que se está verificando (viene del registro).
 * Vive SOLO en memoria: no se guarda en storage ni en Pinia y no viaja en la URL,
 * porque es un dato personal.
 */
let pendingEmail: string | null = null

export function setPendingVerificationEmail(email: string): void {
  pendingEmail = email
}

export function getPendingVerificationEmail(): string | null {
  return pendingEmail
}

export function clearPendingVerificationEmail(): void {
  pendingEmail = null
}
