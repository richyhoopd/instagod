"use client";

import { useState } from "react";
import Link from "next/link";
import { CalendarClock, Images, Plus } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { EstadoBadge } from "@/components/estado-badge";
import { useQueue } from "@/hooks/use-queue";
import { primeraImagen, contarImagenes } from "@/lib/imagenes";
import { formatearFecha } from "@/lib/fecha";

export function ProximasPanel({ slug }: { slug: string }) {
  const { data, isLoading } = useQueue(slug, { estado: "programado" });
  // Se recalcula al montar; suficiente para marcar atrasos de horas o días.
  const [ahora] = useState(() => Date.now());
  const esPasada = (iso: string | null) => {
    const t = iso ? new Date(iso).getTime() : NaN;
    return !Number.isNaN(t) && t < ahora;
  };
  const ordenadas = [...(data ?? [])].sort((a, b) =>
    (a.scheduled_datetime ?? "").localeCompare(b.scheduled_datetime ?? "")
  );
  // Lo que viene va primero; lo programado con fecha ya pasada (no publicado
  // a tiempo) se muestra al final marcado como atrasado, no como "próximo".
  const futuras = ordenadas.filter((i) => !esPasada(i.scheduled_datetime));
  const atrasadas = ordenadas.filter((i) => esPasada(i.scheduled_datetime));
  const proximas = [...futuras, ...atrasadas].slice(0, 5);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CalendarClock className="size-4" />
          Próximas publicaciones
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        )}
        {!isLoading && proximas.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <p className="text-sm text-muted-foreground">No hay nada programado todavía.</p>
            <Button size="sm" variant="outline" asChild>
              <Link href={`/b/${slug}/create`}>
                <Plus className="size-3.5" />
                Crear carrusel
              </Link>
            </Button>
          </div>
        )}
        {proximas.map((item) => {
          const thumb = primeraImagen(item.imagen_url);
          const n = contarImagenes(item.imagen_url);
          return (
            <div key={item.id} className="flex items-center gap-3 rounded-lg border p-2">
              <div className="relative size-12 shrink-0 overflow-hidden rounded-md bg-muted">
                {thumb && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={thumb} alt="" className="size-full object-cover" />
                )}
                {n > 1 && (
                  <span className="absolute right-0.5 bottom-0.5 flex items-center gap-0.5 rounded bg-black/60 px-1 text-[10px] text-white">
                    <Images className="size-2.5" />
                    {n}
                  </span>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">{item.caption || "Sin caption"}</p>
                <p className="text-xs text-muted-foreground">
                  {formatearFecha(item.scheduled_datetime)}
                  {esPasada(item.scheduled_datetime) && (
                    <span className="ml-1.5 text-amber-600 dark:text-amber-400">
                      · atrasada, no se publicó
                    </span>
                  )}
                </p>
              </div>
              <EstadoBadge estado={item.estado} />
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
