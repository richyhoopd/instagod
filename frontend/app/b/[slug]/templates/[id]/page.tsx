"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Grid3x3, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useBrand } from "@/hooks/use-brands";
import { useDiseno, useFuentes, useStickers } from "@/hooks/use-disenos";
import { conCapa, sinCapa, type Capa, type Layout } from "@/lib/layout";
import { Lienzo } from "./_components/lienzo";

export default function DisenoPage() {
  const { slug, id } = useParams<{ slug: string; id: string }>();
  const disenoId = Number(id);

  const disenoQuery = useDiseno(slug, disenoId);
  const fuentesQuery = useFuentes(slug);
  const stickersQuery = useStickers(slug);
  const marcaQuery = useBrand(slug);

  const [layout, setLayout] = useState<Layout | null>(null);
  const [seleccion, setSeleccion] = useState<string | null>(null);
  const [rejilla, setRejilla] = useState(true);

  // Se siembra una sola vez por diseño: un refetch en segundo plano no puede
  // pisar lo que la persona lleva acomodado.
  const sembrado = useRef<number | null>(null);
  const diseno = disenoQuery.data;
  useEffect(() => {
    if (!diseno?.layout || sembrado.current === diseno.id) return;
    sembrado.current = diseno.id;
    setLayout(diseno.layout);
    setSeleccion(null);
  }, [diseno]);

  const volver = (
    <Link
      href={`/b/${slug}/templates`}
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="size-4" /> Diseños
    </Link>
  );

  if (disenoQuery.isLoading) {
    return (
      <div className="space-y-3">
        {volver}
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-[560px] w-full max-w-[520px]" />
      </div>
    );
  }

  if (disenoQuery.isError || !diseno) {
    // Un diseño de otra marca contesta 404, nunca 403: desde aquí no se puede
    // ni averiguar que existe.
    const noExiste = disenoQuery.error?.status === 404;
    return (
      <div className="space-y-3">
        {volver}
        <p className="text-sm text-muted-foreground">
          {noExiste
            ? "Ese diseño no existe."
            : "No se pudo cargar el diseño. Intenta de nuevo en un momento."}
        </p>
      </div>
    );
  }

  const encabezado = (accion?: React.ReactNode) => (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold">{diseno.nombre}</h1>
        <p className="text-sm text-muted-foreground">
          {diseno.aspecto === "9:16" ? "Vertical" : "Cuadrada alta"}
        </p>
      </div>
      {accion}
    </div>
  );

  // Los diseños viejos se hicieron antes del editor y solo tienen su versión
  // ya armada: no hay piezas que mover, así que no se abre el editor.
  if (!diseno.editable || diseno.layout === null) {
    return (
      <div className="space-y-4">
        {volver}
        {encabezado()}
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-14 text-center">
          <Lock className="size-6 text-muted-foreground" />
          <p className="max-w-md text-sm text-muted-foreground">
            Este diseño se hizo antes del editor, así que no se puede acomodar pieza por
            pieza. Duplícalo desde la lista de diseños y edita la copia.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {volver}
      {encabezado(
        <Button
          variant={rejilla ? "default" : "outline"}
          size="sm"
          onClick={() => setRejilla((v) => !v)}
        >
          <Grid3x3 className="size-4" />
          Cuadrícula
        </Button>
      )}

      {layout && (
        <div className="w-full max-w-[520px]">
          <Lienzo
            layout={layout}
            aspecto={diseno.aspecto}
            seleccion={seleccion}
            slug={slug}
            colorMarca={marcaQuery.data?.color_marca ?? "#000000"}
            fuentes={fuentesQuery.data ?? []}
            stickers={stickersQuery.data ?? []}
            onSeleccionar={setSeleccion}
            onCambiar={(capa: Capa) => setLayout((l) => (l ? conCapa(l, capa) : l))}
            onBorrar={(idCapa: string) => {
              setLayout((l) => (l ? sinCapa(l, idCapa) : l));
              setSeleccion(null);
            }}
            rejilla={rejilla}
          />
        </div>
      )}
    </div>
  );
}
