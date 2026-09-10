"use client";

import { useState } from "react";
import { toast } from "sonner";

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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { formatearFecha } from "@/lib/fecha";
import {
  useCambiarPieza,
  useEditarPieza,
  useEliminarPieza,
  useMarcarFlyer,
  type PiezaLote,
  type Reemplazo,
} from "@/hooks/use-lotes";

/** Un slot vacío significa que el pool de fotos de ese criterio se agotó. */
function avisarReemplazo({ reemplazo }: Reemplazo, hecho: string) {
  if (reemplazo) toast.success(`${hecho}. Entró otra banda al slot.`);
  else toast.warning(`${hecho}, pero ya no hay fotos disponibles para ese slot.`);
}

export function PiezaLoteCard({
  slug,
  mes,
  pieza,
  bloqueado,
}: {
  slug: string;
  mes: string;
  pieza: PiezaLote;
  bloqueado: boolean;
}) {
  const editar = useEditarPieza(slug, mes);
  const cambiar = useCambiarPieza(slug, mes);
  const flyer = useMarcarFlyer(slug, mes);
  const eliminar = useEliminarPieza(slug, mes);
  // Sin sincronizar contra el server: un reemplazo trae `id` nuevo y la tarjeta
  // (keyed por id en la grilla) se remonta sola con el tema que venga.
  const [tema, setTema] = useState(pieza.tema_semilla ?? "");

  const ocupado =
    bloqueado || cambiar.isPending || flyer.isPending || eliminar.isPending;

  const guardarTema = () => {
    const limpio = tema.trim();
    if (limpio === (pieza.tema_semilla ?? "")) return;
    editar.mutate(
      { qid: pieza.id, tema_semilla: limpio || null },
      {
        onError: (e) =>
          toast.error(e instanceof Error ? e.message : "No se pudo guardar el tema"),
      },
    );
  };

  const fallo = (e: unknown, texto: string) =>
    toast.error(e instanceof Error ? e.message : texto);

  return (
    <Card className="overflow-hidden py-0">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`/api/brands/${slug}/lotes/foto/${pieza.photo_id}`}
        alt={pieza.banda}
        className="aspect-[4/5] w-full object-cover"
      />
      <CardContent className="grid gap-2 p-3">
        <div className="min-w-0">
          <p className="truncate font-medium">{pieza.banda}</p>
          <p className="truncate text-xs text-muted-foreground">
            {pieza.ig_handle ? `@${pieza.ig_handle} · ` : ""}
            {pieza.followers_ig?.toLocaleString("es-MX") ?? "sin datos"} seguidores
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary">{pieza.tipo}</Badge>
          <Badge variant="outline">P{pieza.prioridad}</Badge>
          <span className="text-xs text-muted-foreground">
            {formatearFecha(pieza.scheduled_datetime)}
          </span>
        </div>

        <Input
          value={tema}
          onChange={(e) => setTema(e.target.value)}
          onBlur={guardarTema}
          disabled={bloqueado}
          placeholder="Tema del chiste (opcional)"
          className="h-8 text-sm"
        />

        <div className="flex gap-1.5">
          <Button
            variant="outline"
            size="sm"
            className="flex-1"
            disabled={ocupado}
            onClick={() =>
              cambiar.mutate(pieza.id, {
                onSuccess: (r) => avisarReemplazo(r, "Cambiada"),
                onError: (e) => fallo(e, "No se pudo cambiar"),
              })
            }
          >
            {cambiar.isPending ? "Cambiando…" : "Cambiar"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="flex-1"
            disabled={ocupado}
            onClick={() =>
              flyer.mutate(pieza.id, {
                onSuccess: (r) => avisarReemplazo(r, "Marcada como flyer"),
                onError: (e) => fallo(e, "No se pudo marcar como flyer"),
              })
            }
          >
            {flyer.isPending ? "Marcando…" : "Flyer"}
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="ghost" size="sm" disabled={ocupado}>
                Nunca
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>¿Nunca volver a sugerir esta foto?</AlertDialogTitle>
                <AlertDialogDescription>
                  Va a la lista negra de {pieza.banda}. No regresa ni aunque se
                  reclasifique la banda. Otra entra a su lugar.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancelar</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() =>
                    eliminar.mutate(pieza.id, {
                      onSuccess: (r) => avisarReemplazo(r, "A la lista negra"),
                      onError: (e) => fallo(e, "No se pudo eliminar"),
                    })
                  }
                >
                  Sí, nunca
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </CardContent>
    </Card>
  );
}
