/**
 * HTTP client.
 *
 * Two headers are mandatory on every call and are the reason a hostile page
 * cannot drive this API:
 *
 *   X-Contrail-Client  anti-CSRF. With no authentication there is no credential
 *                      to withhold, so a custom header is the gate: a simple
 *                      cross-origin form or image request cannot set one.
 *   X-Contrail-Token   the local token from ~/.contrail/token, which stops other
 *                      processes on this machine from calling the API.
 */

import type {
  Anchor,
  AppSettings,
  Capabilities,
  CommuteOD,
  CommuteTrip,
  ExportRequest,
  FenceCheck,
  FenceSuggestions,
  Geofence,
  Group,
  PickResponse,
  Photo,
  Place,
  Prescan,
  SearchResults,
  SourceFile,
  Stats,
  Tag,
  TaskState,
  Track,
  Trip,
} from './types'

const BASE = '/api/v1'
const CLIENT_HEADER = 'X-Contrail-Client'
const CLIENT_VALUE = 'contrail-web'
const TOKEN_HEADER = 'X-Contrail-Token'
const TOKEN_STORAGE_KEY = 'contrail.localToken'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

let localToken = ''

export function setLocalToken(token: string): void {
  localToken = token.trim()
  try {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, localToken)
  } catch {
    // Private browsing or a blocked store: the token still works this session.
  }
}

export function getLocalToken(): string {
  if (!localToken) {
    try {
      localToken = window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? ''
    } catch {
      localToken = ''
    }
  }
  return localToken
}

function headers(json = true): HeadersInit {
  const out: Record<string, string> = { [CLIENT_HEADER]: CLIENT_VALUE }
  if (json) out['Content-Type'] = 'application/json'
  const token = getLocalToken()
  if (token) out[TOKEN_HEADER] = token
  return out
}

function qs(params: object | undefined): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) value.forEach((v) => search.append(key, String(v)))
    else search.append(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...headers(init.body !== undefined), ...(init.headers ?? {}) },
  })

  if (response.status === 204) return undefined as T

  const isJson = (response.headers.get('content-type') ?? '').includes('application/json')
  const payload = isJson ? await response.json() : await response.text()

  if (!response.ok) {
    const detail = isJson ? (payload as { detail?: unknown }).detail ?? payload : payload
    throw new ApiError(response.status, detail, `${response.status} ${path}`)
  }
  return payload as T
}

const get = <T,>(path: string, params?: object) => request<T>(`${path}${qs(params)}`)
const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const put = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: 'PUT', body: JSON.stringify(body) })
const patch = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
const del = <T,>(path: string) => request<T>(path, { method: 'DELETE' })

export interface TripQuery {
  from?: string
  to?: string
  bbox?: string
  group?: string
  tag?: string
  commute?: string
  q?: string
  limit?: number
}

export const api = {
  capabilities: () => get<Capabilities>('/capabilities'),
  health: () => get<{ status: string }>('/health'),

  // ── import ──────────────────────────────────────────────
  /** Opens the host's native folder chooser. 204 means the user cancelled. */
  pickDirectory: () => post<PickResponse | undefined>('/fs/pick'),
  /** Only a pick_token or an upload_id. A path field is a 400 by contract. */
  prescan: (body: { pick_token?: string; upload_id?: string }) =>
    post<Prescan>('/sources/prescan', body),
  upload: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const response = await fetch(`${BASE}/sources/upload`, {
      method: 'POST',
      headers: headers(false),
      body: form,
    })
    if (!response.ok) {
      throw new ApiError(response.status, await response.text(), 'upload failed')
    }
    return (await response.json()) as { upload_id: string; display_name: string; byte_size: number }
  },
  createImport: (body: {
    source_ref: string
    kind: 'photo' | 'file'
    group_id?: string | null
    tag_ids?: string[]
  }) => post<TaskState>('/imports', body),
  listImports: () => get<TaskState[]>('/imports'),
  getImport: (id: string) => get<TaskState>(`/imports/${id}`),
  cancelImport: (id: string) => del<{ cancelled: boolean }>(`/imports/${id}`),
  importEventsUrl: (id: string) => `${BASE}/imports/${id}/events`,

  listSources: () => get<SourceFile[]>('/sources'),
  deleteSource: (id: string) => del<{ deleted: boolean }>(`/sources/${id}`),

  // ── query ───────────────────────────────────────────────
  trips: (params?: TripQuery) => get<Trip[]>('/trips', params),
  trip: (id: string) =>
    get<{ trip: Trip; places: Place[]; tracks: Track[]; photos: Photo[] }>(`/trips/${id}`),
  places: (params?: Record<string, unknown>) => get<Place[]>('/places', params),
  tracks: (params?: Record<string, unknown>) => get<Track[]>('/tracks', params),
  photos: (params?: Record<string, unknown>) => get<Photo[]>('/photos', params),
  anchors: (params?: { kind?: string }) => get<Anchor[]>('/anchors', params),
  search: (q: string) => get<SearchResults>('/search', { q }),
  stats: (params?: { from?: string; to?: string; group?: string }) => get<Stats>('/stats', params),

  thumbUrl: (photoId: string) => `${BASE}/photos/${photoId}/thumb`,
  microUrl: (photoId: string) => `${BASE}/photos/${photoId}/micro`,
  tileUrl: (layer: 'tracks' | 'places' | 'photos') =>
    `${window.location.origin}${BASE}/tiles/${layer}/{z}/{x}/{y}.mvt`,

  // ── organise ────────────────────────────────────────────
  groups: () => get<Group[]>('/groups'),
  createGroup: (body: { name: string; color?: string | null }) => post<Group>('/groups', body),
  updateGroup: (id: string, body: { name: string; color?: string | null }) =>
    patch<Group>(`/groups/${id}`, body),
  deleteGroup: (id: string) => del<void>(`/groups/${id}`),

  tags: () => get<Tag[]>('/tags'),
  createTag: (body: { name: string; color?: string | null }) => post<Tag>('/tags', body),
  deleteTag: (id: string) => del<void>(`/tags/${id}`),

  /** Metadata only. Trip content is algorithm-owned and cannot be edited (P7). */
  patchTrip: (id: string, body: { title?: string; group_id?: string | null; tag_ids?: string[] }) =>
    patch<{ id: string; title: string }>(`/trips/${id}`, body),
  bulkAssignTrips: (body: {
    trip_ids: string[]
    group_id?: string | null
    add_tags?: string[]
    remove_tags?: string[]
  }) => post<{ updated: number }>('/trips/bulk-assign', body),

  // ── commute ─────────────────────────────────────────────
  commuteOds: () => get<CommuteOD[]>('/commute/ods'),
  commuteTrips: (params?: { class?: string }) => get<CommuteTrip[]>('/commute/trips', params),
  commuteAction: (body: { trip_ids: string[]; action: 'collapse' | 'to_normal' | 'delete' }) =>
    post<{ affected: number; action: string }>('/commute/trips/actions', body),
  recomputeCommute: () =>
    post<{ ran: boolean; reason?: string; workdays?: number; required_workdays?: number }>(
      '/commute/recompute',
    ),

  // ── settings and fences ─────────────────────────────────
  settings: () => get<AppSettings>('/settings'),
  saveSettings: (body: Partial<AppSettings>) => put<AppSettings>('/settings', body),
  geofences: () => get<Geofence[]>('/geofences'),
  fenceSuggestions: () => get<FenceSuggestions>('/geofences/suggestions'),
  createFence: (body: {
    kind: 'home' | 'work'
    label: string
    lat: number
    lon: number
    radius_m?: number
    enabled?: boolean
  }) => post<Geofence>('/geofences', body),
  updateFence: (
    id: string,
    body: {
      kind: 'home' | 'work'
      label: string
      lat: number
      lon: number
      radius_m: number
      enabled: boolean
    },
  ) => patch<Geofence>(`/geofences/${id}`, body),
  deleteFence: (id: string) => del<void>(`/geofences/${id}`),
  recluster: () => post<Record<string, unknown>>('/recluster'),

  // ── export ──────────────────────────────────────────────
  /**
   * MUST be called before any export. The server refuses an intersecting export
   * without fence_actions regardless, but calling this is what lets the UI ask
   * the user rather than surfacing a raw 422.
   */
  fenceCheck: (body: { trip_ids?: string[]; place_ids?: string[] }) =>
    post<FenceCheck>('/exports/fence-check', body),
  exportPreview: async (body: ExportRequest) => {
    const response = await fetch(`${BASE}/exports/preview`, {
      method: 'POST',
      headers: headers(true),
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      const isJson = (response.headers.get('content-type') ?? '').includes('application/json')
      const payload = isJson ? await response.json() : await response.text()
      throw new ApiError(response.status, (payload as { detail?: unknown })?.detail ?? payload, 'preview failed')
    }
    return URL.createObjectURL(await response.blob())
  },
  createExport: (body: ExportRequest) =>
    post<{ task_id: string; status: string; download_url: string; fence_action: string | null }>(
      '/exports',
      body,
    ),
  dataExportUrl: () => `${BASE}/exports/data`,
}

export type Api = typeof api
