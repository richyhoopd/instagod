import { describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { Escena } from "@/lib/escena";
import { alternar, encuadre, raicesSeleccionables, zoomEnPunto } from "../vista";

const base = datos.base as unknown as Escena;

describe("vista", () => {
  it("encuadre centra el lienzo con margen", () => {
    const v = encuadre({ w: 600, h: 800 }, { w: 1080, h: 1350 });
    expect(v.zoom).toBeCloseTo(536 / 1080, 4);
    expect(v.x).toBe(32);
    expect(v.y).toBe(65);
  });

  it("zoomEnPunto deja quieto el punto del cursor", () => {
    const v = zoomEnPunto({ zoom: 0.5, x: 0, y: 0 }, 1, 100, 100);
    expect(v).toEqual({ zoom: 1, x: -100, y: -100 });
  });

  it("zoomEnPunto respeta los límites", () => {
    expect(zoomEnPunto({ zoom: 1, x: 0, y: 0 }, 10, 0, 0).zoom).toBe(4);
    expect(zoomEnPunto({ zoom: 1, x: 0, y: 0 }, 0.01, 0, 0).zoom).toBe(0.1);
  });

  it("raicesSeleccionables sube a la raíz y quita las bloqueadas", () => {
    const e = structuredClone(base);
    e.capas.find((c) => c.id === "titulo")!.bloqueada = true;
    expect(raicesSeleccionables(e, ["caja", "logo", "titulo"])).toEqual(["marca"]);
  });

  it("alternar quita las repetidas y agrega las nuevas", () => {
    expect(alternar(["a", "b"], ["b", "c"])).toEqual(["a", "c"]);
  });
});
