import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'

import App from '../App.vue'
import { createAppRouter } from '../router'
import { ApiError } from '../services/auth'
import { setPendingScanToken, takePendingScanToken } from '../services/pendingScan'
import { claimScan, previewScan, type ScanClaim, type ScanPreview } from '../services/scan'
import { useSessionStore } from '../stores/session'

vi.mock('../services/scan', () => ({ previewScan: vi.fn(), claimScan: vi.fn() }))

const previewMock = vi.mocked(previewScan)
const claimMock = vi.mocked(claimScan)

const PREVIEW: ScanPreview = {
  machine: { code: 'LAB3-PC12', lab: 'Sala 3 · Bloque B' },
  expires_at: '2026-10-29T14:05:00Z',
  active_session: null,
}

const CLAIM: ScanClaim = {
  session: {
    id: 's1',
    status: 'active',
    started_at: '2026-10-29T14:04:21Z',
    machine: { id: 'm1', code: 'LAB3-PC12', lab: 'Sala 3 · Bloque B' },
  },
}

async function open(path = '/s#tok123') {
  const pinia = createPinia()
  setActivePinia(pinia)
  useSessionStore().setUser('Ana Pérez', 'student')
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(App, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

const buttonByText = (wrapper: Awaited<ReturnType<typeof open>>['wrapper'], text: string) =>
  wrapper.findAll('button').find((b) => b.text() === text)

beforeEach(() => {
  previewMock.mockReset()
  claimMock.mockReset()
  takePendingScanToken()
})

afterEach(() => vi.unstubAllEnvs())

describe('ConfirmAccessView (W-07)', () => {
  it('vista previa: muestra el equipo, limpia la URL y no crea la sesión', async () => {
    previewMock.mockResolvedValue(PREVIEW)
    const { wrapper, router } = await open()

    expect(previewMock).toHaveBeenCalledWith('tok123')
    expect(claimMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('LAB3-PC12')
    expect(wrapper.text()).toContain('Sala 3 · Bloque B')
    expect(wrapper.text()).toContain('Solo se registra el acceso al confirmar.')
    expect(router.currentRoute.value.hash).toBe('')
  })

  it('avisa si el estudiante tiene una sesión activa en otro equipo', async () => {
    previewMock.mockResolvedValue({ ...PREVIEW, active_session: { machine_code: 'LAB1-PC03' } })
    const { wrapper } = await open()

    expect(wrapper.text()).toContain('Cambio de sesión activa')
    expect(wrapper.text()).toContain('Tienes una sesión activa en LAB1-PC03.')
  })

  it('confirmar crea la sesión y muestra el resultado', async () => {
    previewMock.mockResolvedValue(PREVIEW)
    claimMock.mockResolvedValue(CLAIM)
    const { wrapper } = await open()

    await buttonByText(wrapper, 'Confirmar')?.trigger('click')
    await flushPromises()

    expect(claimMock).toHaveBeenCalledTimes(1)
    expect(claimMock).toHaveBeenCalledWith('tok123')
    expect(wrapper.text()).toContain('Acceso confirmado')
    expect(wrapper.text()).toContain('Sesión activa en LAB3-PC12.')
    expect(buttonByText(wrapper, 'Confirmar')).toBeUndefined()
  })

  it('cancelar no crea sesión y vuelve al inicio', async () => {
    previewMock.mockResolvedValue(PREVIEW)
    const { wrapper, router } = await open()

    await buttonByText(wrapper, 'Cancelar')?.trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('home'))

    expect(claimMock).not.toHaveBeenCalled()
  })

  it.each([
    ['CHALLENGE_EXPIRED', 410, 'QR vencido', 'Escanear código nuevo'],
    ['CHALLENGE_ALREADY_USED', 409, 'QR ya utilizado', 'Escanear código nuevo'],
    ['CHALLENGE_NOT_FOUND', 404, 'QR inválido', 'Volver a escanear'],
    ['MACHINE_DISABLED', 403, 'Equipo deshabilitado', 'Escanear otro equipo'],
  ])(
    'vista previa con %s: mensaje y acción propios (RF-QR-08)',
    async (code, status, title, action) => {
      previewMock.mockRejectedValue(new ApiError(status, code))
      const { wrapper } = await open()

      expect(wrapper.text()).toContain(title)
      expect(wrapper.text()).toContain('No se registró ningún acceso.')
      expect(wrapper.text()).toContain('Tu sesión previa, si existe, no se ha modificado.')
      expect(buttonByText(wrapper, action)).toBeDefined()
      expect(buttonByText(wrapper, 'Confirmar')).toBeUndefined()
    },
  )

  it.each([
    ['CHALLENGE_EXPIRED', 410, 'QR vencido'],
    ['MACHINE_BUSY', 409, 'Equipo en uso'],
    ['NETWORK_ERROR', 0, 'No pudimos completar el acceso'],
  ])('al confirmar, el error %s muestra su mensaje', async (code, status, title) => {
    previewMock.mockResolvedValue(PREVIEW)
    claimMock.mockRejectedValue(new ApiError(status, code))
    const { wrapper } = await open()

    await buttonByText(wrapper, 'Confirmar')?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(title)
    expect(wrapper.text()).not.toContain('Acceso confirmado')
  })

  it('equipo deshabilitado: el botón de soporte solo aparece si hay contacto configurado', async () => {
    previewMock.mockRejectedValue(new ApiError(403, 'MACHINE_DISABLED'))
    const sin = await open()
    expect(sin.wrapper.text()).not.toContain('Contactar a soporte')

    vi.stubEnv('VITE_SUPPORT_URL', 'mailto:soporte@universidad.example')
    const con = await open()
    const link = con.wrapper.find('a[href^="mailto:"]')
    expect(link.text()).toBe('Contactar a soporte')
  })

  it('sin token: QR inválido y no llama a la API', async () => {
    const { wrapper } = await open('/s')

    expect(previewMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('QR inválido')
  })

  it('usa el token que conservó el login (RF-QR-05)', async () => {
    previewMock.mockResolvedValue(PREVIEW)
    setPendingScanToken('guardado')
    await open('/s')

    expect(previewMock).toHaveBeenCalledWith('guardado')
  })
})
