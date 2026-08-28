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
import { QueueDrawer } from "@/components/queue-drawer";
import { formatearFecha } from "@/lib/fecha";
import { contarImagenes, primeraImagen } from "@/lib/imagenes";
import { useAprobarPlan, type PiezaPlan, type PlanDetail } from "@/hooks/use-plans";

function etiqueta(pieza: PiezaPlan): { texto: string; clase: string } {
  if (pieza.error) return { texto: "error", clase: "bg-red-100 text-red-800" };
  if (pieza.aprobacion === "pendiente")
    return { texto: "por revisar", clase: "bg-amber-100 text-amber-800" };
  if (pieza.status === "publicado")
    return { texto: "publicada", clase: "bg-green-100 text-green-800" };
  if (pieza.scheduled_datetime)
    return {
      texto: formatearFecha(pieza.scheduled_datetime),
      clase: "bg-blue-100 text-blue-800",
    };
  return { texto: pieza.status, clase: "" };
}

export function CuradorPiezas({ slug, plan }: { slug: string; plan: PlanDetail }) {
  const aprobar = useAprobarPlan(slug, plan.id);
  const [abierta, setAbierta] = useState<number | null>(null);
  const pendientes = plan.piezas.filter((p) => p.aprobacion === "pendiente");
  const conError = plan.topics.filter((t) => t.estado === "error");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {pendientes.length > 0
            ? `${pendientes.length} de ${plan.piezas.length} publicaciones por revisar.`
            : `Las ${plan.piezas.length} publicaciones ya están programadas.`}{" "}
          Abre cualquiera para editar sus textos, cambiar imágenes o descartarla.
        </p>
        {pendientes.length > 0 && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button disabled={aprobar.isPending}>
                {aprobar.isPending
                  ? "Programando…"
                  : `Aprobar ${pendientes.length} pendientes`}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>¿Aprobar todo lo pendiente?</AlertDialogTitle>
                <AlertDialogDescription>
                  Cada publicación toma el siguiente horario libre de la marca y se publica
                  sola. Las que descartaste no entran.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancelar</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() =>
                    aprobar.mutate(
                      {},
                      {
                        onSuccess: ({ aprobadas, fallidas }) => {
                          if (aprobadas.length > 0)
                            toast.success(
                              `${aprobadas.length} publicaciones programadas`,
                            );
                          if (fallidas.length > 0)
                            toast.error(
                              `${fallidas.length} no se pudieron programar; revisa sus horarios`,
                            );
                        },
                        onError: (e) =>
                          toast.error(
                            e instanceof Error ? e.message : "No se pudo aprobar",
                          ),
                      },
                    )
                  }
                >
                  Aprobar todas
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>

      {conError.length > 0 && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          {conError.length} {conError.length === 1 ? "tema no se pudo" : "temas no se pudieron"}{" "}
          generar: {conError.map((t) => t.titulo).join(" · ")}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
        {plan.piezas.map((p) => {
          const badge = etiqueta(p);
          const portada = primeraImagen(p.imagen_url);
          const slides = contarImagenes(p.imagen_url);
          return (
            <Card
              key={p.id}
              className="cursor-pointer overflow-hidden py-0 transition hover:ring-2 hover:ring-ring"
              onClick={() => setAbierta(p.id)}
            >
              <CardContent className="p-0">
                {portada ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={portada}
                    alt=""
                    className="aspect-[4/5] w-full object-cover"
                  />
                ) : (
                  <div className="flex aspect-[4/5] w-full items-center justify-center bg-muted text-xs text-muted-foreground">
                    sin imagen
                  </div>
                )}
                <div className="space-y-1 p-2">
                  <p className="line-clamp-2 text-xs">{p.caption ?? "(sin texto)"}</p>
                  <div className="flex items-center justify-between gap-1">
                    <Badge variant="secondary" className={`${badge.clase} text-xs`}>
                      {badge.texto}
                    </Badge>
                    {slides > 1 && (
                      <span className="text-xs text-muted-foreground">
                        {slides} slides
                      </span>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <QueueDrawer
        slug={slug}
        qid={abierta}
        onOpenChange={(open) => !open && setAbierta(null)}
      />
    </div>
  );
}
