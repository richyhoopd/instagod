"use client";

import { Suspense, useMemo, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { useBrand } from "@/hooks/use-brands";
import { useTopics, type Topic } from "@/hooks/use-topics";
import { useCrearSlideshow } from "@/hooks/use-job";
import { formatoLabel, formatosDeMarca } from "@/lib/formatos";
import { estiloLabel, estilosDeMarca } from "@/lib/estilos";
import { fuenteLabel, fuentesDeMarca } from "@/lib/fuentes";
import { WizardSteps } from "./_components/wizard-steps";
import { PasoTema } from "./_components/paso-tema";
import { PasoFormato } from "./_components/paso-formato";
import { PasoEstilo } from "./_components/paso-estilo";
import { PasoFuentes } from "./_components/paso-fuentes";
import { PasoSlides } from "./_components/paso-slides";
import { ProgresoJob } from "./_components/progreso-job";

const TOTAL_PASOS = 5;

function CreateWizard() {
  const { slug } = useParams<{ slug: string }>();
  const searchParams = useSearchParams();
  const { data: marca, isLoading: brandLoading } = useBrand(slug);
  const { data: topics, isLoading: topicsLoading } = useTopics(slug);

  const temaInicial = searchParams.get("tema") ?? "";
  const topicIdInicial = Number(searchParams.get("topic"));

  const [paso, setPaso] = useState(1);
  const [tema, setTema] = useState(temaInicial);
  const [contexto, setContexto] = useState("");
  const [topicId, setTopicId] = useState<number | undefined>(
    Number.isFinite(topicIdInicial) && topicIdInicial > 0 ? topicIdInicial : undefined
  );
  const [temaSyncId, setTemaSyncId] = useState<number | undefined>(undefined);
  const [formato, setFormato] = useState<string | undefined>(undefined);
  const [estilo, setEstilo] = useState<string | undefined>(undefined);
  const [fuentesSel, setFuentesSel] = useState<string[] | null>(null);
  const [nSlides, setNSlides] = useState(6);
  const [jobId, setJobId] = useState<number | null>(null);

  const formatos = useMemo(() => formatosDeMarca(marca?.formatos), [marca]);
  const estilos = useMemo(() => estilosDeMarca(marca?.estilos_json), [marca]);
  const fuentesDisponibles = useMemo(() => fuentesDeMarca(marca?.fuentes_imagen), [marca]);
  const fuentesActivas = fuentesSel ?? fuentesDisponibles;

  // Si llegamos con ?topic=id, precarga el tema cuando el listado de temas
  // resuelva ese id (una sola vez, sin pisar lo que el usuario ya editó).
  const topicResuelto = topics?.find((t) => t.id === topicId);
  if (topicResuelto && temaSyncId !== topicId && tema === temaInicial) {
    setTemaSyncId(topicId);
    setTema(topicResuelto.titulo);
  }

  const crear = useCrearSlideshow(slug);

  function onTopicSelect(topic: Topic) {
    setTopicId(topic.id);
    setTema(topic.titulo);
  }

  async function onGenerar() {
    try {
      const res = await crear.mutateAsync({
        tema: tema.trim(),
        formato,
        estilo,
        fuentes: fuentesActivas,
        n_slides: nSlides,
        contexto: contexto.trim() || undefined,
        topic_id: topicId,
      });
      setJobId(res.job_id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo iniciar la generación");
    }
  }

  function onToggleFuente(fuente: string) {
    const activas = fuentesSel ?? fuentesDisponibles;
    setFuentesSel(
      activas.includes(fuente) ? activas.filter((f) => f !== fuente) : [...activas, fuente]
    );
  }

  if (brandLoading) {
    return <Skeleton className="h-96 w-full" />;
  }

  if (jobId !== null) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold">Crear carrusel</h1>
        <ProgresoJob
          slug={slug}
          jobId={jobId}
          onNuevoJob={setJobId}
          onReintentarError={onGenerar}
          onVolver={() => setJobId(null)}
        />
      </div>
    );
  }

  const temaValido = tema.trim().length >= 3;

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold">Crear carrusel</h1>
      <WizardSteps paso={paso} />

      {paso === 1 && (
        <PasoTema
          tema={tema}
          onTemaChange={setTema}
          contexto={contexto}
          onContextoChange={setContexto}
          topics={topics}
          topicsLoading={topicsLoading}
          topicId={topicId}
          onTopicSelect={onTopicSelect}
        />
      )}
      {paso === 2 && (
        <PasoFormato formatos={formatos} seleccionado={formato} onChange={setFormato} />
      )}
      {paso === 3 && (
        <PasoEstilo estilos={estilos} seleccionado={estilo} onChange={setEstilo} />
      )}
      {paso === 4 && (
        <PasoFuentes
          disponibles={fuentesDisponibles}
          activas={fuentesActivas}
          onToggle={onToggleFuente}
        />
      )}
      {paso === 5 && (
        <div className="space-y-5">
          <PasoSlides n={nSlides} onChange={setNSlides} />
          <div className="rounded-lg border bg-muted/30 p-4 text-sm">
            <p className="mb-2 font-medium">Resumen antes de generar</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-muted-foreground">
              <dt>Tema</dt>
              <dd className="text-foreground">{tema.trim()}</dd>
              <dt>Formato</dt>
              <dd className="text-foreground">{formatoLabel(formato ?? formatos[0])}</dd>
              <dt>Estilo</dt>
              <dd className="text-foreground">
                {estilo ? estiloLabel(estilo) : "El habitual de la marca"}
              </dd>
              <dt>Imágenes de</dt>
              <dd className="text-foreground">
                {fuentesActivas.length > 0
                  ? fuentesActivas.map(fuenteLabel).join(", ")
                  : "fuentes estándar"}
              </dd>
              <dt>Slides</dt>
              <dd className="text-foreground">{nSlides}</dd>
            </dl>
            <p className="mt-3 text-xs text-muted-foreground">
              La generación tarda unos minutos. El carrusel queda pendiente de tu
              aprobación: nada se publica solo.
            </p>
          </div>
        </div>
      )}

      <div className="flex justify-between border-t pt-4">
        <Button variant="outline" disabled={paso === 1} onClick={() => setPaso((p) => p - 1)}>
          Atrás
        </Button>
        {paso < TOTAL_PASOS ? (
          <Button disabled={paso === 1 && !temaValido} onClick={() => setPaso((p) => p + 1)}>
            Siguiente
          </Button>
        ) : (
          <Button disabled={!temaValido || crear.isPending} onClick={onGenerar}>
            {crear.isPending && <Loader2 className="animate-spin" />}
            Generar
          </Button>
        )}
      </div>
    </div>
  );
}

export default function CreatePage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <CreateWizard />
    </Suspense>
  );
}
