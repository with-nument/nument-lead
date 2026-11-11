/** The Nument flourish from the design kit (assets/ornament.svg), drawn in the current colour. */
export function Ornament({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 208 32"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      className={className}
    >
      <path d="M4 30h200" />
      <path d="M104 4c-6 8-6 16 0 24c6-8 6-16 0-24Z" />
      <path d="M92 26c-10-2-20-8-26-16c8 2 18 6 26 16Z" />
      <path d="M116 26c10-2 20-8 26-16c-8 2-18 6-26 16Z" />
      <path d="M60 26c-12 0-26-4-36-10c12 0 26 4 36 10Z" />
      <path d="M148 26c12 0 26-4 36-10c-12 0-26 4-36 10Z" />
      <circle cx="104" cy="16" r="1.6" fill="currentColor" stroke="none" />
    </svg>
  )
}
