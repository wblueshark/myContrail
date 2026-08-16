/**
 * Settings: privacy fences, clustering parameters, geocoding, data export.
 *
 * The fence section leads, because it is a precondition of the product rather
 * than a feature. Suggestions arrive in three confidence tiers that are never
 * merged - a confirmed home and an inferred one were measured hundreds of
 * metres apart, and folding them together would leave one real address
 * unprotected.
 */

import { useState } from 'react'

import { api } from '@/api/client'
import {
  useCreateFence,
  useDeleteFence,
  useFenceSuggestions,
  useGeofences,
  useRecluster,
  useSaveSettings,
  useSettings,
  useUpdateFence,
} from '@/api/hooks'
import type { AppSettings, FenceConfidence, FenceSuggestion } from '@/api/types'
import { t } from '@/i18n/zh'

const TIERS: Array<{ key: FenceConfidence; label: string }> = [
  { key: 'google_confirmed', label: t.fences.tierConfirmed },
  { key: 'google_inferred', label: t.fences.tierInferred },
  { key: 'heuristic', label: t.fences.tierHeuristic },
]

function SuggestionRow({ suggestion }: { suggestion: FenceSuggestion }) {
  const createFence = useCreateFence()
  const label = suggestion.kind === 'home' ? t.fences.kindHome : t.fences.kindWork

  return (
    <div className="row row--between" style={{ padding: '6px 0' }}>
      <div>
        <strong>{label}</strong>
        <div className="faint">
          {t.fences.visitSummary(
            suggestion.visit_count,
            suggestion.first_visit_utc?.slice(0, 4) ?? '?',
            suggestion.last_visit_utc?.slice(0, 4) ?? '?',
          )}
        </div>
      </div>
      {suggestion.already_fenced ? (
        <span className="pill pill--ok">{t.fences.alreadyFenced}</span>
      ) : (
        <button
          onClick={() =>
            createFence.mutate({
              kind: suggestion.kind,
              label: `${label} ${suggestion.last_visit_utc?.slice(0, 4) ?? ''}`.trim(),
              lat: suggestion.lat,
              lon: suggestion.lon,
              radius_m: suggestion.radius_m,
            })
          }
        >
          {t.fences.addFence}
        </button>
      )}
    </div>
  )
}

export default function SettingsPage() {
  const settings = useSettings()
  const save = useSaveSettings()
  const recluster = useRecluster()
  const fences = useGeofences()
  const suggestions = useFenceSuggestions()
  const updateFence = useUpdateFence()
  const deleteFence = useDeleteFence()
  const [draft, setDraft] = useState<Record<string, number | boolean | string>>({})

  /** Draft value if the user has edited this field, otherwise the stored one. */
  const value = (key: keyof AppSettings): number =>
    (draft[key] ?? settings.data?.[key]) as number

  return (
    <div className="page">
      <h1>{t.settings.title}</h1>

      <div className="card">
        <h2>🔒 {t.settings.fences}</h2>
        <p className="muted">{t.fences.intro}</p>

        {fences.data && fences.data.length > 0 ? (
          <table>
            <tbody>
              {fences.data.map((fence) => (
                <tr key={fence.id}>
                  <td>
                    <strong>{fence.label}</strong>
                    <div className="faint">
                      {fence.kind === 'home' ? t.fences.kindHome : t.fences.kindWork} ·{' '}
                      {fence.radius_m} m
                      {fence.visit_count
                        ? ` · ${t.fences.visitSummary(
                            fence.visit_count,
                            fence.first_visit_utc?.slice(0, 4) ?? '?',
                            fence.last_visit_utc?.slice(0, 4) ?? '?',
                          )}`
                        : ''}
                    </div>
                  </td>
                  <td>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={fence.enabled}
                        onChange={() =>
                          updateFence.mutate({
                            id: fence.id,
                            kind: fence.kind,
                            label: fence.label,
                            lat: fence.lat,
                            lon: fence.lon,
                            radius_m: fence.radius_m,
                            enabled: !fence.enabled,
                          })
                        }
                      />
                      {t.fences.enabled}
                    </label>
                  </td>
                  <td>
                    <button className="danger" onClick={() => deleteFence.mutate(fence.id)}>
                      {t.app.delete}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="faint">{t.fences.empty}</p>
        )}

        <h3 style={{ marginTop: 16 }}>{t.fences.suggestions}</h3>
        <div className="notice">{t.fences.tierHelp}</div>
        {TIERS.map(({ key, label }) => {
          const items = suggestions.data?.tiers?.[key] ?? []
          if (!items.length) return null
          return (
            <div className="section" key={key}>
              <div className="section__title">{label}</div>
              {items.map((suggestion, index) => (
                <SuggestionRow key={`${key}-${index}`} suggestion={suggestion} />
              ))}
            </div>
          )
        })}
        <p className="faint">{t.fences.offlineNote}</p>
      </div>

      <div className="card">
        <h2>{t.settings.clustering}</h2>
        <div className="grid-2">
          <label>
            {t.settings.radius}
            <input
              type="number"
              value={value('cluster_radius_m') ?? 150}
              onChange={(event) =>
                setDraft((d) => ({ ...d, cluster_radius_m: Number(event.target.value) }))
              }
            />
          </label>
          <label>
            {t.settings.minDwell}
            <input
              type="number"
              value={value('cluster_min_dwell_s') ?? 900}
              onChange={(event) =>
                setDraft((d) => ({ ...d, cluster_min_dwell_s: Number(event.target.value) }))
              }
            />
          </label>
          <label>
            {t.settings.gap}
            <input
              type="number"
              value={value('cluster_gap_s') ?? 3600}
              onChange={(event) =>
                setDraft((d) => ({ ...d, cluster_gap_s: Number(event.target.value) }))
              }
            />
          </label>
          <label>
            {t.settings.accuracyMax}
            <input
              type="number"
              value={value('accuracy_max_m') ?? 500}
              onChange={(event) =>
                setDraft((d) => ({ ...d, accuracy_max_m: Number(event.target.value) }))
              }
            />
          </label>
        </div>

        <h4 style={{ marginTop: 12 }}>{t.settings.presets}</h4>
        <div className="row row--wrap">
          {Object.entries(settings.data?.presets ?? {}).map(([name, preset]) => (
            <button
              key={name}
              onClick={() =>
                setDraft((d) => ({
                  ...d,
                  cluster_radius_m: preset.cluster_radius_m,
                  cluster_min_dwell_s: preset.cluster_min_dwell_s,
                }))
              }
            >
              {name === 'city'
                ? t.settings.presetCity
                : name === 'long_drive'
                  ? t.settings.presetLongDrive
                  : name === 'hiking'
                    ? t.settings.presetHiking
                    : t.settings.presetCoarse}
            </button>
          ))}
        </div>

        <div className="row" style={{ marginTop: 12 }}>
          <button
            className="primary"
            disabled={Object.keys(draft).length === 0}
            onClick={() => save.mutate(draft as never, { onSuccess: () => setDraft({}) })}
          >
            {t.app.save}
          </button>
          <button onClick={() => recluster.mutate()} disabled={recluster.isPending}>
            {recluster.isPending ? t.app.loading : t.settings.recluster}
          </button>
        </div>
        <p className="faint">{t.settings.reclusterHelp}</p>
      </div>

      <div className="card">
        <h2>{t.settings.geocoding}</h2>
        <label className="check">
          <input
            type="radio"
            checked={settings.data?.geocoding_enabled === true}
            onChange={() => save.mutate({ geocoding_enabled: true } as never)}
          />
          {t.settings.geocodingOn}
        </label>
        <label className="check">
          <input
            type="radio"
            checked={settings.data?.geocoding_enabled === false}
            onChange={() => save.mutate({ geocoding_enabled: false } as never)}
          />
          {t.settings.geocodingOff}
        </label>
      </div>

      <div className="card">
        <h2>{t.settings.dataExport}</h2>
        <p className="faint">{t.settings.dataExportHelp}</p>
        <a href={api.dataExportUrl()} target="_blank" rel="noreferrer">
          <button>{t.settings.dataExport}</button>
        </a>
      </div>

      <div className="card">
        <h2>{t.settings.account}</h2>
        <p className="faint">{t.settings.accountReserved}</p>
      </div>
    </div>
  )
}
