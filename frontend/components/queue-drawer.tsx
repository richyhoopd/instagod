"use client";

import { useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { EstadoBadge } from "@/components/estado-badge";
import { ImageCarousel } from "@/components/image-carousel";
import { SlideEditor, slidesDe } from "@/components/slide-editor";
import { ApiError, get } from "@/lib/api";
import { formatearFecha } from "@/lib/fecha";
import { temaLimpio } from "@/lib/formatos";
import { listaImagenes } from "@/lib/imagenes";
import {
  useAprobar,
  useEditarQueue,
  useEliminarQueue,
  useQueueDetail,
  useRechazar,
  useRegenerar,
  useSlotsProximos,
} from "@/hooks/use-queue";
import type { Estado } from "@/lib/estados";

const EDITABLES: Estado[] = ["pendiente", "programado", "error"];
const ELIMINABLES: Estado[] = ["pendiente", "rechazado", "error"];

const TIPO_LABEL: Record<string, string> = {
  slideshow: "Carrusel",
  anuncio: "Anuncio",
  meme: "Meme",
};

export function QueueDrawer({
  slug,
  qid,
  onOpenChange,
}: {
  slug: string;
  qid: number | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: item, isLoading } = useQueueDetail(slug, qid);
  const editar = useEditarQueue(slug);
  const aprobar = useAprobar(slug);
  const rechazar = useRechazar(slug);
  const regenerar = useRegenerar(slug);
  const eliminar = useEliminarQueue(slug);

  const [caption, setCaption] = useState("");
  const [captionSyncId, setCaptionSyncId] = useState<number | null>(null);
  const [reintentando, setReintentando] = useState(false);
  const [slideIdx, setSlideIdx] = useState(0);
  const [editandoSlides, setEditandoSlides] = useState(false);
  const [slotElegido, setSlotElegido] = useState("");
  const slotsQuery = useSlotsProximos(slug, 20);

  // Sincroniza el borrador de caption cuando cambia el item mostrado (nueva
  // fila u otro fetch tras guardar), sin usar un efecto (react-hooks/set-state-in-effect).
  if (item && captionSyncId !== item.id) {
    setCaptionSyncId(item.id);
    setCaption(item.caption ?? "");
    setSlideIdx(0);
    setEditandoSlides(false);
    setSlotElegido("");
  }

  const puedeEditar = item ? EDITABLES.includes(item.estado) : false;
  const puedeEliminar = item ? ELIMINABLES.includes(item.estado) : false;
  const puedeRegenerar = item
    ? item.tipo === "slideshow" && (item.estado === "pendiente" || item.estado === "rechazado")
    : false;
  const enCurso =
    editar.isPending ||
    aprobar.isPending ||
    rechazar.isPending ||
    regenerar.isPending ||
    eliminar.isPending;

  async function onGuardarCaption() {
    if (!item) return;
    try {
      await editar.mutateAsync({ qid: item.id, caption });
      toast.success("Caption actualizado");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo guardar el caption");
    }
  }

  async function onAprobar() {
    if (!item) return;
    try {
      const res = await aprobar.mutateAsync(item.id);
      toast.success(`Aprobado, programado para ${formatearFecha(res.scheduled_datetime)}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo aprobar");
    }
  }

  async function onRechazar() {
    if (!item) return;
    try {
      await rechazar.mutateAsync(item.id);
      toast.success("Rechazado");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo rechazar");
    }
  }

  async function onRegenerar() {
    if (!item) return;
    try {
      await regenerar.mutateAsync(item.id);
      toast.success("Regenerando el carrusel");
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo regenerar");
    }
  }

  async function onEliminar() {
    if (!item) return;
    try {
      await eliminar.mutateAsync(item.id);
      toast.success("Publicación eliminada");
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo eliminar");
    }
  }

  async function onCambiarHorario() {
    if (!item || !slotElegido) return;
    try {
      await editar.mutateAsync({ qid: item.id, scheduled_datetime: slotElegido });
      toast.success(`Horario cambiado a ${formatearFecha(slotElegido)}`);
      setSlotElegido("");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo cambiar el horario");
    }
  }

  async function onReintentar() {
    if (!item) return;
    setReintentando(true);
    try {
      const slots = await get<string[]>(`/brands/${slug}/slots/proximos?n=1`);
      const slot = slots[0];
      if (!slot) {
        toast.error("No hay slots libres disponibles");
        return;
      }
      await editar.mutateAsync({ qid: item.id, scheduled_datetime: slot });
      toast.success(`Reprogramado para ${formatearFecha(slot)}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo reprogramar");
    } finally {
      setReintentando(false);
    }
  }

  return (
    <Dialog open={qid !== null} onOpenChange={(v) => !v && onOpenChange(false)}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {item ? (TIPO_LABEL[item.tipo] ?? item.tipo) : "Publicación"}
            {item && (
              <span className="ml-2 text-xs font-normal text-muted-foreground/60">#{item.id}</span>
            )}
          </DialogTitle>
          {item && (
            <DialogDescription className="flex items-center gap-2">
              <EstadoBadge estado={item.estado} />
              {item.scheduled_datetime && <span>{formatearFecha(item.scheduled_datetime)}</span>}
            </DialogDescription>
          )}
        </DialogHeader>

        {isLoading || !item ? (
          <div className="space-y-3">
            <Skeleton className="h-56 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : (
          <div className="space-y-4">
            <ImageCarousel imagenes={listaImagenes(item.imagen_url)} onIndexChange={setSlideIdx} />

            {item.tipo === "slideshow" && puedeEditar && slidesDe(item.slides_data) && (
              <div className="space-y-2">
                <Button size="sm" variant="outline" onClick={() => setEditandoSlides((v) => !v)}>
                  {editandoSlides ? "Cerrar editor de slides" : "Editar slides"}
                </Button>
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

            {item.error && (
              <div className="flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-500/10 dark:text-red-400">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                <div className="flex-1 space-y-2">
                  <p>{item.error}</p>
                  <Button size="sm" variant="outline" disabled={reintentando} onClick={onReintentar}>
                    {reintentando && <Loader2 className="animate-spin" />}
                    Reintentar
                  </Button>
                </div>
              </div>
            )}

            <div className="space-y-2">
              <Textarea
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
                disabled={!puedeEditar}
                rows={4}
                placeholder="Caption..."
              />
              {puedeEditar && caption !== (item.caption ?? "") && (
                <Button size="sm" disabled={editar.isPending} onClick={onGuardarCaption}>
                  {editar.isPending && <Loader2 className="animate-spin" />}
                  Guardar caption
                </Button>
              )}
            </div>

            {puedeEditar && (
              <div className="space-y-1.5">
                <p className="text-sm font-medium">
                  {item.estado === "programado" ? "Cambiar horario" : "Asignar horario"}
                </p>
                <div className="flex gap-2">
                  <select
                    aria-label="Horario libre"
                    className="border-input dark:bg-input/30 h-9 min-w-0 flex-1 rounded-md border bg-transparent px-3 text-sm"
                    value={slotElegido}
                    onChange={(e) => setSlotElegido(e.target.value)}
                  >
                    <option value="">Elegir un horario libre...</option>
                    {(slotsQuery.data ?? []).map((iso) => (
                      <option key={iso} value={iso}>
                        {formatearFecha(iso)}
                      </option>
                    ))}
                  </select>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-9"
                    disabled={!slotElegido || enCurso}
                    onClick={onCambiarHorario}
                  >
                    {editar.isPending && <Loader2 className="animate-spin" />}
                    Mover
                  </Button>
                </div>
                {item.estado === "pendiente" && (
                  <p className="text-xs text-muted-foreground">
                    Asignar horario no publica: la publicación sigue pendiente de aprobar.
                  </p>
                )}
              </div>
            )}

            {item.tema_semilla && (
              <p className="text-xs text-muted-foreground">
                Tema: {temaLimpio(item.tema_semilla) || item.tema_semilla}
              </p>
            )}
          </div>
        )}

        {item && (
          <DialogFooter className="flex-wrap justify-between sm:justify-between">
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="outline"
                  className="text-destructive"
                  disabled={!puedeEliminar || enCurso}
                >
                  Eliminar
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>¿Eliminar esta publicación?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Se quitará de la cola de contenido y no se puede deshacer.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancelar</AlertDialogCancel>
                  <AlertDialogAction onClick={onEliminar}>Eliminar</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>

            <div className="flex flex-wrap gap-2">
              {puedeRegenerar && (
                <Button variant="outline" disabled={enCurso} onClick={onRegenerar}>
                  {regenerar.isPending && <Loader2 className="animate-spin" />}
                  Regenerar
                </Button>
              )}
              {item.estado === "pendiente" && (
                <>
                  <Button variant="outline" disabled={enCurso} onClick={onRechazar}>
                    Rechazar
                  </Button>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button disabled={enCurso}>
                        {aprobar.isPending && <Loader2 className="animate-spin" />}
                        Aprobar
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>¿Aprobar esta publicación?</AlertDialogTitle>
                        <AlertDialogDescription>
                          Se programará en el siguiente horario libre y se publicará
                          automáticamente en el Instagram de la marca.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancelar</AlertDialogCancel>
                        <AlertDialogAction onClick={onAprobar}>
                          Aprobar y programar
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </>
              )}
            </div>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
