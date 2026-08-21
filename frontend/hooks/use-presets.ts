"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, del, get, post, put } from "@/lib/api";

// GET /brands/{slug}/presets (api/routers/perfil.py::listar_presets) devuelve
// una LISTA — cada item es el preset de config.SLIDESHOW_ESTILOS/marca.estilos
// con "nombre" y "propio" inyectados. La forma real del preset es
// texto/fondo/background_opacity/roles (ver config.SLIDESHOW_ESTILOS); "roles"
// es obligatorio y no vacío para poder guardarlo (guardar_preset lo valida).
export interface Preset {
  nombre: string;
  texto?: string;
  fondo?: string;
  background_opacity?: number;
  roles?: Record<string, unknown>;
  propio?: boolean;
  [key: string]: unknown;
}

export function usePresets(slug: string) {
  return useQuery<Preset[], ApiError>({
    queryKey: ["presets", slug],
    queryFn: () => get<Preset[]>(`/brands/${slug}/presets`),
    enabled: !!slug,
    retry: false,
  });
}

export function useGuardarPreset(slug: string) {
  const qc = useQueryClient();
  return useMutation<Preset, ApiError, { nombre: string; datos: Record<string, unknown> }>({
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
