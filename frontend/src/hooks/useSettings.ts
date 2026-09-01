import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export function useSettings() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: () => api.settings.get(),
    staleTime: 30_000,
  })
}

export function useSaveSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: Parameters<typeof api.settings.update>[0]) => api.settings.update(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })
}

export function useTestNotification() {
  return useMutation({
    mutationFn: () => api.settings.testNotification(),
  })
}

export function useTestPortainer() {
  return useMutation({
    mutationFn: ({ url, api_key }: { url: string; api_key: string }) =>
      api.settings.testPortainer(url, api_key),
  })
}

export function useTestAgent() {
  return useMutation({
    mutationFn: ({ name }: { name: string }) => api.settings.testAgent(name),
  })
}

export function useGenerateAgentToken() {
  return useMutation({
    mutationFn: () => api.settings.generateAgentToken(),
  })
}
