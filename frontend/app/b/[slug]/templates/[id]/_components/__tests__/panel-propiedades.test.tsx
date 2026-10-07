import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { CapaForma, CapaTexto, Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { camposDeContrato, PanelPropiedades } from "../panel-propiedades";

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

  it("X acotada: tras commitear muestra el valor real del store", () => {
    montar(["titulo"]);
    fireEvent.change(campo("X"), { target: { value: "9999" } });
    fireEvent.blur(campo("X"));
    expect(capa("titulo").x).toBe(4000);
    expect(campo("X").value).toBe("4000");
    fireEvent.change(campo("X"), { target: { value: "9999" } });
    fireEvent.blur(campo("X"));
    expect(campo("X").value).toBe("4000");
  });

  it("X con decimales se redondea y el campo lo muestra", () => {
    montar(["titulo"]);
    fireEvent.change(campo("X"), { target: { value: "100.6" } });
    fireEvent.blur(campo("X"));
    expect(capa("titulo").x).toBe(101);
    expect(campo("X").value).toBe("101");
  });

  it("capa bloqueada: todos los campos deshabilitados", () => {
    montar(["titulo"]);
    act(() =>
      st().editarEscena((d) => {
        d.capas.find((c) => c.id === "titulo")!.bloqueada = true;
      }),
    );
    const pasos = st().pasado.length;
    expect(campo("Ancho").disabled).toBe(true);
    expect(campo("X").disabled).toBe(true);
    expect(campo("Opacidad").disabled).toBe(true);
    expect((screen.getByRole("textbox", { name: "Fuente" }) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("combobox", { name: "Peso" }) as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole("combobox", { name: "Color" }) as HTMLSelectElement).disabled).toBe(true);
    expect(st().pasado).toHaveLength(pasos);
  });

  it("Escape revierte al valor del store", () => {
    montar(["titulo"]);
    fireEvent.change(campo("X"), { target: { value: "555" } });
    fireEvent.keyDown(campo("X"), { key: "Escape" });
    expect(campo("X").value).toBe("80");
    expect(st().pasado).toHaveLength(0);
  });

  it("Enter y luego blur es un solo paso", () => {
    montar(["titulo"]);
    fireEvent.change(campo("X"), { target: { value: "100" } });
    fireEvent.keyDown(campo("X"), { key: "Enter" });
    fireEvent.blur(campo("X"));
    expect(st().pasado).toHaveLength(1);
  });

  const fuente = () => screen.getByRole("textbox", { name: "Fuente" }) as HTMLInputElement;

  it("Fuente sigue al store tras deshacer y foco+blur no reaplica", () => {
    montar(["titulo"]);
    fireEvent.change(fuente(), { target: { value: "Lora" } });
    fireEvent.blur(fuente());
    expect((capa("titulo") as CapaTexto).estilo.fontFamily).toBe("Lora");
    act(() => st().deshacer());
    expect(fuente().value).toBe("Inter");
    const pasos = st().pasado.length;
    fireEvent.focus(fuente());
    fireEvent.blur(fuente());
    expect(st().pasado).toHaveLength(pasos);
    expect((capa("titulo") as CapaTexto).estilo.fontFamily).toBe("Inter");
  });

  it("Fuente rechaza comillas, barra invertida y vacío", () => {
    montar(["titulo"]);
    for (const malo of ["Foo'Bar", 'Foo"Bar', "Foo\\Bar", "  "]) {
      fireEvent.change(fuente(), { target: { value: malo } });
      fireEvent.blur(fuente());
      expect((capa("titulo") as CapaTexto).estilo.fontFamily).toBe("Inter");
      expect(fuente().value).toBe("Inter");
    }
    expect(st().pasado).toHaveLength(0);
  });

  const propio = () => screen.getByLabelText("Relleno propio") as HTMLInputElement;

  it("Color propio: foco+blur sin cambio no commitea", () => {
    montar(["caja"]);
    act(() =>
      st().editarEscena((d) => {
        const c = d.capas.find((x) => x.id === "caja")!;
        if (c.tipo === "shape") c.estilo.fill = "#123456";
      }),
    );
    st().seleccionar(["caja"]);
    const pasos = st().pasado.length;
    fireEvent.focus(propio());
    fireEvent.blur(propio());
    expect(st().pasado).toHaveLength(pasos);
  });

  it("Color propio se resincroniza tras deshacer", () => {
    montar(["caja"]);
    act(() =>
      st().editarEscena((d) => {
        const c = d.capas.find((x) => x.id === "caja")!;
        if (c.tipo === "shape") c.estilo.fill = "#123456";
      }),
    );
    fireEvent.change(propio(), { target: { value: "#abcdef" } });
    fireEvent.blur(propio());
    expect(propio().value).toBe("#abcdef");
    act(() => st().deshacer());
    expect(propio().value).toBe("#123456");
    const pasos = st().pasado.length;
    fireEvent.focus(propio());
    fireEvent.blur(propio());
    expect(st().pasado).toHaveLength(pasos);
  });

  it("Peso fuera de la lista muestra el valor actual", () => {
    montar(["titulo"]);
    act(() =>
      st().editarEscena((d) => {
        const c = d.capas.find((x) => x.id === "titulo")!;
        if (c.tipo === "text") c.estilo.fontWeight = 350;
      }),
    );
    expect((screen.getByRole("combobox", { name: "Peso" }) as HTMLSelectElement).value).toBe("350");
  });
});

const CAMPOS = { texto: ["titular", "handle"], imagen: ["imagen", "logo"] };

function montarConCampos(seleccion: string[]) {
  st().vaciar();
  st().cargar(structuredClone(base));
  st().seleccionar(seleccion);
  render(<PanelPropiedades colorMarca="#ff3366" campos={CAMPOS} />);
}
const combo = (nombre: string) => screen.getByRole("combobox", { name: nombre }) as HTMLSelectElement;

describe("camposDeContrato", () => {
  it("separa texto de imagen y suma los extras por tipo", () => {
    expect(
      camposDeContrato({
        aspecto: "4:5",
        base: ["titular", "imagen", "handle", "logo", "color_marca"],
        extras: [
          { id: "precio", tipo: "numero" },
          { id: "foto2", tipo: "imagen" },
        ],
      }),
    ).toEqual({ texto: ["titular", "handle", "precio"], imagen: ["imagen", "logo", "foto2"] });
  });
});

describe("PanelPropiedades: efectos y datos", () => {
  beforeEach(() => st().vaciar());

  it("sin campos no muestra Dato", () => {
    montar(["titulo"]);
    expect(screen.queryByRole("combobox", { name: "Dato" })).toBeNull();
  });

  it("vincular un texto limpia sus tramos en un paso", () => {
    st().vaciar();
    st().cargar(structuredClone(base));
    st().aplicar([{ op: "set", capa: "titulo", ruta: "estilo.spans", valor: [{ desde: 0, hasta: 4, color: "#ff0000" }] }]);
    st().seleccionar(["titulo"]);
    render(<PanelPropiedades colorMarca="#ff3366" campos={CAMPOS} />);
    const antes = st().pasado.length;
    expect([...combo("Dato").options].map((o) => o.value)).toEqual(["", "titular", "handle"]);
    fireEvent.change(combo("Dato"), { target: { value: "titular" } });
    const t = capa("titulo") as CapaTexto;
    expect(t.campo).toBe("titular");
    expect(t.estilo.spans).toEqual([]);
    expect(st().pasado).toHaveLength(antes + 1);
  });

  it("desvincular apaga resaltar", () => {
    st().vaciar();
    st().cargar(structuredClone(base));
    st().aplicar([
      { op: "set", capa: "titulo", ruta: "campo", valor: "titular" },
      { op: "set", capa: "titulo", ruta: "resaltar", valor: true },
    ]);
    st().seleccionar(["titulo"]);
    render(<PanelPropiedades colorMarca="#ff3366" campos={CAMPOS} />);
    fireEvent.change(combo("Dato"), { target: { value: "" } });
    const t = capa("titulo") as CapaTexto;
    expect(t.campo).toBeNull();
    expect(t.resaltar).toBe(false);
  });

  it("la sombra de una forma escribe estilo.filter", () => {
    montarConCampos(["caja"]);
    expect(combo("Sombra").value).toBe("none");
    fireEvent.change(combo("Sombra"), { target: { value: "drop-shadow(0 16px 32px rgba(0,0,0,.3))" } });
    expect((capa("caja") as CapaForma).estilo.filter).toBe("drop-shadow(0 16px 32px rgba(0,0,0,.3))");
  });

  it("una sombra personalizada se muestra y no se pisa", () => {
    st().vaciar();
    st().cargar(structuredClone(base));
    st().aplicar([{ op: "set", capa: "caja", ruta: "estilo.filter", valor: "blur(2px)" }]);
    st().seleccionar(["caja"]);
    render(<PanelPropiedades colorMarca="#ff3366" />);
    expect(combo("Sombra").value).toBe("blur(2px)");
    expect((capa("caja") as CapaForma).estilo.filter).toBe("blur(2px)");
  });

  it("la mezcla escribe estilo.mixBlendMode", () => {
    montarConCampos(["logo"]);
    fireEvent.change(combo("Mezcla"), { target: { value: "multiply" } });
    expect(capa("logo")).toMatchObject({ estilo: { mixBlendMode: "multiply" } });
  });

  it("el texto no tiene efectos", () => {
    montarConCampos(["titulo"]);
    expect(screen.queryByRole("combobox", { name: "Sombra" })).toBeNull();
  });

  it("el borde de una forma", () => {
    montarConCampos(["caja"]);
    fireEvent.change(campo("Borde"), { target: { value: "4" } });
    fireEvent.blur(campo("Borde"));
    expect((capa("caja") as CapaForma).estilo.borderWidth).toBe(4);
    fireEvent.change(combo("Color de borde"), { target: { value: "token:tinta" } });
    expect((capa("caja") as CapaForma).estilo.borderColor).toBe("token:tinta");
  });

  it("el tracking acepta texto y vacío lo quita", () => {
    montarConCampos(["titulo"]);
    const tracking = screen.getByRole("textbox", { name: "Tracking" });
    fireEvent.change(tracking, { target: { value: "2px" } });
    fireEvent.blur(tracking);
    expect((capa("titulo") as CapaTexto).estilo.letterSpacing).toBe("2px");
    fireEvent.change(tracking, { target: { value: "" } });
    fireEvent.blur(tracking);
    expect((capa("titulo") as CapaTexto).estilo.letterSpacing).toBeUndefined();
  });

  const tracking = () => screen.getByRole("textbox", { name: "Tracking" }) as HTMLInputElement;

  it("el tracking inválido no toca el store y revierte el input", () => {
    montarConCampos(["titulo"]);
    for (const malo of ["abc", "2", "1234px", "1.2345em", "2 px", "px"]) {
      fireEvent.change(tracking(), { target: { value: malo } });
      fireEvent.blur(tracking());
      expect((capa("titulo") as CapaTexto).estilo.letterSpacing).toBe("-0.02em");
      expect(tracking().value).toBe("-0.02em");
    }
    expect(st().pasado).toHaveLength(0);
    for (const bueno of ["-0.03em", "2px", "0.5em", "-12.25px"]) {
      fireEvent.change(tracking(), { target: { value: bueno } });
      fireEvent.blur(tracking());
      expect((capa("titulo") as CapaTexto).estilo.letterSpacing).toBe(bueno);
    }
  });

  it("el tracking sigue al store tras deshacer", () => {
    st().vaciar();
    st().cargar(structuredClone(base));
    st().aplicar([{ op: "set", capa: "titulo", ruta: "estilo.letterSpacing", valor: undefined }]);
    st().seleccionar(["titulo"]);
    render(<PanelPropiedades colorMarca="#ff3366" campos={CAMPOS} />);
    fireEvent.change(tracking(), { target: { value: "2px" } });
    fireEvent.blur(tracking());
    expect(tracking().value).toBe("2px");
    act(() => st().deshacer());
    expect(tracking().value).toBe("");
  });

  function conImagenSinSrc(tipo: "image" | "video") {
    st().vaciar();
    st().cargar(structuredClone(base));
    st().editarEscena((d) => {
      const l = d.capas.find((x) => x.id === "logo") as unknown as { tipo: string; src: string | null; campo: string | null };
      l.tipo = tipo;
      l.src = null;
      l.campo = "logo";
    });
    st().seleccionar(["logo"]);
    render(<PanelPropiedades colorMarca="#ff3366" campos={CAMPOS} />);
  }

  it.each(["image", "video"] as const)("%s sin src no se puede desvincular", (tipo) => {
    conImagenSinSrc(tipo);
    const ninguno = [...combo("Dato").options].find((o) => o.value === "")!;
    expect(ninguno.disabled).toBe(true);
    expect(ninguno.title).toMatch(/src/i);
  });

  it("una imagen con src sí se puede desvincular", () => {
    montarConCampos(["logo"]);
    act(() =>
      st().editarEscena((d) => {
        const l = d.capas.find((x) => x.id === "logo") as unknown as { tipo: string; campo: string | null };
        l.tipo = "image";
        l.campo = "logo";
      }),
    );
    const ninguno = [...combo("Dato").options].find((o) => o.value === "")!;
    expect(ninguno.disabled).toBe(false);
  });

  it("una mezcla fuera de la lista se muestra", () => {
    st().vaciar();
    st().cargar(structuredClone(base));
    st().aplicar([{ op: "set", capa: "caja", ruta: "estilo.mixBlendMode", valor: "color-dodge" }]);
    st().seleccionar(["caja"]);
    render(<PanelPropiedades colorMarca="#ff3366" />);
    expect(combo("Mezcla").value).toBe("color-dodge");
    expect([...combo("Mezcla").options].some((o) => o.value === "color-dodge")).toBe(true);
  });

  it("screen se llama Pantalla", () => {
    montarConCampos(["caja"]);
    expect([...combo("Mezcla").options].find((o) => o.value === "screen")!.textContent).toBe("Pantalla");
  });

  it("el borde se acota a 200 como el backend", () => {
    montarConCampos(["caja"]);
    fireEvent.change(campo("Borde"), { target: { value: "500" } });
    fireEvent.blur(campo("Borde"));
    expect((capa("caja") as CapaForma).estilo.borderWidth).toBe(200);
  });

  it("capa bloqueada deshabilita Dato, Efectos, Tracking, Borde y Color de borde", () => {
    montarConCampos(["titulo"]);
    act(() => st().editarEscena((d) => void (d.capas.find((c) => c.id === "titulo")!.bloqueada = true)));
    expect(combo("Dato").disabled).toBe(true);
    expect(tracking().disabled).toBe(true);
    act(() => st().seleccionar(["caja"]));
    act(() => st().editarEscena((d) => void (d.capas.find((c) => c.id === "caja")!.bloqueada = true)));
    expect(combo("Mezcla").disabled).toBe(true);
    expect(combo("Sombra").disabled).toBe(true);
    expect(campo("Borde").disabled).toBe(true);
    expect(combo("Color de borde").disabled).toBe(true);
  });

  it("deshacer tras cambiar Efectos y Dato", () => {
    montarConCampos(["titulo"]);
    fireEvent.change(combo("Dato"), { target: { value: "titular" } });
    expect(combo("Dato").value).toBe("titular");
    act(() => st().deshacer());
    expect(combo("Dato").value).toBe("");
    act(() => st().seleccionar(["caja"]));
    fireEvent.change(combo("Sombra"), { target: { value: "drop-shadow(0 8px 16px rgba(0,0,0,.25))" } });
    act(() => st().deshacer());
    expect(combo("Sombra").value).toBe("none");
    fireEvent.change(combo("Mezcla"), { target: { value: "multiply" } });
    act(() => st().deshacer());
    expect(combo("Mezcla").value).toBe("normal");
  });

  it("un campo fuera del contrato se conserva como huérfano", () => {
    st().vaciar();
    st().cargar(structuredClone(base));
    st().aplicar([{ op: "set", capa: "titulo", ruta: "campo", valor: "viejo" }]);
    st().seleccionar(["titulo"]);
    render(<PanelPropiedades colorMarca="#ff3366" campos={CAMPOS} />);
    expect(combo("Dato").value).toBe("viejo");
    expect([...combo("Dato").options].some((o) => o.textContent === "viejo (no está en el contrato)")).toBe(true);
  });
});
