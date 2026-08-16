/**
 * Map canvas: Mapbox GL for the basemap and vector tiles, deck.gl on top for
 * photos and the heatmap.
 *
 * Tracks and places come from our own MVT endpoints, and every filterable
 * attribute (mode, source, commute flag, timestamps) travels as a FEATURE
 * PROPERTY. Filtering is therefore a Mapbox filter expression evaluated on the
 * GPU - dragging the timeline never issues a request. That is the whole reason
 * the tile layer emits attributes instead of pre-filtering in SQL.
 *
 * No datum shift anywhere: stored data and the Mapbox basemap are both WGS-84.
 */

import { HeatmapLayer } from '@deck.gl/aggregation-layers'
import type { Layer } from '@deck.gl/core'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { IconLayer } from '@deck.gl/layers'
import mapboxgl from 'mapbox-gl'
import { useEffect, useMemo, useRef } from 'react'

import { api } from '@/api/client'
import { usePhotos } from '@/api/hooks'
import type { Photo, SourceKind, TravelMode } from '@/api/types'
import { t } from '@/i18n/zh'
import { useAppStore } from '@/store/appStore'

const MODE_COLOR: Record<TravelMode, string> = {
  walk: '#33a76b',
  run: '#f28c26',
  bike: '#409acf',
  car: '#e55a5a',
  transit: '#8c66d9',
  flight: '#59bfd9',
  unknown: '#8c8f96',
}

const TRACK_SOURCE = 'contrail-tracks'
const PLACE_SOURCE = 'contrail-places'
const TRACK_LAYER = 'contrail-tracks-line'
const TRACK_CASING = 'contrail-tracks-casing'
const PLACE_LAYER = 'contrail-places-circle'

interface Props {
  mapboxToken: string
  onSelect: (kind: 'track' | 'place' | 'photo', id: string) => void
}

function colorExpression(): mapboxgl.ExpressionSpecification {
  const stops: unknown[] = ['match', ['get', 'mode']]
  for (const [mode, color] of Object.entries(MODE_COLOR)) {
    if (mode !== 'unknown') stops.push(mode, color)
  }
  stops.push(MODE_COLOR.unknown)
  return stops as mapboxgl.ExpressionSpecification
}

/** Client-side filter over the attributes the tiles carry. */
function buildFilter(
  modes: Set<TravelMode>,
  sources: Set<SourceKind>,
  from: string | null,
  to: string | null,
  withMode: boolean,
): mapboxgl.FilterSpecification {
  const clauses: unknown[] = ['all']
  if (withMode && modes.size < Object.keys(MODE_COLOR).length) {
    clauses.push(['in', ['get', 'mode'], ['literal', [...modes]]])
  }
  if (from) {
    const seconds = Math.floor(new Date(from).getTime() / 1000)
    clauses.push(['>=', ['coalesce', ['get', 'end_ts'], ['get', 'start_ts']], seconds])
  }
  if (to) {
    const seconds = Math.floor(new Date(to).getTime() / 1000)
    clauses.push(['<=', ['get', 'start_ts'], seconds])
  }
  if (withMode && sources.size < 8) {
    clauses.push(['in', ['get', 'source_kind'], ['literal', [...sources]]])
  }
  return clauses as mapboxgl.FilterSpecification
}

export default function MapCanvas({ mapboxToken, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<mapboxgl.Map | null>(null)
  const overlay = useRef<MapboxOverlay | null>(null)
  const ready = useRef(false)

  const layers = useAppStore((state) => state.layers)
  const modes = useAppStore((state) => state.modes)
  const sources = useAppStore((state) => state.sources)
  const timeFrom = useAppStore((state) => state.timeFrom)
  const timeTo = useAppStore((state) => state.timeTo)

  // Photos are fetched as data rather than tiles so their thumbnails can be
  // used directly as deck.gl icons.
  const photos = usePhotos(
    { from: timeFrom ?? undefined, to: timeTo ?? undefined, limit: 500 },
    layers.photos || layers.heatmap,
  )

  useEffect(() => {
    if (!container.current || map.current || !mapboxToken) return
    mapboxgl.accessToken = mapboxToken

    const instance = new mapboxgl.Map({
      container: container.current,
      style: 'mapbox://styles/mapbox/dark-v11',
      center: [0, 20],
      zoom: 1.4,
      attributionControl: true,
    })
    instance.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right')
    instance.addControl(new mapboxgl.ScaleControl({ unit: 'metric' }), 'bottom-left')
    map.current = instance

    instance.on('load', () => {
      instance.addSource(TRACK_SOURCE, {
        type: 'vector',
        tiles: [api.tileUrl('tracks')],
        minzoom: 0,
        maxzoom: 22,
      })
      instance.addSource(PLACE_SOURCE, {
        type: 'vector',
        tiles: [api.tileUrl('places')],
        minzoom: 0,
        maxzoom: 22,
      })

      // White casing under the coloured line: without it a route is unreadable
      // over a busy basemap.
      instance.addLayer({
        id: TRACK_CASING,
        type: 'line',
        source: TRACK_SOURCE,
        'source-layer': 'tracks',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': '#0d0f13',
          'line-opacity': 0.55,
          'line-width': ['interpolate', ['linear'], ['zoom'], 4, 2.4, 12, 6, 18, 10],
        },
      })
      instance.addLayer({
        id: TRACK_LAYER,
        type: 'line',
        source: TRACK_SOURCE,
        'source-layer': 'tracks',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': colorExpression(),
          // Endpoint-only geometry is a straight-line placeholder, not a
          // measured route, so it is drawn dashed rather than as a real path.
          'line-dasharray': ['case', ['==', ['get', 'geom_quality'], 'endpoints_only'], ['literal', [2, 2]], ['literal', [1]]],
          'line-width': ['interpolate', ['linear'], ['zoom'], 4, 1.1, 12, 3, 18, 6],
        },
      })
      instance.addLayer({
        id: PLACE_LAYER,
        type: 'circle',
        source: PLACE_SOURCE,
        'source-layer': 'places',
        paint: {
          // Radius on a log scale: a 12-hour stay must not be 48x a 15-minute one.
          'circle-radius': [
            'interpolate',
            ['linear'],
            ['zoom'],
            4,
            ['*', 1.4, ['log10', ['max', 2, ['/', ['get', 'duration_s'], 60]]]],
            14,
            ['*', 5.0, ['log10', ['max', 2, ['/', ['get', 'duration_s'], 60]]]],
          ],
          'circle-color': '#f2f4f8',
          'circle-opacity': 0.85,
          'circle-stroke-width': 1.4,
          // A dwell partly deduced from a data gap is drawn differently, so it
          // never passes as measured.
          'circle-stroke-color': [
            'case',
            ['==', ['get', 'is_inferred_dwell'], true],
            '#e0a54a',
            '#14161a',
          ],
        },
      })

      for (const layerId of [TRACK_LAYER, PLACE_LAYER]) {
        instance.on('click', layerId, (event) => {
          const feature = event.features?.[0]
          if (!feature) return
          const id = String(feature.properties?.id ?? '')
          if (id) onSelect(layerId === TRACK_LAYER ? 'track' : 'place', id)
        })
        instance.on('mouseenter', layerId, () => {
          instance.getCanvas().style.cursor = 'pointer'
        })
        instance.on('mouseleave', layerId, () => {
          instance.getCanvas().style.cursor = ''
        })
      }

      overlay.current = new MapboxOverlay({ interleaved: true, layers: [] })
      instance.addControl(overlay.current)
      ready.current = true
    })

    return () => {
      ready.current = false
      overlay.current = null
      instance.remove()
      map.current = null
    }
  }, [mapboxToken, onSelect])

  // Filters and visibility are style updates - no refetch, no tile reload.
  useEffect(() => {
    const instance = map.current
    if (!instance || !ready.current) return

    const trackFilter = buildFilter(modes, sources, timeFrom, timeTo, true)
    const placeFilter = buildFilter(modes, sources, timeFrom, timeTo, false)

    for (const id of [TRACK_LAYER, TRACK_CASING]) {
      if (instance.getLayer(id)) {
        instance.setFilter(id, trackFilter)
        instance.setLayoutProperty(id, 'visibility', layers.tracks ? 'visible' : 'none')
      }
    }
    if (instance.getLayer(PLACE_LAYER)) {
      instance.setFilter(PLACE_LAYER, placeFilter)
      instance.setLayoutProperty(PLACE_LAYER, 'visibility', layers.places ? 'visible' : 'none')
    }
  }, [layers, modes, sources, timeFrom, timeTo])

  const located = useMemo(
    () => (photos.data ?? []).filter((p): p is Photo & { lat: number; lon: number } =>
      p.lat !== null && p.lon !== null),
    [photos.data],
  )

  useEffect(() => {
    if (!overlay.current) return
    const deckLayers: Layer[] = []

    if (layers.photos && located.length) {
      deckLayers.push(
        new IconLayer<Photo & { lat: number; lon: number }>({
          id: 'contrail-photos',
          data: located,
          pickable: true,
          sizeScale: 1,
          getPosition: (photo) => [photo.lon, photo.lat],
          getSize: 34,
          // Thumbnails are lazily loaded into the texture atlas by deck.gl.
          getIcon: (photo) => ({
            url: api.microUrl(photo.id),
            width: 64,
            height: 64,
            anchorY: 32,
            mask: false,
          }),
          onClick: (info) => {
            const photo = info.object as Photo | undefined
            if (photo) onSelect('photo', photo.id)
          },
        }),
      )
    }

    if (layers.heatmap && located.length) {
      deckLayers.push(
        new HeatmapLayer<Photo & { lat: number; lon: number }>({
          id: 'contrail-heatmap',
          data: located,
          getPosition: (photo) => [photo.lon, photo.lat],
          getWeight: () => 1,
          radiusPixels: 42,
          intensity: 1,
          threshold: 0.05,
        }),
      )
    }

    overlay.current.setProps({ layers: deckLayers })
  }, [layers.photos, layers.heatmap, located, onSelect])

  if (!mapboxToken) {
    return (
      <div className="map-empty">
        <div>
          <p>{t.connection.mapboxMissing}</p>
          <p className="faint">VITE_MAPBOX_TOKEN</p>
        </div>
      </div>
    )
  }

  return <div className="map-canvas" ref={container} />
}
