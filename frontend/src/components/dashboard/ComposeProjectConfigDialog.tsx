import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { X, AlertTriangle, Settings2 } from 'lucide-react'
import { useDetectCompose, useValidateComposeConfig } from '../../hooks/useComposeDetect'
import { useSettings, useSaveSettings } from '../../hooks/useSettings'

interface ComposeProjectConfigDialogProps {
  containerName: string
  composeProject: string
  open: boolean
  onClose: () => void
}

function parseComposeFiles(filesText: string): string[] {
  return filesText.split('\n').map((f) => f.trim()).filter(Boolean)
}

export function ComposeProjectConfigDialog({
  containerName,
  composeProject,
  open,
  onClose,
}: ComposeProjectConfigDialogProps) {
  const queryClient = useQueryClient()
  const { data: settings } = useSettings()
  const detectMutation = useDetectCompose()
  const validateMutation = useValidateComposeConfig()
  const saveMutation = useSaveSettings()

  const [workdir, setWorkdir] = useState('')
  const [filesText, setFilesText] = useState('')
  const [projectName, setProjectName] = useState(composeProject)
  const [warnings, setWarnings] = useState<string[]>([])
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!open) return
    detectMutation.mutate(containerName, {
      onSuccess: (data) => {
        setWorkdir(data.detected.workdir)
        setFilesText(data.detected.files.join('\n'))
        setProjectName(data.detected.project_name || composeProject)
        setWarnings(data.warnings)
      },
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, containerName])

  useEffect(() => {
    if (!open) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      const files = parseComposeFiles(filesText)
      validateMutation.mutate(
        { name: containerName, cfg: { workdir, files, project_name: projectName } },
        { onSuccess: (data) => setWarnings(data.warnings) },
      )
    }, 400)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workdir, filesText, projectName])

  if (!open) return null

  const handleSave = () => {
    const files = parseComposeFiles(filesText)
    const composeProjects = { ...(settings?.compose_projects ?? {}) }
    composeProjects[composeProject] = { workdir, files, project_name: projectName }
    saveMutation.mutate(
      { compose_projects: composeProjects },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: ['containers'] })
          onClose()
        },
      },
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-xl border border-[var(--color-border-strong)] bg-[var(--color-bg-panel)] p-6 shadow-[0_8px_30px_rgba(0,0,0,0.35)]">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <Settings2 size={18} className="text-[var(--color-primary)]" />
            <h3 className="text-base font-semibold text-[var(--color-text-primary)]">
              Configure compose project &quot;{composeProject}&quot;
            </h3>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-[var(--color-text-muted)] hover:bg-[var(--color-border)] hover:text-[var(--color-text-primary)]"
          >
            <X size={16} />
          </button>
        </div>

        <div className="mt-4 space-y-3">
          {detectMutation.isPending && (
            <div className="text-sm text-[var(--color-text-muted)]">Detecting from container labels...</div>
          )}

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-[var(--color-text-muted)]">Workdir</label>
            <input
              type="text"
              value={workdir}
              onChange={(e) => setWorkdir(e.target.value)}
              placeholder="/path/to/compose/project"
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-[var(--color-text-muted)]">Compose files (one per line)</label>
            <textarea
              value={filesText}
              onChange={(e) => setFilesText(e.target.value)}
              placeholder="compose.yaml"
              rows={3}
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm font-mono text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-[var(--color-text-muted)]">Project name</label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
            />
          </div>

          {warnings.length > 0 && (
            <div className="space-y-1 rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-sm text-yellow-400">
              {warnings.map((w, i) => (
                <div key={i} className="flex items-start gap-2">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                  <span>{w}</span>
                </div>
              ))}
            </div>
          )}

          {saveMutation.isError && (
            <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
              <AlertTriangle size={14} />
              {saveMutation.error instanceof Error ? saveMutation.error.message : 'Save failed'}
            </div>
          )}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-border)] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saveMutation.isPending || !workdir}
            className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {saveMutation.isPending ? 'Saving...' : warnings.length > 0 ? 'Save anyway' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
