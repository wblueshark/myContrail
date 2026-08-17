/**
 * Map canvas: Mapbox GL for the basemap and vector tiles, deck.gl on top for
 * photo thumbnails.
 *
 * Tracks and places come from our own MVT endpoints, and every filterable
 * attribute (mode, source, commute flag, timestamps) travels as a FEATURE
 * PROPERTY. Filtering is therefore a Mapbox filter expression evaluated on the
 * GPU - dragging the timeline never issues a request. That is the whole reason
 * the tile layer emits attributes instead of pre-filtering in SQL.
 *
 * The basemap follows the application theme. Switching it is a `setStyle` and a
 * reinstall of our own layers, never a new map: the camera is where the user
 * left it, and finding it again is not the price of turning the lights on.
 *
 * No datum shift anywhere: stored data and the Mapbox basemap are both WGS-84.
 */

import type { Layer } from '@deck.gl/core'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { IconLayer } from '@deck.gl/layers'
import mapboxgl from 'mapbox-gl'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '@/api/client'
import { usePhotos } from '@/api/hooks'
import type { Photo, SourceKind, TravelMode } from '@/api/types'
import { useAppStore, type Theme } from '@/store/appStore'

// The design system's transport palette. `run` moved off the danger colour in
// design v2: a running track and a selected place used to render identically.
const MODE_COLOR: Record<TravelMode, string> = {
  walk: '#8fb8dd',
  run: '#d9663c',
  bike: '#8f6fd1',
  car: '#4fa08f',
  transit: '#d9a13c',
  flight: '#c05f9c',
  unknown: '#98989b',
}

const BASEMAP: Record<Theme, string> = {
  light: 'mapbox://styles/mapbox/light-v11',
  dark: 'mapbox://styles/mapbox/dark-v11',
}

// Read against the BASEMAP, not against the app chrome: a dark halo disappears
// on a dark map and a white one disappears on a light one, and the halo is the
// only thing keeping a coloured route legible over street detail.
const PAINT: Record<Theme, { casing: string; casingOpacity: number; place: string; placeStroke: string }> = {
  light: { casing: '#ffffff', casingOpacity: 0.9, place: '#16222e', placeStroke: '#ffffff' },
  dark: { casing: '#0d0f13', casingOpacity: 0.55, place: '#f2f4f8', placeStroke: '#14161a' },
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
  const bound = useRef(false)
  const applied = useRef<string | null>(null)

  // A style swap wipes every source and layer we added. The epoch tells the
  // effects below that what they configured is gone and has to be reapplied.
  const [styleEpoch, setStyleEpoch] = useState(0)

  const theme = useAppStore((state) => state.theme)
  // The mount effect must not list `theme`: re-running it would rebuild the map
  // and throw away the camera. It reads the current value through the ref.
  const themeRef = useRef(theme)
  themeRef.current = theme

  const layers = useAppStore((state) => state.layers)
  const modes = useAppStore((state) => state.modes)
  const sources = useAppStore((state) => state.sources)
  const timeFrom = useAppStore((state) => state.timeFrom)
  const timeTo = useAppStore((state) => state.timeTo)

  // Photos are fetched as data rather than tiles so their thumbnails can be
  // used directly as deck.gl icons.
  const photos = usePhotos(
    { from: timeFrom ?? undefined, to: timeTo ?? undefined, limit: 500 },
    layers.photos,
  )

  /**
   * Put our sources and layers back on top of whatever style is loaded.
   *
   * Called on every `style.load`, which covers both the first load and every
   * theme switch - `setStyle` keeps the camera and the controls but drops
   * everything the application added.
   */
  const installLayers = useCallback(
    (instance: mapboxgl.Map) => {
      const paint = PAINT[themeRef.current]

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

      // Casing under the coloured line: without it a route is unreadable over a
      // busy basemap.
      instance.addLayer({
        id: TRACK_CASING,
        type: 'line',
        source: TRACK_SOURCE,
        'source-layer': 'tracks',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': paint.casing,
          'line-opacity': paint.casingOpacity,
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
          'circle-color': paint.place,
          'circle-opacity': 0.85,
          'circle-stroke-width': 1.4,
          // A dwell partly deduced from a data gap is drawn differently, so it
          // never passes as measured.
          'circle-stroke-color': [
            'case',
            ['==', ['get', 'is_inferred_dwell'], true],
            '#e0a54a',
            paint.placeStroke,
          ],
        },
      })

      // Delegated listeners live on the map, not on the style, so they survive a
      // style swap and are bound exactly once.
      if (!bound.current) {
        bound.current = true
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
      }

      // The interleaved overlay is a custom layer inside the style, so it goes
      // with it. The theme effect removed the old one before swapping.
      if (!overlay.current) {
        overlay.current = new MapboxOverlay({ interleaved: true, layers: [] })
        instance.addControl(overlay.current)
      }

      ready.current = true
      setStyleEpoch((epoch) => epoch + 1)
    },
    [onSelect],
  )

  useEffect(() => {
    if (!container.current || map.current || !mapboxToken) return
    mapboxgl.accessToken = mapboxToken

    applied.current = BASEMAP[themeRef.current]
    const instance = new mapboxgl.Map({
      container: container.current,
      style: applied.current,
      center: [0, 20],
      zoom: 1.4,
      attributionControl: true,
    })
    instance.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right')
    instance.addControl(new mapboxgl.ScaleControl({ unit: 'metric' }), 'bottom-left')
    map.current = instance

    // Not 'load': that one fires once. 'style.load' fires again after every
    // setStyle, which is exactly when the layers need reinstalling.
    instance.on('style.load', () => installLayers(instance))

    return () => {
      ready.current = false
      bound.current = false
      applied.current = null
      overlay.current = null
      instance.remove()
      map.current = null
    }
  }, [installLayers, mapboxToken])

  // Theme switch: swap the basemap in place. Rebuilding the map would be
  // simpler and would throw away the camera, which the user would have to
  // find again every time they change the theme.
  //
  // Guarded on the style actually applied rather than on `ready`, so a switch
  // made while the first style is still loading is not silently dropped.
  useEffect(() => {
    const instance = map.current
    if (!instance || applied.current === BASEMAP[theme]) return
    applied.current = BASEMAP[theme]
    ready.current = false
    if (overlay.current) {
      instance.removeControl(overlay.current)
      overlay.current = null
    }
    instance.setStyle(BASEMAP[theme])
  }, [theme])

  // Filters and visibility are style updates - no refetch, no tile reload.
  // `styleEpoch` is in the dependencies because a reinstalled layer starts
  // unfiltered and visible.
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
  }, [layers, modes, sources, styleEpoch, timeFrom, timeTo])

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

    // No heatmap layer: F-31 stays in P2 and the MVP does not render a control
    // for it, so there is nothing here to switch on.
    overlay.current.setProps({ layers: deckLayers })
  }, [layers.photos, located, onSelect, styleEpoch])

  // Without a token there is no basemap, but the user's own geometry is still
  // real - the canvas keeps its place and the overlay explains the gap.
  if (!mapboxToken) return <div className="map-canvas" ref={container} />

  return <div className="map-canvas" ref={container} style={{ height: '100%' }} />
}
