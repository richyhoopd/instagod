import { describe, expect, it } from "vitest";
import datos from "../__fixtures__/ops-casos.json";
import {
  OpInvalida,
  aplicarOps,
  cajaDe,
  capaNueva,
  descendientes,
  idLibre,
  imanActivo,
  normalizarAngulo,
  ocultasEfectivas,
  ordenadas,
  padreDe,
  raizDe,
  reformatear,
  resolverColor,
  urlDeAsset,
  type Capa,
  type Escena,
  type Op,
} from "../escena";

type Caso = { nombre: string; ops: Op[]; error?: boolean; ids?: string[]; cambiadas?: Record<string, Capa> };
const fixture = datos as unknown as { base: Escena; casos: Caso[] };

describe("casos compartidos con ops.py", () => {
  for (const caso of fixture.casos) {
    it(caso.nombre, () => {
      const base = structuredClone(fixture.base);
      const copia = structuredClone(base);
      if (caso.error) {
        expect(() => aplicarOps(base, caso.ops)).toThrow(OpInvalida);
        expect(base).toEqual(copia);
        return;
      }
      const r = aplicarOps(base, caso.ops);
      expect(r.capas.map((c) => c.id)).toEqual(caso.ids);
      for (const c of r.capas) {
        const esperada = caso.cambiadas?.[c.id] ?? copia.capas.find((b) => b.id === c.id);
        expect(c).toEqual(esperada);
      }
      expect(base).toEqual(copia);
    });
  }
});

function capa(id: string, y: number, anclaje: "top" | "center" | "bottom", extra: Partial<Capa> = {}): Capa {
  return {
    id, nombre: id, tipo: "shape", x: 0, y, w: 200, h: 100, rot: 0, opacity: 1, z: 1,
    bloqueada: false, oculta: false, anclaje, forma: "rect", estilo: { fill: "#000000" },
    ...extra,
  } as Capa;
}

function escenaReformato(): Escena {
  return {
    v: 2,
    lienzo: { w: 1080, h: 1350, formato: "4x5", fondo: { tipo: "color", valor: "#ffffff" } },
    tokens: { colores: {} },
    capas: [
      capa("c_fondo", 0, "top", { x: 0, w: 1080, h: 1350 }),
      capa("c_titular", 196, "top"),
      capa("c_foto", 600, "bottom"),
      capa("c_clip", 0, "center", { x: 100, w: 500, h: 300 }),
      capa("c_caja", 1200, "bottom", { w: 1080, h: 150 }),
      capa("c_logo", 1230, "bottom", { x: 900, w: 120, h: 90 }),
      { id: "g_marca", nombre: "Marca", tipo: "group", x: 0, y: 1200, w: 1080, h: 150, rot: 0, opacity: 1, z: 0,
        bloqueada: false, oculta: false, anclaje: "bottom", hijos: ["c_logo", "c_caja"], estilo: {} },
    ],
  };
}

const y = (e: Escena, id: string) => e.capas.find((c) => c.id === id)!.y;

describe("reformatear como el plan 1", () => {
  it("4x5 → 9x16: bottom +570, center +285, top igual", () => {
    const r = reformatear(escenaReformato(), "9x16");
    expect(r.lienzo).toMatchObject({ w: 1080, h: 1920, formato: "9x16" });
    expect(y(r, "c_titular")).toBe(196);
    expect(y(r, "c_foto")).toBe(1170);
    expect(y(r, "c_clip")).toBe(285);
    expect(y(r, "c_caja")).toBe(1770);
    expect(y(r, "c_logo")).toBe(1800);
  });

  it("la capa a sangre se estira y la caja del grupo se recalcula", () => {
    const r = reformatear(escenaReformato(), "9x16");
    expect(cajaDe(r, "c_fondo")).toEqual({ x: 0, y: 0, w: 1080, h: 1920 });
    const g = r.capas.find((c) => c.id === "g_marca")!;
    expect({ x: g.x, y: g.y, w: g.w, h: g.h }).toEqual({ x: 0, y: 1770, w: 1080, h: 150 });
  });

  it("4x5 → 1x1: −270 y −135", () => {
    const r = reformatear(escenaReformato(), "1x1");
    expect(y(r, "c_foto")).toBe(330);
    expect(y(r, "c_clip")).toBe(-135);
    expect(y(r, "c_caja")).toBe(930);
  });

  it("9x16 → 1x1: −840 y −420", () => {
    const r = reformatear(reformatear(escenaReformato(), "9x16"), "1x1");
    expect(y(r, "c_foto")).toBe(330);
    expect(y(r, "c_clip")).toBe(-135);
    expect(y(r, "c_caja")).toBe(930);
  });

  it("ida y vuelta restaura x/y y no muta la entrada", () => {
    const e = escenaReformato();
    const copia = structuredClone(e);
    const r = reformatear(reformatear(e, "9x16"), "4x5");
    expect(r).toEqual(copia);
    expect(e).toEqual(copia);
  });
});

describe("reformatear: redondeo half-to-even como Python round()", () => {
  const conAlto = (h: number): Escena => ({
    v: 2,
    lienzo: { w: 1080, h, formato: "4x5", fondo: { tipo: "color", valor: "#ffffff" } },
    tokens: { colores: {} },
    capas: [capa("c_med", 100, "center")],
  });

  it("dy=+5 (2.5): Python da 2, no 3", () => {
    expect(y(reformatear(conAlto(1345), "4x5"), "c_med")).toBe(102);
  });

  it("dy=-3 (-1.5): Python da -2, no -1", () => {
    expect(y(reformatear(conAlto(1353), "4x5"), "c_med")).toBe(98);
  });

  it("dy=+3 (1.5) y dy=+7 (3.5) suben al par", () => {
    expect(y(reformatear(conAlto(1347), "4x5"), "c_med")).toBe(102);
    expect(y(reformatear(conAlto(1343), "4x5"), "c_med")).toBe(104);
  });

  it("dy=-5 (-2.5) baja a -2", () => {
    expect(y(reformatear(conAlto(1355), "4x5"), "c_med")).toBe(98);
  });

  it("sin anclaje se deduce del tercio, como _anclaje_de", () => {
    const e = escenaReformato();
    for (const c of e.capas) if (c.id === "c_foto") delete (c as Partial<Capa>).anclaje;
    // centro 650 cae en el tercio medio de 1350 → center → +285
    expect(y(reformatear(e, "9x16"), "c_foto")).toBe(885);
  });
});

describe("utilidades", () => {
  const e = fixture.base;

  it("árbol: padre, raíz, descendientes, ocultas", () => {
    expect(padreDe(e, "logo")).toBe("marca");
    expect(padreDe(e, "titulo")).toBeNull();
    expect(raizDe(e, "caja")).toBe("marca");
    expect(descendientes(e, "marca").sort()).toEqual(["caja", "logo"]);
    const oculto = aplicarOps(e, [{ op: "set", capa: "marca", ruta: "oculta", valor: true }]);
    expect([...ocultasEfectivas(oculto)].sort()).toEqual(["caja", "logo", "marca"]);
  });

  it("ordenadas va por z ascendente", () => {
    expect(ordenadas(e).map((c) => c.id)).toEqual(["marca", "caja", "logo", "titulo"]);
  });

  it("resolverColor", () => {
    expect(resolverColor("token:marca", e.tokens, "#ff5500")).toBe("#ff5500");
    expect(resolverColor("token:tinta", e.tokens, "#ff5500")).toBe("#111111");
    expect(resolverColor("token:nada", e.tokens, "#ff5500")).toBe("transparent");
    expect(resolverColor("#abcdef", e.tokens, "#ff5500")).toBe("#abcdef");
  });

  it("idLibre limpia acentos y numera", () => {
    expect(idLibre(e, "Título Grande")).toBe("titulo_grande");
    expect(idLibre(e, "titulo")).toBe("titulo_2");
    expect(idLibre(e, "9 vidas")).toBe("c_9_vidas");
    expect(idLibre(e, "x".repeat(40))).toHaveLength(26);
  });

  it("capaNueva centra y sube z", () => {
    const t = capaNueva("text", e, { fuente: "Inter" });
    expect(t).toMatchObject({ tipo: "text", x: 140, y: 595, w: 800, h: 160, z: 4, estilo: { fontFamily: "Inter" } });
    const f = capaNueva("shape", e, { fuente: "Inter" });
    expect(f).toMatchObject({ tipo: "shape", w: 400, h: 400, estilo: { fill: "token:marca" } });
    expect(() => capaNueva("image", e, { fuente: "Inter" })).toThrow();
  });

  it("urlDeAsset y normalizarAngulo", () => {
    expect(urlDeAsset("gdlscene", "assets/foto 1.png")).toBe("/api/brands/gdlscene/files/assets/foto%201.png");
    expect(normalizarAngulo(190)).toBe(-170);
    expect(normalizarAngulo(-190)).toBe(170);
    expect(normalizarAngulo(180)).toBe(180);
  });
});

describe("imanActivo", () => {
  it("el imán numérico del backend activa el snap; 0 lo apaga; sin guías queda activo", () => {
    expect(imanActivo({ cols: 12, filas: 15, iman: 8 })).toBe(true);
    expect(imanActivo({ cols: 0, filas: 0, iman: 0 })).toBe(false);
    expect(imanActivo(undefined)).toBe(true);
  });
});
