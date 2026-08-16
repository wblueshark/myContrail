/**
 * One day, fully expanded.
 *
 * A timezone-crossing day must label every event with its own zone abbreviation
 * and carry a badge in the header - without that the user reads the times as
 * wrong. Such a day can legitimately exceed 24 hours (37 h measured), because a
 * flight is never split across days.
 */

import { useState } from 'react'

import { api } from '@/api/client'
import { useGroups, usePatchTrip, useTags, useTrip } from '@/api/hooks'
import type { Place, Track } from '@/api/types'
import ExportPanel from '@/components/ExportPanel'
import { t } from '@/i18n/zh'
import { useAppStore } from '@/store/appStore'

function zoneAbbrev(iso: string, tz: string | null): string {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: tz ?? 'UTC',
      timeZoneName: 'short',
    }).formatToParts(new Date(iso))
    return parts.find((part) => part.type === 'timeZoneName')?.value ?? 'UTC'
  } catch {
    return 'UTC'
  }
}

function clock(iso: string, tz: string | null): string {
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: tz ?? 'UTC',
    }).format(new Date(iso))
  } catch {
    return iso.slice(11, 16)
  }
}

function duration(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.round((seconds % 3600) / 60)
  return hours ? `${hours}h${minutes.toString().padStart(2, '0')}m` : `${minutes}m`
}

type Event = { at: string; kind: 'place'; value: Place } | { at: string; kind: 'track'; value: Track }

export default function TripDetailPage({ tripId }: { tripId: string }) {
  const detail = useTrip(tripId)
  const groups = useGroups()
  const tags = useTags()
  const patch = usePatchTrip()
  const store = useAppStore()
  const [title, setTitle] = useState<string | null>(null)

  if (detail.isLoading) return <div className="page faint">{t.app.loading}</div>
  if (!detail.data) return <div className="page faint">{t.app.empty}</div>

  const { trip, places, tracks, photos } = detail.data
  const events: Event[] = [
    ...places.map((place): Event => ({ at: place.start_utc, kind: 'place', value: place })),
    ...tracks.map((track): Event => ({ at: track.start_utc, kind: 'track', value: track })),
  ].sort((a, b) => a.at.localeCompare(b.at))

  const zones = Array.from(
    new Set(events.map((event) => zoneAbbrev(event.at, event.kind === 'place' ? event.value.tz_name : trip.anchor_tz))),
  )

  return (
    <div className="page">
      <div className="row row--between">
        <div>
          <div className="row">
            <h1 style={{ margin: 0 }}>{trip.title}</h1>
            {zones.length > 1 && (
              <span className="pill pill--warn">⇄ {zones.join('→')}</span>
            )}
          </div>
          <p className="faint">
            {trip.local_date} · {trip.anchor_tz} ·{' '}
            {duration((new Date(trip.end_utc).getTime() - new Date(trip.start_utc).getTime()) / 1000)}
          </p>
        </div>
        <div className="row">
          <button onClick={() => store.navigate({ name: 'trips' })}>← {t.nav.trips}</button>
          <button
            className="primary"
            onClick={() => {
              store.setExportTrips([trip.id])
              store.setExportOpen(true)
            }}
          >
            {t.trips.export}
          </button>
        </div>
      </div>

      <div className="card">
        <h4>{t.trips.rename}</h4>
        <div className="row">
          <input
            value={title ?? trip.title}
            onChange={(event) => setTitle(event.target.value)}
          />
          <button
            disabled={title === null || title === trip.title}
            onClick={() => patch.mutate({ id: trip.id, title: title ?? trip.title })}
          >
            {t.app.save}
          </button>
        </div>

        <div className="grid-2" style={{ marginTop: 10 }}>
          <div>
            <h4>{t.trips.assignGroup}</h4>
            <select
              value={trip.group_id ?? ''}
              onChange={(event) =>
                patch.mutate({ id: trip.id, group_id: event.target.value || null })
              }
            >
              <option value="">{t.sources.noGroup}</option>
              {(groups.data ?? []).map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <h4>{t.trips.addTag}</h4>
            <div className="row row--wrap">
              {(tags.data ?? []).map((tag) => {
                const on = trip.tag_ids.includes(tag.id)
                return (
                  <button
                    key={tag.id}
                    className={on ? 'primary' : ''}
                    onClick={() =>
                      patch.mutate({
                        id: trip.id,
                        tag_ids: on
                          ? trip.tag_ids.filter((id) => id !== tag.id)
                          : [...trip.tag_ids, tag.id],
                      })
                    }
                  >
                    {tag.name}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
        <p className="faint" style={{ marginTop: 10 }}>
          {t.trips.editableNotice}
        </p>
      </div>

      <h2>{t.timeline.day}</h2>
      <table>
        <thead>
          <tr>
            <th>{t.timeline.day}</th>
            <th>{t.detail.place}</th>
            <th>{t.detail.duration}</th>
            <th>{t.detail.distance}</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => {
            const tz = event.kind === 'place' ? event.value.tz_name : trip.anchor_tz
            return (
              <tr key={`${event.kind}-${event.value.id}`}>
                <td className="faint">
                  {/* Every row carries its own zone: on a crossing day the
                      clock jumps, and unlabelled it reads as a bug. */}
                  {clock(event.at, tz)} {zoneAbbrev(event.at, tz)}
                </td>
                <td>
                  {event.kind === 'place' ? (
                    <>
                      📍 {event.value.name ?? event.value.geo_name ?? event.value.geo_city ?? t.detail.place}
                      {event.value.is_inferred_dwell && (
                        <span className="pill pill--warn" style={{ marginLeft: 6 }}>
                          {t.detail.inferredDwell(Math.round(event.value.inferred_ratio * 100))}
                        </span>
                      )}
                      {event.value.origin === 'photo' && (
                        <span className="pill" style={{ marginLeft: 6 }}>
                          {t.trips.photoOnly}
                        </span>
                      )}
                    </>
                  ) : (
                    <>
                      {t.modes[event.value.mode]}
                      {event.value.mode_confidence !== null && event.value.mode_confidence < 0.6 && ' ?'}
                      {event.value.geom_quality === 'endpoints_only' && (
                        <span className="pill" style={{ marginLeft: 6 }}>
                          {t.detail.endpointsOnly}
                        </span>
                      )}
                    </>
                  )}
                </td>
                <td>
                  {event.kind === 'place'
                    ? duration(event.value.duration_s)
                    : duration(event.value.duration_s)}
                </td>
                <td>
                  {event.kind === 'track'
                    ? event.value.distance_unknown || event.value.distance_m === null
                      ? // Never rendered as 0 km: unknown is a different fact.
                        t.detail.distanceUnknown
                      : `${(event.value.distance_m / 1000).toFixed(1)} km`
                    : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {photos.length > 0 && (
        <>
          <h2 style={{ marginTop: 20 }}>{t.trips.photos(photos.length)}</h2>
          <div className="photo-grid">
            {photos.map((photo) => (
              <img
                key={photo.id}
                src={api.thumbUrl(photo.id)}
                alt={photo.orig_filename ?? ''}
                loading="lazy"
                className={photo.location_confidence === 'inferred' ? 'inferred' : undefined}
              />
            ))}
          </div>
        </>
      )}

      <ExportPanel />
    </div>
  )
}
