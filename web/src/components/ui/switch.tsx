'use client'

import { Switch as S } from 'radix-ui'
import { cn } from '@/lib/cn'

export function Switch({
  checked,
  onCheckedChange,
  disabled,
  label,
  className,
}: {
  checked: boolean
  onCheckedChange: (v: boolean) => void
  disabled?: boolean
  label: string
  className?: string
}) {
  return (
    <S.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={label}
      className={cn(
        'relative inline-flex h-6 w-10 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200 ease-ui',
        'bg-grey-300 data-[state=checked]:bg-slate disabled:cursor-not-allowed disabled:opacity-45',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
        className,
      )}
    >
      <S.Thumb className="block size-5 translate-x-0.5 rounded-full bg-white shadow-[0_1px_2px_rgb(0_0_0/0.2)] transition-transform duration-200 ease-ui data-[state=checked]:translate-x-[18px]" />
    </S.Root>
  )
}
