"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EstadoBadge } from "@/components/estado-badge";
import { useJob } from "@/hooks/use-job";
import { ResultadoCarrusel } from "./resultado-carrusel";
import { ResultadoReel } from "./resultado-reel";

// Nombre de la pieza en los textos, según el tipo de job.
function piezaDe(tipo: string): string {
  if (tipo === "video.generar") return "el reel";
  if (tipo.startsWith("post")) return "el post";
  return "el carrusel";
}

export function ProgresoJob({
  slug,
  jobId,
  onNuevoJob,
  onReintentarError,
  onVolver,
}: {
  slug: string;
  jobId: number;
  onNuevoJob: (jobId: number) => void;
  // Vuelve a encolar con los mismos parámetros del wizard.
  onReintentarError: () => void | Promise<void>;
  onVolver: () => void;
}) {
  const { data: job, isLoading } = useJob(slug, jobId);

  if (isLoading || !job) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Cargando el trabajo...
        </CardContent>
      </Card>
    );
  }

  const pieza = piezaDe(job.tipo);

  if (job.estado === "ok" && job.queue_id && job.tipo === "video.generar") {
    return (
      <ResultadoReel slug={slug} qid={job.queue_id} onOtraVersion={async () => onReintentarError()} />
    );
  }

  if (job.estado === "ok" && job.queue_id) {
    return <ResultadoCarrusel slug={slug} qid={job.queue_id} onRegenerar={onNuevoJob} />;
  }

  if (job.estado === "error" || job.estado === "cancelado" || (job.estado === "ok" && !job.queue_id)) {
    const lineas = (job.log ?? "").split("\n").filter(Boolean);
    const errorLinea = [...lineas].reverse().find((l) => l.startsWith("[error]"));
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="size-4" />
            {job.estado === "cancelado" ? "Trabajo cancelado" : `Error al generar ${pieza}`}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            {errorLinea?.replace("[error] ", "") ?? "Ocurrió un error inesperado."}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={onVolver}>
              Cambiar parámetros
            </Button>
            <Button onClick={onReintentarError}>Reintentar</Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  // estado 'cola' o 'corriendo'
  const lineas = (job.log ?? "").split("\n").filter(Boolean);
  const ultimaLinea = lineas[lineas.length - 1];
  const progreso = Math.min(100, Math.max(0, job.progreso ?? 0));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {job.estado === "cola" ? "En cola" : `Generando ${pieza}...`}
          <EstadoBadge estado="generando" />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-(--brand) transition-all"
            style={{ width: `${progreso > 0 ? progreso : 4}%` }}
          />
        </div>
        <p className="text-xs text-muted-foreground">{progreso}%</p>
        {ultimaLinea && (
          <p className="truncate rounded-md bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">
            {ultimaLinea}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
