/**
 * Export panel with the blocking privacy-fence dialog.
 *
 * Flow, and the order matters: fence-check runs BEFORE any render. If the
 * selection touches a fence, the user must pick blur or remove before the
 * export or even the preview can proceed.
 *
 * This dialog is a convenience, not the enforcement. The server returns 422 for
 * an intersecting export with no fence_actions no matter what the UI does - a
 * dialog can be bypassed, the refusal cannot. The preview goes through exactly
 * the same check, because a preview is an image too.
 */

import { useState } from 'react'

import { api } from '@/api/client'
import { useCreateExport, useFenceCheck } from '@/api/hooks'
import type { FenceAction, FenceCheck } from '@/api/types'
import { t } from '@/i18n/zh'
import { useAppStore } from '@/store/appStore'

const SIZES: Array<{ label: string; width: number; height: number }> = [
  { label: '1080 × 1920', width: 1080, height: 1920 },
  { label: '1080 × 1080', width: 1080, height: 1080 },
  { label: '1920 × 1080', width: 1920, height: 1080 },
  { label: '2480 × 3508 (A4)', width: 2480, height: 3508 },
]

export default function ExportPanel() {
  const tripIds = useAppStore((state) => state.exportTripIds)
  const open = useAppStore((state) => state.exportOpen)
  const setOpen = useAppStore((state) => state.setExportOpen)

  const [template, setTemplate] = useState<'map' | 'poster' | 'collage'>('map')
  const [size, setSize] = useState(0)
  const [theme, setTheme] = useState<'light' | 'dark'>('light')
  const [fenceAction, setFenceAction] = useState<FenceAction | null>(null)
  const [check, setCheck] = useState<FenceCheck | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fenceCheck = useFenceCheck()
  const createExport = useCreateExport()

  if (!open) return null

  const chosen = SIZES[size] ?? SIZES[0]!
  const needsChoice = check?.intersects === true && fenceAction === null

  const runCheck = async (): Promise<FenceCheck> => {
    if (check) return check
    const result = await fenceCheck.mutateAsync({ trip_ids: tripIds })
    setCheck(result)
    return result
  }

  const doPreview = async () => {
    setError(null)
    setBusy(true)
    try {
      const result = await runCheck()
      if (result.intersects && fenceAction === null) return // the dialog takes over
      const url = await api.exportPreview({
        trip_ids: tripIds,
        template,
        theme,
        fence_actions: result.intersects ? fenceAction : null,
      })
      setPreview(url)
    } catch (caught) {
      setError(String((caught as { detail?: unknown }).detail ?? caught))
    } finally {
      setBusy(false)
    }
  }

  const doExport = async () => {
    setError(null)
    setBusy(true)
    try {
      const result = await runCheck()
      if (result.intersects && fenceAction === null) {
        setError(t.exportPanel.fenceRequired)
        return
      }
      const response = await createExport.mutateAsync({
        trip_ids: tripIds,
        template,
        width: chosen.width,
        height: chosen.height,
        theme,
        fence_actions: result.intersects ? fenceAction : null,
      })
      window.open(response.download_url, '_blank', 'noopener')
    } catch (caught) {
      setError(String((caught as { detail?: unknown }).detail ?? caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="backdrop" onClick={(event) => event.target === event.currentTarget && setOpen(false)}>
      <div className="dialog dialog--wide">
        <div className="row row--between">
          <h1>{t.exportPanel.title}</h1>
          <button className="ghost" onClick={() => setOpen(false)}>
            ✕
          </button>
        </div>

        {tripIds.length === 0 && <div className="notice">{t.exportPanel.nothingSelected}</div>}

        {/* Blocking choice. Nothing renders until the user decides. */}
        {needsChoice && check && (
          <div className="notice notice--danger">
            <h3>{t.exportPanel.fenceTitle}</h3>
            <p>
              {t.exportPanel.fenceBody(
                check.fences.length,
                check.affected_places,
                check.affected_tracks,
              )}
            </p>
            <button
              className="choice"
              aria-pressed={false}
              onClick={() => setFenceAction('blur')}
            >
              <div className="choice__title">{t.exportPanel.fenceBlur}</div>
              <div className="faint">{t.exportPanel.fenceBlurHelp}</div>
            </button>
            <button
              className="choice"
              aria-pressed={false}
              onClick={() => setFenceAction('remove')}
            >
              <div className="choice__title">{t.exportPanel.fenceRemove}</div>
              <div className="faint">{t.exportPanel.fenceRemoveHelp}</div>
            </button>
            <ul className="faint">
              {check.fences.map((fence) => (
                <li key={fence.fence_id}>
                  {fence.label} · {fence.affected_places} / {fence.affected_tracks}
                </li>
              ))}
            </ul>
          </div>
        )}

        {check?.intersects && fenceAction && (
          <div className="notice">
            🔒{' '}
            {fenceAction === 'blur' ? t.exportPanel.fenceBlur : t.exportPanel.fenceRemove}
            <button className="ghost" onClick={() => setFenceAction(null)}>
              {t.app.cancel}
            </button>
          </div>
        )}

        <div className="grid-2">
          <div>
            <div className="section">
              <div className="section__title">{t.exportPanel.template}</div>
              {(
                [
                  ['map', t.exportPanel.templateMap],
                  ['poster', t.exportPanel.templatePoster],
                  ['collage', t.exportPanel.templateCollage],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  className="choice"
                  aria-pressed={template === key}
                  onClick={() => setTemplate(key)}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="section">
              <div className="section__title">{t.exportPanel.size}</div>
              <select value={size} onChange={(event) => setSize(Number(event.target.value))}>
                {SIZES.map((option, index) => (
                  <option key={option.label} value={index}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="section">
              <div className="section__title">{t.exportPanel.theme}</div>
              <div className="row">
                <button
                  className={theme === 'light' ? 'primary' : ''}
                  onClick={() => setTheme('light')}
                >
                  {t.exportPanel.themeLight}
                </button>
                <button
                  className={theme === 'dark' ? 'primary' : ''}
                  onClick={() => setTheme('dark')}
                >
                  {t.exportPanel.themeDark}
                </button>
              </div>
            </div>

            <p className="faint">{t.exportPanel.attribution}</p>
          </div>

          <div>
            <div className="section__title">{t.exportPanel.preview}</div>
            <div
              style={{
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 8,
                minHeight: 280,
                display: 'grid',
                placeItems: 'center',
                overflow: 'hidden',
              }}
            >
              {preview ? (
                <img src={preview} alt="" style={{ maxWidth: '100%', maxHeight: 420 }} />
              ) : (
                <span className="faint">{busy ? t.exportPanel.previewing : '—'}</span>
              )}
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              <button onClick={doPreview} disabled={busy || tripIds.length === 0}>
                {t.exportPanel.preview}
              </button>
              <button
                className="primary"
                onClick={doExport}
                disabled={busy || tripIds.length === 0 || needsChoice}
              >
                {busy ? t.exportPanel.exporting : t.exportPanel.download}
              </button>
            </div>
            {error && <p style={{ color: 'var(--danger)' }}>{error}</p>}
          </div>
        </div>
      </div>
    </div>
  )
}
