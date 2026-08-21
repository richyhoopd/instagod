"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post } from "@/lib/api";

export interface Topic {
  id: number;
  titulo: string;
  resumen: string | null;
  url: string | null;
  fuente: string | null;
}

export function useTopics(slug: string) {
  return useQuery<Topic[], ApiError>({
    queryKey: ["topics", slug],
    queryFn: () => get<Topic[]>(`/brands/${slug}/topics`),
    enabled: !!slug,
    retry: false,
  });
}

export function useDescartarTopic(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => post<{ ok: boolean }>(`/brands/${slug}/topics/${id}/descartar`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["topics", slug] }),
  });
}
