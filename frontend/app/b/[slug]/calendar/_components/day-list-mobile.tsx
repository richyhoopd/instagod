import { QueueCard } from "./queue-card";
import { SlotPlaceholder } from "./slot-placeholder";
import { claveDia, esHoy, formatDiaLargo } from "@/lib/calendario";
import { cn } from "@/lib/utils";
import type { QueueItem } from "@/hooks/use-queue";

export function DayListMobile({
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
    <div className="flex flex-col gap-3 md:hidden">
      {dias.map((dia) => {
        const key = claveDia(dia);
        const items = itemsByDay.get(key) ?? [];
        const slots = slotsByDay.get(key) ?? [];
        return (
          <div key={key} className="rounded-lg border p-2">
            <p
              className={cn(
                "mb-1.5 text-sm font-medium capitalize",
                esHoy(dia) && "text-(--brand)"
              )}
            >
              {formatDiaLargo(dia)}
            </p>
            <div className="space-y-1.5">
              {items.map((item) => (
                <QueueCard key={item.id} item={item} onClick={() => onItemClick(item.id)} />
              ))}
              {slots.map((iso) => (
                <SlotPlaceholder key={iso} slug={slug} iso={iso} />
              ))}
              {items.length === 0 && slots.length === 0 && (
                <p className="text-xs text-muted-foreground/60">Sin actividad</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
