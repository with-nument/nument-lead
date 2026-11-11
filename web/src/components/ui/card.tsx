import { cn } from '@/lib/cn'

export function Card({ className, children, ...props }: React.HTMLAttributes<HTMLElement>) {
  return (
    <section className={cn('rounded-2xl border border-line-2 bg-surface', className)} {...props}>
      {children}
    </section>
  )
}

export function CardHeader({
  title,
  description,
  actions,
  className,
  id,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  className?: string
  id?: string
}) {
  return (
    <header className={cn('flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-4 pt-4 sm:px-5', className)}>
      <div className="min-w-0">
        <h2 id={id} className="label-mono">
          {title}
        </h2>
        {description ? <p className="mt-1 text-sm text-tx-3">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  )
}

export function CardBody({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn('px-4 pt-3 pb-4 sm:px-5 sm:pb-5', className)}>{children}</div>
}
