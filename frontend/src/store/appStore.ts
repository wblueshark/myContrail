/**
 * UI state (Zustand). Server state lives in TanStack Query - the two are kept
 * strictly apart so a refetch never clobbers what the user is doing.
 *
 * The time window and layer toggles live here rather than in query keys on
 * purpose: MVT features carry mode / source / commute / timestamps as feature
 * ATTRIBUTES, so the histogram filters on the client at 60 fps without a single
 * request.
 */

import { create } from 'zustand'

import type { SourceKind, TravelMode } from '@/api/types'

export type Route =
  | { name: 'map' }
  | { name: 'overview' }
  | { name: 'timeline' }
  | { name: 'trips' }
  | { name: 'trip'; id: string }
  | { name: 'groups' }
  | { name: 'commute' }
  | { name: 'sources' }

export type Theme = 'light' | 'dark'

export type Selection =
  | { kind: 'place'; id: string }
  | { kind: 'track'; id: string }
  | { kind: 'photo'; id: string }
  | { kind: 'trip'; id: string }
  | null

/** Where the overview is pointing. Mirrors the breadcrumb. */
export interface OverviewFocus {
  dimension: 'country' | 'city' | 'place'
  country: string | null
  city: string | null
  anchor: string | null
}

export const ALL_MODES: TravelMode[] = ['walk', 'run', 'bike', 'car', 'transit', 'flight', 'unknown']
export const ALL_SOURCES: SourceKind[] = [
  'photo',
  'google_timeline',
  'google_records',
  'google_semantic',
  'gpx',
  'tcx',
  'fit',
  'manual',
]

export interface LayerToggles {
  tracks: boolean
  places: boolean
  photos: boolean
}

const THEME_KEY = 'contrail.theme'
const GUIDE_KEY = 'contrail.guideSeen'
const FENCE_KEY = 'contrail.fencesConfirmed'

function storedTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

function storedFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function persist(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // Private browsing: the preference just does not survive the session.
  }
}

interface AppState {
  route: Route
  navigate: (route: Route) => void

  theme: Theme
  setTheme: (theme: Theme) => void

  connected: boolean
  setConnected: (value: boolean) => void

  /** Inclusive UTC bounds, or null for "everything". */
  timeFrom: string | null
  timeTo: string | null
  setTimeRange: (from: string | null, to: string | null) => void

  layers: LayerToggles
  toggleLayer: (layer: keyof LayerToggles) => void

  modes: Set<TravelMode>
  toggleMode: (mode: TravelMode) => void

  sources: Set<SourceKind>
  toggleSource: (source: SourceKind) => void

  groupFilter: string | null
  tagFilter: string | null
  setGroupFilter: (id: string | null) => void
  setTagFilter: (id: string | null) => void

  searchTerm: string
  setSearchTerm: (term: string) => void

  selection: Selection
  select: (selection: Selection) => void

  overview: OverviewFocus
  setOverview: (focus: Partial<OverviewFocus>) => void

  /** Trips staged for export; also what the fence check is run against. */
  exportTripIds: string[]
  toggleExportTrip: (id: string) => void
  setExportTrips: (ids: string[]) => void
  clearExport: () => void
  exportOpen: boolean
  setExportOpen: (open: boolean) => void

  settingsOpen: boolean
  setSettingsOpen: (open: boolean) => void

  importOpen: boolean
  setImportOpen: (open: boolean) => void

  /** Onboarding: fences are confirmed before the first map, then never again. */
  fenceModalOpen: boolean
  setFenceModalOpen: (open: boolean) => void
  fencesConfirmed: boolean
  markFencesConfirmed: () => void

  guideStep: number
  startGuide: () => void
  advanceGuide: () => void
  endGuide: () => void

  resetFilters: () => void
}

function parseHash(): Route {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const [name, param] = raw.split('/')
  switch (name) {
    case 'overview':
      return { name: 'overview' }
    case 'timeline':
      return { name: 'timeline' }
    case 'trips':
      return param ? { name: 'trip', id: param } : { name: 'trips' }
    case 'groups':
      return { name: 'groups' }
    case 'commute':
      return { name: 'commute' }
    case 'sources':
      return { name: 'sources' }
    default:
      return { name: 'map' }
  }
}

export function routeToHash(route: Route): string {
  switch (route.name) {
    case 'trip':
      return `#/trips/${route.id}`
    case 'map':
      return '#/map'
    default:
      return `#/${route.name}`
  }
}

export const useAppStore = create<AppState>((set) => ({
  route: parseHash(),
  navigate: (route) => {
    const hash = routeToHash(route)
    if (window.location.hash !== hash) window.location.hash = hash
    set({ route })
  },

  theme: storedTheme(),
  setTheme: (theme) => {
    persist(THEME_KEY, theme)
    document.documentElement.dataset.theme = theme
    set({ theme })
  },

  connected: false,
  setConnected: (value) => set({ connected: value }),

  timeFrom: null,
  timeTo: null,
  setTimeRange: (timeFrom, timeTo) => set({ timeFrom, timeTo }),

  layers: { tracks: true, places: true, photos: true },
  toggleLayer: (layer) =>
    set((state) => ({ layers: { ...state.layers, [layer]: !state.layers[layer] } })),

  modes: new Set(ALL_MODES),
  toggleMode: (mode) =>
    set((state) => {
      const next = new Set(state.modes)
      if (next.has(mode)) next.delete(mode)
      else next.add(mode)
      return { modes: next }
    }),

  sources: new Set(ALL_SOURCES),
  toggleSource: (source) =>
    set((state) => {
      const next = new Set(state.sources)
      if (next.has(source)) next.delete(source)
      else next.add(source)
      return { sources: next }
    }),

  groupFilter: null,
  tagFilter: null,
  setGroupFilter: (groupFilter) => set({ groupFilter }),
  setTagFilter: (tagFilter) => set({ tagFilter }),

  searchTerm: '',
  setSearchTerm: (searchTerm) => set({ searchTerm }),

  selection: null,
  select: (selection) => set({ selection }),

  overview: { dimension: 'country', country: null, city: null, anchor: null },
  setOverview: (focus) => set((state) => ({ overview: { ...state.overview, ...focus } })),

  exportTripIds: [],
  toggleExportTrip: (id) =>
    set((state) => ({
      exportTripIds: state.exportTripIds.includes(id)
        ? state.exportTripIds.filter((t) => t !== id)
        : [...state.exportTripIds, id],
    })),
  setExportTrips: (exportTripIds) => set({ exportTripIds }),
  clearExport: () => set({ exportTripIds: [], exportOpen: false }),
  exportOpen: false,
  setExportOpen: (exportOpen) => set({ exportOpen }),

  settingsOpen: false,
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),

  importOpen: false,
  setImportOpen: (importOpen) => set({ importOpen }),

  fenceModalOpen: false,
  setFenceModalOpen: (fenceModalOpen) => set({ fenceModalOpen }),
  fencesConfirmed: storedFlag(FENCE_KEY),
  markFencesConfirmed: () => {
    persist(FENCE_KEY, '1')
    set({ fencesConfirmed: true, fenceModalOpen: false })
  },

  // 3 means "finished": the bubbles render for steps 0..2.
  guideStep: storedFlag(GUIDE_KEY) ? 3 : 0,
  startGuide: () => set({ guideStep: 0 }),
  advanceGuide: () =>
    set((state) => {
      const next = state.guideStep + 1
      if (next >= 3) persist(GUIDE_KEY, '1')
      return { guideStep: next }
    }),
  endGuide: () => {
    persist(GUIDE_KEY, '1')
    set({ guideStep: 3 })
  },

  resetFilters: () =>
    set({
      timeFrom: null,
      timeTo: null,
      modes: new Set(ALL_MODES),
      sources: new Set(ALL_SOURCES),
      groupFilter: null,
      tagFilter: null,
      searchTerm: '',
    }),
}))

document.documentElement.dataset.theme = useAppStore.getState().theme

/** Keeps the browser back button working without pulling in a router. */
export function installHashListener(): () => void {
  const handler = () => useAppStore.setState({ route: parseHash() })
  window.addEventListener('hashchange', handler)
  return () => window.removeEventListener('hashchange', handler)
}
