"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { BrandCard } from "@/components/brand-card";
import { NuevaMarcaDialog } from "@/components/nueva-marca-dialog";
import { useBrands } from "@/hooks/use-brands";
import { useMe } from "@/hooks/use-me";

export default function BrandsPage() {
  const { data: me } = useMe();
  const { data: marcas, isLoading, isError } = useBrands();

  return (
    <div className="space-y-6 py-8">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Marcas</h1>
          <p className="text-sm text-muted-foreground">Elige una marca para administrarla.</p>
        </div>
        {me?.is_admin && <NuevaMarcaDialog />}
      </div>

      {isLoading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-32 rounded-xl" />
          ))}
        </div>
      )}

      {isError && (
        <p className="text-sm text-destructive">No se pudieron cargar las marcas.</p>
      )}

      {marcas && marcas.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Todavía no tienes marcas asignadas. Pide a un administrador que te agregue.
        </p>
      )}

      {marcas && marcas.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {marcas.map((marca) => (
            <BrandCard key={marca.id} marca={marca} />
          ))}
        </div>
      )}
    </div>
  );
}
