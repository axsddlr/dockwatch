import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export function usePrunePreview(enabled: boolean) {
  return useQuery({
    queryKey: ['prune', 'preview'],
    queryFn: () => api.prune.preview(),
    enabled,
    staleTime: 30_000,
  })
}

export function useRunPrune() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body?: { mode?: string; keep_recent?: number }) => api.prune.run(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prune', 'preview'] })
    },
  })
}
