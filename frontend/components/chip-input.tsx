"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// Input de tags simple (hashtags, listas de handles, etc.): Enter/coma
// agrega, click en la x quita. Sin dependencias externas.
export function ChipInput({
  value,
  onChange,
  placeholder,
  disabled,
  className,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}) {
  const [borrador, setBorrador] = useState("");

  function agregar() {
    const v = borrador.trim().replace(/^,+|,+$/g, "");
    if (v && !value.includes(v)) onChange([...value, v]);
    setBorrador("");
  }

  function quitar(chip: string) {
    onChange(value.filter((c) => c !== chip));
  }

  return (
    <div
      className={cn(
        "flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-input bg-transparent px-2 py-1.5",
        disabled && "opacity-60",
        className
      )}
    >
      {value.map((chip) => (
        <span
          key={chip}
          className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs"
        >
          {chip}
          {!disabled && (
            <button
              type="button"
              onClick={() => quitar(chip)}
              aria-label={`Quitar ${chip}`}
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="size-3" />
            </button>
          )}
        </span>
      ))}
      {!disabled && (
        <Input
          value={borrador}
          onChange={(e) => setBorrador(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              agregar();
            } else if (e.key === "Backspace" && !borrador && value.length > 0) {
              onChange(value.slice(0, -1));
            }
          }}
          onBlur={agregar}
          placeholder={value.length === 0 ? placeholder : undefined}
          className="h-6 flex-1 border-0 p-0 shadow-none focus-visible:ring-0"
        />
      )}
    </div>
  );
}
