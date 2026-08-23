"use client";

import { useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ChipInput } from "@/components/chip-input";
import { BrandAvatar } from "@/components/brand-avatar";
import { ApiError } from "@/lib/api";
import { useActualizarMarca, type BrandDetail } from "@/hooks/use-brands";
import { useSubirLogo } from "@/hooks/use-logo";

// Zonas horarias comunes del equipo; nadie tiene por qué saber escribir un
// identificador IANA a mano. Si la marca ya trae otra zona, se agrega tal cual.
const ZONAS: { valor: string; label: string }[] = [
  { valor: "America/Mexico_City", label: "Ciudad de México / Guadalajara (Centro)" },
  { valor: "America/Monterrey", label: "Monterrey" },
  { valor: "America/Cancun", label: "Cancún (Sureste)" },
  { valor: "America/Mazatlan", label: "Mazatlán (Pacífico)" },
  { valor: "America/Hermosillo", label: "Hermosillo (Sonora)" },
  { valor: "America/Tijuana", label: "Tijuana (Noroeste)" },
  { valor: "America/Bogota", label: "Bogotá" },
  { valor: "America/Los_Angeles", label: "Los Ángeles" },
  { valor: "America/New_York", label: "Nueva York" },
  { valor: "Europe/Madrid", label: "Madrid" },
];

function zonasDisponibles(actual: string | null | undefined): { valor: string; label: string }[] {
  if (actual && !ZONAS.some((z) => z.valor === actual)) {
    return [...ZONAS, { valor: actual, label: actual }];
  }
  return ZONAS;
}

function parseHashtags(v: string | null | undefined): string[] {
  if (!v) return [];
  return v
    .split(/[\s,]+/)
    .map((h) => h.trim())
    .filter(Boolean)
    .map((h) => (h.startsWith("#") ? h : `#${h}`));
}

const schema = z.object({
  nombre: z.string().min(1, "Requerido").max(80),
  ig_handle: z.string().min(1, "Requerido").max(60),
  ciudad: z.string().max(80).optional().or(z.literal("")),
  timezone: z.string().max(60).optional().or(z.literal("")),
  color_marca: z
    .string()
    .regex(/^#[0-9a-fA-F]{6}$/, "color hex #RRGGBB")
    .optional()
    .or(z.literal("")),
  descripcion: z.string().max(500).optional().or(z.literal("")),
  sitio_web: z.string().max(200).optional().or(z.literal("")),
});

type FormValues = z.infer<typeof schema>;

export function TabPerfil({
  slug,
  marca,
  puedeEditar,
}: {
  slug: string;
  marca: BrandDetail;
  puedeEditar: boolean;
}) {
  const actualizar = useActualizarMarca(slug);
  const subirLogo = useSubirLogo(slug);
  const logoInputRef = useRef<HTMLInputElement>(null);
  const [hashtags, setHashtags] = useState<string[]>(() => parseHashtags(marca.hashtags_default));
  const [hashtagsDirty, setHashtagsDirty] = useState(false);

  async function onLogo(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    try {
      await subirLogo.mutateAsync(file);
      toast.success("Logo actualizado");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo subir el logo");
    } finally {
      if (logoInputRef.current) logoInputRef.current.value = "";
    }
  }
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      nombre: marca.nombre,
      ig_handle: marca.ig_handle,
      ciudad: marca.ciudad ?? "",
      timezone: marca.timezone ?? "",
      color_marca: marca.color_marca ?? "",
      descripcion: marca.descripcion ?? "",
      sitio_web: marca.sitio_web ?? "",
    },
  });

  async function onSubmit(values: FormValues) {
    try {
      await actualizar.mutateAsync({ ...values, hashtags_default: hashtags.join(" ") });
      toast.success("Perfil actualizado");
      reset(values);
      setHashtagsDirty(false);
    } catch (err) {
      if (err instanceof ApiError && err.campo && err.campo in values) {
        setError(err.campo as keyof FormValues, { message: err.detalle });
      } else {
        toast.error(err instanceof ApiError ? err.detalle : "No se pudo guardar el perfil");
      }
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="max-w-xl space-y-4">
      <div className="flex items-center gap-3">
        <BrandAvatar
          slug={slug}
          nombre={marca.nombre}
          colorMarca={marca.color_marca}
          logoPath={marca.logo_path}
          className="size-14"
        />
        {puedeEditar && (
          <>
            <input
              ref={logoInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => onLogo(e.target.files)}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => logoInputRef.current?.click()}
              disabled={subirLogo.isPending}
            >
              <Upload className="size-4" />
              {subirLogo.isPending ? "Subiendo..." : "Cambiar logo"}
            </Button>
          </>
        )}
      </div>
      <div className="space-y-2">
        <Label htmlFor="nombre">Nombre</Label>
        <Input id="nombre" disabled={!puedeEditar} {...register("nombre")} />
        {errors.nombre && <p className="text-sm text-destructive">{errors.nombre.message}</p>}
      </div>
      <div className="space-y-2">
        <Label htmlFor="ig_handle">Usuario de Instagram</Label>
        <Input id="ig_handle" disabled={!puedeEditar} {...register("ig_handle")} />
        {errors.ig_handle && (
          <p className="text-sm text-destructive">{errors.ig_handle.message}</p>
        )}
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="ciudad">Ciudad</Label>
          <Input id="ciudad" disabled={!puedeEditar} {...register("ciudad")} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="timezone">Zona horaria</Label>
          <select
            id="timezone"
            disabled={!puedeEditar}
            className="border-input bg-transparent dark:bg-input/30 h-9 w-full rounded-md border px-3 text-sm shadow-xs disabled:cursor-not-allowed disabled:opacity-50"
            {...register("timezone")}
          >
            <option value="">Sin definir</option>
            {zonasDisponibles(marca.timezone).map((z) => (
              <option key={z.valor} value={z.valor}>
                {z.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="color_marca">Color de marca</Label>
        <div className="flex items-center gap-2">
          <Input
            id="color_marca"
            type="color"
            className="h-8 w-14 px-1"
            disabled={!puedeEditar}
            {...register("color_marca")}
          />
          <span className="text-sm text-muted-foreground">{marca.color_marca}</span>
        </div>
        {errors.color_marca && (
          <p className="text-sm text-destructive">{errors.color_marca.message}</p>
        )}
      </div>
      <div className="space-y-2">
        <Label htmlFor="sitio_web">Sitio web</Label>
        <Input id="sitio_web" placeholder="https://..." disabled={!puedeEditar} {...register("sitio_web")} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="descripcion">Descripción</Label>
        <Textarea id="descripcion" rows={4} disabled={!puedeEditar} {...register("descripcion")} />
      </div>
      <div className="space-y-2">
        <Label>Hashtags por defecto</Label>
        <ChipInput
          value={hashtags}
          onChange={(v) => {
            setHashtags(v);
            setHashtagsDirty(true);
          }}
          placeholder="#hashtag y Enter"
          disabled={!puedeEditar}
        />
      </div>
      {puedeEditar && (
        <Button type="submit" disabled={isSubmitting || (!isDirty && !hashtagsDirty)}>
          {isSubmitting ? "Guardando..." : "Guardar cambios"}
        </Button>
      )}
    </form>
  );
}
