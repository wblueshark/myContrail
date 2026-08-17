/** Trip list: group chips over a self-sizing card grid. */

import { useGroups, useTrips } from '@/api/hooks'
import TripCard from '@/components/TripCard'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

export default function TripsPage() {
  const t = useCopy()
  const groupFilter = useAppStore((state) => state.groupFilter)
  const setGroupFilter = useAppStore((state) => state.setGroupFilter)
  const groups = useGroups()
  const trips = useTrips({ group: groupFilter ?? undefined, limit: 300 })

  return (
    <div className="page page--scroll">
      <div className="row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 18 }}>
        <label className="radio" style={{ padding: '5px 11px', border: '1px solid var(--color-divider)' }}>
          <input
            type="radio"
            name="grp"
            checked={groupFilter === null}
            onChange={() => setGroupFilter(null)}
          />
          <span className="dot" />
          {t.trips.allGroups}
        </label>
        {(groups.data ?? []).map((group) => (
          <label
            key={group.id}
            className="radio"
            style={{ padding: '5px 11px', border: '1px solid var(--color-divider)' }}
          >
            <input
              type="radio"
              name="grp"
              checked={groupFilter === group.id}
              onChange={() => setGroupFilter(group.id)}
            />
            <span className="dot" />
            {group.name}
          </label>
        ))}
      </div>

      {trips.isSuccess && trips.data.length === 0 ? (
        <p className="muted">{t.app.empty}</p>
      ) : (
        <div className="grid">
          {(trips.data ?? []).map((trip) => (
            <TripCard key={trip.id} trip={trip} />
          ))}
        </div>
      )}
    </div>
  )
}
