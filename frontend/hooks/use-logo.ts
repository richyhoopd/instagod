"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, postForm } from "@/lib/api";

// subir_logo (api/routers/perfil.py) espera el campo "archivo"
// (UploadFile = File(...)), no "logo".
export function useSubirLogo(slug: string) {
  const qc = useQueryClient();
  return useMutation<{ logo_path: string }, ApiError, File>({
    mutationFn: (file) => {
      const form = new FormData();
      form.append("archivo", file);
      return postForm<{ logo_path: string }>(`/brands/${slug}/logo`, form);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["brand", slug] }),
  });
}
