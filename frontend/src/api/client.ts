import type { UpdateResult, DockwatchSettings, PortainerEnvironment, TrivyScanResult, ComposeDetectResult, ComposeProjectConfig, UserRecord, RoleRecord, SessionUser, UpdateHistoryEntry } from '../types'

class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    if (res.status === 401 && url !== '/api/auth/login' && url !== '/api/auth/session') {
      window.dispatchEvent(new CustomEvent('dockwatch:unauthorized'))
    }
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(body.detail || res.statusText, res.status)
  }
  return res.json()
}

export const api = {
  containers: {
    list: () => request<UpdateResult[]>('/api/containers'),
    check: (source = 'local', environment?: string) => {
      const params = new URLSearchParams({ source })
      if (environment) params.set('environment', environment)
      return request<UpdateResult[]>(`/api/containers/check?${params}`, { method: 'POST' })
    },
    update: (name: string) =>
      request<{
        ok: boolean
        plan: { name: string; success: boolean; message: string; details: string[]; rollback_message: string | null }
      }>(`/api/containers/${encodeURIComponent(name)}/update`, { method: 'POST' }),
    pin: (name: string) =>
      request<{ ok: boolean; pinned: string[] }>(`/api/containers/${encodeURIComponent(name)}/pin`, { method: 'POST' }),
    unpin: (name: string) =>
      request<{ ok: boolean; pinned: string[] }>(`/api/containers/${encodeURIComponent(name)}/pin`, { method: 'DELETE' }),
    scan: (name: string) =>
      request<{ ok: boolean; cached?: boolean; result: TrivyScanResult }>(`/api/containers/${encodeURIComponent(name)}/scan`, { method: 'POST' }),
    getScan: (name: string) =>
      request<{ ok: boolean; result?: TrivyScanResult; message?: string }>(`/api/containers/${encodeURIComponent(name)}/scan`),
    invalidateScan: (name: string) =>
      request<{ ok: boolean; message: string }>(`/api/containers/${encodeURIComponent(name)}/scan`, { method: 'DELETE' }),
    detectCompose: (name: string) =>
      request<ComposeDetectResult>(`/api/containers/${encodeURIComponent(name)}/compose-detect`),
    validateComposeConfig: (name: string, cfg: ComposeProjectConfig) =>
      request<{ warnings: string[] }>(`/api/containers/${encodeURIComponent(name)}/compose-detect/validate`, {
        method: 'POST',
        body: JSON.stringify(cfg),
      }),
    getHistory: (name: string) =>
      request<UpdateHistoryEntry[]>(`/api/containers/${encodeURIComponent(name)}/history`),
    rollback: (name: string) =>
      request<{
        ok: boolean
        plan: { name: string; success: boolean; message: string; details: string[]; rollback_message: string | null }
      }>(`/api/containers/${encodeURIComponent(name)}/rollback`, { method: 'POST' }),
    restart: (name: string) =>
      request<{ ok: boolean; plan: { name: string; success: boolean; message: string } }>(
        `/api/containers/${encodeURIComponent(name)}/restart`,
        { method: 'POST' },
      ),
    deleteContainer: (name: string, force = false) =>
      request<{ ok: boolean; name: string }>(
        `/api/containers/${encodeURIComponent(name)}?force=${force}`,
        { method: 'DELETE' },
      ),
    deleteImage: (name: string, force = false) =>
      request<{ ok: boolean; name: string; image_id: string }>(
        `/api/containers/${encodeURIComponent(name)}/image?force=${force}`,
        { method: 'DELETE' },
      ),
  },
  settings: {
    get: () => request<DockwatchSettings>('/api/settings'),
    update: (data: Partial<DockwatchSettings>) =>
      request<DockwatchSettings>('/api/settings', { method: 'PUT', body: JSON.stringify(data) }),
    testNotification: () =>
      request<{ ok: boolean; message: string }>('/api/settings/test-notification', { method: 'POST' }),
    testPortainer: (url: string, api_key: string) =>
      request<{ ok: boolean; environments: { id: number; name: string }[] }>(
        '/api/settings/test-portainer',
        { method: 'POST', body: JSON.stringify({ url, api_key }) },
      ),
  },
  environments: {
    list: () =>
      request<{ environments: PortainerEnvironment[]; error?: string }>('/api/environments'),
  },
  auth: {
    login: (username: string, password: string) =>
      request<{ ok: boolean; username: string; role: string; permissions: string[] }>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      }),
    logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),
    session: () => request<SessionUser>('/api/auth/session'),
    register: (username: string, password: string) =>
      request<{ ok: boolean; username: string; role: string; permissions: string[] }>('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      }),
    registrationEnabled: () => request<{ enabled: boolean }>('/api/auth/registration-enabled'),
  },
  users: {
    list: () => request<UserRecord[]>('/api/users'),
    create: (username: string, password: string, role_name: string) =>
      request<{ ok: boolean; id: number; username: string; role_name: string }>('/api/users', {
        method: 'POST',
        body: JSON.stringify({ username, password, role_name }),
      }),
    updateRole: (id: number, role_name: string) =>
      request<{ ok: boolean; id: number; role_name: string }>(`/api/users/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ role_name }),
      }),
    delete: (id: number) =>
      request<{ ok: boolean; id: number }>(`/api/users/${id}`, { method: 'DELETE' }),
  },
  roles: {
    list: () => request<RoleRecord[]>('/api/roles'),
    create: (name: string, permissions: string[]) =>
      request<{ ok: boolean; name: string; permissions: string[]; is_builtin: boolean }>('/api/roles', {
        method: 'POST',
        body: JSON.stringify({ name, permissions }),
      }),
    update: (name: string, permissions: string[]) =>
      request<{ ok: boolean; name: string; permissions: string[]; is_builtin: boolean }>(`/api/roles/${encodeURIComponent(name)}`, {
        method: 'PATCH',
        body: JSON.stringify({ permissions }),
      }),
    delete: (name: string) =>
      request<{ ok: boolean; name: string }>(`/api/roles/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  },
}

export { ApiError }
