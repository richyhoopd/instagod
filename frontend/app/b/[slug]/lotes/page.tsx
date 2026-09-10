"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useLotes } from "@/hooks/use-lotes";

import { NuevoLoteDialog } from "./_components/nuevo-lote-dialog";

export default function LotesPage() {
  const { slug } = useParams<{ slug: string }>();
  const { data: meses, isLoading, error } = useLotes(slug);

  // 422 no_aplica: la marca no es gdlscene y esta pantalla no le sirve de nada.
  if (error?.status === 422) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        Los lotes de memes de banda solo existen para gdlscene.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Lotes de memes</h1>
          <p className="text-sm text-muted-foreground">
            Planeas el mes con un criterio, curas foto por foto y lo mandas a Telegram.
          </p>
        </div>
        <NuevoLoteDialog slug={slug} />
      </div>

      {isLoading && (
        <div className="grid gap-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      )}

      {meses?.length === 0 && (
        <p className="py-12 text-center text-sm text-muted-foreground">
          No hay borradores por curar. Planea el mes que sigue.
        </p>
      )}

      <div className="grid gap-3">
        {meses?.map((m) => (
          <Link key={m.mes} href={`/b/${slug}/lotes/${m.mes}`}>
            <Card className="transition-colors hover:bg-accent/50">
              <CardContent className="flex items-center justify-between gap-4 p-4">
                <div className="min-w-0">
                  <p className="font-medium">{m.mes}</p>
                  <p className="text-sm text-muted-foreground">
                    {m.piezas} {m.piezas === 1 ? "pieza" : "piezas"} por curar
                  </p>
                </div>
                {m.job_id ? (
                  <Badge variant="secondary" className="shrink-0 bg-blue-100 text-blue-800">
                    <Loader2 className="mr-1 size-3.5 animate-spin" />
                    Mandando
                  </Badge>
                ) : (
                  <Badge variant="secondary" className="shrink-0 bg-amber-100 text-amber-800">
                    Borrador
                  </Badge>
                )}
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
