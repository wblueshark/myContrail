/**
 * Right-hand detail panel for the selected track or place.
 *
 * Two honesty rules the panel exists to keep:
 *   * rename / merge are DISABLED, not hidden-then-broken. Content correction
 *     returns 501 by design, and the product's rule is that no button may be
 *     offered that cannot work (01 section 6).
 *   * the photo grid is 512 px thumbnails and says so. After an import the
 *     original folder is never read again, so "view original" cannot exist.
 */

import { X } from 'lucide-react'

import { api } from '@/api/client'
import { usePhotos, usePlaces, useTracks, useTrips } from '@/api/hooks'
import type { Place, Track } from '@/api/types'
import Blueprint from '@/components/Blueprint'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

function duration(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.round((seconds % 3600) / 60)
  return hours ? `${hours}h${String(minutes).padStart(2, '0')}m` : `${minutes}m`
}

function clock(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16)
}

export default function DetailDrawer() {
  const t = useCopy()
  const selection = useAppStore((state) => state.selection)
  const select = useAppStore((state) => state.select)
  const navigate = useAppStore((state) => state.navigate)
  const setExportTrips = useAppStore((state) => state.setExportTrips)
  const setExportOpen = useAppStore((state) => state.setExportOpen)

  const isPlace = selection?.kind === 'place'
  const places = usePlaces({ limit: 500 })
  const tracks = useTracks({ limit: 500 })
  const trips = useTrips({ limit: 500 })

  const place: Place | undefined = isPlace
    ? places.data?.find((row) => row.id === selection.id)
    : undefined
  const track: Track | undefined =
    selection?.kind === 'track' ? tracks.data?.find((row) => row.id === selection.id) : undefined

  const tripId = place?.trip_id ?? track?.trip_id ?? null
  const trip = trips.data?.find((row) => row.id === tripId)
  const photos = usePhotos({ place_id: place?.id, limit: 12 }, Boolean(place?.photo_count))

  if (!selection || (!place && !track)) {
    return (
      <aside className="map__detail">
        <div className="detail__pad muted" style={{ padding: '40px 20px', textAlign: 'center' }}>
          {t.map.pickHint}
        </div>
      </aside>
    )
  }

  const title = place
    ? (place.name ?? place.geo_name ?? place.geo_city ?? t.overview.unnamed)
    : `${t.modes[track!.mode]} · ${
        track!.distance_unknown || track!.distance_m === null
          ? t.detail.distanceUnknown
          : `${(track!.distance_m / 1000).toFixed(1)} km`
      }`

  const subtitle = place
    ? `${place.start_utc.slice(0, 10)} · ${clock(place.start_utc)} – ${clock(place.end_utc)}`
    : `${track!.start_utc.slice(0, 10)} · ${clock(track!.start_utc)} – ${clock(track!.end_utc)}`

  const stats: Array<[string, string]> = place
    ? [
        [t.detail.date, place.start_utc.slice(0, 10)],
        [t.detail.window, `${clock(place.start_utc)} – ${clock(place.end_utc)}`],
        [t.detail.stay, duration(place.duration_s)],
        [t.detail.photos, String(place.photo_count)],
      ]
    : [
        [t.detail.date, track!.start_utc.slice(0, 10)],
        [
          t.detail.distance,
          track!.distance_m === null ? t.detail.distanceUnknown : `${(track!.distance_m / 1000).toFixed(1)} km`,
        ],
        [t.detail.duration, duration(track!.duration_s)],
        [t.detail.mode, t.modes[track!.mode]],
      ]

  return (
    <aside className="map__detail">
      <div className="detail__pad">
        <div className="row" style={{ alignItems: 'flex-start' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: 'var(--font-heading)', fontSize: 21, lineHeight: 1.15 }}>
              {title}
            </div>
            <div className="muted" style={{ fontSize: 11.5 }}>
              {subtitle}
            </div>
          </div>
          <button className="btn btn-ghost btn-icon" onClick={() => select(null)}>
            <X size={14} strokeWidth={1.5} />
          </button>
        </div>

        <hr className="hr" />

        {stats.map(([key, value]) => (
          <div key={key} className="detail__stat">
            <span className="muted">{key}</span>
            <span className="num">{value}</span>
          </div>
        ))}

        {place?.is_inferred_dwell && (
          <div className="notice notice--accent" style={{ marginTop: 10 }}>
            {t.detail.inferredDwell(Math.round(place.inferred_ratio * 100))}
          </div>
        )}
        {track?.geom_quality === 'endpoints_only' && (
          <div className="notice" style={{ marginTop: 10 }}>
            {t.detail.endpointsOnly}
          </div>
        )}

        {place && place.photo_count > 0 && (
          <div style={{ marginTop: 14 }}>
            <div className="row" style={{ marginBottom: 7 }}>
              <span className="kicker">{t.detail.photos}</span>
              <span className="num" style={{ fontSize: 12 }}>
                {place.photo_count}
              </span>
            </div>
            <div className="photo-grid">
              {(photos.data ?? []).slice(0, 9).map((photo) => (
                <img key={photo.id} src={api.thumbUrl(photo.id)} alt="" loading="lazy" />
              ))}
            </div>
            <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>
              {t.detail.thumbnailOnly}
            </div>
          </div>
        )}

        <hr className="hr" />
        <div className="kicker" style={{ marginBottom: 6 }}>
          {t.detail.dataSource}
        </div>
        {(place?.source_kinds ?? [track!.source_kind]).map((kind) => (
          <div key={kind} className="row" style={{ fontSize: 12.5, padding: '2px 0' }}>
            <span
              style={{ width: 4, height: 4, background: 'var(--color-accent)', flex: 'none' }}
            />
            {t.sourceKinds[kind]}
          </div>
        ))}

        {trip && (
          <>
            <hr className="hr" />
            <div className="kicker" style={{ marginBottom: 6 }}>
              {t.detail.belongsTo}
            </div>
            <Blueprint style={{ padding: '9px 10px' }}>
              <div className="row">
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13 }}>{trip.title}</div>
                  <div className="muted" style={{ fontSize: 11 }}>
                    {trip.local_date}
                  </div>
                </div>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => navigate({ name: 'trip', id: trip.id })}
                >
                  {t.app.open} →
                </button>
              </div>
            </Blueprint>
          </>
        )}

        <div className="row" style={{ marginTop: 14, gap: 6 }}>
          {/* PUT /places/{id} and POST /trips/merge answer 501 in the MVP. */}
          <button className="btn btn-secondary btn-sm" style={{ flex: 1 }} disabled title={t.detail.editNotInMvp}>
            {t.app.rename}
          </button>
          <button className="btn btn-secondary btn-sm" style={{ flex: 1 }} disabled title={t.detail.editNotInMvp}>
            {t.app.merge}
          </button>
          <button
            className="btn btn-secondary btn-sm"
            disabled={!tripId}
            title={t.map.exportPng}
            onClick={() => {
              if (!tripId) return
              setExportTrips([tripId])
              setExportOpen(true)
            }}
          >
            ↑
          </button>
        </div>
      </div>
    </aside>
  )
}
