/**
 * Activity histogram plus a time window slider.
 *
 * Dragging this only rewrites a Mapbox filter expression - the tiles already in
 * the browser carry the timestamps as feature attributes, so there is no
 * request and no re-render of the map data. That is what keeps it at 60 fps.
 */

import { useMemo } from 'react'

import { useStats } from '@/api/hooks'
import { t } from '@/i18n/zh'
import { useAppStore } from '@/store/appStore'

const BUCKETS = 120

export default function TimelineSlider() {
  const stats = useStats()
  const timeFrom = useAppStore((state) => state.timeFrom)
  const timeTo = useAppStore((state) => state.timeTo)
  const setTimeRange = useAppStore((state) => state.setTimeRange)

  const { buckets, min, max } = useMemo(() => {
    const activity = stats.data?.activity ?? []
    if (!activity.length) return { buckets: [] as number[], min: 0, max: 0 }
    const times = activity.map((entry) => new Date(`${entry.day}T00:00:00Z`).getTime())
    const lo = Math.min(...times)
    const hi = Math.max(...times)
    const span = Math.max(hi - lo, 1)
    const out = new Array<number>(BUCKETS).fill(0)
    activity.forEach((entry, index) => {
      const slot = Math.min(BUCKETS - 1, Math.floor(((times[index] ?? lo) - lo) / span * BUCKETS))
      out[slot] = (out[slot] ?? 0) + entry.places + (entry.distance_m > 0 ? 1 : 0)
    })
    return { buckets: out, min: lo, max: hi }
  }, [stats.data])

  if (!buckets.length) {
    return <div className="map-layout__timeline faint">{t.timeline.noData}</div>
  }

  const peak = Math.max(...buckets, 1)
  const span = Math.max(max - min, 1)
  const fromRatio = timeFrom ? (new Date(timeFrom).getTime() - min) / span : 0
  const toRatio = timeTo ? (new Date(timeTo).getTime() - min) / span : 1

  const setFromRatio = (ratio: number) =>
    setTimeRange(new Date(min + ratio * span).toISOString(), timeTo)
  const setToRatio = (ratio: number) =>
    setTimeRange(timeFrom, new Date(min + ratio * span).toISOString())

  return (
    <div className="map-layout__timeline">
      <div className="timeline__bars" aria-hidden>
        {buckets.map((value, index) => {
          const ratio = index / BUCKETS
          const inWindow = ratio >= fromRatio && ratio <= toRatio
          return (
            <div
              key={index}
              className={`timeline__bar ${inWindow ? 'timeline__bar--active' : 'timeline__bar--muted'}`}
              style={{ height: `${Math.max(2, (value / peak) * 100)}%` }}
            />
          )
        })}
      </div>
      <div className="timeline__range">
        <span className="faint">{new Date(min).toISOString().slice(0, 10)}</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.001}
          value={fromRatio}
          onChange={(event) => setFromRatio(Number(event.target.value))}
          aria-label={t.timeline.year}
        />
        <input
          type="range"
          min={0}
          max={1}
          step={0.001}
          value={toRatio}
          onChange={(event) => setToRatio(Number(event.target.value))}
          aria-label={t.timeline.day}
        />
        <span className="faint">{new Date(max).toISOString().slice(0, 10)}</span>
        <button className="ghost" onClick={() => setTimeRange(null, null)}>
          {t.filters.timeAll}
        </button>
      </div>
    </div>
  )
}
