"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { toast } from "sonner";
import { CalendarToolbar, type Vista } from "./_components/calendar-toolbar";
import { WeekView } from "./_components/week-view";
import { MonthView } from "./_components/month-view";
import { DayListMobile } from "./_components/day-list-mobile";
import { QueueDrawer } from "./_components/queue-drawer";
import { QueueCard } from "./_components/queue-card";
import { ApiError } from "@/lib/api";
import { useEditarQueue, useQueue, useSlotsProximos, type QueueItem } from "@/hooks/use-queue";
import {
  claveDiaIso,
  diasMes,
  diasSemana,
  esMismoMes,
  sumarDias,
  sumarMeses,
} from "@/lib/calendario";

// Tope de la API para slots/proximos (constraints.md); cubre varios dias de
// huecos libres pero no un mes entero si la marca tiene muchos slots/dia.
const N_SLOTS = 50;

export default function CalendarPage() {
  const { slug } = useParams<{ slug: string }>();
  const qc = useQueryClient();
  const [vista, setVista] = useState<Vista>("semana");
  const [ancla, setAncla] = useState(() => new Date());
  const [openQid, setOpenQid] = useState<number | null>(null);

  const dias = useMemo(
    () => (vista === "semana" ? diasSemana(ancla) : diasMes(ancla)),
    [vista, ancla]
  );
  const diasVisibles = useMemo(
    () => (vista === "semana" ? dias : dias.filter((d) => esMismoMes(d, ancla))),
    [dias, vista, ancla]
  );

  // Colchon de un dia por si la zona horaria del navegador difiere de la de
  // la marca; el bucketing real por dia se hace en el cliente con la propia
  // scheduled_datetime de cada fila.
  const desde = sumarDias(dias[0], -1).toISOString();
  const hasta = sumarDias(dias[dias.length - 1], 2).toISOString();

  const queueQuery = useQueue(slug, { desde, hasta });
  const pendientesQuery = useQueue(slug, { estado: "pendiente" });
  const slotsQuery = useSlotsProximos(slug, N_SLOTS);
  const editar = useEditarQueue(slug);

  const itemsByDay = useMemo(() => {
    const map = new Map<string, QueueItem[]>();
    for (const item of queueQuery.data ?? []) {
      const key = claveDiaIso(item.scheduled_datetime);
      if (!key) continue;
      const arr = map.get(key) ?? [];
      arr.push(item);
      map.set(key, arr);
    }
    for (const arr of map.values()) {
      arr.sort((a, b) => (a.scheduled_datetime ?? "").localeCompare(b.scheduled_datetime ?? ""));
    }
    return map;
  }, [queueQuery.data]);

  const slotsByDay = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const iso of slotsQuery.data ?? []) {
      const key = claveDiaIso(iso);
      if (!key) continue;
      const arr = map.get(key) ?? [];
      arr.push(iso);
      map.set(key, arr);
    }
    return map;
  }, [slotsQuery.data]);

  const sinProgramar = useMemo(
    () => (pendientesQuery.data ?? []).filter((i) => !i.scheduled_datetime),
    [pendientesQuery.data]
  );

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over) return;
    const activeId = String(active.id);
    const overId = String(over.id);
    if (!activeId.startsWith("item-") || !overId.startsWith("slot-")) return;

    const itemId = Number(activeId.slice("item-".length));
    const targetIso = overId.slice("slot-".length);
    const todos = [...(queueQuery.data ?? []), ...(pendientesQuery.data ?? [])];
    const item = todos.find((i) => i.id === itemId);
    if (!item || item.scheduled_datetime === targetIso) return;

    const previas = qc.getQueryCache().findAll({ queryKey: ["queue", slug] });
    const snapshot = previas.map((q) => ({ key: q.queryKey, data: q.state.data }));

    qc.setQueriesData<QueueItem[]>({ queryKey: ["queue", slug] }, (old) =>
      old?.map((i) => (i.id === itemId ? { ...i, scheduled_datetime: targetIso } : i))
    );

    editar.mutate(
      { qid: itemId, scheduled_datetime: targetIso },
      {
        onSuccess: () => toast.success("Reprogramado"),
        onError: (err) => {
          snapshot.forEach(({ key, data }) => qc.setQueryData(key, data));
          if (err instanceof ApiError && err.status === 409) {
            toast.error("Ese horario ya está ocupado");
          } else {
            toast.error(err instanceof ApiError ? err.detalle : "No se pudo reprogramar");
          }
        },
      }
    );
  }

  function irAnterior() {
    setAncla((a) => (vista === "semana" ? sumarDias(a, -7) : sumarMeses(a, -1)));
  }
  function irSiguiente() {
    setAncla((a) => (vista === "semana" ? sumarDias(a, 7) : sumarMeses(a, 1)));
  }
  function irHoy() {
    setAncla(new Date());
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Calendario</h1>

      <CalendarToolbar
        vista={vista}
        onVistaChange={setVista}
        ancla={ancla}
        onAnterior={irAnterior}
        onSiguiente={irSiguiente}
        onHoy={irHoy}
      />

      {sinProgramar.length > 0 && (
        <div className="rounded-lg border border-dashed p-3">
          <p className="mb-2 text-sm font-medium text-muted-foreground">
            Pendientes sin horario — arrástralos a un espacio libre del calendario
          </p>
          <div className="flex flex-wrap gap-2">
            {sinProgramar.map((item) => (
              <div key={item.id} className="w-48">
                <QueueCard item={item} onClick={() => setOpenQid(item.id)} />
              </div>
            ))}
          </div>
        </div>
      )}

      <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
        {vista === "semana" ? (
          <WeekView
            slug={slug}
            dias={dias}
            itemsByDay={itemsByDay}
            slotsByDay={slotsByDay}
            onItemClick={setOpenQid}
          />
        ) : (
          <MonthView
            slug={slug}
            dias={dias}
            ancla={ancla}
            itemsByDay={itemsByDay}
            slotsByDay={slotsByDay}
            onItemClick={setOpenQid}
          />
        )}
        <DayListMobile
          slug={slug}
          dias={diasVisibles}
          itemsByDay={itemsByDay}
          slotsByDay={slotsByDay}
          onItemClick={setOpenQid}
        />
      </DndContext>

      <QueueDrawer slug={slug} qid={openQid} onOpenChange={(open) => !open && setOpenQid(null)} />
    </div>
  );
}
