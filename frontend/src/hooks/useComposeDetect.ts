import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import type { ComposeProjectConfig } from '../types'

export function useDetectCompose() {
  return useMutation({
    mutationFn: (name: string) => api.containers.detectCompose(name),
  })
}

export function useValidateComposeConfig() {
  return useMutation({
    mutationFn: ({ name, cfg }: { name: string; cfg: ComposeProjectConfig }) =>
      api.containers.validateComposeConfig(name, cfg),
  })
}
