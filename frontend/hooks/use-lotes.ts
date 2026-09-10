"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, del, get, patch, post } from "@/lib/api";

// Lotes de memes de banda. Solo existen para gdlscene: el backend responde 422
// `no_aplica` a cualquier otra marca (ver api/routers/lotes.py).

export interface PiezaLote {
  id: number;
  tema_semilla: string | null;
  scheduled_datetime: string;
  photo_id: number;
  band_id: number;
  banda: string;
  tipo: string;
  prioridad: number;
  followers_ig: number | null;
  ig_handle: string | null;
}

export interface MesLote {
  mes: string;
  piezas: number;
  job_id: number | null;
}

export interface LoteDetalle {
  mes: string;
  piezas: PiezaLote[];
  job_id: number | null;
  /** Tope de piezas por mes según prioridad de banda (config.MONTHLY_CAP). */
  caps: Record<string, number>;
  /** Horas de publicación del día (config.POSTING_SLOTS). */
  slots: string[];
}

export interface NuevoLote {
  mes: string;
  criterio: "impacto" | "engagement";
  replan: boolean;
}

export interface ResumenLote {
  mes: string;
  resumen: { posts?: number; bandas?: number; slots?: number; existentes?: number };
  piezas: PiezaLote[];
}

/** Reemplazo que entró al slot, o null si el pool de fotos se agotó. */
export interface Reemplazo {
  reemplazo: { id: number } | null;
}

export function useLotes(slug: string) {
  return useQuery<MesLote[], ApiError>({
    queryKey: ["lotes", slug],
    queryFn: () => get<MesLote[]>(`/brands/${slug}/lotes`),
    enabled: !!slug,
    retry: false,
  });
}

/** Detalle del mes. Mientras el envío corre, la pantalla se refresca sola. */
export function useLote(slug: string, mes: string) {
  return useQuery<LoteDetalle, ApiError>({
    queryKey: ["lotes", slug, mes],
    queryFn: () => get<LoteDetalle>(`/brands/${slug}/lotes/${mes}`),
    enabled: !!slug && !!mes,
    retry: false,
    refetchInterval: (query) => (query.state.data?.job_id ? 3000 : false),
  });
}

function useInvalidarLotes(slug: string, mes?: string) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["lotes", slug] });
    if (mes) qc.invalidateQueries({ queryKey: ["lotes", slug, mes] });
    qc.invalidateQueries({ queryKey: ["queue", slug] });
  };
}

export function useCrearLote(slug: string) {
  const invalidar = useInvalidarLotes(slug);
  return useMutation<ResumenLote, ApiError, NuevoLote>({
    mutationFn: (datos) => post<ResumenLote>(`/brands/${slug}/lotes`, datos),
    onSuccess: invalidar,
  });
}

export function useEditarPieza(slug: string, mes: string) {
  const invalidar = useInvalidarLotes(slug, mes);
  return useMutation<
    { id: number; tema_semilla: string | null },
    ApiError,
    { qid: number; tema_semilla: string | null }
  >({
    mutationFn: ({ qid, tema_semilla }) =>
      patch(`/brands/${slug}/lotes/piezas/${qid}`, { tema_semilla }),
    onSuccess: invalidar,
  });
}

/** Saca esta foto del lote y mete otra banda en su slot. No regresa. */
export function useCambiarPieza(slug: string, mes: string) {
  const invalidar = useInvalidarLotes(slug, mes);
  return useMutation<Reemplazo, ApiError, number>({
    mutationFn: (qid) => post<Reemplazo>(`/brands/${slug}/lotes/piezas/${qid}/cambiar`),
    onSuccess: invalidar,
  });
}

/** No era foto de banda, era un flyer: se registra como evento y se reemplaza. */
export function useMarcarFlyer(slug: string, mes: string) {
  const invalidar = useInvalidarLotes(slug, mes);
  return useMutation<Reemplazo, ApiError, number>({
    mutationFn: (qid) => post<Reemplazo>(`/brands/${slug}/lotes/piezas/${qid}/flyer`),
    onSuccess: invalidar,
  });
}

/** Lista negra: la foto NUNCA se vuelve a sugerir. */
export function useEliminarPieza(slug: string, mes: string) {
  const invalidar = useInvalidarLotes(slug, mes);
  return useMutation<Reemplazo, ApiError, number>({
    mutationFn: (qid) => del<Reemplazo>(`/brands/${slug}/lotes/piezas/${qid}`),
    onSuccess: invalidar,
  });
}

export function useEnviarLote(slug: string, mes: string) {
  const invalidar = useInvalidarLotes(slug, mes);
  return useMutation<{ job_id: number; piezas: number }, ApiError, void>({
    mutationFn: () => post(`/brands/${slug}/lotes/${mes}/enviar`, {}),
    onSuccess: invalidar,
  });
}
