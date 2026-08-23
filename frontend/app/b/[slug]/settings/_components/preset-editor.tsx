"use client";

import { useState } from "react";
import { toast } from "sonner";
import { ChevronDown, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Textarea } from "@/components/ui/textarea";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  ANCLAS,
  ESTILOS_TEXTO,
  FUENTES,
  PALETA_NOMBRES,
  ROL_LABELS,
  TAMANOS,
  colorSwatch,
} from "@/lib/estilos";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  useGuardarPreset,
  useBorrarPreset,
  usePreviewPreset,
  type Preset,
} from "@/hooks/use-presets";
import { useJob } from "@/hooks/use-job";

// Si el preview no termina en este tiempo, algo se atoró (worker caído u
// ocupado): hay que decirlo en vez de dejar el botón girando para siempre.
const PREVIEW_TIMEOUT_MS = 90_000;

type Datos = Record<string, unknown>;
type Rol = Record<string, unknown>;

function limpiar(preset: Preset): Datos {
  // "nombre" y "propio" son metadatos que la API inyecta en el listado, no
  // parte del preset guardable — no van en el body de PUT /presets/{nombre}.
  const resto: Datos = { ...preset };
  delete resto.nombre;
  delete resto.propio;
  return resto;
}

function rolesDe(datos: Datos): Record<string, Rol> {
  const roles = datos.roles;
  if (roles && typeof roles === "object" && !Array.isArray(roles)) {
    return roles as Record<string, Rol>;
  }
  return {};
}

// Se remonta (key = cacheKey) cada vez que hay un preview nuevo, así el
// estado de error se reinicia solo sin necesitar un efecto para "resetear".
function PreviewImage({ src, alt }: { src: string; alt: string }) {
  const [error, setError] = useState(false);
  if (error) {
    return (
      <p className="p-2 text-xs text-muted-foreground">
        Todavía no hay vista previa. Genera una con el botón de arriba.
      </p>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} className="w-full" onError={() => setError(true)} />
  );
}

function SelectorColor({
  label,
  valor,
  disabled,
  onChange,
}: {
  label: string;
  valor: string;
  disabled: boolean;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs">{label}</Label>
      <div className="flex flex-wrap gap-1.5">
        {PALETA_NOMBRES.map((nombre) => (
          <button
            key={nombre}
            type="button"
            disabled={disabled}
            title={nombre}
            aria-label={`${label}: ${nombre}`}
            aria-pressed={valor === nombre}
            onClick={() => onChange(nombre)}
            className={cn(
              "size-7 rounded-full border transition-shadow",
              valor === nombre && "ring-2 ring-(--brand) ring-offset-2 ring-offset-background"
            )}
            style={{ backgroundColor: colorSwatch(nombre) }}
          />
        ))}
      </div>
    </div>
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
  const [datos, setDatos] = useState<Datos>(() => limpiar(preset));
  // Borrador del JSON avanzado; null = sincronizado con `datos`.
  const [jsonDraft, setJsonDraft] = useState<string | null>(null);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [previewVencido, setPreviewVencido] = useState(false);

  const jobQuery = useJob(slug, jobId);
  const jobListo = jobId !== null && jobQuery.data?.estado === "ok";
  const jobFallo = jobId !== null && jobQuery.data?.estado === "error";
  // Clave del <img>: cambia solo cuando termina un job de preview nuevo, así
  // se remonta y reintenta la carga (bypass del cache del navegador).
  const cacheKey = jobListo ? String(jobQuery.data?.finished_at ?? jobId) : "inicial";

  const roles = rolesDe(datos);

  function setCampo(campo: string, valor: unknown) {
    setDatos((prev) => ({ ...prev, [campo]: valor }));
    setJsonDraft(null);
    setJsonError(null);
  }

  function setRol(rol: string, campo: string, valor: string) {
    setDatos((prev) => {
      const rolesPrevios = rolesDe(prev);
      return {
        ...prev,
        roles: { ...rolesPrevios, [rol]: { ...rolesPrevios[rol], [campo]: valor } },
      };
    });
    setJsonDraft(null);
    setJsonError(null);
  }

  function aplicarJson() {
    if (jsonDraft === null) return;
    try {
      const parsed: unknown = JSON.parse(jsonDraft);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setJsonError("Debe ser un objeto JSON.");
        return;
      }
      setDatos(parsed as Datos);
      setJsonDraft(null);
      setJsonError(null);
    } catch {
      setJsonError("El JSON tiene un error de sintaxis; revisa comas y llaves.");
    }
  }

  async function guardarPreset() {
    if (!nombre.trim()) {
      toast.error("Ponle un nombre al estilo");
      return;
    }
    if (jsonDraft !== null) {
      setJsonError("Aplica o descarta los cambios del JSON avanzado antes de guardar.");
      return;
    }
    try {
      await guardar.mutateAsync({ nombre: nombre.trim(), datos });
      toast.success("Estilo guardado");
      onGuardado();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo guardar el estilo");
    }
  }

  async function borrarPreset() {
    try {
      await borrar.mutateAsync(nombreInicial);
      toast.success("Estilo borrado");
      onGuardado();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo borrar el estilo");
    }
  }

  async function pedirPreview() {
    setPreviewVencido(false);
    try {
      const res = await previewMutation.mutateAsync(esNuevo ? nombre.trim() : nombreInicial);
      setJobId(res.job_id);
      window.setTimeout(() => setPreviewVencido(true), PREVIEW_TIMEOUT_MS);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo generar la vista previa");
    }
  }

  const generandoPreview =
    !previewVencido && (previewMutation.isPending || (jobId !== null && !jobListo && !jobFallo));
  const previewAtorado = previewVencido && jobId !== null && !jobListo && !jobFallo;

  return (
    <div className="space-y-5 rounded-lg border p-4">
      <div className="space-y-2">
        <Label htmlFor="preset-nombre">Nombre del estilo</Label>
        <Input
          id="preset-nombre"
          value={nombre}
          disabled={!puedeEditar || !esNuevo}
          onChange={(e) => setNombre(e.target.value)}
          placeholder="p. ej. Clásico de la marca"
        />
      </div>

      <SelectorColor
        label="Color del texto"
        valor={typeof datos.texto === "string" ? datos.texto : ""}
        disabled={!puedeEditar}
        onChange={(v) => setCampo("texto", v)}
      />
      <SelectorColor
        label="Color de fondo"
        valor={typeof datos.fondo === "string" ? datos.fondo : ""}
        disabled={!puedeEditar}
        onChange={(v) => setCampo("fondo", v)}
      />

      <div className="max-w-xs space-y-1.5">
        <Label className="text-xs">Qué tanto se nota el color de fondo sobre la foto</Label>
        <div className="flex items-center gap-3">
          <Slider
            min={0}
            max={1}
            step={0.05}
            disabled={!puedeEditar}
            value={[typeof datos.background_opacity === "number" ? datos.background_opacity : 0.35]}
            onValueChange={([v]) => setCampo("background_opacity", v)}
          />
          <span className="w-10 shrink-0 text-right text-sm tabular-nums">
            {Math.round(
              (typeof datos.background_opacity === "number" ? datos.background_opacity : 0.35) * 100
            )}
            %
          </span>
        </div>
      </div>

      <div className="space-y-3">
        <Label>Tipografía por parte del carrusel</Label>
        {Object.entries(roles).map(([rol, valores]) => (
          <div key={rol} className="space-y-2 rounded-lg border p-3">
            <p className="text-sm font-medium">{ROL_LABELS[rol] ?? rol}</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Fuente</Label>
                <Select
                  disabled={!puedeEditar}
                  value={typeof valores.font === "string" ? valores.font : ""}
                  onValueChange={(v) => setRol(rol, "font", v)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Elegir" />
                  </SelectTrigger>
                  <SelectContent>
                    {FUENTES.map((f) => (
                      <SelectItem key={f} value={f}>
                        {f.replace(/-/g, " ")}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Tamaño</Label>
                <Select
                  disabled={!puedeEditar}
                  value={typeof valores.font_size === "string" ? valores.font_size : ""}
                  onValueChange={(v) => setRol(rol, "font_size", v)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Elegir" />
                  </SelectTrigger>
                  <SelectContent>
                    {TAMANOS.map((t) => (
                      <SelectItem key={t.valor} value={t.valor}>
                        {t.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Estilo del texto</Label>
                <Select
                  disabled={!puedeEditar}
                  value={typeof valores.text_style === "string" ? valores.text_style : ""}
                  onValueChange={(v) => setRol(rol, "text_style", v)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Elegir" />
                  </SelectTrigger>
                  <SelectContent>
                    {ESTILOS_TEXTO.map((e) => (
                      <SelectItem key={e.valor} value={e.valor}>
                        {e.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Posición vertical</Label>
                <Select
                  disabled={!puedeEditar}
                  value={
                    typeof valores.text_vertical_anchor === "string"
                      ? valores.text_vertical_anchor
                      : ""
                  }
                  onValueChange={(v) => setRol(rol, "text_vertical_anchor", v)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Elegir" />
                  </SelectTrigger>
                  <SelectContent>
                    {ANCLAS.map((a) => (
                      <SelectItem key={a.valor} value={a.valor}>
                        {a.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        ))}
      </div>

      <details className="group rounded-lg border">
        <summary className="flex cursor-pointer items-center gap-1.5 p-3 text-sm text-muted-foreground select-none">
          <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
          Avanzado: editar el JSON directamente
        </summary>
        <div className="space-y-2 p-3 pt-0">
          <Textarea
            rows={10}
            className="font-mono text-xs"
            disabled={!puedeEditar}
            value={jsonDraft ?? JSON.stringify(datos, null, 2)}
            onChange={(e) => {
              setJsonDraft(e.target.value);
              setJsonError(null);
            }}
          />
          {jsonError && <p className="text-sm text-destructive">{jsonError}</p>}
          {jsonDraft !== null && (
            <div className="flex gap-2">
              <Button type="button" size="sm" variant="outline" onClick={aplicarJson}>
                Aplicar JSON
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  setJsonDraft(null);
                  setJsonError(null);
                }}
              >
                Descartar cambios
              </Button>
            </div>
          )}
        </div>
      </details>

      <div className="flex flex-wrap items-center gap-2">
        {puedeEditar && (
          <Button type="button" onClick={guardarPreset} disabled={guardar.isPending}>
            {guardar.isPending ? "Guardando..." : "Guardar estilo"}
          </Button>
        )}
        {!esNuevo && (
          <Button type="button" variant="secondary" onClick={pedirPreview} disabled={generandoPreview}>
            <RefreshCw className={generandoPreview ? "size-4 animate-spin" : "size-4"} />
            {generandoPreview ? "Generando vista previa..." : "Generar vista previa"}
          </Button>
        )}
        <Button type="button" variant="outline" onClick={onCancelar}>
          Cerrar
        </Button>
        {puedeEditar && !esNuevo && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                className="ml-auto text-destructive"
                disabled={borrar.isPending}
              >
                Borrar
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>¿Borrar este estilo?</AlertDialogTitle>
                <AlertDialogDescription>
                  Los carruseles nuevos ya no podrán usarlo. Esta acción no se puede deshacer.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancelar</AlertDialogCancel>
                <AlertDialogAction onClick={borrarPreset}>Borrar estilo</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>

      {jobFallo && (
        <p className="text-sm text-destructive">
          {jobQuery.data?.log || "Falló la generación de la vista previa."}
        </p>
      )}
      {previewAtorado && (
        <p className="text-sm text-amber-600 dark:text-amber-400">
          La vista previa está tardando más de lo normal. Puede que el servidor esté ocupado;
          intenta de nuevo en un momento.
        </p>
      )}

      {!esNuevo && (
        <div className="w-full max-w-60 overflow-hidden rounded-lg border bg-muted p-1">
          <PreviewImage
            key={cacheKey}
            src={`/api/brands/${slug}/files/previews/${nombreInicial}.png?t=${cacheKey}`}
            alt={`Vista previa del estilo ${nombreInicial}`}
          />
        </div>
      )}
    </div>
  );
}
