"use client";

import { useMutation } from "@tanstack/react-query";
import { post, ApiError } from "@/lib/api";

export type TipoPrueba = "telegram" | "instagram" | "llm";

export interface ResultadoPrueba {
  ok: boolean;
  detalle?: string;
  username?: string;
  provider?: string;
  model?: string;
  respuesta?: string;
}

export function usePrueba(slug: string, tipo: TipoPrueba) {
  return useMutation<ResultadoPrueba, ApiError>({
    mutationFn: () => post<ResultadoPrueba>(`/brands/${slug}/${tipo}/test`),
  });
}
