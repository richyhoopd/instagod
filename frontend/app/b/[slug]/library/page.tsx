"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Images, RefreshCw, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EstadoBadge } from "@/components/estado-badge";
import { QueueDrawer } from "../calendar/_components/queue-drawer";
import { primeraImagen, contarImagenes } from "@/lib/imagenes";
import { formatearFecha } from "@/lib/fecha";
import { ESTADOS, ESTADO_LABELS, type Estado } from "@/lib/estados";
import { useQueue } from "@/hooks/use-queue";

export default function LibraryPage() {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  const [estadoFiltro, setEstadoFiltro] = useState<Estado | "todos">("todos");
  const [busqueda, setBusqueda] = useState("");
  const [openQid, setOpenQid] = useState<number | null>(null);

  const queueQuery = useQueue(slug, {
    estado: estadoFiltro === "todos" ? undefined : estadoFiltro,
  });

  const items = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    return (queueQuery.data ?? [])
      .filter((i) => i.tipo === "slideshow")
      .filter(
        (i) =>
          !q ||
          (i.tema_semilla ?? "").toLowerCase().includes(q) ||
          (i.caption ?? "").toLowerCase().includes(q)
      )
      .sort((a, b) => b.id - a.id);
  }, [queueQuery.data, busqueda]);

  function reusarTema(tema: string) {
    router.push(`/b/${slug}/create?tema=${encodeURIComponent(tema)}`);
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Biblioteca</h1>

      <div className="flex flex-wrap gap-3">
        <div className="relative min-w-48 flex-1">
          <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar por tema o caption..."
            className="pl-8"
          />
        </div>
        <Select
          value={estadoFiltro}
          onValueChange={(v) => setEstadoFiltro(v as Estado | "todos")}
        >
          <SelectTrigger className="w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos los estados</SelectItem>
            {ESTADOS.map((e) => (
              <SelectItem key={e} value={e}>
                {ESTADO_LABELS[e]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {queueQuery.isLoading && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-64 w-full" />
          ))}
        </div>
      )}

      {!queueQuery.isLoading && items.length === 0 && (
        <p className="py-12 text-center text-sm text-muted-foreground">
          No hay carruseles que coincidan con el filtro.
        </p>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((item) => {
          const thumb = primeraImagen(item.imagen_url);
          const n = contarImagenes(item.imagen_url);
          return (
            <div key={item.id} className="flex flex-col overflow-hidden rounded-lg border bg-card">
              <button
                type="button"
                onClick={() => setOpenQid(item.id)}
                className="relative block aspect-[4/5] w-full overflow-hidden bg-muted text-left"
              >
                {thumb ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={thumb} alt="" className="size-full object-cover" />
                ) : (
                  <div className="flex size-full items-center justify-center text-sm text-muted-foreground">
                    Sin imagen
                  </div>
                )}
                {n > 1 && (
                  <span className="absolute right-2 bottom-2 flex items-center gap-1 rounded-full bg-black/60 px-2 py-0.5 text-[10px] text-white">
                    <Images className="size-3" />
                    {n}
                  </span>
                )}
                <div className="absolute top-2 left-2">
                  <EstadoBadge estado={item.estado} />
                </div>
              </button>
              <div className="flex flex-1 flex-col gap-2 p-3">
                <p className="line-clamp-2 text-sm font-medium">
                  {item.tema_semilla || item.caption || "(sin tema)"}
                </p>
                {item.scheduled_datetime && (
                  <p className="text-xs text-muted-foreground">
                    {formatearFecha(item.scheduled_datetime)}
                  </p>
                )}
                <div className="mt-auto flex justify-end">
                  {item.tema_semilla && (
                    <Button size="sm" variant="outline" onClick={() => reusarTema(item.tema_semilla!)}>
                      <RefreshCw className="size-3.5" />
                      Reusar tema
                    </Button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <QueueDrawer slug={slug} qid={openQid} onOpenChange={(open) => !open && setOpenQid(null)} />
    </div>
  );
}
