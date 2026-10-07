import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import { ordenadas, type Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { useAtajos } from "../use-atajos";

const base = datos.base as unknown as Escena;
const st = () => useEditor.getState();
const capa = (id: string) => st().escena!.capas.find((c) => c.id === id)!;
const hojas = (e: Escena) => ordenadas(e).filter((c) => c.tipo !== "group").map((c) => c.id);
const tecla = (key: string, extra: Partial<KeyboardEventInit> & { code?: string } = {}) =>
  fireEvent.keyDown(window, { key, ...extra });

function Arnes({ activo = true }: { activo?: boolean }) {
  useAtajos(activo);
  return <input aria-label="nombre" />;
}

describe("useAtajos", () => {
  beforeEach(() => {
    st().vaciar();
    st().cargar(structuredClone(base));
    render(<Arnes />);
  });

  it("deshacer y rehacer con ⌘ o Ctrl", () => {
    st().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 10 }]);
    tecla("z", { metaKey: true });
    expect(capa("titulo").x).toBe(80);
    tecla("Z", { metaKey: true, shiftKey: true });
    expect(capa("titulo").x).toBe(10);
    tecla("z", { ctrlKey: true });
    expect(capa("titulo").x).toBe(80);
    tecla("y", { ctrlKey: true });
    expect(capa("titulo").x).toBe(10);
  });

  it("las flechas mueven 1 px y con shift 10 px", () => {
    st().seleccionar(["titulo"]);
    tecla("ArrowRight");
    expect(capa("titulo").x).toBe(81);
    tecla("ArrowDown", { shiftKey: true });
    expect(capa("titulo").y).toBe(206);
  });

  it("⌘D mantenido: el repeat no duplica pero sí se bloquea en el navegador", () => {
    st().seleccionar(["titulo"]);
    const n = st().escena!.capas.length;
    tecla("d", { metaKey: true });
    expect(st().escena!.capas.length).toBe(n + 1);
    const noBloqueado = tecla("d", { metaKey: true, repeat: true });
    expect(noBloqueado).toBe(false);
    expect(st().escena!.capas.length).toBe(n + 1);
  });

  it("⌘D repetido sin selección no se bloquea", () => {
    st().seleccionar([]);
    expect(tecla("d", { metaKey: true, repeat: true })).toBe(true);
  });

  it("Escape quita la selección", () => {
    st().seleccionar(["titulo"]);
    tecla("Escape");
    expect(st().seleccion).toEqual([]);
  });

  it("Supr borra", () => {
    st().seleccionar(["titulo"]);
    tecla("Delete");
    expect(st().escena!.capas).toHaveLength(3);
  });

  it("⌘D duplica y evita el atajo del navegador", () => {
    st().seleccionar(["titulo"]);
    const siguio = tecla("d", { metaKey: true });
    expect(siguio).toBe(false);
    expect(st().escena!.capas).toHaveLength(5);
  });

  it("⌘G agrupa y ⇧⌘G desagrupa", () => {
    st().seleccionar(["titulo", "marca"]);
    tecla("g", { metaKey: true });
    expect(st().escena!.capas).toHaveLength(5);
    tecla("G", { metaKey: true, shiftKey: true });
    expect(st().escena!.capas).toHaveLength(4);
  });

  it("⌘[ baja por code, no por key", () => {
    st().seleccionar(["titulo"]);
    tecla("[", { metaKey: true, code: "BracketLeft" });
    expect(hojas(st().escena!)).toEqual(["caja", "titulo", "logo"]);
  });

  it("⌘C y ⌘V pegan una copia", () => {
    st().seleccionar(["titulo"]);
    tecla("c", { metaKey: true });
    tecla("v", { metaKey: true });
    expect(st().escena!.capas).toHaveLength(5);
  });

  it("no actúa con un campo de texto enfocado", () => {
    st().seleccionar(["titulo"]);
    const siguio = fireEvent.keyDown(screen.getByRole("textbox", { name: "nombre" }), { key: "Backspace" });
    expect(siguio).toBe(true);
    expect(st().escena!.capas).toHaveLength(4);
  });

  it("no actúa mientras se edita un texto en el lienzo", () => {
    st().seleccionar(["titulo"]);
    st().editarTexto("titulo");
    tecla("Delete");
    expect(st().escena!.capas).toHaveLength(4);
  });

  it("Backspace/Delete y demás atajos en el textarea de edición de texto no tocan la capa", () => {
    st().seleccionar(["titulo"]);
    const { unmount } = render(<textarea data-editor-texto aria-label="texto" />);
    const ta = screen.getByRole("textbox", { name: "texto" });
    const antes = JSON.stringify(st().escena);
    for (const init of [
      { key: "Backspace" },
      { key: "Delete" },
      { key: "ArrowRight" },
      { key: "ArrowDown", shiftKey: true },
      { key: "Escape" },
      { key: "z", metaKey: true },
      { key: "d", metaKey: true },
      { key: "g", metaKey: true },
    ]) {
      expect(fireEvent.keyDown(ta, init)).toBe(true);
    }
    expect(JSON.stringify(st().escena)).toBe(antes);
    expect(st().seleccion).toEqual(["titulo"]);
    unmount();
  });

  it("tampoco con un input, un select o un contenteditable enfocado", () => {
    st().seleccionar(["titulo"]);
    const antes = JSON.stringify(st().escena);
    const ce = document.createElement("div");
    ce.setAttribute("contenteditable", "true");
    const sel = document.createElement("select");
    document.body.append(ce, sel);
    for (const el of [screen.getByRole("textbox", { name: "nombre" }), ce, sel]) {
      for (const key of ["Backspace", "Delete", "ArrowLeft"]) {
        expect(fireEvent.keyDown(el, { key })).toBe(true);
      }
    }
    expect(JSON.stringify(st().escena)).toBe(antes);
    ce.remove();
    sel.remove();
  });

  it("no actúa dentro de un diálogo", () => {
    st().seleccionar(["titulo"]);
    const { unmount } = render(
      <div role="dialog">
        <button>ok</button>
      </div>,
    );
    expect(fireEvent.keyDown(screen.getByRole("button", { name: "ok" }), { key: "Delete" })).toBe(true);
    expect(st().escena!.capas).toHaveLength(4);
    unmount();
  });

  it("sin selección no bloquea flechas, Supr, ⌘C, ⌘D ni ⌘G", () => {
    st().seleccionar([]);
    const antes = JSON.stringify(st().escena);
    for (const init of [
      { key: "ArrowDown" },
      { key: "ArrowLeft", shiftKey: true },
      { key: "Delete" },
      { key: "Backspace" },
      { key: "c", metaKey: true },
      { key: "d", metaKey: true },
      { key: "g", metaKey: true },
      { key: "Escape" },
    ]) {
      expect(fireEvent.keyDown(window, init)).toBe(true);
    }
    expect(JSON.stringify(st().escena)).toBe(antes);
  });

  it("⌘V sin portapapeles y ⌘Z sin historia no bloquean", () => {
    expect(fireEvent.keyDown(window, { key: "v", metaKey: true })).toBe(true);
    expect(fireEvent.keyDown(window, { key: "z", metaKey: true })).toBe(true);
  });

  it("con selección sí bloquea flechas y ⌘C", () => {
    st().seleccionar(["titulo"]);
    expect(fireEvent.keyDown(window, { key: "ArrowRight" })).toBe(false);
    expect(fireEvent.keyDown(window, { key: "c", metaKey: true })).toBe(false);
  });

  it("con activo=false no muta el store ni bloquea teclas", () => {
    cleanup();
    render(<Arnes activo={false} />);
    st().seleccionar(["titulo"]);
    const antes = JSON.stringify(st().escena);
    for (const init of [
      { key: "ArrowRight" },
      { key: "Delete" },
      { key: "d", metaKey: true },
      { key: "z", metaKey: true },
      { key: "g", metaKey: true },
    ]) {
      expect(fireEvent.keyDown(window, init)).toBe(true);
    }
    expect(JSON.stringify(st().escena)).toBe(antes);
  });

  it("ignora teclas de composición (IME)", () => {
    st().seleccionar(["titulo"]);
    tecla("ArrowRight", { isComposing: true });
    tecla("Delete", { keyCode: 229 });
    expect(capa("titulo").x).toBe(80);
    expect(st().escena!.capas).toHaveLength(4);
  });

  it("e.repeat se ignora en ⌘D/⌘V/⌘G/⌘Z pero no en flechas", () => {
    st().seleccionar(["titulo"]);
    tecla("d", { metaKey: true, repeat: true });
    expect(st().escena!.capas).toHaveLength(4);
    tecla("z", { metaKey: true, repeat: true });
    st().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 10 }]);
    tecla("z", { metaKey: true, repeat: true });
    expect(capa("titulo").x).toBe(10);
    tecla("ArrowRight", { repeat: true });
    expect(capa("titulo").x).toBe(11);
  });
});
