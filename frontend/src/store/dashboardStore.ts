import { create } from 'zustand'
import type { UpdateResult, ContainerStatus, DockwatchSettings, TrivyScanResult } from '../types'

interface DashboardState {
  results: UpdateResult[]
  selectedStatuses: Set<ContainerStatus>
  selectedSource: string
  selectedEnvironment: string | null
  wsConnected: boolean
  isChecking: boolean
  lastChecked: string | null
  autoRefresh: boolean
  autoRefreshInterval: number
  scannedContainers: Record<string, TrivyScanResult>
  scanningContainers: Record<string, boolean>
  expandedScan: string | null

  setResults: (results: UpdateResult[]) => void
  toggleStatusFilter: (status: ContainerStatus) => void
  setSelectedSource: (source: string) => void
  setSelectedEnvironment: (env: string | null) => void
  setWsConnected: (connected: boolean) => void
  setIsChecking: (checking: boolean) => void
  setLastChecked: (time: string) => void
  setAutoRefresh: (on: boolean) => void
  setAutoRefreshInterval: (interval: number) => void
  setScanResult: (name: string, result: TrivyScanResult | null) => void
  setScanning: (name: string, scanning: boolean) => void
  setExpandedScan: (name: string | null) => void
}

function loadFromStorage<T>(key: string, fallback: T): T {
  try {
    const stored = localStorage.getItem(key)
    if (stored) return JSON.parse(stored)
  } catch { /* ignore */ }
  return fallback
}

export const useDashboardStore = create<DashboardState>((set) => ({
  results: [],
  selectedStatuses: new Set(loadFromStorage<ContainerStatus[]>('dockwatch-statuses', [])),
  selectedSource: loadFromStorage('dockwatch-source', 'local'),
  selectedEnvironment: loadFromStorage('dockwatch-env', null),
  wsConnected: false,
  isChecking: false,
  lastChecked: null,
  autoRefresh: false,
  autoRefreshInterval: 300,
  scannedContainers: {},
  scanningContainers: {},
  expandedScan: null,

  setResults: (results) => set({ results }),
  toggleStatusFilter: (status) =>
    set((state) => {
      const next = new Set(state.selectedStatuses)
      if (next.has(status)) next.delete(status)
      else next.add(status)
      localStorage.setItem('dockwatch-statuses', JSON.stringify([...next]))
      return { selectedStatuses: next }
    }),
  setSelectedSource: (source) => {
    localStorage.setItem('dockwatch-source', JSON.stringify(source))
    return set({ selectedSource: source })
  },
  setSelectedEnvironment: (env) => {
    if (env === null) localStorage.removeItem('dockwatch-env')
    else localStorage.setItem('dockwatch-env', JSON.stringify(env))
    return set({ selectedEnvironment: env })
  },
  setWsConnected: (connected) => set({ wsConnected: connected }),
  setIsChecking: (checking) => set({ isChecking: checking }),
  setLastChecked: (time) => set({ lastChecked: time }),
  setAutoRefresh: (on) => set({ autoRefresh: on }),
  setAutoRefreshInterval: (interval) => set({ autoRefreshInterval: interval }),
  setScanResult: (name, result) =>
    set((state) => ({
      scannedContainers: result
        ? { ...state.scannedContainers, [name]: result }
        : { ...state.scannedContainers, [name]: undefined } as Record<string, TrivyScanResult>,
    })),
  setScanning: (name, scanning) =>
    set((state) => ({
      scanningContainers: { ...state.scanningContainers, [name]: scanning },
    })),
  setExpandedScan: (name) => set({ expandedScan: name }),
}))

export type { UpdateResult, ContainerStatus, DockwatchSettings }
