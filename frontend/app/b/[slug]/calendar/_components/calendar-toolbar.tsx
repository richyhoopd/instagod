"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatMesAno, formatRangoSemana } from "@/lib/calendario";

export type Vista = "semana" | "mes";

export function CalendarToolbar({
  vista,
  onVistaChange,
  ancla,
  onAnterior,
  onSiguiente,
  onHoy,
}: {
  vista: Vista;
  onVistaChange: (v: Vista) => void;
  ancla: Date;
  onAnterior: () => void;
  onSiguiente: () => void;
  onHoy: () => void;
}) {
  const titulo = vista === "semana" ? formatRangoSemana(ancla) : formatMesAno(ancla);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <Button variant="outline" size="icon-sm" onClick={onAnterior} aria-label="Semana o mes anterior">
          <ChevronLeft />
        </Button>
        <Button variant="outline" size="sm" onClick={onHoy}>
          Hoy
        </Button>
        <Button variant="outline" size="icon-sm" onClick={onSiguiente} aria-label="Semana o mes siguiente">
          <ChevronRight />
        </Button>
        <h2 className="ml-1 text-base font-medium capitalize">{titulo}</h2>
      </div>
      <Tabs value={vista} onValueChange={(v) => onVistaChange(v as Vista)}>
        <TabsList>
          <TabsTrigger value="semana">Semana</TabsTrigger>
          <TabsTrigger value="mes">Mes</TabsTrigger>
        </TabsList>
      </Tabs>
    </div>
  );
}
