"use client";

import { useState } from "react";
import { History } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useRevertir, useVersiones, type Diseno, type VersionDiseno } from "@/hooks/use-disenos";

const FECHA = new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" });

export function ListaVersiones({
  versiones,
  versionActual,
  ocupado,
  onRestaurar,
}: {
  versiones: VersionDiseno[];
  versionActual: number;
  ocupado: boolean;
  onRestaurar: (version: number) => void;
}) {
  // Cada autoguardado es una versión sin mensaje (D1). Se esconden para que
  // el historial muestre lo que la persona guardó a propósito.
  const [verTodas, setVerTodas] = useState(false);
  const visibles = versiones.filter((v) => verTodas || v.mensaje !== null || v.version === versionActual);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Checkbox id="ver-autoguardados" checked={verTodas} onCheckedChange={(v) => setVerTodas(v === true)} />
        <Label htmlFor="ver-autoguardados" className="text-sm">
          Ver autoguardados
        </Label>
      </div>
      <ul className="max-h-80 divide-y overflow-y-auto rounded-md border">
        {visibles.map((v) => (
          <li key={v.version} className="flex items-center justify-between gap-3 px-3 py-2">
            <div className="min-w-0">
              <p className="truncate text-sm">
                {v.mensaje ?? "Autoguardado"}
                {v.version === versionActual && <span className="text-muted-foreground"> · actual</span>}
              </p>
              <p className="text-xs text-muted-foreground">
                v{v.version} · {FECHA.format(new Date(v.creado_en))}
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label={`Restaurar versión ${v.version}`}
              disabled={ocupado || v.version === versionActual}
              onClick={() => onRestaurar(v.version)}
            >
              Restaurar
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DialogoVersiones({
  slug,
  id,
  versionActual,
  ocupado,
  onRestaurado,
  proteger,
}: {
  slug: string;
  id: number;
  versionActual: number;
  ocupado: boolean;
  onRestaurado: (diseno: Diseno) => void;
  // Envuelve el POST revert: la página vuelca el autoguardado pendiente antes
  // y lo pausa mientras corre.
  proteger?: (accion: () => Promise<Diseno>) => Promise<Diseno>;
}) {
  const [abierto, setAbierto] = useState(false);
  const versiones = useVersiones(slug, id);
  const revertir = useRevertir(slug, id);

  return (
    <Dialog open={abierto} onOpenChange={setAbierto}>
      <DialogTrigger asChild>
        <Button type="button" size="sm" variant="ghost">
          <History className="size-4" />
          Versiones
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Versiones</DialogTitle>
          <DialogDescription>Restaurar crea una versión nueva con el contenido de la elegida.</DialogDescription>
        </DialogHeader>
        {versiones.isLoading && <p className="text-sm text-muted-foreground">Cargando…</p>}
        {versiones.isError && <p className="text-sm text-muted-foreground">No se pudo cargar el historial.</p>}
        {versiones.data && (
          <ListaVersiones
            versiones={versiones.data}
            versionActual={versionActual}
            ocupado={ocupado || revertir.isPending}
            onRestaurar={(v) => {
              const revert = () => revertir.mutateAsync(v);
              (proteger ? proteger(revert) : revert()).then(
                (d) => {
                  onRestaurado(d);
                  setAbierto(false);
                  toast.success(`Versión ${v} restaurada`);
                },
                () => toast.error("No se pudo restaurar la versión."),
              );
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
