import { beforeEach, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'

import App from '../App.vue'
import { server } from '../mocks/server'
import { createAppRouter } from '../router'
import { useSessionStore } from '../stores/session'

const API_URL = 'http://localhost:8000'
const MACHINE_ID = '11111111-1111-4111-8111-111111111111'
const LAB_ID = '22222222-2222-4222-8222-222222222222'

type Body = Record<string, unknown>

let patchBodies: Body[]
let enrollmentCalls: number
let revokeCalls: number

function machine(overrides: Body = {}) {
  return {
    id: MACHINE_ID,
    code: 'LAB2-PC04',
    hostname: 'PC-04',
    lab_id: LAB_ID,
    lab: 'Sala 2',
    status: 'active',
    mode: 'passive',
    app_version: '1.0.0',
    enrolled_at: new Date().toISOString(),
    last_seen_at: new Date().toISOString(),
    ...overrides,
  }
}

/** Registra los handlers de la API para el equipo indicado y cuenta las llamadas. */
function useBackend(current = machine()) {
  server.use(
    http.get(`${API_URL}/api/v1/admin/labs`, () =>
      HttpResponse.json({
        items: [{ id: LAB_ID, name: 'Sala 2', building: 'Bloque B' }],
        total: 1,
        limit: 100,
        offset: 0,
      }),
    ),
    http.get(`${API_URL}/api/v1/admin/machines`, () =>
      HttpResponse.json({ items: [current], total: 1, limit: 100, offset: 0 }),
    ),
    http.patch(`${API_URL}/api/v1/admin/machines/:id`, async ({ request }) => {
      const body = (await request.json()) as Body
      patchBodies.push(body)
      return HttpResponse.json({ ...current, ...body })
    }),
    http.post(`${API_URL}/api/v1/admin/machines/:id/enrollment-code`, () => {
      enrollmentCalls++
      return HttpResponse.json(
        { code: 'ABCD-1234', expires_at: new Date(Date.now() + 86_400_000).toISOString() },
        { status: 201 },
      )
    }),
    http.post(`${API_URL}/api/v1/admin/machines/:id/revoke-key`, () => {
      revokeCalls++
      return new HttpResponse(null, { status: 204 })
    }),
  )
}

async function open() {
  const pinia = createPinia()
  setActivePinia(pinia)
  useSessionStore().setUser('Admin', 'admin')
  const router = createAppRouter(createMemoryHistory())
  await router.push(`/admin/machines/${MACHINE_ID}`)
  const wrapper = mount(App, { global: { plugins: [pinia, router] } })
  await flushPromises()
  // La vista termina de cargar cuando aparece el estado del equipo.
  await vi.waitFor(() => expect(wrapper.find('[data-test="status"]').exists()).toBe(true))
  return wrapper
}

const el = (wrapper: VueWrapper, name: string) => wrapper.get(`[data-test="${name}"]`)

beforeEach(() => {
  patchBodies = []
  enrollmentCalls = 0
  revokeCalls = 0
})

describe('MachineDetailView (W-11)', () => {
  it('muestra el código, el estado y la sala del equipo', async () => {
    useBackend()
    const wrapper = await open()

    expect(wrapper.text()).toContain('LAB2-PC04')
    expect(el(wrapper, 'status').text()).toContain('Activo')
    expect((el(wrapper, 'lab-select').element as HTMLSelectElement).value).toBe(LAB_ID)
  })

  it('cambia el modo enviando solo el campo modificado', async () => {
    useBackend()
    const wrapper = await open()

    await el(wrapper, 'mode-select').setValue('kiosk')
    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => expect(patchBodies).toEqual([{ mode: 'kiosk' }]))
  })

  it('genera el código de enrolamiento y lo descarta al cerrarlo', async () => {
    useBackend()
    const wrapper = await open()

    await el(wrapper, 'gen-code').trigger('click')
    await vi.waitFor(() => expect(el(wrapper, 'enroll-code').text()).toBe('ABCD-1234'))
    expect(enrollmentCalls).toBe(1)

    await el(wrapper, 'close-code').trigger('click')
    expect(wrapper.find('[data-test="enroll-code"]').exists()).toBe(false)
  })

  it('deshabilita el equipo solo después de confirmar', async () => {
    useBackend()
    const wrapper = await open()

    await el(wrapper, 'disable').trigger('click')
    expect(patchBodies).toEqual([])

    await el(wrapper, 'confirm').trigger('click')
    await vi.waitFor(() => expect(patchBodies).toEqual([{ status: 'disabled' }]))
  })

  it('revoca la clave solo después de confirmar', async () => {
    useBackend()
    const wrapper = await open()

    await el(wrapper, 'revoke').trigger('click')
    expect(revokeCalls).toBe(0)

    await el(wrapper, 'confirm').trigger('click')
    await vi.waitFor(() => expect(revokeCalls).toBe(1))
  })

  it('al habilitar un equipo no enrolado muestra el conflicto del servidor', async () => {
    useBackend(machine({ status: 'disabled' }))
    server.use(
      http.patch(`${API_URL}/api/v1/admin/machines/:id`, () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Conflicto',
            status: 409,
            detail: 'No enrolado.',
            code: 'CONFLICT',
          },
          { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    )
    const wrapper = await open()

    await el(wrapper, 'enable').trigger('click')
    await vi.waitFor(() => expect(el(wrapper, 'error').text()).toContain('no se enrolló'))
  })
})
