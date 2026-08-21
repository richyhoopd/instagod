"use client";

import { Check } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { colorSwatch, estiloLabel, type EstiloPreset } from "@/lib/estilos";

export function PasoEstilo({
  estilos,
  seleccionado,
  onChange,
}: {
  estilos: Record<string, EstiloPreset>;
  seleccionado: string | undefined;
  onChange: (v: string) => void;
}) {
  const entradas = Object.entries(estilos);
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        El estilo define tipografía y colores del carrusel. Si no eliges, se usa el default de la
        marca.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {entradas.map(([nombre, estilo]) => {
          const activo = seleccionado === nombre;
          return (
            <button
              key={nombre}
              type="button"
              onClick={() => onChange(nombre)}
              className={cn(
                "flex flex-col gap-2 rounded-lg border p-3 text-left transition-colors",
                activo ? "border-(--brand) ring-1 ring-(--brand)" : "hover:bg-muted"
              )}
            >
              <div
                className="flex h-14 items-center justify-center rounded-md text-xs font-semibold"
                style={{
                  backgroundColor: colorSwatch(estilo.fondo),
                  color: colorSwatch(estilo.texto),
                }}
              >
                Aa
              </div>
              <div className="flex items-center justify-between gap-1">
                <span className="truncate text-sm font-medium">{estiloLabel(nombre)}</span>
                {activo && <Check className="size-4 shrink-0 text-(--brand)" />}
              </div>
              {estilo.propio && (
                <Badge variant="outline" className="w-fit text-[10px] font-normal">
                  De la marca
                </Badge>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
