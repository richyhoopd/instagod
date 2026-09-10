"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";
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
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useJob } from "@/hooks/use-job";
import { useEnviarLote, useLote } from "@/hooks/use-lotes";

import { PiezaLoteCard } from "../_components/pieza-lote";

export default function LotePage() {
  const { slug, mes } = useParams<{ slug: string; mes: string }>();
  const { data: lote, isLoading, error } = useLote(slug, mes);
  const { data: job } = useJob(slug, lote?.job_id ?? null);
  const enviar = useEnviarLote(slug, mes);

  if (error?.status === 422) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        Los lotes de memes de banda solo existen para gdlscene.
      </p>
    );
  }

  const mandando = !!lote?.job_id;
  const piezas = lote?.piezas ?? [];

  return (
    <div className="space-y-4">
      <Link
        href={`/b/${slug}/lotes`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        Lotes
      </Link>

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Lote de {mes}</h1>
          <p className="text-sm text-muted-foreground">
            {piezas.length} {piezas.length === 1 ? "pieza" : "piezas"} en borrador
            {lote ? ` · ${lote.slots.length} horarios al día` : ""}
          </p>
        </div>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button disabled={mandando || enviar.isPending || piezas.length === 0}>
              {mandando || enviar.isPending ? "Mandando…" : "Mandar a Telegram"}
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>¿Mandar {piezas.length} memes a Telegram?</AlertDialogTitle>
              <AlertDialogDescription>
                Se componen y se mandan al canal para que los apruebes ahí con los
                botones. Una vez mandadas, las piezas ya no se curan desde aquí.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancelar</AlertDialogCancel>
              <AlertDialogAction
                onClick={() =>
                  enviar.mutate(undefined, {
                    onSuccess: ({ piezas: n }) => toast.success(`${n} piezas en cola`),
                    onError: (e) =>
                      toast.error(e instanceof Error ? e.message : "No se pudo mandar"),
                  })
                }
              >
                Mandar
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>

      {mandando && (
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <Loader2 className="size-4 animate-spin text-muted-foreground" />
            <div className="min-w-0">
              <p className="text-sm font-medium">Mandando a Telegram</p>
              <p className="truncate text-xs text-muted-foreground">
                {job?.log ?? "En cola…"}
                {job?.progreso != null && ` · ${job.progreso}%`}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {isLoading && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-72 w-full" />
        </div>
      )}

      {lote && piezas.length === 0 && (
        <p className="py-12 text-center text-sm text-muted-foreground">
          Este mes ya no tiene borradores. Plánealo de nuevo desde Lotes.
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
        {piezas.map((p) => (
          <PiezaLoteCard
            key={p.id}
            slug={slug}
            mes={mes}
            pieza={p}
            bloqueado={mandando}
          />
        ))}
      </div>
    </div>
  );
}
