"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, patch, post } from "@/lib/api";
import type { Escena } from "@/lib/escena";
import type { ContratoPlantilla, ExtraContrato, Plantilla } from "./use-templates";
import type { Job } from "./use-job";

// Se reexportan tal cual: el contrato de una plantilla y el de un diseño son
// el mismo tipo, definido en use-templates.ts. No se redeclaran aquí.
export type { ContratoPlantilla, ExtraContrato, Plantilla };

// GET /brands/{slug}/templates (api/routers/plantillas.py) devuelve una
// lista MÁS CORTA que un Diseno: nunca trae `layout` ni el HTML. Desde el
// arreglo del backend (commit d9e50c9) sí trae `estado` y `editable`.
export type PlantillaLista = Plantilla & {
  estado: "activa" | "borrador" | "archivada";
  editable: boolean;
};

// GET /templates/{tid} (api/routers/plantillas.py, `_vista`) — sin `slug`.
export interface Diseno {
  id: number;
  nombre: string;
  descripcion: string | null;
  aspecto: Aspecto;
  estado: PlantillaLista["estado"];
  version_actual: number;
  contrato: ContratoPlantilla;
  layout: Escena | null;
  editable: boolean;
}

export interface VersionDiseno {
  version: number;
  mensaje: string | null;
  creado_en: string;
}

export interface Fuente {
  familia: string;
  propia: boolean;
}

export interface Sticker {
  nombre: string;
  url: string;
}

// Columna brand_templates.aspecto. El plan 1 agrega 1:1.
export type Aspecto = "4:5" | "1:1" | "9:16";

/**
 * Lee el resultado de un job ya terminado. `resultado_json` es una cadena
 * (src/jobs/__init__.py:106): nunca se parsea a pelo, siempre con try/catch,
 * y solo si el job existe y terminó en "ok".
 */
export function resultadoDeJob<T>(job: Job | undefined): T | null {
  if (!job || job.estado !== "ok" || !job.resultado_json) return null;
  try {
    return JSON.parse(job.resultado_json) as T;
  } catch {
    return null;
  }
}

// GET /brands/{slug}/templates?estado= — por omisión el backend filtra por
// "activa"; se manda solo cuando el llamador pide algo distinto.
export function useDisenos(slug: string, estado?: "activa" | "borrador" | "archivada") {
  return useQuery<PlantillaLista[], ApiError>({
    queryKey: ["disenos", slug, estado],
    queryFn: () =>
      get<PlantillaLista[]>(`/brands/${slug}/templates${estado ? `?estado=${estado}` : ""}`),
    enabled: !!slug,
    retry: false,
  });
}

export function useDiseno(slug: string, id: number) {
  return useQuery<Diseno, ApiError>({
    queryKey: ["diseno", slug, id],
    queryFn: () => get<Diseno>(`/brands/${slug}/templates/${id}`),
    enabled: !!slug && !!id,
    retry: false,
  });
}

export function useCrearDiseno(slug: string) {
  const qc = useQueryClient();
  return useMutation<
    Diseno,
    ApiError,
    { nombre: string; aspecto: Aspecto; layout?: Escena; contrato?: ContratoPlantilla }
  >({
    mutationFn: (b) => post<Diseno>(`/brands/${slug}/templates`, b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["disenos", slug] }),
  });
}

export function useGuardarDiseno(slug: string, id: number) {
  const qc = useQueryClient();
  return useMutation<Diseno, ApiError, { layout: Escena; contrato?: ContratoPlantilla; mensaje?: string }>({
    mutationFn: (b) => patch<Diseno>(`/brands/${slug}/templates/${id}`, b),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["diseno", slug, id] });
      qc.invalidateQueries({ queryKey: ["versiones", slug, id] });
      qc.invalidateQueries({ queryKey: ["disenos", slug] });
    },
  });
}

export function useDuplicarDiseno(slug: string) {
  const qc = useQueryClient();
  return useMutation<Diseno, ApiError, number>({
    mutationFn: (id) => post<Diseno>(`/brands/${slug}/templates/${id}/duplicate`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["disenos", slug] }),
  });
}

export function useVersiones(slug: string, id: number) {
  return useQuery<VersionDiseno[], ApiError>({
    queryKey: ["versiones", slug, id],
    queryFn: () => get<VersionDiseno[]>(`/brands/${slug}/templates/${id}/versions`),
    enabled: !!slug && !!id,
    retry: false,
  });
}

export function useRevertir(slug: string, id: number) {
  const qc = useQueryClient();
  return useMutation<Diseno, ApiError, number>({
    mutationFn: (version) => post<Diseno>(`/brands/${slug}/templates/${id}/revert/${version}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["diseno", slug, id] });
      qc.invalidateQueries({ queryKey: ["versiones", slug, id] });
      qc.invalidateQueries({ queryKey: ["disenos", slug] });
    },
  });
}

export function useActivarDiseno(slug: string, id: number) {
  const qc = useQueryClient();
  return useMutation<Diseno, ApiError, void>({
    mutationFn: () => post<Diseno>(`/brands/${slug}/templates/${id}/activate`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["diseno", slug, id] });
      qc.invalidateQueries({ queryKey: ["disenos", slug] });
    },
  });
}

export function useArchivarDiseno(slug: string, id: number) {
  const qc = useQueryClient();
  return useMutation<Diseno, ApiError, void>({
    mutationFn: () => post<Diseno>(`/brands/${slug}/templates/${id}/archive`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["diseno", slug, id] });
      qc.invalidateQueries({ queryKey: ["disenos", slug] });
    },
  });
}

export function useFuentes(slug: string) {
  return useQuery<Fuente[], ApiError>({
    queryKey: ["fuentes", slug],
    queryFn: () => get<Fuente[]>(`/brands/${slug}/fonts`),
    enabled: !!slug,
    retry: false,
  });
}

export function useStickers(slug: string) {
  return useQuery<Sticker[], ApiError>({
    queryKey: ["stickers", slug],
    queryFn: () => get<Sticker[]>(`/brands/${slug}/stickers`),
    enabled: !!slug,
    retry: false,
  });
}

// Vista previa sin guardar: el backend valida contrato+layout y encola el
// render. El resultado ({url}) se lee con useJob + resultadoDeJob.
export function usePreviaDiseno(slug: string) {
  return useMutation<
    { job_id: number },
    ApiError,
    { layout: Escena; contrato?: ContratoPlantilla; aspecto: Aspecto }
  >({
    mutationFn: (b) => post<{ job_id: number }>(`/brands/${slug}/templates/preview`, b),
  });
}

// El asistente: DeepSeek propone un layout_json a partir de una instrucción.
// El resultado ({layout, mensaje}) se lee con useJob + resultadoDeJob.
export function usePedirDiseno(slug: string) {
  return useMutation<
    { job_id: number },
    ApiError,
    { instruccion: string; aspecto: Aspecto; template_id?: number }
  >({
    mutationFn: (b) => post<{ job_id: number }>(`/brands/${slug}/templates/design`, b),
  });
}
