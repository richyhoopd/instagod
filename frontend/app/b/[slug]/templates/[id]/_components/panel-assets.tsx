"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  type TipoAsset,
  useAssets,
  useBuscarAssets,
  useBuscarIaAssets,
  useDescartarAsset,
  useImportarAsset,
  useRecorteAsset,
  useSubirAsset,
} from "@/hooks/use-assets";
import { resultadoDeJob } from "@/hooks/use-disenos";
import { type Job, useJob } from "@/hooks/use-job";
import { ApiError } from "@/lib/api";
import { type Asset, type Candidata, capaDesdeAsset, urlVisible } from "@/lib/assets";
import { useEditor } from "@/stores/editor";

const ES_VIDEO = /\.(mp4|webm)(\?|$)/i;

// 413 cae en el mensaje del backend o del proxy (Caddy, sin cuerpo JSON): se
// dice el tope en claro. 502 trae un `detalle` saneado del origen.
function mensajeError(e: unknown, accion: string): string {
  if (e instanceof ApiError) {
    if (e.status === 413) return "El archivo es demasiado grande (máximo 15 MB en fotos y 100 MB en video).";
    if (e.status === 502) return `${accion}: el origen falló (${e.detalle}).`;
    if (e.status === 429) return e.detalle;   // tope diario de IA: el backend lo explica en español
    if (e.status === 403) return "Tu rol no permite administrar assets.";
    return e.detalle;
  }
  return `${accion}.`;
}

function Miniatura({ src, tipo, alt }: { src: string; tipo: TipoAsset; alt: string }) {
  return tipo === "video" && ES_VIDEO.test(src) ? (
    <video src={src} muted loop playsInline preload="metadata" className="h-full w-full object-cover" />
  ) : (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} loading="lazy" className="h-full w-full object-cover" />
  );
}

// Sigue el job de recorte y avisa una sola vez cuando termina (ok, error o
// cancelado). Vive aparte para que el estado del padre se limpie por callback.
function SeguimientoRecorte({ slug, jid, onFin }: {
  slug: string;
  jid: number;
  onFin: (job: Job | null) => void;
}) {
  const job = useJob(slug, jid);
  const avisado = useRef(false);
  useEffect(() => {
    if (job.isError && !avisado.current) {
      avisado.current = true;
      onFin(null);
      return;
    }
    if (!job.data || avisado.current) return;
    if (job.data.estado === "ok" || job.data.estado === "error" || job.data.estado === "cancelado") {
      avisado.current = true;
      onFin(job.data);
    }
  }, [job.data, job.isError, onFin]);
  return <p className="mt-2 text-xs text-muted-foreground">Quitando el fondo…</p>;
}

export function PanelAssets({ slug, puedeEditar }: { slug: string; puedeEditar: boolean }) {
  const escena = useEditor((s) => s.escena);
  const agregarCapa = useEditor((s) => s.agregarCapa);
  const [tipo, setTipo] = useState<TipoAsset>("imagen");
  const [q, setQ] = useState("");
  const [buscado, setBuscado] = useState("");
  const [conIa, setConIa] = useState(false);
  const [recorteJob, setRecorteJob] = useState<{ jid: number; asset: Asset } | null>(null);
  const archivoRef = useRef<HTMLInputElement>(null);

  const qc = useQueryClient();
  const busquedaGratis = useBuscarAssets(slug, buscado, tipo, puedeEditar && !conIa);
  const busquedaIa = useBuscarIaAssets(slug);
  const busqueda = conIa ? busquedaIa : busquedaGratis;
  const biblioteca = useAssets(slug, tipo, puedeEditar);
  const importar = useImportarAsset(slug);
  const subir = useSubirAsset(slug);
  const descartar = useDescartarAsset(slug);
  const recortar = useRecorteAsset(slug);

  if (!puedeEditar) {
    return (
      <p className="p-3 text-xs text-muted-foreground">
        Administrar assets requiere rol manager o superior.
      </p>
    );
  }

  function terminarRecorte(job: Job | null) {
    const origen = recorteJob?.asset;
    setRecorteJob(null);
    if (!job) {
      toast.error("Se perdió el seguimiento del recorte. Revisa la biblioteca en un momento.");
      return;
    }
    if (job.estado !== "ok") {
      toast.error("No se pudo quitar el fondo.");
      return;
    }
    const r = resultadoDeJob<{ asset_id: number; recorte_archivo: string; src: string }>(job);
    if (!r || !origen || !escena) {
      toast.error("No se pudo leer el resultado del recorte.");
      return;
    }
    void qc.invalidateQueries({ queryKey: ["assets", slug] });
    agregarCapa(
      capaDesdeAsset({ ...origen, recorte_archivo: r.recorte_archivo }, escena, { recorteSrc: r.src }),
    );
    toast.success("Fondo quitado");
  }

  function usar(asset: Asset) {
    if (!escena) return;
    agregarCapa(capaDesdeAsset(asset, escena));
  }

  function usarCandidata(c: Candidata) {
    importar.mutate(
      { ...c, tags: buscado ? [buscado] : [] },
      { onSuccess: usar, onError: (e) => toast.error(mensajeError(e, "No se pudo importar")) },
    );
  }

  const avisos = busqueda.data?.avisos ?? [];
  // Pinterest sigue en el backend pero no se ofrece en la UI.
  const resultados = (busqueda.data?.resultados ?? []).filter((c) => c.proveedor !== "pinterest");
  const hayGiphy = resultados.some((c) => c.proveedor === "giphy");

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <Tabs value={tipo} onValueChange={(v) => { setTipo(v as TipoAsset); setConIa(false); }}>
        <TabsList className="w-full">
          <TabsTrigger value="imagen" className="flex-1">Fotos</TabsTrigger>
          <TabsTrigger value="video" className="flex-1">Video</TabsTrigger>
        </TabsList>
        <TabsContent value={tipo} className="mt-3 space-y-3">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setConIa(false);
              setBuscado(q.trim());
            }}
          >
            <Input value={q} onChange={(e) => setQ(e.target.value)} maxLength={200}
                   placeholder={tipo === "imagen" ? "Buscar fotos…" : "Buscar video…"} />
            <Button type="submit" size="sm">Buscar</Button>
          </form>
          <div className="flex flex-wrap gap-2">
            {tipo === "imagen" && (
              <Button size="sm" variant="outline" disabled={q.trim().length < 2 || busquedaIa.isPending}
                      title="De pago: solo si la marca activó la fuente IA"
                      onClick={() => { setConIa(true); setBuscado(q.trim()); busquedaIa.mutate(q.trim(), {
                        onError: (e) => toast.error(mensajeError(e, "No se pudo generar con IA")),
                      }); }}>
                Generar con IA
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => archivoRef.current?.click()}
                    disabled={subir.isPending}>
              Subir archivo
            </Button>
            <input ref={archivoRef} type="file" hidden
                   accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm"
                   onChange={(e) => {
                     const f = e.target.files?.[0];
                     if (f) {
                       subir.mutate(f, {
                         onSuccess: usar,
                         onError: (err) => toast.error(mensajeError(err, "No se pudo subir")),
                       });
                     }
                     e.target.value = "";
                   }} />
          </div>
          {avisos.length > 0 && (
            <ul className="space-y-1 text-xs text-amber-600">
              {avisos.map((a) => <li key={a}>{a}</li>)}
            </ul>
          )}
          {busqueda.isError && (
            <p className="text-xs text-destructive">{mensajeError(busqueda.error, "No se pudo buscar")}</p>
          )}
        </TabsContent>
      </Tabs>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
        {buscado && (
          <section>
            <h4 className="mb-2 text-xs font-medium text-muted-foreground">Resultados</h4>
            {(conIa ? busquedaIa.isPending : busquedaGratis.isLoading) && <Skeleton className="h-32 w-full" />}
            {busqueda.isSuccess && resultados.length === 0 && (
              <p className="text-xs text-muted-foreground">Sin resultados.</p>
            )}
            <div className="grid grid-cols-2 gap-2">
              {resultados.map((c) => (
                <button key={`${c.proveedor}-${c.id_origen}`} type="button"
                        className="group relative aspect-square overflow-hidden rounded border"
                        disabled={importar.isPending} onClick={() => usarCandidata(c)}
                        title={[c.autor, c.licencia].filter(Boolean).join(" · ")}>
                  <Miniatura src={urlVisible(slug, c.preview_url || c.url)} tipo={c.tipo}
                             alt={c.autor ?? c.proveedor} />
                  <span className="absolute bottom-0 left-0 right-0 truncate bg-black/60 px-1
                                   text-[10px] text-white">
                    {c.proveedor}{c.autor ? ` · ${c.autor}` : ""}
                  </span>
                </button>
              ))}
            </div>
            {hayGiphy && (
              <p className="mt-2 text-right text-[10px] text-muted-foreground">Powered by GIPHY</p>
            )}
          </section>
        )}

        <section>
          <h4 className="mb-2 text-xs font-medium text-muted-foreground">Biblioteca de la marca</h4>
          {biblioteca.isLoading && <Skeleton className="h-32 w-full" />}
          {biblioteca.isError && (
            <p className="text-xs text-destructive">{mensajeError(biblioteca.error, "No se pudo cargar")}</p>
          )}
          <div className="grid grid-cols-2 gap-2">
            {(biblioteca.data ?? []).map((a) => (
              <div key={a.id} className="group relative aspect-square overflow-hidden rounded border">
                <button type="button" className="h-full w-full" onClick={() => usar(a)}>
                  <Miniatura src={urlVisible(slug, a.src)} tipo={a.tipo} alt={a.archivo} />
                </button>
                <div className="absolute right-1 top-1 hidden gap-1 group-focus-within:flex group-hover:flex">
                  {a.tipo === "imagen" && (
                    <Button size="sm" variant="secondary" className="h-6 px-2 text-[10px]"
                            disabled={!!recorteJob || recortar.isPending}
                            onClick={() => recortar.mutate(a.id, {
                              onSuccess: (r) => setRecorteJob({ jid: r.job_id, asset: a }),
                              onError: (e) => toast.error(mensajeError(e, "No se pudo quitar el fondo")),
                            })}>
                      Sin fondo
                    </Button>
                  )}
                  <Button size="sm" variant="secondary" className="h-6 px-2 text-[10px]"
                          disabled={descartar.isPending}
                          onClick={() => descartar.mutate(a.id, {
                            onError: (e) => toast.error(mensajeError(e, "No se pudo quitar")),
                          })}>
                    Quitar
                  </Button>
                </div>
              </div>
            ))}
          </div>
          {!biblioteca.isLoading && (biblioteca.data ?? []).length === 0 && (
            <p className="text-xs text-muted-foreground">La biblioteca está vacía.</p>
          )}
          {recorteJob && (
            <SeguimientoRecorte key={recorteJob.jid} slug={slug} jid={recorteJob.jid}
                                onFin={terminarRecorte} />
          )}
        </section>
      </div>
    </div>
  );
}
