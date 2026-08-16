/** Year -> month -> day drill-down, plus the statistics panel. */

import { useMemo, useState } from 'react'

import { useStats, useTrips } from '@/api/hooks'
import { t } from '@/i18n/zh'
import { useAppStore } from '@/store/appStore'
import { formatKm } from './TripsPage'

export default function TimelinePage() {
  const navigate = useAppStore((state) => state.navigate)
  const [year, setYear] = useState<number | null>(null)
  const [month, setMonth] = useState<number | null>(null)

  const stats = useStats()
  const trips = useTrips({ limit: 2000 })

  const byYear = useMemo(() => {
    const map = new Map<number, { days: number; distance: number }>()
    for (const trip of trips.data ?? []) {
      const y = Number(trip.local_date.slice(0, 4))
      const entry = map.get(y) ?? { days: 0, distance: 0 }
      entry.days += 1
      entry.distance += trip.stats.distance_total_m ?? 0
      map.set(y, entry)
    }
    return [...map.entries()].sort((a, b) => b[0] - a[0])
  }, [trips.data])

  const months = useMemo(() => {
    if (year === null) return []
    const map = new Map<number, number>()
    for (const trip of trips.data ?? []) {
      if (Number(trip.local_date.slice(0, 4)) !== year) continue
      const m = Number(trip.local_date.slice(5, 7))
      map.set(m, (map.get(m) ?? 0) + 1)
    }
    return [...map.entries()].sort((a, b) => a[0] - b[0])
  }, [trips.data, year])

  const days = useMemo(
    () =>
      (trips.data ?? []).filter((trip) => {
        if (year !== null && Number(trip.local_date.slice(0, 4)) !== year) return false
        if (month !== null && Number(trip.local_date.slice(5, 7)) !== month) return false
        return true
      }),
    [trips.data, year, month],
  )

  const s = stats.data

  return (
    <div className="page">
      <h1>{t.timeline.title}</h1>

      {s && (
        <div className="card">
          <div className="row row--wrap">
            <span className="pill">
              {t.stats.trips} {s.trip_count}
            </span>
            <span className="pill">
              {t.stats.distance} {formatKm(s.distance_total_m)}
            </span>
            <span className="pill">
              {t.stats.countries} {s.countries}
            </span>
            <span className="pill">
              {t.stats.cities} {s.cities}
            </span>
            <span className="pill">
              {t.stats.places} {s.place_count}
            </span>
            <span className="pill">
              {t.stats.photos} {s.photos.total}
            </span>
          </div>

          {/* The honest footnotes. A total that hides what it excludes is a lie. */}
          <div className="stack" style={{ marginTop: 10 }}>
            {s.unknown_distance_segments > 0 && (
              <span className="faint">{t.stats.unknownDistance(s.unknown_distance_segments)}</span>
            )}
            {s.inferred_dwell_count > 0 && (
              <span className="faint">{t.stats.inferredDwell(s.inferred_dwell_count)}</span>
            )}
            {s.photos.inferred_location > 0 && (
              <span className="faint">{t.stats.inferredPhotos(s.photos.inferred_location)}</span>
            )}
            {s.photos.unlocated > 0 && (
              <span className="faint">{t.stats.unlocatedPhotos(s.photos.unlocated)}</span>
            )}
            {s.countries === 0 && s.place_count > 0 && (
              <span className="faint">{t.stats.geocodingOff}</span>
            )}
          </div>
        </div>
      )}

      <div className="row row--wrap" style={{ marginBottom: 12 }}>
        <button
          className={year === null ? 'primary' : ''}
          onClick={() => {
            setYear(null)
            setMonth(null)
          }}
        >
          {t.filters.timeAll}
        </button>
        {byYear.map(([value, entry]) => (
          <button
            key={value}
            className={year === value ? 'primary' : ''}
            onClick={() => {
              setYear(value)
              setMonth(null)
            }}
          >
            {value}
            <span className="faint"> · {entry.days}d</span>
          </button>
        ))}
      </div>

      {year !== null && (
        <div className="row row--wrap" style={{ marginBottom: 12 }}>
          <button className={month === null ? 'primary' : ''} onClick={() => setMonth(null)}>
            {t.filters.timeAll}
          </button>
          {months.map(([value, count]) => (
            <button
              key={value}
              className={month === value ? 'primary' : ''}
              onClick={() => setMonth(value)}
            >
              {value} {t.timeline.month}
              <span className="faint"> · {count}</span>
            </button>
          ))}
        </div>
      )}

      {days.length === 0 && <p className="faint">{t.timeline.noData}</p>}

      <table>
        <tbody>
          {days.map((trip) => (
            <tr key={trip.id}>
              <td className="faint">{trip.local_date}</td>
              <td>
                <button
                  className="ghost"
                  style={{ textAlign: 'left' }}
                  onClick={() => navigate({ name: 'trip', id: trip.id })}
                >
                  {trip.title}
                </button>
              </td>
              <td>{formatKm(trip.stats.distance_total_m)}</td>
              <td className="faint">
                {trip.stats.place_count ?? 0} / {trip.stats.photo_count ?? 0}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
