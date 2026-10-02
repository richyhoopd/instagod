"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, del, get, postForm, put } from "@/lib/api";

// Espejo de VideoPreset (src/video_model.py). Solo una parte se edita desde
// Ajustes → Video; el resto (rate, pitch, procesado de voz) viaja de vuelta intacto.
export interface VideoPreset {
  voz: string;
  personaje_path: string | null;
  etiqueta_tarjeta: string;
  autor_tarjeta: string;
  cta_hablado: string;
  cta_texto: string;
  cta_marca: string;
  color_acento: string;
  color_fondo: string;
  fondos: string[];
  palabras_subtitulo: number;
  palabras_min: number;
  palabras_max: number;
  max_duracion_s: number;
}

export interface VideoConfig {
  // false = la marca no tiene video_json y genera con los defaults del motor.
  configurado: boolean;
  tiene_personaje: boolean;
  preset: VideoPreset;
  voces: string[];
  fondos: string[];
}

export type VideoPresetIn = Partial<Omit<VideoPreset, "personaje_path">>;

export function useVideoConfig(slug: string) {
  return useQuery<VideoConfig, ApiError>({
    queryKey: ["video-preset", slug],
    queryFn: () => get<VideoConfig>(`/brands/${slug}/video`),
    enabled: !!slug,
  });
}

export function useGuardarVideoPreset(slug: string) {
  const qc = useQueryClient();
  return useMutation<VideoConfig, ApiError, VideoPresetIn>({
    mutationFn: (datos) => put<VideoConfig>(`/brands/${slug}/video`, datos),
    onSuccess: (data) => qc.setQueryData(["video-preset", slug], data),
  });
}

// subir_personaje (api/routers/perfil.py) espera el campo "archivo", igual que el logo.
export function useSubirPersonaje(slug: string) {
  const qc = useQueryClient();
  return useMutation<VideoConfig, ApiError, File>({
    mutationFn: (file) => {
      const form = new FormData();
      form.append("archivo", file);
      return postForm<VideoConfig>(`/brands/${slug}/video/personaje`, form);
    },
    onSuccess: (data) => qc.setQueryData(["video-preset", slug], data),
  });
}

export function useQuitarPersonaje(slug: string) {
  const qc = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: () => del<void>(`/brands/${slug}/video/personaje`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["video-preset", slug] }),
  });
}
