import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import { aplicarOps, type Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { filasDeCapas, PanelCapas, reordenarFilas } from "../panel-capas";

const base = datos.base as unknown as Escena;
const ids = (e: Escena) => filasDeCapas(e).map((f) => f.id);
const capa = (id: string) => useEditor.getState().escena!.capas.find((c) => c.id === id)!;

describe("filasDeCapas y reordenarFilas", () => {
  it("ordena por z efectiva con los hijos debajo del grupo", () => {
    const f = filasDeCapas(base);
    expect(f.map((x) => x.id)).toEqual(["titulo", "marca", "logo", "caja"]);
    expect(f.map((x) => x.nivel)).toEqual([0, 0, 1, 1]);
    expect(f[2].padre).toBe("marca");
  });

  it("sube un grupo sobre una raíz", () => {
    const ops = reordenarFilas(base, "marca", "titulo")!;
    expect(ids(aplicarOps(base, ops))).toEqual(["marca", "logo", "caja", "titulo"]);
  });

  it("reordena hijos dentro del grupo", () => {
    const ops = reordenarFilas(base, "logo", "caja")!;
    expect(ids(aplicarOps(base, ops))).toEqual(["titulo", "marca", "caja", "logo"]);
  });

  it("no mezcla niveles", () => {
    expect(reordenarFilas(base, "logo", "titulo")).toBeNull();
  });
});

describe("PanelCapas", () => {
  beforeEach(() => {
    useEditor.getState().vaciar();
    useEditor.getState().cargar(structuredClone(base));
    render(<PanelCapas />);
  });

  it("clic selecciona y shift-clic alterna", () => {
    fireEvent.click(screen.getByText("Título"));
    expect(useEditor.getState().seleccion).toEqual(["titulo"]);
    fireEvent.click(screen.getByText("Caja"), { shiftKey: true });
    expect(useEditor.getState().seleccion).toEqual(["titulo", "caja"]);
    fireEvent.click(screen.getByText("Título"), { shiftKey: true });
    expect(useEditor.getState().seleccion).toEqual(["caja"]);
  });

  it("el ojo oculta en un paso", () => {
    fireEvent.click(screen.getByRole("button", { name: "Ocultar Título" }));
    expect(capa("titulo").oculta).toBe(true);
    expect(useEditor.getState().pasado).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Mostrar Título" })).not.toBeNull();
  });

  it("el candado bloquea en un paso", () => {
    fireEvent.click(screen.getByRole("button", { name: "Bloquear Título" }));
    expect(capa("titulo").bloqueada).toBe(true);
    expect(useEditor.getState().pasado).toHaveLength(1);
  });

  it("doble clic renombra con Enter", () => {
    fireEvent.doubleClick(screen.getByText("Título"));
    const input = screen.getByRole("textbox", { name: "Nombre de la capa" });
    fireEvent.change(input, { target: { value: "  Encabezado  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(capa("titulo").nombre).toBe("Encabezado");
    expect(useEditor.getState().pasado).toHaveLength(1);
  });

  it("Escape cancela el renombre", () => {
    fireEvent.doubleClick(screen.getByText("Título"));
    const input = screen.getByRole("textbox", { name: "Nombre de la capa" });
    fireEvent.change(input, { target: { value: "Otro" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(capa("titulo").nombre).toBe("Título");
    expect(useEditor.getState().pasado).toHaveLength(0);
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
