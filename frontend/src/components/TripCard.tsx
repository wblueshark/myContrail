/** One trip, as it appears on the timeline and in the trip list. */

import { useGroups, useTags } from '@/api/hooks'
import type { Trip } from '@/api/types'
import Blueprint from '@/components/Blueprint'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

export default function TripCard({ trip, showNote = true }: { trip: Trip; showNote?: boolean }) {
  const t = useCopy()
  const navigate = useAppStore((state) => state.navigate)
  const setTimeRange = useAppStore((state) => state.setTimeRange)
  const setExportTrips = useAppStore((state) => state.setExportTrips)
  const setExportOpen = useAppStore((state) => state.setExportOpen)
  const groups = useGroups()
  const tags = useTags()

  const group = groups.data?.find((row) => row.id === trip.group_id)
  const tagNames = (trip.tag_ids ?? [])
    .map((id) => tags.data?.find((row) => row.id === id)?.name)
    .filter((name): name is string => Boolean(name))

  const distanceKm = (trip.stats.distance_total_m ?? 0) / 1000
  const unknown = trip.stats.distance_unknown_segments ?? 0

  const showOnMap = () => {
    setTimeRange(`${trip.local_date}T00:00:00Z`, `${trip.local_date}T23:59:59Z`)
    navigate({ name: 'map' })
  }

  return (
    <Blueprint className="card" style={{ gap: 7 }}>
      <div className="row" style={{ alignItems: 'baseline' }}>
        <span style={{ fontFamily: 'var(--font-heading)', fontSize: 18 }}>{trip.title}</span>
        <span className="num muted" style={{ marginLeft: 'auto', fontSize: 11.5 }}>
          {trip.local_date}
        </span>
      </div>

      <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
        {group && <span className="tag tag-accent">{group.name}</span>}
        {tagNames.map((name) => (
          <span key={name} className="tag tag-outline">
            {name}
          </span>
        ))}
        {trip.crosses_tz && <span className="tag tag-neutral">{t.detail.crossesTz}</span>}
      </div>

      <div className="row num" style={{ gap: 14, fontSize: 12, opacity: 0.8 }}>
        <span>
          {trip.stats.photo_count ?? 0} {t.trips.photos}
        </span>
        <span>{distanceKm.toFixed(1)} km</span>
        <span>
          {trip.stats.place_count ?? 0} {t.trips.places}
        </span>
      </div>

      {showNote && unknown > 0 && (
        <div className="faint" style={{ fontSize: 11.5 }}>
          {t.trips.unknownDistanceHint(unknown)}
        </div>
      )}

      <div className="row" style={{ gap: 6, marginTop: 2 }}>
        <button className="btn btn-secondary btn-sm" onClick={showOnMap}>
          {t.trips.map}
        </button>
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => {
            setExportTrips([trip.id])
            setExportOpen(true)
          }}
        >
          {t.trips.export}
        </button>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => navigate({ name: 'trip', id: trip.id })}
        >
          {t.trips.detail} →
        </button>
      </div>
    </Blueprint>
  )
}
