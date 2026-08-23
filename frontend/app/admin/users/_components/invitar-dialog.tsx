"use client";

import { useState } from "react";
import { toast } from "sonner";
import { UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
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
import { useInvitarUsuario, type MarcaRolInput } from "@/hooks/use-users";
import type { RolMarca } from "@/hooks/use-me";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function InvitarDialog() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [nombre, setNombre] = useState("");
  const [esAdmin, setEsAdmin] = useState(false);
  const [roles, setRoles] = useState<Record<string, RolMarca>>({});
  const [errorEmail, setErrorEmail] = useState<string | null>(null);

  const { data: marcas } = useBrands();
  const invitar = useInvitarUsuario();

  function resetear() {
    setEmail("");
    setNombre("");
    setEsAdmin(false);
    setRoles({});
    setErrorEmail(null);
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
    const correo = email.trim().toLowerCase();
    if (!EMAIL_RE.test(correo)) {
      setErrorEmail("Ingresa un correo válido");
      return;
    }
    setErrorEmail(null);

    const seleccion: MarcaRolInput[] = Object.entries(roles).map(([slug, rol]) => ({
      slug,
      rol,
    }));

    try {
      const usuario = await invitar.mutateAsync({
        email: correo,
        nombre: nombre.trim() || undefined,
        is_admin: esAdmin,
        marcas: seleccion,
      });
      toast.success(`Invitación enviada a ${usuario.email}`);
      setOpen(false);
      resetear();
    } catch (err) {
      if (err instanceof ApiError && err.campo === "email") {
        setErrorEmail(err.detalle);
      } else {
        toast.error(err instanceof ApiError ? err.detalle : "No se pudo invitar al usuario");
      }
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) resetear();
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <UserPlus />
          Invitar usuario
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Invitar usuario</DialogTitle>
          <DialogDescription>
            Le enviaremos un link de acceso a su correo. Elige a qué marcas tendrá acceso.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="invitar-email">Correo</Label>
            <Input
              id="invitar-email"
              type="email"
              placeholder="persona@correo.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            {errorEmail && <p className="text-sm text-destructive">{errorEmail}</p>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="invitar-nombre">Nombre (opcional)</Label>
            <Input
              id="invitar-nombre"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
            />
          </div>
          <div className="flex items-center justify-between rounded-lg border p-3">
            <div>
              <p className="text-sm font-medium">Administrador</p>
              <p className="text-xs text-muted-foreground">
                Acceso total a todas las marcas y a esta sección
              </p>
            </div>
            <Switch checked={esAdmin} onCheckedChange={setEsAdmin} />
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
                        id={`marca-${m.slug}`}
                        checked={seleccionada}
                        onCheckedChange={(v) => toggleMarca(m.slug, v === true)}
                      />
                      <Label htmlFor={`marca-${m.slug}`} className="flex-1 truncate font-normal">
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
          <Button onClick={guardar} disabled={invitar.isPending}>
            {invitar.isPending ? "Invitando..." : "Invitar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
