"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { Palette, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useCrearDiseno,
  useDisenos,
  useDuplicarDiseno,
  type PlantillaLista,
} from "@/hooks/use-disenos";

type EstadoDiseno = "activa" | "borrador" | "archivada";

const PESTANAS: { value: EstadoDiseno; label: string }[] = [
  { value: "activa", label: "Publicados" },
  { value: "borrador", label: "Borradores" },
  { value: "archivada", label: "Archivados" },
];

const ETIQUETA_ESTADO: Record<EstadoDiseno, string> = {
  activa: "Publicado",
  borrador: "Borrador",
  archivada: "Archivado",
};

/** Diálogo mínimo para arrancar un diseño nuevo: nombre y proporción. */
function NuevoDisenoDialog({ slug }: { slug: string }) {
  const router = useRouter();
  const crear = useCrearDiseno(slug);
  const [abierto, setAbierto] = useState(false);
  const [nombre, setNombre] = useState("");
  const [aspecto, setAspecto] = useState<"4:5" | "9:16">("4:5");

  function enviar() {
    crear.mutate(
      { nombre: nombre.trim(), aspecto },
      {
        onSuccess: (nuevo) => {
          setAbierto(false);
          setNombre("");
          setAspecto("4:5");
          router.push(`/b/${slug}/templates/${nuevo.id}`);
        },
        onError: (e) =>
          toast.error(e instanceof Error ? e.message : "No se pudo crear el diseño"),
      }
    );
  }

  return (
    <Dialog open={abierto} onOpenChange={setAbierto}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="size-4" />
          Nuevo diseño
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nuevo diseño</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="nombre-diseno">Nombre</Label>
            <Input
              id="nombre-diseno"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              placeholder="Ej. Frase del día"
              maxLength={80}
            />
          </div>
          <div className="grid gap-1.5">
            <p className="text-sm font-medium">Proporción</p>
            <div className="flex gap-2">
              <Button
                type="button"
                variant={aspecto === "4:5" ? "default" : "outline"}
                size="sm"
                onClick={() => setAspecto("4:5")}
              >
                Cuadrada alta
              </Button>
              <Button
                type="button"
                variant={aspecto === "9:16" ? "default" : "outline"}
                size="sm"
                onClick={() => setAspecto("9:16")}
              >
                Vertical
              </Button>
            </div>
          </div>
          <Button onClick={enviar} disabled={crear.isPending || nombre.trim().length === 0}>
            {crear.isPending ? "Creando…" : "Crear diseño"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TarjetaDiseno({
  slug,
  diseno,
  duplicando,
  onDuplicar,
}: {
  slug: string;
  diseno: PlantillaLista;
  duplicando: boolean;
  onDuplicar: (id: number) => void;
}) {
  const clases = "flex flex-col overflow-hidden rounded-lg border bg-card";

  const cuerpo = (
    <>
      <div className="relative aspect-[4/5] w-full overflow-hidden bg-muted">
        {/* eslint-disable-next-line @next/next/no-img-element -- PNG servido por la API vía rewrite */}
        <img
          src={`/api/brands/${slug}/templates/${diseno.id}/preview.png?v=${diseno.version_actual}`}
          alt={`Vista previa del diseño ${diseno.nombre}`}
          loading="lazy"
          className="size-full object-cover"
        />
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex items-start justify-between gap-2">
          <p className="line-clamp-2 text-sm font-medium">{diseno.nombre}</p>
          <Badge variant="outline" className="shrink-0 font-normal">
            {ETIQUETA_ESTADO[diseno.estado]}
          </Badge>
        </div>
        {!diseno.editable && (
          <div className="mt-auto flex items-center justify-between gap-2 pt-1">
            <span className="text-xs text-muted-foreground">No editable</span>
            <Button
              size="sm"
              variant="outline"
              disabled={duplicando}
              onClick={(e) => {
                e.preventDefault();
                onDuplicar(diseno.id);
              }}
            >
              {duplicando ? "Duplicando…" : "Duplicar como editable"}
            </Button>
          </div>
        )}
      </div>
    </>
  );

  if (diseno.editable) {
    return (
      <Link href={`templates/${diseno.id}`} className={clases}>
        {cuerpo}
      </Link>
    );
  }

  return <div className={clases}>{cuerpo}</div>;
}

export default function TemplatesPage() {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  const [estado, setEstado] = useState<EstadoDiseno>("activa");
  const disenosQuery = useDisenos(slug, estado);
  const duplicar = useDuplicarDiseno(slug);

  function duplicarComoEditable(id: number) {
    duplicar.mutate(id, {
      onSuccess: (nuevo) => router.push(`/b/${slug}/templates/${nuevo.id}`),
      onError: (e) =>
        toast.error(e instanceof Error ? e.message : "No se pudo duplicar el diseño"),
    });
  }

  const disenos = disenosQuery.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Diseños</h1>
          <p className="text-sm text-muted-foreground">
            Las plantillas visuales con las que se arman los posts de la marca.
          </p>
        </div>
        <NuevoDisenoDialog slug={slug} />
      </div>

      <Tabs value={estado} onValueChange={(v) => setEstado(v as EstadoDiseno)}>
        <TabsList>
          {PESTANAS.map((p) => (
            <TabsTrigger key={p.value} value={p.value}>
              {p.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {disenosQuery.isLoading && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-64 w-full" />
          ))}
        </div>
      )}

      {disenosQuery.isError && (
        <p className="text-sm text-muted-foreground">No se pudieron cargar los diseños.</p>
      )}

      {!disenosQuery.isLoading && !disenosQuery.isError && disenos.length === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-14 text-center">
          <Palette className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Todavía no hay diseños. Crea el primero.</p>
          <NuevoDisenoDialog slug={slug} />
        </div>
      )}

      {!disenosQuery.isLoading && disenos.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {disenos.map((d) => (
            <TarjetaDiseno
              key={d.id}
              slug={slug}
              diseno={d}
              duplicando={duplicar.isPending && duplicar.variables === d.id}
              onDuplicar={duplicarComoEditable}
            />
          ))}
        </div>
      )}
    </div>
  );
}
