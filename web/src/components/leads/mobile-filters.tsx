'use client'

import { SlidersHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Drawer, DrawerContent, DrawerTrigger } from '@/components/ui/drawer'
import { activeFilterCount, type LeadFilters } from '@/lib/leads-filters'
import { FilterPanel, type FilterOptions } from './filter-panel'

export function MobileFilters({ filters, options, showOwner }: { filters: LeadFilters; options: FilterOptions; showOwner: boolean }) {
  const count = activeFilterCount(filters)
  return (
    <Drawer>
      <DrawerTrigger asChild>
        <Button variant="secondary" className="lg:hidden" data-tour="lead-filters-mobile">
          <SlidersHorizontal aria-hidden />
          Filters{count ? ` · ${count}` : ''}
        </Button>
      </DrawerTrigger>
      <DrawerContent title="Filters">
        <div className="p-4">
          <FilterPanel filters={filters} options={options} showOwner={showOwner} />
        </div>
      </DrawerContent>
    </Drawer>
  )
}
