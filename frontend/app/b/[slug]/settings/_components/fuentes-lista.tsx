"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
  arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Play, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { NoDisponible } from "@/components/no-disponible";
import { ApiError } from "@/lib/api";
import { fuenteLabel } from "@/lib/fuentes";
import {
  useSources,
  useEditarSource,
  useBorrarSource,
  useOrdenarSources,
  useCorrerSource,
  type Source,
  type SourceKind,
} from "@/hooks/use-sources";
import { FuenteDialog } from "./fuente-dialog";
import { cn } from "@/lib/utils";

// Providers que corren manualmente (traen contenido nuevo con un click);
// el resto (pexels/pinterest/etc.) se consultan al vuelo al generar.
const CORRIBLES = new Set(["rss", "newsapi", "ig_accounts"]);

// brand_sources no tiene columna "nombre" (src/db.py) — se arma un resumen
// legible a partir de `config` para distinguir fuentes del mismo provider.
function resumenConfig(source: Source): string | null {
  const c = source.config;
  if (!c) return null;
  if (Array.isArray(c.urls) && c.urls.length > 0) return c.urls.join(", ");
  if (Array.isArray(c.cuentas) && c.cuentas.length > 0) return c.cuentas.join(", ");
  if (typeof c.query === "string" && c.query) return c.query;
  if (typeof c.ruta === "string" && c.ruta) return c.ruta;
  return null;
}

function FuenteRow({
  source,
  puedeEditar,
  onToggle,
  onBorrar,
  onCorrer,
  corriendo,
}: {
  source: Source;
  puedeEditar: boolean;
  onToggle: (activa: boolean) => void;
  onBorrar: () => void;
  onCorrer: () => void;
  corriendo: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: source.id,
    disabled: !puedeEditar,
  });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "flex items-center gap-3 rounded-lg border bg-card p-2.5",
        isDragging && "opacity-50",
        !source.activa && "opacity-60"
      )}
    >
      {puedeEditar && (
        <button
          type="button"
          {...attributes}
          {...listeners}
          className="cursor-grab touch-none text-muted-foreground active:cursor-grabbing"
          aria-label="Reordenar"
        >
          <GripVertical className="size-4" />
        </button>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <p className="truncate text-sm font-medium">{fuenteLabel(source.provider)}</p>
          <Badge variant="outline" className="text-[10px] font-normal">
            #{source.id}
          </Badge>
        </div>
        {resumenConfig(source) && (
          <p className="truncate text-xs text-muted-foreground">{resumenConfig(source)}</p>
        )}
        {source.ultimo_error && (
          <p className="truncate text-xs text-destructive">{source.ultimo_error}</p>
        )}
      </div>
      {CORRIBLES.has(source.provider) && (
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="size-8"
          onClick={onCorrer}
          disabled={corriendo}
          title="Correr ahora"
        >
          <Play className="size-4" />
        </Button>
      )}
      <Switch checked={source.activa} disabled={!puedeEditar} onCheckedChange={onToggle} />
      {puedeEditar && (
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button type="button" size="icon" variant="ghost" className="size-8 text-destructive">
              <Trash2 className="size-4" />
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>¿Borrar &ldquo;{fuenteLabel(source.provider)}&rdquo;?</AlertDialogTitle>
              <AlertDialogDescription>Esta acción no se puede deshacer.</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancelar</AlertDialogCancel>
              <AlertDialogAction onClick={onBorrar}>Borrar</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </div>
  );
}

export function FuentesLista({
  slug,
  kind,
  titulo,
  puedeEditar,
}: {
  slug: string;
  kind: SourceKind;
  titulo: string;
  puedeEditar: boolean;
}) {
  const otroKind: SourceKind = kind === "imagen" ? "info" : "imagen";
  const sourcesQuery = useSources(slug, kind);
  // PUT /sources/orden exige el set COMPLETO de fuentes de la marca (los dos
  // kinds); se pide el otro kind solo para tener sus ids a mano al reordenar.
  const otroQuery = useSources(slug, otroKind);
  const editar = useEditarSource(slug);
  const borrar = useBorrarSource(slug);
  const ordenar = useOrdenarSources(slug);
  const correr = useCorrerSource(slug);
  const [orden, setOrden] = useState<Source[]>([]);
  const [corriendoId, setCorriendoId] = useState<number | null>(null);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  // Sincroniza la lista local con cada respuesta nueva del query (carga
  // inicial y refetches tras crear/borrar/reordenar), sin usar un efecto
  // (react-hooks/set-state-in-effect) — mismo patrón que queue-drawer.tsx.
  const [ordenSyncedAt, setOrdenSyncedAt] = useState(0);
  if (sourcesQuery.data && sourcesQuery.dataUpdatedAt !== ordenSyncedAt) {
    setOrdenSyncedAt(sourcesQuery.dataUpdatedAt);
    setOrden([...sourcesQuery.data].sort((a, b) => a.orden - b.orden));
  }

  if (sourcesQuery.isLoading) {
    return <Skeleton className="h-32 w-full" />;
  }

  if (sourcesQuery.isError) {
    if (sourcesQuery.error.status === 404) {
      return (
        <div>
          <h3 className="mb-2 font-medium">{titulo}</h3>
          <NoDisponible mensaje="Esta lista de fuentes todavía no está disponible en este servidor." />
        </div>
      );
    }
    return <NoDisponible mensaje={sourcesQuery.error.detalle} />;
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    if (!otroQuery.data) {
      toast.error("No se pudo reordenar: falta cargar las fuentes del otro tipo");
      return;
    }
    const oldIndex = orden.findIndex((s) => s.id === active.id);
    const newIndex = orden.findIndex((s) => s.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    const nuevo = arrayMove(orden, oldIndex, newIndex);
    setOrden(nuevo);
    const idsCompletos = [...nuevo.map((s) => s.id), ...otroQuery.data.map((s) => s.id)];
    ordenar.mutate(
      { ids: idsCompletos },
      {
        onError: (err) => {
          setOrden(orden);
          toast.error(err instanceof ApiError ? err.detalle : "No se pudo reordenar");
        },
      }
    );
  }

  async function correrFuente(id: number) {
    setCorriendoId(id);
    try {
      await correr.mutateAsync(id);
      toast.success("Fuente ejecutándose en segundo plano");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo correr la fuente");
    } finally {
      setCorriendoId(null);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">{titulo}</h3>
        {puedeEditar && <FuenteDialog slug={slug} kind={kind} />}
      </div>
      {orden.length === 0 && (
        <p className="text-sm text-muted-foreground">Sin fuentes configuradas.</p>
      )}
      <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
        <SortableContext items={orden.map((s) => s.id)} strategy={verticalListSortingStrategy}>
          <div className="space-y-2">
            {orden.map((source) => (
              <FuenteRow
                key={source.id}
                source={source}
                puedeEditar={puedeEditar}
                corriendo={corriendoId === source.id}
                onToggle={(activa) => {
                  setOrden((prev) => prev.map((s) => (s.id === source.id ? { ...s, activa } : s)));
                  editar.mutate(
                    { id: source.id, kind, activa },
                    {
                      onError: (err) => {
                        setOrden((prev) =>
                          prev.map((s) => (s.id === source.id ? { ...s, activa: !activa } : s))
                        );
                        toast.error(err instanceof ApiError ? err.detalle : "No se pudo actualizar");
                      },
                    }
                  );
                }}
                onBorrar={() => {
                  borrar.mutate(
                    { id: source.id, kind },
                    {
                      onSuccess: () => toast.success("Fuente borrada"),
                      onError: (err) =>
                        toast.error(err instanceof ApiError ? err.detalle : "No se pudo borrar"),
                    }
                  );
                }}
                onCorrer={() => correrFuente(source.id)}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>
    </div>
  );
}
