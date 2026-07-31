import { type ReactNode, useEffect, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutGrid,
  Settings,
  Users,
  Menu,
  X,
  Hexagon,
  LogOut,
} from 'lucide-react'
import { api } from '../../api/client'
import { hasPermission } from '../RequireAuth'

export function AppShell({ children }: { children: ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [version, setVersion] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    fetch('/api/version')
      .then((r) => r.json())
      .then((d) => setVersion(d.version ?? ''))
      .catch(() => {})
  }, [])

  const handleLogout = async () => {
    try {
      await api.auth.logout()
    } finally {
      navigate('/login', { replace: true })
    }
  }

  const navItems = [{ label: 'Dashboard', path: '/', icon: LayoutGrid }]

  if (hasPermission('manage_settings')) {
    navItems.push({ label: 'Settings', path: '/settings', icon: Settings })
  }
  if (hasPermission('manage_users')) {
    navItems.push({ label: 'Users', path: '/users', icon: Users })
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-40 border-b border-[var(--color-border)] bg-[var(--color-bg-panel)]/95 backdrop-blur supports-[backdrop-filter]:bg-[var(--color-bg-panel)]/80">
        <div className="mx-auto flex h-12 max-w-[1260px] items-center justify-between px-4">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setDrawerOpen(!drawerOpen)}
              className="rounded-lg p-1.5 text-[var(--color-primary)] hover:bg-[var(--color-border)] transition-colors lg:hidden"
            >
              {drawerOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
            <button
              onClick={() => navigate('/')}
              className="flex items-center gap-2 text-lg font-semibold tracking-tight text-[var(--color-primary)]"
            >
              <Hexagon size={20} className="text-[var(--color-primary)]" />
              dockwatch
            </button>
          </div>
          <div className="flex items-center gap-3">
            {version && <span className="text-xs text-[var(--color-text-muted)]">v{version}</span>}
            <button
              onClick={handleLogout}
              title="Log out"
              className="rounded-lg p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-border)] hover:text-[var(--color-text-primary)] transition-colors"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-[1260px] flex-1">
        <aside
          className={`fixed inset-y-0 left-0 z-30 w-56 transform border-r border-[var(--color-border)] bg-[var(--color-bg-panel)] pt-12 transition-transform duration-200 ease-in-out lg:sticky lg:block lg:translate-x-0 ${
            drawerOpen ? 'translate-x-0' : '-translate-x-full'
          }`}
        >
          <nav className="flex flex-col gap-1 p-4 pt-6">
            {navItems.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === '/'}
                onClick={() => setDrawerOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-[var(--color-primary)]/10 text-[var(--color-primary)]'
                      : 'text-[var(--color-text-muted)] hover:bg-[var(--color-border)] hover:text-[var(--color-text-primary)]'
                  }`
                }
              >
                <item.icon size={18} />
                {item.label}
              </NavLink>
            ))}
          </nav>
        </aside>

        {drawerOpen && (
          <div
            className="fixed inset-0 z-20 bg-black/50 lg:hidden"
            onClick={() => setDrawerOpen(false)}
          />
        )}

        <main className="flex-1 min-w-0 px-4 py-6 lg:px-8">
          {children}
        </main>
      </div>
    </div>
  )
}
