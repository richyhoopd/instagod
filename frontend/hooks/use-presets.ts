"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, del, get, post, put } from "@/lib/api";

// Forma libre: los campos conocidos del motor (texto/fondo/overlay) más
// cualquier otro que traiga el JSON crudo del preset.
export interface Preset {
  texto?: string;
  fondo?: string;
  overlay?: string;
  background_opacity?: number;
  propio?: boolean;
  [key: string]: unknown;
}

export function usePresets(slug: string) {
  return useQuery<Record<string, Preset>, ApiError>({
    queryKey: ["presets", slug],
    queryFn: () => get<Record<string, Preset>>(`/brands/${slug}/presets`),
    enabled: !!slug,
    retry: false,
  });
}

export function useGuardarPreset(slug: string) {
  const qc = useQueryClient();
  return useMutation<Preset, ApiError, { nombre: string; datos: Preset }>({
    mutationFn: ({ nombre, datos }) => put<Preset>(`/brands/${slug}/presets/${nombre}`, datos),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["presets", slug] }),
  });
}

export function useBorrarPreset(slug: string) {
  const qc = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (nombre) => del<void>(`/brands/${slug}/presets/${nombre}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["presets", slug] }),
  });
}

export function usePreviewPreset(slug: string) {
  return useMutation<{ job_id: number }, ApiError, string>({
    mutationFn: (nombre) => post<{ job_id: number }>(`/brands/${slug}/presets/${nombre}/preview`),
  });
}
