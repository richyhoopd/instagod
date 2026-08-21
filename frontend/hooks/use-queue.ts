"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/lib/api";
import type { Estado } from "@/lib/estados";

export interface QueueItem {
  id: number;
  tipo: "meme" | "anuncio" | "slideshow";
  estado: Estado;
  caption: string | null;
  imagen_url: string | null;
  scheduled_datetime: string | null;
  tema_semilla: string | null;
  template: string | null;
  error: string | null;
  creado_por: number | null;
  aprobado_por: number | null;
}

export function useQueue(slug: string, estado?: "pendiente" | "programado") {
  return useQuery<QueueItem[]>({
    queryKey: ["queue", slug, estado ?? "todos"],
    queryFn: () => get<QueueItem[]>(`/brands/${slug}/queue${estado ? `?estado=${estado}` : ""}`),
    enabled: !!slug,
  });
}

export function useAprobar(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (qid: number) =>
      post<{ ok: boolean; scheduled_datetime: string }>(`/brands/${slug}/queue/${qid}/aprobar`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue", slug] }),
  });
}

export function useRechazar(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (qid: number) => post<{ ok: boolean }>(`/brands/${slug}/queue/${qid}/rechazar`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue", slug] }),
  });
}
