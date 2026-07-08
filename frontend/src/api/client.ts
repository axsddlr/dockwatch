import type { UpdateResult, DockwatchSettings, PortainerEnvironment, TrivyScanResult, ComposeDetectResult, ComposeProjectConfig } from '../types'

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
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
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
      request<{ ok: boolean; plan: Record<string, unknown> }>(`/api/containers/${encodeURIComponent(name)}/update`, { method: 'POST' }),
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
}

export { ApiError }
