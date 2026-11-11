import { cn } from '@/lib/cn'

/** Dense data table in kit style: sticky mono header, 44px rows, hairline dividers (plan 15.4.4). */
export function Table({ className, children, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn('w-full text-left text-base', className)} {...props}>
        {children}
      </table>
    </div>
  )
}

export function THead({ children, sticky = true }: { children: React.ReactNode; sticky?: boolean }) {
  return <thead className={cn('bg-surface', sticky && 'sticky top-0 z-10')}>{children}</thead>
}

export function Th({ className, children, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th className={cn('label-mono h-10 border-b border-line-2 px-3 font-normal whitespace-nowrap first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5', className)} {...props}>
      {children}
    </th>
  )
}

export function Tr({ className, children, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr className={cn('border-b border-line-2 last:border-b-0 hover:bg-grey-50', className)} {...props}>
      {children}
    </tr>
  )
}

export function Td({ className, children, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={cn('h-11 px-3 align-middle first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5', className)} {...props}>
      {children}
    </td>
  )
}
