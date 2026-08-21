"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ApiError } from "@/lib/api";
import { useBrands } from "@/hooks/use-brands";
import { useEditarUsuario, type MarcaRolInput, type Usuario } from "@/hooks/use-users";
import type { RolMarca } from "@/hooks/use-me";

function rolesIniciales(usuario: Usuario): Record<string, RolMarca> {
  return Object.fromEntries(usuario.marcas.map((m) => [m.slug, m.rol]));
}

export function MembresiasDialog({ usuario }: { usuario: Usuario }) {
  const [open, setOpen] = useState(false);
  const [nombre, setNombre] = useState(usuario.nombre ?? "");
  const [roles, setRoles] = useState<Record<string, RolMarca>>(() => rolesIniciales(usuario));

  const { data: marcas } = useBrands();
  const editar = useEditarUsuario();

  function abrir(v: boolean) {
    setOpen(v);
    if (v) {
      setNombre(usuario.nombre ?? "");
      setRoles(rolesIniciales(usuario));
    }
  }

  function toggleMarca(slug: string, checked: boolean) {
    setRoles((prev) => {
      const next = { ...prev };
      if (checked) next[slug] = next[slug] ?? "editor";
      else delete next[slug];
      return next;
    });
  }

  async function guardar() {
    const seleccion: MarcaRolInput[] = Object.entries(roles).map(([slug, rol]) => ({
      slug,
      rol,
    }));
    try {
      await editar.mutateAsync({
        uid: usuario.id,
        nombre: nombre.trim() || undefined,
        marcas: seleccion,
      });
      toast.success("Membresías actualizadas");
      setOpen(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo actualizar");
    }
  }

  return (
    <Dialog open={open} onOpenChange={abrir}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Pencil />
          Editar membresías
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Membresías de {usuario.email}</DialogTitle>
          <DialogDescription>Elige a qué marcas tiene acceso y con qué rol.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="membresias-nombre">Nombre</Label>
            <Input
              id="membresias-nombre"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>Marcas</Label>
            {!marcas || marcas.length === 0 ? (
              <p className="text-sm text-muted-foreground">No hay marcas creadas todavía.</p>
            ) : (
              <div className="max-h-56 space-y-1 overflow-y-auto rounded-lg border p-2">
                {marcas.map((m) => {
                  const seleccionada = m.slug in roles;
                  return (
                    <div key={m.slug} className="flex items-center gap-2 rounded-md p-1.5">
                      <Checkbox
                        id={`edit-marca-${usuario.id}-${m.slug}`}
                        checked={seleccionada}
                        onCheckedChange={(v) => toggleMarca(m.slug, v === true)}
                      />
                      <Label
                        htmlFor={`edit-marca-${usuario.id}-${m.slug}`}
                        className="flex-1 truncate font-normal"
                      >
                        {m.nombre}
                      </Label>
                      {seleccionada && (
                        <Select
                          value={roles[m.slug]}
                          onValueChange={(v) =>
                            setRoles((prev) => ({ ...prev, [m.slug]: v as RolMarca }))
                          }
                        >
                          <SelectTrigger className="h-7 w-28 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="manager">Manager</SelectItem>
                            <SelectItem value="editor">Editor</SelectItem>
                          </SelectContent>
                        </Select>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button onClick={guardar} disabled={editar.isPending}>
            {editar.isPending ? "Guardando..." : "Guardar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
