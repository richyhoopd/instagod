"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, del, get, postForm } from "@/lib/api";

export interface Photo {
  nombre: string;
}

export function usePhotos(slug: string) {
  return useQuery<Photo[], ApiError>({
    queryKey: ["photos", slug],
    queryFn: () => get<Photo[]>(`/brands/${slug}/photos`),
    enabled: !!slug,
    retry: false,
  });
}

export function useSubirFotos(slug: string) {
  const qc = useQueryClient();
  return useMutation<Photo[], ApiError, File[]>({
    mutationFn: (files) => {
      const form = new FormData();
      for (const f of files) form.append("fotos", f);
      return postForm<Photo[]>(`/brands/${slug}/photos`, form);
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
