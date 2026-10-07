"use client";

import { useState } from "react";
import { Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { resultadoDeJob, usePreviaDiseno, type ContratoPlantilla } from "@/hooks/use-disenos";
import { useJob } from "@/hooks/use-job";
import { ASPECTO_DE_FORMATO } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

// Renderiza la escena tal como está en el editor, sin guardarla. El aspecto
// sale del formato del lienzo, no de la columna del diseño (D13).
export function VistaPrevia({ slug, contrato }: { slug: string; contrato: ContratoPlantilla }) {
  const previa = usePreviaDiseno(slug);
  const [jobId, setJobId] = useState<number | null>(null);
  const job = useJob(slug, jobId);
  const url = resultadoDeJob<{ url: string }>(job.data)?.url;
  const fallo = previa.isError || job.data?.estado === "error" || job.data?.estado === "cancelado";

  function pedir() {
    const escena = useEditor.getState().escena;
    if (!escena) return;
    const aspecto = ASPECTO_DE_FORMATO[escena.lienzo.formato];
    setJobId(null);
    previa.mutate(
      { layout: escena, aspecto, contrato: { ...contrato, aspecto } },
      { onSuccess: (r) => setJobId(r.job_id) },
    );
  }

  return (
    <Dialog onOpenChange={(abierto) => abierto && pedir()}>
      <DialogTrigger asChild>
        <Button type="button" size="sm" variant="ghost">
          <Eye className="size-4" />
          Vista previa
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Vista previa</DialogTitle>
        </DialogHeader>
        {fallo ? (
          <p className="text-sm text-muted-foreground">No se pudo generar la vista previa.</p>
        ) : url ? (
          // eslint-disable-next-line @next/next/no-img-element -- PNG servido por la API vía rewrite
          <img src={`/api${url}`} alt="Vista previa del diseño" className="max-h-[70dvh] w-full object-contain" />
        ) : (
          <Skeleton className="aspect-[4/5] w-full" />
        )}
      </DialogContent>
    </Dialog>
  );
}
