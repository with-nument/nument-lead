import type { Metadata, Viewport } from 'next'
import { DM_Mono, Figtree, Newsreader } from 'next/font/google'
import { Toaster } from 'sonner'
import './globals.css'

const display = Newsreader({ subsets: ['latin'], variable: '--nf-display', axes: ['opsz'], display: 'swap' })
const sans = Figtree({ subsets: ['latin'], variable: '--nf-sans', display: 'swap' })
const mono = DM_Mono({ subsets: ['latin'], weight: ['400', '500'], variable: '--nf-mono', display: 'swap' })

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
    <html lang="en-IN" className={`${display.variable} ${sans.variable} ${mono.variable}`}>
      <body>
        {children}
        <Toaster position="bottom-right" closeButton duration={5000} />
      </body>
    </html>
  )
}
