import { useState } from 'react'
import type { HookSettings } from '../../types'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      {children}
    </div>
  )
}

const PHASES: { key: keyof HookSettings; label: string }[] = [
  { key: 'pre_update', label: 'Pre-update' },
  { key: 'post_update', label: 'Post-update' },
  { key: 'pre_stop', label: 'Pre-stop' },
  { key: 'pre_rollback', label: 'Pre-rollback' },
  { key: 'post_rollback', label: 'Post-rollback' },
]

function splitCommands(lines: string): string[] {
  // Trim each line but keep empty lines while editing so a trailing newline
  // isn't collapsed on every keystroke (which would make it impossible to add
  // a second command). Empty lines are dropped on save.
  return lines.split('\n').map((s) => s.trim())
}

export function HooksConfig({
  hooks,
  containerNames,
  timeoutSeconds,
  user,
  workdir,
  onChange,
  onChangeDefaults,
}: {
  hooks: Record<string, HookSettings>
  containerNames: string[]
  timeoutSeconds: number
  user: string
  workdir: string
  onChange: (hooks: Record<string, HookSettings>) => void
  onChangeDefaults: (field: string, value: string) => void
}) {
  const [newName, setNewName] = useState('')

  const addContainer = () => {
    const name = newName.trim()
    if (!name || hooks[name]) return
    onChange({
      ...hooks,
      [name]: { pre_update: [], post_update: [], pre_stop: [], pre_rollback: [], post_rollback: [] },
    })
    setNewName('')
  }

  const removeContainer = (name: string) => {
    const next = { ...hooks }
    delete next[name]
    onChange(next)
  }

  const updatePhase = (name: string, key: keyof HookSettings, lines: string) => {
    onChange({ ...hooks, [name]: { ...hooks[name], [key]: splitCommands(lines) } })
  }

  const names = Object.keys(hooks).sort()

  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Lifecycle Hooks</h3>
      <p className="text-xs text-[var(--color-text-dim)]">
        Run shell commands around update, stop, and rollback for individual containers. One command
        per line. Requires <code>DOCKWATCH_ENABLE_HOOKS=true</code> on the backend.
      </p>

      <div className="grid grid-cols-3 gap-4">
        <Field label="Default timeout (seconds)">
          <input
            type="number"
            min={1}
            value={timeoutSeconds}
            onChange={(e) => onChangeDefaults('hook_timeout_seconds', e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
        <Field label="Run as user (optional)">
          <input
            type="text"
            value={user}
            onChange={(e) => onChangeDefaults('hook_user', e.target.value)}
            placeholder="e.g. app"
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
        <Field label="Working directory (optional)">
          <input
            type="text"
            value={workdir}
            onChange={(e) => onChangeDefaults('hook_workdir', e.target.value)}
            placeholder="e.g. /srv/app"
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="text"
          value={newName}
          list="hooks-container-names"
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              addContainer()
            }
          }}
          placeholder="Container name"
          className="flex-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
        <datalist id="hooks-container-names">
          {containerNames.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        <button
          onClick={addContainer}
          disabled={!newName.trim() || !!hooks[newName.trim()]}
          className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-border)] transition-colors disabled:opacity-50"
        >
          + Add container
        </button>
      </div>

      {names.length === 0 && (
        <p className="text-xs text-[var(--color-text-dim)]">No per-container hooks configured.</p>
      )}

      {names.map((name) => (
        <div key={name} className="space-y-3 rounded-lg border border-[var(--color-border)] p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-[var(--color-text-muted)]">{name}</span>
            <button
              onClick={() => removeContainer(name)}
              className="text-xs text-red-400 hover:text-red-300 transition-colors"
            >
              Remove
            </button>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {PHASES.map(({ key, label }) => (
              <Field key={key} label={label}>
                <textarea
                  rows={2}
                  value={hooks[name][key].join('\n')}
                  onChange={(e) => updatePhase(name, key, e.target.value)}
                  placeholder="echo before update"
                  className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 font-mono text-xs text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
                />
              </Field>
            ))}
          </div>
        </div>
      ))}
    </section>
  )
}
