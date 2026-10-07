import { raizDe, type Escena } from "./escena";

export type Vista = { zoom: number; x: number; y: number };

export const ZOOM_MIN = 0.1;
export const ZOOM_MAX = 4;

export function limitarZoom(z: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));
}

// El zoom que hace caber el lienzo completo, centrado y con margen.
export function encuadre(marco: { w: number; h: number }, lienzo: { w: number; h: number }, margen = 32): Vista {
  const zoom = limitarZoom(Math.min((marco.w - 2 * margen) / lienzo.w, (marco.h - 2 * margen) / lienzo.h));
  return {
    zoom,
    x: Math.round((marco.w - lienzo.w * zoom) / 2),
    y: Math.round((marco.h - lienzo.h * zoom) / 2),
  };
}

export function zoomEnPunto(v: Vista, nuevo: number, px: number, py: number): Vista {
  const zoom = limitarZoom(nuevo);
  return {
    zoom,
    x: px - ((px - v.x) / v.zoom) * zoom,
    y: py - ((py - v.y) / v.zoom) * zoom,
  };
}

// Lo que Selecto toca son hojas; lo que se selecciona es su raíz.
export function raicesSeleccionables(escena: Escena, ids: string[]): string[] {
  const m = new Map(escena.capas.map((c) => [c.id, c]));
  const fuera: string[] = [];
  for (const id of ids) {
    if (!m.has(id) || m.get(id)!.bloqueada) continue;
    const r = raizDe(escena, id);
    if (m.get(r)?.bloqueada || fuera.includes(r)) continue;
    fuera.push(r);
  }
  return fuera;
}

export function alternar(actual: string[], ids: string[]): string[] {
  return [...actual.filter((id) => !ids.includes(id)), ...ids.filter((id) => !actual.includes(id))];
}
