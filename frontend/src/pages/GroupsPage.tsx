/**
 * Groups and tags: the only place an existing trip's filing can be corrected.
 *
 * The import wizard can only set a group on trips it CREATES (a day assembled
 * from several imports keeps its first group, 02 R3-D2), so without this page a
 * wrong choice at import time would be permanent.
 *
 * Two rules made visible rather than implied:
 *   * one group, many tags. The group column is a select; tags are toggles.
 *   * the commute group is algorithm-owned: it is not offered as a move target,
 *     and the server refuses it anyway.
 */

import { Lock, MapPin, Luggage, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import {
  useBulkAssign,
  useCreateGroup,
  useCreateTag,
  useDeleteGroup,
  useDeleteTag,
  useGroups,
  usePlaces,
  useTags,
  useTrips,
  useUpdateGroup,
  useUpdateTag,
} from '@/api/hooks'
import { useCopy } from '@/i18n'

type Kind = 'group' | 'tag'

interface Row {
  id: string
  kind: 'trip' | 'place'
  name: string
  date: string
  groupId: string | null
  inherited: boolean
  tagIds: string[]
}

export default function GroupsPage() {
  const t = useCopy()
  const groups = useGroups()
  const tags = useTags()
  const assign = useBulkAssign()
  const createGroup = useCreateGroup()
  const createTag = useCreateTag()
  const updateGroup = useUpdateGroup()
  const updateTag = useUpdateTag()
  const deleteGroup = useDeleteGroup()
  const deleteTag = useDeleteTag()

  const [selected, setSelected] = useState<{ kind: Kind; id: string } | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [moveTarget, setMoveTarget] = useState<string>('')
  // One dialog drives create and rename: same field, same validation, and the
  // only difference is whether an id is being edited.
  const [editing, setEditing] = useState<{ kind: Kind; id: string | null } | null>(null)
  const [draftName, setDraftName] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const active = selected ?? (groups.data?.[0] ? { kind: 'group' as Kind, id: groups.data[0].id } : null)
  const activeGroup = active?.kind === 'group' ? groups.data?.find((g) => g.id === active.id) : undefined
  const activeTag = active?.kind === 'tag' ? tags.data?.find((g) => g.id === active.id) : undefined

  const query = active
    ? active.kind === 'group'
      ? { group: active.id, limit: 200 }
      : { tag: active.id, limit: 200 }
    : { limit: 0 }
  const trips = useTrips(query)
  const places = usePlaces(query)

  const rows: Row[] = [
    ...(trips.data ?? []).map((trip) => ({
      id: `T${trip.id}`,
      kind: 'trip' as const,
      name: trip.title,
      date: trip.local_date,
      groupId: trip.group_id,
      inherited: false,
      tagIds: trip.tag_ids ?? [],
    })),
    ...(places.data ?? []).map((place) => ({
      id: `P${place.id}`,
      kind: 'place' as const,
      name: place.name ?? place.geo_name ?? place.geo_city ?? t.overview.unnamed,
      date: place.start_utc.slice(0, 10),
      // A place with no group of its own belongs to its trip's group. Saying
      // which it is matters: editing here changes the place, not the trip.
      groupId: active?.kind === 'group' ? active.id : null,
      inherited: true,
      tagIds: [],
    })),
  ].sort((a, b) => (a.date < b.date ? 1 : -1))

  const rawId = (id: string) => id.slice(1)
  const checkedTrips = [...checked].filter((id) => id.startsWith('T')).map(rawId)
  const checkedPlaces = [...checked].filter((id) => id.startsWith('P')).map(rawId)

  const applyMove = async () => {
    if (!moveTarget) return
    if (checkedTrips.length) await assign.mutateAsync({ trip_ids: checkedTrips, group_id: moveTarget })
    if (checkedPlaces.length) await assign.mutateAsync({ place_ids: checkedPlaces, group_id: moveTarget })
    setChecked(new Set())
  }

  const toggleTag = async (row: Row, tagId: string) => {
    const has = row.tagIds.includes(tagId)
    const body = has ? { remove_tags: [tagId] } : { add_tags: [tagId] }
    if (row.kind === 'trip') await assign.mutateAsync({ trip_ids: [rawId(row.id)], ...body })
    else await assign.mutateAsync({ place_ids: [rawId(row.id)], ...body })
  }

  // The system group is never a move target: the detector owns it and would
  // overwrite the assignment on its next pass.
  const movable = (groups.data ?? []).filter((group) => group.kind !== 'system_commute')

  return (
    <div className="page">
      <div className="split">
        <aside className="split__aside split__aside--groups">
          <div className="kicker" style={{ padding: '0 16px 8px' }}>
            {t.groups.groups}
          </div>
          {(groups.data ?? []).map((group) => (
            <button
              key={group.id}
              className="list-item"
              aria-current={active?.kind === 'group' && active.id === group.id}
              onClick={() => {
                setSelected({ kind: 'group', id: group.id })
                setChecked(new Set())
              }}
            >
              <span style={{ fontFamily: 'var(--font-heading)', fontSize: 16 }}>{group.name}</span>
              {group.kind === 'system_commute' && <Lock size={12} strokeWidth={1.5} opacity={0.55} />}
              <span className="list-item__count">
                {t.groups.tripsAndPlaces(group.trip_count, group.place_count)}
              </span>
            </button>
          ))}

          <div style={{ padding: '8px 16px 0' }}>
            <button
              className="btn btn-secondary btn-block btn-sm"
              onClick={() => {
                setDraftName('')
                setEditing({ kind: 'group', id: null })
              }}
            >
              <Plus size={13} strokeWidth={1.5} />
              {t.groups.newGroup}
            </button>
          </div>

          <div className="kicker" style={{ padding: '20px 16px 8px' }}>
            {t.groups.tags}
          </div>
          {(tags.data ?? []).map((tag) => (
            <button
              key={tag.id}
              className="list-item"
              aria-current={active?.kind === 'tag' && active.id === tag.id}
              onClick={() => {
                setSelected({ kind: 'tag', id: tag.id })
                setChecked(new Set())
              }}
            >
              <span style={{ fontSize: 14 }}>{tag.name}</span>
              <span className="list-item__count">
                {tag.trip_count} · {tag.place_count}
              </span>
            </button>
          ))}
          <div style={{ padding: '8px 16px 0' }}>
            <button
              className="btn btn-secondary btn-block btn-sm"
              onClick={() => {
                setDraftName('')
                setEditing({ kind: 'tag', id: null })
              }}
            >
              <Plus size={13} strokeWidth={1.5} />
              {t.groups.newTag}
            </button>
          </div>
        </aside>

        <div className="split__main">
          <div className="row" style={{ alignItems: 'baseline', gap: 10 }}>
            <h1 style={{ fontSize: 28, margin: 0 }}>
              {activeGroup?.name ?? activeTag?.name ?? t.groups.title}
            </h1>
            {activeGroup && <span className="tag tag-accent">{t.groups.groups}</span>}
            <span className="muted" style={{ fontSize: 12 }}>
              {t.groups.members}
            </span>
            {active && (
              <div className="row" style={{ marginLeft: 'auto', gap: 6 }}>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={activeGroup?.kind === 'system_commute'}
                  title={activeGroup?.kind === 'system_commute' ? t.groups.systemLocked : undefined}
                  onClick={() => {
                    setDraftName(activeGroup?.name ?? activeTag?.name ?? '')
                    setEditing({ kind: active.kind, id: active.id })
                  }}
                >
                  <Pencil size={13} strokeWidth={1.5} />
                  {t.app.rename}
                </button>
                <button
                  className="btn btn-danger btn-sm"
                  disabled={activeGroup?.kind === 'system_commute'}
                  title={activeGroup?.kind === 'system_commute' ? t.groups.systemLocked : undefined}
                  onClick={() => setConfirmDelete(true)}
                >
                  <Trash2 size={13} strokeWidth={1.5} />
                  {t.app.delete}
                </button>
              </div>
            )}
          </div>
          <p className="muted" style={{ fontSize: 12, maxWidth: 640, marginTop: 6 }}>
            {t.groups.rule}
          </p>
          {activeGroup?.kind === 'system_commute' && (
            <div className="notice notice--accent" style={{ maxWidth: 640, marginTop: 10 }}>
              <Lock size={14} strokeWidth={1.5} color="var(--color-accent)" />
              {t.groups.systemGroup}
            </div>
          )}

          <div className="row" style={{ margin: '16px 0 10px', gap: 10, flexWrap: 'wrap' }}>
            <span className="muted" style={{ fontSize: 12 }}>
              {checked.size} {t.groups.selected}
            </span>
            <span className="muted" style={{ fontSize: 12 }}>
              {t.groups.moveTo}
            </span>
            <select
              className="input"
              style={{ width: 200 }}
              value={moveTarget}
              onChange={(event) => setMoveTarget(event.target.value)}
            >
              <option value="">{t.groups.noGroup}</option>
              {movable.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}
                </option>
              ))}
            </select>
            <button
              className="btn btn-primary btn-sm"
              disabled={!checked.size || !moveTarget}
              onClick={applyMove}
            >
              {t.app.apply}
            </button>
          </div>

          {rows.length === 0 ? (
            <p className="muted" style={{ padding: '40px 0' }}>
              {t.groups.empty}
            </p>
          ) : (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: 34 }} />
                    <th>{t.groups.columnItem}</th>
                    <th>{t.groups.columnDate}</th>
                    <th style={{ width: 190 }}>{t.groups.columnGroup}</th>
                    <th>{t.groups.columnTags}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={checked.has(row.id)}
                          onChange={() =>
                            setChecked((current) => {
                              const next = new Set(current)
                              if (next.has(row.id)) next.delete(row.id)
                              else next.add(row.id)
                              return next
                            })
                          }
                        />
                      </td>
                      <td>
                        <span className="row" style={{ gap: 8 }}>
                          {row.kind === 'trip' ? (
                            <Luggage size={14} strokeWidth={1.5} opacity={0.6} />
                          ) : (
                            <MapPin size={14} strokeWidth={1.5} opacity={0.6} />
                          )}
                          <span style={{ fontFamily: 'var(--font-heading)', fontSize: 15 }}>
                            {row.name}
                          </span>
                          <span className="faint" style={{ fontSize: 10 }}>
                            {row.kind === 'trip' ? t.groups.kindTrip : t.groups.kindPlace}
                          </span>
                        </span>
                      </td>
                      <td className="num">{row.date}</td>
                      <td>
                        <select
                          className="input"
                          style={{ height: 28, fontSize: 12 }}
                          value={row.groupId ?? ''}
                          onChange={(event) =>
                            row.kind === 'trip'
                              ? assign.mutate({
                                  trip_ids: [rawId(row.id)],
                                  group_id: event.target.value || null,
                                })
                              : assign.mutate({
                                  place_ids: [rawId(row.id)],
                                  group_id: event.target.value || null,
                                })
                          }
                        >
                          <option value="">{t.groups.noGroup}</option>
                          {movable.map((group) => (
                            <option key={group.id} value={group.id}>
                              {group.name}
                            </option>
                          ))}
                        </select>
                        {row.kind === 'place' && row.inherited && (
                          <div className="faint" style={{ fontSize: 10 }}>
                            {t.groups.inherited}
                          </div>
                        )}
                      </td>
                      <td>
                        <span className="row" style={{ gap: 5, flexWrap: 'wrap' }}>
                          {(tags.data ?? []).map((tag) => {
                            const on = row.tagIds.includes(tag.id)
                            return (
                              <button
                                key={tag.id}
                                className={`tag ${on ? 'tag-accent' : 'tag-outline'}`}
                                style={{ cursor: 'pointer', opacity: on ? 1 : 0.5 }}
                                onClick={() => void toggleTag(row, tag.id)}
                              >
                                {tag.name}
                              </button>
                            )
                          })}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {editing && (
        <div className="backdrop" style={{ zIndex: 36 }} onClick={() => setEditing(null)}>
          <div className="dialog" onClick={(event) => event.stopPropagation()}>
            <div className="dialog__head">
              <span className="dialog__title">
                {editing.id
                  ? t.app.rename
                  : editing.kind === 'group'
                    ? t.groups.newGroup
                    : t.groups.newTag}
              </span>
            </div>
            <div className="dialog__body">
              <div className="field">
                <label>{t.groups.namePrompt}</label>
                <input
                  className="input"
                  value={draftName}
                  autoFocus
                  onChange={(event) => setDraftName(event.target.value)}
                />
              </div>
              {error && (
                <p style={{ color: 'var(--color-danger)', marginTop: 8 }}>{error}</p>
              )}
            </div>
            <div className="dialog__foot" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-secondary" onClick={() => setEditing(null)}>
                {t.app.cancel}
              </button>
              <button
                className="btn btn-primary"
                disabled={!draftName.trim()}
                onClick={async () => {
                  setError(null)
                  const name = draftName.trim()
                  try {
                    if (editing.kind === 'group') {
                      const saved = editing.id
                        ? await updateGroup.mutateAsync({ id: editing.id, name })
                        : await createGroup.mutateAsync({ name })
                      setSelected({ kind: 'group', id: saved.id })
                    } else {
                      const saved = editing.id
                        ? await updateTag.mutateAsync({ id: editing.id, name })
                        : await createTag.mutateAsync({ name })
                      setSelected({ kind: 'tag', id: saved.id })
                    }
                    setEditing(null)
                  } catch (caught) {
                    // 409 from the (user_id, name) unique index - shown in place
                    // rather than as a raw error string.
                    const status = (caught as { status?: number }).status
                    setError(status === 409 ? t.groups.nameExists : String(caught))
                  }
                }}
              >
                {t.app.save}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmDelete && active && (
        <div className="backdrop" style={{ zIndex: 36 }} onClick={() => setConfirmDelete(false)}>
          <div className="dialog" onClick={(event) => event.stopPropagation()}>
            <div className="dialog__head">
              <span className="dialog__title">
                {activeGroup?.name ?? activeTag?.name}
              </span>
            </div>
            <div className="dialog__body">
              <p className="muted">
                {active.kind === 'group' ? t.groups.deleteGroupWarning : t.groups.deleteTagWarning}
              </p>
            </div>
            <div className="dialog__foot" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-secondary" onClick={() => setConfirmDelete(false)}>
                {t.app.cancel}
              </button>
              <button
                className="btn btn-danger"
                onClick={async () => {
                  if (active.kind === 'group') await deleteGroup.mutateAsync(active.id)
                  else await deleteTag.mutateAsync(active.id)
                  setSelected(null)
                  setConfirmDelete(false)
                }}
              >
                {t.app.delete}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
