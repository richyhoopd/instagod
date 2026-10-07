"use client";

import { useState } from "react";
import { Check } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { RELACION_DE_ASPECTO } from "@/lib/aspecto";
import type { Plantilla } from "@/hooks/use-templates";

function PreviewPlantilla({ slug, plantilla }: { slug: string; plantilla: Plantilla }) {
  const [falló, setFalló] = useState(false);
  const relacion = RELACION_DE_ASPECTO[plantilla.aspecto];

  if (!falló) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- PNG servido por la API vía rewrite
      <img
        src={`/api/brands/${slug}/templates/${plantilla.id}/preview.png?v=${plantilla.version_actual}`}
        alt={`Vista previa del diseño ${plantilla.nombre}`}
        loading="lazy"
        onError={() => setFalló(true)}
        className="w-full rounded-md bg-muted object-cover"
        style={{ aspectRatio: relacion }}
      />
    );
  }
  // Fallback (la API no pudo renderizar la miniatura).
  return (
    <div
      className="flex w-full items-center justify-center rounded-md bg-muted text-xs font-medium text-muted-foreground"
      style={{ aspectRatio: relacion }}
    >
      Sin vista previa
    </div>
  );
}

export function PasoPlantilla({
  slug,
  plantillas,
  isLoading,
  seleccionado,
  onChange,
}: {
  slug: string;
  plantillas: Plantilla[] | undefined;
  isLoading: boolean;
  seleccionado: number | undefined;
  onChange: (id: number) => void;
}) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="aspect-[4/5] w-full" />
        ))}
      </div>
    );
  }

  const disponibles = plantillas ?? [];

  if (disponibles.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Esta marca todavía no tiene diseños. Pide a un admin que cree uno antes de generar un
        post.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        El diseño define cómo se ve el post: colores, tipografía y acomodo del texto.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {disponibles.map((p) => {
          const activo = seleccionado === p.id;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => onChange(p.id)}
              className={cn(
                "flex flex-col gap-2 rounded-lg border p-3 text-left transition-colors",
                activo ? "border-(--brand) ring-1 ring-(--brand)" : "hover:bg-muted"
              )}
            >
              <PreviewPlantilla slug={slug} plantilla={p} />
              <div className="flex items-center justify-between gap-1">
                <span className="truncate text-sm font-medium">{p.nombre}</span>
                {activo && <Check className="size-4 shrink-0 text-(--brand)" />}
              </div>
              {p.descripcion && (
                <p className="line-clamp-2 text-xs text-muted-foreground">{p.descripcion}</p>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
