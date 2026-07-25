import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { LogIn } from 'lucide-react'
import { api, ApiError } from '../api/client'

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

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
        else if (e.status === 503) setError('No credentials configured — see server logs.')
        else setError(e.message)
      } else {
        setError('Login failed.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg-page)] px-4">
      <div className="w-full max-w-sm rounded-xl border border-[var(--color-border-strong)] bg-[var(--color-bg-panel)] p-6 shadow-xl">
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
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-[var(--color-text-muted)]">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
            />
          </div>

          {error && (
            <p className="text-xs text-red-400">{error}</p>
          )}

          <button
            type="submit"
            disabled={submitting || !username || !password}
            className="w-full rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
