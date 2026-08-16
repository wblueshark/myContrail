/**
 * "Where you have been": countries, cities, places - each drilling into trips.
 *
 * Full-corpus figures, deliberately not windowed: these are the same numbers
 * the map's metric strip shows, and the page says so. The map draws the current
 * window; this page counts everything imported.
 *
 * There is no place CATEGORY dimension. The data contract has no field that
 * could produce one, and inventing categories in the frontend would be making
 * up facts about the user's own history (CR-007, decision Q-CR7-1).
 */

import { useAnchors, useOverviewCities, useOverviewCountries, useTrips } from '@/api/hooks'
import type { OverviewRow } from '@/api/types'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

function km(meters: number): string {
  return `${Math.round(meters / 1000).toLocaleString()} km`
}

function span(from: string | null, to: string | null): string {
  if (!from || !to) return '—'
  return `${from.slice(0, 7)} → ${to.slice(0, 7)}`
}

export default function OverviewPage() {
  const t = useCopy()
  const focus = useAppStore((state) => state.overview)
  const setOverview = useAppStore((state) => state.setOverview)
  const navigate = useAppStore((state) => state.navigate)
  const setSettingsOpen = useAppStore((state) => state.setSettingsOpen)

  const countries = useOverviewCountries()
  const cities = useOverviewCities(focus.dimension === 'country' ? focus.country : null)
  const anchors = useAnchors({ sort: 'visits', limit: 200 })

  const drilled = Boolean(focus.country || focus.city || focus.anchor)
  const trips = useTrips(
    drilled
      ? {
          country: focus.country ?? undefined,
          city: focus.city ?? undefined,
          anchor: focus.anchor ?? undefined,
          limit: 200,
        }
      : { limit: 0 },
  )

  const totalCountries = countries.data?.filter((row) => row.key).length ?? 0
  const totalCities = cities.data?.filter((row) => row.key).length ?? 0
  const totalPlaces = anchors.data?.length ?? 0

  const geocodingOff = countries.isSuccess && totalCountries === 0

  const dimensions = [
    { id: 'country' as const, label: t.overview.dimCountry, count: totalCountries },
    { id: 'city' as const, label: t.overview.dimCity, count: totalCities },
    { id: 'place' as const, label: t.overview.dimPlace, count: totalPlaces },
  ]

  const rowCard = (row: OverviewRow, onClick: () => void) => (
    <button key={row.key ?? 'unnamed'} className="card--link blueprint" onClick={onClick}>
      <i className="corner tl" />
      <i className="corner tr" />
      <i className="corner bl" />
      <i className="corner br" />
      <div className="row" style={{ alignItems: 'baseline' }}>
        <span style={{ fontFamily: 'var(--font-heading)', fontSize: 19 }}>
          {row.label ?? t.overview.unnamed}
        </span>
        <span className="muted" style={{ marginLeft: 'auto', fontSize: 11 }}>
          {row.country ?? (row.city_count ? `${row.city_count} ${t.overview.cityCount}` : '')}
        </span>
      </div>
      <div className="row" style={{ gap: 14, alignItems: 'baseline' }}>
        <span className="metric">
          <span className="metric__value">{row.trip_count.toLocaleString()}</span>
          <span className="metric__label">{t.map.trips}</span>
        </span>
        <span className="metric">
          <span className="metric__value">{row.photo_count.toLocaleString()}</span>
          <span className="metric__label">{t.map.photos}</span>
        </span>
        <span className="metric">
          <span className="metric__value">{km(row.distance_m)}</span>
          <span className="metric__label">{t.stats.distance}</span>
        </span>
      </div>
      <div className="faint num" style={{ fontSize: 11 }}>
        {span(row.first_day, row.last_day)}
      </div>
    </button>
  )

  return (
    <div className="page page--scroll">
      <div className="page__title">
        <h1>{t.overview.title}</h1>
        <div className="seg" style={{ marginLeft: 'auto' }}>
          {dimensions.map((dimension) => (
            <label key={dimension.id} className="seg-opt">
              <input
                type="radio"
                name="dim"
                checked={focus.dimension === dimension.id}
                onChange={() =>
                  setOverview({
                    dimension: dimension.id,
                    country: null,
                    city: null,
                    anchor: null,
                  })
                }
              />
              {dimension.label} {dimension.count}
            </label>
          ))}
        </div>
      </div>

      <div className="crumbs" style={{ margin: '14px 0 4px' }}>
        <button
          className="crumbs__link"
          onClick={() => setOverview({ country: null, city: null, anchor: null })}
        >
          {dimensions.find((dimension) => dimension.id === focus.dimension)?.label}
        </button>
        {focus.country && <span className="crumbs__link">› {focus.country}</span>}
        {focus.city && <span className="crumbs__link">› {focus.city}</span>}
        {!drilled && (
          <span className="muted" style={{ fontSize: 12 }}>
            {focus.dimension === 'country'
              ? t.overview.pickCountry
              : focus.dimension === 'city'
                ? t.overview.pickCity
                : t.overview.pickPlace}
          </span>
        )}
      </div>

      <p className="faint" style={{ fontSize: 11.5, maxWidth: 700 }}>
        {t.overview.totalNote}
        <br />
        {/* The rows sum to more than the total; saying so beats being caught. */}
        {t.overview.distanceNote}
      </p>

      {geocodingOff && focus.dimension !== 'place' ? (
        <div className="notice notice--accent" style={{ maxWidth: 620, marginTop: 16 }}>
          <span>{t.overview.geocodingOff}</span>
          <button className="btn btn-ghost btn-sm" onClick={() => setSettingsOpen(true)}>
            {t.overview.openSettings} →
          </button>
        </div>
      ) : (
        <>
          {focus.dimension === 'country' && !focus.country && (
            <div className="grid" style={{ marginTop: 14 }}>
              {(countries.data ?? []).map((row) =>
                rowCard(row, () => setOverview({ country: row.key })),
              )}
            </div>
          )}

          {focus.dimension === 'country' && focus.country && (
            <>
              <div className="kicker" style={{ margin: '14px 0 8px' }}>
                {t.overview.citiesIn}
              </div>
              <div className="grid">
                {(cities.data ?? []).map((row) =>
                  rowCard(row, () => setOverview({ dimension: 'city', city: row.key, country: null })),
                )}
              </div>
            </>
          )}

          {focus.dimension === 'city' && (
            <div className="grid" style={{ marginTop: 14 }}>
              {(cities.data ?? []).map((row) => rowCard(row, () => setOverview({ city: row.key })))}
            </div>
          )}

          {focus.dimension === 'place' && (
            <div className="grid" style={{ marginTop: 14 }}>
              {(anchors.data ?? []).map((anchor) => (
                <button
                  key={anchor.id}
                  className="card--link blueprint"
                  onClick={() => setOverview({ anchor: anchor.id })}
                >
                  <i className="corner tl" />
                  <i className="corner tr" />
                  <i className="corner bl" />
                  <i className="corner br" />
                  <div className="row" style={{ alignItems: 'baseline' }}>
                    <span style={{ fontFamily: 'var(--font-heading)', fontSize: 19 }}>
                      {anchor.geo_name ?? anchor.geo_city ?? t.overview.unnamed}
                    </span>
                    <span className="muted" style={{ marginLeft: 'auto', fontSize: 11 }}>
                      {[anchor.geo_country, anchor.geo_city].filter(Boolean).join(' · ')}
                    </span>
                  </div>
                  <div className="row" style={{ gap: 14, alignItems: 'baseline' }}>
                    <span className="metric">
                      <span className="metric__value">{anchor.visit_count}</span>
                      <span className="metric__label">{t.overview.visits}</span>
                    </span>
                    <span className="metric">
                      <span className="metric__value">{anchor.trip_count}</span>
                      <span className="metric__label">{t.map.trips}</span>
                    </span>
                  </div>
                  <div className="faint num" style={{ fontSize: 11 }}>
                    {span(anchor.first_visit_utc, anchor.last_visit_utc)}
                  </div>
                </button>
              ))}
            </div>
          )}
        </>
      )}

      {drilled && (
        <>
          <div className="kicker" style={{ margin: '22px 0 8px' }}>
            {t.overview.tripsIn}
          </div>
          {(trips.data ?? []).length === 0 ? (
            <p className="muted">{t.overview.empty}</p>
          ) : (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t.map.trips}</th>
                    <th>{t.detail.date}</th>
                    <th>{t.map.photos}</th>
                    <th>{t.stats.distance}</th>
                    <th>{t.map.places}</th>
                  </tr>
                </thead>
                <tbody>
                  {(trips.data ?? []).map((trip) => (
                    <tr key={trip.id}>
                      <td>
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => navigate({ name: 'trip', id: trip.id })}
                        >
                          {trip.title}
                        </button>
                      </td>
                      <td className="num">{trip.local_date}</td>
                      <td className="num">{trip.stats.photo_count ?? 0}</td>
                      <td className="num">{km(trip.stats.distance_total_m ?? 0)}</td>
                      <td className="num">{trip.stats.place_count ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
