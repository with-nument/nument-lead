import type { Metadata, Viewport } from 'next'
import { DM_Mono, Figtree, Newsreader } from 'next/font/google'
import { ClassicToaster } from './classic-toaster'
import './globals.css'

// Figtree is the type of both designs (the new design reads it as --ui-font), so it is preloaded.
// The other current-design (v1) kit fonts are not: they load on first use (with a size-matched fallback,
// so nothing shifts).
const sans = Figtree({ subsets: ['latin'], variable: '--nf-sans', display: 'swap' })
const display = Newsreader({ subsets: ['latin'], variable: '--nf-display', axes: ['opsz'], display: 'swap', preload: false })
const mono = DM_Mono({ subsets: ['latin'], weight: ['400', '500'], variable: '--nf-mono', display: 'swap', preload: false })

export const metadata: Metadata = {
  title: { default: 'Nument Leads', template: '%s · Nument Leads' },
  description: 'Daily, evidence-backed leads for the Nument team.',
  applicationName: 'Nument Leads',
  robots: { index: false, follow: false },
}

export const viewport: Viewport = {
  themeColor: '#fcfcfc',
  width: 'device-width',
  initialScale: 1,
}

export default function RootLayout({ children }: LayoutProps<'/'>) {
  return (
    // suppressHydrationWarning: a new-design page marks <html data-ui="2"> before React hydrates
    // (V2Scope's first-paint script), so the server HTML and the browser differ on that one attribute.
    <html lang="en-IN" suppressHydrationWarning className={`${display.variable} ${sans.variable} ${mono.variable}`}>
      <body>
        {children}
        <ClassicToaster />
      </body>
    </html>
  )
}
