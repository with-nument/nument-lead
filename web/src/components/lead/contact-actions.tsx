'use client'

import { Mail, MessageCircle, Monitor, Phone, Smartphone } from 'lucide-react'
import { buttonClasses } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { canWhatsApp, waLinks } from '@/lib/whatsapp'

export type ContactTarget = {
  phone: string | null
  phoneType: string | null
  message: string | null
  email?: string | null
  emailSubject?: string | null
  emailBody?: string | null
}

/**
 * The buttons that open a conversation. WhatsApp only for mobile numbers (plan 12.10); landlines get
 * Call. On phones the WhatsApp app button comes first and is the primary one.
 * `onOpen` runs in the same click, after the browser has already started opening the link.
 */
export function ContactButtons({
  target,
  onOpen,
  size = 'sm',
  disabled,
  className,
}: {
  target: ContactTarget
  onOpen?: (channel: 'web' | 'app' | 'call' | 'email') => void
  size?: 'sm' | 'md'
  disabled?: boolean
  className?: string
}) {
  const text = target.message ?? ''
  const links = target.phone ? waLinks(target.phone, text) : null
  const wa = canWhatsApp(target.phoneType, target.phone) && links
  const linkProps = (channel: 'web' | 'app' | 'call' | 'email') => ({
    onClick: () => onOpen?.(channel),
    'aria-disabled': disabled || undefined,
  })

  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      {wa ? (
        <>
          <a
            href={links.web}
            target="_blank"
            rel="noopener noreferrer"
            className={buttonClasses('primary', size, 'hidden sm:inline-flex')}
            {...linkProps('web')}
          >
            <Monitor aria-hidden />
            Open WhatsApp Web
          </a>
          <a
            href={links.app}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(buttonClasses('secondary', size), 'max-sm:btn-ink max-sm:flex-1 max-sm:shadow-[var(--shadow-btn-ink)]')}
            {...linkProps('app')}
          >
            <Smartphone aria-hidden />
            <span className="sm:hidden">Open WhatsApp app</span>
            <span className="hidden sm:inline">WhatsApp app</span>
          </a>
        </>
      ) : target.phone ? (
        <a href={`tel:${target.phone}`} className={buttonClasses('primary', size)} {...linkProps('call')}>
          <Phone aria-hidden />
          Call
        </a>
      ) : target.email ? (
        <a
          href={`mailto:${target.email}?subject=${encodeURIComponent(target.emailSubject ?? '')}&body=${encodeURIComponent(target.emailBody ?? text)}`}
          className={buttonClasses('primary', size)}
          {...linkProps('email')}
        >
          <Mail aria-hidden />
          Write email
        </a>
      ) : (
        <span className="inline-flex items-center gap-1.5 text-sm text-tx-3">
          <MessageCircle aria-hidden className="size-4" />
          No number or email yet
        </span>
      )}
    </div>
  )
}
