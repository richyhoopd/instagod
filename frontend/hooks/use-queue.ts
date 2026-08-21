"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { del, get, patch, post } from "@/lib/api";
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

export interface QueueDetail extends QueueItem {
  slides_data: unknown;
}

export interface QueueParams {
  estado?: Estado;
  desde?: string;
  hasta?: string;
}

function queryString(params: QueueParams): string {
  const usp = new URLSearchParams();
  if (params.estado) usp.set("estado", params.estado);
  if (params.desde) usp.set("desde", params.desde);
  if (params.hasta) usp.set("hasta", params.hasta);
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export function useQueue(slug: string, params: QueueParams = {}) {
  return useQuery<QueueItem[]>({
    queryKey: ["queue", slug, params],
    queryFn: () => get<QueueItem[]>(`/brands/${slug}/queue${queryString(params)}`),
    enabled: !!slug,
  });
}

export function useQueueDetail(slug: string, qid: number | null) {
  return useQuery<QueueDetail>({
    queryKey: ["queue-item", slug, qid],
    queryFn: () => get<QueueDetail>(`/brands/${slug}/queue/${qid}`),
    enabled: !!slug && qid !== null,
  });
}

export function useSlotsProximos(slug: string, n: number) {
  return useQuery<string[]>({
    queryKey: ["slots-proximos", slug, n],
    queryFn: () => get<string[]>(`/brands/${slug}/slots/proximos?n=${n}`),
    enabled: !!slug,
  });
}

export interface EditarQueueVariables {
  qid: number;
  caption?: string;
  scheduled_datetime?: string;
}

// Mutación genérica de PATCH: reprograma (drag-drop, reintentar) y/o edita
// caption. Sin optimismo propio: quien la llama (el calendario) pasa sus
// propios onMutate/onError en la llamada a mutate() para el rollback.
export function useEditarQueue(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ qid, ...datos }: EditarQueueVariables) =>
      patch<QueueDetail>(`/brands/${slug}/queue/${qid}`, datos),
    onSettled: (_data, _err, variables) => {
      qc.invalidateQueries({ queryKey: ["queue", slug] });
      qc.invalidateQueries({ queryKey: ["queue-item", slug, variables.qid] });
    },
  });
}

export function useAprobar(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (qid: number) =>
      post<{ ok: boolean; scheduled_datetime: string }>(`/brands/${slug}/queue/${qid}/aprobar`),
    onSuccess: (_data, qid) => {
      qc.invalidateQueries({ queryKey: ["queue", slug] });
      qc.invalidateQueries({ queryKey: ["queue-item", slug, qid] });
    },
  });
}

export function useRechazar(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (qid: number) => post<{ ok: boolean }>(`/brands/${slug}/queue/${qid}/rechazar`),
    onSuccess: (_data, qid) => {
      qc.invalidateQueries({ queryKey: ["queue", slug] });
      qc.invalidateQueries({ queryKey: ["queue-item", slug, qid] });
    },
  });
}

export function useRegenerar(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (qid: number) => post<{ job_id: number }>(`/brands/${slug}/queue/${qid}/regenerar`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue", slug] }),
  });
}

export function useEliminarQueue(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (qid: number) => del<void>(`/brands/${slug}/queue/${qid}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue", slug] }),
  });
}
