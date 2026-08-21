"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post, put } from "@/lib/api";

export interface PromptsMarca {
  voz: string | null;
  caption_extra: string | null;
  por_formato: Record<string, string> | null;
  hashtags: string[] | null;
}

// Endpoint de Fase 3 (GET/PUT /brands/{slug}/prompts): puede no existir
// todavía en el backend contra el que se corre este build (404). El caller
// distingue ese caso con `query.error instanceof ApiError && error.status === 404`.
export function usePrompts(slug: string) {
  return useQuery<PromptsMarca, ApiError>({
    queryKey: ["prompts", slug],
    queryFn: () => get<PromptsMarca>(`/brands/${slug}/prompts`),
    enabled: !!slug,
    retry: false,
  });
}

export function useGuardarPrompts(slug: string) {
  const qc = useQueryClient();
  return useMutation<PromptsMarca, ApiError, Partial<PromptsMarca>>({
    mutationFn: (datos) => put<PromptsMarca>(`/brands/${slug}/prompts`, datos),
    onSuccess: (data) => qc.setQueryData(["prompts", slug], data),
  });
}

export interface ProbarPromptVariables {
  tema: string;
  formato?: string;
}

// Respuesta documentada como "guion" sin esquema fijo: se muestra tal cual,
// formateada como JSON legible.
export function useProbarPrompt(slug: string) {
  return useMutation<unknown, ApiError, ProbarPromptVariables>({
    mutationFn: (datos) => post<unknown>(`/brands/${slug}/prompts/probar`, datos),
  });
}
