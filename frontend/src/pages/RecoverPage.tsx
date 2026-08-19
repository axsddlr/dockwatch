import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { KeyRound, ArrowLeft } from 'lucide-react'
import { api, ApiError } from '../api/client'

export function RecoverPage() {
  const navigate = useNavigate()
  const [token, setToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.auth.recover(token, newPassword)
      navigate('/login', { replace: true })
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 429) setError('Too many attempts. Try again later.')
        else setError(e.message)
      } else {
        setError('Password recovery failed.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg-page)] px-4">
      <div className="w-full max-w-sm rounded-xl border border-[var(--color-border-strong)] bg-[var(--color-bg-panel)] p-6 shadow-[0_8px_30px_rgba(0,0,0,0.35)]">
        <div className="mb-6 flex items-center gap-2">
          <KeyRound size={20} className="text-[var(--color-primary)]" />
          <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Recover account</h1>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-[var(--color-text-muted)]">Recovery token</label>
            <input
              type="text"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoFocus
              autoComplete="off"
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-[var(--color-text-muted)]">New password</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
            />
          </div>

          {error && (
            <p className="text-xs text-red-400">{error}</p>
          )}

          <button
            type="submit"
            disabled={submitting || !token || !newPassword}
            className="w-full rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Resetting...' : 'Reset password'}
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
