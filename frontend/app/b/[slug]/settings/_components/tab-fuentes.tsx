"use client";

import { Separator } from "@/components/ui/separator";
import { FuentesLista } from "./fuentes-lista";
import { FotosPanel } from "./fotos-panel";
import { TemasLista } from "./temas-lista";

export function TabFuentes({ slug, puedeEditar }: { slug: string; puedeEditar: boolean }) {
  return (
    <div className="max-w-2xl space-y-6">
      <FuentesLista slug={slug} kind="imagen" titulo="Fuentes de imagen" puedeEditar={puedeEditar} />
      <Separator />
      <FuentesLista slug={slug} kind="info" titulo="Fuentes de información" puedeEditar={puedeEditar} />
      <Separator />
      <FotosPanel slug={slug} puedeEditar={puedeEditar} />
      <Separator />
      <TemasLista slug={slug} puedeEditar={puedeEditar} />
    </div>
  );
}
