"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { NoDisponible } from "@/components/no-disponible";
import { colorSwatch, estiloLabel } from "@/lib/estilos";
import { usePresets } from "@/hooks/use-presets";
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

  const presets = presetsQuery.data ?? [];
  const seleccionadoPreset = presets.find((p) => p.nombre === seleccionado) ?? null;

  return (
    <div className="max-w-2xl space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          El estilo define los colores y la tipografía de los carruseles. Los estilos base de
          instagod no se pueden editar; los de tu marca sí.
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
        {presets.map((estilo) => {
          const activo = seleccionado === estilo.nombre;
          return (
            <button
              key={estilo.nombre}
              type="button"
              onClick={() => {
                setSeleccionado(activo ? null : estilo.nombre);
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
                <span className="truncate text-sm font-medium">{estiloLabel(estilo.nombre)}</span>
              </div>
              <Badge variant="outline" className="w-fit text-[10px] font-normal">
                {estilo.propio ? "De la marca" : "Base de instagod"}
              </Badge>
            </button>
          );
        })}
        {presets.length === 0 && (
          <p className="col-span-full text-sm text-muted-foreground">Todavía no hay estilos. Crea el primero con “Nuevo”.</p>
        )}
      </div>

      {nuevo && (
        <PresetEditor
          slug={slug}
          nombreInicial=""
          // guardar_preset (api/routers/perfil.py) exige texto y roles (dict
          // no vacío); se arranca con un esqueleto mínimo de roles editable.
          preset={{
            nombre: "",
            texto: "blanco",
            fondo: "negro",
            background_opacity: 0.35,
            roles: {
              hook: { font_size: "extra_large" },
              punto: { font_size: "large" },
              cta: { font_size: "medium" },
            },
          }}
          esNuevo
          puedeEditar={puedeEditar}
          onGuardado={() => setNuevo(false)}
          onCancelar={() => setNuevo(false)}
        />
      )}

      {seleccionado && seleccionadoPreset && (
        <PresetEditor
          key={seleccionado}
          slug={slug}
          nombreInicial={seleccionado}
          preset={seleccionadoPreset}
          esNuevo={false}
          puedeEditar={puedeEditar && !!seleccionadoPreset.propio}
          onGuardado={() => setSeleccionado(null)}
          onCancelar={() => setSeleccionado(null)}
        />
      )}
    </div>
  );
}
