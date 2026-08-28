"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { usePlan } from "@/hooks/use-plans";

import { ESTADOS_PLAN } from "../page";
import { CuradorPiezas } from "./_components/curador-piezas";
import { CuradorTemas } from "./_components/curador-temas";

export default function PlanPage() {
  const { slug, pid } = useParams<{ slug: string; pid: string }>();
  const { data: plan, isLoading } = usePlan(slug, Number(pid));

  if (isLoading || !plan) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  const estado = ESTADOS_PLAN[plan.estado] ?? { label: plan.estado, clase: "" };
  const trabajando = plan.estado === "proponiendo" || plan.estado === "generando";
  // Un plan en 'error' se puede reintentar: si ya hay piezas se curan, y si no,
  // se vuelve a la lista de temas (el backend acepta generar desde 'error').
  const verTemas =
    plan.estado === "temas" || (plan.estado === "error" && plan.piezas.length === 0);
  const verPiezas =
    plan.estado === "curacion" ||
    plan.estado === "aprobado" ||
    (plan.estado === "error" && plan.piezas.length > 0);

  return (
    <div className="space-y-4">
      <Link
        href={`/b/${slug}/plans`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> Planes
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">
            Plan {plan.tipo_periodo === "semana" ? "semanal" : "mensual"} {plan.periodo}
          </h1>
          <p className="text-sm text-muted-foreground">{plan.objetivo}</p>
        </div>
        <Badge variant="secondary" className={estado.clase}>
          {estado.label}
        </Badge>
      </div>

      {plan.estado === "error" && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          El plan falló: {plan.error ?? "error desconocido"}.
          {plan.topics_aprobados > 0
            ? " Los temas siguen aquí: puedes generar de nuevo."
            : " Crea un plan nuevo para intentarlo otra vez."}
        </div>
      )}

      {trabajando && (
        <div className="flex items-center gap-3 rounded-md border p-4 text-sm">
          <Loader2 className="size-4 animate-spin" />
          <div>
            <p className="font-medium">
              {plan.estado === "proponiendo"
                ? "Proponiendo temas…"
                : `Generando ${plan.topics_aprobados} publicaciones…`}
            </p>
            <p className="text-muted-foreground">
              Corre en segundo plano; esta pantalla se actualiza sola. Puedes cerrarla.
            </p>
          </div>
        </div>
      )}

      {verTemas && <CuradorTemas slug={slug} plan={plan} />}

      {verPiezas && <CuradorPiezas slug={slug} plan={plan} />}
    </div>
  );
}
