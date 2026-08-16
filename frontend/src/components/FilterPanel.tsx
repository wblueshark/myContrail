/**
 * Map filter panel: search, time window, layers, transport modes, sources.
 *
 * Everything here writes to the store, and the map reads the store as Mapbox
 * filter expressions - no filter in this panel issues a request.
 *
 * Two rules the copy has to hold to:
 *   * the fence card says "applied on export". The in-app map deliberately
 *     shows real data (02 section 2); claiming otherwise would be a lie the
 *     user might rely on.
 *   * a mode whose distance is partly unknown is marked, never rounded down
 *     into a total that looks measured.
 */

import { Lock, Search } from 'lucide-react'
import { useState } from 'react'

import { useGeofences, useSearch, useStats } from '@/api/hooks'
import type { SourceKind, TravelMode } from '@/api/types'
import Blueprint from '@/components/Blueprint'
import { useCopy } from '@/i18n'
import { ALL_MODES, ALL_SOURCES, useAppStore } from '@/store/appStore'

const MODE_VARS: Record<TravelMode, string> = {
  walk: 'var(--mode-walk)',
  run: 'var(--mode-run)',
  bike: 'var(--mode-bike)',
  car: 'var(--mode-car)',
  transit: 'var(--mode-transit)',
  flight: 'var(--mode-flight)',
  unknown: 'var(--mode-unknown)',
}

function startOfYear(): string {
  return new Date(Date.UTC(new Date().getUTCFullYear(), 0, 1)).toISOString()
}

function monthsAgo(months: number): string {
  const now = new Date()
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - months, 1)).toISOString()
}

function km(meters: number): string {
  return meters >= 1000 ? `${Math.round(meters / 1000).toLocaleString()} km` : `${Math.round(meters)} m`
}

export default function FilterPanel() {
  const t = useCopy()
  const [customOpen, setCustomOpen] = useState(false)

  const timeFrom = useAppStore((state) => state.timeFrom)
  const timeTo = useAppStore((state) => state.timeTo)
  const setTimeRange = useAppStore((state) => state.setTimeRange)
  const layers = useAppStore((state) => state.layers)
  const toggleLayer = useAppStore((state) => state.toggleLayer)
  const modes = useAppStore((state) => state.modes)
  const toggleMode = useAppStore((state) => state.toggleMode)
  const sources = useAppStore((state) => state.sources)
  const toggleSource = useAppStore((state) => state.toggleSource)
  const searchTerm = useAppStore((state) => state.searchTerm)
  const setSearchTerm = useAppStore((state) => state.setSearchTerm)
  const select = useAppStore((state) => state.select)
  const navigate = useAppStore((state) => state.navigate)
  const setSettingsOpen = useAppStore((state) => state.setSettingsOpen)

  const windowStats = useStats({ from: timeFrom ?? undefined, to: timeTo ?? undefined })
  const fences = useGeofences()
  const results = useSearch(searchTerm)

  const byMode = new Map((windowStats.data?.distance_by_mode ?? []).map((row) => [row.mode, row]))
  const tracksInWindow = (windowStats.data?.distance_by_mode ?? []).reduce(
    (sum, row) => sum + row.segments,
    0,
  )
  const isAll = !timeFrom && !timeTo
  const enabledFences = (fences.data ?? []).filter((fence) => fence.enabled).length

  return (
    <>
      <div className="map__search">
        <Search
          size={15}
          strokeWidth={1.5}
          style={{ position: 'absolute', left: 22, top: 21, opacity: 0.5 }}
        />
        <input
          className="input"
          style={{ paddingLeft: 28 }}
          placeholder={t.filters.search}
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
        />
        {searchTerm.trim().length > 0 && (
          <div className="search-results">
            {results.data?.places.length === 0 && results.data.trips.length === 0 && (
              <div className="search-results__item muted">{t.map.searchEmpty}</div>
            )}
            {(results.data?.places ?? []).length > 0 && (
              <div className="kicker" style={{ padding: '6px 10px' }}>
                {t.map.searchPlaces}
              </div>
            )}
            {(results.data?.places ?? []).slice(0, 8).map((place) => (
              <button
                key={place.id}
                className="search-results__item"
                onClick={() => {
                  select({ kind: 'place', id: place.id })
                  setSearchTerm('')
                }}
              >
                {place.label ?? t.overview.unnamed}
                <span className="faint"> · {place.city ?? place.country ?? ''}</span>
              </button>
            ))}
            {(results.data?.trips ?? []).length > 0 && (
              <div className="kicker" style={{ padding: '6px 10px' }}>
                {t.map.searchTrips}
              </div>
            )}
            {(results.data?.trips ?? []).slice(0, 8).map((trip) => (
              <button
                key={trip.id}
                className="search-results__item"
                onClick={() => {
                  navigate({ name: 'trip', id: trip.id })
                  setSearchTerm('')
                }}
              >
                {trip.title}
                <span className="faint"> · {trip.local_date}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="map__filters-body">
        <div className="kicker" style={{ padding: '14px 0 10px' }}>
          {t.filters.time}
        </div>
        <div className="seg seg--block">
          <label className="seg-opt">
            <input type="radio" name="tp" checked={isAll} onChange={() => setTimeRange(null, null)} />
            {t.filters.timeAll}
          </label>
          <label className="seg-opt">
            <input
              type="radio"
              name="tp"
              checked={timeFrom === startOfYear() && !timeTo}
              onChange={() => setTimeRange(startOfYear(), null)}
            />
            {t.filters.timeThisYear}
          </label>
          <label className="seg-opt">
            <input
              type="radio"
              name="tp"
              checked={timeFrom === monthsAgo(6) && !timeTo}
              onChange={() => setTimeRange(monthsAgo(6), null)}
            />
            {t.filters.timeLast6m}
          </label>
        </div>

        {/* The third granularity from 02 section 7: an exact range, typed. The
            segments and the histogram cover exploring; this covers "May 2024". */}
        {customOpen ? (
          <div className="row" style={{ marginTop: 8, gap: 6 }}>
            <input
              className="input"
              type="date"
              value={timeFrom ? timeFrom.slice(0, 10) : ''}
              onChange={(event) =>
                setTimeRange(event.target.value ? `${event.target.value}T00:00:00Z` : null, timeTo)
              }
            />
            <input
              className="input"
              type="date"
              value={timeTo ? timeTo.slice(0, 10) : ''}
              onChange={(event) =>
                setTimeRange(timeFrom, event.target.value ? `${event.target.value}T23:59:59Z` : null)
              }
            />
          </div>
        ) : (
          <button
            className="btn btn-ghost btn-sm"
            style={{ marginTop: 8 }}
            onClick={() => setCustomOpen(true)}
          >
            <span className="num">
              {timeFrom ? timeFrom.slice(0, 10) : t.filters.timeAll} —{' '}
              {timeTo ? timeTo.slice(0, 10) : t.filters.timeAll}
            </span>
          </button>
        )}

        <div className="kicker" style={{ padding: '18px 0 10px' }}>
          {t.filters.layers}
        </div>
        {(
          [
            ['tracks', t.layers.tracks, tracksInWindow],
            ['places', t.layers.places, windowStats.data?.place_count ?? 0],
            ['photos', t.layers.photos, windowStats.data?.photos.total ?? 0],
          ] as const
        ).map(([key, label, count]) => (
          <label key={key} className="check">
            <input type="checkbox" checked={layers[key]} onChange={() => toggleLayer(key)} />
            <span>{label}</span>
            <span className="num faint" style={{ marginLeft: 'auto', fontSize: 11 }}>
              {count.toLocaleString()}
            </span>
          </label>
        ))}

        <div className="kicker" style={{ padding: '18px 0 10px' }}>
          {t.filters.modes}
        </div>
        {ALL_MODES.filter((mode) => mode !== 'unknown').map((mode) => {
          const row = byMode.get(mode)
          const unknown = row?.unknown_distance_segments ?? 0
          return (
            <label key={mode} className="check">
              <input
                type="checkbox"
                checked={modes.has(mode)}
                onChange={() => toggleMode(mode)}
              />
              <svg width="20" height="8" style={{ flex: 'none' }}>
                <line x1="0" y1="4" x2="20" y2="4" stroke={MODE_VARS[mode]} strokeWidth="2.5" />
              </svg>
              <span>{t.modes[mode]}</span>
              <span className="num faint" style={{ marginLeft: 'auto', fontSize: 11 }}>
                {row && row.distance_m > 0 ? km(row.distance_m) : t.app.dash}
                {/* Segments with no distance are flagged, never folded in as 0. */}
                {unknown > 0 && <sup title={t.detail.distanceUnknown}> +{unknown}</sup>}
              </span>
            </label>
          )
        })}

        <div className="kicker" style={{ padding: '18px 0 10px' }}>
          {t.filters.sources}
        </div>
        {(['photo', 'google_timeline', 'gpx', 'manual'] as SourceKind[]).map((source) => (
          <label key={source} className="check">
            <input
              type="checkbox"
              checked={sources.has(source)}
              onChange={() => toggleSource(source)}
            />
            <span>{t.sourceKinds[source]}</span>
          </label>
        ))}

        <Blueprint style={{ marginTop: 20, padding: '10px 11px' }}>
          <div className="row" style={{ gap: 7, fontSize: 12 }}>
            <Lock size={13} strokeWidth={1.5} />
            <span style={{ fontFamily: 'var(--font-heading)', letterSpacing: '.06em' }}>
              {t.map.fenceTitle}
            </span>
          </div>
          <div className="muted" style={{ fontSize: 11, lineHeight: 1.5, marginTop: 4 }}>
            {t.map.fenceSide(enabledFences)}
          </div>
          <button
            className="btn btn-ghost btn-sm"
            style={{ alignSelf: 'flex-start', marginTop: 4 }}
            onClick={() => setSettingsOpen(true)}
          >
            {t.app.manage} →
          </button>
        </Blueprint>
      </div>
    </>
  )
}

export { ALL_SOURCES }
