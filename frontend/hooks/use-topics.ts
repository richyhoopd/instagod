"use client";

import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api";

export interface Topic {
  id: number;
  titulo: string;
  resumen: string | null;
  url: string | null;
  fuente: string | null;
}

export function useTopics(slug: string) {
  return useQuery<Topic[]>({
    queryKey: ["topics", slug],
    queryFn: () => get<Topic[]>(`/brands/${slug}/topics`),
    enabled: !!slug,
    retry: false,
  });
}
