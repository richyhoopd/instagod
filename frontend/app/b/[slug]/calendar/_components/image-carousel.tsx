"use client";

import { useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ImageCarousel({
  imagenes,
  onIndexChange,
}: {
  imagenes: string[];
  onIndexChange?: (i: number) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [idx, setIdx] = useState(0);

  if (imagenes.length === 0) {
    return (
      <div className="flex h-56 items-center justify-center rounded-lg bg-muted text-sm text-muted-foreground">
        Sin imagen
      </div>
    );
  }

  // Índice = slide cuyo offsetLeft queda más cerca del scroll actual (los
  // slides llevan gap, así que scrollLeft/clientWidth no alcanza).
  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    let mejor = 0;
    let dist = Infinity;
    Array.from(el.children).forEach((hijo, i) => {
      const d = Math.abs((hijo as HTMLElement).offsetLeft - el.scrollLeft);
      if (d < dist) {
        dist = d;
        mejor = i;
      }
    });
    if (mejor !== idx) {
      setIdx(mejor);
      onIndexChange?.(mejor);
    }
  }

  function irA(i: number) {
    const el = scrollRef.current;
    const hijo = el?.children[i] as HTMLElement | undefined;
    if (!el || !hijo) return;
    el.scrollTo({ left: hijo.offsetLeft, behavior: "smooth" });
  }

  return (
    <div className="relative">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex max-h-[60vh] snap-x snap-mandatory gap-2 overflow-x-auto rounded-lg bg-muted/40"
      >
        {imagenes.map((url, i) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={`${url}-${i}`}
            src={url}
            alt={`Imagen ${i + 1} de ${imagenes.length}`}
            className="max-h-[60vh] w-full shrink-0 snap-center rounded-lg object-contain"
          />
        ))}
      </div>
      {imagenes.length > 1 && (
        <>
          <Button
            type="button"
            size="icon"
            variant="secondary"
            aria-label="Slide anterior"
            disabled={idx === 0}
            onClick={() => irA(idx - 1)}
            className="absolute left-2 top-1/2 size-8 -translate-y-1/2 rounded-full opacity-80 shadow disabled:opacity-30"
          >
            <ChevronLeft />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="secondary"
            aria-label="Slide siguiente"
            disabled={idx === imagenes.length - 1}
            onClick={() => irA(idx + 1)}
            className="absolute right-2 top-1/2 size-8 -translate-y-1/2 rounded-full opacity-80 shadow disabled:opacity-30"
          >
            <ChevronRight />
          </Button>
          <span className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full bg-black/60 px-2 py-0.5 text-xs text-white">
            {idx + 1}/{imagenes.length}
          </span>
        </>
      )}
    </div>
  );
}
