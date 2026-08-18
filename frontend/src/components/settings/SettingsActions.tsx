import React, { useState } from 'react'
import { Send, Save } from 'lucide-react'
import { useTestNotification } from '../../hooks/useSettings'

interface SettingsActionsProps {
  onSave: () => void
  saving: boolean
  saveMessage: string | null
}

export function SettingsActions({ onSave, saving, saveMessage }: SettingsActionsProps) {
  const testMutation = useTestNotification()
  const [testResult, setTestResult] = useState<string | null>(null)

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        onClick={onSave}
        disabled={saving}
        className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        <Save size={16} />
        {saving ? 'Saving...' : 'Save Settings'}
      </button>

      <button
        onClick={async () => {
          setTestResult(null)
          try {
            await testMutation.mutateAsync()
            setTestResult('Test notification sent.')
          } catch (e) {
            setTestResult(e instanceof Error ? e.message : 'Failed')
          }
        }}
        disabled={testMutation.isPending}
        className="inline-flex items-center gap-2 rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-border)] transition-colors disabled:opacity-50"
      >
        <Send size={16} />
        {testMutation.isPending ? 'Sending...' : 'Test Notification'}
      </button>

      {saveMessage && (
        <span className={`text-xs ${saveMessage.includes('Failed') || saveMessage.includes('Error') ? 'text-red-400' : 'text-green-400'}`}>
          {saveMessage}
        </span>
      )}
      {testResult && (
        <span className={`text-xs ${testResult.includes('Failed') || testResult.includes('error') ? 'text-red-400' : 'text-green-400'}`}>
          {testResult}
        </span>
      )}
    </div>
  )
}
