"use client";

import Link from "next/link";
import { useDroppable } from "@dnd-kit/core";
import { formatHora } from "@/lib/calendario";
import { cn } from "@/lib/utils";

export function SlotPlaceholder({ slug, iso }: { slug: string; iso: string }) {
  const { setNodeRef, isOver } = useDroppable({ id: `slot-${iso}` });

  return (
    <Link
      ref={setNodeRef}
      href={`/b/${slug}/create?slot=${encodeURIComponent(iso)}`}
      className={cn(
        "flex items-center justify-center gap-1 rounded-md border border-dashed border-muted-foreground/40 px-1.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-(--brand) hover:text-(--brand)",
        isOver && "border-(--brand) bg-(--brand)/10 text-(--brand)"
      )}
    >
      <span>+ crear</span>
      <span className="text-[10px] opacity-70">{formatHora(iso)}</span>
    </Link>
  );
}
