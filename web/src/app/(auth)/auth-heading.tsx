/** The page title and the line under it, rising in on load. */
export function AuthHeading({ title, subtitle }: { title: React.ReactNode; subtitle?: string }) {
  return (
    <>
      <h1 className="signin-rise m-0 text-[38px] leading-[1.15] font-semibold tracking-[-0.025em] text-balance [animation-delay:50ms]">{title}</h1>
      {subtitle ? <p className="signin-rise mt-3 text-[15px] text-signin-label-2 [animation-delay:150ms]">{subtitle}</p> : null}
    </>
  )
}
