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
import { ApiError } from "@/lib/api";
import { formatearFecha } from "@/lib/fecha";
import { miniatura, primeraImagen } from "@/lib/imagenes";
import {
  useAprobar,
  useEditarQueue,
  useQueueDetail,
  useRechazar,
  useSlotsProximos,
} from "@/hooks/use-queue";

const N_SLOTS = 8;

// Igual que ResultadoCarrusel, pero con <video>. "Otra versión" no usa
// /queue/{id}/regenerar (solo sabe de slideshows): rechaza y vuelve a
// encolar video.generar con la misma historia desde el wizard.
export function ResultadoReel({
  slug,
  qid,
  onOtraVersion,
}: {
  slug: string;
  qid: number;
  onOtraVersion: () => Promise<void>;
}) {
  const { data: item, isLoading } = useQueueDetail(slug, qid);
  const slotsQuery = useSlotsProximos(slug, N_SLOTS);
  const aprobar = useAprobar(slug);
  const editar = useEditarQueue(slug);
  const rechazar = useRechazar(slug);

  const [slotElegido, setSlotElegido] = useState<string | null>(null);
  const [slotSyncId, setSlotSyncId] = useState<number | null>(null);
  const [regenerando, setRegenerando] = useState(false);

  if (slotsQuery.data && slotSyncId !== qid) {
    setSlotSyncId(qid);
    setSlotElegido(slotsQuery.data[0] ?? null);
  }

  const enCurso = aprobar.isPending || editar.isPending || rechazar.isPending || regenerando;

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

  async function onRechazarYOtra() {
    setRegenerando(true);
    try {
      await rechazar.mutateAsync(qid);
      await onOtraVersion();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo generar otra versión");
    } finally {
      setRegenerando(false);
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
          Reel generado
          <EstadoBadge estado={item.estado} />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <video
          src={primeraImagen(item.imagen_url) ?? undefined}
          poster={miniatura(item.imagen_url) ?? undefined}
          controls
          playsInline
          className="max-h-[60vh] w-full rounded-md bg-black object-contain"
        />
        {item.caption && <p className="text-sm whitespace-pre-line">{item.caption}</p>}

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
              <Button variant="outline" disabled={enCurso} onClick={onRechazarYOtra}>
                {regenerando && <Loader2 className="animate-spin" />}
                Rechazar y generar otro
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
