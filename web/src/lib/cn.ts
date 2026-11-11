import { clsx, type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

// Teach tailwind-merge the app's custom font sizes, so `text-sm` and `text-tx-3` are not treated as conflicts.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      'font-size': [{ text: ['micro', 'xs', 'sm', 'base', 'md', 'lg', 'xl', 'title', 'kpi'] }],
    },
  },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
