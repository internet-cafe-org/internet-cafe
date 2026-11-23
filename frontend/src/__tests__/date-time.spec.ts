import { describe, expect, it } from 'vitest'

import { formatDateTime } from '../utils/dateTime'

describe('formatDateTime', () => {
  it('convierte UTC a hora de Colombia con formato dd/mm/aaaa, hh:mm', () => {
    expect(formatDateTime('2026-11-04T14:15:00Z')).toBe('04/11/2026, 09:15')
  })

  it('usa 24 horas y no muestra 24:00 a medianoche', () => {
    expect(formatDateTime('2026-11-04T05:00:00Z')).toBe('04/11/2026, 00:00')
  })
})
