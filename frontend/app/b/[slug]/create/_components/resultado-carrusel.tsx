"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EstadoBadge } from "@/components/estado-badge";
import { ImageCarousel } from "../../calendar/_components/image-carousel";
import { SlideEditor, slidesDe } from "../../calendar/_components/slide-editor";
import { ApiError } from "@/lib/api";
import { formatearFecha } from "@/lib/fecha";
import { listaImagenes } from "@/lib/imagenes";
import {
  useAprobar,
  useEditarQueue,
  useQueueDetail,
  useRechazar,
  useRegenerar,
  useSlotsProximos,
} from "@/hooks/use-queue";

const N_SLOTS = 8;

export function ResultadoCarrusel({
  slug,
  qid,
  onRegenerar,
}: {
  slug: string;
  qid: number;
  onRegenerar: (jobId: number) => void;
}) {
  const { data: item, isLoading } = useQueueDetail(slug, qid);
  const slotsQuery = useSlotsProximos(slug, N_SLOTS);
  const aprobar = useAprobar(slug);
  const editar = useEditarQueue(slug);
  const rechazar = useRechazar(slug);
  const regenerar = useRegenerar(slug);

  const [slotElegido, setSlotElegido] = useState<string | null>(null);
  const [slotSyncId, setSlotSyncId] = useState<number | null>(null);
  const [editandoSlides, setEditandoSlides] = useState(false);
  const [slideIdx, setSlideIdx] = useState(0);

  // Preselecciona el primer slot libre cuando llega la lista (una vez por qid).
  if (slotsQuery.data && slotSyncId !== qid) {
    setSlotSyncId(qid);
    setSlotElegido(slotsQuery.data[0] ?? null);
  }

  const enCurso = aprobar.isPending || editar.isPending || rechazar.isPending || regenerar.isPending;

  async function onAprobar() {
    try {
      const res = await aprobar.mutateAsync(qid);
      if (slotElegido && slotElegido !== res.scheduled_datetime) {
        await editar.mutateAsync({ qid, scheduled_datetime: slotElegido });
        toast.success(`Aprobado y programado para ${formatearFecha(slotElegido)}`);
      } else {
        toast.success(`Aprobado, programado para ${formatearFecha(res.scheduled_datetime)}`);
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo aprobar");
    }
  }

  async function onRechazarYRegenerar() {
    try {
      await rechazar.mutateAsync(qid);
      const res = await regenerar.mutateAsync(qid);
      toast.success("Regenerando el carrusel");
      onRegenerar(res.job_id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo regenerar");
    }
  }

  if (isLoading || !item) {
    return <Skeleton className="h-96 w-full" />;
  }

  const puedeResolver = item.estado === "pendiente";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Carrusel generado
          <EstadoBadge estado={item.estado} />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <ImageCarousel imagenes={listaImagenes(item.imagen_url)} onIndexChange={setSlideIdx} />
        {item.caption && <p className="text-sm whitespace-pre-line">{item.caption}</p>}

        {puedeResolver && item.tipo === "slideshow" && slidesDe(item.slides_data) && (
          <div className="space-y-2 rounded-lg border p-3">
            <div className="flex items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium">¿Algo que cambiar?</p>
                <p className="text-xs text-muted-foreground">
                  Edita el texto o la imagen de cada slide antes de aprobar.
                </p>
              </div>
              <Button size="sm" variant={editandoSlides ? "outline" : "default"}
                onClick={() => setEditandoSlides((v) => !v)}>
                {editandoSlides ? "Cerrar editor" : "Editar slides"}
              </Button>
            </div>
            {editandoSlides && (
              <SlideEditor
                key={item.id}
                slug={slug}
                qid={item.id}
                slides={slidesDe(item.slides_data)!}
                slideIdx={slideIdx}
              />
            )}
          </div>
        )}

        {puedeResolver && (
          <div className="space-y-3 rounded-lg border p-3">
            <p className="text-sm font-medium">Programar para</p>
            <Select value={slotElegido ?? undefined} onValueChange={setSlotElegido}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Elige un horario" />
              </SelectTrigger>
              <SelectContent>
                {(slotsQuery.data ?? []).map((iso) => (
                  <SelectItem key={iso} value={iso}>
                    {formatearFecha(iso)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" disabled={enCurso} onClick={onRechazarYRegenerar}>
                {regenerar.isPending && <Loader2 className="animate-spin" />}
                Rechazar y regenerar
              </Button>
              <Button disabled={enCurso || !slotElegido} onClick={onAprobar}>
                {aprobar.isPending && <Loader2 className="animate-spin" />}
                Aprobar y programar
              </Button>
            </div>
          </div>
        )}

        {!puedeResolver && (
          <p className="text-sm text-muted-foreground">
            Este item ya está en estado &quot;{item.estado}&quot;; revísalo desde la biblioteca o
            el calendario.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
