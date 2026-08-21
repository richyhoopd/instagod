"use client";

import { useRef } from "react";
import { toast } from "sonner";
import { Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { NoDisponible } from "@/components/no-disponible";
import { ApiError } from "@/lib/api";
import { usePhotos, useSubirFotos, useBorrarFoto } from "@/hooks/use-photos";

export function FotosPanel({ slug, puedeEditar }: { slug: string; puedeEditar: boolean }) {
  const photosQuery = usePhotos(slug);
  const subir = useSubirFotos(slug);
  const borrar = useBorrarFoto(slug);
  const inputRef = useRef<HTMLInputElement>(null);

  if (photosQuery.isLoading) {
    return <Skeleton className="h-40 w-full" />;
  }

  if (photosQuery.isError) {
    if (photosQuery.error.status === 404) {
      return <NoDisponible mensaje="La galería de fotos propias todavía no está disponible en este servidor." />;
    }
    return <NoDisponible mensaje={photosQuery.error.detalle} />;
  }

  const fotos = photosQuery.data ?? [];

  async function onFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    try {
      await subir.mutateAsync(Array.from(files));
      toast.success("Fotos subidas");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudieron subir las fotos");
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function borrarFoto(nombre: string) {
    try {
      await borrar.mutateAsync(nombre);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo borrar la foto");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Fotos propias</h3>
        {puedeEditar && (
          <>
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => onFiles(e.target.files)}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => inputRef.current?.click()}
              disabled={subir.isPending}
            >
              <Upload className="size-4" />
              {subir.isPending ? "Subiendo..." : "Subir"}
            </Button>
          </>
        )}
      </div>
      {fotos.length === 0 && <p className="text-sm text-muted-foreground">Sin fotos propias.</p>}
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
        {fotos.map((foto) => (
          <div key={foto.nombre} className="group relative aspect-square overflow-hidden rounded-lg border bg-muted">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`/api/brands/${slug}/files/fotos/${foto.nombre}`}
              alt={foto.nombre}
              className="size-full object-cover"
            />
            {puedeEditar && (
              <button
                type="button"
                onClick={() => borrarFoto(foto.nombre)}
                className="absolute top-1 right-1 rounded-full bg-black/60 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100"
                aria-label={`Borrar ${foto.nombre}`}
              >
                <Trash2 className="size-3.5" />
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
