"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, patch, post, postForm } from "@/lib/api";
import type { Asset, Candidata } from "@/lib/assets";

export type TipoAsset = "imagen" | "video";

// Todos estos endpoints exigen rol manager (api/routers/assets.py): `habilitado`
// evita pedirlos como editor, que solo recibiría 403.
export function useBuscarAssets(slug: string, q: string, tipo: TipoAsset, habilitado = true) {
  const params = new URLSearchParams({ q, tipo, n: "30" });
  return useQuery<{ resultados: Candidata[]; avisos: string[] }, ApiError>({
    queryKey: ["assets-buscar", slug, tipo, q],
    queryFn: () => get(`/brands/${slug}/assets/buscar?${params.toString()}`),
    enabled: habilitado && !!slug && q.trim().length >= 1,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

// Búsqueda de pago (fal.ai): mutación, no query. Una mutación solo corre por un
// clic explícito; ningún remount, refoco ni expiración de caché la repite.
export function useBuscarIaAssets(slug: string) {
  return useMutation<{ resultados: Candidata[]; avisos: string[] }, ApiError, string>({
    mutationFn: (q) => {
      const params = new URLSearchParams({ q, tipo: "imagen", n: "30", proveedores: "ia_imagen" });
      return get(`/brands/${slug}/assets/buscar?${params.toString()}`);
    },
  });
}

export function useAssets(slug: string, tipo?: TipoAsset, habilitado = true) {
  return useQuery<Asset[], ApiError>({
    queryKey: ["assets", slug, tipo ?? "todos"],
    queryFn: () => get<Asset[]>(`/brands/${slug}/assets${tipo ? `?tipo=${tipo}` : ""}`),
    enabled: habilitado && !!slug,
    retry: false,
  });
}

export function useImportarAsset(slug: string) {
  const qc = useQueryClient();
  return useMutation<Asset, ApiError, Candidata & { tags?: string[] }>({
    mutationFn: (cand) => post<Asset>(`/brands/${slug}/assets/importar`, cand),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets", slug] }),
  });
}

export function useSubirAsset(slug: string) {
  const qc = useQueryClient();
  return useMutation<Asset, ApiError, File>({
    mutationFn: (archivo) => {
      const form = new FormData();
      form.append("archivo", archivo);
      return postForm<Asset>(`/brands/${slug}/assets/subir`, form);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets", slug] }),
  });
}

export function useDescartarAsset(slug: string) {
  const qc = useQueryClient();
  return useMutation<Asset, ApiError, number>({
    mutationFn: (id) => patch<Asset>(`/brands/${slug}/assets/${id}`, { descartada: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets", slug] }),
  });
}

export function useRecorteAsset(slug: string) {
  return useMutation<{ job_id: number }, ApiError, number>({
    mutationFn: (id) => post<{ job_id: number }>(`/brands/${slug}/assets/${id}/recorte`, {}),
  });
}
