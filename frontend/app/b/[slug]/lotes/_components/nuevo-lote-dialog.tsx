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
import { ApiError } from "@/lib/api";
import { useCrearLote } from "@/hooks/use-lotes";

/** Mes por default: el siguiente. Los slots ya pasados de este mes no se planean. */
export function mesDefault(hoy = new Date()): string {
  const m = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 1);
  return `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`;
}

const CRITERIOS = [
  {
    valor: "impacto" as const,
    label: "Impacto",
    ayuda: "Prioriza bandas grandes: pega más pero repite a las de siempre.",
  },
  {
    valor: "engagement" as const,
    label: "Engagement",
    ayuda: "Prioriza bandas chicas con buena interacción: más variedad.",
  },
];

export function NuevoLoteDialog({ slug }: { slug: string }) {
  const router = useRouter();
  const crear = useCrearLote(slug);
  const [abierto, setAbierto] = useState(false);
  const [mes, setMes] = useState(() => mesDefault());
  const [criterio, setCriterio] = useState<"impacto" | "engagement">("impacto");
  const [replan, setReplan] = useState(false);

  const enviar = () => {
    crear.mutate(
      { mes: mes.trim(), criterio, replan },
      {
        onSuccess: ({ mes: creado }) => {
          setAbierto(false);
          setReplan(false);
          router.push(`/b/${slug}/lotes/${creado}`);
        },
        onError: (e) => {
          // El backend marca campo="replan" cuando ya hay borrador de ese mes.
          if (e instanceof ApiError && e.campo === "replan") setReplan(true);
          toast.error(e instanceof Error ? e.message : "No se pudo planear el lote");
        },
      },
    );
  };

  const ayuda = CRITERIOS.find((c) => c.valor === criterio)?.ayuda;

  return (
    <Dialog open={abierto} onOpenChange={setAbierto}>
      <DialogTrigger asChild>
        <Button>Nuevo lote</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Planear lote de memes</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="mes">Mes</Label>
            <Input
              id="mes"
              value={mes}
              onChange={(e) => setMes(e.target.value)}
              placeholder="2026-10"
            />
            <p className="text-xs text-muted-foreground">
              Solo se planean los horarios que aún no pasan.
            </p>
          </div>

          <div className="grid gap-1.5">
            <Label>Criterio de selección</Label>
            <div className="flex gap-2">
              {CRITERIOS.map((c) => (
                <Button
                  key={c.valor}
                  variant={criterio === c.valor ? "default" : "outline"}
                  size="sm"
                  onClick={() => setCriterio(c.valor)}
                >
                  {c.label}
                </Button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">{ayuda}</p>
          </div>

          <div className="flex items-center justify-between gap-4">
            <Label htmlFor="replan" className="font-normal">
              Rehacer si ya hay borrador de ese mes
            </Label>
            <Switch id="replan" checked={replan} onCheckedChange={setReplan} />
          </div>
          {replan && (
            <p className="text-xs text-muted-foreground">
              Tira el borrador anterior y vuelve a elegir fotos. Lo tirado no regresa.
            </p>
          )}

          <Button onClick={enviar} disabled={crear.isPending || !mes.trim()}>
            {crear.isPending ? "Planeando…" : "Planear"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
