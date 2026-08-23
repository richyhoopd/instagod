"use client";

import { useQuery } from "@tanstack/react-query";
import { ApiError, get } from "@/lib/api";

export interface Health {
  ok: boolean;
  version: string;
}

export function useHealth() {
  return useQuery<Health, ApiError>({
    queryKey: ["health"],
    queryFn: () => get<Health>("/health"),
    retry: false,
  });
}
