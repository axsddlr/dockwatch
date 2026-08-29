import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export function useEnvironments(enabled: boolean) {
  return useQuery({
    queryKey: ['environments'],
    queryFn: () => api.environments.list(),
    staleTime: 60_000,
    enabled,
  })
}
