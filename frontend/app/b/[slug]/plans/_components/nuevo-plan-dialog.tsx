"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useCrearPlan } from "@/hooks/use-plans";

/** Periodo por default: la semana ISO siguiente, o el mes siguiente. */
export function periodoDefault(tipo: "semana" | "mes", hoy = new Date()): string {
  if (tipo === "mes") {
    const m = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 1);
    return `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`;
  }
  const d = new Date(hoy);
  d.setDate(d.getDate() + 7);
  // Semana ISO: el jueves de esa semana define el año y el número.
  const jueves = new Date(d);
  jueves.setDate(d.getDate() + 3 - ((d.getDay() + 6) % 7));
  const inicioAno = new Date(jueves.getFullYear(), 0, 1);
  const semana = Math.ceil(((+jueves - +inicioAno) / 86400000 + 1) / 7);
  return `${jueves.getFullYear()}-W${String(semana).padStart(2, "0")}`;
}

export function NuevoPlanDialog({ slug }: { slug: string }) {
  const router = useRouter();
  const crear = useCrearPlan(slug);
  const [abierto, setAbierto] = useState(false);
  const [tipo, setTipo] = useState<"semana" | "mes">("semana");
  const [periodo, setPeriodo] = useState(() => periodoDefault("semana"));
  const [objetivo, setObjetivo] = useState("");
  const [nPiezas, setNPiezas] = useState(8);
  const [conNoticias, setConNoticias] = useState(false);

  const cambiarTipo = (t: "semana" | "mes") => {
    setTipo(t);
    setPeriodo(periodoDefault(t));
    setNPiezas(t === "mes" ? 20 : 8);
  };

  const enviar = () => {
    crear.mutate(
      {
        tipo_periodo: tipo,
        periodo,
        objetivo: objetivo.trim(),
        n_piezas: nPiezas,
        fuentes_info: conNoticias ? ["prompt", "noticias"] : ["prompt"],
      },
      {
        onSuccess: ({ plan_id }) => {
          setAbierto(false);
          router.push(`/b/${slug}/plans/${plan_id}`);
        },
        onError: (e) =>
          toast.error(e instanceof Error ? e.message : "No se pudo crear el plan"),
      },
    );
  };

  return (
    <Dialog open={abierto} onOpenChange={setAbierto}>
      <DialogTrigger asChild>
        <Button>Nuevo plan</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nuevo plan de contenido</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="flex gap-2">
            <Button
              variant={tipo === "semana" ? "default" : "outline"}
              size="sm"
              onClick={() => cambiarTipo("semana")}
            >
              Semanal
            </Button>
            <Button
              variant={tipo === "mes" ? "default" : "outline"}
              size="sm"
              onClick={() => cambiarTipo("mes")}
            >
              Mensual
            </Button>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="periodo">Periodo</Label>
            <Input
              id="periodo"
              value={periodo}
              onChange={(e) => setPeriodo(e.target.value)}
              placeholder={tipo === "semana" ? "2026-W36" : "2026-09"}
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="objetivo">¿Qué quieres lograr este periodo?</Label>
            <Textarea
              id="objetivo"
              value={objetivo}
              rows={3}
              onChange={(e) => setObjetivo(e.target.value)}
              placeholder="Ej. dar a conocer los foros chicos y llevar gente a los shows de octubre"
            />
            <p className="text-xs text-muted-foreground">
              Con esto te proponemos los temas. Los revisas antes de generar nada.
            </p>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="npiezas">Número de publicaciones</Label>
            <Input
              id="npiezas"
              type="number"
              min={1}
              max={30}
              value={nPiezas}
              onChange={(e) => setNPiezas(Number(e.target.value))}
            />
          </div>

          <div className="flex items-center justify-between gap-4">
            <Label htmlFor="noticias" className="font-normal">
              Usar noticias de mis fuentes como inspiración
            </Label>
            <Switch id="noticias" checked={conNoticias} onCheckedChange={setConNoticias} />
          </div>

          <Button
            onClick={enviar}
            disabled={crear.isPending || objetivo.trim().length < 10 || nPiezas < 1}
          >
            {crear.isPending ? "Creando…" : "Proponer temas"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
