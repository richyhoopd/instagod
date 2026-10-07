import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { CapaTexto, Escena } from "@/lib/escena";
import { MAX_TEXTO } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { EditorTexto } from "../editor-texto";

const base = datos.base as unknown as Escena;
const titulo = () => useEditor.getState().escena!.capas.find((c) => c.id === "titulo") as CapaTexto;

function montar() {
  const st = useEditor.getState();
  st.cargar(structuredClone(base));
  st.editarTexto("titulo");
  render(<EditorTexto capa={titulo()} tokens={base.tokens} colorMarca="#ff3366" zoom={1} />);
  return screen.getByRole("textbox") as HTMLTextAreaElement;
}

describe("EditorTexto", () => {
  beforeEach(() => useEditor.getState().vaciar());

  it("teclear y salir es un solo paso", () => {
    const ta = montar();
    expect(document.activeElement).toBe(ta);
    fireEvent.change(ta, { target: { value: "Hola mundo!" } });
    fireEvent.change(ta, { target: { value: "Hola mundo!!" } });
    fireEvent.blur(ta);
    expect(titulo().texto).toBe("Hola mundo!!");
    expect(useEditor.getState().pasado).toHaveLength(1);
    expect(useEditor.getState().editandoTexto).toBeNull();
  });

  it("Escape confirma", () => {
    const ta = montar();
    fireEvent.change(ta, { target: { value: "Adiós" } });
    fireEvent.keyDown(ta, { key: "Escape" });
    expect(titulo().texto).toBe("Adiós");
    expect(useEditor.getState().editandoTexto).toBeNull();
  });

  it("sin cambios no hay paso", () => {
    const ta = montar();
    fireEvent.blur(ta);
    expect(useEditor.getState().pasado).toHaveLength(0);
    expect(useEditor.getState().editandoTexto).toBeNull();
  });

  it("pinta el tramo seleccionado", () => {
    const ta = montar();
    ta.setSelectionRange(0, 4);
    const boton = screen.getByRole("button", { name: "Color tinta" });
    fireEvent.mouseDown(boton);
    fireEvent.click(boton);
    fireEvent.blur(ta);
    expect(titulo().estilo.spans).toEqual([{ desde: 0, hasta: 4, color: "token:tinta" }]);
    expect(titulo().texto).toBe("Hola mundo");
    expect(useEditor.getState().pasado).toHaveLength(1);
  });

  it("limita el largo del texto", () => {
    const ta = montar();
    expect(ta.maxLength).toBe(MAX_TEXTO);
  });

  it("la selección UTF-16 se convierte a code points al pintar", () => {
    const ta = montar();
    fireEvent.change(ta, { target: { value: "😀 Hola" } });
    // UTF-16: "😀"=0-2, " "=2-3, "Hola"=3-7. En code points: 2-6.
    ta.setSelectionRange(3, 7);
    const boton = screen.getByRole("button", { name: "Color tinta" });
    fireEvent.mouseDown(boton);
    fireEvent.click(boton);
    fireEvent.blur(ta);
    expect(titulo().estilo.spans).toEqual([{ desde: 2, hasta: 6, color: "token:tinta" }]);
  });

  it("ajusta los tramos con la posición del cursor (letra repetida)", () => {
    const ta = montar();
    fireEvent.change(ta, { target: { value: "aa" } });
    ta.setSelectionRange(0, 1);
    const boton = screen.getByRole("button", { name: "Color tinta" });
    fireEvent.click(boton);
    // Se teclea una "a" al inicio: el cursor queda en 1.
    fireEvent.change(ta, { target: { value: "aaa", selectionStart: 1, selectionEnd: 1 } });
    fireEvent.blur(ta);
    expect(titulo().estilo.spans).toEqual([{ desde: 1, hasta: 2, color: "token:tinta" }]);
  });
});
