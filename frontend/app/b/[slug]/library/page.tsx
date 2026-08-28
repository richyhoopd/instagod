"use client";

import { Suspense, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Check, CheckCheck, Images, ListChecks, Plus, RefreshCw, Search, X } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
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
import { QueueDrawer } from "@/components/queue-drawer";
import { primeraImagen, contarImagenes } from "@/lib/imagenes";
import { formatearFecha } from "@/lib/fecha";
import { ESTADOS, ESTADO_LABELS, esEstado, type Estado } from "@/lib/estados";
import { temaLimpio } from "@/lib/formatos";
import { cn } from "@/lib/utils";
import { useAprobar, useQueue, useRechazar } from "@/hooks/use-queue";

function LibraryContent() {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const estadoInicial = searchParams.get("estado");
  const [estadoFiltro, setEstadoFiltro] = useState<Estado | "todos">(
    estadoInicial && esEstado(estadoInicial) ? estadoInicial : "todos"
  );
  const [busqueda, setBusqueda] = useState("");
  const [openQid, setOpenQid] = useState<number | null>(null);
  const [seleccionando, setSeleccionando] = useState(false);
  const [sel, setSel] = useState<Set<number>>(new Set());
  // Progreso del lote en curso: null = no hay lote corriendo.
  const [lote, setLote] = useState<{ accion: "aprobar" | "rechazar"; done: number; total: number } | null>(null);

  const queueQuery = useQueue(slug, {
    estado: estadoFiltro === "todos" ? undefined : estadoFiltro,
  });
  const aprobar = useAprobar(slug);
  const rechazar = useRechazar(slug);

  const items = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    return (queueQuery.data ?? [])
      .filter(
        (i) =>
          !q ||
          (i.tema_semilla ?? "").toLowerCase().includes(q) ||
          (i.caption ?? "").toLowerCase().includes(q)
      )
      .sort((a, b) => b.id - a.id);
  }, [queueQuery.data, busqueda]);

  function reusarTema(tema: string) {
    router.push(`/b/${slug}/create?tema=${encodeURIComponent(temaLimpio(tema) || tema)}`);
  }

  const pendientesVisibles = items.filter((i) => i.estado === "pendiente");

  function entrarSeleccion() {
    // El lote solo aplica a pendientes; fijar el filtro evita seleccionar
    // cosas sobre las que aprobar/rechazar no tiene sentido.
    setEstadoFiltro("pendiente");
    setSeleccionando(true);
    setSel(new Set());
  }

  function salirSeleccion() {
    setSeleccionando(false);
    setSel(new Set());
  }

  function toggleSel(id: number) {
    setSel((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function ejecutarLote(accion: "aprobar" | "rechazar") {
    const ids = [...sel];
    setLote({ accion, done: 0, total: ids.length });
    let ok = 0;
    let fallos = 0;
    // Secuencial a propósito: cada aprobación toma el siguiente horario libre.
    for (const id of ids) {
      try {
        if (accion === "aprobar") await aprobar.mutateAsync(id);
        else await rechazar.mutateAsync(id);
        ok += 1;
      } catch {
        fallos += 1;
      }
      setLote((prev) => (prev ? { ...prev, done: prev.done + 1 } : prev));
    }
    setLote(null);
    salirSeleccion();
    if (fallos === 0) {
      toast.success(
        accion === "aprobar"
          ? `${ok} publicaciones aprobadas y programadas`
          : `${ok} publicaciones rechazadas`
      );
    } else {
      toast.error(`${ok} listas, ${fallos} fallaron. Revisa e intenta de nuevo.`);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Biblioteca</h1>
        <p className="text-sm text-muted-foreground">
          Todo el contenido de la marca. Busca, revisa el detalle o reutiliza un tema.
        </p>
      </div>

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
        {!seleccionando && pendientesVisibles.length > 1 && (
          <Button variant="outline" onClick={entrarSeleccion}>
            <ListChecks className="size-4" />
            Revisar en lote
          </Button>
        )}
      </div>

      {seleccionando && (
        <div className="sticky top-2 z-10 flex flex-wrap items-center gap-2 rounded-lg border bg-background/95 p-2 shadow-sm backdrop-blur">
          {lote ? (
            <p className="px-1 text-sm">
              {lote.accion === "aprobar" ? "Aprobando" : "Rechazando"} {lote.done} de {lote.total}...
            </p>
          ) : (
            <>
              <p className="px-1 text-sm">
                {sel.size === 0
                  ? "Toca las publicaciones que quieras revisar"
                  : `${sel.size} seleccionada${sel.size === 1 ? "" : "s"}`}
              </p>
              <div className="ml-auto flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setSel(new Set(pendientesVisibles.map((i) => i.id)))}
                >
                  <CheckCheck className="size-3.5" />
                  Todas
                </Button>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button size="sm" variant="outline" disabled={sel.size === 0}>
                      <X className="size-3.5 text-destructive" />
                      Rechazar ({sel.size})
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>
                        ¿Rechazar {sel.size} publicaci{sel.size === 1 ? "ón" : "ones"}?
                      </AlertDialogTitle>
                      <AlertDialogDescription>
                        No se publicarán. Quedan en el historial como rechazadas.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancelar</AlertDialogCancel>
                      <AlertDialogAction onClick={() => ejecutarLote("rechazar")}>
                        Rechazar todas
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button size="sm" disabled={sel.size === 0}>
                      <Check className="size-3.5" />
                      Aprobar ({sel.size})
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>
                        ¿Aprobar {sel.size} publicaci{sel.size === 1 ? "ón" : "ones"}?
                      </AlertDialogTitle>
                      <AlertDialogDescription>
                        Cada una tomará el siguiente horario libre y se publicará
                        automáticamente en el Instagram de la marca.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancelar</AlertDialogCancel>
                      <AlertDialogAction onClick={() => ejecutarLote("aprobar")}>
                        Aprobar y programar
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
                <Button size="sm" variant="ghost" onClick={salirSeleccion}>
                  Cancelar
                </Button>
              </div>
            </>
          )}
        </div>
      )}

      {queueQuery.isLoading && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-64 w-full" />
          ))}
        </div>
      )}

      {!queueQuery.isLoading && items.length === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-14 text-center">
          <Images className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            {busqueda || estadoFiltro !== "todos"
              ? "No hay contenido que coincida con la búsqueda o el filtro."
              : "Todavía no hay contenido. Crea tu primer carrusel y aparecerá aquí."}
          </p>
          <Button size="sm" asChild>
            <Link href={`/b/${slug}/create`}>
              <Plus className="size-3.5" />
              Crear carrusel
            </Link>
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((item) => {
          const thumb = primeraImagen(item.imagen_url);
          const n = contarImagenes(item.imagen_url);
          const seleccionada = sel.has(item.id);
          return (
            <div
              key={item.id}
              className={cn(
                "flex flex-col overflow-hidden rounded-lg border bg-card",
                seleccionando && item.estado !== "pendiente" && "opacity-40",
                seleccionada && "ring-2 ring-(--brand)"
              )}
            >
              <button
                type="button"
                onClick={() => {
                  if (seleccionando) {
                    if (item.estado === "pendiente") toggleSel(item.id);
                  } else {
                    setOpenQid(item.id);
                  }
                }}
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
                {seleccionada && (
                  <span className="absolute top-2 right-2 flex size-6 items-center justify-center rounded-full bg-(--brand) text-white">
                    <Check className="size-4" />
                  </span>
                )}
              </button>
              <div className="flex flex-1 flex-col gap-2 p-3">
                <p className="line-clamp-2 text-sm font-medium">
                  {temaLimpio(item.tema_semilla) || item.caption || "Sin tema"}
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

export default function LibraryPage() {
  // useSearchParams exige un límite de Suspense al prerenderizar.
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <LibraryContent />
    </Suspense>
  );
}
