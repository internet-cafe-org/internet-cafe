import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'

import App from '../App.vue'
import { createAppRouter } from '../router'
import { previewScan } from '../services/scan'
import { configureQrWasm } from '../services/zxing'
import { useSessionStore } from '../stores/session'

vi.mock('vue-qrcode-reader', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    QrcodeStream: defineComponent({
      name: 'QrcodeStream',
      emits: ['detect', 'error', 'camera-on'],
      render: () => h('div', { 'data-test': 'stream' }),
    }),
  }
})
vi.mock('../services/zxing', () => ({ configureQrWasm: vi.fn() }))
// La pantalla de Confirmar acceso (destino) consume y limpia el token; aquí solo se comprueba que lo recibe.
vi.mock('../services/scan', () => ({
  previewScan: vi.fn(() => new Promise(() => {})),
  claimScan: vi.fn(),
}))

const ORIGIN = window.location.origin

async function open() {
  const pinia = createPinia()
  setActivePinia(pinia)
  useSessionStore().setUser('Ana Pérez', 'student')
  const router = createAppRouter(createMemoryHistory())
  await router.push('/scan')
  const wrapper = mount(App, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

const stream = (wrapper: VueWrapper) => wrapper.findComponent({ name: 'QrcodeStream' })
const button = (wrapper: VueWrapper, text: string) =>
  wrapper.findAll('button').find((b) => b.text() === text)
const cameraError = (name: string) => Object.assign(new Error(name), { name })

beforeEach(() => {
  vi.mocked(configureQrWasm).mockClear()
  vi.mocked(previewScan).mockClear()
})

describe('ScanView (W-06)', () => {
  it('configura el WASM propio y muestra el visor mientras inicia la cámara', async () => {
    const { wrapper } = await open()

    expect(configureQrWasm).toHaveBeenCalledTimes(1)
    expect(stream(wrapper).exists()).toBe(true)
    expect(wrapper.text()).toContain('Iniciando la cámara')
    expect(wrapper.text()).toContain('¿Prefieres usar la cámara del celular?')
  })

  it('al activarse la cámara quita el aviso de inicio', async () => {
    const { wrapper } = await open()

    stream(wrapper).vm.$emit('camera-on', {})
    await flushPromises()

    expect(wrapper.text()).not.toContain('Iniciando la cámara')
  })

  it('un QR válido lleva a Confirmar acceso con el token', async () => {
    const { wrapper, router } = await open()

    stream(wrapper).vm.$emit('detect', [{ rawValue: `${ORIGIN}/s#tok123` }])
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('confirm'))

    await vi.waitFor(() => expect(previewScan).toHaveBeenCalledWith('tok123'))
  })

  it('un QR de otro dominio muestra el aviso y no navega', async () => {
    const { wrapper, router } = await open()

    stream(wrapper).vm.$emit('detect', [{ rawValue: 'https://otro.example/s#tok' }])
    await flushPromises()

    expect(wrapper.text()).toContain('Este código no pertenece al sistema.')
    expect(router.currentRoute.value.name).toBe('scan')
    expect(stream(wrapper).exists()).toBe(true)
  })

  it('si en la imagen hay varios códigos, usa el válido', async () => {
    const { wrapper, router } = await open()

    stream(wrapper).vm.$emit('detect', [
      { rawValue: 'https://otro.example/s#malo' },
      { rawValue: `${ORIGIN}/s#bueno` },
    ])
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('confirm'))

    await vi.waitFor(() => expect(previewScan).toHaveBeenCalledWith('bueno'))
    expect(previewScan).not.toHaveBeenCalledWith('malo')
  })

  it('permiso denegado: instrucciones por navegador y reintento (RF-QR-04)', async () => {
    const { wrapper } = await open()

    stream(wrapper).vm.$emit('error', cameraError('NotAllowedError'))
    await flushPromises()

    expect(wrapper.text()).toContain('Permiso de cámara denegado')
    expect(wrapper.text()).toContain('Safari (iPhone o iPad)')
    expect(wrapper.text()).toContain('Chrome (Android)')
    expect(wrapper.text()).toContain('¿Prefieres usar la cámara del celular?')
    expect(stream(wrapper).exists()).toBe(false)

    await button(wrapper, 'Intentar de nuevo')?.trigger('click')
    await flushPromises()

    expect(stream(wrapper).exists()).toBe(true)
    expect(wrapper.text()).toContain('Iniciando la cámara')
  })

  it.each([
    ['NotFoundError', 'No encontramos una cámara', true],
    ['OverconstrainedError', 'No encontramos una cámara', true],
    ['NotReadableError', 'La cámara está en uso', true],
    ['InsecureContextError', 'Conexión no segura', false],
    ['StreamApiNotSupportedError', 'Navegador no compatible', false],
    ['StreamLoadTimeoutError', 'No pudimos iniciar la cámara', true],
  ])('error %s: mensaje propio y reintento=%s', async (name, title, canRetry) => {
    const { wrapper } = await open()

    stream(wrapper).vm.$emit('error', cameraError(name))
    await flushPromises()

    expect(wrapper.text()).toContain(title)
    expect(Boolean(button(wrapper, 'Intentar de nuevo'))).toBe(canRetry)
    expect(wrapper.text()).toContain('¿Prefieres usar la cámara del celular?')
  })

  it('cancelar vuelve al inicio', async () => {
    const { wrapper, router } = await open()

    await button(wrapper, 'Cancelar')?.trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('home'))
  })
})
