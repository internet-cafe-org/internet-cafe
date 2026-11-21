import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { http, HttpResponse } from 'msw'

import App from '../App.vue'
import { createAppRouter } from '../router'
import { server } from '../mocks/server'
import { useSessionStore } from '../stores/session'
import SessionsView from '../views/admin/SessionsView.vue'
import { forceEndSession, getAdminLabs, getAdminSessions } from '../services/adminSessions'

const API_URL = 'http://localhost:8000'

async function setupAdmin(path = '/admin/sessions') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const session = useSessionStore()
  session.setUser('Super Admin', 'admin')

  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()

  return { pinia, router, session }
}

describe('Servicio adminSessions', () => {
  it('obtiene la lista de accesos con getAdminSessions', async () => {
    const page = await getAdminSessions({ limit: 10, offset: 0 })
    expect(page.items).toBeDefined()
    expect(page.items.length).toBeGreaterThan(0)
    expect(page.total).toBeGreaterThan(0)
  })

  it('obtiene accesos filtrados por machine_code', async () => {
    const page = await getAdminSessions({ machine_code: 'LAB3-PC12' })
    expect(page.items.length).toBe(1)
    expect(page.items[0]?.machine_code).toBe('LAB3-PC12')
  })

  it('obtiene el listado de salas con getAdminLabs', async () => {
    const labs = await getAdminLabs()
    expect(labs.length).toBeGreaterThan(0)
    expect(labs[0]?.name).toBe('Sala 1')
  })

  it('fuerza el cierre de una sesión con forceEndSession', async () => {
    const closed = await forceEndSession('sess-001')
    expect(closed.id).toBe('sess-001')
    expect(closed.end_reason).toBe('admin_forced')
    expect(closed.ended_at).toBeDefined()
  })

  it('lanza error cuando la sesión no existe (404)', async () => {
    await expect(forceEndSession('not-found')).rejects.toThrow()
  })
})

describe('Vista SessionsView (W-12 - HU-15)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renderiza la vista con la lista de accesos y salas', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(App, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.find('h1').text()).toBe('Historial de accesos')
    expect(wrapper.text()).toContain('Ana Pérez')
    expect(wrapper.text()).toContain('2021****34')
    expect(wrapper.text()).toContain('LAB3-PC12')
    expect(wrapper.text()).toContain('Activa')
    expect(wrapper.text()).toContain('Carlos Gómez')
    expect(wrapper.text()).toContain('Cerrada')
  })

  it('permite filtrar por código de equipo', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    const machineInput = wrapper.get('#filter-machine')
    await machineInput.setValue('LAB3-PC12')
    await wrapper.get('.filters-form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('LAB3-PC12')
    expect(wrapper.text()).not.toContain('LAB1-PC05')
  })

  it('permite filtrar por sala', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    const labSelect = wrapper.get('#filter-lab')
    await labSelect.setValue('lab-001')
    await wrapper.get('.filters-form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('LAB1-PC05')
    expect(wrapper.text()).not.toContain('LAB3-PC12')
  })

  it('permite filtrar por estado (activas)', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    const stateSelect = wrapper.get('#filter-state')
    await stateSelect.setValue('active')
    await wrapper.get('.filters-form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Ana Pérez')
    expect(wrapper.text()).not.toContain('Carlos Gómez')
  })

  it('permite filtrar localmente por estudiante', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    const studentInput = wrapper.get('#filter-student')
    await studentInput.setValue('Carlos')
    await flushPromises()

    expect(wrapper.text()).toContain('Carlos Gómez')
    expect(wrapper.text()).not.toContain('Ana Pérez')
  })

  it('valida que fecha desde no sea posterior a fecha hasta', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.get('#filter-from').setValue('2026-11-25')
    await wrapper.get('#filter-to').setValue('2026-11-20')
    await wrapper.get('.filters-form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('La fecha "desde" no puede ser posterior a la fecha "hasta"')
  })

  it('limpia los filtros al pulsar "Limpiar filtros"', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.get('#filter-machine').setValue('LAB3-PC12')
    await wrapper.get('.filters-form').trigger('submit')
    await flushPromises()

    const clearBtn = wrapper.find('.filters-actions .btn-secondary')
    await clearBtn.trigger('click')
    await flushPromises()

    expect((wrapper.get('#filter-machine').element as HTMLInputElement).value).toBe('')
    expect(wrapper.text()).toContain('Ana Pérez')
    expect(wrapper.text()).toContain('Carlos Gómez')
  })

  it('muestra estado vacío cuando no hay resultados', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.get('#filter-machine').setValue('NO_EXISTE')
    await wrapper.get('.filters-form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('No hay accesos con estos filtros')
    expect(wrapper.find('.state-card--empty').exists()).toBe(true)
  })

  it('muestra estado de error cuando la API falla y permite reintentar', async () => {
    server.use(
      http.get(`${API_URL}/api/v1/admin/sessions`, () => {
        return HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Error de servidor',
            status: 500,
            detail: 'Fallo interno en la base de datos.',
            code: 'INTERNAL_ERROR',
          },
          { status: 500, headers: { 'Content-Type': 'application/problem+json' } },
        )
      }),
    )

    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Error al cargar accesos')
    expect(wrapper.find('.btn-retry').exists()).toBe(true)
  })

  it('abre el diálogo de confirmación de cierre forzado al hacer clic en el botón', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    const forceBtn = wrapper.find('.btn-force-close')
    expect(forceBtn.exists()).toBe(true)
    await forceBtn.trigger('click')
    await flushPromises()

    expect(wrapper.find('.modal-backdrop').exists()).toBe(true)
    expect(wrapper.text()).toContain('¿Forzar el cierre de esta sesión?')
    expect(wrapper.text()).toContain('admin_forced')
  })

  it('cancela el diálogo de confirmación de cierre forzado sin realizar petición', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.find('.btn-force-close').trigger('click')
    await flushPromises()
    expect(wrapper.find('.modal-backdrop').exists()).toBe(true)

    const cancelBtn = wrapper.find('.modal-card__footer .btn-secondary')
    await cancelBtn.trigger('click')
    await flushPromises()

    expect(wrapper.find('.modal-backdrop').exists()).toBe(false)
  })

  it('ejecuta el cierre forzado con éxito, actualiza la fila y muestra banner', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.find('.btn-force-close').trigger('click')
    await flushPromises()

    const confirmBtn = wrapper.find('.modal-card__footer .btn-danger')
    await confirmBtn.trigger('click')
    await flushPromises()

    expect(wrapper.find('.modal-backdrop').exists()).toBe(false)
    expect(wrapper.text()).toContain('cerrada forzadamente con éxito')
    expect(wrapper.text()).toContain('Cierre forzado')
  })

  it('muestra error en el modal si falla el cierre forzado', async () => {
    server.use(
      http.post(`${API_URL}/api/v1/admin/sessions/:id/end`, () => {
        return HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Sesión no encontrada',
            status: 404,
            detail: 'La sesión no existe.',
            code: 'SESSION_NOT_FOUND',
          },
          { status: 404, headers: { 'Content-Type': 'application/problem+json' } },
        )
      }),
    )

    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.find('.btn-force-close').trigger('click')
    await flushPromises()

    const confirmBtn = wrapper.find('.modal-card__footer .btn-danger')
    await confirmBtn.trigger('click')
    await flushPromises()

    expect(wrapper.find('.modal-backdrop').exists()).toBe(true)
    expect(wrapper.text()).toContain('La sesión indicada no existe o ya no está disponible.')
  })

  it('soporta paginación cuando hay múltiples páginas', async () => {
    server.use(
      http.get(`${API_URL}/api/v1/admin/sessions`, () => {
        return HttpResponse.json({
          items: [
            {
              id: 'sess-p1',
              user: { id: 'u1', full_name: 'Usuario Uno', student_code_masked: '2021****01' },
              machine_code: 'LAB1-PC01',
              lab: 'Sala 1',
              started_at: '2026-11-20T10:00:00Z',
              last_heartbeat_at: '2026-11-20T10:10:00Z',
              ended_at: null,
              end_reason: null,
              duration_s: null,
            },
          ],
          total: 45,
          limit: 20,
          offset: 0,
        })
      }),
    )

    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Página 1 de 3')
    const nextBtn = wrapper.findAll('.btn-page')[1]
    expect(nextBtn?.attributes('disabled')).toBeUndefined()
  })

  it('permite cerrar la notificación de éxito', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.find('.btn-force-close').trigger('click')
    await flushPromises()
    await wrapper.find('.modal-card__footer .btn-danger').trigger('click')
    await flushPromises()

    expect(wrapper.find('.alert-banner--success').exists()).toBe(true)
    await wrapper.find('.alert-banner__close').trigger('click')
    await flushPromises()
    expect(wrapper.find('.alert-banner--success').exists()).toBe(false)
  })
})
