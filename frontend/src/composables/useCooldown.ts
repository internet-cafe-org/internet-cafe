import { computed, onBeforeUnmount, ref } from 'vue'

/** Cuenta regresiva en segundos para bloquear un botón (p. ej. «Reenviar código»). */
export function useCooldown(seconds: number) {
  const remaining = ref(0)
  let timer: ReturnType<typeof setInterval> | undefined

  function stop() {
    clearInterval(timer)
    timer = undefined
  }

  function start() {
    stop()
    remaining.value = seconds
    timer = setInterval(() => {
      remaining.value -= 1
      if (remaining.value <= 0) {
        remaining.value = 0
        stop()
      }
    }, 1000)
  }

  onBeforeUnmount(stop)
  return { remaining, active: computed(() => remaining.value > 0), start }
}
