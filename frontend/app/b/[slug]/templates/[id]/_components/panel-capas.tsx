"use client";

import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Eye, EyeOff, Film, Folder, GripVertical, Image as IconoImagen, Lock, Shapes, Square, Type, Unlock } from "lucide-react";
import { useRef, useState } from "react";
import { expandir, opsReordenar } from "@/lib/edicion";
import { padreDe, type Capa, type Escena, type Op, type TipoCapa } from "@/lib/escena";
import { alternar } from "@/lib/vista";
import { cn } from "@/lib/utils";
import { useEditor } from "@/stores/editor";

export type Fila = {
  id: string;
  nombre: string;
  tipo: TipoCapa;
  nivel: number;
  padre: string | null;
  oculta: boolean;
  bloqueada: boolean;
};

const ICONO: Record<TipoCapa, typeof Type> = {
  text: Type,
  image: IconoImagen,
  video: Film,
  shape: Square,
  svg: Shapes,
  group: Folder,
};

function zEfectiva(escena: Escena, c: Capa): number {
  if (c.tipo !== "group") return c.z;
  const zs = expandir(escena, [c.id]).map((id) => escena.capas.find((x) => x.id === id)?.z ?? 0);
  return zs.length ? Math.max(...zs) : c.z;
}

function hermanos(escena: Escena, padre: string | null): Capa[] {
  const m = new Map(escena.capas.map((c) => [c.id, c]));
  const lista =
    padre === null
      ? escena.capas.filter((c) => padreDe(escena, c.id) === null)
      : ((m.get(padre) as Extract<Capa, { tipo: "group" }>).hijos.map((id) => m.get(id)).filter(Boolean) as Capa[]);
  return [...lista].sort((a, b) => zEfectiva(escena, b) - zEfectiva(escena, a));
}

export function filasDeCapas(escena: Escena): Fila[] {
  const filas: Fila[] = [];
  const bajar = (padre: string | null, nivel: number) => {
    for (const c of hermanos(escena, padre)) {
      filas.push({ id: c.id, nombre: c.nombre, tipo: c.tipo, nivel, padre, oculta: c.oculta, bloqueada: c.bloqueada });
      if (c.tipo === "group") bajar(c.id, nivel + 1);
    }
  };
  bajar(null, 0);
  return filas;
}

export function reordenarFilas(escena: Escena, activo: string, sobre: string): Op[] | null {
  const padre = padreDe(escena, activo);
  if (padre !== padreDe(escena, sobre)) return null;
  const orden = hermanos(escena, padre).map((c) => c.id);
  const de = orden.indexOf(activo);
  const a = orden.indexOf(sobre);
  if (de < 0 || a < 0 || de === a) return null;
  return opsReordenar(escena, arrayMove(orden, de, a));
}

function FilaCapa({ fila, elegida }: { fila: Fila; elegida: boolean }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: fila.id });
  const [renombrando, setRenombrando] = useState(false);
  const [valor, setValor] = useState(fila.nombre);
  const cancelado = useRef(false);
  const Icono = ICONO[fila.tipo];

  const set = (ruta: string, v: unknown, etiqueta: string) =>
    useEditor.getState().aplicar([{ op: "set", capa: fila.id, ruta, valor: v }], etiqueta);

  const renombrar = () => {
    if (cancelado.current) return;
    const n = valor.trim();
    if (n && n !== fila.nombre) set("nombre", n, "Renombrar");
    setRenombrando(false);
  };

  const empezarRenombre = () => {
    cancelado.current = false;
    setValor(fila.nombre);
    setRenombrando(true);
  };

  return (
    <div
      ref={setNodeRef}
      data-fila={fila.id}
      data-seleccionada={elegida || undefined}
      role="option"
      aria-selected={elegida}
      tabIndex={0}
      style={{ transform: CSS.Transform.toString(transform), transition, paddingLeft: 4 + fila.nivel * 12 }}
      className={cn(
        "group flex h-8 items-center gap-1 rounded-sm pr-1 text-sm select-none",
        elegida ? "bg-primary/10 text-foreground" : "hover:bg-muted",
        fila.oculta && "opacity-50",
        isDragging && "z-10 bg-background shadow-sm",
      )}
      onClick={(ev) => {
        const st = useEditor.getState();
        st.seleccionar(ev.shiftKey ? alternar(st.seleccion, [fila.id]) : [fila.id]);
      }}
      onKeyDown={(ev) => {
        if (ev.target !== ev.currentTarget) return;
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          const st = useEditor.getState();
          st.seleccionar(ev.shiftKey ? alternar(st.seleccion, [fila.id]) : [fila.id]);
        } else if (ev.key === "F2") {
          ev.preventDefault();
          empezarRenombre();
        }
      }}
    >
      <button
        type="button"
        aria-label={`Arrastrar ${fila.nombre}`}
        className="cursor-grab text-muted-foreground opacity-0 group-hover:opacity-100 focus:opacity-100"
        onClick={(ev) => ev.stopPropagation()}
        {...attributes}
        {...listeners}
      >
        <GripVertical className="size-3.5" />
      </button>
      <Icono className="size-3.5 shrink-0 text-muted-foreground" />
      {renombrando ? (
        <input
          aria-label="Nombre de la capa"
          autoFocus
          maxLength={60}
          value={valor}
          className="h-6 min-w-0 flex-1 rounded-sm border bg-background px-1 text-sm"
          onClick={(ev) => ev.stopPropagation()}
          onChange={(ev) => setValor(ev.target.value)}
          onBlur={renombrar}
          onKeyDown={(ev) => {
            ev.stopPropagation();
            if (ev.key === "Enter") {
              renombrar();
              // El blur del desmontaje no debe registrar un segundo paso.
              cancelado.current = true;
            }
            if (ev.key === "Escape") {
              cancelado.current = true;
              setRenombrando(false);
            }
          }}
        />
      ) : (
        <span
          className="min-w-0 flex-1 truncate"
          onDoubleClick={(ev) => {
            ev.stopPropagation();
            empezarRenombre();
          }}
        >
          {fila.nombre}
        </span>
      )}
      <button
        type="button"
        aria-label={`${fila.oculta ? "Mostrar" : "Ocultar"} ${fila.nombre}`}
        className="text-muted-foreground hover:text-foreground"
        onClick={(ev) => {
          ev.stopPropagation();
          set("oculta", !fila.oculta, fila.oculta ? "Mostrar" : "Ocultar");
        }}
      >
        {fila.oculta ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
      </button>
      {/* El lienzo y el store bloquean por hoja; un candado de grupo no tendría efecto. */}
      {fila.tipo !== "group" && <button
        type="button"
        aria-label={`${fila.bloqueada ? "Desbloquear" : "Bloquear"} ${fila.nombre}`}
        className={cn(
          "text-muted-foreground hover:text-foreground",
          !fila.bloqueada && "opacity-0 group-hover:opacity-100 focus:opacity-100",
        )}
        onClick={(ev) => {
          ev.stopPropagation();
          set("bloqueada", !fila.bloqueada, fila.bloqueada ? "Desbloquear" : "Bloquear");
        }}
      >
        {fila.bloqueada ? <Lock className="size-3.5" /> : <Unlock className="size-3.5" />}
      </button>}
    </div>
  );
}

export function PanelCapas() {
  const escena = useEditor((s) => s.escena);
  const seleccion = useEditor((s) => s.seleccion);
  const sensores = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  if (!escena) return null;
  const filas = filasDeCapas(escena);

  const soltar = ({ active, over }: DragEndEvent) => {
    const e = useEditor.getState().escena;
    if (!e || !over || active.id === over.id) return;
    const ops = reordenarFilas(e, String(active.id), String(over.id));
    if (ops?.length) useEditor.getState().aplicar(ops, "Reordenar capas");
  };

  if (!filas.length) return <p className="p-3 text-sm text-muted-foreground">Sin capas. Agrega un texto o una forma.</p>;

  return (
    <DndContext sensors={sensores} collisionDetection={closestCenter} onDragEnd={soltar}>
      <SortableContext items={filas.map((f) => f.id)} strategy={verticalListSortingStrategy}>
        <div role="listbox" aria-label="Capas" aria-multiselectable className="flex flex-col gap-0.5 p-1">
          {filas.map((f) => (
            <FilaCapa key={f.id} fila={f} elegida={seleccion.includes(f.id)} />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
