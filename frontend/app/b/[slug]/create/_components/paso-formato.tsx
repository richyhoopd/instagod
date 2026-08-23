"use client";

import { cn } from "@/lib/utils";
import { ASPECTS, formatoDescripcion, formatoLabel } from "@/lib/formatos";

export function PasoFormato({
  formatos,
  seleccionado,
  onChange,
  aspect,
  onAspectChange,
}: {
  formatos: string[];
  seleccionado: string | undefined;
  onChange: (v: string) => void;
  aspect: string;
  onAspectChange: (v: string) => void;
}) {
  return (
    <div className="space-y-6">
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

      <div className="space-y-3">
        <div>
          <p className="text-sm font-medium">Tamaño de pantalla</p>
          <p className="text-sm text-muted-foreground">
            Elige 9:16 para TikTok, Reels o Stories; 4:5 para el feed de Instagram.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {ASPECTS.map((a) => {
            const activo = aspect === a.value;
            const [w, h] = a.value.split(":").map(Number);
            return (
              <button
                key={a.value}
                type="button"
                onClick={() => onAspectChange(a.value)}
                aria-pressed={activo}
                className={cn(
                  "flex flex-col items-center gap-2 rounded-lg border p-3 text-center transition-colors",
                  activo ? "border-(--brand) bg-(--brand)/5" : "hover:bg-muted"
                )}
              >
                <div
                  className={cn(
                    "rounded-sm border-2",
                    activo ? "border-(--brand)" : "border-muted-foreground/50"
                  )}
                  style={{ width: 36 * Math.min(1, w / h), height: 36 * Math.min(1, h / w) }}
                  aria-hidden
                />
                <p className={cn("text-xs font-medium leading-tight", activo && "text-(--brand)")}>
                  {a.label}
                </p>
                <p className="text-[10px] leading-tight text-muted-foreground">{a.hint}</p>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
