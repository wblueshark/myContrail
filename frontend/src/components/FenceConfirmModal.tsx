/**
 * "Two places to confirm before you see the map."
 *
 * The three confidence tiers are rendered SEPARATELY and are never merged. In
 * real data a Google-confirmed Home and an inferred one sat 427 m apart - two
 * different addresses, with the inferred one holding more night-time hours.
 * Merged into a single suggestion, the user confirms one and leaves the other
 * completely exposed while believing they are safe (02 section 2).
 *
 * Defaults follow the same table: confirmed and inferred are pre-checked,
 * statistics are not.
 */

import { BarChart3, Building2, Check, Home, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { useCreateFence, useFenceSuggestions } from '@/api/hooks'
import type { FenceConfidence, FenceSuggestion } from '@/api/types'
import Blueprint from '@/components/Blueprint'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

const TIERS: Array<{ key: FenceConfidence; defaultOn: boolean }> = [
  { key: 'google_confirmed', defaultOn: true },
  { key: 'google_inferred', defaultOn: true },
  { key: 'heuristic', defaultOn: false },
]

function suggestionKey(suggestion: FenceSuggestion): string {
  return `${suggestion.confidence}:${suggestion.lat.toFixed(5)}:${suggestion.lon.toFixed(5)}`
}

export default function FenceConfirmModal() {
  const t = useCopy()
  const open = useAppStore((state) => state.fenceModalOpen)
  const markConfirmed = useAppStore((state) => state.markFencesConfirmed)
  const navigate = useAppStore((state) => state.navigate)
  const startGuide = useAppStore((state) => state.startGuide)

  const suggestions = useFenceSuggestions()
  const createFence = useCreateFence()
  const [adopted, setAdopted] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)

  if (!open) return null

  const tiers = suggestions.data?.tiers
  const isOn = (suggestion: FenceSuggestion, fallback: boolean) =>
    adopted[suggestionKey(suggestion)] ?? fallback

  const confirm = async () => {
    setBusy(true)
    try {
      for (const tier of TIERS) {
        for (const suggestion of tiers?.[tier.key] ?? []) {
          if (suggestion.already_fenced || !isOn(suggestion, tier.defaultOn)) continue
          await createFence.mutateAsync({
            kind: suggestion.kind,
            label: suggestion.kind === 'home' ? t.fences.kindHome : t.fences.kindWork,
            lat: suggestion.lat,
            lon: suggestion.lon,
            radius_m: suggestion.radius_m,
            enabled: true,
          })
        }
      }
      markConfirmed()
      navigate({ name: 'map' })
      startGuide()
    } finally {
      setBusy(false)
    }
  }

  const tierLabel: Record<FenceConfidence, string> = {
    google_confirmed: t.fences.tierConfirmed,
    google_inferred: t.fences.tierInferred,
    heuristic: t.fences.tierHeuristic,
  }
  const tierIcon: Record<FenceConfidence, JSX.Element> = {
    google_confirmed: <Check size={14} strokeWidth={1.6} color="var(--color-accent)" />,
    google_inferred: <TriangleAlert size={14} strokeWidth={1.6} color="var(--color-danger)" />,
    heuristic: <BarChart3 size={14} strokeWidth={1.5} />,
  }
  const total = suggestions.data?.total ?? 0

  return (
    <div className="backdrop" style={{ zIndex: 32 }}>
      <div className="dialog dialog--fence blueprint">
        <i className="corner tl" />
        <i className="corner tr" />
        <i className="corner bl" />
        <i className="corner br" />

        <div className="dialog__head">
          <Home size={19} strokeWidth={1.5} color="var(--color-accent)" />
          <span className="dialog__title">{t.fences.confirmTitle}</span>
        </div>

        <div className="dialog__body">
          <p style={{ fontSize: 13, lineHeight: 1.75, maxWidth: 640 }}>{t.fences.confirmBody}</p>

          {TIERS.map((tier) => {
            const items = tiers?.[tier.key] ?? []
            if (!items.length) return null
            const danger = tier.key === 'google_inferred'
            return (
              <div
                key={tier.key}
                style={{
                  border: `1px solid ${danger ? 'var(--color-danger)' : 'var(--color-divider)'}`,
                  marginTop: 12,
                }}
              >
                <div
                  className="row"
                  style={{
                    padding: '8px 12px',
                    borderBottom: `1px solid ${
                      danger ? 'var(--color-danger)' : 'var(--color-divider)'
                    }`,
                    fontSize: 12,
                    color: danger ? 'var(--color-danger)' : undefined,
                  }}
                >
                  {tierIcon[tier.key]}
                  {tierLabel[tier.key]}
                </div>
                {items.map((suggestion) => (
                  <div
                    key={suggestionKey(suggestion)}
                    className="row"
                    style={{ padding: '10px 12px', gap: 10 }}
                  >
                    {suggestion.kind === 'home' ? (
                      <Home size={17} strokeWidth={1.5} />
                    ) : (
                      <Building2 size={17} strokeWidth={1.5} />
                    )}
                    <span style={{ fontFamily: 'var(--font-heading)', fontSize: 16, width: 80 }}>
                      {suggestion.kind === 'home' ? t.fences.kindHome : t.fences.kindWork}
                    </span>
                    <span className="tag tag-neutral">{Math.round(suggestion.radius_m)} m</span>
                    <span className="muted" style={{ fontSize: 12 }}>
                      {t.fences.visitSummary(
                        suggestion.visit_count,
                        suggestion.first_visit_utc?.slice(0, 7) ?? '—',
                        suggestion.last_visit_utc?.slice(0, 7) ?? '—',
                      )}
                    </span>
                    <label className="check" style={{ marginLeft: 'auto' }}>
                      <input
                        type="checkbox"
                        disabled={suggestion.already_fenced}
                        checked={suggestion.already_fenced || isOn(suggestion, tier.defaultOn)}
                        onChange={(event) =>
                          setAdopted((current) => ({
                            ...current,
                            [suggestionKey(suggestion)]: event.target.checked,
                          }))
                        }
                      />
                      {suggestion.already_fenced
                        ? t.fences.alreadyFenced
                        : danger
                          ? t.fences.alsoProtect
                          : t.fences.adopt}
                    </label>
                  </div>
                ))}
              </div>
            )
          })}

          {/* The measured 427 m case, stated plainly: this is why the tiers are
              not merged into one tidy suggestion. */}
          <Blueprint style={{ marginTop: 12, padding: '11px 12px' }}>
            <span style={{ fontSize: 12, lineHeight: 1.65 }}>{t.fences.tierWarn}</span>
          </Blueprint>

          <p className="muted" style={{ marginTop: 16, fontSize: 12.5, lineHeight: 1.7 }}>
            {t.fences.when}
          </p>
        </div>

        <div className="dialog__foot" style={{ justifyContent: 'flex-end' }}>
          <button
            className="btn btn-secondary"
            onClick={() => {
              markConfirmed()
              navigate({ name: 'map' })
            }}
          >
            {t.fences.skip}
          </button>
          <button className="btn btn-primary" onClick={confirm} disabled={busy || total === 0}>
            {t.fences.ok} →
          </button>
        </div>
      </div>
    </div>
  )
}
