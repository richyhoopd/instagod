import { beforeEach, describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import { capaNueva, OpInvalida, type Escena } from "@/lib/escena";
import { LIMITE_HISTORIA, useEditor } from "../editor";

const base = datos.base as unknown as Escena;
const ed = () => useEditor.getState();
const capa = (id: string) => ed().escena!.capas.find((c) => c.id === id)!;

beforeEach(() => {
  useEditor.setState(useEditor.getInitialState(), true);
  ed().cargar(structuredClone(base));
});

describe("store del editor", () => {
  it("cargar deja la historia vacía y la escena limpia", () => {
    expect(ed().pasado).toEqual([]);
    expect(ed().futuro).toEqual([]);
    expect(ed().sucio).toBe(false);
    expect(ed().seleccion).toEqual([]);
  });

  it("aplicar es un paso", () => {
    ed().aplicar(
      [
        { op: "set", capa: "titulo", ruta: "x", valor: 100 },
        { op: "set", capa: "titulo", ruta: "y", valor: 200 },
      ],
      "Mover",
    );
    expect(ed().pasado).toHaveLength(1);
    expect(ed().pasado[0].etiqueta).toBe("Mover");
    expect(ed().sucio).toBe(true);
    ed().deshacer();
    expect(capa("titulo").x).toBe(80);
    expect(capa("titulo").y).toBe(196);
    expect(ed().futuro).toHaveLength(1);
    ed().rehacer();
    expect(capa("titulo").x).toBe(100);
    expect(capa("titulo").y).toBe(200);
  });

  it("la caja del grupo va en el mismo paso", () => {
    ed().aplicar([{ op: "set", capa: "logo", ruta: "y", valor: 1000 }]);
    expect(ed().pasado).toHaveLength(1);
    expect(capa("marca").y).toBe(1000);
    expect(capa("marca").h).toBe(350);
    ed().deshacer();
    expect(capa("marca").y).toBe(1200);
    expect(capa("marca").h).toBe(150);
    expect(capa("logo").y).toBe(1230);
  });

  it("una op inválida lanza y no registra nada", () => {
    expect(() => ed().aplicar([{ op: "del", capa: "nadie" }])).toThrow(OpInvalida);
    expect(ed().pasado).toEqual([]);
    expect(ed().sucio).toBe(false);
  });

  it("aplicar sin cambios no crea paso", () => {
    ed().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 80 }]);
    ed().aplicar([]);
    expect(ed().pasado).toEqual([]);
  });

  it("cambiarFormato es un paso y se deshace", () => {
    ed().cambiarFormato("9x16");
    expect(ed().escena!.lienzo.h).toBe(1920);
    expect(ed().escena!.lienzo.formato).toBe("9x16");
    ed().cambiarFormato("9x16");
    expect(ed().pasado).toHaveLength(1);
    ed().deshacer();
    expect(ed().escena!.lienzo.h).toBe(1350);
    expect(ed().escena!.lienzo.formato).toBe("4x5");
  });

  it("una edición durante el guardado deja sucio", () => {
    ed().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 1 }]);
    const enVuelo = ed().revision;
    ed().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 2 }]);
    ed().marcarGuardado(enVuelo);
    expect(ed().sucio).toBe(true);
    ed().marcarGuardado(ed().revision);
    expect(ed().sucio).toBe(false);
  });

  it("la selección se filtra a capas existentes, sin repetir", () => {
    ed().seleccionar(["nadie", "caja", "caja", "titulo"]);
    expect(ed().seleccion).toEqual(["caja", "titulo"]);
    ed().aplicar([{ op: "del", capa: "titulo" }]);
    expect(ed().seleccion).toEqual(["caja"]);
  });

  it(`la historia se corta en ${LIMITE_HISTORIA} pasos`, () => {
    for (let i = 0; i < LIMITE_HISTORIA + 5; i++) {
      ed().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: i + 1000 }]);
    }
    expect(ed().pasado).toHaveLength(LIMITE_HISTORIA);
  });

  it("deshacer o rehacer sin historia no hace nada", () => {
    const antes = ed().escena;
    ed().deshacer();
    ed().rehacer();
    expect(ed().escena).toBe(antes);
    expect(ed().sucio).toBe(false);
  });

  it("agregarCapa es un paso y selecciona la capa", () => {
    const nueva = capaNueva("shape", ed().escena!, { fuente: "Inter" });
    ed().agregarCapa(nueva);
    expect(ed().seleccion).toEqual([nueva.id]);
    expect(capa(nueva.id).tipo).toBe("shape");
    expect(ed().pasado).toHaveLength(1);
  });

  it("copiar y pegar crea capas nuevas y las selecciona", () => {
    ed().seleccionar(["titulo"]);
    ed().copiar();
    ed().pegar();
    expect(ed().escena!.capas).toHaveLength(5);
    expect(ed().seleccion).toHaveLength(1);
    expect(ed().seleccion[0]).not.toBe("titulo");
    expect(ed().pasado).toHaveLength(1);
  });

  it("borrar respeta el candado", () => {
    ed().aplicar([{ op: "set", capa: "titulo", ruta: "bloqueada", valor: true }]);
    ed().seleccionar(["titulo", "marca"]);
    ed().borrar();
    expect(ed().escena!.capas.map((c) => c.id)).toEqual(["titulo"]);
    expect(ed().pasado).toHaveLength(2);
  });

  it("agrupar y desagrupar", () => {
    ed().seleccionar(["titulo", "marca"]);
    ed().agrupar();
    const grupo = ed().seleccion[0];
    expect(capa(grupo).tipo).toBe("group");
    ed().desagrupar();
    expect(ed().escena!.capas.some((c) => c.id === grupo)).toBe(false);
    expect([...ed().seleccion].sort()).toEqual(["marca", "titulo"]);
  });

  it("deshacer cierra la edición de texto", () => {
    ed().aplicar([{ op: "set", capa: "titulo", ruta: "texto", valor: "Adiós" }]);
    ed().editarTexto("titulo");
    ed().deshacer();
    expect(ed().editandoTexto).toBeNull();
  });
});
