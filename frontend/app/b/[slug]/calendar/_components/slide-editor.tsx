"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ImageOff, Link2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { usePhotos } from "@/hooks/use-photos";
import { useJob } from "@/hooks/use-job";
import { useEditarSlides, type SlideEdit } from "@/hooks/use-queue";

// Forma mínima de slideshow_json que necesita el editor (src/slideshow_model.py).
export interface SlideData {
  image_urls: string[];
  text_items: { text: string }[];
}

export function slidesDe(slidesData: unknown): SlideData[] | null {
  if (!slidesData || typeof slidesData !== "object") return null;
  const slides = (slidesData as { slides?: unknown }).slides;
  if (!Array.isArray(slides) || slides.length === 0) return null;
  return slides as SlideData[];
}

function draftInicial(slides: SlideData[]): SlideEdit[] {
  return slides.map((s) => ({
    texts: (s.text_items ?? []).map((t) => t.text),
    image_url: (s.image_urls ?? [])[0] ?? null,
  }));
}

// Vista del fondo actual: http(s) y /brands/... se pueden previsualizar;
// una ruta local del server (elegida por el provider "carpeta") no.
function previewDe(url: string | null): { src: string | null; label: string } {
  if (!url) return { src: null, label: "Fondo sólido (sin foto)" };
  if (url.startsWith("/brands/")) {
    return { src: `/api${url}`, label: url.split("/").pop() ?? url };
  }
  if (url.startsWith("http://") || url.startsWith("https://")) {
    return { src: url, label: url.replace(/^https?:\/\//, "") };
  }
  return { src: null, label: url.split("/").pop() ?? url };
}

export function SlideEditor({
  slug,
  qid,
  slides,
  slideIdx,
}: {
  slug: string;
  qid: number;
  slides: SlideData[];
  slideIdx: number;
}) {
  const [draft, setDraft] = useState<SlideEdit[]>(() => draftInicial(slides));
  const [jobId, setJobId] = useState<number | null>(null);
  const [pickerAbierto, setPickerAbierto] = useState(false);
  const [urlManual, setUrlManual] = useState<string | null>(null);
  const editarSlides = useEditarSlides(slug);
  const { data: job } = useJob(slug, jobId);
  const photosQuery = usePhotos(slug);
  const qc = useQueryClient();
  const avisadoRef = useRef<number | null>(null);

  // Al terminar el re-render: refrescar el item (imagen_url nueva) y avisar.
  // Solo side effects (sin setState): la UI se deriva del estado del job.
  useEffect(() => {
    if (jobId === null || !job || avisadoRef.current === jobId) return;
    if (job.estado === "ok") {
      avisadoRef.current = jobId;
      qc.invalidateQueries({ queryKey: ["queue-item", slug, qid] });
      qc.invalidateQueries({ queryKey: ["queue", slug] });
      toast.success("Slides actualizados");
    } else if (job.estado === "error" || job.estado === "cancelado") {
      avisadoRef.current = jobId;
      toast.error("No se pudo re-renderizar el carrusel");
    }
  }, [job, jobId, qc, slug, qid]);

  const idx = Math.min(slideIdx, draft.length - 1);
  const slide = draft[idx];
  const guardando =
    editarSlides.isPending ||
    (jobId !== null && (!job || job.estado === "cola" || job.estado === "corriendo"));
  const hayCambios = JSON.stringify(draft) !== JSON.stringify(draftInicial(slides));
  const preview = previewDe(slide.image_url);

  function setSlide(cambio: Partial<SlideEdit>) {
    setDraft((d) => d.map((s, i) => (i === idx ? { ...s, ...cambio } : s)));
  }

  async function onGuardar() {
    try {
      const res = await editarSlides.mutateAsync({ qid, slides: draft });
      avisadoRef.current = null;
      setJobId(res.job_id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudieron guardar los slides");
    }
  }

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <p className="text-xs font-medium text-muted-foreground">
        Editando slide {idx + 1} de {draft.length}
      </p>

      {slide.texts.map((texto, i) => (
        <Textarea
          key={i}
          value={texto}
          rows={2}
          disabled={guardando}
          onChange={(e) =>
            setSlide({ texts: slide.texts.map((t, j) => (j === i ? e.target.value : t)) })
          }
          placeholder={`Texto ${i + 1}`}
        />
      ))}

      <div className="flex items-center gap-2">
        {preview.src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={preview.src} alt="Fondo del slide" className="size-10 rounded object-cover" />
        ) : (
          <span className="flex size-10 items-center justify-center rounded bg-muted">
            <ImageOff className="size-4 text-muted-foreground" />
          </span>
        )}
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {preview.label}
        </span>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={guardando}
          onClick={() => {
            setPickerAbierto((v) => !v);
            setUrlManual(null);
          }}
        >
          Banco
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={guardando}
          onClick={() => {
            setUrlManual((v) => (v === null ? "" : null));
            setPickerAbierto(false);
          }}
        >
          <Link2 />
        </Button>
        {slide.image_url !== null && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={guardando}
            onClick={() => setSlide({ image_url: null })}
          >
            Quitar
          </Button>
        )}
      </div>

      {pickerAbierto && (
        <div className="max-h-40 overflow-y-auto rounded-md border p-2">
          {photosQuery.isLoading ? (
            <Loader2 className="mx-auto size-4 animate-spin" />
          ) : !photosQuery.data?.length ? (
            <p className="text-center text-xs text-muted-foreground">
              La marca no tiene fotos en el banco
            </p>
          ) : (
            <div className="grid grid-cols-5 gap-2">
              {photosQuery.data.map((foto) => (
                <button
                  key={foto.nombre}
                  type="button"
                  className="overflow-hidden rounded border hover:ring-2 hover:ring-(--brand)"
                  onClick={() => {
                    setSlide({ image_url: foto.url });
                    setPickerAbierto(false);
                  }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`/api/brands/${slug}/files/fotos/${foto.nombre}`}
                    alt={foto.nombre}
                    className="aspect-square w-full object-cover"
                  />
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {urlManual !== null && (
        <div className="flex gap-2">
          <Input
            value={urlManual}
            onChange={(e) => setUrlManual(e.target.value)}
            placeholder="https://..."
            disabled={guardando}
          />
          <Button
            type="button"
            size="sm"
            disabled={guardando || !urlManual.trim()}
            onClick={() => {
              setSlide({ image_url: urlManual.trim() });
              setUrlManual(null);
            }}
          >
            Usar
          </Button>
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button size="sm" disabled={guardando || !hayCambios} onClick={onGuardar}>
          {guardando && <Loader2 className="animate-spin" />}
          {guardando ? "Re-renderizando..." : "Guardar y re-renderizar"}
        </Button>
        {guardando && job?.progreso != null && (
          <span className="text-xs text-muted-foreground">{job.progreso}%</span>
        )}
      </div>
    </div>
  );
}
