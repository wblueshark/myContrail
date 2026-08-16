import { useState } from 'react'

import { useGeofences, useGroups, useSearch, useTags } from '@/api/hooks'
import type { SourceKind, TravelMode } from '@/api/types'
import { t } from '@/i18n/zh'
import { ALL_MODES, ALL_SOURCES, useAppStore } from '@/store/appStore'

const MODE_COLOR: Record<TravelMode, string> = {
  walk: 'var(--mode-walk)',
  run: 'var(--mode-run)',
  bike: 'var(--mode-bike)',
  car: 'var(--mode-car)',
  transit: 'var(--mode-transit)',
  flight: 'var(--mode-flight)',
  unknown: 'var(--mode-unknown)',
}

const MODE_GLYPH: Record<TravelMode, string> = {
  walk: '🚶',
  run: '🏃',
  bike: '🚴',
  car: '🚗',
  transit: '🚆',
  flight: '✈️',
  unknown: '❓',
}

function thisYearRange(): [string, string] {
  const year = new Date().getUTCFullYear()
  return [`${year}-01-01T00:00:00Z`, `${year}-12-31T23:59:59Z`]
}

export default function FilterPanel() {
  const store = useAppStore()
  const groups = useGroups()
  const tags = useTags()
  const fences = useGeofences()
  const [term, setTerm] = useState('')
  const search = useSearch(term)

  const preset = store.timeFrom === null ? 'all' : 'custom'

  return (
    <div>
      <div className="section">
        <input
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder={t.filters.search}
        />
        {search.data && term.trim() !== '' && (
          <div className="stack" style={{ marginTop: 8 }}>
            {search.data.trips.slice(0, 5).map((trip) => (
              <button
                key={trip.id}
                className="ghost"
                style={{ textAlign: 'left' }}
                onClick={() => store.navigate({ name: 'trip', id: trip.id })}
              >
                🧳 {trip.title}
              </button>
            ))}
            {search.data.places.slice(0, 5).map((place) => (
              <button
                key={place.id}
                className="ghost"
                style={{ textAlign: 'left' }}
                onClick={() => store.select({ kind: 'place', id: place.id })}
              >
                📍 {place.label ?? place.city ?? t.app.unknown}
              </button>
            ))}
            {!search.data.trips.length && !search.data.places.length && (
              <span className="faint">{t.app.empty}</span>
            )}
          </div>
        )}
      </div>

      <div className="section">
        <div className="section__title">{t.filters.time}</div>
        <div className="row row--wrap">
          <button
            className={preset === 'all' ? 'primary' : ''}
            onClick={() => store.setTimeRange(null, null)}
          >
            {t.filters.timeAll}
          </button>
          <button onClick={() => store.setTimeRange(...thisYearRange())}>
            {t.filters.timeThisYear}
          </button>
        </div>
        <div className="grid-2" style={{ marginTop: 8 }}>
          <input
            type="date"
            value={store.timeFrom ? store.timeFrom.slice(0, 10) : ''}
            onChange={(event) =>
              store.setTimeRange(
                event.target.value ? `${event.target.value}T00:00:00Z` : null,
                store.timeTo,
              )
            }
          />
          <input
            type="date"
            value={store.timeTo ? store.timeTo.slice(0, 10) : ''}
            onChange={(event) =>
              store.setTimeRange(
                store.timeFrom,
                event.target.value ? `${event.target.value}T23:59:59Z` : null,
              )
            }
          />
        </div>
      </div>

      <div className="section">
        <div className="section__title">{t.filters.layers}</div>
        {(
          [
            ['tracks', t.filters.layerTracks],
            ['places', t.filters.layerPlaces],
            ['photos', t.filters.layerPhotos],
            ['heatmap', t.filters.layerHeatmap],
          ] as const
        ).map(([key, label]) => (
          <label className="check" key={key}>
            <input
              type="checkbox"
              checked={store.layers[key]}
              onChange={() => store.toggleLayer(key)}
            />
            {label}
          </label>
        ))}
      </div>

      <div className="section">
        <div className="section__title">{t.filters.modes}</div>
        {ALL_MODES.map((mode) => (
          <label className="check" key={mode}>
            <input
              type="checkbox"
              checked={store.modes.has(mode)}
              onChange={() => store.toggleMode(mode)}
            />
            <span className="swatch" style={{ background: MODE_COLOR[mode] }} />
            <span aria-hidden>{MODE_GLYPH[mode]}</span>
            {t.modes[mode]}
          </label>
        ))}
      </div>

      <div className="section">
        <div className="section__title">{t.filters.sources}</div>
        {ALL_SOURCES.map((source: SourceKind) => (
          <label className="check" key={source}>
            <input
              type="checkbox"
              checked={store.sources.has(source)}
              onChange={() => store.toggleSource(source)}
            />
            {t.sourceKinds[source]}
          </label>
        ))}
      </div>

      <div className="section">
        <div className="section__title">{t.filters.groups}</div>
        <select
          value={store.groupFilter ?? ''}
          onChange={(event) => store.setGroupFilter(event.target.value || null)}
        >
          <option value="">{t.filters.timeAll}</option>
          {(groups.data ?? []).map((group) => (
            <option key={group.id} value={group.id}>
              {group.name} ({group.trip_count})
            </option>
          ))}
        </select>
      </div>

      <div className="section">
        <div className="section__title">{t.filters.tags}</div>
        <select
          value={store.tagFilter ?? ''}
          onChange={(event) => store.setTagFilter(event.target.value || null)}
        >
          <option value="">{t.filters.timeAll}</option>
          {(tags.data ?? []).map((tag) => (
            <option key={tag.id} value={tag.id}>
              {tag.name}
            </option>
          ))}
        </select>
      </div>

      <div className="section">
        <div className="pill">
          🔒{' '}
          {fences.data && fences.data.length
            ? t.filters.fenceNotice(fences.data.filter((f) => f.enabled).length)
            : t.filters.fenceNone}
        </div>
      </div>

      <button className="ghost" onClick={store.resetFilters}>
        {t.filters.reset}
      </button>
    </div>
  )
}
