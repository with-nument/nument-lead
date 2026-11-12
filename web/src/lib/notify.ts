// Email recipients (Settings > Email recipients) and the test email. Pure: no server or DOM access, so it
// can be unit tested. The engine sends the real emails (engine/src/nument_engine/ops/emails.py); the web
// app only sends the test email, through lib/resend.ts.
import { z } from 'zod'

export const NOTIFY_KINDS = ['morning', 'alerts', 'weekly'] as const
export type NotifyKind = (typeof NOTIFY_KINDS)[number]

export const NOTIFY_KIND_LABEL: Record<NotifyKind, string> = {
  morning: 'Morning list',
  alerts: 'Alerts',
  weekly: 'Weekly report',
}

export const NOTIFY_KIND_HINT: Record<NotifyKind, string> = {
  morning: 'New A and B leads, every morning by 7:30 IST',
  alerts: 'A failed run or spend near the daily cap',
  weekly: 'What worked last week, every Monday',
}

/** The switches on each row: the three kinds plus Active (off pauses every email to that person). */
export const RECIPIENT_FIELDS = [...NOTIFY_KINDS, 'active'] as const
export type RecipientField = (typeof RECIPIENT_FIELDS)[number]

export const FIELD_LABEL: Record<RecipientField, string> = { ...NOTIFY_KIND_LABEL, active: 'Active' }

export type Recipient = {
  id: string
  email: string
  name: string | null
  morning: boolean
  alerts: boolean
  weekly: boolean
  active: boolean
}

export const NewRecipient = z.object({
  email: z.string().trim().toLowerCase().max(254, 'Use at most 254 characters.').pipe(z.email('Enter a valid email.')),
  name: z
    .string()
    .trim()
    .max(80, 'Use at most 80 characters.')
    .transform((v) => v || null),
})

export const RecipientToggle = z.object({
  id: z.uuid(),
  field: z.enum(RECIPIENT_FIELDS),
  value: z.boolean(),
})

/** Addresses on reserved test domains (RFC 2606 and 6761) never get a real email. */
export function isReservedAddress(email: string): boolean {
  const domain = email.trim().toLowerCase().split('@').pop() ?? ''
  if (['example.com', 'example.net', 'example.org'].some((d) => domain === d || domain.endsWith(`.${d}`))) return true
  return /\.(test|example|invalid|localhost)$/.test(domain) || domain === 'localhost'
}

/** What a person will receive, in words: "Morning list and Alerts", or "Paused" when inactive. */
export function receives(r: Pick<Recipient, NotifyKind | 'active'>): string {
  if (!r.active) return 'Paused'
  const on = NOTIFY_KINDS.filter((k) => r[k]).map((k) => NOTIFY_KIND_LABEL[k])
  if (!on.length) return 'Nothing yet'
  return on.length === 1 ? on[0]! : `${on.slice(0, -1).join(', ')} and ${on.at(-1)}`
}

const escapeHtml = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')

const SANS = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

export type TestEmail = { subject: string; html: string; text: string }

/**
 * The sample a "Send test email" click sends: the same frame as the engine's emails (base.html), saying
 * which emails this address gets. No lead data, so it is safe for any recipient.
 */
export function testEmail(r: Pick<Recipient, 'email' | 'name' | NotifyKind | 'active'>, appUrl: string): TestEmail {
  const app = appUrl.replace(/\/+$/, '')
  const hello = r.name ? `Hi ${r.name.split(/\s+/)[0]}, this` : 'This'
  const lines = NOTIFY_KINDS.map((k) => ({ label: NOTIFY_KIND_LABEL[k], hint: NOTIFY_KIND_HINT[k], on: r.active && r[k] }))
  const subject = '[Test] Email from Nument Leads works'
  const intro = `${hello} is a test from Nument Leads. Emails reach ${r.email}, each one sent to this address alone.`
  const rows = lines
    .map(
      (l, i) => `<tr><td style="padding:14px 20px;${i < lines.length - 1 ? 'border-bottom:1px solid #f0f0f0;' : ''}">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="vertical-align:top;"><div style="font:600 15px/22px ${SANS};color:#1f1f1f;">${escapeHtml(l.label)}</div>
          <div style="font:400 13px/20px ${SANS};color:#999999;">${escapeHtml(l.hint)}</div></td>
          <td align="right" style="vertical-align:top;font:600 11px/22px ${SANS};letter-spacing:.06em;text-transform:uppercase;color:${l.on ? '#496D21' : '#999999'};white-space:nowrap;padding-left:12px;">${l.on ? 'On' : 'Off'}</td>
        </tr></table></td></tr>`,
    )
    .join('')
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><title>${escapeHtml(subject)}</title>
<style>@media (max-width: 620px) { .wrap { padding: 12px !important; } .pad { padding-left: 20px !important; padding-right: 20px !important; } .h1 { font-size: 26px !important; line-height: 32px !important; } .btn { display: block !important; text-align: center !important; } }</style></head>
<body style="margin:0;padding:0;background:#f5f5f5;-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#f5f5f5;">Your email settings, and what this address gets.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;"><tr><td class="wrap" align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;">
<tr><td style="padding:0 4px 14px 4px;font:600 14px/20px ${SANS};color:#1f1f1f;"><img src="${app}/icon-192.png" width="22" height="22" alt="" style="vertical-align:-5px;border-radius:6px;margin-right:8px;">Nument <span style="color:#999999;font-weight:500;">Leads</span></td></tr>
<tr><td style="background:#ffffff;border:1px solid #ececec;border-radius:16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td class="pad" style="padding:32px 36px 8px 36px;">
<div style="font:600 12px/16px ${SANS};letter-spacing:.08em;text-transform:uppercase;color:#4250d5;">Test email</div>
<div class="h1" style="font:400 30px/38px Georgia,'Times New Roman',serif;color:#1f1f1f;margin:10px 0 8px 0;">Email works</div>
<div style="font:400 15px/23px ${SANS};color:#666666;">${escapeHtml(intro)}</div>
</td></tr>
<tr><td class="pad" style="padding:20px 36px 0 36px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #ececec;border-radius:14px;">${rows}</table></td></tr>
<tr><td class="pad" style="padding:20px 36px 0 36px;"><a class="btn" href="${app}/settings/email" style="display:inline-block;background:#2a2c33;color:#ffffff;font:600 14px/20px ${SANS};text-decoration:none;padding:10px 18px;border-radius:10px;">Open email settings</a></td></tr>
<tr><td style="padding:32px 0 0 0;"></td></tr>
</table></td></tr>
<tr><td style="padding:18px 8px 0 8px;font:400 12px/18px ${SANS};color:#999999;text-align:center;">Sent by an admin from Settings, Email recipients.<br>Nument Leads, made by Nument</td></tr>
</table></td></tr></table></body></html>`
  const text = [
    'Email works',
    '',
    intro,
    '',
    ...lines.map((l) => `- ${l.label}: ${l.on ? 'on' : 'off'} (${l.hint})`),
    '',
    `Email settings: ${app}/settings/email`,
    '',
  ].join('\n')
  return { subject, html, text }
}
