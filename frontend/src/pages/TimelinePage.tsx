/**
 * Timeline: year rail, twelve month bars, month sections of trip cards.
 *
 * A trip is one day (04 section 10), so a month section is a list of days -
 * there is no multi-day entity to fold them into.
 */

import { useMemo, useState } from 'react'

import { useStats, useTrips } from '@/api/hooks'
import TripCard from '@/components/TripCard'
import { useCopy } from '@/i18n'

export default function TimelinePage() {
  const t = useCopy()
  const trips = useTrips({ limit: 500 })
  const stats = useStats()
  const [year, setYear] = useState<number | null>(null)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const years = useMemo(() => {
    const counts = new Map<number, number>()
    for (const trip of trips.data ?? []) {
      const key = Number(trip.local_date.slice(0, 4))
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => b[0] - a[0])
  }, [trips.data])

  const activeYear = year ?? years[0]?.[0] ?? new Date().getUTCFullYear()

  const monthBars = useMemo(() => {
    const bars = new Array(12).fill(0)
    for (const entry of stats.data?.activity ?? []) {
      if (Number(entry.day.slice(0, 4)) !== activeYear) continue
      const month = Number(entry.day.slice(5, 7)) - 1
      bars[month] += entry.places + (entry.distance_m > 0 ? 1 : 0)
    }
    return bars
  }, [stats.data, activeYear])

  const months = useMemo(() => {
    const grouped = new Map<string, typeof trips.data>()
    for (const trip of trips.data ?? []) {
      if (Number(trip.local_date.slice(0, 4)) !== activeYear) continue
      const key = trip.local_date.slice(0, 7)
      grouped.set(key, [...(grouped.get(key) ?? []), trip])
    }
    return [...grouped.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1))
  }, [trips.data, activeYear])

  const peak = Math.max(1, ...monthBars)
  const yearCount = years.find(([value]) => value === activeYear)?.[1] ?? 0

  return (
    <div className="page">
      <div className="split">
        <aside className="split__aside split__aside--years">
          {years.map(([value, count]) => (
            <button
              key={value}
              className="year-item"
              aria-current={value === activeYear}
              onClick={() => setYear(value)}
            >
              <span className="year-item__year">{value}</span>
              <span className="num faint" style={{ fontSize: 11 }}>
                {count}
              </span>
            </button>
          ))}
        </aside>

        <div className="split__main">
          <div className="page__title">
            <span
              style={{
                fontFamily: 'var(--font-heading)',
                fontSize: 52,
                lineHeight: 0.9,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {activeYear}
            </span>
            <span className="muted" style={{ fontSize: 13, paddingBottom: 8 }}>
              {yearCount} {t.timeline.trips}
            </span>
          </div>

          <div className="row" style={{ alignItems: 'flex-end', height: 44, margin: '18px 0 4px', gap: 6 }}>
            {monthBars.map((value, index) => (
              <div
                key={index}
                style={{
                  flex: 1,
                  height: `${Math.max(4, (value / peak) * 100)}%`,
                  background: `color-mix(in srgb, var(--color-accent) ${Math.round(
                    30 + (value / peak) * 70,
                  )}%, transparent)`,
                }}
              />
            ))}
          </div>
          <div className="row faint" style={{ gap: 6, fontSize: 10, marginBottom: 24 }}>
            {monthBars.map((_, index) => (
              <div key={index} style={{ flex: 1, textAlign: 'center' }}>
                {t.timeline.monthLabel(index + 1)}
              </div>
            ))}
          </div>

          {months.map(([key, list]) => {
            const isOpen = !collapsed.has(key)
            return (
              <section key={key} style={{ marginBottom: 14 }}>
                <button
                  className="row"
                  style={{
                    all: 'unset',
                    cursor: 'pointer',
                    display: 'flex',
                    width: '100%',
                    padding: '7px 0',
                    borderBottom: '1px solid var(--color-divider)',
                    gap: 10,
                  }}
                  onClick={() =>
                    setCollapsed((current) => {
                      const next = new Set(current)
                      if (next.has(key)) next.delete(key)
                      else next.add(key)
                      return next
                    })
                  }
                >
                  <span className="muted" style={{ width: 12 }}>
                    {isOpen ? '▾' : '▸'}
                  </span>
                  <span style={{ fontFamily: 'var(--font-heading)', fontSize: 22 }}>
                    {t.timeline.monthLabel(Number(key.slice(5, 7)))}
                  </span>
                  <span className="num muted" style={{ marginLeft: 'auto', fontSize: 12 }}>
                    {(list ?? []).length} {t.timeline.trips}
                  </span>
                </button>
                {isOpen && (
                  <div className="grid grid--wide" style={{ paddingTop: 12 }}>
                    {(list ?? []).map((trip) => (
                      <TripCard key={trip.id} trip={trip} />
                    ))}
                  </div>
                )}
              </section>
            )
          })}
        </div>
      </div>
    </div>
  )
}
