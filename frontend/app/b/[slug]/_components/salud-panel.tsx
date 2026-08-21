"use client";

import { CheckCircle2, HeartPulse, Loader2, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { usePrueba, type TipoPrueba } from "@/hooks/use-pruebas";

const CANALES: { tipo: TipoPrueba; label: string }[] = [
  { tipo: "telegram", label: "Telegram" },
  { tipo: "instagram", label: "Instagram" },
  { tipo: "llm", label: "LLM" },
];

function SaludChip({ slug, tipo, label }: { slug: string; tipo: TipoPrueba; label: string }) {
  const prueba = usePrueba(slug, tipo);

  const estado = prueba.isPending
    ? "cargando"
    : prueba.isSuccess
      ? "ok"
      : prueba.isError
        ? "error"
        : "idle";

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg border p-3",
        estado === "ok" && "border-green-300 bg-green-50 dark:border-green-900 dark:bg-green-500/10",
        estado === "error" && "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-500/10"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{label}</span>
        {estado === "ok" && <CheckCircle2 className="size-4 text-green-600 dark:text-green-400" />}
        {estado === "error" && <XCircle className="size-4 text-red-600 dark:text-red-400" />}
      </div>
      <Button
        size="sm"
        variant="outline"
        disabled={prueba.isPending}
        onClick={() => prueba.mutate()}
      >
        {prueba.isPending && <Loader2 className="animate-spin" />}
        Probar
      </Button>
      {estado === "ok" && (
        <p className="text-xs text-muted-foreground">
          {prueba.data?.respuesta || prueba.data?.username || prueba.data?.detalle || "Conectado"}
        </p>
      )}
      {estado === "error" && (
        <p className="text-xs text-red-700 dark:text-red-400">{prueba.error?.detalle}</p>
      )}
    </div>
  );
}

export function SaludPanel({ slug }: { slug: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <HeartPulse className="size-4" />
          Salud de conexiones
        </CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {CANALES.map((c) => (
          <SaludChip key={c.tipo} slug={slug} tipo={c.tipo} label={c.label} />
        ))}
      </CardContent>
    </Card>
  );
}
