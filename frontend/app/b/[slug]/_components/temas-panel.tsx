"use client";

import Link from "next/link";
import { Lightbulb } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { useTopics } from "@/hooks/use-topics";

export function TemasPanel({ slug }: { slug: string }) {
  const { data, isLoading, isError } = useTopics(slug);
  const temas = (data ?? []).slice(0, 5);

  // El endpoint de temas puede no estar disponible todavía en despliegues
  // parciales; en ese caso no mostramos error, solo omitimos la sección.
  if (isError) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Lightbulb className="size-4" />
          Temas sugeridos
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        )}
        {!isLoading && temas.length === 0 && (
          <p className="text-sm text-muted-foreground">No hay temas sugeridos por ahora.</p>
        )}
        {temas.map((tema) => (
          <div key={tema.id} className="flex items-start justify-between gap-3 rounded-lg border p-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{tema.titulo}</p>
              {tema.resumen && (
                <p className="line-clamp-2 text-xs text-muted-foreground">{tema.resumen}</p>
              )}
              {tema.fuente && <p className="text-xs text-muted-foreground">{tema.fuente}</p>}
            </div>
            <Button size="sm" variant="outline" className="shrink-0" asChild>
              <Link href={`/b/${slug}/create?topic=${tema.id}`}>Crear carrusel</Link>
            </Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
