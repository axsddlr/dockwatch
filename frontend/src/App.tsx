import { Routes, Route } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { DashboardPage } from './pages/DashboardPage'
import { SettingsPage } from './pages/SettingsPage'
import { ErrorBoundary } from './components/ErrorBoundary'

export default function App() {
  return (
    <AppShell>
      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </ErrorBoundary>
    </AppShell>
  )
}
