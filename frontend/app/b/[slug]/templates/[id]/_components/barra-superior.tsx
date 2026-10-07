"use client";

import { useState, type ReactNode } from "react";
import {
  AlignCenterHorizontal,
  AlignCenterVertical,
  AlignEndHorizontal,
  AlignEndVertical,
  AlignHorizontalDistributeCenter,
  AlignStartHorizontal,
  AlignStartVertical,
  AlignVerticalDistributeCenter,
  Redo2,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { Diseno } from "@/hooks/use-disenos";
import type { ModoAlinear } from "@/lib/edicion";
import type { Formato } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

const FORMATOS: { valor: Formato; nombre: string }[] = [
  { valor: "4x5", nombre: "4:5" },
  { valor: "1x1", nombre: "1:1" },
  { valor: "9x16", nombre: "9:16" },
];

const ALINEAR: { modo: ModoAlinear; nombre: string; Icono: LucideIcon }[] = [
  { modo: "izq", nombre: "Alinear a la izquierda", Icono: AlignStartVertical },
  { modo: "centro-h", nombre: "Centrar en horizontal", Icono: AlignCenterVertical },
  { modo: "der", nombre: "Alinear a la derecha", Icono: AlignEndVertical },
  { modo: "arriba", nombre: "Alinear arriba", Icono: AlignStartHorizontal },
  { modo: "centro-v", nombre: "Centrar en vertical", Icono: AlignCenterHorizontal },
  { modo: "abajo", nombre: "Alinear abajo", Icono: AlignEndHorizontal },
];

const ETIQUETA_ESTADO: Record<Diseno["estado"], string> = {
  activa: "Publicado",
  borrador: "Borrador",
  archivada: "Archivado",
};

function Icono({ nombre, onClick, disabled, children }: {
  nombre: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <Button type="button" variant="ghost" size="icon" aria-label={nombre} title={nombre} disabled={disabled} onClick={onClick}>
      {children}
    </Button>
  );
}

export function BarraSuperior({
  estado,
  guardando,
  errorGuardado,
  onGuardarVersion,
  onActivar,
  activando,
  extra,
}: {
  estado: Diseno["estado"];
  guardando: boolean;
  errorGuardado?: Error | null;
  onGuardarVersion: (mensaje: string) => Promise<void>;
  onActivar: () => void;
  activando: boolean;
  extra?: ReactNode;
}) {
  const formato = useEditor((s) => s.escena?.lienzo.formato);
  const nSeleccion = useEditor((s) => s.seleccion.length);
  const sucio = useEditor((s) => s.sucio);
  const hayPasado = useEditor((s) => s.pasado.length > 0);
  const hayFuturo = useEditor((s) => s.futuro.length > 0);
  const st = useEditor.getState;

  const [abierto, setAbierto] = useState(false);
  const [mensaje, setMensaje] = useState("");
  const [enviando, setEnviando] = useState(false);

  if (!formato) return null;

  const textoEstado = guardando
    ? "Guardando…"
    : errorGuardado
      ? "No se pudo guardar"
      : sucio
        ? "Cambios sin guardar"
        : "Guardado";

  async function confirmar() {
    const m = mensaje.trim();
    if (!m) return;
    setEnviando(true);
    try {
      await onGuardarVersion(m);
      setAbierto(false);
      setMensaje("");
    } catch {
      // page.tsx ya avisó con un toast; el diálogo sigue abierto para reintentar.
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b pb-2">
      <div className="flex items-center gap-1" role="group" aria-label="Formato">
        {FORMATOS.map((f) => (
          <Button
            key={f.valor}
            type="button"
            size="sm"
            variant={formato === f.valor ? "default" : "outline"}
            aria-pressed={formato === f.valor}
            onClick={() => st().cambiarFormato(f.valor)}
          >
            {f.nombre}
          </Button>
        ))}
      </div>

      <div className="flex items-center">
        <Icono nombre="Deshacer" disabled={!hayPasado} onClick={() => st().deshacer()}>
          <Undo2 className="size-4" />
        </Icono>
        <Icono nombre="Rehacer" disabled={!hayFuturo} onClick={() => st().rehacer()}>
          <Redo2 className="size-4" />
        </Icono>
      </div>

      <div className="flex items-center">
        {ALINEAR.map(({ modo, nombre, Icono: Ico }) => (
          <Icono key={modo} nombre={nombre} disabled={nSeleccion === 0} onClick={() => st().alinear(modo)}>
            <Ico className="size-4" />
          </Icono>
        ))}
        <Icono nombre="Distribuir en horizontal" disabled={nSeleccion < 3} onClick={() => st().distribuir("h")}>
          <AlignHorizontalDistributeCenter className="size-4" />
        </Icono>
        <Icono nombre="Distribuir en vertical" disabled={nSeleccion < 3} onClick={() => st().distribuir("v")}>
          <AlignVerticalDistributeCenter className="size-4" />
        </Icono>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <span data-testid="estado-guardado" aria-live="polite" className="text-xs text-muted-foreground">
          {textoEstado}
        </span>
        <Badge data-testid="estado-diseno" variant={estado === "activa" ? "default" : "secondary"}>
          {ETIQUETA_ESTADO[estado]}
        </Badge>
        {extra}
        <Button type="button" size="sm" variant="outline" onClick={() => setAbierto(true)}>
          Guardar versión
        </Button>
        {estado !== "activa" && (
          <Button type="button" size="sm" disabled={activando} onClick={onActivar}>
            Activar
          </Button>
        )}
      </div>

      <Dialog open={abierto} onOpenChange={(v) => !enviando && setAbierto(v)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Guardar versión</DialogTitle>
            <DialogDescription>Un nombre corto para encontrarla después en el historial.</DialogDescription>
          </DialogHeader>
          <Input
            aria-label="Mensaje de la versión"
            value={mensaje}
            maxLength={120}
            autoFocus
            onChange={(e) => setMensaje(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void confirmar();
            }}
          />
          <DialogFooter>
            <Button type="button" disabled={enviando || mensaje.trim().length === 0} onClick={() => void confirmar()}>
              Guardar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
