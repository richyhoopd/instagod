"use client";

import { toast } from "sonner";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { NoDisponible } from "@/components/no-disponible";
import { ApiError } from "@/lib/api";
import { useTopics, useDescartarTopic } from "@/hooks/use-topics";

export function TemasLista({ slug, puedeEditar }: { slug: string; puedeEditar: boolean }) {
  const topicsQuery = useTopics(slug);
  const descartar = useDescartarTopic(slug);

  if (topicsQuery.isLoading) {
    return <Skeleton className="h-32 w-full" />;
  }

  if (topicsQuery.isError) {
    if (topicsQuery.error.status === 404) {
      return <NoDisponible mensaje="El descubrimiento de temas todavía no está disponible en este servidor." />;
    }
    return <NoDisponible mensaje={topicsQuery.error.detalle} />;
  }

  const temas = topicsQuery.data ?? [];

  async function descartarTema(id: number) {
    try {
      await descartar.mutateAsync(id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo descartar el tema");
    }
  }

  return (
    <div className="space-y-2">
      <h3 className="font-medium">Temas sugeridos</h3>
      {temas.length === 0 && (
        <p className="text-sm text-muted-foreground">No hay temas sugeridos por ahora.</p>
      )}
      {temas.map((tema) => (
        <div key={tema.id} className="flex items-start justify-between gap-3 rounded-lg border p-2.5">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{tema.titulo}</p>
            {tema.resumen && <p className="line-clamp-2 text-xs text-muted-foreground">{tema.resumen}</p>}
            {tema.fuente && <p className="text-xs text-muted-foreground">{tema.fuente}</p>}
          </div>
          {puedeEditar && (
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="size-8 shrink-0"
              onClick={() => descartarTema(tema.id)}
              title="Descartar tema"
            >
              <X className="size-4" />
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}
