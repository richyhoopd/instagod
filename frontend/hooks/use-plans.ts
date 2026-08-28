"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post } from "@/lib/api";

export interface PlanTopic {
  id: number;
  orden: number;
  titulo: string;
  formato: string | null;
  hook: string | null;
  fuente: "prompt" | "noticia" | "manual";
  url: string | null;
  estado: "propuesto" | "aprobado" | "descartado" | "generado" | "error";
  error: string | null;
  queue_id: number | null;
}

export interface PiezaPlan {
  id: number;
  tipo: string;
  status: string;
  aprobacion: string | null;
  caption: string | null;
  imagen_url: string | null;
  scheduled_datetime: string | null;
  error: string | null;
}

export type EstadoPlan =
  | "proponiendo"
  | "temas"
  | "generando"
  | "curacion"
  | "aprobado"
  | "error";

export interface Plan {
  id: number;
  tipo_periodo: "semana" | "mes";
  periodo: string;
  objetivo: string;
  estado: EstadoPlan;
  error: string | null;
  config_json: string | null;
  created_at: string;
  topics_total: number;
  topics_aprobados: number;
  piezas: number;
  piezas_pendientes: number;
}

export interface PlanDetail extends Omit<Plan, "piezas"> {
  topics: PlanTopic[];
  piezas: PiezaPlan[];
  job_id: number | null;
}

export interface NuevoPlan {
  tipo_periodo: "semana" | "mes";
  periodo: string;
  objetivo: string;
  n_piezas: number;
  n_slides?: number;
  aspect?: string;
  estilo?: string | null;
  formatos?: string[] | null;
  fuentes_imagen?: string[] | null;
  fuentes_info?: ("prompt" | "noticias")[];
}

export function usePlans(slug: string) {
  return useQuery<Plan[]>({
    queryKey: ["plans", slug],
    queryFn: () => get(`/brands/${slug}/plans`),
  });
}

/** Detalle del plan. Mientras un job corre, la pantalla se refresca sola. */
export function usePlan(slug: string, pid: number) {
  return useQuery<PlanDetail>({
    queryKey: ["plans", slug, pid],
    queryFn: () => get(`/brands/${slug}/plans/${pid}`),
    refetchInterval: (query) =>
      query.state.data &&
      ["proponiendo", "generando"].includes(query.state.data.estado)
        ? 3000
        : false,
  });
}

function useInvalidarPlanes(slug: string, pid?: number) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["plans", slug] });
    if (pid) qc.invalidateQueries({ queryKey: ["plans", slug, pid] });
    qc.invalidateQueries({ queryKey: ["queue", slug] });
  };
}

export function useCrearPlan(slug: string) {
  const invalidar = useInvalidarPlanes(slug);
  return useMutation({
    mutationFn: (datos: NuevoPlan) =>
      post<{ plan_id: number; job_id: number }>(`/brands/${slug}/plans`, datos),
    onSuccess: invalidar,
  });
}

export function useAgregarTopic(slug: string, pid: number) {
  const invalidar = useInvalidarPlanes(slug, pid);
  return useMutation({
    mutationFn: (datos: {
      titulo: string;
      formato?: string | null;
      hook?: string | null;
    }) => post<PlanTopic>(`/brands/${slug}/plans/${pid}/topics`, datos),
    onSuccess: invalidar,
  });
}

export function useEditarTopic(slug: string, pid: number) {
  const invalidar = useInvalidarPlanes(slug, pid);
  return useMutation({
    mutationFn: ({
      tid,
      ...datos
    }: {
      tid: number;
      titulo?: string;
      hook?: string;
      formato?: string;
      estado?: "aprobado" | "descartado";
    }) => patch<PlanTopic>(`/brands/${slug}/plans/${pid}/topics/${tid}`, datos),
    onSuccess: invalidar,
  });
}

export function useGenerarPlan(slug: string, pid: number) {
  const invalidar = useInvalidarPlanes(slug, pid);
  return useMutation({
    mutationFn: () =>
      post<{ job_id: number }>(`/brands/${slug}/plans/${pid}/generar`, {}),
    onSuccess: invalidar,
  });
}

export interface ResultadoAprobacion {
  aprobadas: { queue_id: number; slot: string }[];
  fallidas: number[];
  plan_estado: EstadoPlan;
}

export function useAprobarPlan(slug: string, pid: number) {
  const invalidar = useInvalidarPlanes(slug, pid);
  return useMutation({
    mutationFn: (datos: { queue_ids?: number[] }) =>
      post<ResultadoAprobacion>(`/brands/${slug}/plans/${pid}/aprobar`, datos),
    onSuccess: invalidar,
  });
}
