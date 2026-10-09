import { describe, expect, it, vi } from "vitest";
import { OpInvalida } from "@/lib/escena";
import { aplicarResultado, interpretarResultado } from "../use-chat-diseno";

describe("interpretarResultado", () => {
  it("crear devuelve escena", () => {
    const r = interpretarResultado({ escena: { v: 2, capas: [] }, respuesta: "Listo", version: 3 });
    expect(r).toEqual({ tipo: "escena", escena: { v: 2, capas: [] }, respuesta: "Listo", version: 3 });
  });
  it("editar devuelve ops", () => {
    const ops = [{ op: "del", capa: "a" }];
    const r = interpretarResultado({ ops, respuesta: "Hecho", version: 4 });
    expect(r).toEqual({ tipo: "ops", ops, respuesta: "Hecho", version: 4 });
  });
  it("basura es null", () => {
    expect(interpretarResultado(null)).toBeNull();
    expect(interpretarResultado({ respuesta: "x" })).toBeNull();
  });
});

describe("aplicarResultado", () => {
  it("escena va a cargar, ops a aplicar con etiqueta", () => {
    const cargar = vi.fn();
    const aplicar = vi.fn();
    expect(aplicarResultado({ tipo: "escena", escena: { v: 2, capas: [] } as never, respuesta: "Listo", version: 1 },
      { cargar, aplicar })).toBeNull();
    expect(cargar).toHaveBeenCalledOnce();
    const ops = [{ op: "del", capa: "a" }] as never;
    expect(aplicarResultado({ tipo: "ops", ops, respuesta: "Hecho", version: 2 }, { cargar, aplicar })).toBeNull();
    expect(aplicar).toHaveBeenCalledWith(ops, "IA: Hecho");
  });
  it("ops que ya no aplican no rompen", () => {
    // La persona borró la capa mientras corría el job: aplicar lanza OpInvalida.
    const aplicar = vi.fn(() => {
      throw new OpInvalida("no existe la capa a");
    });
    const err = aplicarResultado({ tipo: "ops", ops: [{ op: "del", capa: "a" }] as never, respuesta: "x", version: 3 },
      { cargar: vi.fn(), aplicar });
    expect(err).toMatch(/cambió mientras/);
  });
  it("otro error sí se propaga", () => {
    const aplicar = vi.fn(() => {
      throw new TypeError("bug");
    });
    expect(() => aplicarResultado({ tipo: "ops", ops: [], respuesta: "x", version: 3 },
      { cargar: vi.fn(), aplicar })).toThrow(TypeError);
  });
});
