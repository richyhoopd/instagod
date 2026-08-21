"use client";

import { CheckCircle2, Images, ListChecks, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { useAprobar, useQueue, useRechazar, type QueueItem } from "@/hooks/use-queue";
import { primeraImagen, contarImagenes } from "@/lib/imagenes";
import { formatearFecha } from "@/lib/fecha";
import { ApiError } from "@/lib/api";

function PendienteCard({ item, slug }: { item: QueueItem; slug: string }) {
  const aprobar = useAprobar(slug);
  const rechazar = useRechazar(slug);
  const thumb = primeraImagen(item.imagen_url);
  const n = contarImagenes(item.imagen_url);
  const enCurso = aprobar.isPending || rechazar.isPending;

  async function onAprobar() {
    try {
      const res = await aprobar.mutateAsync(item.id);
      toast.success(`Aprobado, programado para ${formatearFecha(res.scheduled_datetime)}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo aprobar");
    }
  }

  async function onRechazar() {
    try {
      await rechazar.mutateAsync(item.id);
      toast.success("Rechazado");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo rechazar");
    }
  }

  return (
    <div className="flex items-center gap-3 rounded-lg border p-2">
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
        <p className="truncate text-sm">{item.caption || item.tema_semilla || "(sin caption)"}</p>
        <p className="truncate text-xs text-muted-foreground">
          {item.tipo === "slideshow" ? "Carrusel" : "Meme"}
          {item.tema_semilla ? ` · ${item.tema_semilla}` : ""}
        </p>
      </div>
      <div className="flex shrink-0 gap-1">
        <Button
          size="sm"
          variant="outline"
          disabled={enCurso}
          onClick={onRechazar}
          aria-label="Rechazar"
        >
          <XCircle className="text-destructive" />
        </Button>
        <Button size="sm" disabled={enCurso} onClick={onAprobar} aria-label="Aprobar">
          <CheckCircle2 />
        </Button>
      </div>
    </div>
  );
}

export function PendientesPanel({ slug }: { slug: string }) {
  const { data, isLoading } = useQueue(slug, { estado: "pendiente" });
  const pendientes = data ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ListChecks className="size-4" />
          Pendientes de aprobar
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        )}
        {!isLoading && pendientes.length === 0 && (
          <p className="text-sm text-muted-foreground">No hay nada pendiente de aprobar.</p>
        )}
        {pendientes.map((item) => (
          <PendienteCard key={item.id} item={item} slug={slug} />
        ))}
      </CardContent>
    </Card>
  );
}
