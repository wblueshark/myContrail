/**
 * Export: the blocking fence gate, then the panel.
 *
 * The gate is not a warning, it is a decision point. When the selection touches
 * a fence there is NO default treatment and the confirm button stays disabled
 * until one is picked (02 section 8, G-1). The server refuses the export the
 * same way, so this dialog is the explanation rather than the protection - a
 * dialog can be bypassed, the 422 cannot.
 */

import { Lock, TriangleAlert, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { api } from '@/api/client'
import { useCreateExport, useFenceCheck } from '@/api/hooks'
import type { Basemap, ExportContents, FenceAction, FenceCheck } from '@/api/types'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

const SIZES: Array<{ key: string; width: number; height: number }> = [
  { key: 'sizePhone', width: 1080, height: 1920 },
  { key: 'sizeSocial', width: 1080, height: 1350 },
  { key: 'sizeDesktop', width: 2560, height: 1440 },
  { key: 'sizeA4', width: 3508, height: 2480 },
]

export default function ExportFlow() {
  const t = useCopy()
  const open = useAppStore((state) => state.exportOpen)
  const setOpen = useAppStore((state) => state.setExportOpen)
  const tripIds = useAppStore((state) => state.exportTripIds)

  const fenceCheck = useFenceCheck()
  const createExport = useCreateExport()

  const [check, setCheck] = useState<FenceCheck | null>(null)
  const [action, setAction] = useState<FenceAction | null>(null)
  const [perFence, setPerFence] = useState<Record<string, FenceAction>>({})
  const [perFenceMode, setPerFenceMode] = useState(false)
  const [gateDone, setGateDone] = useState(false)

  const [template, setTemplate] = useState<'map' | 'poster' | 'collage'>('map')
  const [sizeIndex, setSizeIndex] = useState(0)
  const [basemap, setBasemap] = useState<Basemap>('light')
  const [contents, setContents] = useState<ExportContents>({
    tracks: true,
    places: true,
    photos: true,
    labels: false,
    stats: true,
  })
  const [applyFences, setApplyFences] = useState(true)
  const [coarsen, setCoarsen] = useState(false)
  const [title, setTitle] = useState('')
  const [subtitle, setSubtitle] = useState('')
  const [preview, setPreview] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Fence check runs as soon as the flow opens: whether the gate is needed at
  // all is a server answer, not a guess.
  useEffect(() => {
    if (!open || !tripIds.length) return
    setGateDone(false)
    setCheck(null)
    setAction(null)
    setPerFence({})
    fenceCheck
      .mutateAsync({ trip_ids: tripIds })
      .then((result) => {
        setCheck(result)
        if (!result.intersects) setGateDone(true)
      })
      .catch(() => setGateDone(true))
    // fenceCheck is a stable mutation object from the hook.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tripIds])

  const fenceActions = (): FenceAction | Record<string, FenceAction> | null => {
    if (!check?.intersects || !applyFences) return null
    return perFenceMode ? perFence : action
  }

  const body = () => ({
    trip_ids: tripIds,
    template,
    width: SIZES[sizeIndex]!.width,
    height: SIZES[sizeIndex]!.height,
    theme: basemap === 'dark' ? ('dark' as const) : ('light' as const),
    basemap,
    contents,
    coarsen_to_city: coarsen,
    title: title || null,
    subtitle: subtitle || null,
    fence_actions: fenceActions(),
  })

  const renderPreview = async () => {
    setBusy(true)
    setError(null)
    try {
      setPreview(await api.exportPreview(body()))
    } catch (caught) {
      setError(String((caught as { detail?: unknown }).detail ?? caught))
    } finally {
      setBusy(false)
    }
  }

  // Debounced: every toggle would otherwise fire a render request.
  useEffect(() => {
    if (!open || !gateDone || !tripIds.length) return
    const timer = window.setTimeout(() => void renderPreview(), 400)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, gateDone, template, sizeIndex, basemap, contents, coarsen, applyFences, action, perFence])

  if (!open) return null

  const close = () => {
    setOpen(false)
    setPreview(null)
  }

  const hits = check?.fences ?? []
  const gateReady = perFenceMode
    ? hits.every((hit) => perFence[hit.fence_id])
    : action !== null

  if (check?.intersects && !gateDone) {
    return (
      <div className="backdrop" style={{ zIndex: 34 }}>
        <div className="dialog blueprint">
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          <div className="dialog__head" style={{ borderColor: 'var(--color-danger)' }}>
            <TriangleAlert size={18} strokeWidth={1.6} color="var(--color-danger)" />
            <span className="dialog__title">{t.exportPanel.gateTitle}</span>
          </div>

          <div className="dialog__body">
            {hits.map((hit) => (
              <div key={hit.fence_id} className="row" style={{ gap: 10, fontSize: 13, padding: '3px 0' }}>
                <Lock size={16} strokeWidth={1.5} />
                <span style={{ width: 70 }}>{hit.label}</span>
                <span className="muted">
                  {t.exportPanel.gateCoverage(hit.affected_places, hit.affected_tracks)}
                </span>
                {perFenceMode && (
                  <span className="seg" style={{ marginLeft: 'auto' }}>
                    {(['blur', 'remove'] as FenceAction[]).map((option) => (
                      <label key={option} className="seg-opt">
                        <input
                          type="radio"
                          name={`fence-${hit.fence_id}`}
                          checked={perFence[hit.fence_id] === option}
                          onChange={() =>
                            setPerFence((current) => ({ ...current, [hit.fence_id]: option }))
                          }
                        />
                        {option === 'blur' ? t.exportPanel.gateBlur.split(' ')[0] : t.exportPanel.gateRemove.split(' ')[0]}
                      </label>
                    ))}
                  </span>
                )}
              </div>
            ))}

            <div style={{ fontFamily: 'var(--font-heading)', fontSize: 14, margin: '18px 0 10px' }}>
              {t.exportPanel.gateChoose}
            </div>

            {!perFenceMode && (
              <>
                {/* No default: neither option starts selected, and continuing is
                    impossible until the user answers. */}
                <label
                  className="radio"
                  style={{
                    alignItems: 'flex-start',
                    padding: '11px 12px',
                    border: '1px solid var(--color-divider)',
                    width: '100%',
                    marginBottom: 8,
                  }}
                >
                  <input
                    type="radio"
                    name="gate"
                    checked={action === 'blur'}
                    onChange={() => setAction('blur')}
                  />
                  <span className="dot" style={{ marginTop: 3 }} />
                  <span className="col" style={{ gap: 4 }}>
                    <span style={{ fontSize: 13.5 }}>{t.exportPanel.gateBlur}</span>
                    <span className="muted" style={{ fontSize: 12, lineHeight: 1.6 }}>
                      {t.exportPanel.gateBlurHelp}
                    </span>
                  </span>
                </label>
                <label
                  className="radio"
                  style={{
                    alignItems: 'flex-start',
                    padding: '11px 12px',
                    border: '1px solid var(--color-divider)',
                    width: '100%',
                  }}
                >
                  <input
                    type="radio"
                    name="gate"
                    checked={action === 'remove'}
                    onChange={() => setAction('remove')}
                  />
                  <span className="dot" style={{ marginTop: 3 }} />
                  <span className="col" style={{ gap: 4 }}>
                    <span style={{ fontSize: 13.5 }}>{t.exportPanel.gateRemove}</span>
                    <span className="muted" style={{ fontSize: 12, lineHeight: 1.6 }}>
                      {t.exportPanel.gateRemoveHelp}
                    </span>
                  </span>
                </label>
              </>
            )}

            <button
              className="btn btn-ghost btn-sm"
              style={{ marginTop: 10 }}
              onClick={() => setPerFenceMode((value) => !value)}
            >
              {t.exportPanel.gateEach} · {t.exportPanel.gatePerFence}
            </button>
          </div>

          <div className="dialog__foot">
            {!gateReady && (
              <span style={{ fontSize: 11.5, color: 'var(--color-danger)' }}>
                {t.exportPanel.gateNeed}
              </span>
            )}
            <div className="row" style={{ marginLeft: 'auto', gap: 8 }}>
              <button className="btn btn-secondary" onClick={close}>
                {t.app.cancel}
              </button>
              <button
                className="btn btn-primary"
                disabled={!gateReady}
                onClick={() => setGateDone(true)}
              >
                {t.exportPanel.gateGo} →
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const toggle = (key: keyof ExportContents) =>
    setContents((current) => ({ ...current, [key]: !current[key] }))

  return (
    <div className="backdrop" style={{ zIndex: 33 }}>
      <div className="dialog dialog--wide blueprint">
        <i className="corner tl" />
        <i className="corner tr" />
        <i className="corner bl" />
        <i className="corner br" />

        <div className="dialog__head">
          <span className="dialog__title">{t.exportPanel.title}</span>
          <span className="tag tag-accent">
            {t.exportPanel.scope} · {t.exportPanel.scopeValue(tripIds.length)}
          </span>
          <button className="btn btn-ghost btn-icon" style={{ marginLeft: 'auto' }} onClick={close}>
            <X size={15} strokeWidth={1.5} />
          </button>
        </div>

        <div className="export">
          <div className="export__form">
            {tripIds.length === 0 && (
              <div className="notice" style={{ marginBottom: 12 }}>
                {t.exportPanel.nothingSelected}
              </div>
            )}

            <div className="kicker" style={{ marginBottom: 8 }}>
              {t.exportPanel.template}
            </div>
            {(
              [
                ['map', t.exportPanel.templateMap],
                ['poster', t.exportPanel.templatePoster],
                ['collage', t.exportPanel.templateCollage],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="radio" style={{ display: 'flex', padding: '4px 0' }}>
                <input
                  type="radio"
                  name="etpl"
                  checked={template === key}
                  onChange={() => setTemplate(key)}
                />
                <span className="dot" />
                {label}
              </label>
            ))}

            <div className="kicker" style={{ margin: '18px 0 8px' }}>
              {t.exportPanel.size}
            </div>
            <select
              className="input"
              value={sizeIndex}
              onChange={(event) => setSizeIndex(Number(event.target.value))}
            >
              {SIZES.map((size, index) => (
                <option key={size.key} value={index}>
                  {size.width}×{size.height} · {t.exportPanel[size.key as keyof typeof t.exportPanel] as string}
                </option>
              ))}
            </select>

            <div className="kicker" style={{ margin: '18px 0 8px' }}>
              {t.exportPanel.basemap}
            </div>
            {(
              [
                ['light', t.exportPanel.basemapLight],
                ['dark', t.exportPanel.basemapDark],
                ['terrain', t.exportPanel.basemapTerrain],
                ['none', t.exportPanel.basemapNone],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="radio" style={{ display: 'flex', padding: '4px 0' }}>
                <input
                  type="radio"
                  name="ebase"
                  checked={basemap === key}
                  onChange={() => setBasemap(key)}
                />
                <span className="dot" />
                {label}
              </label>
            ))}

            <div className="kicker" style={{ margin: '18px 0 8px' }}>
              {t.exportPanel.contents}
            </div>
            {(
              [
                ['tracks', t.exportPanel.cTracks],
                ['places', t.exportPanel.cPlaces],
                ['photos', t.exportPanel.cPhotos],
                ['labels', t.exportPanel.cLabels],
                ['stats', t.exportPanel.cStats],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="check">
                <input type="checkbox" checked={contents[key]} onChange={() => toggle(key)} />
                {label}
              </label>
            ))}
            {contents.photos && (
              <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>
                {t.exportPanel.photoWarning}
              </div>
            )}

            <div
              className="kicker"
              style={{ margin: '18px 0 8px', color: 'var(--color-danger)', display: 'flex', gap: 7 }}
            >
              <Lock size={13} strokeWidth={1.5} />
              {t.exportPanel.privacy}
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={applyFences}
                onChange={() => setApplyFences((value) => !value)}
              />
              {t.exportPanel.applyFences}
            </label>
            <label className="check">
              <input type="checkbox" checked={coarsen} onChange={() => setCoarsen((v) => !v)} />
              {t.exportPanel.coarsen}
            </label>

            <div className="kicker" style={{ margin: '18px 0 8px' }}>
              {t.exportPanel.heading}
            </div>
            <input
              className="input"
              style={{ marginBottom: 8 }}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
            <input
              className="input"
              placeholder={t.exportPanel.subtitle}
              value={subtitle}
              onChange={(event) => setSubtitle(event.target.value)}
            />
            {/* Not a preference: the basemap licence requires it. */}
            <div className="faint" style={{ fontSize: 11, marginTop: 12 }}>
              {t.exportPanel.credit}
            </div>
          </div>

          <div className="export__preview">
            <div className="kicker">{t.exportPanel.preview}</div>
            <div className="blueprint export__frame">
              <i className="corner tl" />
              <i className="corner tr" />
              <i className="corner bl" />
              <i className="corner br" />
              {busy && <span className="muted">{t.exportPanel.previewing}</span>}
              {!busy && preview && <img src={preview} alt="" />}
              {!busy && !preview && <span className="muted">{t.app.empty}</span>}
            </div>
            {error && <div className="notice notice--danger">{error}</div>}
          </div>
        </div>

        <div className="dialog__foot" style={{ justifyContent: 'flex-end' }}>
          <button className="btn btn-secondary" onClick={close}>
            {t.app.cancel}
          </button>
          <button
            className="btn btn-primary"
            disabled={busy || !tripIds.length}
            onClick={async () => {
              setBusy(true)
              setError(null)
              try {
                const result = await createExport.mutateAsync(body())
                window.open(result.download_url, '_blank', 'noopener')
              } catch (caught) {
                setError(String((caught as { detail?: unknown }).detail ?? caught))
              } finally {
                setBusy(false)
              }
            }}
          >
            {busy ? t.exportPanel.exporting : t.exportPanel.download} ↓
          </button>
        </div>
      </div>
    </div>
  )
}
