"use client";

import { cn } from "@/lib/utils";

export type TipoPieza = "carrusel" | "post";

const OPCIONES: { valor: TipoPieza; titulo: string; descripcion: string }[] = [
  {
    valor: "carrusel",
    titulo: "Carrusel",
    descripcion: "Varias imágenes en secuencia, escritas y armadas por IA.",
  },
  {
    valor: "post",
    titulo: "Post simple",
    descripcion: "Una sola imagen a partir de un diseño de la marca.",
  },
];

export function PasoTipo({
  valor,
  onChange,
}: {
  valor: TipoPieza | undefined;
  onChange: (v: TipoPieza) => void;
}) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">¿Qué quieres crear?</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {OPCIONES.map((o) => {
          const activo = valor === o.valor;
          return (
            <button
              key={o.valor}
              type="button"
              onClick={() => onChange(o.valor)}
              aria-pressed={activo}
              className={cn(
                "flex flex-col gap-1 rounded-lg border p-4 text-left transition-colors",
                activo ? "border-(--brand) bg-(--brand)/5" : "hover:bg-muted"
              )}
            >
              <p className={cn("text-sm font-medium", activo && "text-(--brand)")}>{o.titulo}</p>
              <p className="text-xs text-muted-foreground">{o.descripcion}</p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
