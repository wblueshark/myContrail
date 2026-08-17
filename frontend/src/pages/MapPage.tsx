/**
 * The map workbench: filters, metric strip, canvas, histogram, detail drawer.
 *
 * The canvas keeps its own state (Mapbox GL + deck.gl). Everything around it
 * reads the store, so a filter change is a style update rather than a fetch.
 */

import { Crosshair, PanelLeft } from 'lucide-react'
import { useCallback, useState } from 'react'

import { useCapabilities, useStats } from '@/api/hooks'
import Dashboard from '@/components/Dashboard'
import DetailDrawer from '@/components/DetailDrawer'
import FilterPanel from '@/components/FilterPanel'
import GuideBubbles from '@/components/GuideBubbles'
import Histogram from '@/components/Histogram'
import MapCanvas from '@/components/MapCanvas'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

const MAPBOX_TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN as string | undefined) ?? ''

export default function MapPage() {
  const t = useCopy()
  const select = useAppStore((state) => state.select)
  const selection = useAppStore((state) => state.selection)
  const timeFrom = useAppStore((state) => state.timeFrom)
  const timeTo = useAppStore((state) => state.timeTo)
  const setTimeRange = useAppStore((state) => state.setTimeRange)
  const setExportOpen = useAppStore((state) => state.setExportOpen)
  const capabilities = useCapabilities()
  const windowed = useStats({ from: timeFrom ?? undefined, to: timeTo ?? undefined })

  const [filtersOpen, setFiltersOpen] = useState(true)
  const [zoom] = useState(12)

  const onSelect = useCallback(
    (kind: 'track' | 'place' | 'photo', id: string) => select({ kind, id }),
    [select],
  )

  const basemapMissing =
    capabilities.data !== undefined && !capabilities.data.mapbox_token_configured && !MAPBOX_TOKEN
  const emptyWindow =
    windowed.isSuccess &&
    windowed.data.place_count === 0 &&
    windowed.data.trip_count === 0 &&
    Boolean(timeFrom || timeTo)

  return (
    <div className="page">
      <div className="map">
        <aside className="map__filters" hidden={!filtersOpen}>
          <FilterPanel />
        </aside>

        <div className="map__main">
          <Dashboard zoom={zoom} />

          <div className="map__canvas">
            <button
              className="btn btn-secondary btn-icon panel-toggle"
              style={{ position: 'absolute', left: 12, top: 12, zIndex: 5 }}
              onClick={() => setFiltersOpen((open) => !open)}
              title={t.filters.time}
            >
              <PanelLeft size={16} strokeWidth={1.5} />
            </button>

            <MapCanvas mapboxToken={MAPBOX_TOKEN} onSelect={onSelect} />

            {basemapMissing && (
              <div className="map__overlay map__overlay--bl">
                <Crosshair size={12} strokeWidth={1.5} />
                {t.connection.mapboxMissing}
              </div>
            )}

            <div className="map__overlay map__overlay--br">
              <span
                style={{
                  padding: '4px 8px',
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-divider)',
                }}
              >
                {t.map.shiftHint}
              </span>
              {/* Attribution is not switchable: it is the basemap licence. */}
              <span className="faint" style={{ fontSize: 10 }}>
                {t.map.attribution}
              </span>
            </div>

            {emptyWindow && (
              <div className="map__empty">
                <span style={{ fontFamily: 'var(--font-heading)', fontSize: 20 }}>
                  {t.map.emptyWindow}
                </span>
                <span className="muted" style={{ fontSize: 12 }}>
                  {t.map.emptyWindowHint}
                </span>
                <button
                  className="btn btn-secondary"
                  style={{ marginTop: 6 }}
                  onClick={() => setTimeRange(null, null)}
                >
                  {t.filters.timeAll}
                </button>
              </div>
            )}

            <GuideBubbles />
          </div>

          <Histogram onExport={() => setExportOpen(true)} />
        </div>

        {selection && <DetailDrawer />}
      </div>
    </div>
  )
}
