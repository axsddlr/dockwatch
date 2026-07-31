export interface ContainerInfo {
  name: string
  container_id: string
  image_ref: string
  registry: string
  namespace: string
  image_name: string
  current_tag: string
  labels: Record<string, string>
  version_label: string | null
  compose_image_digest: string | null
  repo_digest: string | null
  watch_enabled: boolean | null
  pinned_override: boolean | null
  ignored_override: boolean | null
  notify_enabled: boolean | null
  include_tags_override: string[] | null
  exclude_tags_override: string[] | null
  source: string
  environment_id: string | null
  environment_name: string | null
  compose_project: string | null
  compose_service: string | null
}

export interface VersionDiff {
  bump_type: string
  current_parsed: string | null
  latest_parsed: string | null
  current_raw: string
  latest_raw: string
}

export interface UpdateResult {
  container_info: ContainerInfo
  latest_tag: string | null
  latest_version: string | null
  is_outdated: boolean | null
  check_error: string | null
  status: string | null
  event: string | null
  deployed_tag: string | null
  deployed_version: string | null
  deployed_display: string | null
  remote_display: string | null
  deployed_digest: string | null
  remote_tag: string | null
  remote_digest: string | null
  comparison_basis: string | null
  comparison_reason: string | null
  version_status: string | null
  version_diff: VersionDiff | null
}

export interface TrivyFinding {
  vulnerability_id: string
  pkg_name: string
  installed_version: string
  fixed_version: string | null
  severity: string
  title: string
  primary_url: string
  target: string
  class_type: string
}

export interface TrivyScanResult {
  image_ref: string
  critical_count: number
  high_count: number
  medium_count: number
  low_count: number
  total_count: number
  error: string | null
  scanned_at: string | null
  image_id: string | null
  findings: TrivyFinding[]
}

export interface DockwatchSettings {
  pinned: string[]
  ignored: string[]
  notify_only: string[]
  include_tags: string[]
  exclude_tags: string[]
  notify_on: string[]
  first_check_notify: boolean
  webhook_url: string
  discord_webhook: string
  ntfy_url: string
  schedule_interval_seconds: number
  schedule_jitter_seconds: number
  run_on_startup: boolean
  max_concurrent_checks: number
  portainer: {
    enabled: boolean
    url: string
    api_key: string
    environments: string[]
  }
  trivy?: {
    enabled: boolean
    binary_path: string
    severity: string[]
    scanners: string[]
    timeout_seconds: number
    skip_db_update: boolean
    cache_ttl_minutes: number
  }
  compose_projects?: Record<string, ComposeProjectConfig>
}

export interface ComposeProjectConfig {
  workdir: string
  files: string[]
  project_name: string
}

export interface SessionUser {
  authenticated: boolean
  username?: string
  role?: string
  permissions?: string[]
}

export interface UserRecord {
  id: number
  username: string
  role_name: string
  created_at: string
}

export interface RoleRecord {
  name: string
  permissions: string[]
  is_builtin: boolean
}

export interface UpdateHistoryEntry {
  id: number
  action: 'update' | 'rollback' | 'restart' | 'digest_drift_detected'
  source: 'local' | 'portainer'
  environment_id: string | null
  old_tag: string | null
  new_tag: string | null
  old_digest: string | null
  new_digest: string | null
  status: 'success' | 'failed'
  error: string | null
  user_id: number | null
  username: string | null
  created_at: string
}

export interface ComposeDetectResult {
  compose_project: string
  detected: ComposeProjectConfig
  warnings: string[]
}

export interface PortainerEnvironment {
  id: number
  name: string
}

export interface WsMessage {
  type: string
  payload: Record<string, unknown>
}

export type ContainerStatus =
  | 'UP_TO_DATE'
  | 'OUTDATED'
  | 'PINNED'
  | 'LOCAL'
  | 'UNKNOWN'
  | 'ERROR'

export function deriveStatus(r: UpdateResult): ContainerStatus {
  if (r.status === 'PINNED' || r.container_info.pinned_override) return 'PINNED'
  if (r.status === 'LOCAL') return 'LOCAL'
  if (r.check_error) return 'ERROR'
  if (r.is_outdated === true) return 'OUTDATED'
  if (r.is_outdated === false) return 'UP_TO_DATE'
  return 'UNKNOWN'
}

export const STATUS_CONFIG: Record<ContainerStatus, { label: string; color: string; bg: string }> = {
  UP_TO_DATE: { label: 'Up-to-date', color: 'text-green-400', bg: 'bg-green-400/10' },
  OUTDATED: { label: 'Outdated', color: 'text-red-400', bg: 'bg-red-400/10' },
  PINNED: { label: 'Pinned', color: 'text-blue-400', bg: 'bg-blue-400/10' },
  LOCAL: { label: 'Local', color: 'text-cyan-400', bg: 'bg-cyan-400/10' },
  UNKNOWN: { label: 'Unknown', color: 'text-yellow-400', bg: 'bg-yellow-400/10' },
  ERROR: { label: 'Error', color: 'text-yellow-400', bg: 'bg-yellow-400/10' },
}

export const BUMP_COLORS: Record<string, string> = {
  MAJOR: 'bg-red-500/20 text-red-300 border-red-500/30',
  MINOR: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  PATCH: 'bg-green-500/20 text-green-300 border-green-500/30',
  'PRE-RELEASE': 'bg-purple-500/20 text-purple-300 border-purple-500/30',
  UNKNOWN: 'bg-zinc-500/20 text-zinc-300 border-zinc-500/30',
}
