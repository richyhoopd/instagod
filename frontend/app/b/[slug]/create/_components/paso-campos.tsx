"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { ChipInput } from "@/components/chip-input";
import { cn } from "@/lib/utils";
import { usePhotos } from "@/hooks/use-photos";
import type { ExtraContrato } from "@/hooks/use-templates";

// PRODUCT.md: cero jerga técnica visible. Un extra sin `desc` se etiqueta con
// su id capitalizado (guiones bajos como espacios), nunca con el id crudo.
function labelDe(extra: ExtraContrato): string {
  if (extra.desc) return extra.desc;
  const limpio = extra.id.replace(/_/g, " ");
  return limpio.charAt(0).toUpperCase() + limpio.slice(1);
}

function SelectorImagen({
  slug,
  valor,
  onChange,
}: {
  slug: string;
  valor: string | undefined;
  onChange: (v: string) => void;
}) {
  const { data: fotos, isLoading } = usePhotos(slug);

  if (isLoading) {
    return <Skeleton className="h-20 w-full" />;
  }

  const disponibles = fotos ?? [];
  if (disponibles.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No hay fotos en el banco de la marca todavía. Sube alguna en Ajustes → Fotos.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
      {disponibles.map((foto) => {
        const activo = valor === foto.url;
        return (
          <button
            key={foto.nombre}
            type="button"
            onClick={() => onChange(foto.url)}
            aria-pressed={activo}
            className={cn(
              "aspect-square overflow-hidden rounded-md border transition-opacity",
              activo ? "border-(--brand) ring-1 ring-(--brand)" : "hover:opacity-80"
            )}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- foto del banco de la marca */}
            <img src={foto.url} alt={foto.nombre} className="size-full object-cover" />
          </button>
        );
      })}
    </div>
  );
}

function CampoExtra({
  slug,
  extra,
  valor,
  onChange,
}: {
  slug: string;
  extra: ExtraContrato;
  valor: unknown;
  onChange: (v: unknown) => void;
}) {
  const label = labelDe(extra);
  const id = `campo-${extra.id}`;

  if (extra.tipo === "texto_largo") {
    return (
      <div className="space-y-1.5">
        <Label htmlFor={id}>{label}</Label>
        <Textarea
          id={id}
          value={(valor as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          rows={3}
        />
      </div>
    );
  }

  if (extra.tipo === "numero") {
    return (
      <div className="space-y-1.5">
        <Label htmlFor={id}>{label}</Label>
        <Input
          id={id}
          type="number"
          value={valor === undefined || valor === null ? "" : String(valor)}
          // El backend valida el tipo real: un número tiene que viajar como
          // número en el JSON, no como el string que da <input type="number">.
          onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
        />
      </div>
    );
  }

  if (extra.tipo === "booleano") {
    return (
      <div className="flex items-center justify-between rounded-lg border p-3">
        <Label htmlFor={id} className="cursor-pointer">
          {label}
        </Label>
        <Switch id={id} checked={!!valor} onCheckedChange={onChange} />
      </div>
    );
  }

  if (extra.tipo === "lista") {
    return (
      <div className="space-y-1.5">
        <Label>{label}</Label>
        <ChipInput
          value={(valor as string[]) ?? []}
          onChange={onChange}
          placeholder="Escribe y presiona Enter"
        />
        {(extra.min !== undefined || extra.max !== undefined) && (
          <p className="text-xs text-muted-foreground">
            Entre {extra.min ?? 1} y {extra.max ?? 10} elementos.
          </p>
        )}
      </div>
    );
  }

  if (extra.tipo === "imagen") {
    return (
      <div className="space-y-1.5">
        <Label>{label}</Label>
        <SelectorImagen slug={slug} valor={valor as string | undefined} onChange={onChange} />
      </div>
    );
  }

  // texto
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} value={(valor as string) ?? ""} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

export function PasoCampos({
  slug,
  extras,
  valores,
  onChange,
}: {
  slug: string;
  extras: ExtraContrato[];
  valores: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
}) {
  const [opcionalesAbiertos, setOpcionalesAbiertos] = useState(false);
  const requeridos = extras.filter((e) => !e.opcional);
  const opcionales = extras.filter((e) => e.opcional);

  function setCampo(id: string, v: unknown) {
    onChange({ ...valores, [id]: v });
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Completa el texto del post. El titular es lo único obligatorio.
      </p>

      <div className="space-y-1.5">
        <Label htmlFor="campo-titular">Titular</Label>
        <Input
          id="campo-titular"
          value={(valores.titular as string) ?? ""}
          onChange={(e) => setCampo("titular", e.target.value)}
          placeholder="El texto principal del post"
        />
      </div>

      {requeridos.map((extra) => (
        <CampoExtra
          key={extra.id}
          slug={slug}
          extra={extra}
          valor={valores[extra.id]}
          onChange={(v) => setCampo(extra.id, v)}
        />
      ))}

      {opcionales.length > 0 && (
        <div className="rounded-lg border">
          <button
            type="button"
            onClick={() => setOpcionalesAbiertos((v) => !v)}
            className="flex w-full items-center justify-between p-3 text-sm font-medium"
            aria-expanded={opcionalesAbiertos}
          >
            Opcionales
            {opcionalesAbiertos ? (
              <ChevronDown className="size-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="size-4 text-muted-foreground" />
            )}
          </button>
          {opcionalesAbiertos && (
            <div className="space-y-5 border-t p-3">
              {opcionales.map((extra) => (
                <CampoExtra
                  key={extra.id}
                  slug={slug}
                  extra={extra}
                  valor={valores[extra.id]}
                  onChange={(v) => setCampo(extra.id, v)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
