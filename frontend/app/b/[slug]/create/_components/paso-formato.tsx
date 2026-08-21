"use client";

import { cn } from "@/lib/utils";
import { formatoDescripcion, formatoLabel } from "@/lib/formatos";

export function PasoFormato({
  formatos,
  seleccionado,
  onChange,
}: {
  formatos: string[];
  seleccionado: string | undefined;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        ¿Cómo quieres contar el tema? Cada opción cambia la estructura del carrusel.
      </p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {formatos.map((f) => {
          const activo = seleccionado ? seleccionado === f : f === formatos[0];
          return (
            <button
              key={f}
              type="button"
              onClick={() => onChange(f)}
              aria-pressed={activo}
              className={cn(
                "rounded-lg border p-3 text-left transition-colors",
                activo ? "border-(--brand) bg-(--brand)/5" : "hover:bg-muted"
              )}
            >
              <p className={cn("text-sm font-medium", activo && "text-(--brand)")}>
                {formatoLabel(f)}
              </p>
              {formatoDescripcion(f) && (
                <p className="mt-0.5 text-xs text-muted-foreground">{formatoDescripcion(f)}</p>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
