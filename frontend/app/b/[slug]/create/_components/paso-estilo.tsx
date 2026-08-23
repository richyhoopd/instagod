"use client";

import { useState } from "react";
import { Check } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { colorSwatch, estiloLabel, type EstiloPreset } from "@/lib/estilos";

// Hash corto del preset: cambia la URL (y el caché del navegador) cuando el
// manager edita el estilo; la API ya regenera la miniatura por hash del preset.
function versionDe(estilo: EstiloPreset): string {
  const s = JSON.stringify(estilo);
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

function PreviewEstilo({
  slug,
  nombre,
  estilo,
}: {
  slug: string;
  nombre: string;
  estilo: EstiloPreset;
}) {
  const [falló, setFalló] = useState(false);
  if (!falló) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- PNG servido por la API vía rewrite
      <img
        src={`/api/brands/${slug}/estilos/${nombre}/preview.png?v=${versionDe(estilo)}`}
        alt={`Preview del estilo ${estiloLabel(nombre)}`}
        loading="lazy"
        onError={() => setFalló(true)}
        className="aspect-[4/5] w-full rounded-md bg-muted object-cover"
      />
    );
  }
  // Fallback (la API no pudo renderizar): swatch de colores del preset.
  return (
    <div
      className="flex aspect-[4/5] w-full items-center justify-center rounded-md text-xs font-semibold"
      style={{ backgroundColor: colorSwatch(estilo.fondo), color: colorSwatch(estilo.texto) }}
    >
      Aa
    </div>
  );
}

export function PasoEstilo({
  slug,
  estilos,
  seleccionado,
  onChange,
}: {
  slug: string;
  estilos: Record<string, EstiloPreset>;
  seleccionado: string | undefined;
  onChange: (v: string) => void;
}) {
  const entradas = Object.entries(estilos);
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        El estilo define los colores y la tipografía del carrusel. Las miniaturas son un
        render real con una foto de la marca. Si no eliges, se usa el estilo habitual.
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
              <PreviewEstilo slug={slug} nombre={nombre} estilo={estilo} />
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
