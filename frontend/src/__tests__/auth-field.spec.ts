import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AuthField from '@/components/AuthField.vue'

function mountPassword() {
  return mount(AuthField, {
    props: { id: 'password', label: 'Contraseña', modelValue: '', type: 'password' },
  })
}

describe('AuthField: botón de mostrar contraseña', () => {
  it('oculta la contraseña por defecto, con el icono de ojo tachado', () => {
    const wrapper = mountPassword()
    const toggle = wrapper.get('button.field__toggle')

    expect(wrapper.get('input').attributes('type')).toBe('password')
    expect(toggle.attributes('aria-label')).toBe('Mostrar contraseña')
    expect(toggle.attributes('aria-pressed')).toBe('false')
    expect(toggle.get('.pi').classes()).toContain('pi-eye-slash')
  })

  it('al pulsarlo muestra la contraseña: icono de ojo, misma etiqueta y aria-pressed activo', async () => {
    const wrapper = mountPassword()
    const toggle = wrapper.get('button.field__toggle')

    await toggle.trigger('click')

    expect(wrapper.get('input').attributes('type')).toBe('text')
    expect(toggle.attributes('aria-label')).toBe('Mostrar contraseña')
    expect(toggle.attributes('aria-pressed')).toBe('true')
    expect(toggle.get('.pi').classes()).toContain('pi-eye')
    expect(toggle.get('.pi').classes()).not.toContain('pi-eye-slash')
  })

  it('al pulsarlo otra vez vuelve a ocultarla', async () => {
    const wrapper = mountPassword()
    const toggle = wrapper.get('button.field__toggle')

    await toggle.trigger('click')
    await toggle.trigger('click')

    expect(wrapper.get('input').attributes('type')).toBe('password')
    expect(toggle.attributes('aria-pressed')).toBe('false')
    expect(toggle.get('.pi').classes()).toContain('pi-eye-slash')
  })

  it('un campo que no es de contraseña no muestra el botón', () => {
    const wrapper = mount(AuthField, {
      props: { id: 'email', label: 'Correo', modelValue: '', type: 'email' },
    })

    expect(wrapper.find('button.field__toggle').exists()).toBe(false)
  })
})
