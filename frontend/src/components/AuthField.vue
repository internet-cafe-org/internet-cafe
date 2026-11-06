<script setup lang="ts">
import { computed, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    id: string
    label: string
    modelValue: string
    type?: 'text' | 'email' | 'password'
    placeholder?: string
    error?: string
    hint?: string
    autocomplete?: string
    disabled?: boolean
  }>(),
  { type: 'text', placeholder: '', error: '', hint: '', autocomplete: 'off', disabled: false },
)

defineEmits<{ 'update:modelValue': [value: string] }>()

const visible = ref(false)
const isPassword = computed(() => props.type === 'password')
const inputType = computed(() => (isPassword.value && visible.value ? 'text' : props.type))
const describedBy = computed(() => {
  const ids: string[] = []
  if (props.hint) ids.push(`${props.id}-hint`)
  if (props.error) ids.push(`${props.id}-error`)
  return ids.length > 0 ? ids.join(' ') : undefined
})
</script>

<template>
  <div class="field">
    <label :for="id" class="field__label">{{ label }}</label>
    <div class="field__control" :class="{ 'field__control--error': error }">
      <input
        :id="id"
        class="field__input"
        :type="inputType"
        :value="modelValue"
        :placeholder="placeholder"
        :autocomplete="autocomplete"
        :disabled="disabled"
        :aria-invalid="error ? 'true' : undefined"
        :aria-describedby="describedBy"
        @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      />
      <button
        v-if="isPassword"
        type="button"
        class="field__toggle"
        :aria-label="visible ? 'Ocultar contraseña' : 'Mostrar contraseña'"
        :aria-pressed="visible"
        :disabled="disabled"
        @click="visible = !visible"
      >
        <span class="pi" :class="visible ? 'pi-eye-slash' : 'pi-eye'" aria-hidden="true"></span>
      </button>
      <span
        v-if="error"
        class="field__error-icon pi pi-exclamation-circle"
        aria-hidden="true"
      ></span>
    </div>
    <p v-if="hint" :id="`${id}-hint`" class="field__hint">{{ hint }}</p>
    <p v-if="error" :id="`${id}-error`" class="field__error">Error: {{ error }}</p>
  </div>
</template>

<style scoped>
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.field__label {
  font-size: 14px;
  font-weight: 600;
}
.field__control {
  display: flex;
  align-items: center;
  min-height: 48px;
  padding: 0 12px;
  gap: 8px;
  background: #fff;
  border: 1px solid #d7e0ec;
  border-radius: 8px;
}
.field__control:focus-within {
  border: 2px solid #2563eb;
  padding: 0 11px;
}
.field__control--error {
  border-color: #b42318;
}
.field__input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: #19365c;
  font: inherit;
}
.field__input::placeholder {
  color: #7a8799;
}
.field__input:disabled {
  color: #52647a;
}
.field__control:has(.field__input:disabled) {
  background: #e8edf4;
}
.field__toggle {
  min-width: 32px;
  min-height: 32px;
  border: 0;
  background: transparent;
  color: #52647a;
  cursor: pointer;
}
.field__toggle:focus-visible {
  outline: 2px solid #2563eb;
  border-radius: 4px;
}
.field__error-icon {
  color: #b42318;
}
.field__hint {
  margin: 0;
  font-size: 12px;
  color: #52647a;
}
.field__error {
  margin: 0;
  font-size: 12px;
  color: #b42318;
}
</style>
