"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post } from "@/lib/api";

export type RolEfectivo = "editor" | "manager" | "admin";

export interface Brand {
  id: number;
  slug: string;
  nombre: string;
  ig_handle: string;
  ciudad: string;
  timezone: string;
  color_marca: string;
  activa: number;
  logo_path: string | null;
  rol: RolEfectivo;
  creds_faltantes: string[];
}

export interface BrandDetail extends Omit<Brand, "creds_faltantes"> {
  voz_extra: string | null;
  fuentes_imagen: string | null;
  estilos_json: string | null;
  voz: string | null;
  formatos: string | null;
  posting_slots: string | null;
  descripcion: string | null;
  sitio_web: string | null;
  hashtags_default: string | null;
  prompts_json: string | null;
}

export function useBrands() {
  return useQuery<Brand[]>({
    queryKey: ["brands"],
    queryFn: () => get<Brand[]>("/brands"),
  });
}

export function useBrand(slug: string) {
  return useQuery<BrandDetail>({
    queryKey: ["brand", slug],
    queryFn: () => get<BrandDetail>(`/brands/${slug}`),
    enabled: !!slug,
  });
}

export interface NuevaMarca {
  slug: string;
  nombre: string;
  ig_handle: string;
  ciudad?: string;
  color_marca?: string;
}

export function useCrearMarca() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (datos: NuevaMarca) => post<Brand>("/brands", datos),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["brands"] });
    },
  });
}

export interface PerfilMarca {
  nombre?: string;
  ig_handle?: string;
  ciudad?: string;
  timezone?: string;
  color_marca?: string;
  descripcion?: string;
  sitio_web?: string;
  hashtags_default?: string;
}

export function useActualizarMarca(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (datos: PerfilMarca) => patch<BrandDetail>(`/brands/${slug}`, datos),
    onSuccess: (data) => {
      qc.setQueryData(["brand", slug], data);
      qc.invalidateQueries({ queryKey: ["brands"] });
    },
  });
}
