import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { useAutoguardado } from "../use-autoguardado";

const base = datos.base as unknown as Escena;
const st = () => useEditor.getState();
type Guardar = (e: Escena, m?: string) => Promise<void>;

const avanzar = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
const editar = (x: number) =>
  act(() => st().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: x }]));
const xGuardada = (g: ReturnType<typeof vi.fn<Guardar>>, llamada: number) =>
  g.mock.calls[llamada][0].capas.find((c) => c.id === "titulo")!.x;

function diferido() {
  let resolver!: () => void;
  let rechazar!: (e: Error) => void;
  const promesa = new Promise<void>((res, rej) => {
    resolver = res;
    rechazar = rej;
  });
  return { promesa, resolver, rechazar };
}

function montar(guardar: Guardar, activo = true) {
  return renderHook((p: { activo: boolean }) => useAutoguardado({ activo: p.activo, guardar }), {
    initialProps: { activo },
  });
}

describe("useAutoguardado", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    st().vaciar();
    st().cargar(structuredClone(base));
  });
  afterEach(() => vi.useRealTimers());

  it("inactivo no guarda", async () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    montar(guardar, false);
    editar(90);
    await avanzar(10_000);
    expect(guardar).not.toHaveBeenCalled();
    expect(st().sucio).toBe(true);
  });

  it("espera 2 s desde la última edición", async () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    montar(guardar);
    editar(90);
    await avanzar(1000);
    editar(110);
    await avanzar(1999);
    expect(guardar).not.toHaveBeenCalled();
    await avanzar(1);
    expect(guardar).toHaveBeenCalledTimes(1);
    expect(xGuardada(guardar, 0)).toBe(110);
    expect(st().sucio).toBe(false);
  });

  it("una edición durante el guardado deja sucio y vuelve a guardar", async () => {
    const primero = diferido();
    const guardar = vi.fn<Guardar>().mockReturnValueOnce(primero.promesa).mockResolvedValue(undefined);
    montar(guardar);
    editar(110);
    await avanzar(2000);
    expect(guardar).toHaveBeenCalledTimes(1);
    editar(120);
    primero.resolver();
    await avanzar(0);
    expect(st().sucio).toBe(true);
    await avanzar(2000);
    expect(guardar).toHaveBeenCalledTimes(2);
    expect(xGuardada(guardar, 1)).toBe(120);
    expect(st().sucio).toBe(false);
  });

  it("los guardados van en serie", async () => {
    const primero = diferido();
    const guardar = vi.fn<Guardar>().mockReturnValueOnce(primero.promesa).mockResolvedValue(undefined);
    montar(guardar);
    editar(110);
    await avanzar(2000);
    editar(120);
    await avanzar(2000);
    expect(guardar).toHaveBeenCalledTimes(1);
    primero.resolver();
    await avanzar(0);
    expect(guardar).toHaveBeenCalledTimes(2);
  });

  it("un error deja sucio y no reintenta solo", async () => {
    const guardar = vi.fn<Guardar>().mockRejectedValue(new Error("500"));
    const { result } = montar(guardar);
    editar(110);
    await avanzar(2000);
    expect(result.current.error?.message).toBe("500");
    expect(st().sucio).toBe(true);
    await avanzar(10_000);
    expect(guardar).toHaveBeenCalledTimes(1);
  });

  it("guardarAhora con mensaje guarda aunque no haya cambios", async () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    const { result } = montar(guardar);
    await act(() => result.current.guardarAhora("Portada lista"));
    expect(guardar).toHaveBeenCalledWith(expect.objectContaining({ v: 2 }), "Portada lista");
  });

  it("guardarAhora con mensaje propaga el error", async () => {
    const guardar = vi.fn<Guardar>().mockRejectedValue(new Error("409"));
    const { result } = montar(guardar);
    await act(async () => {
      await expect(result.current.guardarAhora("Portada lista")).rejects.toThrow("409");
    });
    expect(result.current.error?.message).toBe("409");
  });

  it("beforeunload avisa solo con cambios sin guardar y activo", () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    montar(guardar);
    const limpio = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(limpio);
    expect(limpio.defaultPrevented).toBe(false);
    editar(90);
    const sucio = new Event("beforeunload", { cancelable: true }) as BeforeUnloadEvent;
    Object.defineProperty(sucio, "returnValue", { value: "x", writable: true });
    window.dispatchEvent(sucio);
    expect(sucio.defaultPrevented).toBe(true);
    expect(sucio.returnValue).toBe("");
  });

  it("beforeunload no avisa si está inactivo", () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    montar(guardar, false);
    editar(90);
    const ev = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
  });

  it("guardarAhora con mensaje rechaza si está inactivo y no guarda", async () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    const { result } = montar(guardar, false);
    await act(async () => {
      await expect(result.current.guardarAhora("Hito")).rejects.toThrow(/inactivo/i);
    });
    expect(guardar).not.toHaveBeenCalled();
  });

  it("guardarAhora con mensaje rechaza si no hay escena", async () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    const { result } = montar(guardar);
    act(() => st().vaciar());
    await act(async () => {
      await expect(result.current.guardarAhora("Hito")).rejects.toThrow(/escena/i);
    });
    expect(guardar).not.toHaveBeenCalled();
  });

  it("un guardado encolado lee activo al ejecutarse", async () => {
    const primero = diferido();
    const guardar = vi.fn<Guardar>().mockReturnValueOnce(primero.promesa).mockResolvedValue(undefined);
    const { result, rerender } = montar(guardar);
    editar(110);
    await avanzar(2000);
    expect(guardar).toHaveBeenCalledTimes(1);
    let encolado!: Promise<void>;
    act(() => {
      encolado = result.current.guardarAhora("Hito");
    });
    encolado.catch(() => {});
    rerender({ activo: false });
    primero.resolver();
    await avanzar(0);
    await expect(encolado).rejects.toThrow(/inactivo/i);
    expect(guardar).toHaveBeenCalledTimes(1);
  });

  it("al desmontar con cambios sucios y activo hace flush", async () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    const { unmount } = montar(guardar);
    editar(95);
    unmount();
    // El store se vacía justo después, como hace la página.
    st().vaciar();
    await avanzar(0);
    expect(guardar).toHaveBeenCalledTimes(1);
    expect(xGuardada(guardar, 0)).toBe(95);
  });

  it("al desmontar sin cambios o inactivo no guarda", async () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    montar(guardar).unmount();
    const g2 = vi.fn<Guardar>().mockResolvedValue(undefined);
    const inactivo = montar(g2, false);
    editar(95);
    inactivo.unmount();
    await avanzar(0);
    expect(guardar).not.toHaveBeenCalled();
    expect(g2).not.toHaveBeenCalled();
  });

  it("un guardado en vuelo que termina tras cargar otra escena no toca el estado", async () => {
    const primero = diferido();
    const guardar = vi.fn<Guardar>().mockReturnValueOnce(primero.promesa).mockResolvedValue(undefined);
    montar(guardar);
    editar(110);
    await avanzar(2000);
    act(() => st().cargar(structuredClone(base)));
    editar(120);
    primero.resolver();
    await avanzar(0);
    expect(st().sucio).toBe(true);
  });

  it("un guardado en vuelo que termina tras vaciar no toca el estado", async () => {
    const primero = diferido();
    const guardar = vi.fn<Guardar>().mockReturnValueOnce(primero.promesa);
    montar(guardar);
    editar(110);
    await avanzar(2000);
    act(() => st().vaciar());
    const antes = st();
    primero.resolver();
    await avanzar(0);
    expect(st()).toBe(antes);
  });
});
