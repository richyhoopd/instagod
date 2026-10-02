"use client";

import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type { Topic } from "@/hooks/use-topics";
import type { VideoConfig } from "@/hooks/use-video-preset";

export type ModoHistoria = "tema" | "manual";

// Mínimo que exige video_model.validar al guion; sin LLM el cuerpo se narra
// tal cual, así que el backend lo revisa al encolar (crear_video).
export const PALABRAS_MIN_SIN_LLM = 20;

export function contarPalabras(texto: string): number {
  return texto.trim() ? texto.trim().split(/\s+/).length : 0;
}

export function PasoHistoria({
  slug,
  videoConfig,
  modo,
  onModoChange,
  topics,
  topicsLoading,
  topicId,
  onTopicSelect,
  titulo,
  onTituloChange,
  cuerpo,
  onCuerpoChange,
  sinLlm,
  onSinLlmChange,
}: {
  slug: string;
  videoConfig: VideoConfig | undefined;
  modo: ModoHistoria;
  onModoChange: (m: ModoHistoria) => void;
  topics: Topic[] | undefined;
  topicsLoading: boolean;
  topicId: number | undefined;
  onTopicSelect: (topic: Topic) => void;
  titulo: string;
  onTituloChange: (v: string) => void;
  cuerpo: string;
  onCuerpoChange: (v: string) => void;
  sinLlm: boolean;
  onSinLlmChange: (v: boolean) => void;
}) {
  // Solo los temas con resumen: el motor narra el resumen, sin él no hay reel.
  const narrables = (topics ?? []).filter((t) => t.resumen?.trim());
  const palabras = contarPalabras(cuerpo);

  return (
    <div className="space-y-4">
      {videoConfig && !videoConfig.configurado && (
        <div className="flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
          <p>
            Esta marca no tiene preset de video: el reel saldrá con la voz, colores y CTA por
            defecto del motor. Configúralo en{" "}
            <Link href={`/b/${slug}/settings?tab=video`} className="font-medium underline">
              Ajustes → Video
            </Link>
            .
          </p>
        </div>
      )}
      {videoConfig?.configurado && !videoConfig.tiene_personaje && (
        <p className="text-xs text-muted-foreground">
          Sin personaje: el reel sale sin narrador y con fondos de color plano.
        </p>
      )}

      <Tabs value={modo} onValueChange={(v) => onModoChange(v as ModoHistoria)}>
        <TabsList>
          <TabsTrigger value="tema">De los temas</TabsTrigger>
          <TabsTrigger value="manual">Escribirla</TabsTrigger>
        </TabsList>

        <TabsContent value="tema" className="space-y-2 pt-2">
          {topicsLoading && (
            <div className="space-y-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          )}
          {!topicsLoading && narrables.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No hay temas con historia para narrar. Escríbela a mano.
            </p>
          )}
          {narrables.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => onTopicSelect(t)}
              aria-pressed={topicId === t.id}
              className={cn(
                "w-full rounded-lg border p-2 text-left text-sm transition-colors hover:bg-muted",
                topicId === t.id && "border-(--brand) bg-(--brand)/5"
              )}
            >
              <p className="font-medium">{t.titulo}</p>
              <p className="line-clamp-3 text-xs text-muted-foreground">{t.resumen}</p>
            </button>
          ))}
        </TabsContent>

        <TabsContent value="manual" className="space-y-4 pt-2">
          <div className="space-y-1.5">
            <Label htmlFor="titulo-reel">Título</Label>
            <Input
              id="titulo-reel"
              value={titulo}
              onChange={(e) => onTituloChange(e.target.value)}
              placeholder="p. ej. Mi vecino cría gallinas en la azotea"
              maxLength={300}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cuerpo-reel">Historia</Label>
            <Textarea
              id="cuerpo-reel"
              value={cuerpo}
              onChange={(e) => onCuerpoChange(e.target.value)}
              rows={8}
              placeholder="Cuéntala completa; la IA la convierte en guion narrado."
            />
            <p className="text-xs text-muted-foreground">{palabras} palabras</p>
          </div>
        </TabsContent>
      </Tabs>

      <div className="flex items-start gap-3 rounded-lg border p-3">
        <Switch id="sin-llm" checked={sinLlm} onCheckedChange={onSinLlmChange} />
        <div className="space-y-0.5">
          <Label htmlFor="sin-llm">Narrar tal cual, sin reescribir con IA</Label>
          <p className="text-xs text-muted-foreground">
            Mínimo {PALABRAS_MIN_SIN_LLM} palabras. Si es muy larga para el máximo de duración, el
            reel falla al final.
          </p>
        </div>
      </div>
    </div>
  );
}
