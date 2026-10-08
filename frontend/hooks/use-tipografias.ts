"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post } from "@/lib/api";

// api/routers/assets.py::catalogo_tipografias → src/plantillas/fontsource.py::catalogo
// (máx. 50 entradas). Solo rol manager: un editor recibe 403.
export interface TipografiaCatalogo {
  id: string;
  familia: string;
  categoria: string | null;
  pesos: number[];
}

export function useCatalogoTipografias(slug: string, q: string) {
  return useQuery<TipografiaCatalogo[], ApiError>({
    queryKey: ["tipografias-catalogo", slug, q],
    queryFn: () =>
      get<TipografiaCatalogo[]>(
        `/brands/${slug}/tipografias/catalogo?q=${encodeURIComponent(q)}`,
      ),
    enabled: !!slug,
    staleTime: 60 * 60_000,
    retry: false,
  });
}

export function useInstalarTipografia(slug: string) {
  const qc = useQueryClient();
  return useMutation<{ familia: string }, ApiError, { id: string; peso: number }>({
    mutationFn: (vars) => post(`/brands/${slug}/tipografias`, vars),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["fuentes", slug] }),
  });
}
