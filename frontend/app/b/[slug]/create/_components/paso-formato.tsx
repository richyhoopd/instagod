"use client";

import { cn } from "@/lib/utils";
import { formatoLabel } from "@/lib/formatos";

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
        Elige la estructura editorial del carrusel. Si no eliges, se usa el default de la marca.
      </p>
      <div className="flex flex-wrap gap-2">
        {formatos.map((f) => {
          const activo = seleccionado ? seleccionado === f : f === formatos[0];
          return (
            <button
              key={f}
              type="button"
              onClick={() => onChange(f)}
              className={cn(
                "rounded-full border px-4 py-2 text-sm transition-colors",
                activo ? "border-(--brand) bg-(--brand) text-white" : "hover:bg-muted"
              )}
            >
              {formatoLabel(f)}
            </button>
          );
        })}
      </div>
    </div>
  );
}
