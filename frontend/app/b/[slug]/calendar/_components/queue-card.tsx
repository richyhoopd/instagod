"use client";

import { useDraggable } from "@dnd-kit/core";
import { Images } from "lucide-react";
import { EstadoBadge } from "@/components/estado-badge";
import { contarImagenes, primeraImagen } from "@/lib/imagenes";
import { formatHora } from "@/lib/calendario";
import { cn } from "@/lib/utils";
import type { QueueItem } from "@/hooks/use-queue";
import type { Estado } from "@/lib/estados";

const ARRASTRABLES: Estado[] = ["pendiente", "programado", "error"];

export function QueueCard({ item, onClick }: { item: QueueItem; onClick: () => void }) {
  const arrastrable = ARRASTRABLES.includes(item.estado);
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `item-${item.id}`,
    disabled: !arrastrable,
  });
  const thumb = primeraImagen(item.imagen_url);
  const n = contarImagenes(item.imagen_url);
  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
    : undefined;

  return (
    <button
      ref={setNodeRef}
      type="button"
      style={style}
      {...(arrastrable ? { ...listeners, ...attributes } : {})}
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-1.5 rounded-md border bg-card p-1.5 text-left shadow-sm transition-shadow hover:shadow touch-none",
        isDragging && "z-10 opacity-70 shadow-lg",
        arrastrable && "cursor-grab active:cursor-grabbing"
      )}
    >
      <div className="relative size-8 shrink-0 overflow-hidden rounded bg-muted">
        {thumb && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumb} alt="" className="size-full object-cover" />
        )}
        {n > 1 && (
          <span className="absolute right-0 bottom-0 flex items-center gap-0.5 rounded-tl bg-black/60 px-0.5 text-[8px] text-white">
            <Images className="size-2" />
            {n}
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        {item.scheduled_datetime && (
          <p className="truncate text-[11px] font-medium">{formatHora(item.scheduled_datetime)}</p>
        )}
        <p className="truncate text-[11px] text-muted-foreground">
          {item.caption || item.tema_semilla || "(sin caption)"}
        </p>
      </div>
      <EstadoBadge estado={item.estado} className="h-4 shrink-0 px-1 py-0 text-[9px]" />
    </button>
  );
}
