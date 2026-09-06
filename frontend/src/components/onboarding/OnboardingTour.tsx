import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ACTIONS, EVENTS, Joyride, STATUS, type EventHandler, type Step } from 'react-joyride'
import { api } from '../../api/client'
import { getSession, hasPermission } from '../RequireAuth'

type TourStep = Step & { data: { route: string } }

const SETTINGS_TOUR_SEEN_KEY = 'dockwatch:settings-tour-seen'

function isSettingsRoute(pathname: string) {
  return pathname.startsWith('/settings') || pathname.startsWith('/users')
}

function buildDashboardSteps(): TourStep[] {
  return [
    {
      target: '[data-tour="stat-cards"]',
      content: 'These cards summarize your containers: total, up-to-date, outdated, and pinned.',
      data: { route: '/' },
    },
    {
      target: '[data-tour="scan-button"]',
      content: 'Click Refresh any time to re-scan your running containers for updates. Nothing scans automatically without this.',
      data: { route: '/' },
    },
    {
      target: '[data-tour="source-selector"]',
      content: 'Switch between Local containers, Portainer-managed stacks, or both.',
      data: { route: '/' },
    },
    {
      target: '[data-tour="auto-refresh"]',
      content: 'Turn this on to have dockwatch re-check automatically on an interval.',
      data: { route: '/' },
    },
    {
      target: '[data-tour="filter-bar"]',
      content: 'Filter the table down to just the statuses you care about, like Outdated.',
      data: { route: '/' },
    },
    {
      target: '[data-tour="container-table"]',
      content: 'Each row is a container. Once you have scanned, you can update, roll back, pin, or inspect any of them here.',
      data: { route: '/' },
    },
    {
      target: '[data-tour="action-menu"]',
      content: 'The kebab menu on each row holds less-frequent actions: logs, history, restart, and delete.',
      data: { route: '/' },
    },
  ]
}

function buildSettingsSteps(): TourStep[] {
  const settingsSteps: TourStep[] = hasPermission('manage_settings')
    ? [
        {
          target: '[data-tour="settings-monitoring"]',
          content: 'Choose which containers to ignore or auto-update.',
          data: { route: '/settings' },
        },
        {
          target: '[data-tour="settings-tags"]',
          content: 'Restrict which image tags count as updates, e.g. only stable semver tags.',
          data: { route: '/settings' },
        },
        {
          target: '[data-tour="settings-notify-delivery"]',
          content: 'Wire up a webhook, Discord, or ntfy endpoint to receive notifications.',
          data: { route: '/settings' },
        },
        {
          target: '[data-tour="settings-notify-rules"]',
          content: 'Control which events actually trigger a notification.',
          data: { route: '/settings' },
        },
        {
          target: '[data-tour="settings-scheduler"]',
          content: 'Set how often dockwatch checks for updates on its own.',
          data: { route: '/settings' },
        },
        {
          target: '[data-tour="settings-advanced-toggle"]',
          content: 'Click here to expand Portainer and Trivy integration settings.',
          data: { route: '/settings' },
        },
      ]
    : []

  const usersSteps: TourStep[] = hasPermission('manage_users')
    ? [
        {
          target: '[data-tour="nav-users"]',
          content: 'Manage who can access this dockwatch instance and what they can do.',
          data: { route: '/settings' },
        },
        {
          target: '[data-tour="users-create"]',
          content: 'Invite teammates by creating an account for them here.',
          data: { route: '/users' },
        },
        {
          target: '[data-tour="users-table"]',
          content: "That's the tour! You can replay it anytime from the help icon in the header.",
          data: { route: '/users' },
        },
      ]
    : []

  return [...settingsSteps, ...usersSteps]
}

function settingsTourSeen() {
  try {
    return localStorage.getItem(SETTINGS_TOUR_SEEN_KEY) === 'true'
  } catch {
    return false
  }
}

function markSettingsTourSeen() {
  try {
    localStorage.setItem(SETTINGS_TOUR_SEEN_KEY, 'true')
  } catch {
    // ignore storage failures
  }
}

export function OnboardingTour() {
  const navigate = useNavigate()
  const location = useLocation()
  const session = getSession()

  const [activeTour, setActiveTour] = useState<'dashboard' | 'settings' | null>(null)
  const [stepIndex, setStepIndex] = useState(0)

  const dashboardSteps = useMemo(buildDashboardSteps, [])
  const settingsSteps = useMemo(buildSettingsSteps, [])
  const steps = activeTour === 'dashboard' ? dashboardSteps : activeTour === 'settings' ? settingsSteps : []
  const run = activeTour !== null

  useEffect(() => {
    if (activeTour !== null) return
    if (location.pathname === '/' && session?.onboarding_seen === false) {
      setActiveTour('dashboard')
      setStepIndex(0)
    } else if (isSettingsRoute(location.pathname) && !settingsTourSeen()) {
      setActiveTour('settings')
      setStepIndex(0)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

  const finish = () => {
    if (activeTour === 'dashboard' && session && !session.onboarding_seen) {
      session.onboarding_seen = true
      api.users.completeOnboarding().catch(() => {})
    }
    if (activeTour === 'settings') {
      markSettingsTourSeen()
    }
    setActiveTour(null)
  }

  const handleEvent: EventHandler = (data) => {
    const { status, type, index, action } = data

    if (type === EVENTS.TARGET_NOT_FOUND) {
      const nextIndex = index + 1
      if (nextIndex >= steps.length) {
        finish()
        return
      }
      setStepIndex(nextIndex)
      return
    }

    if (status === STATUS.FINISHED || status === STATUS.SKIPPED) {
      finish()
      return
    }

    if (type === EVENTS.STEP_AFTER) {
      const nextIndex = index + (action === ACTIONS.PREV ? -1 : 1)
      const nextStep = steps[nextIndex]
      if (nextStep && nextStep.data.route !== location.pathname) {
        navigate(nextStep.data.route)
      }
      setStepIndex(nextIndex)
    }
  }

  useEffect(() => {
    const restart = () => {
      if (isSettingsRoute(location.pathname)) {
        setActiveTour('settings')
      } else {
        if (location.pathname !== '/') navigate('/')
        setActiveTour('dashboard')
      }
      setStepIndex(0)
    }
    window.addEventListener('dockwatch:restart-tour', restart)
    return () => window.removeEventListener('dockwatch:restart-tour', restart)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

  if (dashboardSteps.length === 0 && settingsSteps.length === 0) return null

  return (
    <Joyride
      steps={steps}
      run={run}
      stepIndex={stepIndex}
      continuous
      onEvent={handleEvent}
      options={{
        zIndex: 10000,
        showProgress: true,
        buttons: ['back', 'close', 'primary', 'skip'],
        skipBeacon: true,
        arrowColor: 'var(--color-bg-panel)',
        backgroundColor: 'var(--color-bg-panel)',
        overlayColor: 'rgba(0, 0, 0, 0.6)',
        primaryColor: 'var(--color-primary)',
        textColor: 'var(--color-text-primary)',
      }}
      styles={{
        tooltip: {
          borderRadius: 12,
          border: '1px solid var(--color-border-strong)',
          padding: 20,
        },
        tooltipTitle: {
          fontSize: 15,
          fontWeight: 600,
          color: 'var(--color-text-primary)',
        },
        tooltipContent: {
          fontSize: 13.5,
          lineHeight: 1.5,
          color: 'var(--color-text-muted)',
        },
        buttonPrimary: {
          backgroundColor: 'var(--color-primary)',
          color: '#fff',
          borderRadius: 8,
          fontSize: 13,
          padding: '8px 14px',
        },
        buttonBack: {
          color: 'var(--color-text-muted)',
          fontSize: 13,
        },
        buttonSkip: {
          color: 'var(--color-text-dim)',
          fontSize: 13,
        },
        buttonClose: {
          color: 'var(--color-text-dim)',
        },
      }}
    />
  )
}
