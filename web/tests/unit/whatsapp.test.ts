import { describe, expect, it } from 'vitest'
import { canWhatsApp, waLinks } from '@/lib/whatsapp'

describe('waLinks', () => {
  it('builds both links with digits only and the text encoded', () => {
    const l = waLinks('+91 98110 12345', 'Hi, test? A&B\nok')
    expect(l.web).toBe('https://web.whatsapp.com/send?phone=919811012345&text=Hi%2C%20test%3F%20A%26B%0Aok')
    expect(l.app).toBe('https://wa.me/919811012345?text=Hi%2C%20test%3F%20A%26B%0Aok')
  })

  it('only allows WhatsApp to mobile numbers', () => {
    expect(canWhatsApp('mobile', '+919811012345')).toBe(true)
    expect(canWhatsApp('landline', '+912012345678')).toBe(false)
    expect(canWhatsApp('mobile', null)).toBe(false)
  })
})
