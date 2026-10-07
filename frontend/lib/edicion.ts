import {
  aplicarOps,
  cajaDe,
  cajasDeGrupo,
  descendientes,
  idLibre,
  MAX_CAPAS,
  ordenadas,
  padreDe,
  type Caja,
  type Capa,
  type CapaGrupo,
  type Escena,
  type Op,
} from "./escena";

const acotar = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));
const porId = (e: Escena) => new Map(e.capas.map((c) => [c.id, c]));

// Hojas (no grupos) de una selección, sin repetir.
export function expandir(escena: Escena, ids: string[]): string[] {
  const m = porId(escena);
  const out = new Set<string>();
  for (const id of ids) {
    for (const k of [id, ...descendientes(escena, id)]) {
      const c = m.get(k);
      if (c && c.tipo !== "group") out.add(k);
    }
  }
  return [...out];
}

export function opsMover(escena: Escena, ids: string[], dx: number, dy: number): Op[] {
  const m = porId(escena);
  const ops: Op[] = [];
  for (const id of expandir(escena, ids)) {
    const c = m.get(id)!;
    if (c.bloqueada) continue;
    const x = acotar(Math.round(c.x + dx), -2000, 4000);
    const y = acotar(Math.round(c.y + dy), -2000, 4000);
    if (x !== c.x) ops.push({ op: "set", capa: id, ruta: "x", valor: x });
    if (y !== c.y) ops.push({ op: "set", capa: id, ruta: "y", valor: y });
  }
  return ops;
}

function union(cajas: Caja[]): Caja {
  const x0 = Math.min(...cajas.map((k) => k.x));
  const y0 = Math.min(...cajas.map((k) => k.y));
  const x1 = Math.max(...cajas.map((k) => k.x + k.w));
  const y1 = Math.max(...cajas.map((k) => k.y + k.h));
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

export type ModoAlinear = "izq" | "centro-h" | "der" | "arriba" | "centro-v" | "abajo";

// Una capa se alinea al lienzo; varias, a la unión de sus cajas.
export function opsAlinear(escena: Escena, ids: string[], modo: ModoAlinear): Op[] {
  const cajas = ids.map((id) => [id, cajaDe(escena, id)] as const).filter((p): p is [string, Caja] => !!p[1]);
  if (cajas.length === 0) return [];
  const ref = cajas.length === 1 ? { x: 0, y: 0, w: escena.lienzo.w, h: escena.lienzo.h } : union(cajas.map((p) => p[1]));
  return cajas.flatMap(([id, k]) => {
    const dx =
      modo === "izq" ? ref.x - k.x : modo === "der" ? ref.x + ref.w - (k.x + k.w) : modo === "centro-h" ? ref.x + (ref.w - k.w) / 2 - k.x : 0;
    const dy =
      modo === "arriba" ? ref.y - k.y : modo === "abajo" ? ref.y + ref.h - (k.y + k.h) : modo === "centro-v" ? ref.y + (ref.h - k.h) / 2 - k.y : 0;
    return opsMover(escena, [id], dx, dy);
  });
}

export function opsDistribuir(escena: Escena, ids: string[], eje: "h" | "v"): Op[] {
  const cajas = ids.map((id) => [id, cajaDe(escena, id)] as const).filter((p): p is [string, Caja] => !!p[1]);
  if (cajas.length < 3) return [];
  const pos = (k: Caja) => (eje === "h" ? k.x : k.y);
  const tam = (k: Caja) => (eje === "h" ? k.w : k.h);
  cajas.sort((a, b) => pos(a[1]) - pos(b[1]));
  const primera = cajas[0][1];
  const ultima = cajas[cajas.length - 1][1];
  const total = pos(ultima) + tam(ultima) - pos(primera);
  const hueco = (total - cajas.reduce((s, p) => s + tam(p[1]), 0)) / (cajas.length - 1);
  const ops: Op[] = [];
  let cursor = pos(primera) + tam(primera) + hueco;
  for (const [id, k] of cajas.slice(1, -1)) {
    const d = cursor - pos(k);
    ops.push(...opsMover(escena, [id], eje === "h" ? d : 0, eje === "v" ? d : 0));
    cursor += tam(k) + hueco;
  }
  return ops;
}

export function opsAgrupar(escena: Escena, ids: string[]): { ops: Op[]; id: string } | null {
  if (ids.length < 2 || escena.capas.length + 1 > MAX_CAPAS) return null;
  const padres = new Set(ids.map((id) => padreDe(escena, id)));
  if (padres.size !== 1) return null;
  const padre = [...padres][0];
  const enOrden = escena.capas.filter((c) => ids.includes(c.id)).map((c) => c.id);
  const cajas = enOrden.map((id) => cajaDe(escena, id)).filter((k): k is Caja => !!k);
  const z = Math.max(...expandir(escena, enOrden).map((id) => escena.capas.find((c) => c.id === id)!.z));
  const id = idLibre(escena, "grupo");
  const grupo: CapaGrupo = {
    id,
    nombre: "Grupo",
    tipo: "group",
    ...union(cajas),
    rot: 0,
    opacity: 1,
    z,
    bloqueada: false,
    oculta: false,
    anclaje: "center",
    hijos: enOrden,
    estilo: {},
  };
  const ops: Op[] = [{ op: "add", capa: grupo }];
  if (padre) {
    const p = escena.capas.find((c) => c.id === padre) as CapaGrupo;
    const primero = p.hijos.findIndex((h) => enOrden.includes(h));
    const resto = p.hijos.filter((h) => !enOrden.includes(h));
    resto.splice(Math.min(primero, resto.length), 0, id);
    ops.push({ op: "set", capa: padre, ruta: "hijos", valor: resto });
  }
  return { ops, id };
}

export function opsDesagrupar(escena: Escena, id: string): { ops: Op[]; hijos: string[] } | null {
  const g = escena.capas.find((c) => c.id === id);
  if (!g || g.tipo !== "group") return null;
  const ops: Op[] = [];
  const padre = padreDe(escena, id);
  if (padre) {
    const p = escena.capas.find((c) => c.id === padre) as CapaGrupo;
    ops.push({ op: "set", capa: padre, ruta: "hijos", valor: p.hijos.flatMap((h) => (h === id ? g.hijos : [h])) });
  }
  // Primero se vacía el grupo para que del no se lleve a los hijos.
  ops.push({ op: "set", capa: id, ruta: "hijos", valor: [] }, { op: "del", capa: id });
  return { ops, hijos: [...g.hijos] };
}

export function clonarConIds(escena: Escena, capas: Capa[], desplazar = 20): { capas: Capa[]; mapa: Map<string, string> } {
  const temp: Escena = { ...escena, capas: [...escena.capas] };
  const mapa = new Map<string, string>();
  for (const c of capas) {
    const nuevo = idLibre(temp, c.id);
    mapa.set(c.id, nuevo);
    temp.capas.push({ ...c, id: nuevo });
  }
  const clones = capas.map((c) => {
    const k = structuredClone(c);
    k.id = mapa.get(c.id)!;
    k.x = acotar(k.x + desplazar, -2000, 4000);
    k.y = acotar(k.y + desplazar, -2000, 4000);
    if (k.tipo === "group") k.hijos = k.hijos.map((h) => mapa.get(h)).filter((h): h is string => !!h);
    return k;
  });
  return { capas: clones, mapa };
}

// Un grupo cuyos hijos no vienen en la lista quedaría vacío (el validador lo
// rechaza): se descarta, y con él los grupos que solo lo contenían.
function sinGruposVacios(capas: Capa[]): Capa[] {
  let lista = capas;
  for (;;) {
    const ids = new Set(lista.map((c) => c.id));
    const sig = lista.filter((c) => c.tipo !== "group" || c.hijos.some((h) => ids.has(h)));
    if (sig.length === lista.length) return lista;
    lista = sig;
  }
}

// Clona y pone las copias arriba de todo, conservando su orden relativo.
function opsClonar(escena: Escena, capas: Capa[], desplazar: number): { ops: Op[]; nuevos: string[] } {
  capas = sinGruposVacios(capas);
  if (capas.length === 0 || escena.capas.length + capas.length > MAX_CAPAS) return { ops: [], nuevos: [] };
  const { capas: clones, mapa } = clonarConIds(escena, capas, desplazar);
  const tope = Math.max(-1, ...escena.capas.map((c) => c.z));
  const enOrden = [...clones].sort((a, b) => a.z - b.z);
  enOrden.forEach((c, i) => (c.z = Math.min(999, tope + 1 + i)));
  const hijosDeCopia = new Set(clones.flatMap((c) => (c.tipo === "group" ? c.hijos : [])));
  const nuevos = capas.map((c) => mapa.get(c.id)!).filter((id) => !hijosDeCopia.has(id));
  return { ops: clones.map((c) => ({ op: "add", capa: c }) as Op), nuevos };
}

export function opsDuplicar(escena: Escena, ids: string[]): { ops: Op[]; nuevos: string[] } {
  const todos = new Set(ids.flatMap((id) => [id, ...descendientes(escena, id)]));
  return opsClonar(escena, escena.capas.filter((c) => todos.has(c.id)), 20);
}

export function opsPegar(escena: Escena, capas: Capa[]): { ops: Op[]; nuevos: string[] } {
  return opsClonar(escena, capas, 20);
}

export type ModoZ = "subir" | "bajar" | "frente" | "fondo";

const ordenHojas = (e: Escena) => ordenadas(e).filter((c) => c.tipo !== "group").map((c) => c.id);

function opsDeOrden(escena: Escena, orden: string[]): Op[] {
  const m = porId(escena);
  return orden.flatMap((id, i) => (m.get(id)!.z === i ? [] : [{ op: "set", capa: id, ruta: "z", valor: i } as Op]));
}

export function opsZ(escena: Escena, ids: string[], modo: ModoZ): Op[] {
  const sel = new Set(expandir(escena, ids));
  const L = ordenHojas(escena);
  let nuevo: string[];
  if (modo === "frente") nuevo = [...L.filter((id) => !sel.has(id)), ...L.filter((id) => sel.has(id))];
  else if (modo === "fondo") nuevo = [...L.filter((id) => sel.has(id)), ...L.filter((id) => !sel.has(id))];
  else {
    nuevo = [...L];
    if (modo === "subir") {
      for (let i = nuevo.length - 2; i >= 0; i--)
        if (sel.has(nuevo[i]) && !sel.has(nuevo[i + 1])) [nuevo[i], nuevo[i + 1]] = [nuevo[i + 1], nuevo[i]];
    } else {
      for (let i = 1; i < nuevo.length; i++)
        if (sel.has(nuevo[i]) && !sel.has(nuevo[i - 1])) [nuevo[i], nuevo[i - 1]] = [nuevo[i - 1], nuevo[i]];
    }
  }
  if (nuevo.every((id, i) => id === L[i])) return [];
  return opsDeOrden(escena, nuevo);
}

// El panel manda los hermanos de arriba hacia abajo. Cada hermano es un
// bloque de hojas; los bloques se reinsertan donde estaba el más bajo.
export function opsReordenar(escena: Escena, hermanosArribaPrimero: string[]): Op[] {
  const L = ordenHojas(escena);
  const bloques = hermanosArribaPrimero.map((id) => {
    const set = new Set(expandir(escena, [id]));
    return L.filter((h) => set.has(h));
  });
  const enBloques = new Set(bloques.flat());
  const pos = L.findIndex((h) => enBloques.has(h));
  if (pos < 0) return [];
  const resto = L.filter((h) => !enBloques.has(h));
  const antes = L.slice(0, pos).filter((h) => !enBloques.has(h)).length;
  const nuevo = [...resto.slice(0, antes), ...[...bloques].reverse().flat(), ...resto.slice(antes)];
  return opsDeOrden(escena, nuevo);
}

export function opsCajasDeGrupo(escena: Escena): Op[] {
  const cajas = cajasDeGrupo(escena);
  const ops: Op[] = [];
  for (const c of escena.capas) {
    const k = cajas.get(c.id);
    if (!k) continue;
    for (const campo of ["x", "y", "w", "h"] as const)
      if (c[campo] !== k[campo]) ops.push({ op: "set", capa: c.id, ruta: campo, valor: k[campo] });
  }
  return ops;
}

// Lo que manda el store: las ops y el recálculo de cajas, en un solo paso.
export function conCajasDeGrupo(escena: Escena, ops: Op[]): Op[] {
  if (ops.length === 0) return ops;
  return [...ops, ...opsCajasDeGrupo(aplicarOps(escena, ops))];
}

export function esCampoDeTexto(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || t.isContentEditable === true || t.getAttribute("contenteditable") === "true";
}
