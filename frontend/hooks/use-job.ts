"use client";

import { useRef } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError, get, post } from "@/lib/api";

export type JobEstado = "cola" | "corriendo" | "ok" | "error" | "cancelado";

export interface Job {
  id: number;
  tipo: string;
  estado: JobEstado;
  progreso: number | null;
  log: string | null;
  queue_id: number | null;
  created_at: string;
  finished_at: string | null;
  // Cadena JSON con lo que devolvió el handler (src/jobs/__init__.py:106).
  // Solo GET /jobs/{jid} la trae; la lista GET /jobs la filtra. Se parsea
  // con el helper resultadoDeJob de use-disenos.ts, nunca a pelo.
  resultado_json: string | null;
}

const TERMINALES: readonly JobEstado[] = ["ok", "error", "cancelado"];

// Lista de jobs recientes de una marca (para /admin/system y similares).
export function useJobs(slug: string) {
  return useQuery<Job[], ApiError>({
    queryKey: ["jobs", slug],
    queryFn: () => get<Job[]>(`/brands/${slug}/jobs`),
    enabled: !!slug,
  });
}

// Polling de jobs (constraints.md): cada 2s, backoff a 5s tras 30s de espera
// del mismo job, y se detiene en ok/error/cancelado.
export function useJob(slug: string, jid: number | null) {
  const inicioRef = useRef<{ jid: number | null; at: number } | null>(null);

  return useQuery<Job>({
    queryKey: ["job", slug, jid],
    queryFn: () => get<Job>(`/brands/${slug}/jobs/${jid}`),
    enabled: !!slug && jid !== null,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data || TERMINALES.includes(data.estado)) return false;
      if (!inicioRef.current || inicioRef.current.jid !== jid) {
        inicioRef.current = { jid, at: Date.now() };
      }
      return Date.now() - inicioRef.current.at > 30_000 ? 5000 : 2000;
    },
  });
}

export interface NuevoSlideshow {
  tema: string;
  formato?: string;
  estilo?: string;
  fuentes?: string[];
  n_slides: number;
  aspect?: string;
  contexto?: string;
  topic_id?: number;
}

export function useCrearSlideshow(slug: string) {
  return useMutation({
    mutationFn: (datos: NuevoSlideshow) =>
      post<{ job_id: number }>(`/brands/${slug}/slideshows`, datos),
  });
}

export interface NuevoPost {
  template_id: number;
  tema: string;
  entidad_id?: number;
  campos?: Record<string, unknown>;
  imagen?: string;
}

export function useCrearPost(slug: string) {
  return useMutation({
    mutationFn: (datos: NuevoPost) => post<{ job_id: number }>(`/brands/${slug}/posts`, datos),
  });
}

// POST /brands/{slug}/videos (api/routers/trabajos.py:crear_video): o un
// topic_id, o titulo + cuerpo; nunca ambos.
export interface NuevoVideo {
  topic_id?: number;
  titulo?: string;
  cuerpo?: string;
  sin_llm?: boolean;
}

export function useCrearVideo(slug: string) {
  return useMutation({
    mutationFn: (datos: NuevoVideo) => post<{ job_id: number }>(`/brands/${slug}/videos`, datos),
  });
}
