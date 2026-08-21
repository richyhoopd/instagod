"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ApiError } from "@/lib/api";
import { useCrearMarca } from "@/hooks/use-brands";

const schema = z.object({
  slug: z
    .string()
    .min(2, "Mínimo 2 caracteres")
    .max(32, "Máximo 32 caracteres")
    .regex(/^[a-z0-9_]+$/, "solo minúsculas, dígitos y guion bajo"),
  nombre: z.string().min(1, "Requerido").max(80),
  ig_handle: z.string().min(1, "Requerido").max(60),
  ciudad: z.string().max(80).optional().or(z.literal("")),
  color_marca: z
    .string()
    .regex(/^#[0-9a-fA-F]{6}$/, "color hex #RRGGBB")
    .optional()
    .or(z.literal("")),
});

type FormValues = z.infer<typeof schema>;

// "La Escena GDL" → "la_escena_gdl": el identificador se arma solo a partir
// del nombre para no pedirle un "slug" a quien no sabe qué es eso.
function slugify(nombre: string): string {
  return nombre
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 32);
}

export function NuevaMarcaDialog() {
  const [open, setOpen] = useState(false);
  const [slugTocado, setSlugTocado] = useState(false);
  const crear = useCrearMarca();

  const {
    register,
    handleSubmit,
    reset,
    setError,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { slug: "", nombre: "", ig_handle: "", ciudad: "", color_marca: "#1b5e3f" },
  });

  async function onSubmit(values: FormValues) {
    try {
      const marca = await crear.mutateAsync({
        slug: values.slug,
        nombre: values.nombre,
        ig_handle: values.ig_handle,
        ciudad: values.ciudad || undefined,
        color_marca: values.color_marca || undefined,
      });
      toast.success(`Marca ${marca.nombre} creada`);
      reset();
      setOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.campo && err.campo in values) {
        setError(err.campo as keyof FormValues, { message: err.detalle });
      } else {
        const detalle = err instanceof ApiError ? err.detalle : "No se pudo crear la marca";
        toast.error(detalle);
      }
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) {
          reset();
          setSlugTocado(false);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <Plus />
          Nueva marca
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Nueva marca</DialogTitle>
          <DialogDescription>Da de alta una cuenta nueva en el portal.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="nombre">Nombre de la marca</Label>
            <Input
              id="nombre"
              placeholder="La Escena GDL"
              {...register("nombre", {
                onChange: (e) => {
                  if (!slugTocado) setValue("slug", slugify(e.target.value));
                },
              })}
            />
            {errors.nombre && <p className="text-sm text-destructive">{errors.nombre.message}</p>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="ig_handle">Usuario de Instagram</Label>
            <Input id="ig_handle" placeholder="gdlscene" {...register("ig_handle")} />
            {errors.ig_handle && (
              <p className="text-sm text-destructive">{errors.ig_handle.message}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="slug" className="text-muted-foreground">
              Identificador interno
            </Label>
            <Input
              id="slug"
              placeholder="se_genera_solo"
              {...register("slug", { onChange: () => setSlugTocado(true) })}
            />
            <p className="text-xs text-muted-foreground">
              Se genera solo a partir del nombre y no se puede cambiar después.
            </p>
            {errors.slug && <p className="text-sm text-destructive">{errors.slug.message}</p>}
          </div>
          <div className="grid grid-cols-[1fr_auto] gap-4">
            <div className="space-y-2">
              <Label htmlFor="ciudad">Ciudad</Label>
              <Input id="ciudad" placeholder="Guadalajara" {...register("ciudad")} />
              {errors.ciudad && (
                <p className="text-sm text-destructive">{errors.ciudad.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="color_marca">Color</Label>
              <Input
                id="color_marca"
                type="color"
                className="h-8 w-14 px-1"
                {...register("color_marca")}
              />
            </div>
          </div>
          {errors.color_marca && (
            <p className="text-sm text-destructive">{errors.color_marca.message}</p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Creando..." : "Crear marca"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
