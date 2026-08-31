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
import { useCrearSlideshow, useCrearPost } from "@/hooks/use-job";
import { useEstadoFuentes } from "@/hooks/use-sources";
import { useTemplates } from "@/hooks/use-templates";
import { ASPECT_DEFAULT, aspectLabel, formatoLabel, formatosDeMarca } from "@/lib/formatos";
import { estiloLabel, estilosDeMarca } from "@/lib/estilos";
import { fuenteLabel, fuentesDeMarca } from "@/lib/fuentes";
import { WizardSteps } from "./_components/wizard-steps";
import { PasoTipo, type TipoPieza } from "./_components/paso-tipo";
import { PasoTema } from "./_components/paso-tema";
import { PasoFormato } from "./_components/paso-formato";
import { PasoEstilo } from "./_components/paso-estilo";
import { PasoFuentes } from "./_components/paso-fuentes";
import { PasoSlides } from "./_components/paso-slides";
import { PasoPlantilla } from "./_components/paso-plantilla";
import { PasoCampos } from "./_components/paso-campos";
import { ProgresoJob } from "./_components/progreso-job";

// El primer paso siempre es "¿Carrusel o post simple?". A partir de ahí el
// camino del carrusel sigue exactamente como antes (solo recorrido desde el
// paso 2 en vez del 1); el de post simple es plantilla → tema → campos.
const PASOS_CARRUSEL = ["Tipo", "Tema", "Formato", "Estilo", "Fuentes", "Slides"];
const PASOS_POST = ["Tipo", "Diseño", "Tema", "Campos"];

function CreateWizard() {
  const { slug } = useParams<{ slug: string }>();
  const searchParams = useSearchParams();
  const { data: marca, isLoading: brandLoading } = useBrand(slug);
  const { data: topics, isLoading: topicsLoading } = useTopics(slug);
  const { data: estadoFuentes } = useEstadoFuentes(slug);
  const { data: plantillas, isLoading: plantillasLoading } = useTemplates(slug);

  const temaInicial = searchParams.get("tema") ?? "";
  const topicIdInicial = Number(searchParams.get("topic"));

  const [paso, setPaso] = useState(1);
  const [tipoPieza, setTipoPieza] = useState<TipoPieza | undefined>(undefined);
  const [tema, setTema] = useState(temaInicial);
  const [contexto, setContexto] = useState("");
  const [topicId, setTopicId] = useState<number | undefined>(
    Number.isFinite(topicIdInicial) && topicIdInicial > 0 ? topicIdInicial : undefined
  );
  const [temaSyncId, setTemaSyncId] = useState<number | undefined>(undefined);
  const [formato, setFormato] = useState<string | undefined>(undefined);
  const [aspect, setAspect] = useState<string>(ASPECT_DEFAULT);
  const [estilo, setEstilo] = useState<string | undefined>(undefined);
  const [fuentesSel, setFuentesSel] = useState<string[] | null>(null);
  const [nSlides, setNSlides] = useState(6);
  const [templateId, setTemplateId] = useState<number | undefined>(undefined);
  const [campos, setCampos] = useState<Record<string, unknown>>({});
  const [jobId, setJobId] = useState<number | null>(null);

  const formatos = useMemo(() => formatosDeMarca(marca?.formatos), [marca]);
  const estilos = useMemo(() => estilosDeMarca(marca?.estilos_json), [marca]);
  const fuentesDisponibles = useMemo(() => fuentesDeMarca(marca?.fuentes_imagen), [marca]);
  const fuentesActivas = fuentesSel ?? fuentesDisponibles;

  const esPost = tipoPieza === "post";
  const pasosActivos = esPost ? PASOS_POST : PASOS_CARRUSEL;
  const totalPasos = pasosActivos.length;

  // Si llegamos con ?topic=id, precarga el tema cuando el listado de temas
  // resuelva ese id (una sola vez, sin pisar lo que el usuario ya editó).
  const topicResuelto = topics?.find((t) => t.id === topicId);
  if (topicResuelto && temaSyncId !== topicId && tema === temaInicial) {
    setTemaSyncId(topicId);
    setTema(topicResuelto.titulo);
  }

  const crear = useCrearSlideshow(slug);
  const crearPost = useCrearPost(slug);

  const plantillaSeleccionada = plantillas?.find((p) => p.id === templateId);

  function onTopicSelect(topic: Topic) {
    setTopicId(topic.id);
    setTema(topic.titulo);
  }

  async function onGenerarCarrusel() {
    try {
      const res = await crear.mutateAsync({
        tema: tema.trim(),
        formato,
        estilo,
        fuentes: fuentesActivas,
        n_slides: nSlides,
        aspect,
        contexto: contexto.trim() || undefined,
        topic_id: topicId,
      });
      setJobId(res.job_id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo iniciar la generación");
    }
  }

  async function onGenerarPost() {
    if (!templateId) return;
    try {
      const res = await crearPost.mutateAsync({
        template_id: templateId,
        tema: tema.trim(),
        campos,
      });
      setJobId(res.job_id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo iniciar la generación");
    }
  }

  function onGenerar() {
    return esPost ? onGenerarPost() : onGenerarCarrusel();
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

  const titulo = esPost ? "Crear post" : "Crear carrusel";

  if (jobId !== null) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold">{titulo}</h1>
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

  // Qué paso concreto es "paso" según el camino elegido: ambos comparten el
  // paso 1 (Tipo); de ahí se bifurcan.
  const pasoTema = esPost ? 3 : 2;
  const siguienteDeshabilitado =
    paso === 1
      ? !tipoPieza
      : esPost
        ? (paso === 2 && !templateId) || (paso === pasoTema && !temaValido)
        : paso === pasoTema && !temaValido;

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold">{titulo}</h1>
      <WizardSteps paso={paso} pasos={pasosActivos} />

      {paso === 1 && <PasoTipo valor={tipoPieza} onChange={setTipoPieza} />}

      {esPost && paso === 2 && (
        <PasoPlantilla
          slug={slug}
          plantillas={plantillas}
          isLoading={plantillasLoading}
          seleccionado={templateId}
          onChange={setTemplateId}
        />
      )}
      {esPost && paso === 3 && (
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
      {esPost && paso === 4 && (
        <PasoCampos
          slug={slug}
          extras={plantillaSeleccionada?.contrato.extras ?? []}
          valores={campos}
          onChange={setCampos}
        />
      )}

      {!esPost && paso === 2 && (
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
      {!esPost && paso === 3 && (
        <PasoFormato
          formatos={formatos}
          seleccionado={formato}
          onChange={setFormato}
          aspect={aspect}
          onAspectChange={setAspect}
        />
      )}
      {!esPost && paso === 4 && (
        <PasoEstilo slug={slug} estilos={estilos} seleccionado={estilo} onChange={setEstilo} />
      )}
      {!esPost && paso === 5 && (
        <PasoFuentes
          disponibles={fuentesDisponibles}
          activas={fuentesActivas}
          estado={estadoFuentes}
          onToggle={onToggleFuente}
        />
      )}
      {!esPost && paso === 6 && (
        <div className="space-y-5">
          <PasoSlides n={nSlides} onChange={setNSlides} />
          <div className="rounded-lg border bg-muted/30 p-4 text-sm">
            <p className="mb-2 font-medium">Resumen antes de generar</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-muted-foreground">
              <dt>Tema</dt>
              <dd className="text-foreground">{tema.trim()}</dd>
              <dt>Formato</dt>
              <dd className="text-foreground">{formatoLabel(formato ?? formatos[0])}</dd>
              <dt>Pantalla</dt>
              <dd className="text-foreground">{aspectLabel(aspect)}</dd>
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
        {paso < totalPasos ? (
          <Button disabled={siguienteDeshabilitado} onClick={() => setPaso((p) => p + 1)}>
            Siguiente
          </Button>
        ) : (
          <Button
            disabled={
              !temaValido || (esPost && !templateId) || crear.isPending || crearPost.isPending
            }
            onClick={onGenerar}
          >
            {(crear.isPending || crearPost.isPending) && <Loader2 className="animate-spin" />}
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
