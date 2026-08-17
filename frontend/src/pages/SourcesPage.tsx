/**
 * Imported data: what is in the library, and what is being added right now.
 *
 * The in-progress block is not decoration. An import runs server-side and
 * survives the browser (02 section 10, E8), so closing the wizard has to leave
 * somewhere to watch it.
 *
 * Undo is destructive - it deletes everything derived from a source - so it
 * asks first and says exactly what survives: the original file.
 */

import { useState } from 'react'

import { useDeleteSource, useImports, useSources } from '@/api/hooks'
import type { SourceFile } from '@/api/types'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

function bytes(size: number | null): string {
  if (size === null) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = size
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

export default function SourcesPage() {
  const t = useCopy()
  const sources = useSources()
  const running = useImports()
  const remove = useDeleteSource()
  const setImportOpen = useAppStore((state) => state.setImportOpen)
  const [pending, setPending] = useState<SourceFile | null>(null)

  const active = (running.data ?? []).filter(
    (task) => task.status === 'running' || task.status === 'queued',
  )

  return (
    <div className="page page--scroll">
      <div className="page__title" style={{ marginBottom: 16 }}>
        <h1>{t.sources.title}</h1>
        <button
          className="btn btn-primary"
          style={{ marginLeft: 'auto' }}
          onClick={() => setImportOpen(true)}
        >
          + {t.sources.openWizard}
        </button>
      </div>

      {active.length > 0 && (
        <section style={{ marginBottom: 20 }}>
          <div className="kicker" style={{ marginBottom: 8 }}>
            {t.sources.running}
          </div>
          {active.map((task) => (
            <div key={task.id} className="notice notice--accent" style={{ marginBottom: 8 }}>
              <span style={{ flex: 1 }}>
                {task.display_name} ·{' '}
                {task.stage ? (t.sources.stage[task.stage as keyof typeof t.sources.stage] ?? task.stage) : ''}{' '}
                <span className="num">{t.sources.progress(task.processed, task.total)}</span>
              </span>
            </div>
          ))}
        </section>
      )}

      {sources.isSuccess && sources.data.length === 0 ? (
        <p className="muted">{t.sources.empty}</p>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>{t.sources.columnFiles}</th>
                <th>{t.sources.columnKind}</th>
                <th>{t.sources.columnSize}</th>
                <th>{t.sources.columnPoints}</th>
                <th>{t.sources.columnWhen}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(sources.data ?? []).map((source) => (
                <tr key={source.id}>
                  <td className="num">{source.display_name}</td>
                  <td className="muted">{t.sourceKinds[source.kind]}</td>
                  <td className="num muted">{bytes(source.byte_size)}</td>
                  <td className="num">
                    {Number(
                      (source.stats.points as number | undefined) ??
                        (source.stats.photos as number | undefined) ??
                        0,
                    ).toLocaleString()}
                  </td>
                  <td className="num muted">{source.imported_at.slice(0, 16).replace('T', ' ')}</td>
                  <td style={{ textAlign: 'right' }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => setPending(source)}>
                      {t.sources.undo}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="notice" style={{ marginTop: 16, maxWidth: 620 }}>
        {t.sources.rawNote}
      </div>

      {pending && (
        <div className="backdrop" onClick={() => setPending(null)}>
          <div className="dialog" onClick={(event) => event.stopPropagation()}>
            <div className="dialog__head">
              <span className="dialog__title">{t.sources.undoTitle}</span>
            </div>
            <div className="dialog__body">
              <p>{pending.display_name}</p>
              <p className="muted">{t.sources.undoWarning}</p>
            </div>
            <div className="dialog__foot" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-secondary" onClick={() => setPending(null)}>
                {t.app.cancel}
              </button>
              <button
                className="btn btn-danger"
                onClick={async () => {
                  await remove.mutateAsync(pending.id)
                  setPending(null)
                }}
              >
                {t.sources.undo}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
