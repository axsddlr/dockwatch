import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => api.health.list(),
    staleTime: 30_000,
  })
}

export function useRunHealthCheck() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.health.check(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['health'] })
    },
  })
}
