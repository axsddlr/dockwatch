import { useState } from 'react'
import { useTestAgent } from '../../hooks/useSettings'
import type { AgentConfig } from '../../types'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      {children}
    </div>
  )
}

export function AgentIntegration({
  agents,
  onChange,
}: {
  agents: AgentConfig[]
  onChange: (agents: AgentConfig[]) => void
}) {
  const testMutation = useTestAgent()
  const [testResults, setTestResults] = useState<Record<string, string>>({})

  const update = (index: number, patch: Partial<AgentConfig>) => {
    onChange(agents.map((agent, i) => (i === index ? { ...agent, ...patch } : agent)))
  }

  const addAgent = () => {
    onChange([...agents, { name: '', url: '', token: '', enabled: true }])
  }

  const removeAgent = (index: number) => {
    onChange(agents.filter((_, i) => i !== index))
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Agents</h3>
        <button
          onClick={addAgent}
          className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-border)] transition-colors"
        >
          + Add agent
        </button>
      </div>
      <p className="text-xs text-[var(--color-text-dim)]">
        Each agent runs the dockwatch image on another Docker host (
        <code>dockwatch agent --token &lt;shared&gt;</code>) and exposes that host's
        containers to this instance. The token grants full Docker control on the agent
        host — only connect agents you trust.
      </p>

      {agents.length === 0 && (
        <p className="text-xs text-[var(--color-text-dim)]">No agents configured yet.</p>
      )}

      {agents.map((agent, index) => (
        <div key={index} className="space-y-3 rounded-lg border border-[var(--color-border)] p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-[var(--color-text-muted)]">Agent {index + 1}</span>
            <button
              onClick={() => removeAgent(index)}
              className="text-xs text-red-400 hover:text-red-300 transition-colors"
            >
              Remove
            </button>
          </div>
          <Field label="Name">
            <input
              type="text"
              value={agent.name}
              onChange={(e) => update(index, { name: e.target.value })}
              placeholder="media-pc"
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
            />
          </Field>
          <Field label="URL">
            <input
              type="text"
              value={agent.url}
              onChange={(e) => update(index, { url: e.target.value })}
              placeholder="http://media-pc:8081"
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
            />
          </Field>
          <Field label="Token (shared secret)">
            <input
              type="password"
              value={agent.token}
              onChange={(e) => update(index, { token: e.target.value })}
              placeholder="openssl rand -hex 32"
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
            />
          </Field>
          <label className="flex items-center gap-3">
            <button
              onClick={() => update(index, { enabled: !agent.enabled })}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                agent.enabled ? 'bg-[var(--color-primary)]' : 'bg-[var(--color-border-strong)]'
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
                  agent.enabled ? 'translate-x-[18px]' : 'translate-x-[3px]'
                }`}
              />
            </button>
            <span className="text-sm text-[var(--color-text-primary)]">Enabled</span>
          </label>

          <div className="flex items-center gap-3">
            <button
              onClick={async () => {
                setTestResults((prev) => ({ ...prev, [index]: 'Testing...' }))
                try {
                  const res = await testMutation.mutateAsync({ name: agent.name })
                  setTestResults((prev) => ({
                    ...prev,
                    [index]: `Connected. ${res.containers} container(s) found.`,
                  }))
                } catch (e) {
                  setTestResults((prev) => ({
                    ...prev,
                    [index]: e instanceof Error ? e.message : 'Connection failed',
                  }))
                }
              }}
              disabled={testMutation.isPending || !agent.name || !agent.url || !agent.token}
              className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-border)] transition-colors disabled:opacity-50"
            >
              {testMutation.isPending ? 'Testing...' : 'Test Connection'}
            </button>
            {testResults[index] && (
              <span
                className={`text-xs ${
                  testResults[index].startsWith('Connected') ? 'text-green-400' : 'text-red-400'
                }`}
              >
                {testResults[index]}
              </span>
            )}
          </div>
        </div>
      ))}
    </section>
  )
}
