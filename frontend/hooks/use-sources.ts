"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, del, get, patch, post, put } from "@/lib/api";

export type SourceKind = "imagen" | "info";

// Esquema de src/image_sources.py + src/news_sources.py aproximado: `config`
// es libre y depende del provider (url para rss, query para newsapi, etc).
export interface Source {
  id: number;
  kind: SourceKind;
  provider: string;
  nombre: string;
  activa: boolean;
  orden: number;
  config: Record<string, unknown> | null;
}

export function useSources(slug: string, kind: SourceKind) {
  return useQuery<Source[], ApiError>({
    queryKey: ["sources", slug, kind],
    queryFn: () => get<Source[]>(`/brands/${slug}/sources?kind=${kind}`),
    enabled: !!slug,
    retry: false,
  });
}

export interface NuevaSource {
  kind: SourceKind;
  provider: string;
  nombre: string;
  config?: Record<string, unknown>;
}

export function useCrearSource(slug: string) {
  const qc = useQueryClient();
  return useMutation<Source, ApiError, NuevaSource>({
    mutationFn: (datos) => post<Source>(`/brands/${slug}/sources`, datos),
    onSuccess: (_data, vars) => qc.invalidateQueries({ queryKey: ["sources", slug, vars.kind] }),
  });
}

export interface EditarSource {
  id: number;
  kind: SourceKind;
  activa?: boolean;
  nombre?: string;
  config?: Record<string, unknown>;
}

export function useEditarSource(slug: string) {
  const qc = useQueryClient();
  return useMutation<Source, ApiError, EditarSource>({
    mutationFn: ({ id, kind, ...datos }) => {
      void kind;
      return patch<Source>(`/brands/${slug}/sources/${id}`, datos);
    },
    onSuccess: (_data, vars) => qc.invalidateQueries({ queryKey: ["sources", slug, vars.kind] }),
  });
}

export function useBorrarSource(slug: string) {
  const qc = useQueryClient();
  return useMutation<void, ApiError, { id: number; kind: SourceKind }>({
    mutationFn: ({ id }) => del<void>(`/brands/${slug}/sources/${id}`),
    onSuccess: (_data, vars) => qc.invalidateQueries({ queryKey: ["sources", slug, vars.kind] }),
  });
}

export function useOrdenarSources(slug: string) {
  const qc = useQueryClient();
  return useMutation<void, ApiError, { kind: SourceKind; ids: number[] }>({
    mutationFn: ({ ids }) => put<void>(`/brands/${slug}/sources/orden`, { ids }),
    onSuccess: (_data, vars) => qc.invalidateQueries({ queryKey: ["sources", slug, vars.kind] }),
  });
}

export function useCorrerSource(slug: string) {
  return useMutation<{ job_id: number }, ApiError, number>({
    mutationFn: (id) => post<{ job_id: number }>(`/brands/${slug}/sources/${id}/run`),
  });
}
