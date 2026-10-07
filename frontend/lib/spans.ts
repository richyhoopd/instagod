import { MAX_SPANS, type Span } from "./escena";

// Los offsets de `Span` (desde/hasta) son PUNTOS DE CÓDIGO, igual que el slicing
// de str en Python (src/plantillas/escena.py). NO son unidades UTF-16: "😀" mide
// 1 aquí y 2 en `string.length`. Todo lo de este módulo opera en code points;
// solo `utf16ACodePoint`/`codePointAUtf16` tocan UTF-16, para el textarea
// (selectionStart/End).

export type Trozo = { texto: string; color: string | null };

// Índice UTF-16 (textarea) -> índice en code points. Fuera de rango se acota; si
// cae en medio de un par sustituto, devuelve el code point que lo contiene.
export function utf16ACodePoint(texto: string, idx: number): number {
  const tope = Math.min(Math.max(idx, 0), texto.length);
  let cp = 0;
  let u = 0;
  for (const c of texto) {
    const siguiente = u + c.length;
    if (siguiente > tope) break;
    u = siguiente;
    cp++;
  }
  return cp;
}

// Índice en code points -> índice UTF-16. Fuera de rango se acota.
export function codePointAUtf16(texto: string, cp: number): number {
  let u = 0;
  let n = 0;
  for (const c of texto) {
    if (n >= cp) break;
    u += c.length;
    n++;
  }
  return u;
}

export function trozos(texto: string, spans: Span[] = []): Trozo[] {
  const cps = Array.from(texto);
  const orden = [...spans].sort((a, b) => a.desde - b.desde);
  const out: Trozo[] = [];
  let i = 0;
  for (const s of orden) {
    const desde = Math.max(s.desde, i);
    const hasta = Math.min(s.hasta, cps.length);
    if (hasta <= desde) continue;
    if (desde > i) out.push({ texto: cps.slice(i, desde).join(""), color: null });
    out.push({ texto: cps.slice(desde, hasta).join(""), color: s.color });
    i = hasta;
  }
  if (i < cps.length) out.push({ texto: cps.slice(i).join(""), color: null });
  return out;
}

// Recoloca los spans tras una edición. El tramo editado es lo que queda
// entre el prefijo y el sufijo comunes (en code points, para no partir pares
// sustitutos). Regla D11: lo insertado hereda color solo si cae estrictamente
// dentro de un span.
//
// `cursor` (code points, en `despues`, tras la edición) desambigua letras
// repetidas: lo editado termina en el cursor, así que el sufijo común se fija
// ahí. Si no es consistente con los textos, se ignora.
export function ajustarSpans(antes: string, despues: string, spans: Span[], cursor?: number): Span[] {
  if (antes === despues) return spans;
  const a = Array.from(antes);
  const d = Array.from(despues);
  const max = Math.min(a.length, d.length);
  let s = -1;
  if (cursor !== undefined && Number.isInteger(cursor) && cursor >= 0 && cursor <= d.length) {
    const fijo = d.length - cursor;
    if (fijo <= max && fijo <= a.length) {
      let ok = true;
      for (let i = 0; i < fijo; i++) if (a[a.length - 1 - i] !== d[d.length - 1 - i]) ok = false;
      if (ok) s = fijo;
    }
  }
  let p = 0;
  if (s >= 0) {
    while (p < max - s && a[p] === d[p]) p++;
  } else {
    while (p < max && a[p] === d[p]) p++;
    s = 0;
    while (s < max - p && a[a.length - 1 - s] === d[d.length - 1 - s]) s++;
  }
  const finA = a.length - s;
  const finD = d.length - s;
  const delta = finD - finA;
  const desde = (pos: number) => (pos < p ? pos : pos >= finA ? pos + delta : finD);
  const hasta = (pos: number) => (pos <= p ? pos : pos >= finA ? pos + delta : p);
  return spans
    .map((sp) => ({
      ...sp,
      desde: Math.min(Math.max(desde(sp.desde), 0), d.length),
      hasta: Math.min(Math.max(hasta(sp.hasta), 0), d.length),
    }))
    .filter((sp) => sp.hasta > sp.desde);
}

// `largo` (code points del texto) recorta el rango. Si el resultado pasaría de
// MAX_SPANS se rechaza el pintado y se devuelve `spans` tal cual.
export function pintarSpan(
  spans: Span[],
  desde: number,
  hasta: number,
  color: string | null,
  largo?: number,
): Span[] {
  if (largo !== undefined) {
    desde = Math.max(desde, 0);
    hasta = Math.min(hasta, largo);
  }
  if (hasta <= desde) return spans;
  const out: Span[] = [];
  for (const s of spans) {
    if (s.hasta <= desde || s.desde >= hasta) {
      out.push(s);
      continue;
    }
    if (s.desde < desde) out.push({ ...s, hasta: desde });
    if (s.hasta > hasta) out.push({ ...s, desde: hasta });
  }
  if (color) out.push({ desde, hasta, color });
  out.sort((a, b) => a.desde - b.desde);
  const unidos: Span[] = [];
  for (const s of out) {
    const u = unidos[unidos.length - 1];
    if (u && u.hasta === s.desde && u.color === s.color) u.hasta = s.hasta;
    else unidos.push({ ...s });
  }
  return unidos.length > MAX_SPANS && unidos.length > spans.length ? spans : unidos;
}
