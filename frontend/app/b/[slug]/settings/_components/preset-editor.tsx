"use client";

import { useState } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { colorSwatch } from "@/lib/estilos";
import { ApiError } from "@/lib/api";
import {
  useGuardarPreset,
  useBorrarPreset,
  usePreviewPreset,
  type Preset,
} from "@/hooks/use-presets";
import { useJob } from "@/hooks/use-job";

function limpiar(preset: Preset): Record<string, unknown> {
  const resto = { ...preset };
  delete resto.propio;
  return resto;
}

// Se remonta (key = cacheKey) cada vez que hay un preview nuevo, así el
// estado de error se reinicia solo sin necesitar un efecto para "resetear".
function PreviewImage({ src, alt }: { src: string; alt: string }) {
  const [error, setError] = useState(false);
  if (error) {
    return <p className="text-xs text-muted-foreground">Sin preview disponible todavía.</p>;
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} className="w-full" onError={() => setError(true)} />
  );
}

export function PresetEditor({
  slug,
  nombreInicial,
  preset,
  esNuevo,
  puedeEditar,
  onGuardado,
  onCancelar,
}: {
  slug: string;
  nombreInicial: string;
  preset: Preset;
  esNuevo: boolean;
  puedeEditar: boolean;
  onGuardado: () => void;
  onCancelar: () => void;
}) {
  const guardar = useGuardarPreset(slug);
  const borrar = useBorrarPreset(slug);
  const previewMutation = usePreviewPreset(slug);

  const [nombre, setNombre] = useState(nombreInicial);
  const [rawJson, setRawJson] = useState(() => JSON.stringify(limpiar(preset), null, 2));
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);

  const jobQuery = useJob(slug, jobId);
  const jobListo = jobId !== null && jobQuery.data?.estado === "ok";
  const jobFallo = jobId !== null && jobQuery.data?.estado === "error";
  // Clave del <img>: cambia solo cuando termina un job de preview nuevo, así
  // se remonta y reintenta la carga (bypass del cache del navegador).
  const cacheKey = jobListo ? String(jobQuery.data?.finished_at ?? jobId) : "inicial";

  function actualizarCampo(campo: "texto" | "fondo" | "overlay", valor: string) {
    try {
      const actual = JSON.parse(rawJson) as Record<string, unknown>;
      if (valor) actual[campo] = valor;
      else delete actual[campo];
      setRawJson(JSON.stringify(actual, null, 2));
      setJsonError(null);
    } catch {
      // JSON crudo inválido: no se puede sincronizar el campo estructurado.
    }
  }

  let parsed: Record<string, unknown> = {};
  try {
    parsed = JSON.parse(rawJson) as Record<string, unknown>;
  } catch {
    // se refleja en jsonError al intentar guardar
  }

  async function guardarPreset() {
    if (!nombre.trim()) {
      toast.error("Ponle un nombre al preset");
      return;
    }
    let datos: Preset;
    try {
      datos = JSON.parse(rawJson) as Preset;
    } catch {
      setJsonError("JSON inválido");
      return;
    }
    try {
      await guardar.mutateAsync({ nombre: nombre.trim(), datos });
      toast.success("Preset guardado");
      onGuardado();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo guardar el preset");
    }
  }

  async function borrarPreset() {
    try {
      await borrar.mutateAsync(nombreInicial);
      toast.success("Preset borrado");
      onGuardado();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo borrar el preset");
    }
  }

  async function pedirPreview() {
    try {
      const res = await previewMutation.mutateAsync(esNuevo ? nombre.trim() : nombreInicial);
      setJobId(res.job_id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo pedir el preview");
    }
  }

  const generandoPreview = previewMutation.isPending || (jobId !== null && !jobListo && !jobFallo);

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <div className="space-y-2">
        <Label htmlFor="preset-nombre">Nombre</Label>
        <Input
          id="preset-nombre"
          value={nombre}
          disabled={!puedeEditar || !esNuevo}
          onChange={(e) => setNombre(e.target.value)}
        />
      </div>
      <div className="grid grid-cols-3 gap-3">
        {(["texto", "fondo", "overlay"] as const).map((campo) => (
          <div key={campo} className="space-y-1.5">
            <Label className="text-xs capitalize">{campo}</Label>
            <div className="flex items-center gap-1.5">
              <span
                className="size-5 shrink-0 rounded border"
                style={{ backgroundColor: colorSwatch(String(parsed[campo] ?? "")) }}
              />
              <Input
                disabled={!puedeEditar}
                value={typeof parsed[campo] === "string" ? (parsed[campo] as string) : ""}
                onChange={(e) => actualizarCampo(campo, e.target.value)}
              />
            </div>
          </div>
        ))}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="preset-json">JSON crudo</Label>
        <Textarea
          id="preset-json"
          rows={8}
          className="font-mono text-xs"
          disabled={!puedeEditar}
          value={rawJson}
          onChange={(e) => {
            setRawJson(e.target.value);
            setJsonError(null);
          }}
        />
        {jsonError && <p className="text-sm text-destructive">{jsonError}</p>}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {puedeEditar && (
          <Button type="button" onClick={guardarPreset} disabled={guardar.isPending}>
            {guardar.isPending ? "Guardando..." : "Guardar"}
          </Button>
        )}
        {puedeEditar && !esNuevo && (
          <Button type="button" variant="destructive" onClick={borrarPreset} disabled={borrar.isPending}>
            Borrar
          </Button>
        )}
        <Button type="button" variant="outline" onClick={onCancelar}>
          Cerrar
        </Button>
        {!esNuevo && (
          <Button type="button" variant="secondary" onClick={pedirPreview} disabled={generandoPreview}>
            <RefreshCw className={generandoPreview ? "size-4 animate-spin" : "size-4"} />
            {generandoPreview ? "Generando..." : "Preview"}
          </Button>
        )}
      </div>

      {jobFallo && (
        <p className="text-sm text-destructive">
          {jobQuery.data?.log || "Falló la generación del preview."}
        </p>
      )}

      {!esNuevo && (
        <div className="w-40 overflow-hidden rounded-lg border bg-muted p-1">
          <PreviewImage
            key={cacheKey}
            src={`/api/brands/${slug}/files/previews/${nombreInicial}.png?t=${cacheKey}`}
            alt={`Preview de ${nombreInicial}`}
          />
        </div>
      )}
    </div>
  );
}
