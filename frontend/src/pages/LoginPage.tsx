import { useState, useEffect } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { LogIn } from 'lucide-react'
import { api, ApiError } from '../api/client'

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [registerEnabled, setRegisterEnabled] = useState(false)

  useEffect(() => {
    api.auth.registrationEnabled().then((r) => setRegisterEnabled(r.enabled)).catch(() => {})
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.auth.login(username, password)
      const params = new URLSearchParams(location.search)
      navigate(params.get('next') || '/', { replace: true })
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 401) setError('Invalid username or password.')
        else if (e.status === 429) setError('Too many attempts. Try again later.')
        else setError(e.message)
      } else {
        setError('Login failed.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[var(--color-bg-page)] px-4">
      <div
        className="pointer-events-none absolute left-1/2 top-1/2 h-[600px] w-[600px] -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{ background: 'radial-gradient(circle, rgba(196,69,60,0.06), transparent 70%)' }}
      />
      <div className="relative w-full max-w-sm rounded-xl border border-[var(--color-border-strong)] bg-[var(--color-bg-panel)] p-6 shadow-[0_8px_30px_rgba(0,0,0,0.35)]">
        <div className="mb-6 flex items-center gap-2">
          <LogIn size={20} className="text-[var(--color-primary)]" />
          <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">dockwatch</h1>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-[var(--color-text-muted)]">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              autoComplete="username"
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)]/60 focus:outline-none focus:ring-1 focus:ring-[var(--color-primary)]/20"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-[var(--color-text-muted)]">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)]/60 focus:outline-none focus:ring-1 focus:ring-[var(--color-primary)]/20"
            />
          </div>

          {error && (
            <p className="text-xs text-red-400">{error}</p>
          )}

          <button
            type="submit"
            disabled={submitting || !username || !password}
            className="w-full rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        {registerEnabled && (
          <div className="mt-4 text-center">
            <Link to="/register" className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-primary)] transition-colors">
              Create an account
            </Link>
          </div>
        )}
      </div>
    </div>
  )
}
