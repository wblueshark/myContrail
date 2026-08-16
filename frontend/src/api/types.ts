/** Mirrors backend/contrail/schemas.py. */

export interface Capabilities {
  mode: string
  scan_local_path: boolean
  /** null means no native folder chooser on this host, so photo import is hidden entirely. */
  directory_picker: string | null
  serve_original: boolean
  multi_user: boolean
  sharing: boolean
  geocoding_enabled: boolean
  mapbox_token_configured: boolean
}

export type TravelMode = 'walk' | 'run' | 'bike' | 'car' | 'transit' | 'flight' | 'unknown'
export type CommuteClass = 'pure' | 'mixed' | 'none'
export type SourceKind =
  | 'photo'
  | 'google_records'
  | 'google_semantic'
  | 'google_timeline'
  | 'gpx'
  | 'tcx'
  | 'fit'
  | 'manual'

export interface Trip {
  id: string
  title: string
  local_date: string
  anchor_tz: string
  start_utc: string
  end_utc: string
  group_id: string | null
  commute_class: CommuteClass
  stats: TripStats
  tag_ids: string[]
  cover_photo_id: string | null
  /** The day crosses zones: every event must be labelled with its own zone. */
  crosses_tz: boolean
}

export interface TripStats {
  distance_by_mode_m?: Record<string, number>
  distance_total_m?: number
  /** Segments whose distance is genuinely unknown. Never folded in as zero. */
  distance_unknown_segments?: number
  place_count?: number
  track_count?: number
  photo_count?: number
  photo_only?: boolean
  inferred_dwell_count?: number
  timezones?: string[]
  collapsed?: boolean
}

export interface Place {
  id: string
  trip_id: string | null
  lat: number
  lon: number
  radius_m: number | null
  start_utc: string
  end_utc: string
  duration_s: number
  origin: 'track' | 'photo'
  /** Part of this dwell was deduced from a data gap, not measured. */
  is_inferred_dwell: boolean
  inferred_ratio: number
  tz_name: string | null
  name: string | null
  geo_name: string | null
  geo_city: string | null
  geo_country: string | null
  point_count: number
  source_kinds: SourceKind[]
  photo_count: number
}

export interface Track {
  id: string
  trip_id: string | null
  start_utc: string
  end_utc: string
  distance_m: number | null
  distance_unknown: boolean
  geom_quality: 'full' | 'endpoints_only'
  duration_s: number
  mode: TravelMode
  mode_source: string | null
  mode_confidence: number | null
  is_commute: boolean
  crosses_tz: boolean
  source_kind: SourceKind
}

export interface Photo {
  id: string
  trip_id: string | null
  place_id: string | null
  lat: number | null
  lon: number | null
  taken_at_utc: string | null
  taken_at_local: string | null
  tz_name: string | null
  tz_source: string | null
  location_confidence: 'measured' | 'inferred' | 'manual' | null
  /** Only the filename. Absolute paths never cross the HTTP boundary. */
  orig_filename: string | null
  width: number | null
  height: number | null
  camera_make: string | null
  camera_model: string | null
}

export interface Anchor {
  id: string
  lat: number
  lon: number
  kind: 'home' | 'work' | 'frequent' | 'other'
  kind_source: string | null
  visit_count: number
  total_duration_s: number
  weekday_ratio: number | null
  first_visit_utc: string | null
  last_visit_utc: string | null
  geo_name: string | null
  geo_city: string | null
  geo_country: string | null
  trip_count: number
  hour_histogram: number[]
}

export interface Group {
  id: string
  name: string
  kind: 'user' | 'system_commute'
  color: string | null
  trip_count: number
  /** Counted with the inheritance rule: a place with no group takes its trip's. */
  place_count: number
}

export interface Tag {
  id: string
  name: string
  color: string | null
  trip_count: number
  place_count: number
}

export interface SourceFile {
  id: string
  kind: SourceKind
  display_name: string
  status: string
  byte_size: number | null
  stats: Record<string, unknown>
  error_detail: Record<string, unknown> | null
  imported_at: string
  has_original: boolean
}

export interface TaskStage {
  key: string
  processed: number
  total: number | null
}

export interface TaskState {
  id: string
  kind: string
  display_name: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  stage: string | null
  /** Absolute count. Total is unknown while streaming, so no fake percentage. */
  processed: number
  total: number | null
  /** One entry per phase: the wizard draws three bars at once. */
  stages: TaskStage[]
  eta_seconds: number | null
  result: ImportReport | Record<string, never>
  error: { type: string; message: string } | null
  created_at?: string
  finished_at?: string | null
}

export interface ImportReport {
  source_file_id?: string | null
  kind?: string
  display_name?: string
  points?: number
  photos?: number
  duplicates?: number
  skipped?: Record<string, number>
  errors?: Array<Record<string, unknown>>
  trips_created?: number
  trips_updated?: number
  places?: number
  tracks?: number
  time_span?: { start: string | null; end: string | null }
  already_imported?: boolean
  /** Days spanning more than one zone. The trip was NOT split at the border. */
  tz_crossings?: number
  commute?: {
    detected: boolean
    reason: string | null
    workdays?: number
    required_workdays?: number
    ods?: number
  }
  updated_trip_ids?: string[]
  updated_trip_ids_truncated?: boolean
}

export interface ImportOptions {
  include_subdirs?: boolean
  infer_missing_gps?: boolean
  infer_tolerance_s?: number | null
  generate_thumbnails?: boolean
  skip_duplicates?: boolean
  date_range?: { start: string | null; end: string | null } | null
}

export interface PickResponse {
  pick_token: string
  /** The last path component only - never the absolute path. */
  display_name: string
  prescan: Prescan
}

export interface Prescan {
  file_count: number
  parsable_count?: number
  by_format?: Record<string, number>
  sampled?: number
  sample_readable?: number
  /** True when gps_ratio came from a sample - it must never be shown as exact. */
  gps_estimated?: boolean
  gps_ratio?: number
  gps_count_estimate?: number
  no_gps_count_estimate?: number
  include_subdirs?: boolean
  time_span?: { start: string | null; end: string | null }
  estimated_seconds?: number
  display_name?: string
  needs_confirmation?: boolean
  kind?: string
  variant?: string
  byte_size?: number
}

export interface Geofence {
  id: string
  kind: 'home' | 'work'
  label: string
  lat: number
  lon: number
  radius_m: number
  enabled: boolean
  visit_count: number | null
  first_visit_utc: string | null
  last_visit_utc: string | null
}

export type FenceConfidence = 'google_confirmed' | 'google_inferred' | 'heuristic'

export interface FenceSuggestion {
  kind: 'home' | 'work'
  confidence: FenceConfidence
  lat: number
  lon: number
  radius_m: number
  visit_count: number
  first_visit_utc: string | null
  last_visit_utc: string | null
  already_fenced: boolean
}

export interface FenceSuggestions {
  tiers: Record<FenceConfidence, FenceSuggestion[]>
  total: number
}

export interface FenceHit {
  fence_id: string
  label: string
  kind: string
  affected_places: number
  affected_tracks: number
}

export interface FenceCheck {
  intersects: boolean
  fences: FenceHit[]
  affected_places: number
  affected_tracks: number
}

export type FenceAction = 'blur' | 'remove'
export type Basemap = 'light' | 'dark' | 'terrain' | 'none'

export interface ExportContents {
  tracks: boolean
  places: boolean
  photos: boolean
  labels: boolean
  stats: boolean
}

export interface ExportRequest {
  trip_ids?: string[]
  place_ids?: string[]
  template?: 'map' | 'poster' | 'collage'
  width?: number
  height?: number
  theme?: 'light' | 'dark'
  basemap?: Basemap
  contents?: ExportContents
  coarsen_to_city?: boolean
  title?: string | null
  subtitle?: string | null
  /** A map is per fence. Either shape must cover every fence that is hit. */
  fence_actions?: FenceAction | Record<string, FenceAction> | null
}

export interface CommuteOD {
  id: string
  occurrence: number
  weekday_ratio: number | null
  depart_hour_mean: number | null
  depart_hour_circstd: number | null
  path_jaccard: number | null
  evidence: {
    sample_dates?: string[]
    median_distance_m?: number | null
    /** Known distances only; the unknown ones are counted, never summed as 0. */
    total_distance_m?: number | null
    distance_unknown_count?: number
    median_duration_s?: number
    first_seen?: string
    last_seen?: string
    anchor_is_home_or_work?: boolean
  }
  track_count: number
  from: { id: string; lat: number; lon: number; kind: string; label: string | null }
  to: { id: string; lat: number; lon: number; kind: string; label: string | null }
}

export interface CommuteTrip {
  id: string
  title: string
  local_date: string
  commute_class: CommuteClass
  place_count: number
  photo_count: number
  commute_track_count: number
  /** Only a pure commute day may be deleted whole. */
  deletable: boolean
}

export interface Stats {
  trip_count: number
  first_day: string | null
  last_day: string | null
  distance_by_mode: Array<{
    mode: TravelMode
    distance_m: number
    segments: number
    unknown_distance_segments: number
    duration_s: number
  }>
  distance_total_m: number
  unknown_distance_segments: number
  countries: number
  cities: number
  place_count: number
  inferred_dwell_count: number
  photos: { total: number; inferred_location: number; unlocated: number }
  activity: Array<{ day: string; places: number; distance_m: number }>
}

export interface OverviewRow {
  /** null is the "no place name" bucket - reported, never dropped. */
  key: string | null
  label: string | null
  country?: string | null
  city_count: number
  trip_count: number
  photo_count: number
  distance_m: number
  first_day: string | null
  last_day: string | null
}

export interface AppSettings {
  default_tz: string
  cluster_radius_m: number
  cluster_min_dwell_s: number
  cluster_gap_s: number
  accuracy_max_m: number
  photo_infer_tolerance_s: number
  geocoding_enabled: boolean
  commute_min_repeats: number
  display_local_time: boolean
  /** Read-only: the token lives in .env and never crosses this boundary. */
  mapbox_token_configured: boolean
  presets: Record<string, { cluster_radius_m: number; cluster_min_dwell_s: number }>
}

export interface SearchResults {
  places: Array<{
    id: string
    label: string | null
    lat: number
    lon: number
    city: string | null
    country: string | null
    trip_id: string | null
    start_utc: string
  }>
  trips: Array<{ id: string; title: string; local_date: string }>
}
