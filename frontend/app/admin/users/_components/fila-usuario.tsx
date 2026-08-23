"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Mail, MoreHorizontal, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { ApiError } from "@/lib/api";
import { formatearFecha } from "@/lib/fecha";
import {
  useCerrarSesionesUsuario,
  useEditarUsuario,
  useReinvitarUsuario,
  type Usuario,
} from "@/hooks/use-users";
import { MembresiasDialog } from "./membresias-dialog";

export function FilaUsuario({ usuario, esYo }: { usuario: Usuario; esYo: boolean }) {
  const [cerrandoSesiones, setCerrandoSesiones] = useState(false);
  const editar = useEditarUsuario();
  const reinvitar = useReinvitarUsuario();
  const cerrarSesiones = useCerrarSesionesUsuario();

  function toggleActivo(activo: boolean) {
    editar.mutate(
      { uid: usuario.id, activo },
      {
        onSuccess: () => toast.success(activo ? "Usuario activado" : "Usuario desactivado"),
        onError: (err) =>
          toast.error(err instanceof ApiError ? err.detalle : "No se pudo actualizar"),
      }
    );
  }

  function toggleAdmin(is_admin: boolean) {
    editar.mutate(
      { uid: usuario.id, is_admin },
      {
        onSuccess: () => toast.success(is_admin ? "Ahora es administrador" : "Ya no es administrador"),
        onError: (err) =>
          toast.error(err instanceof ApiError ? err.detalle : "No se pudo actualizar"),
      }
    );
  }

  async function onReinvitar() {
    try {
      await reinvitar.mutateAsync(usuario.id);
      toast.success("Link de acceso reenviado");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo reenviar el link");
    }
  }

  async function onCerrarSesiones() {
    setCerrandoSesiones(true);
    try {
      const res = await cerrarSesiones.mutateAsync(usuario.id);
      toast.success(`${res.cerradas} sesión${res.cerradas === 1 ? "" : "es"} cerrada${res.cerradas === 1 ? "" : "s"}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudieron cerrar las sesiones");
    } finally {
      setCerrandoSesiones(false);
    }
  }

  return (
    <tr className="border-b last:border-0">
      <td className="py-3 pr-3">
        <p className="font-medium">{usuario.nombre || "(sin nombre)"}</p>
        <p className="flex items-center gap-1 text-xs text-muted-foreground">
          <Mail className="size-3" />
          {usuario.email}
        </p>
      </td>
      <td className="py-3 pr-3">
        <div className="flex flex-wrap gap-1">
          {usuario.is_admin ? (
            <Badge variant="outline" className="gap-1 border-primary/30 text-primary">
              <ShieldCheck className="size-3" />
              Todas (admin)
            </Badge>
          ) : usuario.marcas.length === 0 ? (
            <span className="text-xs text-muted-foreground">Sin marcas asignadas</span>
          ) : (
            usuario.marcas.map((m) => (
              <Badge key={m.slug} variant="outline">
                {m.nombre} · {m.rol}
              </Badge>
            ))
          )}
        </div>
      </td>
      <td className="py-3 pr-3">
        <Switch
          checked={usuario.is_admin}
          disabled={esYo || editar.isPending}
          onCheckedChange={toggleAdmin}
          aria-label="Administrador"
        />
      </td>
      <td className="py-3 pr-3">
        <Switch
          checked={usuario.activo}
          disabled={esYo || editar.isPending}
          onCheckedChange={toggleActivo}
          aria-label="Activo"
        />
      </td>
      <td className="py-3 pr-3 text-sm text-muted-foreground">
        {usuario.last_login ? formatearFecha(usuario.last_login) : "Nunca"}
      </td>
      <td className="py-3">
        <div className="flex items-center justify-end gap-2">
          <MembresiasDialog usuario={usuario} />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon" variant="ghost" className="size-8">
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={onReinvitar} disabled={reinvitar.isPending}>
                Reenviar link de acceso
              </DropdownMenuItem>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <DropdownMenuItem
                    variant="destructive"
                    onSelect={(e) => e.preventDefault()}
                  >
                    Cerrar sesiones activas
                  </DropdownMenuItem>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>¿Cerrar todas las sesiones?</AlertDialogTitle>
                    <AlertDialogDescription>
                      {usuario.email} tendrá que volver a pedir un link de acceso para entrar.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancelar</AlertDialogCancel>
                    <AlertDialogAction onClick={onCerrarSesiones} disabled={cerrandoSesiones}>
                      Cerrar sesiones
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </td>
    </tr>
  );
}
