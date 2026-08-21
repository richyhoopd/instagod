"use client";

import Link from "next/link";
import { CheckCircle2, ExternalLink, ServerCrash, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useBrands } from "@/hooks/use-brands";
import { useHealth } from "@/hooks/use-health";
import { JobsMarca } from "./_components/jobs-marca";

export default function AdminSystemPage() {
  const { data: marcas, isLoading: cargandoMarcas } = useBrands();
  const health = useHealth();

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Sistema</h2>
        <p className="text-sm text-muted-foreground">
          Estado del servidor y actividad reciente de jobs por marca.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Estado de la API</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          {health.isLoading && <Skeleton className="h-6 w-40" />}
          {health.isError && (
            <Badge variant="outline" className="gap-1 border-red-300 text-red-700 dark:text-red-400">
              <ServerCrash className="size-3" />
              No responde
            </Badge>
          )}
          {health.data && (
            <>
              <Badge
                variant="outline"
                className={
                  health.data.ok
                    ? "gap-1 border-green-300 text-green-700 dark:text-green-400"
                    : "gap-1 border-red-300 text-red-700 dark:text-red-400"
                }
              >
                {health.data.ok ? <CheckCircle2 className="size-3" /> : <XCircle className="size-3" />}
                {health.data.ok ? "Operando" : "Con problemas"}
              </Badge>
              <span className="text-sm text-muted-foreground">Versión {health.data.version}</span>
            </>
          )}
          <Button variant="outline" size="sm" className="ml-auto" asChild>
            <Link href="/api/docs" target="_blank" rel="noopener noreferrer">
              <ExternalLink className="size-3.5" />
              Documentación de la API
            </Link>
          </Button>
        </CardContent>
      </Card>

      <div>
        <h3 className="mb-3 text-sm font-medium">Jobs recientes por marca</h3>
        {cargandoMarcas && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-40 rounded-xl" />
            ))}
          </div>
        )}
        {!cargandoMarcas && (!marcas || marcas.length === 0) && (
          <p className="text-sm text-muted-foreground">No hay marcas creadas todavía.</p>
        )}
        {!cargandoMarcas && marcas && marcas.length > 0 && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {marcas.map((m) => (
              <JobsMarca key={m.slug} marca={m} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
