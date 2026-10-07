import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { Diseno } from "@/hooks/use-disenos";
import type { Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

const guardar = vi.fn();
const activar = vi.fn();
const toast = { error: vi.fn() };
let idRuta = "7";
let diseno: Partial<Diseno>;

vi.mock("next/navigation", () => ({ useParams: () => ({ slug: "marca", id: idRuta }) }));
vi.mock("@/hooks/use-brands", () => ({ useBrand: () => ({ data: { color_marca: "#112233" } }) }));
vi.mock("@/hooks/use-disenos", () => ({
  useDiseno: () => ({ data: diseno, isLoading: false, isError: false }),
  useGuardarDiseno: () => ({ mutateAsync: guardar }),
  useActivarDiseno: () => ({ mutateAsync: activar }),
}));
vi.mock("sonner", () => ({ toast: { error: (m: string) => toast.error(m), success: vi.fn() } }));
vi.mock("../_components/lienzo", () => ({ Lienzo: () => <div data-testid="lienzo" /> }));
vi.mock("../_components/panel-capas", () => ({ PanelCapas: () => null }));
vi.mock("../_components/panel-propiedades", () => ({
  PanelPropiedades: () => null,
  camposDeContrato: () => ({ texto: [], imagen: [] }),
}));
vi.mock("../_components/vista-previa", () => ({ VistaPrevia: () => null }));
let alRestaurar: ((d: Diseno) => void) | undefined;
vi.mock("../_components/dialogo-versiones", () => ({
  DialogoVersiones: (p: { onRestaurado: (d: Diseno) => void }) => {
    alRestaurar = p.onRestaurado;
    return null;
  },
}));

import DisenoPage from "../page";

const escena = datos.base as unknown as Escena;

describe("DisenoPage", () => {
  beforeEach(() => {
    useEditor.getState().vaciar();
    guardar.mockReset();
    activar.mockReset();
    toast.error.mockReset();
    idRuta = "7";
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("un diseño editable siembra el store y muestra el editor", () => {
    diseno = { id: 7, nombre: "X", aspecto: "4:5", estado: "borrador", editable: true, layout: structuredClone(escena) };
    render(<DisenoPage />);
    expect(useEditor.getState().escena).not.toBeNull();
    expect(screen.getByTestId("lienzo")).not.toBeNull();
  });

  it("un diseño no editable no carga el store ni guarda", () => {
    diseno = { id: 7, nombre: "X", aspecto: "4:5", estado: "borrador", editable: false, layout: structuredClone(escena) };
    render(<DisenoPage />);
    expect(useEditor.getState().escena).toBeNull();
    expect(screen.queryByTestId("lienzo")).toBeNull();
    expect(screen.getByText(/antes del editor/)).not.toBeNull();
  });

  it("uno de solo lectura no llama al guardado ni con el tiempo", async () => {
    vi.useFakeTimers();
    diseno = { id: 7, nombre: "X", aspecto: "4:5", estado: "borrador", editable: false, layout: structuredClone(escena) };
    const { unmount } = render(<DisenoPage />);
    act(() => useEditor.getState().cargar(structuredClone(escena)));
    act(() => useEditor.getState().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 90 }]));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(guardar).not.toHaveBeenCalled();
  });

  it("activar: si el guardado funcionó aunque se editó mientras, no avisa de error", async () => {
    diseno = { id: 7, nombre: "X", aspecto: "4:5", estado: "borrador", editable: true, layout: structuredClone(escena) };
    let resolver!: () => void;
    guardar.mockImplementationOnce(() => new Promise<void>((r) => (resolver = r)));
    activar.mockResolvedValue(undefined);
    render(<DisenoPage />);
    act(() => useEditor.getState().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 90 }]));
    fireEvent.click(screen.getByRole("button", { name: /activar|publicar/i }));
    await waitFor(() => expect(guardar).toHaveBeenCalledTimes(1));
    act(() => useEditor.getState().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 91 }]));
    await act(async () => resolver());
    await waitFor(() => expect(activar).toHaveBeenCalled());
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("activar: si el guardado falla avisa y no activa", async () => {
    diseno = { id: 7, nombre: "X", aspecto: "4:5", estado: "borrador", editable: true, layout: structuredClone(escena) };
    guardar.mockRejectedValue(new Error("500"));
    render(<DisenoPage />);
    act(() => useEditor.getState().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 90 }]));
    fireEvent.click(screen.getByRole("button", { name: /activar|publicar/i }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("No se pudo guardar antes de activar."));
    expect(activar).not.toHaveBeenCalled();
  });

  it("un layout null no carga el store", () => {
    diseno = { id: 7, nombre: "X", aspecto: "4:5", estado: "borrador", editable: true, layout: null };
    render(<DisenoPage />);
    expect(useEditor.getState().escena).toBeNull();
    expect(screen.queryByTestId("lienzo")).toBeNull();
  });

  it("cambiar de diseño remonta: guarda A y vacía el store antes de B", async () => {
    vi.useFakeTimers();
    guardar.mockResolvedValue(undefined);
    diseno = { id: 7, nombre: "A", aspecto: "4:5", estado: "borrador", editable: true, layout: structuredClone(escena) };
    const { rerender } = render(<DisenoPage />);
    act(() => useEditor.getState().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 90 }]));
    idRuta = "8";
    diseno = { id: 8, nombre: "B", aspecto: "4:5", estado: "borrador", editable: false, layout: null };
    rerender(<DisenoPage />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(guardar).toHaveBeenCalledTimes(1);
    expect(guardar.mock.calls[0][0].layout.capas.find((c: { id: string }) => c.id === "titulo").x).toBe(90);
    expect(useEditor.getState().escena).toBeNull();
  });

  it("el resultado de un revert de A no se carga sobre B", async () => {
    const capas = (x: number) => {
      const e = structuredClone(escena);
      e.capas.find((c) => c.id === "titulo")!.x = x;
      return e;
    };
    diseno = { id: 7, nombre: "A", aspecto: "4:5", estado: "borrador", editable: true, layout: capas(10) };
    const { rerender } = render(<DisenoPage />);
    const restauraA = alRestaurar!;
    idRuta = "8";
    diseno = { id: 8, nombre: "B", aspecto: "4:5", estado: "borrador", editable: true, layout: capas(20) };
    rerender(<DisenoPage />);
    const xB = () => useEditor.getState().escena!.capas.find((c) => c.id === "titulo")!.x;
    expect(xB()).toBe(20);
    act(() => restauraA({ id: 7, layout: capas(99) } as Diseno));
    expect(xB()).toBe(20);
    // El del diseño montado sí se aplica.
    act(() => alRestaurar!({ id: 8, layout: capas(55) } as Diseno));
    expect(xB()).toBe(55);
  });
});
