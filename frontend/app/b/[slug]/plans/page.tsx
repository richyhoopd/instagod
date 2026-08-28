"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePlans, type EstadoPlan } from "@/hooks/use-plans";

import { NuevoPlanDialog } from "./_components/nuevo-plan-dialog";

export const ESTADOS_PLAN: Record<EstadoPlan, { label: string; clase: string }> = {
  proponiendo: { label: "Proponiendo temas", clase: "bg-blue-100 text-blue-800" },
  temas: { label: "Temas por revisar", clase: "bg-amber-100 text-amber-800" },
  generando: { label: "Generando", clase: "bg-blue-100 text-blue-800" },
  curacion: { label: "Por revisar", clase: "bg-purple-100 text-purple-800" },
  aprobado: { label: "Programado", clase: "bg-green-100 text-green-800" },
  error: { label: "Error", clase: "bg-red-100 text-red-800" },
};

export default function PlanesPage() {
  const { slug } = useParams<{ slug: string }>();
  const { data: planes, isLoading } = usePlans(slug);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Planes de contenido</h1>
          <p className="text-sm text-muted-foreground">
            Escribes el objetivo del periodo y se generan varias publicaciones de una vez.
          </p>
        </div>
        <NuevoPlanDialog slug={slug} />
      </div>

      {isLoading && (
        <div className="grid gap-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      )}

      {planes?.length === 0 && (
        <p className="py-12 text-center text-sm text-muted-foreground">
          Todavía no hay planes. Crea el primero y te proponemos los temas.
        </p>
      )}

      <div className="grid gap-3">
        {planes?.map((p) => {
          const estado = ESTADOS_PLAN[p.estado] ?? { label: p.estado, clase: "" };
          return (
            <Link key={p.id} href={`/b/${slug}/plans/${p.id}`}>
              <Card className="transition-colors hover:bg-accent/50">
                <CardContent className="flex items-center justify-between gap-4 p-4">
                  <div className="min-w-0">
                    <p className="font-medium">
                      {p.tipo_periodo === "semana" ? "Semana" : "Mes"} {p.periodo}
                    </p>
                    <p className="truncate text-sm text-muted-foreground">{p.objetivo}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <span className="hidden text-sm text-muted-foreground sm:inline">
                      {p.topics_aprobados}/{p.topics_total} temas · {p.piezas} piezas
                      {p.piezas_pendientes > 0 && ` (${p.piezas_pendientes} por revisar)`}
                    </span>
                    <Badge variant="secondary" className={estado.clase}>
                      {estado.label}
                    </Badge>
                  </div>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
