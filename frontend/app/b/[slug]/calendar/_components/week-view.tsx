import { QueueCard } from "./queue-card";
import { SlotPlaceholder } from "./slot-placeholder";
import { claveDia, esHoy, formatDiaCorto } from "@/lib/calendario";
import { cn } from "@/lib/utils";
import type { QueueItem } from "@/hooks/use-queue";

export function WeekView({
  slug,
  dias,
  itemsByDay,
  slotsByDay,
  onItemClick,
}: {
  slug: string;
  dias: Date[];
  itemsByDay: Map<string, QueueItem[]>;
  slotsByDay: Map<string, string[]>;
  onItemClick: (id: number) => void;
}) {
  return (
    <div className="hidden gap-2 md:grid md:grid-cols-7">
      {dias.map((dia) => {
        const key = claveDia(dia);
        const items = itemsByDay.get(key) ?? [];
        const slots = slotsByDay.get(key) ?? [];
        return (
          <div key={key} className="flex min-h-40 flex-col gap-1.5 rounded-lg border p-1.5">
            <p
              className={cn(
                "px-0.5 text-xs font-medium text-muted-foreground",
                esHoy(dia) && "text-(--brand)"
              )}
            >
              {formatDiaCorto(dia)}
            </p>
            {items.map((item) => (
              <QueueCard key={item.id} item={item} onClick={() => onItemClick(item.id)} />
            ))}
            {slots.map((iso) => (
              <SlotPlaceholder key={iso} slug={slug} iso={iso} />
            ))}
            {items.length === 0 && slots.length === 0 && (
              <p className="px-0.5 text-[11px] text-muted-foreground/60">Sin actividad</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
