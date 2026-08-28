"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Check, ExternalLink, X } from "lucide-react";

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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useAgregarTopic,
  useEditarTopic,
  useGenerarPlan,
  type PlanDetail,
  type PlanTopic,
} from "@/hooks/use-plans";

function FilaTema({
  slug,
  pid,
  tema,
}: {
  slug: string;
  pid: number;
  tema: PlanTopic;
}) {
  const editar = useEditarTopic(slug, pid);
  const [titulo, setTitulo] = useState(tema.titulo);
  const descartado = tema.estado === "descartado";
  const aprobado = tema.estado === "aprobado";

  const guardarTitulo = () => {
    const limpio = titulo.trim();
    if (limpio.length >= 3 && limpio !== tema.titulo) {
      editar.mutate({ tid: tema.id, titulo: limpio });
    } else if (limpio.length < 3) {
      setTitulo(tema.titulo);
    }
  };

  return (
    <div
      className={`flex items-center gap-2 rounded-md border p-2 ${
        descartado ? "opacity-50" : ""
      }`}
    >
      <Input
        value={titulo}
        className="flex-1"
        onChange={(e) => setTitulo(e.target.value)}
        onBlur={guardarTitulo}
      />
      {tema.hook && (
        <span
          className="hidden max-w-[16rem] truncate text-xs text-muted-foreground lg:inline"
          title={tema.hook}
        >
          {tema.hook}
        </span>
      )}
      {tema.fuente === "noticia" && tema.url && (
        <a
          href={tema.url}
          target="_blank"
          rel="noreferrer"
          className="text-muted-foreground hover:text-foreground"
          title="Ver la noticia"
        >
          <ExternalLink className="size-4" />
        </a>
      )}
      {tema.formato && <Badge variant="outline">{tema.formato}</Badge>}
      <Button
        size="icon"
        variant={aprobado ? "default" : "outline"}
        title="Incluir en el plan"
        onClick={() => editar.mutate({ tid: tema.id, estado: "aprobado" })}
      >
        <Check className="size-4" />
      </Button>
      <Button
        size="icon"
        variant={descartado ? "destructive" : "outline"}
        title="Descartar"
        onClick={() => editar.mutate({ tid: tema.id, estado: "descartado" })}
      >
        <X className="size-4" />
      </Button>
    </div>
  );
}

export function CuradorTemas({ slug, plan }: { slug: string; plan: PlanDetail }) {
  const agregar = useAgregarTopic(slug, plan.id);
  const generar = useGenerarPlan(slug, plan.id);
  const [nuevo, setNuevo] = useState("");
  const aprobados = plan.topics.filter((t) => t.estado === "aprobado").length;

  const agregarTema = () => {
    const limpio = nuevo.trim();
    if (limpio.length < 3) return;
    agregar.mutate(
      { titulo: limpio },
      {
        onSuccess: () => setNuevo(""),
        onError: (e) =>
          toast.error(e instanceof Error ? e.message : "No se pudo agregar el tema"),
      },
    );
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Revisa los temas antes de generar nada. Marca ✓ los que quieres, ✕ los que no, o
        edita el título directo.
      </p>

      <div className="space-y-2">
        {plan.topics.map((t) => (
          <FilaTema key={t.id} slug={slug} pid={plan.id} tema={t} />
        ))}
      </div>

      <div className="flex gap-2">
        <Input
          value={nuevo}
          placeholder="Agregar un tema tuyo…"
          onChange={(e) => setNuevo(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && agregarTema()}
        />
        <Button variant="outline" disabled={nuevo.trim().length < 3} onClick={agregarTema}>
          Agregar
        </Button>
      </div>

      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button disabled={aprobados === 0 || generar.isPending}>
            Generar {aprobados} {aprobados === 1 ? "publicación" : "publicaciones"}
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Generar el contenido?</AlertDialogTitle>
            <AlertDialogDescription>
              Se van a crear {aprobados}{" "}
              {aprobados === 1 ? "publicación" : "publicaciones"} con sus imágenes. Toma
              varios minutos y corre en segundo plano; después las revisas una por una.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                generar.mutate(undefined, {
                  onError: (e) =>
                    toast.error(e instanceof Error ? e.message : "No se pudo generar"),
                })
              }
            >
              Generar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
