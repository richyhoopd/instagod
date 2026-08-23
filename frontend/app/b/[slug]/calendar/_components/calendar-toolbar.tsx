"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
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
  mostrarRechazados,
  onMostrarRechazadosChange,
}: {
  vista: Vista;
  onVistaChange: (v: Vista) => void;
  ancla: Date;
  onAnterior: () => void;
  onSiguiente: () => void;
  onHoy: () => void;
  mostrarRechazados: boolean;
  onMostrarRechazadosChange: (v: boolean) => void;
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
        <h2 className="ml-1 text-base font-medium">{titulo}</h2>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <Switch
            id="mostrar-rechazados"
            checked={mostrarRechazados}
            onCheckedChange={onMostrarRechazadosChange}
          />
          <Label htmlFor="mostrar-rechazados" className="text-sm font-normal text-muted-foreground">
            Mostrar rechazados
          </Label>
        </div>
        <Tabs value={vista} onValueChange={(v) => onVistaChange(v as Vista)}>
          <TabsList>
            <TabsTrigger value="semana">Semana</TabsTrigger>
            <TabsTrigger value="mes">Mes</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
    </div>
  );
}
