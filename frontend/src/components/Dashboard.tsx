/**
 * The map's metric strip.
 *
 * The five KPIs are FULL-CORPUS totals, not window totals, and they are the
 * same numbers the overview page shows. "I have been to 14 countries" is a fact
 * about the user, not about the slider position - if dragging the histogram
 * changed it to 2, the number would mean nothing. What the window holds is
 * reported separately, on the right.
 *
 * Four of the five are buttons into the overview. The photo count is not: there
 * is no photo dimension to land on, and a button that goes nowhere is worse
 * than plain text.
 */

import { useStats } from '@/api/hooks'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

interface Props {
  zoom: number
}

function lodLabel(zoom: number, t: ReturnType<typeof useCopy>): string {
  if (zoom <= 5) return t.map.lodWorld
  if (zoom <= 10) return t.map.lodCountry
  if (zoom <= 15) return t.map.lodCity
  return t.map.lodStreet
}

export default function Dashboard({ zoom }: Props) {
  const t = useCopy()
  const navigate = useAppStore((state) => state.navigate)
  const setOverview = useAppStore((state) => state.setOverview)
  const setImportOpen = useAppStore((state) => state.setImportOpen)
  const timeFrom = useAppStore((state) => state.timeFrom)
  const timeTo = useAppStore((state) => state.timeTo)

  const total = useStats()
  const windowed = useStats({ from: timeFrom ?? undefined, to: timeTo ?? undefined })

  const openOverview = (dimension: 'country' | 'city' | 'place') => {
    setOverview({ dimension, country: null, city: null, anchor: null })
    navigate({ name: 'overview' })
  }

  // 0 countries with geocoding off would read as "you have been nowhere", which
  // is false. An em dash plus the reason is the honest rendering.
  const geoOff = (total.data?.countries ?? 0) === 0 && (total.data?.place_count ?? 0) > 0
  const geoValue = (value: number) => (geoOff ? t.app.dash : value.toLocaleString())

  const cells: Array<{ value: string; label: string; onClick?: () => void; title?: string }> = [
    {
      value: geoValue(total.data?.countries ?? 0),
      label: t.map.countries,
      onClick: () => openOverview('country'),
      title: geoOff ? t.map.geocodingOffHint : undefined,
    },
    {
      value: geoValue(total.data?.cities ?? 0),
      label: t.map.cities,
      onClick: () => openOverview('city'),
      title: geoOff ? t.map.geocodingOffHint : undefined,
    },
    {
      value: (total.data?.place_count ?? 0).toLocaleString(),
      label: t.map.places,
      onClick: () => openOverview('place'),
    },
    {
      value: (total.data?.trip_count ?? 0).toLocaleString(),
      label: t.map.trips,
      onClick: () => navigate({ name: 'trips' }),
    },
    { value: (total.data?.photos.total ?? 0).toLocaleString(), label: t.map.photos },
  ]

  const windowTracks = (windowed.data?.distance_by_mode ?? []).reduce(
    (sum, row) => sum + row.segments,
    0,
  )

  return (
    <div className="map__dashboard">
      {cells.map((cell) =>
        cell.onClick ? (
          <button
            key={cell.label}
            className="kpi kpi--link"
            onClick={cell.onClick}
            title={cell.title}
          >
            <span className="kpi__value">{cell.value}</span>
            <span className="kpi__label">{cell.label}</span>
          </button>
        ) : (
          <span key={cell.label} className="kpi" title={cell.title}>
            <span className="kpi__value">{cell.value}</span>
            <span className="kpi__label">{cell.label}</span>
          </span>
        ),
      )}

      <div className="map__dashboard-right">
        <span className="map__window-summary">
          {t.map.windowNow} {(windowed.data?.place_count ?? 0).toLocaleString()} {t.layers.places} ·{' '}
          {windowTracks.toLocaleString()} {t.layers.tracks} ·{' '}
          {(windowed.data?.photos.total ?? 0).toLocaleString()} {t.layers.photos}
        </span>
        <span className="tag tag-outline">{t.map.lod(lodLabel(zoom, t), Math.round(zoom))}</span>
        <button className="btn btn-secondary btn-sm" onClick={() => setImportOpen(true)}>
          + {t.nav.appendData}
        </button>
      </div>
    </div>
  )
}
