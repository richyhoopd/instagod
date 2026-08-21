"use client";

import { Info } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { BrandDetail } from "@/hooks/use-brands";

export function TabHorarios({ marca }: { marca: BrandDetail }) {
  const slots = (marca.posting_slots ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  return (
    <div className="max-w-xl space-y-4">
      <div className="flex items-start gap-2 rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
        <Info className="mt-0.5 size-4 shrink-0" />
        <p>
          Estos son los horarios en los que la marca publica cada día. Por ahora no se pueden
          editar desde aquí; si necesitas cambiarlos, pídeselo al administrador.
        </p>
      </div>

      <div className="space-y-1.5">
        <p className="text-sm font-medium">Zona horaria</p>
        <p className="text-sm text-muted-foreground">{marca.timezone || "—"}</p>
      </div>

      <div className="space-y-1.5">
        <p className="text-sm font-medium">Horarios configurados ({slots.length} por día)</p>
        {slots.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sin horarios propios; se usan los horarios estándar de instagod.</p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {slots.map((slot) => (
              <Badge key={slot} variant="outline" className="font-normal">
                {slot}
              </Badge>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
