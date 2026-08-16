/**
 * The five-step import wizard, reachable from anywhere.
 *
 * Non-negotiables it has to hold:
 *   * no filesystem path ever enters a request. The folder is chosen by the OS
 *     picker and referenced by a one-shot pick_token; only the last path
 *     component is ever displayed.
 *   * with no native picker (`capabilities.directory_picker === null`) the photo
 *     card is not rendered at all. There is no fallback text field - that would
 *     put a path back into the request body.
 *   * the pre-scan's GPS figure is a SAMPLE. It is labelled as an estimate
 *     rather than printed as a count.
 *   * "pause" does not exist: the task layer has no resumable checkpoint, so the
 *     control is Cancel, and the original files make a re-run cheap.
 */

import { Camera, Folder, Map as MapIcon, PencilLine, X, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'

import { api } from '@/api/client'
import { useCapabilities, useCreateImport, useGroups, useImports, useTags } from '@/api/hooks'
import type { ImportReport, Prescan, TaskState } from '@/api/types'
import Blueprint from '@/components/Blueprint'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

type Source = 'photo' | 'google' | 'sport'

const STEPS = 5

export default function ImportWizard() {
  const t = useCopy()
  const open = useAppStore((state) => state.importOpen)
  const setOpen = useAppStore((state) => state.setImportOpen)
  const setFenceModalOpen = useAppStore((state) => state.setFenceModalOpen)
  const navigate = useAppStore((state) => state.navigate)

  const capabilities = useCapabilities()
  const groups = useGroups()
  const tags = useTags()
  const createImport = useCreateImport()

  const [step, setStep] = useState(1)
  const [source, setSource] = useState<Source>('photo')
  const [groupId, setGroupId] = useState<string | null>(null)
  const [tagIds, setTagIds] = useState<string[]>([])
  const [pickToken, setPickToken] = useState<string | null>(null)
  const [uploadId, setUploadId] = useState<string | null>(null)
  const [displayName, setDisplayName] = useState('')
  const [prescan, setPrescan] = useState<Prescan | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [includeSubdirs, setIncludeSubdirs] = useState(true)
  const [inferGps, setInferGps] = useState(true)
  const [thumbnails, setThumbnails] = useState(true)
  const [skipDuplicates, setSkipDuplicates] = useState(true)
  const [rangeOn, setRangeOn] = useState(false)
  const [rangeStart, setRangeStart] = useState('')
  const [rangeEnd, setRangeEnd] = useState('')

  const tasks = useImports(step === 4)
  const task: TaskState | undefined = tasks.data?.find((entry) => entry.id === taskId)
  const report = (task?.result ?? {}) as ImportReport

  useEffect(() => {
    if (task?.status === 'done') setStep(5)
    if (task?.status === 'failed') setError(task.error?.message ?? t.sources.failed)
  }, [task?.status, task?.error?.message, t.sources.failed])

  if (!open) return null

  const reset = () => {
    setStep(1)
    setPickToken(null)
    setUploadId(null)
    setPrescan(null)
    setTaskId(null)
    setError(null)
  }

  const pickFolder = async () => {
    setBusy(true)
    setError(null)
    try {
      const picked = await api.pickDirectory()
      if (!picked) return // the user cancelled the OS dialog
      setPickToken(picked.pick_token)
      setDisplayName(picked.display_name)
      setPrescan(picked.prescan)
    } catch (caught) {
      setError(String((caught as { detail?: unknown }).detail ?? caught))
    } finally {
      setBusy(false)
    }
  }

  const rescan = async (subdirs: boolean) => {
    setIncludeSubdirs(subdirs)
    if (!pickToken) return
    setBusy(true)
    try {
      setPrescan(await api.prescan({ pick_token: pickToken, include_subdirs: subdirs }))
    } finally {
      setBusy(false)
    }
  }

  const upload = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      const result = await api.upload(file)
      setUploadId(result.upload_id)
      setDisplayName(result.display_name)
      setPrescan(await api.prescan({ upload_id: result.upload_id }))
    } catch (caught) {
      setError(String((caught as { detail?: unknown }).detail ?? caught))
    } finally {
      setBusy(false)
    }
  }

  const start = async () => {
    const ref = source === 'photo' ? pickToken : uploadId
    if (!ref) return
    if (
      prescan?.needs_confirmation &&
      !window.confirm(
        t.importWizard.largeWarning(
          prescan.file_count,
          Math.max(1, Math.round((prescan.estimated_seconds ?? 0) / 60)),
        ),
      )
    ) {
      return
    }
    setBusy(true)
    setError(null)
    try {
      const state = await createImport.mutateAsync({
        source_ref: ref,
        kind: source === 'photo' ? 'photo' : 'file',
        group_id: groupId,
        tag_ids: tagIds,
        options: {
          include_subdirs: includeSubdirs,
          infer_missing_gps: inferGps,
          generate_thumbnails: thumbnails,
          skip_duplicates: skipDuplicates,
          date_range:
            rangeOn && (rangeStart || rangeEnd)
              ? { start: rangeStart || null, end: rangeEnd || null }
              : null,
        },
      })
      setTaskId(state.id)
      setStep(4)
    } catch (caught) {
      setError(String((caught as { detail?: unknown }).detail ?? caught))
    } finally {
      setBusy(false)
    }
  }

  const pickerAvailable = capabilities.data?.directory_picker !== null
  const canNext = step === 1 || step === 2
  const canStart = step === 3 && Boolean(source === 'photo' ? pickToken : uploadId)
  const stageCount = (key: string) => task?.stages.find((stage) => stage.key === key)

  const bar = (key: string, label: string) => {
    const stage = stageCount(key)
    const total = stage?.total ?? null
    const pct = stage && total ? Math.min(100, (stage.processed / total) * 100) : 0
    return (
      <div className="row" style={{ gap: 12, marginBottom: 10 }}>
        <span style={{ width: 120, fontSize: 12.5 }}>{label}</span>
        <div style={{ flex: 1, height: 8, border: '1px solid var(--color-divider)' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: 'var(--color-accent)' }} />
        </div>
        {/* Absolute counts: the total is unknown while streaming, and a made-up
            percentage would be worse than no percentage. */}
        <span className="num" style={{ width: 120, textAlign: 'right', fontSize: 12 }}>
          {stage ? t.sources.progress(stage.processed, total) : '—'}
        </span>
      </div>
    )
  }

  return (
    <div className="backdrop" style={{ zIndex: 30 }}>
      <div className="dialog dialog--import blueprint">
        <i className="corner tl" />
        <i className="corner tr" />
        <i className="corner bl" />
        <i className="corner br" />

        <div className="dialog__head">
          <span className="dialog__title">{t.importWizard.title}</span>
          <span className="tag tag-neutral">
            {capabilities.data?.mode.toUpperCase() ?? t.importWizard.localMode}
          </span>
          <span className="num muted" style={{ marginLeft: 'auto', fontSize: 12 }}>
            {t.importWizard.step(step, STEPS)}
          </span>
          <button
            className="btn btn-ghost btn-icon"
            onClick={() => {
              setOpen(false)
              reset()
            }}
          >
            <X size={15} strokeWidth={1.5} />
          </button>
        </div>

        <div className="dialog__body">
          {error && <div className="notice notice--danger" style={{ marginBottom: 12 }}>{error}</div>}

          {step === 1 && (
            <>
              <div className="kicker" style={{ marginBottom: 14 }}>
                {t.importWizard.s1}
              </div>
              <div className="grid">
                {pickerAvailable && (
                  <button
                    className="card--link"
                    style={{ borderColor: source === 'photo' ? 'var(--color-accent)' : undefined }}
                    onClick={() => setSource('photo')}
                  >
                    <Camera size={26} strokeWidth={1.4} />
                    <span style={{ fontFamily: 'var(--font-heading)', fontSize: 19 }}>
                      {t.importWizard.photo}
                    </span>
                    <span className="muted" style={{ fontSize: 12 }}>
                      {t.importWizard.photoDesc}
                    </span>
                    <span style={{ fontSize: 11.5, color: 'var(--color-accent)' }}>
                      {t.importWizard.photoPro}
                    </span>
                    <span className="faint" style={{ fontSize: 11.5 }}>
                      {t.importWizard.photoHow}
                    </span>
                  </button>
                )}
                <button
                  className="card--link"
                  style={{ borderColor: source === 'google' ? 'var(--color-accent)' : undefined }}
                  onClick={() => setSource('google')}
                >
                  <MapIcon size={26} strokeWidth={1.4} />
                  <span style={{ fontFamily: 'var(--font-heading)', fontSize: 19 }}>
                    {t.importWizard.google}
                  </span>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {t.importWizard.googleDesc}
                  </span>
                  <span style={{ fontSize: 11.5, color: 'var(--color-accent)' }}>
                    {t.importWizard.googlePro}
                  </span>
                  <span className="faint" style={{ fontSize: 11.5 }}>
                    {t.importWizard.googleHow}
                  </span>
                </button>
                <button
                  className="card--link"
                  style={{ borderColor: source === 'sport' ? 'var(--color-accent)' : undefined }}
                  onClick={() => setSource('sport')}
                >
                  <Zap size={26} strokeWidth={1.4} />
                  <span style={{ fontFamily: 'var(--font-heading)', fontSize: 19 }}>
                    {t.importWizard.sport}
                  </span>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {t.importWizard.sportDesc}
                  </span>
                  <span style={{ fontSize: 11.5, color: 'var(--color-accent)' }}>
                    {t.importWizard.sportPro}
                  </span>
                  <span className="faint" style={{ fontSize: 11.5 }}>
                    {t.importWizard.sportHow}
                  </span>
                </button>
              </div>

              {!pickerAvailable && (
                <div className="notice" style={{ marginTop: 14 }}>
                  {t.importWizard.pickerUnavailable}
                </div>
              )}

              <div
                className="notice"
                style={{ marginTop: 14, opacity: 0.55, borderStyle: 'dashed' }}
              >
                <PencilLine size={16} strokeWidth={1.4} />
                {t.importWizard.manual}
                <span className="tag tag-neutral" style={{ marginLeft: 'auto' }}>
                  {t.importWizard.soon}
                </span>
              </div>
              <p style={{ marginTop: 14, color: 'var(--color-accent)', fontSize: 12.5 }}>
                {t.importWizard.where}
              </p>
            </>
          )}

          {step === 2 && (
            <>
              <div className="kicker" style={{ marginBottom: 14 }}>
                {t.importWizard.s2}
              </div>
              <div className="kicker" style={{ marginBottom: 8 }}>
                {t.importWizard.group}
              </div>
              <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
                {(groups.data ?? []).map((group) => {
                  const locked = group.kind === 'system_commute'
                  return (
                    <label
                      key={group.id}
                      className="radio"
                      style={{
                        padding: '7px 12px',
                        border: '1px solid var(--color-divider)',
                        opacity: locked ? 0.5 : 1,
                      }}
                    >
                      <input
                        type="radio"
                        name="impg"
                        disabled={locked}
                        checked={groupId === group.id}
                        onChange={() => setGroupId(group.id)}
                      />
                      <span className="dot" />
                      {group.name}
                      {locked && (
                        <span className="faint" style={{ fontSize: 10 }}>
                          {t.importWizard.systemManaged}
                        </span>
                      )}
                    </label>
                  )
                })}
              </div>

              <div className="kicker" style={{ margin: '20px 0 8px' }}>
                {t.importWizard.tags}
              </div>
              <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
                {(tags.data ?? []).map((tag) => (
                  <label
                    key={tag.id}
                    className="check"
                    style={{ padding: '7px 12px', border: '1px solid var(--color-divider)' }}
                  >
                    <input
                      type="checkbox"
                      checked={tagIds.includes(tag.id)}
                      onChange={() =>
                        setTagIds((current) =>
                          current.includes(tag.id)
                            ? current.filter((id) => id !== tag.id)
                            : [...current, tag.id],
                        )
                      }
                    />
                    {tag.name}
                  </label>
                ))}
              </div>

              <div className="notice" style={{ marginTop: 22, maxWidth: 620 }}>
                {t.importWizard.groupNote}
              </div>
            </>
          )}

          {step === 3 && source === 'photo' && (
            <>
              {!pickToken ? (
                <div className="col" style={{ alignItems: 'center', gap: 16, padding: '48px 20px' }}>
                  <span style={{ fontFamily: 'var(--font-heading)', fontSize: 20, opacity: 0.7 }}>
                    {t.importWizard.pickDir}
                  </span>
                  <button className="btn btn-primary" onClick={pickFolder} disabled={busy}>
                    <Folder size={15} strokeWidth={1.5} />
                    {t.importWizard.pickDir}
                  </button>
                  <p className="muted" style={{ maxWidth: 520, textAlign: 'center', fontSize: 12.5 }}>
                    {t.importWizard.dirNote}
                  </p>
                </div>
              ) : (
                <>
                  <div
                    className="row"
                    style={{ paddingBottom: 12, borderBottom: '1px solid var(--color-divider)' }}
                  >
                    <Folder size={17} strokeWidth={1.4} />
                    {/* Last path component only - the full path stays server-side. */}
                    <span style={{ fontFamily: 'var(--font-heading)', fontSize: 18 }}>
                      {displayName}
                    </span>
                    <span className="faint" style={{ fontSize: 11 }}>
                      {t.importWizard.pathNote}
                    </span>
                    <button
                      className="btn btn-secondary btn-sm"
                      style={{ marginLeft: 'auto' }}
                      onClick={pickFolder}
                    >
                      {t.importWizard.reselect}
                    </button>
                  </div>

                  <label className="check">
                    <input
                      type="checkbox"
                      checked={includeSubdirs}
                      onChange={(event) => void rescan(event.target.checked)}
                    />
                    {t.importWizard.includeSubdirs}
                  </label>

                  <div className="kicker" style={{ margin: '8px 0' }}>
                    {t.importWizard.s3}
                  </div>
                  <div className="plate plate--3">
                    <div className="plate__cell">
                      <div className="plate__value">{prescan?.file_count.toLocaleString() ?? '—'}</div>
                      <div className="plate__label">{t.importWizard.found}</div>
                    </div>
                    <div className="plate__cell">
                      <div className="plate__value">
                        {(prescan?.parsable_count ?? 0).toLocaleString()}
                      </div>
                      <div className="plate__label">
                        {t.importWizard.parsable}
                        {prescan?.by_format
                          ? ` · ${Object.entries(prescan.by_format)
                              .map(([kind, count]) => `${kind.toUpperCase()} ${count}`)
                              .join(' · ')}`
                          : ''}
                      </div>
                    </div>
                    <div className="plate__cell">
                      <div className="plate__value" style={{ color: 'var(--color-accent)' }}>
                        ≈ {(prescan?.gps_count_estimate ?? 0).toLocaleString()}
                      </div>
                      <div className="plate__label">
                        {t.importWizard.withGps} ·{' '}
                        {Math.round((prescan?.gps_ratio ?? 0) * 100)}%
                      </div>
                    </div>
                    <div className="plate__cell">
                      <div className="plate__value">
                        ≈ {(prescan?.no_gps_count_estimate ?? 0).toLocaleString()}
                      </div>
                      <div className="plate__label">{t.importWizard.noGps}</div>
                    </div>
                    <div className="plate__cell">
                      <div className="plate__value" style={{ fontSize: 15 }}>
                        {prescan?.time_span?.start?.slice(0, 7) ?? '—'} →{' '}
                        {prescan?.time_span?.end?.slice(0, 7) ?? '—'}
                      </div>
                      <div className="plate__label">{t.importWizard.span}</div>
                    </div>
                    <div className="plate__cell">
                      <div className="plate__value">
                        ≈ {Math.max(1, Math.round((prescan?.estimated_seconds ?? 0) / 60))}{' '}
                        {t.settings.minutes}
                      </div>
                      <div className="plate__label">{t.importWizard.eta}</div>
                    </div>
                  </div>

                  {/* The GPS numbers above are extrapolated from a sample, and
                      the caption has to say so rather than imply a census. */}
                  <p className="faint" style={{ fontSize: 11.5, marginTop: 8, maxWidth: 640 }}>
                    {t.importWizard.estimated(prescan?.sampled ?? 0)} · {t.importWizard.prescanNote}
                  </p>

                  <div className="kicker" style={{ margin: '18px 0 8px' }}>
                    {t.importWizard.options}
                  </div>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={inferGps}
                      onChange={() => setInferGps((value) => !value)}
                    />
                    {t.importWizard.optInterp}
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={thumbnails}
                      onChange={() => setThumbnails((value) => !value)}
                    />
                    {t.importWizard.optThumb}
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={skipDuplicates}
                      onChange={() => setSkipDuplicates((value) => !value)}
                    />
                    {t.importWizard.optDedupe}
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={rangeOn}
                      onChange={() => setRangeOn((value) => !value)}
                    />
                    {t.importWizard.optRange}
                    <span className="faint" style={{ fontSize: 11 }}>
                      · {t.importWizard.rangeNote}
                    </span>
                  </label>
                  {rangeOn && (
                    <div className="row" style={{ gap: 6, marginTop: 6 }}>
                      <input
                        className="input"
                        type="date"
                        value={rangeStart}
                        onChange={(event) => setRangeStart(event.target.value)}
                      />
                      <input
                        className="input"
                        type="date"
                        value={rangeEnd}
                        onChange={(event) => setRangeEnd(event.target.value)}
                      />
                    </div>
                  )}
                </>
              )}
            </>
          )}

          {step === 3 && source !== 'photo' && (
            <>
              <div className="kicker" style={{ marginBottom: 14 }}>
                {t.importWizard.s3}
              </div>
              <label
                className="notice"
                style={{ cursor: 'pointer', justifyContent: 'center', padding: 32 }}
              >
                <input
                  type="file"
                  style={{ display: 'none' }}
                  accept=".zip,.json,.gpx,.tcx,.fit"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) void upload(file)
                  }}
                />
                {busy ? t.importWizard.uploading : t.importWizard.dropFile}
              </label>

              {prescan && (
                <Blueprint style={{ marginTop: 14, padding: 12 }}>
                  <div className="row">
                    <span style={{ fontFamily: 'var(--font-heading)', fontSize: 16 }}>
                      {displayName}
                    </span>
                    <span className="tag tag-outline" style={{ marginLeft: 'auto' }}>
                      {prescan.kind ?? t.app.unknown}
                      {prescan.variant ? ` · ${prescan.variant}` : ''}
                    </span>
                  </div>
                  <div className="muted num" style={{ fontSize: 12, marginTop: 6 }}>
                    {t.importWizard.detectedPoints} {(prescan.file_count ?? 0).toLocaleString()} ·{' '}
                    {prescan.time_span?.start?.slice(0, 10) ?? '—'} →{' '}
                    {prescan.time_span?.end?.slice(0, 10) ?? '—'}
                  </div>
                </Blueprint>
              )}
            </>
          )}

          {step === 4 && (
            <div style={{ padding: '20px 0 10px' }}>
              <div style={{ fontFamily: 'var(--font-heading)', fontSize: 20, marginBottom: 18 }}>
                {t.importWizard.s4}
              </div>
              {bar('read_exif', t.sources.stage.read_exif)}
              {bar('thumbnails', t.sources.stage.thumbnails)}
              {bar('cluster', t.sources.stage.cluster)}
              <div className="row muted" style={{ gap: 12, fontSize: 12 }}>
                {task?.eta_seconds ? (
                  <span>{t.importWizard.remaining(Math.max(1, Math.round(task.eta_seconds / 60)))}</span>
                ) : null}
                {/* Cancel, not pause: there is no resumable checkpoint, and the
                    original files make a re-run cheap. */}
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => taskId && void api.cancelImport(taskId)}
                >
                  {t.importWizard.cancelImport}
                </button>
              </div>
            </div>
          )}

          {step === 5 && (
            <>
              <div className="row" style={{ gap: 10, marginBottom: 16 }}>
                <span style={{ fontFamily: 'var(--font-heading)', fontSize: 24 }}>
                  {t.importWizard.doneTitle}
                </span>
              </div>
              <div
                className="row num"
                style={{ flexWrap: 'wrap', gap: 10, fontFamily: 'var(--font-heading)', fontSize: 26 }}
              >
                <span>{(report.points ?? report.photos ?? 0).toLocaleString()}</span>
                <span className="muted" style={{ fontSize: 13, fontFamily: 'var(--font-body)' }}>
                  {t.importWizard.rPoints}
                </span>
                <span style={{ opacity: 0.4 }}>→</span>
                <span>{(report.places ?? 0).toLocaleString()}</span>
                <span className="muted" style={{ fontSize: 13, fontFamily: 'var(--font-body)' }}>
                  {t.importWizard.rPlaces}
                </span>
                <span>{(report.tracks ?? 0).toLocaleString()}</span>
                <span className="muted" style={{ fontSize: 13, fontFamily: 'var(--font-body)' }}>
                  {t.importWizard.rTracks}
                </span>
                <span style={{ opacity: 0.4 }}>→</span>
                <span style={{ color: 'var(--color-accent)' }}>
                  {(report.trips_created ?? 0) + (report.trips_updated ?? 0)}
                </span>
                <span className="muted" style={{ fontSize: 13, fontFamily: 'var(--font-body)' }}>
                  {t.importWizard.rTrips}
                </span>
              </div>

              <div style={{ marginTop: 18, border: '1px solid var(--color-divider)' }}>
                <div
                  className="row"
                  style={{ padding: '10px 12px', borderBottom: '1px solid var(--color-divider)' }}
                >
                  {t.importWizard.rNew(report.trips_created ?? 0)}{' '}
                  <span className="tag tag-accent">
                    {groups.data?.find((group) => group.id === groupId)?.name ?? t.groups.noGroup}
                  </span>
                </div>
                <div className="row" style={{ padding: '10px 12px', flexWrap: 'wrap' }}>
                  {t.importWizard.rExisting(report.trips_updated ?? 0)} · {t.importWizard.rTagged}
                  {(report.updated_trip_ids ?? []).length > 0 && (
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ marginLeft: 'auto' }}
                      onClick={() => {
                        setOpen(false)
                        navigate({ name: 'trips' })
                      }}
                    >
                      {t.importWizard.rSee((report.updated_trip_ids ?? []).length)}
                    </button>
                  )}
                </div>
              </div>

              <div className="col" style={{ gap: 6, marginTop: 14, fontSize: 12.5 }}>
                <div className="row">
                  <span className="muted" style={{ width: 90 }}>
                    {t.importWizard.span}
                  </span>
                  <span className="num">
                    {report.time_span?.start?.slice(0, 10) ?? '—'} ~{' '}
                    {report.time_span?.end?.slice(0, 10) ?? '—'}
                  </span>
                </div>
                <div className="row">
                  <span className="muted" style={{ width: 90 }}>
                    ⇄
                  </span>
                  <span>
                    {report.tz_crossings
                      ? t.importWizard.rTz(report.tz_crossings)
                      : t.importWizard.rTzNone}
                  </span>
                </div>
                <div className="row">
                  <span className="muted" style={{ width: 90 }}>
                    {t.nav.commute}
                  </span>
                  <span>
                    {report.commute?.detected
                      ? t.importWizard.rCommuteFound(report.commute.ods ?? 0)
                      : t.importWizard.rCommuteNone}
                  </span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="dialog__foot">
          {(step === 2 || step === 3) && (
            <button className="btn btn-secondary" onClick={() => setStep(step - 1)}>
              {t.importWizard.prev}
            </button>
          )}
          <div className="row" style={{ marginLeft: 'auto', gap: 8 }}>
            {step < 4 && (
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setOpen(false)
                  reset()
                }}
              >
                {t.app.cancel}
              </button>
            )}
            {canNext && (
              <button className="btn btn-primary" onClick={() => setStep(step + 1)}>
                {t.importWizard.next} →
              </button>
            )}
            {canStart && (
              <button className="btn btn-primary" onClick={start} disabled={busy}>
                {t.importWizard.start}
              </button>
            )}
            {step === 5 && (
              <>
                <button className="btn btn-secondary" onClick={reset}>
                  {t.importWizard.more}
                </button>
                <button
                  className="btn btn-primary"
                  onClick={() => {
                    setOpen(false)
                    reset()
                    // Fences are confirmed before the first map, never after.
                    setFenceModalOpen(true)
                  }}
                >
                  {t.importWizard.toFence} →
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
