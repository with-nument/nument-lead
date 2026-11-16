import type { Viewport } from 'next'
import { AuthArt } from '@/components/auth/auth-art'
import { SIGNIN_THEME_COLOR } from '@/styles/theme-color'

export const viewport: Viewport = { themeColor: SIGNIN_THEME_COLOR, colorScheme: 'light' }

/**
 * Sign-in, reset and new-password pages (the approved mock, 16 Nov 2026): the form on the left, the
 * floating card and coins on the right. Phones and narrow windows: the art on top (46vh), the form below.
 * Black, white and greys only, in Figtree (the app's --nf-sans: one font file, shared with the app).
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="signin-root grid min-h-dvh grid-cols-2 bg-signin-canvas font-signin text-[15px] leading-[normal] font-normal text-signin-ink antialiased [color-scheme:light] signin-phone:grid-cols-1">
      <div className="relative flex min-w-0 flex-col justify-center pr-[6vw] pl-[12vw] signin-phone:px-6 signin-phone:pt-8 signin-phone:pb-[90px]">
        <p className="absolute top-10 left-[12vw] text-[24px] font-bold tracking-[-0.035em] text-signin-ink-strong signin-phone:static signin-phone:mb-7">
          nument
        </p>
        <main className="w-[400px] max-w-full">{children}</main>
        <p className="absolute bottom-[34px] left-[12vw] text-[13px] text-signin-label-4 signin-phone:left-6">Nument Lead desk · Private workspace for Team Nument</p>
      </div>
      <div className="relative signin-phone:order-first signin-phone:h-[46vh]">
        <AuthArt />
      </div>
    </div>
  )
}
