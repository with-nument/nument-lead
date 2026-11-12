/** WhatsApp links are built when shown, never stored, so a fixed phone number updates them at once. */
export function waLinks(phone: string, text: string) {
  const digits = phone.replace(/\D/g, '')
  const t = encodeURIComponent(text)
  return {
    web: `https://web.whatsapp.com/send?phone=${digits}&text=${t}`,
    app: `https://wa.me/${digits}?text=${t}`,
  }
}

/** The plan only allows WhatsApp to mobile numbers. Landlines get a Call button instead. */
export const canWhatsApp = (phoneType: string | null | undefined, phone: string | null | undefined) =>
  Boolean(phone) && phoneType === 'mobile'
