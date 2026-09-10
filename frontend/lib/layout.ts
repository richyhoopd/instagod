// Tipos y funciones puras del layout de un diseño (Task 2 del backend,
// `src/plantillas/layout.py`). Sin dependencias de React: el lienzo del
// editor y cualquier prueba manual las usan igual.

export type TipoCapa = "texto" | "imagen" | "caja";

export type Capa = {
  id: string;
  tipo: TipoCapa;
  x: number;
  y: number;
  w: number;
  h: number;
  z: number;
  rot: number;
  opacidad: number;
  campo?: string;
  texto?: string;
  archivo?: string;
  fuente?: string;
  tam?: number;
  peso?: number;
  color?: string;
  alinear?: "izq" | "centro" | "der";
  vertical?: "arriba" | "centro" | "abajo";
  interlinea?: number;
  mayusculas?: boolean;
  auto?: boolean;
  resaltar?: boolean;
  ajuste?: "cover" | "contain";
  anclaje?: string;
  radio?: number;
};

export type Layout = {
  v: 1;
  lienzo: { fondo: string };
  guias: { cols: number; filas: number; iman: number };
  capas: Capa[];
};

export const LIENZO: Record<string, { ancho: number; alto: number }> = {
  "4:5": { ancho: 1080, alto: 1350 },
  "9:16": { ancho: 1080, alto: 1920 },
};

/** Pega el valor a la rejilla cuando pasa cerca. Fuera del imán, movimiento libre. */
export function imantar(v: number, paso: number, iman: number): number {
  const pegado = Math.round(v / paso) * paso;
  return Math.abs(pegado - v) <= iman ? pegado : Math.round(v);
}

/** Ninguna capa puede salirse del lienzo: lo de afuera no sale en la foto. */
export function dentro(capa: Capa, ancho: number, alto: number): Capa {
  const w = Math.min(Math.max(1, Math.round(capa.w)), ancho);
  const h = Math.min(Math.max(1, Math.round(capa.h)), alto);
  return {
    ...capa,
    w,
    h,
    x: Math.min(Math.max(0, Math.round(capa.x)), ancho - w),
    y: Math.min(Math.max(0, Math.round(capa.y)), alto - h),
  };
}

/** Un id legible y único; el backend exige ^[a-z][a-z0-9_-]{0,31}$ */
function idLibre(base: string, layout: Layout): string {
  const usados = new Set(layout.capas.map((c) => c.id));
  let n = 1;
  while (usados.has(`${base}${n}`)) n += 1;
  return `${base}${n}`;
}

export function capaNueva(tipo: TipoCapa, layout: Layout): Capa {
  const z = Math.min(999, Math.max(0, ...layout.capas.map((c) => c.z)) + 1);
  const comun = { x: 120, y: 120, z, rot: 0, opacidad: 1, radio: 0 };
  if (tipo === "texto")
    return {
      ...comun,
      id: idLibre("texto", layout),
      tipo,
      w: 700,
      h: 180,
      texto: "Escribe aquí",
      // "Poppins-Bold" coincide con layout.vacio() del backend: el catálogo
      // real trae el peso dentro del nombre de la familia, "Poppins" a
      // secas no existe y no pasa la validación.
      fuente: layout.capas.find((c) => c.fuente)?.fuente ?? "Poppins-Bold",
      tam: 48,
      peso: 700,
      color: "#111111",
      alinear: "centro",
      vertical: "centro",
      interlinea: 1.2,
      mayusculas: false,
      auto: false,
    };
  if (tipo === "imagen")
    return {
      ...comun,
      id: idLibre("imagen", layout),
      tipo,
      w: 400,
      h: 400,
      ajuste: "cover",
      anclaje: "center",
    };
  return { ...comun, id: idLibre("caja", layout), tipo, w: 400, h: 8, color: "marca" };
}

export const conCapa = (layout: Layout, capa: Capa): Layout => ({
  ...layout,
  capas: layout.capas.some((c) => c.id === capa.id)
    ? layout.capas.map((c) => (c.id === capa.id ? capa : c))
    : [...layout.capas, capa],
});

export const sinCapa = (layout: Layout, id: string): Layout => ({
  ...layout,
  capas: layout.capas.filter((c) => c.id !== id),
});
