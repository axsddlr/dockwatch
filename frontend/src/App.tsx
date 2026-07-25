import { Routes, Route } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { DashboardPage } from './pages/DashboardPage'
import { SettingsPage } from './pages/SettingsPage'
import { LoginPage } from './pages/LoginPage'
import { ErrorBoundary } from './components/ErrorBoundary'
import { RequireAuth } from './components/RequireAuth'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <AppShell>
              <ErrorBoundary>
                <Routes>
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                </Routes>
              </ErrorBoundary>
            </AppShell>
          </RequireAuth>
        }
      />
    </Routes>
  )
}
