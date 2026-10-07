"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Lock } from "lucide-react";
import { toast } from "sonner";
import { Skeleton } from "@/components/ui/skeleton";
import { useAtajos } from "@/hooks/use-atajos";
import { useAutoguardado } from "@/hooks/use-autoguardado";
import { useBrand } from "@/hooks/use-brands";
import { useActivarDiseno, useDiseno, useGuardarDiseno } from "@/hooks/use-disenos";
import { useEditor } from "@/stores/editor";
import { BarraSuperior } from "./_components/barra-superior";
import { DialogoVersiones } from "./_components/dialogo-versiones";
import { Lienzo } from "./_components/lienzo";
import { PanelCapas } from "./_components/panel-capas";
import { PanelLateral } from "./_components/panel-lateral";
import { PanelPropiedades } from "./_components/panel-propiedades";
import { VistaPrevia } from "./_components/vista-previa";

export default function DisenoPage() {
  const { slug, id } = useParams<{ slug: string; id: string }>();
  const disenoId = Number(id);

  const disenoQuery = useDiseno(slug, disenoId);
  const marcaQuery = useBrand(slug);
  const guardarMut = useGuardarDiseno(slug, disenoId);
  const activarMut = useActivarDiseno(slug, disenoId);
  const listo = useEditor((s) => s.escena !== null);
  const colorMarca = marcaQuery.data?.color_marca ?? "#000000";

  // Se siembra una sola vez por diseño: un refetch en segundo plano no puede
  // pisar lo que la persona lleva acomodado.
  const sembrado = useRef<number | null>(null);
  const diseno = disenoQuery.data;
  useEffect(() => {
    if (!diseno?.layout || !diseno.editable || sembrado.current === diseno.id) return;
    sembrado.current = diseno.id;
    useEditor.getState().cargar(diseno.layout);
  }, [diseno]);

  // Al salir del editor el store queda vacío para el siguiente diseño. En
  // StrictMode el efecto corre dos veces; `sembrado` en null deja resembrar.
  useEffect(
    () => () => {
      sembrado.current = null;
      useEditor.getState().vaciar();
    },
    [],
  );

  const { guardando, error, guardarAhora } = useAutoguardado({
    // Solo en un diseño editable con escena cargada; uno de solo lectura nunca
    // siembra el store, así que tampoco guarda.
    activo: !!diseno?.editable && diseno.layout !== null && diseno.estado === "borrador" && listo,
    guardar: (escena, mensaje) =>
      guardarMut.mutateAsync(mensaje ? { layout: escena, mensaje } : { layout: escena }),
  });
  useAtajos();
  const [activando, setActivando] = useState(false);

  async function activar() {
    setActivando(true);
    try {
      if (useEditor.getState().sucio) await guardarAhora();
      if (useEditor.getState().sucio) {
        toast.error("No se pudo guardar antes de activar.");
        return;
      }
      await activarMut.mutateAsync();
      toast.success("Diseño publicado");
    } catch {
      toast.error("No se pudo activar el diseño.");
    } finally {
      setActivando(false);
    }
  }

  async function guardarVersion(mensaje: string) {
    try {
      await guardarAhora(mensaje);
      toast.success("Versión guardada");
    } catch (e) {
      toast.error("No se pudo guardar la versión.");
      throw e;
    }
  }

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

  const encabezado = (
    <div>
      <h1 className="text-xl font-semibold">{diseno.nombre}</h1>
      <p className="text-sm text-muted-foreground">
        {diseno.aspecto === "9:16" ? "Vertical" : "Cuadrada alta"}
      </p>
    </div>
  );

  // Los diseños viejos se hicieron antes del editor y solo tienen su versión
  // ya armada: no hay piezas que mover, así que no se abre el editor.
  if (!diseno.editable || diseno.layout === null) {
    return (
      <div className="space-y-4">
        {volver}
        {encabezado}
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
    <div className="flex h-[calc(100dvh-7rem)] min-h-[600px] flex-col gap-3">
      <div className="flex flex-wrap items-center gap-4">
        {volver}
        {encabezado}
      </div>
      <BarraSuperior
        estado={diseno.estado}
        guardando={guardando}
        errorGuardado={error}
        onGuardarVersion={guardarVersion}
        onActivar={() => void activar()}
        activando={activando}
        extra={
          <>
            <VistaPrevia slug={slug} contrato={diseno.contrato} />
            <DialogoVersiones
              slug={slug}
              id={disenoId}
              versionActual={diseno.version_actual}
              ocupado={guardando}
              onRestaurado={(d) => {
                if (d.layout) useEditor.getState().cargar(d.layout);
              }}
            />
          </>
        }
      />
      <div className="flex min-h-0 flex-1 gap-3">
        <aside className="w-60 shrink-0 overflow-hidden rounded-lg border">
          <PanelLateral pestanas={[{ id: "capas", etiqueta: "Capas", contenido: <PanelCapas /> }]} />
        </aside>
        <div className="min-w-0 flex-1 overflow-hidden rounded-lg border bg-muted/40">
          <Lienzo slug={slug} colorMarca={colorMarca} />
        </div>
        <aside className="w-72 shrink-0 overflow-y-auto rounded-lg border">
          <PanelPropiedades colorMarca={colorMarca} />
        </aside>
      </div>
    </div>
  );
}
