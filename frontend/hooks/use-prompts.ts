"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post, put } from "@/lib/api";

// GET/PUT /brands/{slug}/prompts (api/routers/perfil.py): voz siempre es
// string (falls back a "" en el backend, marcas.Marca.voz: str) y
// caption_extra/por_formato/hashtags tienen base no nula
// (marcas._PROMPTS_BASE) — PUT los exige como estos tipos, nunca null.
export interface PromptsMarca {
  voz: string;
  caption_extra: string;
  por_formato: Record<string, string>;
  hashtags: string[];
}

export interface PromptsInput {
  voz: string;
  caption_extra: string;
  por_formato: Record<string, string>;
  hashtags: string[];
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
  return useMutation<PromptsMarca, ApiError, PromptsInput>({
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
