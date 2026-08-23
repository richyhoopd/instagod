"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { fuenteLabel } from "@/lib/fuentes";
import type { EstadoFuente } from "@/hooks/use-sources";

export function PasoFuentes({
  disponibles,
  activas,
  estado,
  onToggle,
}: {
  disponibles: string[];
  activas: string[];
  // GET /sources/estado: proveedores que no operan en este servidor (sin API key,
  // bloqueados). undefined mientras carga → se asume todo operativo.
  estado?: Record<string, EstadoFuente>;
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
          const est = estado?.[f];
          const noOpera = est ? !est.ok : false;
          return (
            <label
              key={f}
              className={cn(
                "flex items-center gap-3 rounded-lg border p-3 text-sm transition-opacity",
                noOpera ? "cursor-not-allowed opacity-60" : "cursor-pointer",
                !activa && !noOpera && "opacity-50"
              )}
              title={noOpera ? `Esta fuente no va a dar imágenes: ${est?.motivo}` : undefined}
            >
              <input
                type="checkbox"
                checked={activa && !noOpera}
                disabled={noOpera}
                onChange={() => onToggle(f)}
                className="size-4 accent-(--brand)"
              />
              <span className="w-5 text-xs text-muted-foreground">{i + 1}</span>
              <span className="flex-1">{fuenteLabel(f)}</span>
              {noOpera && (
                <Badge variant="outline" className="text-[10px] font-normal text-destructive">
                  {est?.motivo === "sin API key" ? "Sin API key" : "No disponible en el servidor"}
                </Badge>
              )}
            </label>
          );
        })}
        {disponibles.length === 0 && (
          <p className="text-sm text-muted-foreground">
            La marca no tiene fuentes de imagen configuradas; se usarán las fuentes estándar.
          </p>
        )}
        {estado && disponibles.some((f) => estado[f] && !estado[f].ok) && (
          <p className="text-xs text-muted-foreground">
            Las fuentes marcadas no producen imágenes hoy; el carrusel usará las demás (o fondos
            sólidos si no queda ninguna). Un admin puede agregar la API key en Ajustes → Secretos.
          </p>
        )}
      </div>
    </div>
  );
}
