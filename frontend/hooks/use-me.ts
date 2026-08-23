"use client";

import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api";

export type RolMarca = "manager" | "editor";

export interface MarcaMembresia {
  account_id: number;
  slug: string;
  nombre: string;
  ig_handle: string | null;
  color_marca: string | null;
  activa: boolean;
  rol: RolMarca;
}

export interface Me {
  id: number;
  email: string;
  nombre: string;
  is_admin: boolean;
  marcas: MarcaMembresia[];
}

export function useMe() {
  return useQuery<Me>({
    queryKey: ["me"],
    queryFn: () => get<Me>("/me"),
    retry: false,
  });
}
