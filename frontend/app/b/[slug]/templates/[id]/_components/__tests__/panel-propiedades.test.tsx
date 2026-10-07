import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { CapaTexto, Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { PanelPropiedades } from "../panel-propiedades";

const base = datos.base as unknown as Escena;
const st = () => useEditor.getState();
const capa = (id: string) => st().escena!.capas.find((c) => c.id === id)!;
const campo = (nombre: string) => screen.getByRole("spinbutton", { name: nombre }) as HTMLInputElement;

function montar(seleccion: string[] = []) {
  st().vaciar();
  st().cargar(structuredClone(base));
  st().seleccionar(seleccion);
  render(<PanelPropiedades colorMarca="#ff3366" />);
}

describe("PanelPropiedades", () => {
  beforeEach(() => st().vaciar());

  it("sin selección cambia el formato del lienzo", () => {
    montar();
    fireEvent.change(screen.getByRole("combobox", { name: "Formato" }), { target: { value: "1x1" } });
    expect(st().escena!.lienzo.formato).toBe("1x1");
    expect(st().escena!.lienzo.h).toBe(1080);
    expect(st().pasado).toHaveLength(1);
  });

  it("sin selección cambia el fondo a un token", () => {
    montar();
    fireEvent.change(screen.getByRole("combobox", { name: "Fondo" }), { target: { value: "token:tinta" } });
    expect(st().escena!.lienzo.fondo).toEqual({ tipo: "color", valor: "token:tinta" });
  });

  it("con varias muestra el conteo", () => {
    montar(["titulo", "marca"]);
    expect(screen.queryByText("2 capas seleccionadas")).not.toBeNull();
  });

  it("X confirma en blur con un paso", () => {
    montar(["titulo"]);
    fireEvent.change(campo("X"), { target: { value: "100" } });
    fireEvent.blur(campo("X"));
    expect(capa("titulo").x).toBe(100);
    expect(st().pasado).toHaveLength(1);
  });

  it("Ancho confirma con Enter", () => {
    montar(["titulo"]);
    fireEvent.change(campo("Ancho"), { target: { value: "500" } });
    fireEvent.keyDown(campo("Ancho"), { key: "Enter" });
    expect(capa("titulo").w).toBe(500);
  });

  it("un valor inválido regresa sin paso", () => {
    montar(["titulo"]);
    fireEvent.change(campo("Ancho"), { target: { value: "" } });
    fireEvent.blur(campo("Ancho"));
    expect(capa("titulo").w).toBe(920);
    expect(campo("Ancho").value).toBe("920");
    expect(st().pasado).toHaveLength(0);
  });

  it("un grupo mueve a sus hijos y no se redimensiona", () => {
    montar(["marca"]);
    expect(campo("Ancho").disabled).toBe(true);
    fireEvent.change(campo("Y"), { target: { value: "1000" } });
    fireEvent.blur(campo("Y"));
    expect(capa("caja").y).toBe(1000);
    expect(capa("logo").y).toBe(1030);
    expect(st().pasado).toHaveLength(1);
  });

  it("opacidad en por ciento", () => {
    montar(["titulo"]);
    fireEvent.change(campo("Opacidad"), { target: { value: "50" } });
    fireEvent.blur(campo("Opacidad"));
    expect(capa("titulo").opacity).toBe(0.5);
  });

  it("color del texto desde los tokens", () => {
    montar(["titulo"]);
    fireEvent.change(screen.getByRole("combobox", { name: "Color" }), { target: { value: "token:marca" } });
    expect((capa("titulo") as CapaTexto).estilo.color).toBe("token:marca");
  });
});
