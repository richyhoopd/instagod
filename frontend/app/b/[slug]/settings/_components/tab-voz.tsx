"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ChipInput } from "@/components/chip-input";
import { NoDisponible } from "@/components/no-disponible";
import { ApiError } from "@/lib/api";
import { usePrompts, useGuardarPrompts, useProbarPrompt } from "@/hooks/use-prompts";
import { formatosDeMarca, formatoLabel } from "@/lib/formatos";
import type { BrandDetail } from "@/hooks/use-brands";

export function TabVoz({
  slug,
  marca,
  puedeEditar,
}: {
  slug: string;
  marca: BrandDetail;
  puedeEditar: boolean;
}) {
  const promptsQuery = usePrompts(slug);
  const guardar = useGuardarPrompts(slug);
  const probar = useProbarPrompt(slug);

  const formatos = formatosDeMarca(marca.formatos);

  const [voz, setVoz] = useState("");
  const [captionExtra, setCaptionExtra] = useState("");
  const [porFormato, setPorFormato] = useState<Record<string, string>>({});
  const [hashtags, setHashtags] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);

  const [temaPrueba, setTemaPrueba] = useState("");
  const [formatoPrueba, setFormatoPrueba] = useState("");

  // Precarga el borrador cuando llega la primera respuesta de la API (sin
  // efecto: react-hooks/set-state-in-effect). Refetches posteriores del
  // mismo query no vuelven a pisar lo que el usuario esté editando.
  const [sincronizado, setSincronizado] = useState(false);
  if (promptsQuery.data && !sincronizado) {
    setSincronizado(true);
    setVoz(promptsQuery.data.voz ?? "");
    setCaptionExtra(promptsQuery.data.caption_extra ?? "");
    setPorFormato(promptsQuery.data.por_formato ?? {});
    setHashtags(promptsQuery.data.hashtags ?? []);
  }

  if (promptsQuery.isLoading) {
    return <Skeleton className="h-64 w-full max-w-2xl" />;
  }

  if (promptsQuery.isError) {
    if (promptsQuery.error.status === 404) {
      return (
        <NoDisponible mensaje="La edición de voz y prompts todavía no está disponible en este servidor." />
      );
    }
    return <NoDisponible mensaje={promptsQuery.error.detalle} />;
  }

  async function guardarCambios() {
    // PromptsIn (api/routers/perfil.py) exige voz/caption_extra como string
    // (no nullable) y hashtags con "#" al frente; nunca mandar null aquí.
    const hashtagsNormalizados = hashtags.map((h) => (h.startsWith("#") ? h : `#${h}`));
    try {
      await guardar.mutateAsync({
        voz,
        caption_extra: captionExtra,
        por_formato: porFormato,
        hashtags: hashtagsNormalizados,
      });
      toast.success("Prompts guardados");
      setDirty(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo guardar");
    }
  }

  async function ejecutarPrueba() {
    if (!temaPrueba.trim()) {
      toast.error("Escribe un tema de ejemplo");
      return;
    }
    try {
      await probar.mutateAsync({
        tema: temaPrueba,
        formato: formatoPrueba === "default" ? undefined : formatoPrueba || undefined,
      });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo generar la prueba");
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div className="space-y-2">
        <Label htmlFor="voz">Voz de la marca</Label>
        <Textarea
          id="voz"
          rows={4}
          disabled={!puedeEditar}
          value={voz}
          onChange={(e) => {
            setVoz(e.target.value);
            setDirty(true);
          }}
          placeholder="Tono, personalidad y reglas de estilo para el LLM..."
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="caption_extra">Extra para captions</Label>
        <Textarea
          id="caption_extra"
          rows={3}
          disabled={!puedeEditar}
          value={captionExtra}
          onChange={(e) => {
            setCaptionExtra(e.target.value);
            setDirty(true);
          }}
        />
      </div>
      <div className="space-y-3">
        <Label>Instrucciones por formato</Label>
        {formatos.map((f) => (
          <div key={f} className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">{formatoLabel(f)}</p>
            <Textarea
              rows={2}
              disabled={!puedeEditar}
              value={porFormato[f] ?? ""}
              onChange={(e) => {
                setPorFormato((prev) => ({ ...prev, [f]: e.target.value }));
                setDirty(true);
              }}
            />
          </div>
        ))}
      </div>
      <div className="space-y-2">
        <Label>Hashtags de prompts</Label>
        <ChipInput
          value={hashtags}
          onChange={(v) => {
            setHashtags(v);
            setDirty(true);
          }}
          placeholder="#hashtag y Enter"
          disabled={!puedeEditar}
        />
      </div>
      {puedeEditar && (
        <Button onClick={guardarCambios} disabled={guardar.isPending || !dirty}>
          {guardar.isPending ? "Guardando..." : "Guardar cambios"}
        </Button>
      )}

      <div className="space-y-3 border-t pt-6">
        <Label>Probar generación</Label>
        <div className="flex flex-wrap gap-2">
          <Input
            value={temaPrueba}
            onChange={(e) => setTemaPrueba(e.target.value)}
            placeholder="Tema de ejemplo"
            className="max-w-xs"
          />
          <Select value={formatoPrueba || "default"} onValueChange={setFormatoPrueba}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="default">Formato default</SelectItem>
              {formatos.map((f) => (
                <SelectItem key={f} value={f}>
                  {formatoLabel(f)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button type="button" variant="outline" onClick={ejecutarPrueba} disabled={probar.isPending}>
            {probar.isPending ? "Probando..." : "Probar"}
          </Button>
        </div>
        {probar.data !== undefined && (
          <pre className="max-h-96 overflow-auto rounded-lg border bg-muted p-3 text-xs whitespace-pre-wrap">
            {JSON.stringify(probar.data, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
