'use client'

import { Mail, Monitor, Phone, Smartphone } from 'lucide-react'
import { outlineClass } from '../../_ui/marks'
import { cx } from '@/components/ui2/cx'
import { canWhatsApp, waLinks } from '@/lib/whatsapp'

export type Channel = 'web' | 'app' | 'call' | 'email'

export type ContactTarget = {
  phone: string | null
  phoneType: string | null
  message: string | null
  email?: string | null
  emailSubject?: string | null
  emailBody?: string | null
}

/**
 * The links that open a conversation, all outlined (the page has one solid button, in the header).
 * WhatsApp only for mobile numbers (plan 12.10); landlines get Call; no phone means email.
 * `onOpen` runs in the same click, after the browser has started opening the link.
 */
export function ContactButtons({
  target,
  onOpen,
  disabled,
  className,
}: {
  target: ContactTarget
  onOpen?: (channel: Channel) => void
  disabled?: boolean
  className?: string
}) {
  const text = target.message ?? ''
  const links = target.phone ? waLinks(target.phone, text) : null
  const wa = canWhatsApp(target.phoneType, target.phone) && links
  const props = (channel: Channel) => ({ onClick: () => onOpen?.(channel), 'aria-disabled': disabled || undefined })
  const cls = (extra?: string) => outlineClass('small', extra)
  return (
    <div className={cx('flex flex-wrap items-center gap-2', className)}>
      {wa ? (
        <>
          <a href={links.web} target="_blank" rel="noopener noreferrer" className={cls('hidden lg:inline-flex')} {...props('web')}>
            <Monitor aria-hidden />
            WhatsApp Web
          </a>
          <a href={links.app} target="_blank" rel="noopener noreferrer" className={cls()} {...props('app')}>
            <Smartphone aria-hidden />
            WhatsApp app
          </a>
        </>
      ) : target.phone ? (
        <a href={`tel:${target.phone}`} className={cls()} {...props('call')}>
          <Phone aria-hidden />
          Call
        </a>
      ) : null}
      {target.email ? (
        <a
          href={`mailto:${target.email}?subject=${encodeURIComponent(target.emailSubject ?? '')}&body=${encodeURIComponent(target.emailBody ?? text)}`}
          className={cls()}
          {...props('email')}
        >
          <Mail aria-hidden />
          Email
        </a>
      ) : null}
      {!target.phone && !target.email ? <span className="type-subhead text-label-3">No published number or email yet</span> : null}
    </div>
  )
}
