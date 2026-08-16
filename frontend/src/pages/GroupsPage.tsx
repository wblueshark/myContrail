/** Groups (exclusive, at most one) and tags (non-exclusive, any number). */

import { useState } from 'react'

import {
  useCreateGroup,
  useCreateTag,
  useDeleteGroup,
  useDeleteTag,
  useGroups,
  useTags,
} from '@/api/hooks'
import { t } from '@/i18n/zh'

export default function GroupsPage() {
  const groups = useGroups()
  const tags = useTags()
  const createGroup = useCreateGroup()
  const createTag = useCreateTag()
  const deleteGroup = useDeleteGroup()
  const deleteTag = useDeleteTag()

  const [groupName, setGroupName] = useState('')
  const [tagName, setTagName] = useState('')

  return (
    <div className="page">
      <h1>{t.groups.title}</h1>

      <div className="grid-2">
        <div className="card">
          <h2>{t.groups.groups}</h2>
          <div className="row" style={{ marginBottom: 12 }}>
            <input
              value={groupName}
              onChange={(event) => setGroupName(event.target.value)}
              placeholder={t.groups.newGroup}
            />
            <button
              disabled={!groupName.trim() || createGroup.isPending}
              onClick={() =>
                createGroup.mutate({ name: groupName.trim() }, { onSuccess: () => setGroupName('') })
              }
            >
              +
            </button>
          </div>
          {createGroup.isError && <p style={{ color: 'var(--danger)' }}>{t.groups.nameExists}</p>}

          <table>
            <tbody>
              {(groups.data ?? []).map((group) => (
                <tr key={group.id}>
                  <td>
                    {group.name}
                    {group.kind === 'system_commute' && (
                      <span className="pill" style={{ marginLeft: 6 }}>
                        {t.groups.systemGroup}
                      </span>
                    )}
                  </td>
                  <td className="faint">{t.groups.tripCount(group.trip_count)}</td>
                  <td>
                    <button
                      className="danger"
                      // The commute pass depends on the system group existing.
                      disabled={group.kind === 'system_commute'}
                      onClick={() => deleteGroup.mutate(group.id)}
                    >
                      {t.app.delete}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h2>{t.groups.tags}</h2>
          <div className="row" style={{ marginBottom: 12 }}>
            <input
              value={tagName}
              onChange={(event) => setTagName(event.target.value)}
              placeholder={t.groups.newTag}
            />
            <button
              disabled={!tagName.trim() || createTag.isPending}
              onClick={() =>
                createTag.mutate({ name: tagName.trim() }, { onSuccess: () => setTagName('') })
              }
            >
              +
            </button>
          </div>
          {createTag.isError && <p style={{ color: 'var(--danger)' }}>{t.groups.nameExists}</p>}

          <div className="row row--wrap">
            {(tags.data ?? []).map((tag) => (
              <span className="pill" key={tag.id}>
                {tag.name}
                <button className="ghost" onClick={() => deleteTag.mutate(tag.id)}>
                  ✕
                </button>
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
