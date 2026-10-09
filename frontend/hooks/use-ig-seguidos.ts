"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post } from "@/lib/api";

// api/routers/ig_seguidos.py
export type EstadoIG = "candidata" | "activa" | "descartada";

export interface CuentaIG {
  id: number;
  ig_handle: string;
  nombre: string | null;
  estado: EstadoIG;
  origen: string; // "manual" | "seguido_de:<handle>"
  avatar_url: string | null;
  bio: string | null;
  privada: number;
  scraped_at: string | null;
  notas: string | null;
}

const clave = (slug: string) => ["ig-cuentas", slug];

export function useCuentasIG(slug: string) {
  return useQuery<CuentaIG[], ApiError>({
    queryKey: clave(slug),
    queryFn: () => get<CuentaIG[]>(`/brands/${slug}/fuentes/ig/cuentas`),
    enabled: !!slug,
    retry: false,
  });
}

export function useFijarCuentaIG(slug: string) {
  const qc = useQueryClient();
  return useMutation<CuentaIG, ApiError, { ig_handle: string; estado: EstadoIG }>({
    mutationFn: (datos) => post<CuentaIG>(`/brands/${slug}/fuentes/ig/cuentas`, datos),
    onSuccess: () => qc.invalidateQueries({ queryKey: clave(slug) }),
  });
}

export function useImportarSeguidos(slug: string) {
  return useMutation<{ job_id: number }, ApiError, { semilla: string; limite?: number }>({
    mutationFn: (datos) => post<{ job_id: number }>(`/brands/${slug}/fuentes/ig/importar-seguidos`, datos),
  });
}

export function useIngerirIG(slug: string) {
  return useMutation<{ job_id: number }, ApiError, { por_cuenta?: number }>({
    mutationFn: (datos) => post<{ job_id: number }>(`/brands/${slug}/fuentes/ig/ingerir`, datos),
  });
}

export function invalidarCuentasIG(qc: ReturnType<typeof useQueryClient>, slug: string) {
  return qc.invalidateQueries({ queryKey: clave(slug) });
}
