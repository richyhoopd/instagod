"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { NoDisponible } from "@/components/no-disponible";
import { colorSwatch, estiloLabel } from "@/lib/estilos";
import { usePresets, type Preset } from "@/hooks/use-presets";
import { PresetEditor } from "./preset-editor";
import { cn } from "@/lib/utils";

export function TabEstilos({ slug, puedeEditar }: { slug: string; puedeEditar: boolean }) {
  const presetsQuery = usePresets(slug);
  const [seleccionado, setSeleccionado] = useState<string | null>(null);
  const [nuevo, setNuevo] = useState(false);

  if (presetsQuery.isLoading) {
    return <Skeleton className="h-64 w-full max-w-2xl" />;
  }

  if (presetsQuery.isError) {
    if (presetsQuery.error.status === 404) {
      return <NoDisponible mensaje="La biblioteca de estilos todavía no está disponible en este servidor." />;
    }
    return <NoDisponible mensaje={presetsQuery.error.detalle} />;
  }

  const presets = presetsQuery.data ?? {};
  const entradas = Object.entries(presets);

  return (
    <div className="max-w-2xl space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Los presets globales del motor son de solo lectura; los propios de la marca los puedes
          editar o borrar.
        </p>
        {puedeEditar && !nuevo && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setNuevo(true);
              setSeleccionado(null);
            }}
          >
            <Plus className="size-4" />
            Nuevo
          </Button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {entradas.map(([nombre, estilo]) => {
          const activo = seleccionado === nombre;
          return (
            <button
              key={nombre}
              type="button"
              onClick={() => {
                setSeleccionado(activo ? null : nombre);
                setNuevo(false);
              }}
              className={cn(
                "flex flex-col gap-2 rounded-lg border p-3 text-left transition-colors",
                activo ? "border-(--brand) ring-1 ring-(--brand)" : "hover:bg-muted"
              )}
            >
              <div
                className="flex h-12 items-center justify-center rounded-md text-xs font-semibold"
                style={{
                  backgroundColor: colorSwatch(estilo.fondo),
                  color: colorSwatch(estilo.texto),
                }}
              >
                Aa
              </div>
              <div className="flex items-center justify-between gap-1">
                <span className="truncate text-sm font-medium">{estiloLabel(nombre)}</span>
              </div>
              <Badge variant="outline" className="w-fit text-[10px] font-normal">
                {estilo.propio ? "De la marca" : "Global"}
              </Badge>
            </button>
          );
        })}
        {entradas.length === 0 && (
          <p className="col-span-full text-sm text-muted-foreground">Sin presets configurados.</p>
        )}
      </div>

      {nuevo && (
        <PresetEditor
          slug={slug}
          nombreInicial=""
          preset={{}}
          esNuevo
          puedeEditar={puedeEditar}
          onGuardado={() => setNuevo(false)}
          onCancelar={() => setNuevo(false)}
        />
      )}

      {seleccionado && presets[seleccionado] && (
        <PresetEditor
          key={seleccionado}
          slug={slug}
          nombreInicial={seleccionado}
          preset={presets[seleccionado] as Preset}
          esNuevo={false}
          puedeEditar={puedeEditar && !!presets[seleccionado]?.propio}
          onGuardado={() => setSeleccionado(null)}
          onCancelar={() => setSeleccionado(null)}
        />
      )}
    </div>
  );
}
