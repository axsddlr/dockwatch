import { useState } from 'react'
import { useGenerateAgentToken, useTestAgent } from '../../hooks/useSettings'
import type { AgentConfig } from '../../types'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      {children}
    </div>
  )
}

function isSaved(agent: AgentConfig, savedAgents: AgentConfig[]): boolean {
  return savedAgents.some(
    (saved) =>
      saved.name === agent.name && saved.url === agent.url && saved.token === agent.token,
  )
}

// Turns a raw AgentError message into something the operator can act on,
// instead of a passthrough httpx exception string.
function describeTestError(message: string): string {
  if (/401/.test(message)) return 'Token mismatch — check the token matches on both sides.'
  if (/429/.test(message)) return 'Agent is rate-limiting — too many recent failed attempts.'
  if (/timed?.?out|timeout/i.test(message)) return 'Connection timed out — check the host/port and that the agent is running.'
  if (/connect|refused|resolve|name or service/i.test(message)) {
    return 'Could not reach the agent at this URL — check host, port, and firewall.'
  }
  return message
}

function deploySnippet(agent: AgentConfig): string {
  const token = agent.token || '<paste-token-here>'
  return `docker run -d --name dockwatch-agent \\
  -v /var/run/docker.sock:/var/run/docker.sock \\
  -p 8081:8081 \\
  -e DOCKWATCH_AGENT_TOKEN=${token} \\
  ghcr.io/axsddlr/dockwatch:latest dockwatch agent --host 0.0.0.0 --port 8081`
}

export function AgentIntegration({
  agents,
  savedAgents,
  onChange,
  onSave,
}: {
  agents: AgentConfig[]
  savedAgents: AgentConfig[]
  onChange: (agents: AgentConfig[]) => void
  onSave: () => Promise<boolean>
}) {
  const testMutation = useTestAgent()
  const generateTokenMutation = useGenerateAgentToken()
  const [testResults, setTestResults] = useState<Record<string, string>>({})
  const [savingIndex, setSavingIndex] = useState<number | null>(null)

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
            <div className="flex gap-2">
              <input
                type="password"
                value={agent.token}
                onChange={(e) => update(index, { token: e.target.value })}
                placeholder="openssl rand -hex 32"
                className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
              />
              <button
                onClick={async () => {
                  const res = await generateTokenMutation.mutateAsync()
                  update(index, { token: res.token })
                }}
                disabled={generateTokenMutation.isPending}
                className="shrink-0 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-border)] transition-colors disabled:opacity-50"
              >
                Generate
              </button>
            </div>
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

          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3">
            <p className="mb-1.5 text-xs font-medium text-[var(--color-text-muted)]">
              Deploy this agent
            </p>
            <pre className="overflow-x-auto whitespace-pre-wrap break-all text-xs text-[var(--color-text-primary)]">
              {deploySnippet(agent)}
            </pre>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={async () => {
                const runTest = async () => {
                  setTestResults((prev) => ({ ...prev, [index]: 'Testing...' }))
                  try {
                    const res = await testMutation.mutateAsync({ name: agent.name })
                    setTestResults((prev) => ({
                      ...prev,
                      [index]: `Connected. ${res.containers} container(s) found.`,
                    }))
                  } catch (e) {
                    const message = e instanceof Error ? e.message : 'Connection failed'
                    setTestResults((prev) => ({ ...prev, [index]: describeTestError(message) }))
                  }
                }

                if (!isSaved(agent, savedAgents)) {
                  setSavingIndex(index)
                  const saved = await onSave()
                  setSavingIndex(null)
                  if (!saved) return
                }
                await runTest()
              }}
              disabled={testMutation.isPending || savingIndex === index || !agent.name || !agent.url || !agent.token}
              className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-border)] transition-colors disabled:opacity-50"
            >
              {savingIndex === index
                ? 'Saving...'
                : testMutation.isPending
                  ? 'Testing...'
                  : isSaved(agent, savedAgents)
                    ? 'Test Connection'
                    : 'Save & Test'}
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
