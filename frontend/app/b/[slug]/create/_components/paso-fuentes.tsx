"use client";

import { cn } from "@/lib/utils";
import { fuenteLabel } from "@/lib/fuentes";

export function PasoFuentes({
  disponibles,
  activas,
  onToggle,
}: {
  disponibles: string[];
  activas: string[];
  onToggle: (fuente: string) => void;
}) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        De aquí saca la IA las imágenes del carrusel, en este orden de preferencia.
      </p>
      <div className="space-y-2">
        {disponibles.map((f, i) => {
          const activa = activas.includes(f);
          return (
            <label
              key={f}
              className={cn(
                "flex cursor-pointer items-center gap-3 rounded-lg border p-3 text-sm transition-opacity",
                !activa && "opacity-50"
              )}
            >
              <input
                type="checkbox"
                checked={activa}
                onChange={() => onToggle(f)}
                className="size-4 accent-(--brand)"
              />
              <span className="w-5 text-xs text-muted-foreground">{i + 1}</span>
              <span className="flex-1">{fuenteLabel(f)}</span>
            </label>
          );
        })}
        {disponibles.length === 0 && (
          <p className="text-sm text-muted-foreground">
            La marca no tiene fuentes de imagen configuradas; se usarán las fuentes estándar.
          </p>
        )}
      </div>
    </div>
  );
}
