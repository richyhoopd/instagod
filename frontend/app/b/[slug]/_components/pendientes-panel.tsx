"use client";

import Link from "next/link";
import { ArrowRight, Check, Images, ListChecks, X } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
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
        >
          <X className="text-destructive" />
          Rechazar
        </Button>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button size="sm" disabled={enCurso}>
              <Check />
              Aprobar
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>¿Aprobar esta publicación?</AlertDialogTitle>
              <AlertDialogDescription>
                Se programará en el siguiente horario libre y se publicará automáticamente
                en el Instagram de la marca.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancelar</AlertDialogCancel>
              <AlertDialogAction onClick={onAprobar}>Aprobar y programar</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  );
}

// El dashboard es un resumen: muestra pocas y manda al calendario para
// revisar el resto; una cola grande aquí enterraría el resto de paneles.
const MAX_VISIBLES = 5;

export function PendientesPanel({ slug }: { slug: string }) {
  const { data, isLoading } = useQueue(slug, { estado: "pendiente" });
  const pendientes = data ?? [];
  const visibles = pendientes.slice(0, MAX_VISIBLES);
  const restantes = pendientes.length - visibles.length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ListChecks className="size-4" />
          Pendientes de aprobar
          {pendientes.length > 0 && (
            <span className="text-sm font-normal text-muted-foreground">
              {pendientes.length}
            </span>
          )}
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
          <p className="text-sm text-muted-foreground">
            No hay nada pendiente de aprobar. Lo nuevo que se genere aparecerá aquí.
          </p>
        )}
        {visibles.map((item) => (
          <PendienteCard key={item.id} item={item} slug={slug} />
        ))}
        {restantes > 0 && (
          <Button variant="outline" size="sm" className="w-full" asChild>
            <Link href={`/b/${slug}/library?estado=pendiente`}>
              Revisar {restantes} pendiente{restantes === 1 ? "" : "s"} más
              <ArrowRight className="size-3.5" />
            </Link>
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
