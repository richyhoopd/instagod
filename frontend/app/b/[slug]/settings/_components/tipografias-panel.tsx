"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { useCatalogoTipografias, useInstalarTipografia } from "@/hooks/use-tipografias";

// Solo se monta para rol manager (los endpoints devuelven 403 a un editor).
export function TipografiasPanel({ slug }: { slug: string }) {
  const [q, setQ] = useState("");
  const [buscado, setBuscado] = useState("");
  const catalogo = useCatalogoTipografias(slug, buscado);
  const instalar = useInstalarTipografia(slug);

  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-medium">Tipografías de Fontsource</h3>
        <p className="text-xs text-muted-foreground">
          Se instalan como fuentes propias de la marca y aparecen en el editor.
        </p>
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setBuscado(q.trim());
        }}
      >
        <Label htmlFor="tipo-q" className="sr-only">Buscar tipografía</Label>
        <Input id="tipo-q" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Bebas, Inter, Playfair…" maxLength={60} />
        <Button type="submit" variant="secondary">Buscar</Button>
      </form>
      {catalogo.isLoading && <Skeleton className="h-24 w-full" />}
      {catalogo.error && (
        <p className="text-xs text-destructive">
          {catalogo.error.status === 403
            ? "Solo un manager puede instalar tipografías."
            : "No se pudo cargar el catálogo."}
        </p>
      )}
      <ul className="max-h-72 divide-y overflow-y-auto rounded-md border">
        {(catalogo.data ?? []).map((t) => (
          <li key={t.id} className="flex items-center justify-between gap-2 px-3 py-2">
            <div className="min-w-0">
              <p className="truncate text-sm">{t.familia}</p>
              <p className="text-xs text-muted-foreground">
                {t.categoria ?? "—"} · {t.pesos.join(", ")}
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={instalar.isPending || t.pesos.length === 0}
              onClick={() =>
                instalar.mutate(
                  { id: t.id, peso: t.pesos.includes(400) ? 400 : t.pesos[0] },
                  {
                    onSuccess: (r) => toast.success(`${r.familia} instalada`),
                    onError: (e) =>
                      toast.error(e instanceof ApiError ? e.detalle : "No se pudo instalar"),
                  },
                )
              }
            >
              Instalar
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
