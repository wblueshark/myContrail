/**
 * Import wizard and imported-source list.
 *
 * The photo flow never handles a path. "Choose folder" asks the backend to open
 * the host's native chooser and gets back a one-shot pick_token plus a prescan
 * summary; the import request carries only that token. If the host has no
 * native chooser, the entry point is not rendered at all rather than rendered
 * and failing.
 */

import { useEffect, useRef, useState } from 'react'

import { api } from '@/api/client'
import { useCapabilities, useDeleteSource, useGroups, useSources, useTags } from '@/api/hooks'
import type { ImportReport, PickResponse, Prescan, TaskState } from '@/api/types'
import { t } from '@/i18n/zh'

function StageLabel({ task }: { task: TaskState }) {
  const key = (task.stage ?? '') as keyof typeof t.sources.stage
  const label = t.sources.stage[key] ?? task.stage ?? task.status
  return (
    <div>
      <div className="row row--between">
        <span>{label}</span>
        <span className="faint">{t.sources.progress(task.processed, task.total)}</span>
      </div>
      <div className="progress" style={{ marginTop: 6 }}>
        {task.total ? (
          <div
            className="progress__fill"
            style={{ width: `${Math.min(100, (task.processed / task.total) * 100)}%` }}
          />
        ) : (
          // Total unknown while streaming: an indeterminate bar is honest, an
          // invented percentage is not.
          <div className="progress__fill progress__fill--indeterminate" />
        )}
      </div>
    </div>
  )
}

function Report({ report }: { report: ImportReport }) {
  if (report.already_imported) return <div className="notice">{t.sources.alreadyImported}</div>
  return (
    <div className="stack">
      <strong>{t.sources.reportTitle}</strong>
      {report.points ? <span>{t.sources.reportPoints(report.points)}</span> : null}
      {report.photos ? <span>{t.sources.reportPhotos(report.photos)}</span> : null}
      {report.duplicates ? <span className="faint">{t.sources.reportDuplicates(report.duplicates)}</span> : null}
      {report.trips_created ? <span>✅ {t.sources.reportCreated(report.trips_created, '—')}</span> : null}
      {/* Existing trips keep their group: a day can be built from several
          imports, and last-write-wins would silently refile a whole holiday. */}
      {report.trips_updated ? <span>↻ {t.sources.reportExisting(report.trips_updated)}</span> : null}
      {report.skipped && Object.keys(report.skipped).length > 0 && (
        <details>
          <summary className="faint">{t.sources.reportSkipped}</summary>
          <ul className="faint">
            {Object.entries(report.skipped).map(([reason, count]) => (
              <li key={reason}>
                {reason}: {count}
              </li>
            ))}
          </ul>
        </details>
      )}
      {report.errors && report.errors.length > 0 && (
        <details>
          <summary style={{ color: 'var(--danger)' }}>{t.sources.reportErrors}</summary>
          <pre className="faint" style={{ whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(report.errors, null, 1)}
          </pre>
        </details>
      )}
    </div>
  )
}

export default function SourcesPage() {
  const capabilities = useCapabilities()
  const sources = useSources()
  const groups = useGroups()
  const tags = useTags()
  const deleteSource = useDeleteSource()

  const [pick, setPick] = useState<PickResponse | null>(null)
  const [upload, setUpload] = useState<{ id: string; name: string; prescan: Prescan } | null>(null)
  const [groupId, setGroupId] = useState('')
  const [tagIds, setTagIds] = useState<string[]>([])
  const [task, setTask] = useState<TaskState | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const eventSource = useRef<EventSource | null>(null)

  // SSE progress. The stream ends with an explicit `end` event, so the UI never
  // has to poll to find out an import finished.
  useEffect(() => {
    if (!task || ['done', 'failed', 'cancelled'].includes(task.status)) {
      eventSource.current?.close()
      eventSource.current = null
      return
    }
    if (eventSource.current) return

    const stream = new EventSource(api.importEventsUrl(task.id))
    eventSource.current = stream
    stream.onmessage = (event) => setTask(JSON.parse(event.data) as TaskState)
    stream.addEventListener('end', () => {
      stream.close()
      eventSource.current = null
      void sources.refetch()
    })
    stream.onerror = () => {
      stream.close()
      eventSource.current = null
    }
    return () => {
      stream.close()
      eventSource.current = null
    }
  }, [task, sources])

  const choosePhotos = async () => {
    setMessage(null)
    try {
      const result = await api.pickDirectory()
      // 204 means the user cancelled the native dialog.
      if (!result) {
        setMessage(t.sources.cancelled)
        return
      }
      setPick(result)
    } catch (caught) {
      setMessage(String((caught as { detail?: unknown }).detail ?? caught))
    }
  }

  const chooseFile = async (file: File) => {
    setMessage(null)
    const uploaded = await api.upload(file)
    const prescan = await api.prescan({ upload_id: uploaded.upload_id })
    setUpload({ id: uploaded.upload_id, name: uploaded.display_name, prescan })
  }

  const start = async (ref: string, kind: 'photo' | 'file') => {
    const created = await api.createImport({
      source_ref: ref,
      kind,
      group_id: groupId || null,
      tag_ids: tagIds,
    })
    setTask(created)
    setPick(null)
    setUpload(null)
  }

  const pickerAvailable = capabilities.data?.directory_picker !== null

  return (
    <div className="page">
      <h1>{t.sources.title}</h1>

      {message && <div className="notice">{message}</div>}

      <div className="grid-2">
        <div className="card">
          <h2>{t.sources.importPhotos}</h2>
          {/* Not rendered at all when the host has no native chooser. */}
          {pickerAvailable ? (
            <>
              <p className="faint">{t.sources.chooseFolderHelp}</p>
              <button onClick={choosePhotos}>{t.sources.chooseFolder}</button>
            </>
          ) : (
            <div className="notice notice--warn">{t.sources.pickerUnavailable}</div>
          )}

          {pick && (
            <div className="stack" style={{ marginTop: 12 }}>
              <strong>{pick.display_name}</strong>
              <span className="faint">
                {t.sources.prescanResult(
                  pick.prescan.file_count,
                  Math.round((pick.prescan.gps_ratio ?? 0) * 100),
                )}
              </span>
              <span className="faint">
                {t.sources.prescanEstimate(pick.prescan.estimated_seconds ?? 0)}
              </span>
              {/* The one remaining way to hurt yourself is picking "/", so a big
                  directory asks a second time. */}
              {pick.prescan.needs_confirmation && (
                <div className="notice notice--warn">
                  {t.sources.largeWarning(pick.prescan.file_count)}
                </div>
              )}
              <button className="primary" onClick={() => start(pick.pick_token, 'photo')}>
                {t.sources.startImport}
              </button>
            </div>
          )}
        </div>

        <div className="card">
          <h2>{t.sources.importFile}</h2>
          <p className="faint">{t.sources.dropFile}</p>
          <input
            ref={fileInput}
            type="file"
            accept=".gpx,.tcx,.fit,.json,.zip,.xml"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void chooseFile(file)
            }}
          />
          {upload && (
            <div className="stack" style={{ marginTop: 12 }}>
              <strong>{upload.name}</strong>
              <span className="faint">
                {t.sources.detected(
                  t.sourceKinds[upload.prescan.kind as keyof typeof t.sourceKinds] ??
                    upload.prescan.kind ??
                    t.app.unknown,
                )}
              </span>
              <button className="primary" onClick={() => start(upload.id, 'file')}>
                {t.sources.startImport}
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <h3>{t.sources.batchGroup}</h3>
        <select value={groupId} onChange={(event) => setGroupId(event.target.value)}>
          <option value="">{t.sources.noGroup}</option>
          {(groups.data ?? []).map((group) => (
            <option key={group.id} value={group.id}>
              {group.name}
            </option>
          ))}
        </select>
        <h3 style={{ marginTop: 12 }}>{t.sources.batchTags}</h3>
        <div className="row row--wrap">
          {(tags.data ?? []).map((tag) => (
            <button
              key={tag.id}
              className={tagIds.includes(tag.id) ? 'primary' : ''}
              onClick={() =>
                setTagIds((current) =>
                  current.includes(tag.id)
                    ? current.filter((id) => id !== tag.id)
                    : [...current, tag.id],
                )
              }
            >
              {tag.name}
            </button>
          ))}
        </div>
      </div>

      {task && (
        <div className="card">
          <div className="row row--between">
            <h3>
              {t.sources.importing}: {task.display_name}
            </h3>
            {['queued', 'running'].includes(task.status) && (
              <button className="danger" onClick={() => void api.cancelImport(task.id)}>
                {t.app.cancel}
              </button>
            )}
          </div>
          <StageLabel task={task} />
          {task.status === 'done' && <Report report={task.result as ImportReport} />}
          {task.status === 'failed' && (
            <div className="notice notice--danger">
              {t.sources.failed}: {task.error?.message}
            </div>
          )}
        </div>
      )}

      <h2 style={{ marginTop: 20 }}>{t.sources.imported}</h2>
      <table>
        <thead>
          <tr>
            <th>{t.sources.title}</th>
            <th>{t.sources.status}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(sources.data ?? []).map((source) => (
            <tr key={source.id}>
              <td>
                <strong>{source.display_name}</strong>
                <div className="faint">
                  {t.sourceKinds[source.kind]} · {source.imported_at.slice(0, 10)}
                  {source.has_original && ` · ${t.sources.originalKept}`}
                </div>
              </td>
              <td>
                <span className={source.status === 'done' ? 'pill pill--ok' : 'pill pill--warn'}>
                  {source.status}
                </span>
              </td>
              <td>
                <button
                  className="danger"
                  title={t.sources.undoWarning}
                  onClick={() => {
                    if (window.confirm(t.sources.undoWarning)) deleteSource.mutate(source.id)
                  }}
                >
                  {t.sources.undo}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {sources.data && sources.data.length === 0 && <p className="faint">{t.app.empty}</p>}
    </div>
  )
}
