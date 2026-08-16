/**
 * One trip (= one day), on its own route so refresh and deep links work.
 *
 * The map preview fits itself to the trip's own bounding box - a fixed viewBox
 * looks right on the sample data and puts every other trip off-screen. Aspect
 * is forced to 3:2 with 9% padding so a single-place day does not blow up to
 * infinite zoom.
 */

import { useMemo } from 'react'

import { api } from '@/api/client'
import { useGroups, useTags, useTrip } from '@/api/hooks'
import Blueprint from '@/components/Blueprint'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

const MODE_VARS: Record<string, string> = {
  walk: 'var(--mode-walk)',
  run: 'var(--mode-run)',
  bike: 'var(--mode-bike)',
  car: 'var(--mode-car)',
  transit: 'var(--mode-transit)',
  flight: 'var(--mode-flight)',
  unknown: 'var(--mode-unknown)',
}

const ASPECT = 1.5
const PAD = 0.09
const MIN_SPAN = 0.004 // ~450 m: the floor for a single-place day

interface Geometry {
  viewBox: string
  places: Array<{ x: number; y: number; label: string | null }>
}

export default function TripDetailPage({ tripId }: { tripId: string }) {
  const t = useCopy()
  const navigate = useAppStore((state) => state.navigate)
  const setTimeRange = useAppStore((state) => state.setTimeRange)
  const setExportTrips = useAppStore((state) => state.setExportTrips)
  const setExportOpen = useAppStore((state) => state.setExportOpen)
  const detail = useTrip(tripId)
  const groups = useGroups()
  const tags = useTags()

  const geometry: Geometry | null = useMemo(() => {
    const places = detail.data?.places ?? []
    if (!places.length) return null
    const lons = places.map((place) => place.lon)
    const lats = places.map((place) => place.lat)
    let minLon = Math.min(...lons)
    let minLat = Math.min(...lats)
    let width = Math.max(MIN_SPAN, Math.max(...lons) - minLon)
    let height = Math.max(MIN_SPAN / ASPECT, Math.max(...lats) - minLat)

    if (width / height < ASPECT) {
      const grown = height * ASPECT
      minLon -= (grown - width) / 2
      width = grown
    } else {
      const grown = width / ASPECT
      minLat -= (grown - height) / 2
      height = grown
    }
    const padX = width * PAD
    const padY = height * PAD

    return {
      viewBox: `${minLon - padX} ${-(minLat + height + padY)} ${width + padX * 2} ${height + padY * 2}`,
      places: places.map((place) => ({ x: place.lon, y: -place.lat, label: place.name ?? place.geo_name })),
    }
  }, [detail.data])

  if (!detail.data) return <div className="page page--scroll muted">{t.app.loading}</div>

  const { trip, tracks, photos } = detail.data
  const group = groups.data?.find((row) => row.id === trip.group_id)
  const tagNames = (trip.tag_ids ?? [])
    .map((id) => tags.data?.find((row) => row.id === id)?.name)
    .filter((name): name is string => Boolean(name))

  return (
    <div className="page page--scroll">
      <button
        className="btn btn-ghost btn-sm"
        style={{ marginBottom: 12 }}
        onClick={() => navigate({ name: 'trips' })}
      >
        ← {t.trips.backToList}
      </button>

      <div className="page__title" style={{ marginBottom: 14 }}>
        <h1 style={{ fontSize: 36 }}>{trip.title}</h1>
        <span className="num muted" style={{ fontSize: 13, paddingBottom: 5 }}>
          {trip.local_date}
        </span>
        {group && <span className="tag tag-accent">{group.name}</span>}
        {tagNames.map((name) => (
          <span key={name} className="tag tag-outline">
            {name}
          </span>
        ))}
        <div className="row" style={{ marginLeft: 'auto', gap: 6 }}>
          <button
            className="btn btn-secondary"
            onClick={() => {
              setTimeRange(`${trip.local_date}T00:00:00Z`, `${trip.local_date}T23:59:59Z`)
              navigate({ name: 'map' })
            }}
          >
            {t.trips.map}
          </button>
          <button
            className="btn btn-primary"
            onClick={() => {
              setExportTrips([trip.id])
              setExportOpen(true)
            }}
          >
            {t.trips.export} PNG
          </button>
          {/* Sharing is out of the MVP (02 section 9): offered, visibly off. */}
          <button className="btn btn-secondary" disabled title={t.app.notInMvp}>
            {t.trips.share}
          </button>
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gap: 16,
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
        }}
      >
        <Blueprint style={{ height: 380, background: 'var(--color-surface)', overflow: 'hidden' }}>
          {geometry ? (
            <svg viewBox={geometry.viewBox} preserveAspectRatio="xMidYMid slice" width="100%" height="100%">
              {tracks.map((track) => (
                <circle
                  key={track.id}
                  r={0}
                  fill="none"
                  stroke={MODE_VARS[track.mode] ?? MODE_VARS.unknown}
                />
              ))}
              {geometry.places.map((place, index) => (
                <g key={index}>
                  <circle
                    cx={place.x}
                    cy={place.y}
                    r={geometryRadius(geometry.viewBox)}
                    fill="var(--color-bg)"
                    stroke="var(--color-danger)"
                    strokeWidth={geometryRadius(geometry.viewBox) / 3}
                  />
                </g>
              ))}
            </svg>
          ) : (
            <div
              className="muted"
              style={{ display: 'grid', placeItems: 'center', height: '100%', fontSize: 13 }}
            >
              {t.trips.noGeometry}
            </div>
          )}
        </Blueprint>

        <div>
          <div className="kicker" style={{ marginBottom: 8 }}>
            {t.trips.stats}
          </div>
          <div className="plate plate--2" style={{ marginBottom: 16 }}>
            <div className="plate__cell">
              <div className="plate__value">
                {((trip.stats.distance_total_m ?? 0) / 1000).toFixed(1)} km
              </div>
              <div className="plate__label">{t.stats.distance}</div>
            </div>
            <div className="plate__cell">
              <div className="plate__value">{trip.stats.photo_count ?? 0}</div>
              <div className="plate__label">{t.map.photos}</div>
            </div>
            <div className="plate__cell">
              <div className="plate__value">{trip.stats.place_count ?? 0}</div>
              <div className="plate__label">{t.map.places}</div>
            </div>
            <div className="plate__cell">
              <div className="plate__value">{trip.stats.track_count ?? 0}</div>
              <div className="plate__label">{t.layers.tracks}</div>
            </div>
          </div>

          <div className="kicker" style={{ marginBottom: 8 }}>
            {t.map.photos}
          </div>
          <div className="photo-grid">
            {photos.slice(0, 12).map((photo) => (
              <img key={photo.id} src={api.thumbUrl(photo.id)} alt="" loading="lazy" />
            ))}
          </div>
        </div>
      </div>

      <p className="faint" style={{ marginTop: 18, maxWidth: 640, fontSize: 12 }}>
        {t.trips.editableNotice}
      </p>
    </div>
  )
}

/** Marker radius in viewBox units, so dots stay the same visual size. */
function geometryRadius(viewBox: string): number {
  const width = Number(viewBox.split(' ')[2] ?? 1)
  return width / 90
}
