import { describe, expect, it } from 'vitest'

import { parseScanUrl } from '../utils/qrUrl'

const ORIGIN = 'https://acceso.universidad.example'

describe('parseScanUrl (RF-QR-03)', () => {
  it('acepta una URL del propio dominio con la ruta /s y el token en el fragmento', () => {
    expect(parseScanUrl(`${ORIGIN}/s#k3J9abc`, ORIGIN)).toEqual({ ok: true, token: 'k3J9abc' })
  })

  it('ignora espacios alrededor del texto leído', () => {
    expect(parseScanUrl(`  ${ORIGIN}/s#tok  \n`, ORIGIN)).toEqual({ ok: true, token: 'tok' })
  })

  it.each([
    ['otro dominio', 'https://otro.example/s#tok'],
    ['subdominio engañoso', 'https://acceso.universidad.example.malo.example/s#tok'],
    ['dominio propio como credencial', 'https://acceso.universidad.example@malo.example/s#tok'],
    ['otro protocolo del mismo host', 'http://acceso.universidad.example/s#tok'],
    ['otra ruta', `${ORIGIN}/login#tok`],
    ['ruta con barra final', `${ORIGIN}/s/#tok`],
    ['ruta anidada', `${ORIGIN}/s/otra#tok`],
    ['sin token', `${ORIGIN}/s`],
    ['token vacío', `${ORIGIN}/s#`],
    ['token con espacios', `${ORIGIN}/s#uno dos`],
    ['con parámetros de consulta', `${ORIGIN}/s?x=1#tok`],
    ['con usuario y contraseña', 'https://u:p@acceso.universidad.example/s#tok'],
    ['esquema javascript', 'javascript:alert(1)'],
    ['texto que no es una URL', 'hola mundo'],
    ['cadena vacía', ''],
  ])('rechaza: %s', (_nombre, texto) => {
    expect(parseScanUrl(texto, ORIGIN)).toEqual({ ok: false })
  })

  it('usa el origen de la página por defecto', () => {
    expect(parseScanUrl(`${window.location.origin}/s#tok`)).toEqual({ ok: true, token: 'tok' })
    expect(parseScanUrl('https://otro.example/s#tok')).toEqual({ ok: false })
  })
})
