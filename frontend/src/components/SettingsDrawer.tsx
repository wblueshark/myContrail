/**
 * Settings, as a right-hand drawer over whatever page is open.
 *
 * Three things this panel must not misrepresent:
 *   * fences apply ON EXPORT. The in-app map shows real data, and the note says
 *     so rather than implying the map is already redacted.
 *   * the Mapbox token is read-only here. It lives in .env; accepting it in the
 *     UI would mean storing a secret, masking it, and keeping it out of logs -
 *     all to save one file edit on a single-user machine.
 *   * re-clustering is a rebuild, so it asks first and states what survives:
 *     the raw points, always.
 */

import { Building2, Home, Lock, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  useDeleteFence,
  useGeofences,
  useRecluster,
  useRecomputeCommute,
  useSaveSettings,
  useSettings,
  useUpdateFence,
} from '@/api/hooks'
import type { Geofence } from '@/api/types'
import Blueprint from '@/components/Blueprint'
import { LOCALES, useCopy, useLocaleStore } from '@/i18n'
import { useAppStore } from '@/store/appStore'

interface Slider {
  key: 'cluster_radius_m' | 'cluster_min_dwell_s' | 'cluster_gap_s' | 'commute_min_repeats'
  label: string
  min: number
  max: number
  step: number
  /** Display scale: minutes are stored as seconds. */
  divisor: number
  unit: string
}

export default function SettingsDrawer() {
  const t = useCopy()
  const open = useAppStore((state) => state.settingsOpen)
  const setOpen = useAppStore((state) => state.setSettingsOpen)
  const theme = useAppStore((state) => state.theme)
  const setTheme = useAppStore((state) => state.setTheme)
  const startGuide = useAppStore((state) => state.startGuide)
  const navigate = useAppStore((state) => state.navigate)
  const locale = useLocaleStore((state) => state.locale)
  const setLocale = useLocaleStore((state) => state.setLocale)

  const settings = useSettings()
  const save = useSaveSettings()
  const fences = useGeofences()
  const updateFence = useUpdateFence()
  const deleteFence = useDeleteFence()
  const recluster = useRecluster()
  const recomputeCommute = useRecomputeCommute()

  const [draft, setDraft] = useState<Record<string, number>>({})
  const [pendingDelete, setPendingDelete] = useState<Geofence | null>(null)
  const [confirmRecluster, setConfirmRecluster] = useState(false)

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [setOpen])

  if (!open) return null

  const sliders: Slider[] = [
    {
      key: 'cluster_radius_m',
      label: t.settings.radius,
      min: 40,
      max: 400,
      step: 10,
      divisor: 1,
      unit: t.settings.meters,
    },
    {
      key: 'cluster_min_dwell_s',
      label: t.settings.minDwell,
      min: 3,
      max: 60,
      step: 1,
      divisor: 60,
      unit: t.settings.minutes,
    },
    {
      key: 'cluster_gap_s',
      label: t.settings.gap,
      min: 10,
      max: 180,
      step: 5,
      divisor: 60,
      unit: t.settings.minutes,
    },
    {
      key: 'commute_min_repeats',
      label: t.settings.commuteRepeats,
      min: 3,
      max: 60,
      step: 1,
      divisor: 1,
      unit: t.settings.times,
    },
  ]

  const valueOf = (slider: Slider): number => {
    const stored = settings.data?.[slider.key] ?? 0
    return draft[slider.key] ?? Math.round(stored / slider.divisor)
  }
  const dirty = Object.keys(draft).length > 0

  const commit = async () => {
    const body: Record<string, number> = {}
    for (const slider of sliders) {
      const value = draft[slider.key]
      if (value !== undefined) body[slider.key] = value * slider.divisor
    }
    if (Object.keys(body).length) await save.mutateAsync(body)
    setDraft({})
  }

  return (
    <>
      <div className="drawer-backdrop" onClick={() => setOpen(false)} />
      <aside className="drawer">
        <div className="drawer__head">
          <span
            style={{
              fontFamily: 'var(--font-heading)',
              fontSize: 16,
              letterSpacing: '.08em',
              textTransform: 'uppercase',
            }}
          >
            {t.settings.title}
          </span>
          <button
            className="btn btn-ghost btn-icon"
            style={{ marginLeft: 'auto' }}
            onClick={() => setOpen(false)}
          >
            <X size={16} strokeWidth={1.5} />
          </button>
        </div>

        <div className="drawer__body">
          <div className="drawer__section">{t.settings.fences}</div>
          {(fences.data ?? []).map((fence) => (
            <Blueprint key={fence.id} style={{ padding: '10px 11px', marginBottom: 9 }}>
              <div className="row" style={{ gap: 10 }}>
                {fence.kind === 'home' ? (
                  <Home size={17} strokeWidth={1.5} />
                ) : (
                  <Building2 size={17} strokeWidth={1.5} />
                )}
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13 }}>{fence.label}</div>
                  <div className="muted" style={{ fontSize: 11 }}>
                    {fence.visit_count
                      ? t.fences.visitSummary(
                          fence.visit_count,
                          fence.first_visit_utc?.slice(0, 7) ?? '—',
                          fence.last_visit_utc?.slice(0, 7) ?? '—',
                        )
                      : ''}
                  </div>
                </div>
                <span className="tag tag-accent">{Math.round(fence.radius_m)} m</span>
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
                {/* The comp has no delete control; without one a mis-added fence
                    is permanent. */}
                <button
                  className="btn btn-ghost btn-icon"
                  title={t.app.delete}
                  onClick={() => setPendingDelete(fence)}
                >
                  <Trash2 size={14} strokeWidth={1.5} />
                </button>
              </div>
            </Blueprint>
          ))}
          {fences.isSuccess && fences.data.length === 0 && (
            <p className="muted" style={{ fontSize: 12 }}>
              {t.fences.empty}
            </p>
          )}
          <p className="muted" style={{ fontSize: 11, lineHeight: 1.6, marginTop: 8 }}>
            {t.fences.sideNote}
          </p>

          <hr className="hr" />
          <div className="drawer__section">{t.settings.clustering}</div>
          {sliders.map((slider) => (
            <div key={slider.key} style={{ marginBottom: 12 }}>
              <div className="row row--between" style={{ fontSize: 12.5, marginBottom: 4 }}>
                <span>{slider.label}</span>
                <span className="num" style={{ color: 'var(--color-accent)' }}>
                  {valueOf(slider)} {slider.unit}
                </span>
              </div>
              <input
                type="range"
                min={slider.min}
                max={slider.max}
                step={slider.step}
                value={valueOf(slider)}
                style={{ width: '100%' }}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, [slider.key]: Number(event.target.value) }))
                }
              />
            </div>
          ))}
          {dirty && <div className="notice notice--accent">{t.settings.dirty}</div>}
          <div className="row" style={{ gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setConfirmRecluster(true)}
              disabled={recluster.isPending}
            >
              {t.settings.recluster}
            </button>
            <button
              className="btn btn-secondary btn-sm"
              onClick={async () => {
                await commit()
                await recomputeCommute.mutateAsync()
              }}
            >
              {t.settings.recomputeCommute}
            </button>
          </div>
          <p className="muted" style={{ fontSize: 11, lineHeight: 1.6, marginTop: 8 }}>
            {t.settings.reclusterNote}
          </p>

          <hr className="hr" />
          <div className="drawer__section">{t.settings.map}</div>
          <div className="field" style={{ marginBottom: 12 }}>
            <label>{t.settings.token}</label>
            <div className="row">
              <span className={settings.data?.mapbox_token_configured ? 'tag tag-accent' : 'tag tag-neutral'}>
                {settings.data?.mapbox_token_configured
                  ? t.settings.tokenConfigured
                  : t.settings.tokenMissing}
              </span>
            </div>
            <p className="faint" style={{ fontSize: 11, marginTop: 6 }}>
              {t.settings.tokenHelp}
            </p>
          </div>
          <label className="check">
            <input
              type="checkbox"
              checked={settings.data?.geocoding_enabled ?? false}
              onChange={() =>
                save.mutate({ geocoding_enabled: !(settings.data?.geocoding_enabled ?? false) })
              }
            />
            {t.settings.geocoding}
          </label>
          <p className="faint" style={{ fontSize: 11, margin: '2px 0 8px 23px' }}>
            {t.settings.geocodingHelp}
          </p>
          <label className="check">
            <input
              type="checkbox"
              checked={settings.data?.display_local_time ?? true}
              onChange={() =>
                save.mutate({ display_local_time: !(settings.data?.display_local_time ?? true) })
              }
            />
            {t.settings.localTime}
          </label>

          <hr className="hr" />
          <div className="drawer__section">{t.settings.appearance}</div>
          <div className="row" style={{ gap: 10, marginBottom: 10 }}>
            <span style={{ fontSize: 12.5, width: 64 }}>{t.settings.language}</span>
            <div className="seg seg--block" style={{ flex: 1 }}>
              {LOCALES.map((option) => (
                <label key={option.id} className="seg-opt">
                  <input
                    type="radio"
                    name="lang2"
                    checked={locale === option.id}
                    onChange={() => setLocale(option.id)}
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </div>
          <div className="row" style={{ gap: 10 }}>
            <span style={{ fontSize: 12.5, width: 64 }}>{t.settings.theme}</span>
            <div className="seg seg--block" style={{ flex: 1 }}>
              <label className="seg-opt">
                <input
                  type="radio"
                  name="thm2"
                  checked={theme === 'light'}
                  onChange={() => setTheme('light')}
                />
                {t.theme.light}
              </label>
              <label className="seg-opt">
                <input
                  type="radio"
                  name="thm2"
                  checked={theme === 'dark'}
                  onChange={() => setTheme('dark')}
                />
                {t.theme.dark}
              </label>
            </div>
          </div>

          <hr className="hr" />
          <div className="row" style={{ opacity: 0.5, gap: 10 }}>
            <Lock size={14} strokeWidth={1.5} />
            <span style={{ fontSize: 12.5 }}>{t.settings.account}</span>
            <span className="tag tag-neutral" style={{ marginLeft: 'auto' }}>
              {t.settings.reserved}
            </span>
          </div>

          <button
            className="btn btn-ghost btn-sm"
            style={{ marginTop: 14 }}
            onClick={() => {
              setOpen(false)
              navigate({ name: 'map' })
              startGuide()
            }}
          >
            {t.settings.replayGuide}
          </button>
        </div>
      </aside>

      {pendingDelete && (
        <div className="backdrop" style={{ zIndex: 36 }} onClick={() => setPendingDelete(null)}>
          <div className="dialog" onClick={(event) => event.stopPropagation()}>
            <div className="dialog__head">
              <span className="dialog__title">{t.fences.deleteTitle}</span>
            </div>
            <div className="dialog__body">
              <p>{pendingDelete.label}</p>
              <p className="muted">{t.fences.deleteWarning}</p>
            </div>
            <div className="dialog__foot" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-secondary" onClick={() => setPendingDelete(null)}>
                {t.app.cancel}
              </button>
              <button
                className="btn btn-danger"
                onClick={async () => {
                  await deleteFence.mutateAsync(pendingDelete.id)
                  setPendingDelete(null)
                }}
              >
                {t.app.delete}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmRecluster && (
        <div className="backdrop" style={{ zIndex: 36 }} onClick={() => setConfirmRecluster(false)}>
          <div className="dialog" onClick={(event) => event.stopPropagation()}>
            <div className="dialog__head">
              <span className="dialog__title">{t.settings.reclusterTitle}</span>
            </div>
            <div className="dialog__body">
              <p>{t.settings.reclusterNote}</p>
              <p className="muted">{t.settings.reclusterAutoOnly}</p>
            </div>
            <div className="dialog__foot" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-secondary" onClick={() => setConfirmRecluster(false)}>
                {t.app.cancel}
              </button>
              <button
                className="btn btn-primary"
                onClick={async () => {
                  await commit()
                  await recluster.mutateAsync()
                  setConfirmRecluster(false)
                }}
              >
                {t.settings.recluster}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
