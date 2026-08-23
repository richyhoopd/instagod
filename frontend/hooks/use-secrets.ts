"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, del, get, put } from "@/lib/api";

export interface Secret {
  clave: string;
  configurada: boolean;
  ultimos4: string | null;
  updated_at: string | null;
}

export function useSecrets(slug: string) {
  return useQuery<Secret[], ApiError>({
    queryKey: ["secrets", slug],
    queryFn: () => get<Secret[]>(`/brands/${slug}/secrets`),
    enabled: !!slug,
    retry: false,
  });
}

export function useGuardarSecret(slug: string) {
  const qc = useQueryClient();
  return useMutation<void, ApiError, { clave: string; valor: string }>({
    mutationFn: ({ clave, valor }) => put<void>(`/brands/${slug}/secrets/${clave}`, { valor }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["secrets", slug] }),
  });
}

export function useBorrarSecret(slug: string) {
  const qc = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (clave) => del<void>(`/brands/${slug}/secrets/${clave}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["secrets", slug] }),
  });
}
