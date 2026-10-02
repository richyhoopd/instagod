"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import {
  useGuardarVideoPreset,
  useQuitarPersonaje,
  useSubirPersonaje,
  useVideoConfig,
  type VideoConfig,
  type VideoPresetIn,
} from "@/hooks/use-video-preset";

const FONDO_LABEL: Record<string, string> = {
  mosaico: "Mosaico",
  cara_gigante: "Cara gigante",
  deep_fried: "Deep fried",
  espejo: "Espejo",
  duotono: "Duotono",
  enjambre: "Enjambre",
  invertido: "Invertido",
};

// es-MX-JorgeNeural → "Jorge (es-MX)"
function vozLabel(voz: string): string {
  const m = voz.match(/^([a-z]{2}-[A-Z]{2})-(.+)Neural$/);
  return m ? `${m[2]} (${m[1]})` : voz;
}

export function TabVideo({ slug, puedeEditar }: { slug: string; puedeEditar: boolean }) {
  const { data, isLoading } = useVideoConfig(slug);
  if (isLoading || !data) return <Skeleton className="h-96 w-full max-w-xl" />;
  // key: al guardar, el formulario se reinicia con lo que devolvió el backend.
  return (
    <FormVideo
      key={JSON.stringify(data.preset)}
      slug={slug}
      config={data}
      puedeEditar={puedeEditar}
    />
  );
}

function FormVideo({
  slug,
  config,
  puedeEditar,
}: {
  slug: string;
  config: VideoConfig;
  puedeEditar: boolean;
}) {
  const p = config.preset;
  const [form, setForm] = useState<Required<VideoPresetIn>>({
    voz: p.voz,
    cta_hablado: p.cta_hablado,
    cta_texto: p.cta_texto,
    cta_marca: p.cta_marca,
    etiqueta_tarjeta: p.etiqueta_tarjeta,
    autor_tarjeta: p.autor_tarjeta,
    color_acento: p.color_acento,
    color_fondo: p.color_fondo,
    fondos: p.fondos,
    palabras_subtitulo: p.palabras_subtitulo,
    palabras_min: p.palabras_min,
    palabras_max: p.palabras_max,
    max_duracion_s: p.max_duracion_s,
  });
  const guardar = useGuardarVideoPreset(slug);
  const subir = useSubirPersonaje(slug);
  const quitar = useQuitarPersonaje(slug);
  const inputRef = useRef<HTMLInputElement>(null);
  // Cambia tras cada subida para que el navegador no muestre el PNG viejo.
  const [versionImg, setVersionImg] = useState(() => Date.now());

  function set<K extends keyof VideoPresetIn>(campo: K, valor: Required<VideoPresetIn>[K]) {
    setForm((f) => ({ ...f, [campo]: valor }));
  }

  function toggleFondo(fondo: string) {
    set(
      "fondos",
      form.fondos.includes(fondo) ? form.fondos.filter((f) => f !== fondo) : [...form.fondos, fondo]
    );
  }

  async function onGuardar(e: React.FormEvent) {
    e.preventDefault();
    try {
      await guardar.mutateAsync(form);
      toast.success("Preset de video guardado");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo guardar");
    }
  }

  async function onPersonaje(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    try {
      await subir.mutateAsync(file);
      setVersionImg(Date.now());
      toast.success("Personaje actualizado");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo subir el personaje");
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function onQuitarPersonaje() {
    try {
      await quitar.mutateAsync();
      toast.success("Personaje quitado");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo quitar");
    }
  }

  const rangoInvalido = form.palabras_min >= form.palabras_max;

  return (
    <form onSubmit={onGuardar} className="max-w-xl space-y-6">
      {!config.configurado && (
        <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          Esta marca aún no tiene preset de video: los reels salen con estos valores por defecto.
          Guárdalo para fijarlos.
        </p>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-medium">Personaje</h2>
        <div className="flex items-center gap-4">
          <div className="flex size-24 items-center justify-center overflow-hidden rounded-lg border bg-[repeating-conic-gradient(var(--muted)_0_25%,transparent_0_50%)] bg-size-[16px_16px]">
            {config.tiene_personaje ? (
              // eslint-disable-next-line @next/next/no-img-element -- PNG servido por la API con auth de cookie
              <img
                src={`/api/brands/${slug}/files/personaje?v=${versionImg}`}
                alt="Personaje de la marca"
                className="max-h-full max-w-full object-contain"
              />
            ) : (
              <span className="px-2 text-center text-xs text-muted-foreground">Sin personaje</span>
            )}
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              PNG con transparencia, máximo 5 MB. Es el narrador que rebota abajo. Sin personaje
              el reel se genera igual, sin narrador y con fondos de color plano.
            </p>
            {puedeEditar && (
              <div className="flex gap-2">
                <input
                  ref={inputRef}
                  type="file"
                  accept="image/png"
                  className="hidden"
                  onChange={(e) => onPersonaje(e.target.files)}
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => inputRef.current?.click()}
                  disabled={subir.isPending}
                >
                  <Upload className="size-4" />
                  {subir.isPending ? "Subiendo..." : "Subir personaje"}
                </Button>
                {config.tiene_personaje && (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={onQuitarPersonaje}
                    disabled={quitar.isPending}
                  >
                    <Trash2 className="size-4" />
                    Quitar
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium">Voz</h2>
        <Select value={form.voz} onValueChange={(v) => set("voz", v)} disabled={!puedeEditar}>
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {config.voces.map((v) => (
              <SelectItem key={v} value={v}>
                {vozLabel(v)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium">CTA</h2>
        <div className="space-y-2">
          <Label htmlFor="cta_hablado">Lo que dice la voz al final</Label>
          <Input
            id="cta_hablado"
            value={form.cta_hablado}
            maxLength={300}
            disabled={!puedeEditar}
            onChange={(e) => set("cta_hablado", e.target.value)}
            placeholder="p. ej. Síguenos para más historias"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="cta_texto">Texto en pantalla</Label>
            <Input
              id="cta_texto"
              value={form.cta_texto}
              maxLength={120}
              disabled={!puedeEditar}
              onChange={(e) => set("cta_texto", e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cta_marca">Cuenta</Label>
            <Input
              id="cta_marca"
              value={form.cta_marca}
              maxLength={60}
              disabled={!puedeEditar}
              onChange={(e) => set("cta_marca", e.target.value)}
              placeholder="@marca"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="etiqueta_tarjeta">Etiqueta de la tarjeta</Label>
            <Input
              id="etiqueta_tarjeta"
              value={form.etiqueta_tarjeta}
              maxLength={60}
              disabled={!puedeEditar}
              onChange={(e) => set("etiqueta_tarjeta", e.target.value)}
              placeholder="r/confesiones"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="autor_tarjeta">Autor de la tarjeta</Label>
            <Input
              id="autor_tarjeta"
              value={form.autor_tarjeta}
              maxLength={60}
              disabled={!puedeEditar}
              onChange={(e) => set("autor_tarjeta", e.target.value)}
            />
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium">Colores</h2>
        <div className="grid grid-cols-2 gap-4">
          {(["color_acento", "color_fondo"] as const).map((campo) => (
            <div key={campo} className="space-y-2">
              <Label htmlFor={campo}>{campo === "color_acento" ? "Acento" : "Fondo"}</Label>
              <div className="flex gap-2">
                <input
                  type="color"
                  aria-label={`Elegir ${campo === "color_acento" ? "acento" : "fondo"}`}
                  value={/^#[0-9a-fA-F]{6}$/.test(form[campo]) ? form[campo] : "#000000"}
                  disabled={!puedeEditar}
                  onChange={(e) => set(campo, e.target.value.toUpperCase())}
                  className="h-9 w-12 cursor-pointer rounded-md border bg-transparent"
                />
                <Input
                  id={campo}
                  value={form[campo]}
                  maxLength={7}
                  disabled={!puedeEditar}
                  onChange={(e) => set(campo, e.target.value)}
                />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium">Fondos</h2>
        <div className="flex flex-wrap gap-2">
          {config.fondos.map((f) => {
            const activo = form.fondos.includes(f);
            return (
              <button
                key={f}
                type="button"
                disabled={!puedeEditar}
                aria-pressed={activo}
                onClick={() => toggleFondo(f)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs transition-colors disabled:opacity-60",
                  activo ? "border-(--brand) bg-(--brand)/10 text-(--brand)" : "hover:bg-muted"
                )}
              >
                {FONDO_LABEL[f] ?? f}
              </button>
            );
          })}
        </div>
        {form.fondos.length === 0 && (
          <p className="text-sm text-destructive">Elige al menos un fondo.</p>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium">Guion y subtítulos</h2>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="palabras_subtitulo">Palabras por subtítulo</Label>
            <Input
              id="palabras_subtitulo"
              type="number"
              min={1}
              max={6}
              value={form.palabras_subtitulo}
              disabled={!puedeEditar}
              onChange={(e) => set("palabras_subtitulo", Number(e.target.value))}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="max_duracion_s">Duración máxima (s)</Label>
            <Input
              id="max_duracion_s"
              type="number"
              min={10}
              max={180}
              value={form.max_duracion_s}
              disabled={!puedeEditar}
              onChange={(e) => set("max_duracion_s", Number(e.target.value))}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="palabras_min">Guion: mínimo de palabras</Label>
            <Input
              id="palabras_min"
              type="number"
              min={20}
              max={400}
              value={form.palabras_min}
              disabled={!puedeEditar}
              onChange={(e) => set("palabras_min", Number(e.target.value))}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="palabras_max">Guion: máximo de palabras</Label>
            <Input
              id="palabras_max"
              type="number"
              min={20}
              max={400}
              value={form.palabras_max}
              disabled={!puedeEditar}
              onChange={(e) => set("palabras_max", Number(e.target.value))}
            />
          </div>
        </div>
        {rangoInvalido && (
          <p className="text-sm text-destructive">El mínimo debe ser menor que el máximo.</p>
        )}
        <p className="text-xs text-muted-foreground">
          A la velocidad de voz actual, 170 palabras rondan los 65 s (comentario del motor en
          src/video_model.py). Si el guion pasa de la duración máxima, el reel falla.
        </p>
      </section>

      {puedeEditar && (
        <Button
          type="submit"
          disabled={guardar.isPending || rangoInvalido || form.fondos.length === 0}
        >
          {guardar.isPending ? "Guardando..." : "Guardar preset de video"}
        </Button>
      )}
    </form>
  );
}
