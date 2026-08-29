import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export function useContainers(source: string, environment: string | null) {
  return useQuery({
    queryKey: ['containers', source, environment],
    queryFn: () => api.containers.check(source, environment ?? undefined),
    staleTime: Infinity,
    enabled: false,
  })
}
