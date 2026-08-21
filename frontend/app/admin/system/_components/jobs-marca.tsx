"use client";

import { CheckCircle2, CircleDashed, Loader2, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { NoDisponible } from "@/components/no-disponible";
import { BrandAvatar } from "@/components/brand-avatar";
import { formatearFecha } from "@/lib/fecha";
import { useJobs, type Job, type JobEstado } from "@/hooks/use-job";
import type { Brand } from "@/hooks/use-brands";

const ICONO: Record<JobEstado, typeof Loader2> = {
  cola: CircleDashed,
  corriendo: Loader2,
  ok: CheckCircle2,
  error: XCircle,
  cancelado: XCircle,
};

const CLASE: Record<JobEstado, string> = {
  cola: "text-muted-foreground",
  corriendo: "text-blue-600 dark:text-blue-400",
  ok: "text-green-600 dark:text-green-400",
  error: "text-red-600 dark:text-red-400",
  cancelado: "text-muted-foreground",
};

function FilaJob({ job }: { job: Job }) {
  const Icono = ICONO[job.estado];
  return (
    <div className="flex items-center gap-2 py-1.5 text-sm">
      <Icono className={`size-3.5 shrink-0 ${CLASE[job.estado]} ${job.estado === "corriendo" ? "animate-spin" : ""}`} />
      <span className="min-w-0 flex-1 truncate">{job.tipo}</span>
      <span className="shrink-0 text-xs text-muted-foreground">{formatearFecha(job.created_at)}</span>
    </div>
  );
}

export function JobsMarca({ marca }: { marca: Brand }) {
  const { data, isLoading, isError } = useJobs(marca.slug);
  const jobs = (data ?? []).slice(0, 5);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <BrandAvatar
            slug={marca.slug}
            nombre={marca.nombre}
            colorMarca={marca.color_marca}
            logoPath={marca.logo_path}
            className="size-5"
          />
          {marca.nombre}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="space-y-1.5">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-full" />
          </div>
        )}
        {isError && <NoDisponible mensaje="No se pudieron cargar los jobs de esta marca." />}
        {!isLoading && !isError && jobs.length === 0 && (
          <p className="text-sm text-muted-foreground">Sin jobs recientes.</p>
        )}
        {!isLoading && !isError && jobs.map((j) => <FilaJob key={j.id} job={j} />)}
      </CardContent>
    </Card>
  );
}
