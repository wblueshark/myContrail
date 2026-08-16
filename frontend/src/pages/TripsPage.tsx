import { useGroups, useTrips } from '@/api/hooks'
import type { Trip } from '@/api/types'
import ExportPanel from '@/components/ExportPanel'
import { t } from '@/i18n/zh'
import { useAppStore } from '@/store/appStore'

export function formatKm(meters: number | undefined): string {
  if (!meters) return '0 km'
  return `${(meters / 1000).toFixed(meters >= 100_000 ? 0 : 1)} km`
}

export function TripCard({
  trip,
  selected,
  onToggle,
}: {
  trip: Trip
  selected: boolean
  onToggle: () => void
}) {
  const navigate = useAppStore((state) => state.navigate)
  const stats = trip.stats

  return (
    <div className={`card card--interactive ${selected ? 'card--selected' : ''}`}>
      <div className="row row--between">
        <button className="ghost" style={{ textAlign: 'left', flex: 1 }} onClick={() => navigate({ name: 'trip', id: trip.id })}>
          <strong>{trip.title}</strong>
          <div className="faint">{trip.local_date}</div>
        </button>
        <label className="check">
          <input type="checkbox" checked={selected} onChange={onToggle} />
        </label>
      </div>

      <div className="row row--wrap" style={{ marginTop: 8 }}>
        {stats.place_count ? <span className="pill">{t.trips.places(stats.place_count)}</span> : null}
        {stats.track_count ? <span className="pill">{t.trips.tracks(stats.track_count)}</span> : null}
        {stats.photo_count ? <span className="pill">{t.trips.photos(stats.photo_count)}</span> : null}
        {stats.distance_total_m ? <span className="pill">{formatKm(stats.distance_total_m)}</span> : null}
        {trip.commute_class !== 'none' && (
          <span className="pill">
            🚇 {trip.commute_class === 'pure' ? t.commute.classPure : t.commute.classMixed}
          </span>
        )}
        {/* A day that crosses zones needs its label, or the times look wrong. */}
        {trip.crosses_tz && <span className="pill pill--warn">⇄ {t.detail.crossesTz}</span>}
        {stats.photo_only && <span className="pill pill--warn">{t.trips.photoOnly}</span>}
      </div>

      {/* Unknown mileage is stated, never folded into the total as zero. */}
      {stats.distance_unknown_segments ? (
        <p className="faint" style={{ marginTop: 6 }}>
          {t.trips.unknownDistanceHint(stats.distance_unknown_segments)}
        </p>
      ) : null}
    </div>
  )
}

export default function TripsPage() {
  const store = useAppStore()
  const groups = useGroups()
  const trips = useTrips({
    group: store.groupFilter ?? undefined,
    tag: store.tagFilter ?? undefined,
    from: store.timeFrom?.slice(0, 10),
    to: store.timeTo?.slice(0, 10),
    limit: 500,
  })

  const selected = store.exportTripIds

  return (
    <div className="page">
      <div className="row row--between">
        <h1>{t.trips.title}</h1>
        <div className="row">
          <select
            value={store.groupFilter ?? ''}
            onChange={(event) => store.setGroupFilter(event.target.value || null)}
          >
            <option value="">{t.filters.timeAll}</option>
            {(groups.data ?? []).map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
          <button
            className="primary"
            disabled={selected.length === 0}
            onClick={() => store.setExportOpen(true)}
          >
            {t.trips.export} ({selected.length})
          </button>
        </div>
      </div>

      <div className="notice">{t.trips.editableNotice}</div>

      {trips.isLoading && <p className="faint">{t.app.loading}</p>}
      {trips.data && <p className="faint">{t.trips.count(trips.data.length)}</p>}

      {(trips.data ?? []).map((trip) => (
        <TripCard
          key={trip.id}
          trip={trip}
          selected={selected.includes(trip.id)}
          onToggle={() => store.toggleExportTrip(trip.id)}
        />
      ))}

      {trips.data && trips.data.length === 0 && <p className="faint">{t.app.empty}</p>}
      <ExportPanel />
    </div>
  )
}
