"use client";

import { useQuery } from "@tanstack/react-query";
import { ApiError, get } from "@/lib/api";

// GET /brands/{slug}/templates (api/routers/posts.py::listar_templates).
// El contrato es la MISMA fuente de verdad que usa el render y el generador
// de campos con DeepSeek: si la plantilla declara un extra, el wizard lo pide.
export interface ExtraContrato {
  id: string;
  tipo: "texto" | "texto_largo" | "numero" | "booleano" | "lista" | "imagen";
  desc?: string;
  opcional?: boolean;
  min?: number;
  max?: number;
}

export interface ContratoPlantilla {
  aspecto: string;
  base: string[];
  extras: ExtraContrato[];
}

export interface Plantilla {
  id: number;
  slug: string;
  nombre: string;
  descripcion: string | null;
  aspecto: "4:5" | "9:16";
  version_actual: number;
  contrato: ContratoPlantilla;
}

export function useTemplates(slug: string) {
  return useQuery<Plantilla[], ApiError>({
    queryKey: ["templates", slug],
    queryFn: () => get<Plantilla[]>(`/brands/${slug}/templates`),
    enabled: !!slug,
    retry: false,
  });
}
