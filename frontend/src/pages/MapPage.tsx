import { useCallback } from 'react'

import { useCapabilities } from '@/api/hooks'
import DetailDrawer from '@/components/DetailDrawer'
import ExportPanel from '@/components/ExportPanel'
import FilterPanel from '@/components/FilterPanel'
import MapCanvas from '@/components/MapCanvas'
import TimelineSlider from '@/components/TimelineSlider'
import { t } from '@/i18n/zh'
import { useAppStore } from '@/store/appStore'

const MAPBOX_TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN as string | undefined) ?? ''

export default function MapPage() {
  const select = useAppStore((state) => state.select)
  const selection = useAppStore((state) => state.selection)
  const capabilities = useCapabilities()

  const onSelect = useCallback(
    (kind: 'track' | 'place' | 'photo', id: string) => select({ kind, id }),
    [select],
  )

  return (
    <div className="page page--flush">
      <div className="map-layout">
        <aside className="map-layout__filters">
          <FilterPanel />
        </aside>

        <div className="map-layout__canvas">
          {capabilities.data && !capabilities.data.mapbox_token_configured && !MAPBOX_TOKEN && (
            <div className="notice notice--warn" style={{ position: 'absolute', zIndex: 5, margin: 12 }}>
              {t.connection.mapboxMissing}
            </div>
          )}
          <MapCanvas mapboxToken={MAPBOX_TOKEN} onSelect={onSelect} />
        </div>

        {selection && <DetailDrawer />}

        <TimelineSlider />
      </div>
      <ExportPanel />
    </div>
  )
}
