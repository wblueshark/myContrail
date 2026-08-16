/**
 * Commute results and disposal.
 *
 * Two rules drive the UI:
 *   the evidence is shown, because every criterion is a plain statistic;
 *   only a PURE commute day may be deleted, and a mixed day says why not -
 *   deleting it would take the other places and photos with it.
 */

import { useState } from 'react'

import { useCommuteAction, useCommuteOds, useCommuteTrips, useRecomputeCommute } from '@/api/hooks'
import { t } from '@/i18n/zh'

function hourLabel(hour: number | null): string {
  if (hour === null) return '—'
  const h = Math.floor(hour)
  const m = Math.round((hour - h) * 60)
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`
}

export default function CommutePage() {
  const ods = useCommuteOds()
  const trips = useCommuteTrips()
  const action = useCommuteAction()
  const recompute = useRecomputeCommute()
  const [selected, setSelected] = useState<string[]>([])

  const coldStart = recompute.data && recompute.data.ran === false
  const pureSelected = (trips.data ?? [])
    .filter((trip) => selected.includes(trip.id))
    .every((trip) => trip.deletable)

  return (
    <div className="page">
      <div className="row row--between">
        <h1>{t.commute.title}</h1>
        <button onClick={() => recompute.mutate()} disabled={recompute.isPending}>
          {t.commute.recompute}
        </button>
      </div>

      {/* Fewer than 30 workdays: the detector does not run, and says so. This is
          the correct answer for a two-month holiday dataset, not a failure. */}
      {coldStart && recompute.data && (
        <div className="notice notice--warn">
          {t.commute.coldStart(
            recompute.data.workdays ?? 0,
            recompute.data.required_workdays ?? 30,
          )}
        </div>
      )}

      {ods.data && <p className="faint">{t.commute.detected(ods.data.length)}</p>}

      {(ods.data ?? []).map((od) => (
        <div className="card" key={od.id}>
          <h3>
            {od.from.label ?? od.from.kind} → {od.to.label ?? od.to.kind}
          </h3>
          <div className="row row--wrap">
            <span className="pill">{t.commute.occurrence(od.occurrence)}</span>
            <span className="pill">
              {t.commute.weekdayRatio(Math.round((od.weekday_ratio ?? 0) * 100))}
            </span>
            <span className="pill">
              {t.commute.departHour(
                hourLabel(od.depart_hour_mean),
                (od.depart_hour_circstd ?? 0).toFixed(1),
              )}
            </span>
            <span className="pill">
              {t.commute.pathStability(Math.round((od.path_jaccard ?? 0) * 100))}
            </span>
          </div>

          <details style={{ marginTop: 8 }}>
            <summary className="faint">{t.commute.evidence}</summary>
            <div className="stack" style={{ marginTop: 6 }}>
              <span className="faint">
                {t.commute.sampleDates}: {(od.evidence.sample_dates ?? []).join(', ')}
              </span>
              <span className="faint">
                {t.commute.medianDistance}:{' '}
                {od.evidence.median_distance_m
                  ? `${(od.evidence.median_distance_m / 1000).toFixed(1)} km`
                  : t.detail.distanceUnknown}
                {od.evidence.distance_unknown_count
                  ? ` (${od.evidence.distance_unknown_count} ${t.detail.distanceUnknown})`
                  : ''}
              </span>
            </div>
          </details>
        </div>
      ))}

      <h2 style={{ marginTop: 20 }}>{t.nav.trips}</h2>
      <div className="row" style={{ marginBottom: 10 }}>
        <button
          disabled={selected.length === 0}
          onClick={() => action.mutate({ trip_ids: selected, action: 'collapse' })}
        >
          {t.commute.actionCollapse}
        </button>
        <button
          disabled={selected.length === 0}
          onClick={() => action.mutate({ trip_ids: selected, action: 'to_normal' })}
        >
          {t.commute.actionToNormal}
        </button>
        <button
          className="danger"
          // Disabled unless every selected day is pure. The server also refuses
          // with 422, so this is only about not offering an impossible action.
          disabled={selected.length === 0 || !pureSelected}
          onClick={() => {
            if (window.confirm(t.commute.deleteWarning)) {
              action.mutate({ trip_ids: selected, action: 'delete' })
              setSelected([])
            }
          }}
        >
          {t.commute.actionDelete}
        </button>
      </div>

      <table>
        <tbody>
          {(trips.data ?? []).map((trip) => (
            <tr key={trip.id}>
              <td style={{ width: 30 }}>
                <input
                  type="checkbox"
                  checked={selected.includes(trip.id)}
                  onChange={() =>
                    setSelected((current) =>
                      current.includes(trip.id)
                        ? current.filter((id) => id !== trip.id)
                        : [...current, trip.id],
                    )
                  }
                />
              </td>
              <td>
                <strong>{trip.title}</strong>
                <div className="faint">{trip.local_date}</div>
              </td>
              <td>
                <span className="pill">
                  {trip.commute_class === 'pure' ? t.commute.classPure : t.commute.classMixed}
                </span>
              </td>
              <td className="faint">
                {/* A mixed day states exactly what would be lost. */}
                {trip.deletable
                  ? `${trip.commute_track_count} ×  🚇`
                  : t.commute.mixedNotDeletable(trip.place_count, trip.photo_count)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {trips.data && trips.data.length === 0 && <p className="faint">{t.app.empty}</p>}
    </div>
  )
}
