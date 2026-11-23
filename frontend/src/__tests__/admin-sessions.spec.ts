import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { http, HttpResponse } from 'msw'

import App from '../App.vue'
import { createAppRouter } from '../router'
import { server } from '../mocks/server'
import { useSessionStore } from '../stores/session'
import SessionsView from '../views/admin/SessionsView.vue'
import {
  buildExportSessionsUrl,
  downloadBlob,
  exportAdminSessionsCsv,
  forceEndSession,
  getAdminLabs,
  getAdminSessions,
} from '../services/adminSessions'
import { setAccessToken } from '../api/client'

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

  it('construye la URL de exportación con parámetros correctamente (buildExportSessionsUrl)', () => {
    const urlSinFiltros = buildExportSessionsUrl()
    expect(urlSinFiltros).toBe('http://localhost:8000/api/v1/admin/sessions/export')

    const urlConFiltros = buildExportSessionsUrl({
      machine_code: 'LAB3-PC12',
      lab_id: 'lab-001',
      state: 'active',
      started_from: '2026-11-01T00:00:00Z',
      started_to: '2026-11-20T23:59:59Z',
      student: 'ana.perez@universidad.edu.co',
    })
    expect(urlConFiltros).toContain('machine_code=LAB3-PC12')
    expect(urlConFiltros).toContain('lab_id=lab-001')
    expect(urlConFiltros).toContain('state=active')
    expect(urlConFiltros).toContain('started_from=2026-11-01T00%3A00%3A00Z')
    expect(urlConFiltros).toContain('started_to=2026-11-20T23%3A59%3A59Z')
    expect(urlConFiltros).toContain('student=ana.perez%40universidad.edu.co')
  })

  it('exporta accesos a CSV mediante Fetch API y devuelve Blob (exportAdminSessionsCsv)', async () => {
    setAccessToken('mock-admin-token')
    const result = await exportAdminSessionsCsv({ machine_code: 'LAB3-PC12' })

    expect(result.blob).toBeInstanceOf(Blob)
    expect(result.filename).toBe('accesos.csv')
    expect(result.truncated).toBe(false)

    const text = await result.blob.text()
    expect(text).toContain(
      'estudiante,código,equipo,sala,inicio,fin,duración en minutos,motivo de cierre',
    )
    expect(text).toContain('Ana Pérez')
    expect(text).toContain('LAB3-PC12')
  })

  it('detecta cabecera X-Export-Truncated cuando el archivo supera el límite', async () => {
    setAccessToken('mock-admin-token')
    const result = await exportAdminSessionsCsv({ machine_code: 'TRUNCATED' })

    expect(result.truncated).toBe(true)
    expect(result.filename).toBe('accesos.csv')
  })

  it('lanza ApiError cuando la petición de exportación no está autorizada (401)', async () => {
    setAccessToken(null)
    await expect(exportAdminSessionsCsv()).rejects.toThrow()
  })

  it('lanza ApiError cuando el servidor responde con error 500', async () => {
    setAccessToken('mock-admin-token')
    await expect(exportAdminSessionsCsv({ machine_code: 'SERVER_ERROR' })).rejects.toThrow()
  })

  it('inicia la descarga con createObjectURL y la libera con revokeObjectURL (downloadBlob)', () => {
    const mockCreateObjectURL = vi.fn().mockReturnValue('blob:http://localhost/mock-uuid')
    const mockRevokeObjectURL = vi.fn()
    window.URL.createObjectURL = mockCreateObjectURL
    window.URL.revokeObjectURL = mockRevokeObjectURL

    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const blob = new Blob(['col1,col2\nval1,val2'], { type: 'text/csv' })
    downloadBlob(blob, 'prueba-descarga.csv')

    expect(mockCreateObjectURL).toHaveBeenCalledWith(blob)
    expect(clickSpy).toHaveBeenCalled()
    expect(mockRevokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/mock-uuid')

    clickSpy.mockRestore()
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

  it('renderiza el botón de exportar CSV con el icono de descarga (HU-33 / ST-UI-05)', async () => {
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    const exportBtn = wrapper.find('.btn-export')
    expect(exportBtn.exists()).toBe(true)
    expect(exportBtn.text()).toContain('Exportar CSV')
    expect(exportBtn.find('.pi-download').exists()).toBe(true)
  })

  it('ejecuta la exportación a CSV con Fetch y Blob al pulsar el botón (HU-33)', async () => {
    const mockCreateObjectURL = vi.fn().mockReturnValue('blob:http://localhost/mock-uuid-2')
    const mockRevokeObjectURL = vi.fn()
    window.URL.createObjectURL = mockCreateObjectURL
    window.URL.revokeObjectURL = mockRevokeObjectURL

    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    setAccessToken('mock-admin-token')
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    const exportBtn = wrapper.find('.btn-export')
    await exportBtn.trigger('click')
    await flushPromises()

    expect(mockCreateObjectURL).toHaveBeenCalled()
    expect(clickSpy).toHaveBeenCalled()
    expect(mockRevokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/mock-uuid-2')

    expect(wrapper.find('.alert-banner--success').exists()).toBe(true)
    expect(wrapper.text()).toContain('Archivo accesos.csv descargado con éxito.')

    clickSpy.mockRestore()
  })

  it('informa al usuario cuando la exportación supera el límite y viene truncada', async () => {
    const mockCreateObjectURL = vi.fn().mockReturnValue('blob:http://localhost/mock-uuid-3')
    const mockRevokeObjectURL = vi.fn()
    window.URL.createObjectURL = mockCreateObjectURL
    window.URL.revokeObjectURL = mockRevokeObjectURL

    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    setAccessToken('mock-admin-token')
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.get('#filter-machine').setValue('TRUNCATED')
    const exportBtn = wrapper.find('.btn-export')
    await exportBtn.trigger('click')
    await flushPromises()

    expect(wrapper.find('.alert-banner--success').exists()).toBe(true)
    expect(wrapper.text()).toContain('truncado por el servidor')

    clickSpy.mockRestore()
  })

  it('valida el rango de fechas al pulsar exportar y no realiza la petición si es inválido', async () => {
    const mockCreateObjectURL = vi.fn()
    window.URL.createObjectURL = mockCreateObjectURL

    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.get('#filter-from').setValue('2026-11-25')
    await wrapper.get('#filter-to').setValue('2026-11-20')

    const exportBtn = wrapper.find('.btn-export')
    await exportBtn.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('La fecha "desde" no puede ser posterior a la fecha "hasta"')
    expect(mockCreateObjectURL).not.toHaveBeenCalled()
  })

  it('muestra banner de error cuando la exportación falla y permite cerrarlo', async () => {
    setAccessToken('mock-admin-token')
    const { pinia, router } = await setupAdmin()
    const wrapper = mount(SessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.get('#filter-machine').setValue('SERVER_ERROR')
    const exportBtn = wrapper.find('.btn-export')
    await exportBtn.trigger('click')
    await flushPromises()

    expect(wrapper.find('.alert-banner--error').exists()).toBe(true)
    expect(wrapper.text()).toContain('Error al exportar accesos')

    // Permite cerrar el banner
    const closeBtn = wrapper.find('.alert-banner--error .alert-banner__close')
    await closeBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.alert-banner--error').exists()).toBe(false)
  })
})
