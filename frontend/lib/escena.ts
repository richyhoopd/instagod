import { produce, type Draft } from "immer";

// Escena v2: el mismo esquema que valida src/plantillas/escena.py (plan 1).
// Los nombres de campo NO se traducen: el backend los lee tal cual.

export type Formato = "4x5" | "1x1" | "9x16";
export const FORMATOS: Record<Formato, { w: number; h: number }> = {
  "4x5": { w: 1080, h: 1350 },
  "1x1": { w: 1080, h: 1080 },
  "9x16": { w: 1080, h: 1920 },
};
export const ASPECTO_DE_FORMATO: Record<Formato, "4:5" | "1:1" | "9:16"> = {
  "4x5": "4:5",
  "1x1": "1:1",
  "9x16": "9:16",
};
export const MAX_CAPAS = 80;
export const MAX_TEXTO = 1000;
export const MAX_SPANS = 50;
export const ID_RE = /^[a-z][a-z0-9_-]{0,31}$/;

export type Anclaje = "top" | "center" | "bottom";
export type Fondo = { tipo: "color" | "gradiente" | "imagen"; valor: string };
export type Tokens = { colores: Record<string, string>; fuente?: string };
export type Guias = { cols: number; filas: number; iman: boolean };
export type Span = { desde: number; hasta: number; color: string };

type CapaBase = {
  id: string;
  nombre: string;
  x: number;
  y: number;
  w: number;
  h: number;
  rot: number;
  opacity: number;
  z: number;
  bloqueada: boolean;
  oculta: boolean;
  anclaje: Anclaje;
};

export type EstiloTexto = {
  fontFamily: string;
  fontWeight: number;
  fontSize: number;
  lineHeight: number;
  letterSpacing?: string;
  color: string;
  textAlign: "left" | "center" | "right" | "justify";
  textWrap?: "wrap" | "balance" | "pretty" | "nowrap";
  verticalAlign?: "top" | "center" | "bottom";
  textTransform?: "none" | "uppercase";
  spans?: Span[];
};
export type CapaTexto = CapaBase & {
  tipo: "text";
  texto: string;
  campo?: string | null;
  auto?: boolean;
  resaltar?: boolean;
  estilo: EstiloTexto;
};

export type FuenteAsset = {
  proveedor?: string;
  autor?: string | null;
  licencia?: string | null;
  url?: string | null;
  ig_handle?: string | null;
};
type EstiloMedio = { objectPosition?: string; filter?: string; mixBlendMode?: string };
export type CapaImagen = CapaBase & {
  tipo: "image";
  src: string | null;
  campo?: string | null;
  recorte?: { x: number; y: number; w: number; h: number } | null;
  ajuste: "cover" | "contain";
  mascara: string; // "none" | "circle" | "rounded:N"
  estilo: EstiloMedio;
  fuente_asset?: FuenteAsset | null;
};
export type CapaVideo = Omit<CapaImagen, "tipo"> & { tipo: "video"; poster?: string | null };
export type CapaForma = CapaBase & {
  tipo: "shape";
  forma: "rect" | "ellipse";
  estilo: {
    fill: string;
    radius?: number;
    borderWidth?: number;
    borderColor?: string;
    filter?: string;
    mixBlendMode?: string;
  };
};
export type CapaSvg = CapaBase & {
  tipo: "svg";
  src: string;
  ajuste: "cover" | "contain";
  estilo: { filter?: string; mixBlendMode?: string };
  fuente_asset?: FuenteAsset | null;
};
export type CapaGrupo = CapaBase & { tipo: "group"; hijos: string[]; estilo: Record<string, never> };

export type Capa = CapaTexto | CapaImagen | CapaVideo | CapaForma | CapaSvg | CapaGrupo;
export type TipoCapa = Capa["tipo"];

export type Escena = {
  v: 2;
  lienzo: { w: number; h: number; formato: Formato; fondo: Fondo };
  tokens: Tokens;
  capas: Capa[];
  guias?: Guias;
};

export type Op =
  | { op: "set"; capa: string; ruta: string; valor: unknown }
  | { op: "add"; capa: Capa; indice?: number }
  | { op: "del"; capa: string };

export class OpInvalida extends Error {}

export type Caja = { x: number; y: number; w: number; h: number };

const INTOCABLES = new Set(["id", "tipo"]);
const PELIGROSAS = new Set(["__proto__", "prototype", "constructor"]);

// Aplica una op sobre un borrador de immer. Lanza OpInvalida y deja que
// produce() descarte el borrador completo: las ops son atómicas.
export function aplicarEnBorrador(d: Draft<Escena>, op: Op): void {
  if (op.op === "set") {
    const capa = d.capas.find((c) => c.id === op.capa);
    if (!capa) throw new OpInvalida(`set: no existe la capa «${op.capa}»`);
    const partes = op.ruta.split(".");
    if (partes.some((p) => p === "" || PELIGROSAS.has(p))) throw new OpInvalida(`set: ruta inválida «${op.ruta}»`);
    if (partes.length === 1 && INTOCABLES.has(partes[0])) throw new OpInvalida(`set: «${op.ruta}» no se puede cambiar`);
    let nodo = capa as unknown as Record<string, unknown>;
    for (const p of partes.slice(0, -1)) {
      const sig = nodo[p];
      if (sig === undefined || sig === null) nodo[p] = {};
      else if (typeof sig !== "object" || Array.isArray(sig))
        throw new OpInvalida(`set: «${p}» no es un objeto en la capa «${op.capa}»`);
      nodo = nodo[p] as Record<string, unknown>;
    }
    nodo[partes[partes.length - 1]] = structuredClone(op.valor);
    return;
  }
  if (op.op === "add") {
    if (d.capas.some((c) => c.id === op.capa.id)) throw new OpInvalida(`add: ya existe la capa «${op.capa.id}»`);
    const n = d.capas.length;
    const i = op.indice === undefined ? n : Math.min(Math.max(Math.trunc(op.indice), 0), n);
    d.capas.splice(i, 0, structuredClone(op.capa) as Draft<Capa>);
    return;
  }
  if (!d.capas.some((c) => c.id === op.capa)) throw new OpInvalida(`del: no existe la capa «${op.capa}»`);
  const borrar = new Set([op.capa, ...descendientes(d as Escena, op.capa)]);
  // Un grupo que se queda sin hijos se borra también (el validador prohíbe hijos vacíos).
  let cambio = true;
  while (cambio) {
    cambio = false;
    for (const c of d.capas) {
      if (c.tipo === "group" && !borrar.has(c.id) && c.hijos.length > 0 && c.hijos.every((h) => borrar.has(h))) {
        borrar.add(c.id);
        cambio = true;
      }
    }
  }
  d.capas = d.capas.filter((c) => !borrar.has(c.id));
  for (const c of d.capas) if (c.tipo === "group") c.hijos = c.hijos.filter((h) => !borrar.has(h));
}

export function aplicarOps(escena: Escena, ops: Op[]): Escena {
  return produce(escena, (d) => {
    for (const op of ops) aplicarEnBorrador(d, op);
  });
}

export function descendientes(escena: Escena, id: string): string[] {
  const porId = new Map(escena.capas.map((c) => [c.id, c]));
  const vistos = new Set<string>();
  const pila = [id];
  while (pila.length) {
    const c = porId.get(pila.pop()!);
    if (!c || c.tipo !== "group") continue;
    for (const h of c.hijos) {
      if (vistos.has(h) || h === id) continue;
      vistos.add(h);
      pila.push(h);
    }
  }
  return [...vistos];
}

export function padreDe(escena: Escena, id: string): string | null {
  for (const c of escena.capas) if (c.tipo === "group" && c.hijos.includes(id)) return c.id;
  return null;
}

export function raizDe(escena: Escena, id: string): string {
  let actual = id;
  const vistos = new Set([id]);
  for (let p = padreDe(escena, actual); p && !vistos.has(p); p = padreDe(escena, actual)) {
    vistos.add(p);
    actual = p;
  }
  return actual;
}

// Ids que no se pintan: ocultas ellas mismas o dentro de un grupo oculto.
export function ocultasEfectivas(escena: Escena): Set<string> {
  const out = new Set<string>();
  for (const c of escena.capas) {
    if (!c.oculta) continue;
    out.add(c.id);
    for (const d of descendientes(escena, c.id)) out.add(d);
  }
  return out;
}

// Orden de pintado: z ascendente; en empate, el orden del arreglo.
export function ordenadas(escena: Escena): Capa[] {
  return escena.capas
    .map((c, i) => [c, i] as const)
    .sort((a, b) => a[0].z - b[0].z || a[1] - b[1])
    .map(([c]) => c);
}

// Caja de cada grupo = unión de las cajas de sus hijos (recursivo, sin ciclos).
export function cajasDeGrupo(escena: Escena): Map<string, Caja> {
  const porId = new Map(escena.capas.map((c) => [c.id, c]));
  const memo = new Map<string, Caja | null>();
  const enCurso = new Set<string>();
  const caja = (id: string): Caja | null => {
    if (memo.has(id)) return memo.get(id)!;
    const c = porId.get(id);
    if (!c) return null;
    if (c.tipo !== "group") return { x: c.x, y: c.y, w: c.w, h: c.h };
    if (enCurso.has(id)) return null;
    enCurso.add(id);
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const h of c.hijos) {
      const k = caja(h);
      if (!k) continue;
      x0 = Math.min(x0, k.x);
      y0 = Math.min(y0, k.y);
      x1 = Math.max(x1, k.x + k.w);
      y1 = Math.max(y1, k.y + k.h);
    }
    enCurso.delete(id);
    const r = x0 === Infinity ? null : { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
    memo.set(id, r);
    return r;
  };
  const out = new Map<string, Caja>();
  for (const c of escena.capas) {
    if (c.tipo !== "group") continue;
    const k = caja(c.id);
    if (k) out.set(c.id, k);
  }
  return out;
}

export function cajaDe(escena: Escena, id: string): Caja | null {
  const c = escena.capas.find((k) => k.id === id);
  if (!c) return null;
  if (c.tipo !== "group") return { x: c.x, y: c.y, w: c.w, h: c.h };
  return cajasDeGrupo(escena).get(id) ?? null;
}

// Python round(): half-to-even (round(2.5) == 2). Math.round(2.5) == 3.
export function redondearPar(n: number): number {
  const piso = Math.floor(n);
  const dif = n - piso;
  if (dif < 0.5) return piso;
  if (dif > 0.5) return piso + 1;
  return piso % 2 === 0 ? piso : piso + 1;
}

// Igual que escena._anclaje_de del backend: lo que cubre el lienzo va arriba;
// lo demás, por el tercio en que cae su centro.
function anclajeDe(c: Capa, ow: number, oh: number): Anclaje {
  if (c.x <= 0 && c.y <= 0 && c.x + c.w >= ow && c.y + c.h >= oh) return "top";
  const centro = c.y + c.h / 2;
  if (centro < oh / 3) return "top";
  if (centro > (oh * 2) / 3) return "bottom";
  return "center";
}

// Misma regla que escena.reformatear (src/plantillas/escena.py): dy = nuevoH − viejoH;
// top no se mueve, bottom suma dy, center suma round(dy/2) con half-to-even como
// Python; lo que cubre todo el lienzo se estira; los grupos se recalculan al final.
export function reformatear(escena: Escena, formato: Formato): Escena {
  const { w: nw, h: nh } = FORMATOS[formato];
  const ow = escena.lienzo.w;
  const oh = escena.lienzo.h;
  const dy = nh - oh;
  return produce(escena, (d) => {
    for (const c of d.capas) {
      if (c.tipo === "group") continue;
      if (c.x <= 0 && c.y <= 0 && c.x + c.w >= ow && c.y + c.h >= oh) {
        Object.assign(c, { x: 0, y: 0, w: nw, h: nh });
        continue;
      }
      const anclaje = c.anclaje || anclajeDe(c as Capa, ow, oh);
      if (anclaje === "bottom") c.y += dy;
      else if (anclaje === "center") c.y += redondearPar(dy / 2);
    }
    const cajas = cajasDeGrupo(d as Escena);
    for (const c of d.capas) {
      const k = c.tipo === "group" ? cajas.get(c.id) : undefined;
      if (k) Object.assign(c, k);
    }
    d.lienzo.w = nw;
    d.lienzo.h = nh;
    d.lienzo.formato = formato;
  });
}

export function resolverColor(valor: string, tokens: Tokens, colorMarca: string): string {
  if (!valor.startsWith("token:")) return valor;
  const nombre = valor.slice("token:".length);
  if (nombre === "marca") return colorMarca;
  return tokens.colores[nombre] ?? "transparent";
}

export function idLibre(escena: Escena, base: string): string {
  let s = base
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!/^[a-z]/.test(s)) s = `c_${s}`;
  s = s.slice(0, 26).replace(/_+$/, "") || "c";
  const usados = new Set(escena.capas.map((c) => c.id));
  if (!usados.has(s)) return s;
  for (let n = 2; ; n++) {
    const id = `${s}_${n}`;
    if (!usados.has(id)) return id;
  }
}

export function capaNueva(
  tipo: "text" | "shape" | "image" | "svg",
  escena: Escena,
  opciones: { fuente: string; src?: string; nombre?: string },
): Capa {
  const { w: W, h: H } = escena.lienzo;
  const z = Math.min(999, Math.max(-1, ...escena.capas.map((c) => c.z)) + 1);
  const base = (nombre: string, w: number, h: number) => ({
    id: idLibre(escena, opciones.nombre ?? nombre),
    nombre: opciones.nombre ?? nombre,
    x: Math.round((W - w) / 2),
    y: Math.round((H - h) / 2),
    w,
    h,
    rot: 0,
    opacity: 1,
    z,
    bloqueada: false,
    oculta: false,
    anclaje: "center" as Anclaje,
  });
  if (tipo === "text") {
    return {
      ...base("texto", 800, 160),
      tipo: "text",
      texto: "Texto",
      estilo: {
        fontFamily: opciones.fuente,
        fontWeight: 700,
        fontSize: 96,
        lineHeight: 1.1,
        letterSpacing: "0em",
        color: "#111111",
        textAlign: "left",
        textWrap: "balance",
        verticalAlign: "top",
        textTransform: "none",
        spans: [],
      },
    };
  }
  if (tipo === "shape") {
    return { ...base("forma", 400, 400), tipo: "shape", forma: "rect", estilo: { fill: "token:marca", radius: 0, borderWidth: 0 } };
  }
  if (!opciones.src) throw new Error(`capaNueva: «${tipo}» necesita src`);
  if (tipo === "svg") {
    return { ...base("svg", 300, 300), tipo: "svg", src: opciones.src, ajuste: "contain", estilo: {} };
  }
  return {
    ...base("imagen", 800, 800),
    tipo: "image",
    src: opciones.src,
    campo: null,
    ajuste: "cover",
    mascara: "none",
    estilo: { objectPosition: "center" },
  };
}

// src es "assets/<archivo>" o "fotos/<archivo>" (plan 1, D2).
export function urlDeAsset(slug: string, src: string): string {
  return `/api/brands/${slug}/files/${src.split("/").map(encodeURIComponent).join("/")}`;
}

export function normalizarAngulo(a: number): number {
  const r = ((((a + 180) % 360) + 360) % 360) - 180;
  return r === -180 && a > 0 ? 180 : r;
}
