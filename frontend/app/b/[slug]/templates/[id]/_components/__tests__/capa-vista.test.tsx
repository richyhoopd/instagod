import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import { aplicarOps, type Capa, type Escena, type Op } from "@/lib/escena";
import { Escenario, fondoCss, radioDeMascara } from "../capa-vista";

const base = datos.base as unknown as Escena;
const con = (ops: Op[]) => aplicarOps(base, ops);
const pintar = (escena: Escena) =>
  render(<Escenario escena={escena} slug="gdlscene" colorMarca="#e11d48" />).container;

describe("Escenario", () => {
  it("pinta los tramos de color del texto", () => {
    pintar(con([{ op: "set", capa: "titulo", ruta: "estilo.spans", valor: [{ desde: 0, hasta: 4, color: "#ff0000" }] }]));
    expect(screen.getByText("Hola").style.color).toBe("rgb(255, 0, 0)");
    expect(screen.getByText("mundo", { exact: false }).style.color).toBe("");
  });

  it("white-space igual que escena.py: pre-line, pre si nowrap; el dato del post no respeta saltos", () => {
    const caja = (escena: Escena) => pintar(escena).querySelector<HTMLElement>('[data-id="titulo"] > div')!;
    expect(caja(base).style.whiteSpace).toBe("pre-line");
    expect(caja(con([{ op: "set", capa: "titulo", ruta: "estilo.textWrap", valor: "nowrap" }])).style.whiteSpace).toBe("pre");
    expect(caja(con([{ op: "set", capa: "titulo", ruta: "campo", valor: "titulo" }])).style.whiteSpace).toBe("");
    expect(pintar(base).querySelector<HTMLElement>('[data-id="titulo"]')!.style.overflow).toBe("hidden");
  });

  it("no pinta una capa oculta", () => {
    const c = pintar(con([{ op: "set", capa: "titulo", ruta: "oculta", valor: true }]));
    expect(c.querySelector('[data-id="titulo"]')).toBeNull();
    expect(c.querySelector('[data-id="caja"]')).not.toBeNull();
  });

  it("un grupo oculto esconde a sus hijos", () => {
    const c = pintar(con([{ op: "set", capa: "marca", ruta: "oculta", valor: true }]));
    expect(c.querySelector('[data-id="caja"]')).toBeNull();
    expect(c.querySelector('[data-id="logo"]')).toBeNull();
  });

  it("un grupo no pinta nada propio", () => {
    const c = pintar(base);
    expect(c.querySelector('[data-id="marca"]')).toBeNull();
    expect(c.querySelectorAll(".capa")).toHaveLength(3);
  });

  it("una imagen sin src muestra su campo", () => {
    const foto: Capa = {
      id: "foto", nombre: "Foto", tipo: "image", x: 0, y: 0, w: 500, h: 500, rot: 0, opacity: 1, z: 5,
      bloqueada: false, oculta: false, anclaje: "center", src: null, campo: "foto", ajuste: "cover",
      mascara: "none", estilo: {},
    };
    pintar(con([{ op: "add", capa: foto }]));
    expect(screen.getByText("Campo: foto")).toBeTruthy();
  });

  it("elipse redonda y token:marca resuelto", () => {
    const c = pintar(con([{ op: "set", capa: "caja", ruta: "forma", valor: "ellipse" }]));
    const relleno = c.querySelector<HTMLElement>('[data-id="caja"] > div')!;
    expect(relleno.style.borderRadius).toBe("50%");
    expect(relleno.style.backgroundColor).toBe("rgb(225, 29, 72)");
  });
});

describe("helpers de estilo", () => {
  it("fondoCss y radioDeMascara", () => {
    const t = { colores: { tinta: "#111111" } };
    expect(fondoCss({ tipo: "color", valor: "token:tinta" }, t, "#e11d48", "x")).toBe("#111111");
    expect(fondoCss({ tipo: "gradiente", valor: "linear-gradient(#fff, #000)" }, t, "#e11d48", "x")).toBe(
      "linear-gradient(#fff, #000)",
    );
    expect(fondoCss({ tipo: "imagen", valor: "assets/fondo 1.jpg" }, t, "#e11d48", "gdl")).toBe(
      "url('/api/brands/gdl/files/assets/fondo%201.jpg') center/cover no-repeat",
    );
    expect(radioDeMascara("none")).toBeUndefined();
    expect(radioDeMascara("circle")).toBe("50%");
    expect(radioDeMascara("rounded:24")).toBe("24px");
  });
});
