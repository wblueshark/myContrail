/** TanStack Query bindings. Server state only - UI state lives in the store. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type TripQuery } from './client'
import type { AppSettings, ExportRequest, Trip } from './types'

export const keys = {
  capabilities: ['capabilities'] as const,
  trips: (params?: TripQuery) => ['trips', params ?? {}] as const,
  trip: (id: string) => ['trip', id] as const,
  places: (params?: Record<string, unknown>) => ['places', params ?? {}] as const,
  tracks: (params?: Record<string, unknown>) => ['tracks', params ?? {}] as const,
  photos: (params?: Record<string, unknown>) => ['photos', params ?? {}] as const,
  anchors: (params?: Record<string, unknown>) => ['anchors', params ?? {}] as const,
  overviewCountries: ['overview', 'countries'] as const,
  overviewCities: (country?: string | null) => ['overview', 'cities', country ?? 'all'] as const,
  groups: ['groups'] as const,
  tags: ['tags'] as const,
  sources: ['sources'] as const,
  imports: ['imports'] as const,
  settings: ['settings'] as const,
  geofences: ['geofences'] as const,
  fenceSuggestions: ['geofences', 'suggestions'] as const,
  commuteOds: ['commute', 'ods'] as const,
  commuteTrips: (cls?: string) => ['commute', 'trips', cls ?? 'all'] as const,
  stats: (params?: Record<string, unknown>) => ['stats', params ?? {}] as const,
  search: (q: string) => ['search', q] as const,
}

export const useCapabilities = () =>
  useQuery({ queryKey: keys.capabilities, queryFn: api.capabilities, staleTime: Infinity })

export const useTrips = (params?: TripQuery) =>
  useQuery({ queryKey: keys.trips(params), queryFn: () => api.trips(params) })

export const useTrip = (id: string | null) =>
  useQuery({ queryKey: keys.trip(id ?? ''), queryFn: () => api.trip(id!), enabled: Boolean(id) })

export const usePlaces = (params?: Record<string, unknown>) =>
  useQuery({ queryKey: keys.places(params), queryFn: () => api.places(params) })

export const useTracks = (params?: Record<string, unknown>) =>
  useQuery({ queryKey: keys.tracks(params), queryFn: () => api.tracks(params) })

export const usePhotos = (params?: Record<string, unknown>, enabled = true) =>
  useQuery({ queryKey: keys.photos(params), queryFn: () => api.photos(params), enabled })

export const useAnchors = (params?: Parameters<typeof api.anchors>[0]) =>
  useQuery({ queryKey: keys.anchors(params), queryFn: () => api.anchors(params) })

/** Overview aggregates. Full-corpus figures: deliberately no time window. */
export const useOverviewCountries = () =>
  useQuery({ queryKey: keys.overviewCountries, queryFn: api.overviewCountries })

export const useOverviewCities = (country?: string | null) =>
  useQuery({
    queryKey: keys.overviewCities(country),
    queryFn: () => api.overviewCities(country ? { country } : undefined),
  })
export const useGroups = () => useQuery({ queryKey: keys.groups, queryFn: api.groups })
export const useTags = () => useQuery({ queryKey: keys.tags, queryFn: api.tags })
export const useSources = () => useQuery({ queryKey: keys.sources, queryFn: api.listSources })
export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: api.settings })
export const useGeofences = () => useQuery({ queryKey: keys.geofences, queryFn: api.geofences })

export const useFenceSuggestions = () =>
  useQuery({ queryKey: keys.fenceSuggestions, queryFn: api.fenceSuggestions })

export const useCommuteOds = () => useQuery({ queryKey: keys.commuteOds, queryFn: api.commuteOds })

export const useCommuteTrips = (cls?: string) =>
  useQuery({
    queryKey: keys.commuteTrips(cls),
    queryFn: () => api.commuteTrips(cls ? { class: cls } : undefined),
  })

export const useStats = (params?: { from?: string; to?: string; group?: string }) =>
  useQuery({ queryKey: keys.stats(params), queryFn: () => api.stats(params) })

export const useSearch = (q: string) =>
  useQuery({
    queryKey: keys.search(q),
    queryFn: () => api.search(q),
    enabled: q.trim().length > 0,
  })

/** Anything that changes derived data invalidates the whole derived surface. */
function invalidateDerived(client: ReturnType<typeof useQueryClient>) {
  for (const key of ['trips', 'trip', 'places', 'photos', 'anchors', 'stats', 'commute']) {
    void client.invalidateQueries({ queryKey: [key] })
  }
}

export function usePatchTrip() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Parameters<typeof api.patchTrip>[1]) =>
      api.patchTrip(id, body),
    onSuccess: (_data, variables) => {
      void client.invalidateQueries({ queryKey: keys.trip(variables.id) })
      void client.invalidateQueries({ queryKey: ['trips'] })
    },
  })
}

export function useCreateGroup() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.createGroup,
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.groups }),
  })
}

export function useUpdateGroup() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name: string; color?: string | null }) =>
      api.updateGroup(id, body),
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.groups }),
  })
}

export function useUpdateTag() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name: string; color?: string | null }) =>
      api.updateTag(id, body),
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.tags }),
  })
}

export function useDeleteGroup() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.deleteGroup,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.groups })
      void client.invalidateQueries({ queryKey: ['trips'] })
    },
  })
}

export function useCreateTag() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.createTag,
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.tags }),
  })
}

export function useDeleteTag() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.deleteTag,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.tags })
      void client.invalidateQueries({ queryKey: ['trips'] })
    },
  })
}

export function useDeleteSource() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.deleteSource,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.sources })
      invalidateDerived(client)
    },
  })
}

export function useSaveSettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<AppSettings>) => api.saveSettings(body),
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.settings }),
  })
}

export function useRecluster() {
  const client = useQueryClient()
  return useMutation({ mutationFn: api.recluster, onSuccess: () => invalidateDerived(client) })
}

export function useCreateFence() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.createFence,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.geofences })
      void client.invalidateQueries({ queryKey: keys.fenceSuggestions })
    },
  })
}

export function useUpdateFence() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Parameters<typeof api.updateFence>[1]) =>
      api.updateFence(id, body),
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.geofences }),
  })
}

export function useDeleteFence() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.deleteFence,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.geofences })
      void client.invalidateQueries({ queryKey: keys.fenceSuggestions })
    },
  })
}

export function useCommuteAction() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.commuteAction,
    onSuccess: () => invalidateDerived(client),
  })
}

export function useRecomputeCommute() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.recomputeCommute,
    onSuccess: () => invalidateDerived(client),
  })
}

export function useBulkAssign() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      trip_ids?: string[]
      place_ids?: string[]
      group_id?: string | null
      add_tags?: string[]
      remove_tags?: string[]
    }) => {
      const { place_ids, trip_ids, ...rest } = body
      return place_ids?.length
        ? api.bulkAssignPlaces({ place_ids, ...rest })
        : api.bulkAssignTrips({ trip_ids: trip_ids ?? [], ...rest })
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.groups })
      void client.invalidateQueries({ queryKey: keys.tags })
      invalidateDerived(client)
    },
  })
}

export function useCreateImport() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.createImport,
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.imports }),
  })
}

export function useImports(enabled = true) {
  return useQuery({
    queryKey: keys.imports,
    queryFn: api.listImports,
    enabled,
    // A running import is the one thing here that changes without the user.
    refetchInterval: enabled ? 1200 : false,
  })
}

export function useFenceCheck() {
  return useMutation({ mutationFn: api.fenceCheck })
}

export function useCreateExport() {
  return useMutation({ mutationFn: (body: ExportRequest) => api.createExport(body) })
}

export function tripById(trips: Trip[] | undefined, id: string): Trip | undefined {
  return trips?.find((trip) => trip.id === id)
}
