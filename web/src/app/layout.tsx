import type { Metadata, Viewport } from 'next'
import { DM_Mono, Figtree, Inter, Newsreader } from 'next/font/google'
import { ClassicToaster } from './classic-toaster'
import './globals.css'

// Current-design (v1) kit fonts. Not preloaded: the sign-in page and new-design pages never use them,
// so they no longer download there; current-design pages load them on first use (with a size-matched
// fallback, so nothing shifts).
const display = Newsreader({ subsets: ['latin'], variable: '--nf-display', axes: ['opsz'], display: 'swap', preload: false })
const sans = Figtree({ subsets: ['latin'], variable: '--nf-sans', display: 'swap', preload: false })
const mono = DM_Mono({ subsets: ['latin'], weight: ['400', '500'], variable: '--nf-mono', display: 'swap', preload: false })
// New design: San Francisco on Apple devices (nothing downloaded). Inter is only the fallback where
// the system has no SF, fetched the first time text needs it.
const inter = Inter({ subsets: ['latin'], variable: '--font-inter', display: 'swap', preload: false })

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
    <html lang="en-IN" className={`${display.variable} ${sans.variable} ${mono.variable} ${inter.variable}`}>
      <body>
        {children}
        <ClassicToaster />
      </body>
    </html>
  )
}
