"use client";

import { Users } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/hooks/use-me";
import { useUsuarios } from "@/hooks/use-users";
import { InvitarDialog } from "./_components/invitar-dialog";
import { FilaUsuario } from "./_components/fila-usuario";

export default function AdminUsersPage() {
  const { data: me } = useMe();
  const { data: usuarios, isLoading, isError, error } = useUsuarios();

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Usuarios</h2>
          <p className="text-sm text-muted-foreground">
            Administra quién tiene acceso al portal y a qué marcas.
          </p>
        </div>
        <InvitarDialog />
      </div>

      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      )}

      {isError && (
        <p className="text-sm text-destructive">
          {error?.detalle ?? "No se pudo cargar la lista de usuarios."}
        </p>
      )}

      {!isLoading && !isError && (!usuarios || usuarios.length === 0) && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed py-16 text-center">
          <Users className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Todavía no hay usuarios invitados.</p>
          <InvitarDialog />
        </div>
      )}

      {!isLoading && !isError && usuarios && usuarios.length > 0 && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Usuario</th>
                <th className="px-3 py-2 font-medium">Marcas</th>
                <th className="px-3 py-2 font-medium">Admin</th>
                <th className="px-3 py-2 font-medium">Activo</th>
                <th className="px-3 py-2 font-medium">Último acceso</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="[&>tr>td]:px-3">
              {usuarios.map((u) => (
                <FilaUsuario key={u.id} usuario={u} esYo={u.id === me?.id} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
