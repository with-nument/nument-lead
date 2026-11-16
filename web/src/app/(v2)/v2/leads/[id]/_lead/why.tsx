import Link from 'next/link'
import { ExternalLink } from 'lucide-react'
import { cx } from '@/components/ui2/cx'
import { eyebrow, panel } from '../../_ui/marks'
import type { LeadView } from './model'
import type { BestOffer } from './types'

function Source({ url, host, date, prefix }: { url: string | null; host: string; date: string; prefix?: string }) {
  const label = [host, date ? `${prefix ? `${prefix} ` : ''}${date}` : ''].filter(Boolean).join(' · ')
  if (!label) return null
  return url ? (
    <a href={url} target="_blank" rel="noopener noreferrer" className="type-subhead mt-2 inline-flex items-center gap-1.5 text-label-3 hover:text-label-1">
      <ExternalLink aria-hidden className="size-3.5 shrink-0" strokeWidth={1.75} />
      <span className="min-w-0 truncate">{label}</span>
    </a>
  ) : (
    <p className="type-subhead mt-2 text-label-3">{label}</p>
  )
}

/** The evidence: each reason this lead needs us, as a dated quote with its source. */
export function Why({
  view,
  offer,
  isAdmin,
  includeUnverified,
}: {
  view: LeadView
  offer?: BestOffer | null
  isAdmin: boolean
  includeUnverified: boolean
}) {
  const offerText = offer ? [offer.text, offer.timeline, offer.range].filter(Boolean).join(' ') : view.angle
  return (
    <div className="flex flex-col gap-4">
      <section aria-label="Evidence" className={panel}>
        {view.evidence.length ? (
          view.evidence.map((g) => (
            <div key={g.label} className="px-5 py-5 lg:px-[26px] lg:py-[22px] [&+&]:hairline-t">
              <h3 className={cx(eyebrow, 'mb-3')}>{g.label}</h3>
              <div className="flex flex-col gap-[18px]">
                {g.items.map((e, i) => (
                  <figure key={i} className={cx(e.expired && 'opacity-55')}>
                    {e.quote ? (
                      <blockquote className="border-l-2 border-label-3 py-0.5 pl-4 text-[16px] leading-[1.5] text-label-1">&ldquo;{e.quote}&rdquo;</blockquote>
                    ) : (
                      <p className="text-[15.5px] leading-[1.55] text-label-1">{e.text}</p>
                    )}
                    <figcaption>
                      <Source url={e.url} host={e.host} date={e.expired ? `${e.date}, expired` : e.date} />
                    </figcaption>
                  </figure>
                ))}
              </div>
            </div>
          ))
        ) : (
          <div className="px-5 py-8 lg:px-[26px]">
            <h3 className="type-headline text-label-1">No dated evidence yet</h3>
            <p className="type-body mt-1 text-label-3">The engine adds quotes with their source when it finds them. Check the facts below.</p>
          </div>
        )}
        {view.judgeNote ? (
          <div className="px-5 py-5 hairline-t lg:px-[26px] lg:py-[22px]">
            <h3 className={cx(eyebrow, 'mb-2')}>The judge&rsquo;s note</h3>
            <p className="text-[15.5px] leading-[1.55] text-label-1">{view.judgeNote}</p>
          </div>
        ) : null}
      </section>

      {offerText ? (
        <section aria-label={offer ? 'Best offer' : 'Angle'} className={cx(panel, 'px-5 py-5 lg:px-[26px] lg:py-[22px]')}>
          <h3 className={cx(eyebrow, 'mb-2')}>{offer ? `Best offer · ${offer.name}` : 'Best angle'}</h3>
          <p className="text-[17px] leading-[1.45] tracking-[-0.01em] text-label-1 lg:text-[19px]">{offerText}</p>
          {view.pitch || view.testGroup ? (
            <p className="type-subhead mt-3 text-label-3">{[view.pitch && `Pitch: ${view.pitch}`, view.testGroup && `Test group: ${view.testGroup}`].filter(Boolean).join(' · ')}</p>
          ) : null}
        </section>
      ) : null}

      {view.parts.length ? (
        <section aria-label="Score" className={cx(panel, 'px-5 py-5 lg:px-[26px] lg:py-[22px]')}>
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h3 className={eyebrow}>Score</h3>
            <span className="text-[22px] font-semibold tracking-[-0.02em] text-label-1">
              {view.total ?? '–'}
              <span className="type-subhead font-normal text-label-3"> / 100</span>
            </span>
          </div>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            {view.parts.map((p) => (
              <div key={p.label}>
                <dt className="type-subhead text-label-3">{p.label}</dt>
                <dd className="mt-1 flex items-center gap-2">
                  <span className="h-1 flex-1 overflow-hidden rounded-full bg-fill-1">
                    <span className="block h-full rounded-full bg-label-3" style={{ width: `${Math.max(0, Math.min(100, (p.value / p.max) * 100))}%` }} />
                  </span>
                  <span className="type-subhead text-label-2">
                    {Math.round(p.value)}/{p.max}
                  </span>
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      <section aria-labelledby="facts-h" className={panel}>
        <div className="flex items-center justify-between gap-3 px-5 pt-5 lg:px-[26px]">
          <h3 id="facts-h" className={eyebrow}>
            Facts, each with its source
          </h3>
          {isAdmin ? (
            <Link
              href={includeUnverified ? `/leads/${view.id}` : `/leads/${view.id}?unverified=1`}
              scroll={false}
              className="type-subhead text-label-3 underline decoration-separator-strong underline-offset-4 hover:text-label-1"
            >
              {includeUnverified ? 'Verified only' : 'Show unverified'}
            </Link>
          ) : null}
        </div>
        {view.facts.length ? (
          <div className="flex flex-col pb-2">
            {view.facts.map((g) => (
              <div key={g.title} className="px-5 pt-4 lg:px-[26px]">
                <h4 className="type-subhead mb-1 font-semibold text-label-2">{g.title}</h4>
                <dl>
                  {g.items.map((f) => (
                    <div key={f.id} className="grid gap-0.5 py-2.5 hairline-b last:shadow-none sm:grid-cols-[160px_minmax(0,1fr)] sm:gap-4">
                      <dt className="type-subhead text-label-3">{f.label}</dt>
                      <dd className="min-w-0">
                        <span className="break-words text-label-1">{f.value}</span>
                        {!f.verified ? <span className="type-caption ml-2 text-status-warn">unverified</span> : null}
                        {f.quote ? <p className="type-subhead mt-0.5 text-label-3">&ldquo;{f.quote}&rdquo;</p> : null}
                        {f.url ? (
                          <a href={f.url} target="_blank" rel="noopener noreferrer" className="type-caption mt-0.5 inline-flex items-center gap-1 text-label-3 hover:text-label-1">
                            {f.host}
                            <ExternalLink aria-hidden className="size-3" />
                          </a>
                        ) : null}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        ) : (
          <p className="type-body px-5 pt-2 pb-5 text-label-3 lg:px-[26px]">No verified facts yet.</p>
        )}
      </section>
    </div>
  )
}
