"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, del, get, postForm } from "@/lib/api";

// GET /brands/{slug}/photos (api/routers/fuentes_api.py::listar_photos).
export interface Photo {
  nombre: string;
  tamano: number;
  mtime: number;
  url: string;
}

export function usePhotos(slug: string) {
  return useQuery<Photo[], ApiError>({
    queryKey: ["photos", slug],
    queryFn: () => get<Photo[]>(`/brands/${slug}/photos`),
    enabled: !!slug,
    retry: false,
  });
}

// subir_photos espera el campo "archivos" (list[UploadFile]) y devuelve
// {guardadas: [nombre, ...]} con los nombres nuevos generados server-side
// (uuid4, no el nombre original del archivo).
export function useSubirFotos(slug: string) {
  const qc = useQueryClient();
  return useMutation<{ guardadas: string[] }, ApiError, File[]>({
    mutationFn: (files) => {
      const form = new FormData();
      for (const f of files) form.append("archivos", f);
      return postForm<{ guardadas: string[] }>(`/brands/${slug}/photos`, form);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["photos", slug] }),
  });
}

export function useBorrarFoto(slug: string) {
  const qc = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (nombre) => del<void>(`/brands/${slug}/photos/${nombre}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["photos", slug] }),
  });
}
