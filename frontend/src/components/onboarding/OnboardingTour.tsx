import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ACTIONS, EVENTS, Joyride, STATUS, type EventHandler, type Step } from 'react-joyride'
import { api } from '../../api/client'
import { getSession, hasPermission } from '../RequireAuth'

type TourStep = Step & { data: { route: string } }

function buildSteps(): TourStep[] {
  const dashboardSteps: TourStep[] = [
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

  const settingsSteps: TourStep[] = hasPermission('manage_settings')
    ? [
        {
          target: '[data-tour="nav-settings"]',
          content: "Settings is where you configure how dockwatch monitors and notifies you.",
          data: { route: '/' },
        },
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

  return [...dashboardSteps, ...settingsSteps, ...usersSteps]
}

export function OnboardingTour() {
  const navigate = useNavigate()
  const location = useLocation()
  const session = getSession()

  const [run, setRun] = useState(() => session?.onboarding_seen === false)
  const [stepIndex, setStepIndex] = useState(0)

  const steps = useMemo(buildSteps, [])

  const finish = () => {
    setRun(false)
    if (session && !session.onboarding_seen) {
      session.onboarding_seen = true
      api.users.completeOnboarding().catch(() => {})
    }
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
      if (location.pathname !== '/') navigate('/')
      setStepIndex(0)
      setRun(true)
    }
    window.addEventListener('dockwatch:restart-tour', restart)
    return () => window.removeEventListener('dockwatch:restart-tour', restart)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (steps.length === 0) return null

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
      }}
    />
  )
}
