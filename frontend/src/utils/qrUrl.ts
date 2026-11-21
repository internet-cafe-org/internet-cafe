/** Resultado de interpretar el texto de un QR escaneado (RF-QR-03). */
export type ScanTarget = { ok: true; token: string } | { ok: false }

/**
 * Solo se aceptan URLs del propio dominio con la ruta `/s` y un token en el
 * fragmento (`https://<front>/s#token`). Cualquier otra cosa se rechaza y no se navega.
 */
export function parseScanUrl(text: string, origin: string = window.location.origin): ScanTarget {
  let url: URL
  try {
    url = new URL(text.trim())
  } catch {
    return { ok: false }
  }

  if (url.origin !== origin || url.pathname !== '/s') return { ok: false }
  if (url.username || url.password || url.search) return { ok: false }

  const token = url.hash.slice(1)
  if (token === '') return { ok: false }
  // Se revisa el texto original: la URL normaliza los espacios a %20 y los tabuladores desaparecen.
  const rawFragment = text.trim().slice(text.trim().indexOf('#') + 1)
  if (/\s/.test(rawFragment)) return { ok: false }
  return { ok: true, token }
}
