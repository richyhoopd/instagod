// Estados derivados de la cola (src/cola.py::estado_de), 8 posibles.
export const ESTADOS = [
  "generando",
  "borrador",
  "pendiente",
  "programado",
  "publicado",
  "rechazado",
  "error",
  "descartado",
] as const;

export type Estado = (typeof ESTADOS)[number];

export const ESTADO_LABELS: Record<Estado, string> = {
  generando: "Generando",
  borrador: "Borrador",
  pendiente: "Pendiente",
  programado: "Programado",
  publicado: "Publicado",
  rechazado: "Rechazado",
  error: "Error",
  descartado: "Descartado",
};

// Colores de fila (constraints.md): generando gris animado, borrador gris,
// pendiente ámbar, programado azul, publicado verde, rechazado rojo tenue,
// error rojo, descartado gris tachado.
export const ESTADO_CLASSES: Record<Estado, string> = {
  generando:
    "bg-neutral-200 text-neutral-600 animate-pulse dark:bg-neutral-800 dark:text-neutral-400",
  borrador: "bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
  pendiente: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-400",
  programado: "bg-blue-100 text-blue-800 dark:bg-blue-500/15 dark:text-blue-400",
  publicado: "bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-400",
  rechazado: "bg-red-50 text-red-600/80 dark:bg-red-500/10 dark:text-red-400/80",
  error: "bg-red-100 text-red-800 dark:bg-red-500/20 dark:text-red-400",
  descartado:
    "bg-neutral-200 text-neutral-500 line-through dark:bg-neutral-800 dark:text-neutral-500",
};

export function esEstado(v: string): v is Estado {
  return (ESTADOS as readonly string[]).includes(v);
}
