import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { BarraSuperior } from "../barra-superior";

const base = datos.base as unknown as Escena;
const st = () => useEditor.getState();
const capa = (id: string) => st().escena!.capas.find((c) => c.id === id)!;
const boton = (nombre: string) => screen.getByRole("button", { name: nombre }) as HTMLButtonElement;

type Props = Partial<Parameters<typeof BarraSuperior>[0]>;
function montar(props: Props = {}) {
  const onGuardarVersion = vi.fn<(m: string) => Promise<void>>().mockResolvedValue(undefined);
  const onActivar = vi.fn();
  render(
    <BarraSuperior
      estado="borrador"
      guardando={false}
      onGuardarVersion={onGuardarVersion}
      onActivar={onActivar}
      activando={false}
      {...props}
    />,
  );
  return { onGuardarVersion, onActivar };
}

describe("BarraSuperior", () => {
  beforeEach(() => {
    st().vaciar();
    st().cargar(structuredClone(base));
  });

  it("cambia el formato del lienzo", () => {
    montar();
    expect(boton("4:5").getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(boton("1:1"));
    expect(st().escena!.lienzo.formato).toBe("1x1");
  });

  it("deshacer se habilita con historia", () => {
    montar();
    expect(boton("Deshacer").disabled).toBe(true);
    // El store cambia fuera de React; la barra se suscribe y se vuelve a pintar.
    fireEvent.click(boton("1:1"));
    expect(boton("Deshacer").disabled).toBe(false);
    fireEvent.click(boton("Deshacer"));
    expect(st().escena!.lienzo.formato).toBe("4x5");
  });

  it("alinea una capa al lienzo", () => {
    st().seleccionar(["titulo"]);
    montar();
    fireEvent.click(boton("Alinear abajo"));
    expect(capa("titulo").y).toBe(1050);
  });

  it("distribuir pide tres capas", () => {
    st().seleccionar(["titulo"]);
    montar();
    expect(boton("Distribuir en horizontal").disabled).toBe(true);
    expect(boton("Alinear a la izquierda").disabled).toBe(false);
  });

  it("distribuir con tres se habilita", () => {
    st().seleccionar(["titulo", "caja", "logo"]);
    montar();
    expect(boton("Distribuir en vertical").disabled).toBe(false);
  });

  it("el estado de guardado sigue la prioridad", () => {
    const { rerender } = render(
      <BarraSuperior estado="borrador" guardando={false} onGuardarVersion={vi.fn()} onActivar={vi.fn()} activando={false} />,
    );
    const estado = () => screen.getByTestId("estado-guardado").textContent;
    expect(estado()).toBe("Guardado");
    fireEvent.click(boton("1:1"));
    expect(estado()).toBe("Cambios sin guardar");
    rerender(
      <BarraSuperior estado="borrador" guardando={false} errorGuardado={new Error("500")} onGuardarVersion={vi.fn()} onActivar={vi.fn()} activando={false} />,
    );
    expect(estado()).toBe("No se pudo guardar");
    rerender(
      <BarraSuperior estado="borrador" guardando errorGuardado={new Error("500")} onGuardarVersion={vi.fn()} onActivar={vi.fn()} activando={false} />,
    );
    expect(estado()).toBe("Guardando…");
  });

  it("el badge dice el estado y Activar solo aparece si no está activo", () => {
    const { onActivar } = montar({ estado: "borrador" });
    expect(screen.getByTestId("estado-diseno").textContent).toBe("Borrador");
    fireEvent.click(boton("Activar"));
    expect(onActivar).toHaveBeenCalledTimes(1);
  });

  it("un diseño activo no muestra Activar", () => {
    montar({ estado: "activa" });
    expect(screen.getByTestId("estado-diseno").textContent).toBe("Publicado");
    expect(screen.queryByRole("button", { name: "Activar" })).toBeNull();
  });

  it("guardar versión pide un mensaje y cierra al terminar", async () => {
    const { onGuardarVersion } = montar();
    fireEvent.click(boton("Guardar versión"));
    expect(boton("Guardar").disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox", { name: "Mensaje de la versión" }), {
      target: { value: "  Portada lista  " },
    });
    fireEvent.click(boton("Guardar"));
    expect(onGuardarVersion).toHaveBeenCalledWith("Portada lista");
    expect(await screen.findByRole("button", { name: "Guardar versión" })).not.toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("si guardar versión falla, el diálogo sigue abierto", async () => {
    const falla = vi.fn<(m: string) => Promise<void>>().mockRejectedValue(new Error("409"));
    montar({ onGuardarVersion: falla });
    fireEvent.click(boton("Guardar versión"));
    fireEvent.change(screen.getByRole("textbox", { name: "Mensaje de la versión" }), { target: { value: "x" } });
    fireEvent.click(boton("Guardar"));
    expect(falla).toHaveBeenCalledWith("x");
    expect(await screen.findByRole("dialog")).not.toBeNull();
    await vi.waitFor(() => expect(boton("Guardar").disabled).toBe(false));
  });
});
