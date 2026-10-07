import { describe, expect, it } from "vitest";
import datos from "../__fixtures__/ops-casos.json";
import { aplicarOps, MAX_CAPAS, ordenadas, type Capa, type Escena } from "../escena";
import {
  conCajasDeGrupo,
  esCampoDeTexto,
  expandir,
  opsAgrupar,
  opsAlinear,
  opsDesagrupar,
  opsDistribuir,
  opsDuplicar,
  opsMover,
  opsPegar,
  opsReordenar,
  opsZ,
} from "../edicion";

const base = () => structuredClone((datos as unknown as { base: Escena }).base);
const capa = (e: Escena, id: string) => e.capas.find((c) => c.id === id)!;
const hojas = (e: Escena) => ordenadas(e).filter((c) => c.tipo !== "group").map((c) => c.id);
// Aplica y recalcula cajas de grupo, como hace el store.
const correr = (e: Escena, ops: Parameters<typeof aplicarOps>[1]) => aplicarOps(e, conCajasDeGrupo(e, ops));

describe("mover", () => {
  it("expandir baja a las hojas", () => {
    expect(expandir(base(), ["marca", "titulo"]).sort()).toEqual(["caja", "logo", "titulo"]);
  });
  it("mover un grupo mueve sus hijos y recalcula su caja", () => {
    const e = base();
    const r = correr(e, opsMover(e, ["marca"], 10.4, -20));
    expect(capa(r, "caja")).toMatchObject({ x: 10, y: 1180 });
    expect(capa(r, "logo")).toMatchObject({ x: 910, y: 1210 });
    expect(capa(r, "marca")).toMatchObject({ x: 10, y: 1180, w: 1080, h: 150 });
  });
  it("una capa bloqueada no se mueve", () => {
    const e = aplicarOps(base(), [{ op: "set", capa: "logo", ruta: "bloqueada", valor: true }]);
    expect(opsMover(e, ["marca"], 5, 5).some((o) => o.op === "set" && o.capa === "logo")).toBe(false);
  });
});

describe("alinear y distribuir", () => {
  it("una sola capa se alinea al lienzo", () => {
    const e = base();
    const r = correr(e, opsAlinear(e, ["titulo"], "centro-h"));
    expect(capa(r, "titulo").x).toBe(80); // ya estaba centrada: (1080 − 920) / 2
    const r2 = correr(e, opsAlinear(e, ["titulo"], "abajo"));
    expect(capa(r2, "titulo").y).toBe(1050);
  });
  it("varias se alinean a su unión", () => {
    const e = base();
    const r = correr(e, opsAlinear(e, ["titulo", "logo"], "der"));
    expect(capa(r, "titulo").x + capa(r, "titulo").w).toBe(1020);
    expect(capa(r, "logo").x + capa(r, "logo").w).toBe(1020);
  });
  it("distribuir necesita tres", () => {
    const e = base();
    expect(opsDistribuir(e, ["titulo", "logo"], "h")).toEqual([]);
  });
  it("distribuir reparte el hueco", () => {
    const e = aplicarOps(base(), [
      { op: "set", capa: "titulo", ruta: "w", valor: 100 },
      { op: "set", capa: "titulo", ruta: "x", valor: 0 },
      { op: "set", capa: "caja", ruta: "w", valor: 100 },
      { op: "set", capa: "caja", ruta: "x", valor: 100 },
      { op: "set", capa: "logo", ruta: "w", valor: 100 },
      { op: "set", capa: "logo", ruta: "x", valor: 900 },
    ]);
    const r = aplicarOps(e, opsDistribuir(e, ["titulo", "caja", "logo"], "h"));
    expect(capa(r, "caja").x).toBe(450);
  });
});

describe("grupos", () => {
  it("agrupar crea el grupo con la caja de la unión", () => {
    const e = base();
    const g = opsAgrupar(e, ["caja", "titulo"]);
    expect(g).toBeNull(); // padres distintos: caja está en marca, titulo en la raíz
    const g2 = opsAgrupar(e, ["titulo", "marca"])!;
    const r = correr(e, g2.ops);
    expect(g2.id).toBe("grupo");
    expect(capa(r, "grupo")).toMatchObject({ tipo: "group", hijos: ["titulo", "marca"], x: 0, y: 196, w: 1080, h: 1154 });
  });
  it("agrupar dentro de un grupo reemplaza los hijos del padre", () => {
    const e = base();
    const g = opsAgrupar(e, ["caja", "logo"])!;
    const r = correr(e, g.ops);
    expect(capa(r, "marca")).toMatchObject({ hijos: ["grupo"] });
    expect(capa(r, "grupo")).toMatchObject({ hijos: ["caja", "logo"] });
  });
  it("desagrupar devuelve los hijos al padre y borra el grupo", () => {
    const e = base();
    const d = opsDesagrupar(e, "marca")!;
    const r = correr(e, d.ops);
    expect(d.hijos).toEqual(["caja", "logo"]);
    expect(r.capas.map((c) => c.id)).toEqual(["titulo", "caja", "logo"]);
  });
  it("desagrupar algo que no es grupo es null", () => {
    expect(opsDesagrupar(base(), "titulo")).toBeNull();
  });
});

describe("duplicar y pegar", () => {
  it("duplicar un grupo clona sus hijos con ids nuevos y los sube al frente", () => {
    const e = base();
    const d = opsDuplicar(e, ["marca"]);
    const r = correr(e, d.ops);
    expect(d.nuevos).toEqual(["marca_2"]);
    expect(capa(r, "marca_2")).toMatchObject({ hijos: ["caja_2", "logo_2"], x: 20, y: 1220 });
    expect(capa(r, "caja_2")).toMatchObject({ x: 20, y: 1220 });
    expect(Math.min(capa(r, "caja_2").z, capa(r, "logo_2").z)).toBeGreaterThan(3);
  });
  it("pegar sobre una escena sin esas capas conserva los ids", () => {
    const e = base();
    const vacia = { ...e, capas: [] };
    const p = opsPegar(vacia, [capa(e, "titulo")]);
    expect(p.nuevos).toEqual(["titulo"]);
  });
});

describe("orden z", () => {
  it("frente y fondo", () => {
    const e = base();
    expect(hojas(aplicarOps(e, opsZ(e, ["caja"], "frente")))).toEqual(["logo", "titulo", "caja"]);
    expect(hojas(aplicarOps(e, opsZ(e, ["titulo"], "fondo")))).toEqual(["titulo", "caja", "logo"]);
  });
  it("subir y bajar un paso", () => {
    const e = base();
    expect(hojas(aplicarOps(e, opsZ(e, ["caja"], "subir")))).toEqual(["logo", "caja", "titulo"]);
    expect(hojas(aplicarOps(e, opsZ(e, ["titulo"], "bajar")))).toEqual(["caja", "titulo", "logo"]);
  });
  it("subir lo que ya está arriba no genera ops", () => {
    const e = base();
    expect(opsZ(e, ["titulo"], "subir")).toEqual([]);
  });
  it("reordenar hermanos mueve el bloque del grupo completo", () => {
    const e = base();
    // Raíces de arriba hacia abajo: marca arriba de titulo.
    expect(hojas(aplicarOps(e, opsReordenar(e, ["marca", "titulo"])))).toEqual(["titulo", "caja", "logo"]);
  });
});

describe("esCampoDeTexto", () => {
  it("reconoce input, textarea y contenteditable", () => {
    const div = document.createElement("div");
    div.contentEditable = "true";
    expect(esCampoDeTexto(document.createElement("input"))).toBe(true);
    expect(esCampoDeTexto(document.createElement("textarea"))).toBe(true);
    expect(esCampoDeTexto(document.createElement("button"))).toBe(false);
    expect(esCampoDeTexto(null)).toBe(false);
  });
});

describe("límites del validador", () => {
  const llena = (e: Escena) => {
    const extra = Array.from({ length: MAX_CAPAS - e.capas.length }, (_, i) => ({ ...capa(e, "caja"), id: `r${i}`, z: 10 + i }) as Capa);
    return { ...e, capas: [...e.capas, ...extra] };
  };
  it("duplicar y agrupar respetan MAX_CAPAS", () => {
    const e = llena(base());
    expect(opsDuplicar(e, ["titulo"]).ops).toEqual([]);
    expect(opsAgrupar(e, ["titulo", "marca"])).toBeNull();
  });
  it("pegar un grupo sin sus hijos no deja grupos vacíos", () => {
    const e = base();
    const p = opsPegar({ ...e, capas: [] }, [capa(e, "marca")]);
    expect(p.ops).toEqual([]);
  });
  it("las copias respetan el rango de x/y y z <= 999", () => {
    const e = aplicarOps(base(), [{ op: "set", capa: "titulo", ruta: "x", valor: 3990 }]);
    const r = aplicarOps(e, opsDuplicar(e, ["titulo"]).ops);
    expect(capa(r, "titulo_2").x).toBeLessThanOrEqual(4000);
  });
});
