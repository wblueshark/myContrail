/**
 * Detail panel for the selected map object.
 *
 * Quality signals are shown, not hidden: an inferred dwell says how much of it
 * was deduced, an endpoints-only track says its line is a placeholder, an
 * unknown distance says "unknown" instead of showing 0 km, and a low-confidence
 * mode is marked. A guess that looks like a measurement is worse than no answer.
 */

import { api } from '@/api/client'
import { usePhotos, usePlaces, useTracks } from '@/api/hooks'
import type { Place, Track } from '@/api/types'
import { t } from '@/i18n/zh'
import { useAppStore } from '@/store/appStore'

function formatDuration(seconds: number): string {
  if (seconds <= 0) return '—'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.round((seconds % 3600) / 60)
  return hours ? `${hours}h${minutes.toString().padStart(2, '0')}m` : `${minutes}m`
}

function formatDistance(meters: number | null, unknown: boolean): string {
  if (unknown || meters === null) return t.detail.distanceUnknown
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`
}

function localTime(iso: string, tz: string | null): string {
  const date = new Date(iso)
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      dateStyle: 'short',
      timeStyle: 'short',
      timeZone: tz ?? 'UTC',
      timeZoneName: 'short',
    }).format(date)
  } catch {
    return date.toISOString().slice(0, 16).replace('T', ' ')
  }
}

function PlaceDetail({ place }: { place: Place }) {
  const navigate = useAppStore((state) => state.navigate)
  const photos = usePhotos({ place_id: place.id, limit: 60 })

  return (
    <>
      <h2>{place.name ?? place.geo_name ?? place.geo_city ?? t.detail.place}</h2>
      <p className="faint">
        {localTime(place.start_utc, place.tz_name)} → {localTime(place.end_utc, place.tz_name)}
      </p>

      <div className="row row--wrap" style={{ marginBottom: 10 }}>
        <span className="pill">
          {t.detail.duration} {formatDuration(place.duration_s)}
        </span>
        {place.origin === 'photo' && <span className="pill pill--warn">{t.trips.photoOnly}</span>}
      </div>

      {/* P4: a dwell partly deduced from a data gap must never look measured. */}
      {place.is_inferred_dwell && (
        <div className="notice notice--warn">
          {t.detail.inferredDwell(Math.round(place.inferred_ratio * 100))}
        </div>
      )}

      <div className="section">
        <div className="section__title">{t.detail.dataSource}</div>
        <div className="row row--wrap">
          {place.source_kinds.map((kind) => (
            <span className="pill" key={kind}>
              {t.sourceKinds[kind]}
            </span>
          ))}
          <span className="faint">{place.point_count} pts</span>
        </div>
      </div>

      {photos.data && photos.data.length > 0 && (
        <div className="section">
          <div className="section__title">{t.detail.photoCount(photos.data.length)}</div>
          <div className="photo-grid">
            {photos.data.slice(0, 9).map((photo) => (
              <img
                key={photo.id}
                src={api.thumbUrl(photo.id)}
                alt={photo.orig_filename ?? ''}
                loading="lazy"
                className={photo.location_confidence === 'inferred' ? 'inferred' : undefined}
              />
            ))}
          </div>
        </div>
      )}

      {place.trip_id && (
        <button onClick={() => navigate({ name: 'trip', id: place.trip_id! })}>
          {t.detail.openTrip} →
        </button>
      )}
    </>
  )
}

function TrackDetail({ track }: { track: Track }) {
  const navigate = useAppStore((state) => state.navigate)
  const uncertain = track.mode_confidence !== null && track.mode_confidence < 0.6

  return (
    <>
      <h2>
        {t.modes[track.mode]}
        {uncertain && ' ?'}
      </h2>
      <p className="faint">
        {localTime(track.start_utc, null)} → {localTime(track.end_utc, null)}
      </p>

      <div className="row row--wrap" style={{ marginBottom: 10 }}>
        <span className={track.distance_unknown ? 'pill pill--warn' : 'pill'}>
          {formatDistance(track.distance_m, track.distance_unknown)}
        </span>
        <span className="pill">{formatDuration(track.duration_s)}</span>
        {track.is_commute && <span className="pill">🚇</span>}
        {track.crosses_tz && <span className="pill pill--warn">{t.detail.crossesTz}</span>}
      </div>

      {uncertain && <div className="notice notice--warn">{t.detail.modeUncertain}</div>}
      {/* Semantic-era segments carry only endpoints; the line is a placeholder. */}
      {track.geom_quality === 'endpoints_only' && (
        <div className="notice">{t.detail.endpointsOnly}</div>
      )}

      <div className="section">
        <div className="section__title">{t.detail.dataSource}</div>
        <span className="pill">{t.sourceKinds[track.source_kind]}</span>
      </div>

      {track.trip_id && (
        <button onClick={() => navigate({ name: 'trip', id: track.trip_id! })}>
          {t.detail.openTrip} →
        </button>
      )}
    </>
  )
}

export default function DetailDrawer() {
  const selection = useAppStore((state) => state.selection)
  const select = useAppStore((state) => state.select)

  const places = usePlaces({ limit: 2000 })
  const tracks = useTracks({ limit: 2000 })
  const photos = usePhotos({ limit: 2000 }, selection?.kind === 'photo')

  if (!selection) return null

  const place =
    selection.kind === 'place' ? places.data?.find((p) => p.id === selection.id) : undefined
  const track =
    selection.kind === 'track' ? tracks.data?.find((tr) => tr.id === selection.id) : undefined
  const photo =
    selection.kind === 'photo' ? photos.data?.find((p) => p.id === selection.id) : undefined

  return (
    <aside className="map-layout__drawer">
      <div className="row row--between" style={{ marginBottom: 10 }}>
        <span className="faint">{t.detail[selection.kind === 'track' ? 'track' : 'place']}</span>
        <button className="ghost" onClick={() => select(null)}>
          ✕
        </button>
      </div>

      {place && <PlaceDetail place={place} />}
      {track && <TrackDetail track={track} />}
      {photo && (
        <>
          <img
            src={api.thumbUrl(photo.id)}
            alt={photo.orig_filename ?? ''}
            style={{ width: '100%', borderRadius: 8 }}
            className={photo.location_confidence === 'inferred' ? 'inferred' : undefined}
          />
          <p className="faint">{photo.orig_filename}</p>
          {photo.taken_at_local && (
            <p>
              {photo.taken_at_local.replace('T', ' ').slice(0, 16)}
              {/* tz_source of nearest_track or user_default means the time is a
                  guess, so it is marked rather than presented as exact. */}
              {photo.tz_source && ['nearest_track', 'user_default'].includes(photo.tz_source)
                ? ' ?'
                : ''}
            </p>
          )}
          {photo.location_confidence === 'inferred' && (
            <div className="notice notice--warn">{t.detail.inferredLocation}</div>
          )}
        </>
      )}

      {!place && !track && !photo && <p className="faint">{t.app.loading}</p>}
    </aside>
  )
}
