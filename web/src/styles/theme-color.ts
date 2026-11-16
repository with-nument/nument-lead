/**
 * Browser chrome colour for v2 pages and the sign-in pages: the top of the wash (--ui-wash-1 in
 * theme.css), light and dark. The meta tag cannot read CSS variables; tests/unit/contrast.test.ts
 * checks these stay equal to the CSS values.
 */
export const THEME_COLOR = [
  { media: '(prefers-color-scheme: light)', color: '#dfe6f8' },
  { media: '(prefers-color-scheme: dark)', color: '#0b1022' },
]

/** Browser chrome colour for the sign-in pages: --ui-signin-canvas in theme.css (light only). */
export const SIGNIN_THEME_COLOR = '#f4f4f4'
