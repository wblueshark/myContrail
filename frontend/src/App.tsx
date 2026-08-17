import {
  Calendar,
  Download,
  LayoutGrid,
  Layers,
  Lock,
  Luggage,
  Map as MapIcon,
  Moon,
  Settings as SettingsIcon,
  Sun,
  Tag as TagIcon,
  TrainFront,
} from 'lucide-react'
import { useEffect, useState } from 'react'

import { api, getLocalToken, setLocalToken } from '@/api/client'
import { useCapabilities } from '@/api/hooks'
import ExportFlow from '@/components/ExportFlow'
import FenceConfirmModal from '@/components/FenceConfirmModal'
import ImportWizard from '@/components/ImportWizard'
import SettingsDrawer from '@/components/SettingsDrawer'
import { LOCALES, useCopy, useLocaleStore } from '@/i18n'
import CommutePage from '@/pages/CommutePage'
import GroupsPage from '@/pages/GroupsPage'
import MapPage from '@/pages/MapPage'
import OverviewPage from '@/pages/OverviewPage'
import SourcesPage from '@/pages/SourcesPage'
import TimelinePage from '@/pages/TimelinePage'
import TripDetailPage from '@/pages/TripDetailPage'
import TripsPage from '@/pages/TripsPage'
import { installHashListener, useAppStore, type Route } from '@/store/appStore'

const ICON = { size: 20, strokeWidth: 1.5 } as const

/**
 * Gate shown until the local token works.
 *
 * This is not authentication - it is the guard that stops any other process on
 * this machine from reading the location history through the API.
 */
function TokenGate({ onConnected }: { onConnected: () => void }) {
  const t = useCopy()
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
      <form className="dialog" onSubmit={submit} style={{ padding: 20, gap: 12 }}>
        <h1>{t.connection.tokenTitle}</h1>
        <p className="muted">{t.connection.tokenHelp}</p>
        <input
          className="input"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={t.connection.tokenPlaceholder}
          autoFocus
          spellCheck={false}
        />
        {error && <p style={{ color: 'var(--color-danger)' }}>{error}</p>}
        <div className="row row--between" style={{ marginTop: 14 }}>
          <code className="faint">cat ~/.contrail/token</code>
          <button className="btn btn-primary" type="submit" disabled={busy || !value.trim()}>
            {busy ? t.app.loading : t.connection.tokenSubmit}
          </button>
        </div>
      </form>
    </div>
  )
}

function TopBar() {
  const t = useCopy()
  const locale = useLocaleStore((state) => state.locale)
  const setLocale = useLocaleStore((state) => state.setLocale)
  const theme = useAppStore((state) => state.theme)
  const setTheme = useAppStore((state) => state.setTheme)
  const setImportOpen = useAppStore((state) => state.setImportOpen)
  const setSettingsOpen = useAppStore((state) => state.setSettingsOpen)
  const route = useAppStore((state) => state.route)

  const viewTitle: Record<Route['name'], string> = {
    map: t.nav.map,
    overview: t.nav.overview,
    timeline: t.nav.timeline,
    trips: t.nav.trips,
    trip: t.nav.trips,
    groups: t.nav.groups,
    commute: t.nav.commute,
    sources: t.nav.sources,
  }

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <span className="topbar__name">{t.app.name}</span>
        <span className="topbar__tagline">{t.app.tagline}</span>
      </div>
      <div className="topbar__divider" />
      <span className="topbar__view">{viewTitle[route.name]}</span>

      <div className="topbar__actions">
        <span className="topbar__badge">
          <Lock size={13} strokeWidth={1.5} />
          {t.app.noBackgroundLocation}
        </span>

        <div className="seg">
          {LOCALES.map((option) => (
            <label key={option.id} className="seg-opt">
              <input
                type="radio"
                name="locale"
                checked={locale === option.id}
                onChange={() => setLocale(option.id)}
              />
              {option.label}
            </label>
          ))}
        </div>

        <div className="seg">
          <label className="seg-opt" title={t.theme.light}>
            <input
              type="radio"
              name="theme"
              checked={theme === 'light'}
              onChange={() => setTheme('light')}
            />
            <Sun size={14} strokeWidth={1.5} />
          </label>
          <label className="seg-opt" title={t.theme.dark}>
            <input
              type="radio"
              name="theme"
              checked={theme === 'dark'}
              onChange={() => setTheme('dark')}
            />
            <Moon size={14} strokeWidth={1.5} />
          </label>
        </div>

        <button className="btn btn-primary" onClick={() => setImportOpen(true)}>
          <Download size={14} strokeWidth={1.5} />
          {t.nav.import}
        </button>
        <button
          className="btn btn-secondary btn-icon"
          title={t.nav.settings}
          onClick={() => setSettingsOpen(true)}
        >
          <SettingsIcon size={16} strokeWidth={1.5} />
        </button>
      </div>
    </header>
  )
}

function Rail() {
  const t = useCopy()
  const route = useAppStore((state) => state.route)
  const navigate = useAppStore((state) => state.navigate)
  const capabilities = useCapabilities()

  const items: Array<{ route: Route['name']; icon: JSX.Element; label: string }> = [
    { route: 'map', icon: <MapIcon {...ICON} />, label: t.nav.map },
    { route: 'overview', icon: <LayoutGrid {...ICON} />, label: t.nav.overview },
    { route: 'timeline', icon: <Calendar {...ICON} />, label: t.nav.timeline },
    { route: 'trips', icon: <Luggage {...ICON} />, label: t.nav.trips },
    { route: 'groups', icon: <TagIcon {...ICON} />, label: t.nav.groups },
    { route: 'commute', icon: <TrainFront {...ICON} />, label: t.nav.commute },
    { route: 'sources', icon: <Layers {...ICON} />, label: t.nav.sources },
  ]

  return (
    <nav className="rail">
      {items.map((item) => {
        const active = route.name === item.route || (item.route === 'trips' && route.name === 'trip')
        return (
          <button
            key={item.route}
            className="rail__item"
            aria-current={active ? 'page' : undefined}
            onClick={() => navigate({ name: item.route } as Route)}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        )
      })}
      <div className="rail__foot">
        {capabilities.data ? `MVP\n${capabilities.data.mode.toUpperCase()}` : t.nav.modeLocal}
      </div>
    </nav>
  )
}

function CurrentPage() {
  const route = useAppStore((state) => state.route)
  switch (route.name) {
    case 'overview':
      return <OverviewPage />
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
      <TopBar />
      <div className="body">
        <Rail />
        <CurrentPage />
      </div>
      <SettingsDrawer />
      <ImportWizard />
      <FenceConfirmModal />
      <ExportFlow />
    </div>
  )
}
