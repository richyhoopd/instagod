"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useJob } from "@/hooks/use-job";
import { ultimaLinea } from "@/lib/log";
import {
  type CuentaIG,
  type EstadoIG,
  invalidarCuentasIG,
  useCuentasIG,
  useFijarCuentaIG,
  useImportarSeguidos,
  useIngerirIG,
} from "@/hooks/use-ig-seguidos";

function Avatar({ c }: { c: CuentaIG }) {
  const [roto, setRoto] = useState(false);
  const iniciales = (c.nombre || c.ig_handle).slice(0, 2).toUpperCase();
  if (!c.avatar_url || roto) {
    return (
      <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">
        {iniciales}
      </div>
    );
  }
  // URL firmada del CDN de IG: puede expirar o negarse al hotlink; cae a iniciales.
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={c.avatar_url}
      alt=""
      referrerPolicy="no-referrer"
      onError={() => setRoto(true)}
      className="size-10 shrink-0 rounded-full object-cover"
    />
  );
}

function Fila({ c, puedeEditar, onEstado, ocupado }: {
  c: CuentaIG; puedeEditar: boolean; ocupado: boolean;
  onEstado: (handle: string, estado: EstadoIG) => void;
}) {
  return (
    <li className="flex items-start gap-3 py-2">
      <Avatar c={c} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <a href={`https://www.instagram.com/${c.ig_handle}/`} target="_blank" rel="noreferrer"
             className="truncate text-sm font-medium hover:underline">@{c.ig_handle}</a>
          {c.privada ? <Badge variant="outline">privada</Badge> : null}
          <Badge variant={c.estado === "activa" ? "default" : "secondary"}>{c.estado}</Badge>
        </div>
        {c.nombre && c.nombre !== c.ig_handle ? (
          <p className="truncate text-xs text-muted-foreground">{c.nombre}</p>
        ) : null}
        {c.bio ? <p className="line-clamp-2 text-xs text-muted-foreground">{c.bio}</p> : null}
        {c.notas ? <p className="text-xs text-amber-600">{c.notas}</p> : null}
      </div>
      {puedeEditar ? (
        <div className="flex shrink-0 gap-1">
          {c.estado !== "activa" ? (
            <Button size="sm" variant="outline" disabled={ocupado}
                    onClick={() => onEstado(c.ig_handle, "activa")}>Aprobar</Button>
          ) : null}
          {c.estado !== "descartada" ? (
            <Button size="sm" variant="ghost" disabled={ocupado}
                    onClick={() => onEstado(c.ig_handle, "descartada")}>Descartar</Button>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export function IgSeguidosPanel({ slug, puedeEditar }: { slug: string; puedeEditar: boolean }) {
  const qc = useQueryClient();
  const cuentas = useCuentasIG(slug);
  const fijar = useFijarCuentaIG(slug);
  const importar = useImportarSeguidos(slug);
  const ingerir = useIngerirIG(slug);
  const [semilla, setSemilla] = useState("");
  const [manual, setManual] = useState("");
  const [verDescartadas, setVerDescartadas] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const job = useJob(slug, jobId);

  // Sin setState en el efecto: el job terminado se deriva de su estado y el
  // aviso se da una sola vez por job_id.
  const estadoJob = job.data?.estado;
  const avisado = useRef<number | null>(null);
  useEffect(() => {
    if (jobId === null || !estadoJob || estadoJob === "cola" || estadoJob === "corriendo") return;
    if (avisado.current === jobId) return;
    avisado.current = jobId;
    if (estadoJob === "ok") toast.success("Listo");
    else if (estadoJob === "cancelado") toast.info("Job cancelado");
    else toast.error(ultimaLinea(job.data?.log) || "El job falló");
    invalidarCuentasIG(qc, slug);
  }, [jobId, estadoJob, job.data?.log, qc, slug]);

  // Bloquea importar/ingerir mientras el job esté en cola o corriendo; un error
  // de lectura del job (404, red) no deja los botones bloqueados para siempre.
  const corriendo =
    jobId !== null && !job.isError && (!estadoJob || estadoJob === "cola" || estadoJob === "corriendo");
  const lista = (cuentas.data ?? []).filter((c) => verDescartadas || c.estado !== "descartada");
  const activas = (cuentas.data ?? []).filter((c) => c.estado === "activa").length;

  const onEstado = (ig_handle: string, estado: EstadoIG) =>
    fijar.mutate({ ig_handle, estado }, { onError: (e) => toast.error(e.detalle ?? e.message) });

  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold">Instagram (seguidos)</h3>
        <p className="text-xs text-muted-foreground">
          Importa a quién sigue una cuenta, aprueba las que sirven y baja sus fotos y reels a la
          biblioteca. Contenido de terceros: revisa el permiso antes de publicarlo.
        </p>
      </div>

      {puedeEditar ? (
        <div className="flex flex-wrap gap-2">
          <Input value={semilla} onChange={(e) => setSemilla(e.target.value)}
                 placeholder="@cuenta semilla" className="w-48" />
          <Button size="sm" disabled={!semilla.trim() || corriendo || importar.isPending}
                  onClick={() => importar.mutate({ semilla }, {
                    onSuccess: (r) => { setJobId(r.job_id); setSemilla(""); },
                    onError: (e) => toast.error(e.detalle ?? e.message),
                  })}>
            Importar seguidos
          </Button>
          <Button size="sm" variant="secondary" disabled={!activas || corriendo || ingerir.isPending}
                  onClick={() => ingerir.mutate({}, {
                    onSuccess: (r) => setJobId(r.job_id),
                    onError: (e) => toast.error(e.detalle ?? e.message),
                  })}>
            Bajar fotos de {activas} activas
          </Button>
        </div>
      ) : null}

      {corriendo ? (
        <p className="text-xs text-muted-foreground">
          {job.data?.estado === "cola" ? "En cola (otra marca puede estar usando Instagram)…" : null}
          {job.data?.estado === "corriendo" ? `${job.data.progreso ?? 0}% · ${ultimaLinea(job.data.log)}` : null}
        </p>
      ) : null}

      {cuentas.isLoading ? <Skeleton className="h-24 w-full" /> : null}
      {cuentas.error ? <p className="text-xs text-destructive">{cuentas.error.detalle}</p> : null}

      <ul className="divide-y">
        {lista.map((c) => (
          <Fila key={c.id} c={c} puedeEditar={puedeEditar} onEstado={onEstado} ocupado={fijar.isPending} />
        ))}
      </ul>
      {cuentas.data && lista.length === 0 ? (
        <p className="text-xs text-muted-foreground">Sin cuentas. Importa desde una semilla o agrega una.</p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {puedeEditar ? (
          <>
            <Input value={manual} onChange={(e) => setManual(e.target.value)}
                   placeholder="@agregar a mano" className="w-48" />
            <Button size="sm" variant="outline" disabled={!manual.trim() || fijar.isPending}
                    onClick={() => fijar.mutate({ ig_handle: manual, estado: "activa" }, {
                      onSuccess: () => setManual(""),
                      onError: (e) => toast.error(e.detalle ?? e.message),
                    })}>
              Agregar
            </Button>
          </>
        ) : null}
        <Button size="sm" variant="ghost" onClick={() => setVerDescartadas((v) => !v)}>
          {verDescartadas ? "Ocultar descartadas" : "Ver descartadas"}
        </Button>
      </div>
    </section>
  );
}
