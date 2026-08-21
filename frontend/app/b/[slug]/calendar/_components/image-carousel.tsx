export function ImageCarousel({ imagenes }: { imagenes: string[] }) {
  if (imagenes.length === 0) {
    return (
      <div className="flex h-56 items-center justify-center rounded-lg bg-muted text-sm text-muted-foreground">
        Sin imagen
      </div>
    );
  }

  return (
    <div className="flex max-h-[60vh] snap-x snap-mandatory gap-2 overflow-x-auto rounded-lg bg-muted/40">
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
  );
}
