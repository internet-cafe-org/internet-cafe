/**
 * Sirve el binario WASM del lector de QR desde el propio dominio (CSP `default-src 'self'`).
 * Por defecto vue-qrcode-reader lo descarga de jsDelivr. Este archivo debe ser la MISMA versión
 * que embebe la librería (zxing-wasm@1.1.3, fijada en devDependencies): si se actualiza
 * vue-qrcode-reader, hay que actualizar también esa versión.
 */
import { setZXingModuleOverrides } from 'vue-qrcode-reader'

// El paquete no expone el .wasm en "exports", por eso se importa por ruta relativa.
import wasmUrl from '../../node_modules/zxing-wasm/dist/reader/zxing_reader.wasm?url'

let configured = false

export function configureQrWasm(origin: string = window.location.origin): void {
  if (configured) return
  const url = new URL(wasmUrl, origin).href
  setZXingModuleOverrides({
    locateFile: (path, prefix) => (path.endsWith('.wasm') ? url : prefix + path),
  })
  configured = true
}
