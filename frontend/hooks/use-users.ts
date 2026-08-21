"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, del, get, patch, post } from "@/lib/api";
import type { RolMarca } from "@/hooks/use-me";

export interface UsuarioMarca {
  account_id: number;
  slug: string;
  nombre: string;
  ig_handle: string | null;
  color_marca: string | null;
  activa: boolean;
  rol: RolMarca;
}

export interface Usuario {
  id: number;
  email: string;
  nombre: string | null;
  is_admin: boolean;
  activo: boolean;
  last_login: string | null;
  marcas: UsuarioMarca[];
}

export function useUsuarios() {
  return useQuery<Usuario[], ApiError>({
    queryKey: ["usuarios"],
    queryFn: () => get<Usuario[]>("/users"),
  });
}

export interface MarcaRolInput {
  slug: string;
  rol: RolMarca;
}

export interface InvitarUsuario {
  email: string;
  nombre?: string;
  is_admin?: boolean;
  marcas: MarcaRolInput[];
}

export function useInvitarUsuario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (datos: InvitarUsuario) => post<Usuario>("/users/invite", datos),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["usuarios"] }),
  });
}

export interface EditarUsuario {
  nombre?: string;
  activo?: boolean;
  is_admin?: boolean;
  marcas?: MarcaRolInput[];
}

export function useEditarUsuario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ uid, ...datos }: EditarUsuario & { uid: number }) =>
      patch<Usuario>(`/users/${uid}`, datos),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["usuarios"] }),
  });
}

export function useReinvitarUsuario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (uid: number) => post<{ ok: boolean }>(`/users/${uid}/reinvitar`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["usuarios"] }),
  });
}

export function useCerrarSesionesUsuario() {
  return useMutation({
    mutationFn: (uid: number) => del<{ cerradas: number }>(`/users/${uid}/sessions`),
  });
}
