import { useEffect, useState } from 'react'

import { api, getLocalToken, setLocalToken } from '@/api/client'
import { t } from '@/i18n/zh'
import CommutePage from '@/pages/CommutePage'
import GroupsPage from '@/pages/GroupsPage'
import MapPage from '@/pages/MapPage'
import SettingsPage from '@/pages/SettingsPage'
import SourcesPage from '@/pages/SourcesPage'
import TimelinePage from '@/pages/TimelinePage'
import TripDetailPage from '@/pages/TripDetailPage'
import TripsPage from '@/pages/TripsPage'
import { installHashListener, useAppStore, type Route } from '@/store/appStore'

const NAV: Array<{ route: Route['name']; glyph: string; label: string }> = [
  { route: 'map', glyph: '🗺️', label: t.nav.map },
  { route: 'timeline', glyph: '📅', label: t.nav.timeline },
  { route: 'trips', glyph: '🧳', label: t.nav.trips },
  { route: 'groups', glyph: '🏷️', label: t.nav.groups },
  { route: 'commute', glyph: '🚇', label: t.nav.commute },
  { route: 'sources', glyph: '📥', label: t.nav.sources },
  { route: 'settings', glyph: '⚙️', label: t.nav.settings },
]

/**
 * Gate shown until the local token works.
 *
 * This is not authentication - it is the guard that stops any other process on
 * this machine from reading the location history through the API.
 */
function TokenGate({ onConnected }: { onConnected: () => void }) {
  const [value, setValue] = useState(getLocalToken())
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setLocalToken(value)
    try {
      await api.trips({ limit: 1 })
      onConnected()
    } catch (caught) {
      const status = (caught as { status?: number }).status
      setError(status === 401 ? t.connection.tokenInvalid : t.connection.backendDown)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="backdrop">
      <form className="dialog" onSubmit={submit}>
        <h1>{t.connection.tokenTitle}</h1>
        <p className="muted">{t.connection.tokenHelp}</p>
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={t.connection.tokenPlaceholder}
          autoFocus
          spellCheck={false}
        />
        {error && <p style={{ color: 'var(--danger)' }}>{error}</p>}
        <div className="row row--between" style={{ marginTop: 14 }}>
          <code className="faint">cat ~/.contrail/token</code>
          <button className="primary" type="submit" disabled={busy || !value.trim()}>
            {busy ? t.app.loading : t.connection.tokenSubmit}
          </button>
        </div>
      </form>
    </div>
  )
}

function Rail() {
  const route = useAppStore((state) => state.route)
  const navigate = useAppStore((state) => state.navigate)

  return (
    <nav className="rail">
      {NAV.map((item) => {
        const active = route.name === item.route || (item.route === 'trips' && route.name === 'trip')
        return (
          <button
            key={item.route}
            className="rail__item"
            aria-current={active ? 'page' : undefined}
            onClick={() => navigate({ name: item.route } as Route)}
          >
            <span className="rail__glyph" aria-hidden>
              {item.glyph}
            </span>
            {item.label}
          </button>
        )
      })}
    </nav>
  )
}

function CurrentPage() {
  const route = useAppStore((state) => state.route)
  switch (route.name) {
    case 'timeline':
      return <TimelinePage />
    case 'trips':
      return <TripsPage />
    case 'trip':
      return <TripDetailPage tripId={route.id} />
    case 'groups':
      return <GroupsPage />
    case 'commute':
      return <CommutePage />
    case 'sources':
      return <SourcesPage />
    case 'settings':
      return <SettingsPage />
    default:
      return <MapPage />
  }
}

export default function App() {
  const connected = useAppStore((state) => state.connected)
  const setConnected = useAppStore((state) => state.setConnected)

  useEffect(() => installHashListener(), [])

  useEffect(() => {
    // A token may already be stored from a previous session; verify it rather
    // than assuming, so a rotated token surfaces the gate immediately.
    if (!getLocalToken()) return
    void api
      .trips({ limit: 1 })
      .then(() => setConnected(true))
      .catch(() => setConnected(false))
  }, [setConnected])

  if (!connected) return <TokenGate onConnected={() => setConnected(true)} />

  return (
    <div className="shell">
      <Rail />
      <CurrentPage />
    </div>
  )
}
