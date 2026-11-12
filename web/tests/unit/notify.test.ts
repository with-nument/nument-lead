import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NewRecipient, RecipientToggle, RECIPIENT_FIELDS, isReservedAddress, receives, testEmail } from '@/lib/notify'

vi.mock('server-only', () => ({}))

const DASH = /[–—]/
const person = { email: 'aditya@nument.in', name: 'Aditya Rao', morning: true, alerts: false, weekly: true, active: true }

describe('NewRecipient', () => {
  it('lower-cases and trims the email, and an empty name means none', () => {
    expect(NewRecipient.parse({ email: '  Aditya@Nument.IN ', name: '  ' })).toEqual({ email: 'aditya@nument.in', name: null })
    expect(NewRecipient.parse({ email: 'a@b.co', name: ' Aditya ' }).name).toBe('Aditya')
  })

  it('rejects bad emails and long names with plain messages', () => {
    const bad = NewRecipient.safeParse({ email: 'not-an-email', name: '' })
    expect(bad.success).toBe(false)
    expect(bad.error?.issues[0]?.message).toBe('Enter a valid email.')
    const long = NewRecipient.safeParse({ email: 'a@b.co', name: 'x'.repeat(81) })
    expect(long.error?.issues[0]?.message).toBe('Use at most 80 characters.')
  })
})

describe('RecipientToggle', () => {
  it('accepts only the four switches', () => {
    expect(RECIPIENT_FIELDS).toEqual(['morning', 'alerts', 'weekly', 'active'])
    const id = '0f8fad5b-d9cb-469f-a165-70867728950e'
    expect(RecipientToggle.safeParse({ id, field: 'weekly', value: false }).success).toBe(true)
    expect(RecipientToggle.safeParse({ id, field: 'email', value: true }).success).toBe(false)
    expect(RecipientToggle.safeParse({ id: 'x', field: 'weekly', value: true }).success).toBe(false)
  })
})

describe('isReservedAddress', () => {
  it('never mails reserved test domains', () => {
    for (const e of ['e2e-recipient-abc@example.com', 'a@mail.example.org', 'x@foo.test', 'y@host.invalid', 'z@localhost']) expect(isReservedAddress(e)).toBe(true)
    for (const e of ['aditya@nument.in', 'someone@gmail.com', 'a@example.company.in']) expect(isReservedAddress(e)).toBe(false)
  })
})

describe('receives', () => {
  it('says what a person gets in plain words', () => {
    expect(receives(person)).toBe('Morning list and Weekly report')
    expect(receives({ ...person, alerts: true })).toBe('Morning list, Alerts and Weekly report')
    expect(receives({ ...person, morning: false, weekly: false })).toBe('Nothing yet')
    expect(receives({ ...person, active: false })).toBe('Paused')
  })
})

describe('testEmail', () => {
  it('lists what this address gets, with links to the app', () => {
    const e = testEmail(person, 'https://leads.nument.in/')
    expect(e.subject).toBe('[Test] Email from Nument Leads works')
    expect(e.html).toContain('Hi Aditya, this is a test')
    expect(e.html).toContain('https://leads.nument.in/settings/email')
    expect(e.text).toContain('- Morning list: on')
    expect(e.text).toContain('- Alerts: off')
    for (const part of [e.subject, e.html, e.text]) expect(part).not.toMatch(DASH)
  })

  it('escapes names and shows everything off while paused', () => {
    const e = testEmail({ ...person, name: '<b>Eve</b>', active: false }, 'https://x.test')
    expect(e.html).not.toContain('<b>Eve')
    expect(e.html).toContain('&lt;b&gt;Eve')
    expect(e.text).not.toContain(': on')
  })
})

describe('sendEmail', () => {
  const saved = { ...process.env }
  beforeEach(() => {
    vi.resetModules()
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://example.supabase.co'
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'anon-key-for-tests-only-123'
    delete process.env.ALERT_EMAIL_FROM
    delete process.env.ALERT_REPLY_TO
  })
  afterEach(() => {
    process.env = { ...saved }
    vi.unstubAllGlobals()
  })

  it('does nothing without RESEND_API_KEY', async () => {
    delete process.env.RESEND_API_KEY
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const { sendEmail, emailConfigured } = await import('@/lib/resend')
    expect(emailConfigured()).toBe(false)
    expect(await sendEmail('a@nument.in', { subject: 's', html: '<p>h</p>', text: 't' })).toEqual({ ok: false, reason: 'not_configured' })
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('sends one email to one address, from Nument Leads with the founder as reply-to', async () => {
    process.env.RESEND_API_KEY = 're_test_not_real_key'
    const fetchSpy = vi.fn().mockResolvedValue(new Response('{"id":"1"}', { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)
    const { sendEmail, RESEND_URL } = await import('@/lib/resend')
    expect(await sendEmail('a@nument.in', { subject: 's', html: '<p>h</p>', text: 't' })).toEqual({ ok: true })
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(RESEND_URL)
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer re_test_not_real_key')
    const body = JSON.parse(String(init.body))
    expect(body).toMatchObject({ from: 'Nument Leads <leads@nument.in>', to: ['a@nument.in'], reply_to: 'heyy.abhigyan@gmail.com', subject: 's', text: 't' })
  })

  it('reports a rejected email without throwing', async () => {
    process.env.RESEND_API_KEY = 're_test_not_real_key'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 422 })))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { sendEmail } = await import('@/lib/resend')
    expect(await sendEmail('a@nument.in', { subject: 's', html: 'h', text: 't' })).toEqual({ ok: false, reason: 'rejected' })
  })
})
