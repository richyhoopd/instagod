"use client";

import type { ReactNode } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type Pestana = { id: string; etiqueta: string; contenido: ReactNode };

export function PanelLateral({ pestanas }: { pestanas: Pestana[] }) {
  if (!pestanas.length) return null;
  return (
    <Tabs defaultValue={pestanas[0].id} className="flex h-full min-h-0 flex-col gap-0">
      <TabsList className="m-2 w-[calc(100%-1rem)]">
        {pestanas.map((p) => (
          <TabsTrigger key={p.id} value={p.id} className="flex-1">
            {p.etiqueta}
          </TabsTrigger>
        ))}
      </TabsList>
      {pestanas.map((p) => (
        <TabsContent key={p.id} value={p.id} className="min-h-0 flex-1 overflow-y-auto">
          {p.contenido}
        </TabsContent>
      ))}
    </Tabs>
  );
}
