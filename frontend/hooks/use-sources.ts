"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, del, get, patch, post, put } from "@/lib/api";

export type SourceKind = "imagen" | "info" | "video";

// api/routers/fuentes_api.py::_resumen_fuente — brand_sources (src/db.py)
// NO tiene columna "nombre": la fuente se identifica por provider (+ id),
// no por un nombre editable.
export interface Source {
  id: number;
  kind: SourceKind;
  provider: string;
  activa: boolean;
  orden: number;
  config: Record<string, unknown> | null;
  ultimo_run: string | null;
  ultimo_error: string | null;
  created_at: string;
}

export function useSources(slug: string, kind: SourceKind) {
  return useQuery<Source[], ApiError>({
    queryKey: ["sources", slug, kind],
    queryFn: () => get<Source[]>(`/brands/${slug}/sources?kind=${kind}`),
    enabled: !!slug,
    retry: false,
  });
}

// Todas las fuentes de la marca (los tres kinds). El reordenamiento manda la
// lista COMPLETA de ids al backend, así que la lista de un kind necesita los demás.
export function useTodasSources(slug: string) {
  return useQuery<Source[], ApiError>({
    queryKey: ["sources", slug, "todas"],
    queryFn: () => get<Source[]>(`/brands/${slug}/sources`),
    enabled: !!slug,
    retry: false,
  });
}

export interface NuevaSource {
  kind: SourceKind;
  provider: string;
  config?: Record<string, unknown>;
}

export function useCrearSource(slug: string) {
  const qc = useQueryClient();
  return useMutation<Source, ApiError, NuevaSource>({
    mutationFn: (datos) => post<Source>(`/brands/${slug}/sources`, datos),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources", slug] }),
  });
}

export interface EditarSource {
  id: number;
  kind: SourceKind;
  activa?: boolean;
  config?: Record<string, unknown>;
}

export function useEditarSource(slug: string) {
  const qc = useQueryClient();
  return useMutation<Source, ApiError, EditarSource>({
    mutationFn: ({ id, kind, ...datos }) => {
      void kind;
      return patch<Source>(`/brands/${slug}/sources/${id}`, datos);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources", slug] }),
  });
}

export function useBorrarSource(slug: string) {
  const qc = useQueryClient();
  return useMutation<void, ApiError, { id: number; kind: SourceKind }>({
    mutationFn: ({ id }) => del<void>(`/brands/${slug}/sources/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources", slug] }),
  });
}

// PUT /sources/orden (src/fuentes.py::reordenar) exige el set COMPLETO de
// brand_sources de la marca (todos los kinds juntos, ver ValueError("ids") si
// falta/sobra alguno) — por eso el caller arma `ids` con TODAS las fuentes,
// no solo las del kind visible; la invalidación por prefijo cubre todos los kinds.
export function useOrdenarSources(slug: string) {
  const qc = useQueryClient();
  return useMutation<void, ApiError, { ids: number[] }>({
    mutationFn: ({ ids }) => put<void>(`/brands/${slug}/sources/orden`, { ids }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources", slug] }),
  });
}

export function useCorrerSource(slug: string) {
  return useMutation<{ job_id: number }, ApiError, number>({
    mutationFn: (id) => post<{ job_id: number }>(`/brands/${slug}/sources/${id}/run`),
  });
}

// GET /brands/{slug}/sources/estado — qué proveedores operan en ESTE servidor
// (sin API key, bloqueado por IP de datacenter, etc.). El wizard lo usa para no
// prometer imágenes que no van a llegar.
export interface EstadoFuente {
  ok: boolean;
  motivo: string | null;
}

export function useEstadoFuentes(slug: string) {
  return useQuery<Record<string, EstadoFuente>, ApiError>({
    queryKey: ["sources-estado", slug],
    queryFn: () => get<Record<string, EstadoFuente>>(`/brands/${slug}/sources/estado`),
    enabled: !!slug,
    staleTime: 5 * 60_000,
  });
}
