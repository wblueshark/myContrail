/**
 * Activity density, binned by month, dragged to set the time window.
 *
 * Dragging only rewrites a Mapbox filter expression - the tiles already in the
 * browser carry timestamps as feature attributes, so there is no request and no
 * re-render of map data. That is what keeps it at 60 fps.
 *
 * The axis is derived from the data, never hard-coded: the design comp's
 * 2011-2026 labels belong to its sample, not to whoever is running this.
 */

import { Image as ImageIcon } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'

import { useStats } from '@/api/hooks'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

interface Bin {
  key: string
  year: number
  month: number
  weight: number
}

function monthKey(day: string): string {
  return day.slice(0, 7)
}

function buildBins(activity: Array<{ day: string; places: number; distance_m: number }>): Bin[] {
  if (!activity.length) return []
  const totals = new Map<string, number>()
  for (const entry of activity) {
    const key = monthKey(entry.day)
    totals.set(key, (totals.get(key) ?? 0) + entry.places + (entry.distance_m > 0 ? 1 : 0))
  }
  const days = activity.map((entry) => entry.day).sort()
  const first = days[0]!
  const last = days[days.length - 1]!
  const bins: Bin[] = []
  let year = Number(first.slice(0, 4))
  let month = Number(first.slice(5, 7))
  const endYear = Number(last.slice(0, 4))
  const endMonth = Number(last.slice(5, 7))
  while (year < endYear || (year === endYear && month <= endMonth)) {
    const key = `${year}-${String(month).padStart(2, '0')}`
    bins.push({ key, year, month, weight: totals.get(key) ?? 0 })
    month += 1
    if (month > 12) {
      month = 1
      year += 1
    }
  }
  return bins
}

export default function Histogram({ onExport }: { onExport: () => void }) {
  const t = useCopy()
  const stats = useStats()
  const timeFrom = useAppStore((state) => state.timeFrom)
  const timeTo = useAppStore((state) => state.timeTo)
  const setTimeRange = useAppStore((state) => state.setTimeRange)

  const bars = useRef<HTMLDivElement>(null)
  const [dragStart, setDragStart] = useState<number | null>(null)

  const bins = useMemo(() => buildBins(stats.data?.activity ?? []), [stats.data])
  const peak = Math.max(1, ...bins.map((bin) => bin.weight))

  const indexAt = (clientX: number): number => {
    const box = bars.current?.getBoundingClientRect()
    if (!box || !bins.length) return 0
    const ratio = (clientX - box.left) / box.width
    return Math.max(0, Math.min(bins.length - 1, Math.floor(ratio * bins.length)))
  }

  const applyRange = (a: number, b: number) => {
    const lo = bins[Math.min(a, b)]
    const hi = bins[Math.max(a, b)]
    if (!lo || !hi) return
    const from = new Date(Date.UTC(lo.year, lo.month - 1, 1)).toISOString()
    const to = new Date(Date.UTC(hi.year, hi.month, 0, 23, 59, 59)).toISOString()
    setTimeRange(from, to)
  }

  const inWindow = (bin: Bin): boolean => {
    if (!timeFrom && !timeTo) return true
    const start = Date.UTC(bin.year, bin.month - 1, 1)
    const end = Date.UTC(bin.year, bin.month, 0, 23, 59, 59)
    if (timeFrom && end < new Date(timeFrom).getTime()) return false
    return !(timeTo && start > new Date(timeTo).getTime())
  }

  const axis = useMemo(() => {
    const years = [...new Set(bins.map((bin) => bin.year))]
    const step = Math.max(1, Math.ceil(years.length / 8))
    return years.filter((_, index) => index % step === 0)
  }, [bins])

  if (!bins.length) {
    return (
      <div className="map__histogram">
        <div className="row row--between">
          <span className="kicker">{t.map.density}</span>
          <span className="muted">{t.timeline.noData}</span>
        </div>
      </div>
    )
  }

  return (
    <div className="map__histogram">
      <div className="row">
        <span className="kicker">{t.map.density}</span>
        <span className="num" style={{ fontSize: 11.5 }}>
          {timeFrom ? timeFrom.slice(0, 7) : bins[0]!.key} —{' '}
          {timeTo ? timeTo.slice(0, 7) : bins[bins.length - 1]!.key}
        </span>
        <span className="muted" style={{ fontSize: 11.5 }}>
          {t.map.dragHint}
        </span>
        <button className="btn btn-primary btn-sm" style={{ marginLeft: 'auto' }} onClick={onExport}>
          <ImageIcon size={13} strokeWidth={1.5} />
          {t.map.exportPng}
        </button>
      </div>

      <div
        ref={bars}
        className="histogram__bars"
        onMouseDown={(event) => {
          const index = indexAt(event.clientX)
          setDragStart(index)
          applyRange(index, index)
        }}
        onMouseMove={(event) => {
          if (dragStart === null) return
          applyRange(dragStart, indexAt(event.clientX))
        }}
        onMouseUp={() => setDragStart(null)}
        onMouseLeave={() => setDragStart(null)}
      >
        {bins.map((bin) => (
          <div
            key={bin.key}
            className={`histogram__bar ${inWindow(bin) ? 'histogram__bar--in' : ''}`}
            style={{ height: `${Math.max(6, (bin.weight / peak) * 100)}%` }}
            title={bin.key}
          />
        ))}
      </div>

      <div className="histogram__axis">
        {axis.map((year) => (
          <span key={year}>{year}</span>
        ))}
      </div>
    </div>
  )
}
