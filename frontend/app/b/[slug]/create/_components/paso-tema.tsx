"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { Topic } from "@/hooks/use-topics";

export function PasoTema({
  tema,
  onTemaChange,
  contexto,
  onContextoChange,
  topics,
  topicsLoading,
  topicId,
  onTopicSelect,
}: {
  tema: string;
  onTemaChange: (v: string) => void;
  contexto: string;
  onContextoChange: (v: string) => void;
  topics: Topic[] | undefined;
  topicsLoading: boolean;
  topicId: number | undefined;
  onTopicSelect: (topic: Topic) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="tema">Tema del carrusel</Label>
        <Input
          id="tema"
          value={tema}
          onChange={(e) => onTemaChange(e.target.value)}
          placeholder="p. ej. 5 señales de que tu ciudad está cambiando"
          maxLength={200}
        />
        <p className="text-xs text-muted-foreground">Mínimo 3 caracteres.</p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="contexto">Contexto adicional (opcional)</Label>
        <Textarea
          id="contexto"
          value={contexto}
          onChange={(e) => onContextoChange(e.target.value)}
          rows={3}
          placeholder="Datos, fuentes o el ángulo que quieres que la IA tome en cuenta..."
        />
      </div>

      {topicsLoading && (
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      )}

      {!topicsLoading && topics && topics.length > 0 && (
        <div className="space-y-2">
          <Label>O elige un tema sugerido</Label>
          <div className="space-y-2">
            {topics.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => onTopicSelect(t)}
                className={cn(
                  "w-full rounded-lg border p-2 text-left text-sm transition-colors hover:bg-muted",
                  topicId === t.id && "border-(--brand) bg-(--brand)/5"
                )}
              >
                <p className="font-medium">{t.titulo}</p>
                {t.resumen && (
                  <p className="line-clamp-2 text-xs text-muted-foreground">{t.resumen}</p>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
