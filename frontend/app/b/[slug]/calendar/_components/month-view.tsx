import { QueueCard } from "./queue-card";
import { SlotPlaceholder } from "./slot-placeholder";
import { claveDia, esHoy, esMismoMes } from "@/lib/calendario";
import { cn } from "@/lib/utils";
import type { QueueItem } from "@/hooks/use-queue";

const MAX_ITEMS = 3;
const MAX_SLOTS = 2;

export function MonthView({
  slug,
  dias,
  ancla,
  itemsByDay,
  slotsByDay,
  onItemClick,
}: {
  slug: string;
  dias: Date[];
  ancla: Date;
  itemsByDay: Map<string, QueueItem[]>;
  slotsByDay: Map<string, string[]>;
  onItemClick: (id: number) => void;
}) {
  return (
    <div className="hidden grid-cols-7 gap-1.5 md:grid">
      {dias.map((dia) => {
        const key = claveDia(dia);
        const items = itemsByDay.get(key) ?? [];
        const slots = slotsByDay.get(key) ?? [];
        const enMes = esMismoMes(dia, ancla);
        return (
          <div
            key={key}
            className={cn(
              "flex min-h-26 flex-col gap-1 rounded-lg border p-1",
              !enMes && "opacity-40"
            )}
          >
            <p
              className={cn(
                "px-0.5 text-[11px] font-medium text-muted-foreground",
                esHoy(dia) && "text-(--brand)"
              )}
            >
              {dia.getDate()}
            </p>
            {items.slice(0, MAX_ITEMS).map((item) => (
              <QueueCard key={item.id} item={item} onClick={() => onItemClick(item.id)} />
            ))}
            {items.length > MAX_ITEMS && (
              <p className="px-0.5 text-[10px] text-muted-foreground">
                +{items.length - MAX_ITEMS} más
              </p>
            )}
            {slots.slice(0, MAX_SLOTS).map((iso) => (
              <SlotPlaceholder key={iso} slug={slug} iso={iso} />
            ))}
          </div>
        );
      })}
    </div>
  );
}
