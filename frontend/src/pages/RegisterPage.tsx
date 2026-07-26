import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { UserPlus, ArrowLeft } from 'lucide-react'
import { api, ApiError } from '../api/client'

export function RegisterPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.auth.register(username, password)
      navigate('/', { replace: true })
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 403) setError('Registration is disabled.')
        else if (e.status === 409) setError('Username already exists.')
        else if (e.status === 422) setError(e.message)
        else setError('Registration failed.')
      } else {
        setError('Registration failed.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg-page)] px-4">
      <div className="w-full max-w-sm rounded-xl border border-[var(--color-border-strong)] bg-[var(--color-bg-panel)] p-6 shadow-xl">
        <div className="mb-6 flex items-center gap-2">
          <UserPlus size={20} className="text-[var(--color-primary)]" />
          <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Create account</h1>
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
              autoComplete="new-password"
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
            {submitting ? 'Creating account...' : 'Create account'}
          </button>
        </form>

        <div className="mt-4 text-center">
          <Link to="/login" className="inline-flex items-center gap-1 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors">
            <ArrowLeft size={12} />
            Back to sign in
          </Link>
        </div>
      </div>
    </div>
  )
}
