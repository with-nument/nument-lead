'use client'

import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { toast } from 'sonner'
import { Button, type ButtonProps } from './button'

export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export function CopyButton({
  text,
  label = 'Copy',
  copiedLabel = 'Copied',
  toastMessage,
  ...props
}: Omit<ButtonProps, 'onClick'> & { text: string; label?: string; copiedLabel?: string; toastMessage?: string }) {
  const [done, setDone] = useState(false)
  return (
    <Button
      {...props}
      onClick={async () => {
        if (await copyText(text)) {
          setDone(true)
          if (toastMessage) toast(toastMessage)
          setTimeout(() => setDone(false), 1600)
        } else toast.error('Could not copy. Select the text and copy it by hand.')
      }}
    >
      {done ? <Check aria-hidden /> : <Copy aria-hidden />}
      <span>{done ? copiedLabel : label}</span>
    </Button>
  )
}
