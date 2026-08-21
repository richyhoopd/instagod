"use client";

import { Slider } from "@/components/ui/slider";

export function PasoSlides({ n, onChange }: { n: number; onChange: (v: number) => void }) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        ¿Cuántas imágenes lleva el carrusel? La primera engancha y la última cierra
        invitando a seguir la cuenta; el conteo ya las incluye.
      </p>
      <div className="flex items-center gap-4">
        <Slider min={3} max={10} step={1} value={[n]} onValueChange={([v]) => onChange(v)} />
        <span className="w-8 shrink-0 text-center text-lg font-semibold">{n}</span>
      </div>
    </div>
  );
}
