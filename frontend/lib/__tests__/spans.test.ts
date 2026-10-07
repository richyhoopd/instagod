import { describe, expect, it } from "vitest";
import { ajustarSpans, codePointAUtf16, pintarSpan, trozos, utf16ACodePoint } from "../spans";

const S = (desde: number, hasta: number, color = "#f00") => ({ desde, hasta, color });

describe("trozos", () => {
  it("parte el texto en tramos con y sin color", () => {
    expect(trozos("Hola mundo", [S(5, 10)])).toEqual([
      { texto: "Hola ", color: null },
      { texto: "mundo", color: "#f00" },
    ]);
  });
  it("ignora spans vacíos y fuera de rango", () => {
    expect(trozos("Hola", [S(2, 2), S(3, 99)])).toEqual([
      { texto: "Hol", color: null },
      { texto: "a", color: "#f00" },
    ]);
  });
  it("sin spans devuelve un solo tramo", () => {
    expect(trozos("Hola")).toEqual([{ texto: "Hola", color: null }]);
  });
});

describe("ajustarSpans", () => {
  it("insertar dentro del span lo agranda", () => {
    expect(ajustarSpans("Hola mundo", "Hola muXndo", [S(5, 10)])).toEqual([S(5, 11)]);
  });
  it("insertar antes del span lo recorre", () => {
    expect(ajustarSpans("Hola mundo", "Hola Xmundo", [S(5, 10)])).toEqual([S(6, 11)]);
  });
  it("insertar justo al final del span no hereda color", () => {
    expect(ajustarSpans("Hola mundo", "Hola mundoX", [S(5, 10)])).toEqual([S(5, 10)]);
  });
  it("borrar a caballo del span lo recorta", () => {
    // "Hola mundo" con span "a mu" (3-7); se borra "la m" (2-6) → "Houndo", queda "u".
    expect(ajustarSpans("Hola mundo", "Houndo", [S(3, 7)])).toEqual([S(2, 3)]);
  });
  it("borrar todo el span lo elimina", () => {
    expect(ajustarSpans("Hola mundo", "Hola ", [S(5, 10)])).toEqual([]);
  });
  it("sin cambio devuelve lo mismo", () => {
    const spans = [S(0, 4)];
    expect(ajustarSpans("Hola", "Hola", spans)).toBe(spans);
  });
});

describe("pintarSpan", () => {
  it("agrega un tramo", () => {
    expect(pintarSpan([], 0, 4, "#f00")).toEqual([S(0, 4)]);
  });
  it("parte un span existente al pintar en medio", () => {
    expect(pintarSpan([S(0, 10)], 3, 6, "#00f")).toEqual([S(0, 3), S(3, 6, "#00f"), S(6, 10)]);
  });
  it("une tramos contiguos del mismo color", () => {
    expect(pintarSpan([S(0, 3)], 3, 6, "#f00")).toEqual([S(0, 6)]);
  });
  it("con color null borra el tramo", () => {
    expect(pintarSpan([S(0, 10)], 3, 6, null)).toEqual([S(0, 3), S(6, 10)]);
  });
  it("rango vacío no cambia nada", () => {
    const spans = [S(0, 3)];
    expect(pintarSpan(spans, 2, 2, "#00f")).toBe(spans);
  });
});

// Los offsets de spans son code points (Python), no UTF-16.
const EMOJI = "😀"; // 1 code point, 2 unidades UTF-16
const FAMILIA = "👩\u200d👩\u200d👧"; // 5 code points, 8 unidades UTF-16
const E_COMP = "\u00e9"; // é compuesta: 1 code point
const E_COMB = "e\u0301"; // é combinada: 2 code points

describe("conversión UTF-16 <-> code points", () => {
  it("emoji ocupa 2 unidades UTF-16 y 1 code point", () => {
    const t = `a${EMOJI}b`;
    expect(utf16ACodePoint(t, 0)).toBe(0);
    expect(utf16ACodePoint(t, 1)).toBe(1);
    expect(utf16ACodePoint(t, 3)).toBe(2);
    expect(utf16ACodePoint(t, 4)).toBe(3);
    expect(codePointAUtf16(t, 2)).toBe(3);
    expect(codePointAUtf16(t, 3)).toBe(4);
  });
  it("ZWJ cuenta cada code point", () => {
    const t = `${FAMILIA}x`;
    expect(Array.from(FAMILIA)).toHaveLength(5);
    expect(utf16ACodePoint(t, FAMILIA.length)).toBe(5);
    expect(codePointAUtf16(t, 5)).toBe(FAMILIA.length);
  });
  it("é compuesta 1, combinada 2", () => {
    expect(utf16ACodePoint(`${E_COMP}x`, 1)).toBe(1);
    expect(utf16ACodePoint(`${E_COMB}x`, 2)).toBe(2);
  });
  it("una posición en medio de un par sustituto cae al code point que lo contiene", () => {
    expect(utf16ACodePoint(EMOJI, 1)).toBe(0);
  });
  it("ida y vuelta y fuera de rango se acotan", () => {
    const t = `${EMOJI}${FAMILIA}${E_COMB}z`;
    const n = Array.from(t).length;
    for (let i = 0; i <= n; i++) expect(utf16ACodePoint(t, codePointAUtf16(t, i))).toBe(i);
    expect(utf16ACodePoint(t, 999)).toBe(n);
    expect(codePointAUtf16(t, 999)).toBe(t.length);
    expect(codePointAUtf16(t, -3)).toBe(0);
  });
});

describe("spans en code points", () => {
  it("trozos con tramo después de un emoji", () => {
    // 😀 = cp 0; "Hola" = cp 1-4; span cp 1-5 cubre "Hola"
    expect(trozos(`${EMOJI}Hola mundo`, [S(1, 5)])).toEqual([
      { texto: EMOJI, color: null },
      { texto: "Hola", color: "#f00" },
      { texto: " mundo", color: null },
    ]);
  });
  it("trozos con span que cubre el emoji sin partirlo", () => {
    expect(trozos(`a${EMOJI}b`, [S(1, 2)])).toEqual([
      { texto: "a", color: null },
      { texto: EMOJI, color: "#f00" },
      { texto: "b", color: null },
    ]);
  });
  it("trozos con ZWJ y é combinada", () => {
    expect(trozos(`${FAMILIA}${E_COMB}!`, [S(5, 7)])).toEqual([
      { texto: FAMILIA, color: null },
      { texto: E_COMB, color: "#f00" },
      { texto: "!", color: null },
    ]);
  });
  it("trozos recorta 'hasta' al largo en code points, no UTF-16", () => {
    expect(trozos(`${EMOJI}${EMOJI}`, [S(1, 2)])).toEqual([
      { texto: EMOJI, color: null },
      { texto: EMOJI, color: "#f00" },
    ]);
  });
  it("ajustarSpans: insertar un emoji dentro del span suma 1, no 2", () => {
    expect(ajustarSpans(`${EMOJI}Hola`, `${EMOJI}Ho${EMOJI}la`, [S(1, 5)])).toEqual([S(1, 6)]);
  });
  it("ajustarSpans: insertar un emoji antes del span lo recorre 1", () => {
    expect(ajustarSpans(`${EMOJI}Hola`, `${EMOJI}${EMOJI}Hola`, [S(1, 5)])).toEqual([S(2, 6)]);
  });
  it("ajustarSpans: borrar un emoji antes del span lo recorre -1", () => {
    expect(ajustarSpans(`${EMOJI}Hola`, "Hola", [S(1, 5)])).toEqual([S(0, 4)]);
  });
  it("ajustarSpans: no parte un par sustituto al comparar prefijos", () => {
    // 😀 y 😁 comparten el surrogate alto; el cambio es de 1 code point.
    expect(ajustarSpans("a\u{1F600}b", "a\u{1F601}b", [S(0, 3)])).toEqual([S(0, 3)]);
  });
  it("ajustarSpans: ZWJ cuenta 5 code points", () => {
    expect(ajustarSpans(`${FAMILIA}Hola`, `Hola`, [S(5, 9)])).toEqual([S(0, 4)]);
  });
  it("ajustarSpans: é combinada (2 cp) reemplazada por compuesta (1 cp) en el borde izquierdo", () => {
    // El reemplazo toca el borde (p == desde): lo nuevo queda sin color (D11); "x" conserva el span.
    expect(ajustarSpans(`${E_COMB}x`, `${E_COMP}x`, [S(0, 3)])).toEqual([S(1, 2)]);
  });
  it("ajustarSpans: é combinada reemplazada por compuesta dentro del span", () => {
    expect(ajustarSpans(`a${E_COMB}x`, `a${E_COMP}x`, [S(0, 4)])).toEqual([S(0, 3)]);
  });
  it("pintarSpan opera en code points sin importar el texto", () => {
    expect(pintarSpan([S(0, 6)], 1, 2, null)).toEqual([S(0, 1), S(2, 6)]);
  });
});
