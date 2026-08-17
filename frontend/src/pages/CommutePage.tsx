/**
 * Commute: detected OD pairs and what to do about the days they cover.
 *
 * The rule that shapes the whole page: only a PURE commute day may be deleted.
 * A mixed day also holds other places and photos, and "delete my commute" must
 * never take the evening concert with it (02 section 8b). The mixed card
 * therefore has no delete control at all, and says why.
 */

import { AlertTriangle, ArrowLeftRight } from 'lucide-react'
import { useState } from 'react'

import { useCommuteAction, useCommuteOds, useCommuteTrips } from '@/api/hooks'
import Blueprint from '@/components/Blueprint'
import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

function hhmm(hour: number | null): string {
  if (hour === null) return '—'
  const hours = Math.floor(hour)
  const minutes = Math.round((hour - hours) * 60)
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

export default function CommutePage() {
  const t = useCopy()
  const ods = useCommuteOds()
  const pure = useCommuteTrips('pure')
  const mixed = useCommuteTrips('mixed')
  const action = useCommuteAction()
  const setSettingsOpen = useAppStore((state) => state.setSettingsOpen)
  const setTimeRange = useAppStore((state) => state.setTimeRange)
  const navigate = useAppStore((state) => state.navigate)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const pureTrips = pure.data ?? []
  const mixedTrips = mixed.data ?? []
  const mixedPlaces = mixedTrips.reduce((sum, trip) => sum + trip.place_count, 0)
  const mixedPhotos = mixedTrips.reduce((sum, trip) => sum + trip.photo_count, 0)

  const run = async (ids: string[], kind: 'collapse' | 'to_normal' | 'delete') => {
    if (!ids.length) return
    await action.mutateAsync({ trip_ids: ids, action: kind })
    setNotice(
      kind === 'collapse'
        ? t.commute.collapsed(ids.length)
        : kind === 'to_normal'
          ? t.commute.converted(ids.length)
          : t.commute.deleted(ids.length),
    )
    setConfirmDelete(false)
  }

  return (
    <div className="page page--scroll">
      <div className="page__title">
        <h1>{t.commute.title}</h1>
        <span className="muted" style={{ fontSize: 12, paddingBottom: 4 }}>
          {t.commute.note}
        </span>
      </div>

      {ods.isSuccess && ods.data.length === 0 && (
        <p className="muted" style={{ marginTop: 16 }}>
          {t.commute.empty}
        </p>
      )}

      <div className="grid grid--wide" style={{ marginTop: 16 }}>
        {(ods.data ?? []).map((od) => {
          const total = od.evidence.total_distance_m ?? null
          const unknown = od.evidence.distance_unknown_count ?? 0
          return (
            <Blueprint key={od.id} style={{ padding: '14px 15px' }}>
              <div className="row" style={{ alignItems: 'baseline', gap: 10 }}>
                <ArrowLeftRight size={18} strokeWidth={1.5} color="var(--color-accent)" />
                <span style={{ fontFamily: 'var(--font-heading)', fontSize: 20 }}>
                  {(od.from.label ?? t.fences.kindHome) + ' → ' + (od.to.label ?? t.fences.kindWork)}
                </span>
                <span
                  className="num"
                  style={{
                    marginLeft: 'auto',
                    fontFamily: 'var(--font-heading)',
                    fontSize: 22,
                    color: 'var(--color-accent)',
                  }}
                >
                  {od.occurrence}
                </span>
                <span className="muted" style={{ fontSize: 12 }}>
                  {t.commute.times}
                </span>
              </div>
              <div className="muted num" style={{ fontSize: 11.5 }}>
                {od.evidence.first_seen ?? '—'} ~ {od.evidence.last_seen ?? '—'}
              </div>

              <div className="plate plate--3" style={{ marginTop: 12 }}>
                <div className="plate__cell">
                  <div className="plate__value">{hhmm(od.depart_hour_mean)}</div>
                  <div className="plate__label">{t.commute.depart}</div>
                </div>
                <div className="plate__cell">
                  <div className="plate__value">
                    {Math.round((od.evidence.median_duration_s ?? 0) / 60)} {t.settings.minutes}
                  </div>
                  <div className="plate__label">{t.commute.duration}</div>
                </div>
                <div className="plate__cell">
                  <div className="plate__value">
                    {total === null ? '—' : `${Math.round(total / 1000).toLocaleString()} km`}
                  </div>
                  <div className="plate__label">{t.commute.total}</div>
                </div>
              </div>

              {unknown > 0 && (
                <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>
                  {t.commute.unknownDistance(unknown)}
                </div>
              )}

              <div className="row num" style={{ marginTop: 10, fontSize: 11.5, opacity: 0.75 }}>
                <span className="muted">{t.commute.samples}</span>
                {(od.evidence.sample_dates ?? []).join(' / ')}
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ marginLeft: 'auto' }}
                  onClick={() => {
                    const dates = od.evidence.sample_dates ?? []
                    if (dates.length) {
                      setTimeRange(`${dates[0]}T00:00:00Z`, `${dates[dates.length - 1]}T23:59:59Z`)
                    }
                    navigate({ name: 'map' })
                  }}
                >
                  {t.commute.preview}
                </button>
              </div>
            </Blueprint>
          )
        })}
      </div>

      <div className="kicker" style={{ margin: '26px 0 10px' }}>
        {t.commute.affected}
      </div>

      {notice && <div className="notice notice--accent" style={{ marginBottom: 12 }}>{notice}</div>}

      <div className="grid grid--wide">
        <Blueprint style={{ padding: '14px 15px' }}>
          <div className="row" style={{ alignItems: 'baseline', gap: 10 }}>
            <span style={{ width: 7, height: 7, background: 'var(--color-accent)', flex: 'none' }} />
            <span style={{ fontFamily: 'var(--font-heading)', fontSize: 19 }}>{t.commute.pure}</span>
            <span
              className="num"
              style={{ marginLeft: 'auto', fontFamily: 'var(--font-heading)', fontSize: 22 }}
            >
              {pureTrips.length}
            </span>
            <span className="muted" style={{ fontSize: 12 }}>
              {t.commute.days}
            </span>
          </div>
          <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
            {t.commute.pureNote}
          </div>
          <div className="row" style={{ gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => run(pureTrips.map((trip) => trip.id), 'collapse')}
            >
              {t.commute.collapse}
            </button>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => run(pureTrips.map((trip) => trip.id), 'to_normal')}
            >
              {t.commute.convert}
            </button>
            <button
              className="btn btn-danger btn-sm"
              disabled={!pureTrips.length}
              onClick={() => setConfirmDelete(true)}
            >
              {t.commute.delete}
            </button>
          </div>
        </Blueprint>

        <Blueprint style={{ padding: '14px 15px' }}>
          <div className="row" style={{ alignItems: 'baseline', gap: 10 }}>
            <span style={{ width: 7, height: 7, background: 'var(--color-danger)', flex: 'none' }} />
            <span style={{ fontFamily: 'var(--font-heading)', fontSize: 19 }}>{t.commute.mixed}</span>
            <span
              className="num"
              style={{ marginLeft: 'auto', fontFamily: 'var(--font-heading)', fontSize: 22 }}
            >
              {mixedTrips.length}
            </span>
            <span className="muted" style={{ fontSize: 12 }}>
              {t.commute.days}
            </span>
          </div>
          <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
            {t.commute.mixedNote}
          </div>
          <div className="row" style={{ gap: 6, marginTop: 12 }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => run(mixedTrips.map((trip) => trip.id), 'collapse')}
            >
              {t.commute.collapseCommuteOnly}
            </button>
          </div>
          {/* No delete control here, by design - and the reason is on screen. */}
          <div className="notice notice--danger" style={{ marginTop: 12 }}>
            <AlertTriangle size={15} strokeWidth={1.5} color="var(--color-danger)" />
            {t.commute.mixedWarn(mixedPlaces, mixedPhotos)}
          </div>
        </Blueprint>
      </div>

      <button
        className="btn btn-ghost btn-sm"
        style={{ marginTop: 18 }}
        onClick={() => setSettingsOpen(true)}
      >
        {t.commute.params} →
      </button>

      {confirmDelete && (
        <div className="backdrop" onClick={() => setConfirmDelete(false)}>
          <div className="dialog" onClick={(event) => event.stopPropagation()}>
            <div className="dialog__head">
              <span className="dialog__title">{t.commute.deleteTitle(pureTrips.length)}</span>
            </div>
            <div className="dialog__body">{t.commute.deleteBody(pureTrips.length)}</div>
            <div className="dialog__foot" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-secondary" onClick={() => setConfirmDelete(false)}>
                {t.app.cancel}
              </button>
              <button
                className="btn btn-primary"
                style={{ background: 'var(--color-danger)', borderColor: 'var(--color-danger)' }}
                onClick={() => run(pureTrips.map((trip) => trip.id), 'delete')}
              >
                {t.commute.delete}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
