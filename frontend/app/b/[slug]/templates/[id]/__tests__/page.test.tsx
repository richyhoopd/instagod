import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { Diseno } from "@/hooks/use-disenos";
import type { Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

const guardar = vi.fn();
let diseno: Partial<Diseno>;

vi.mock("next/navigation", () => ({ useParams: () => ({ slug: "marca", id: "7" }) }));
vi.mock("@/hooks/use-brands", () => ({ useBrand: () => ({ data: { color_marca: "#112233" } }) }));
vi.mock("@/hooks/use-disenos", () => ({
  useDiseno: () => ({ data: diseno, isLoading: false, isError: false }),
  useGuardarDiseno: () => ({ mutateAsync: guardar }),
  useActivarDiseno: () => ({ mutateAsync: vi.fn() }),
}));
vi.mock("../_components/lienzo", () => ({ Lienzo: () => <div data-testid="lienzo" /> }));
vi.mock("../_components/panel-capas", () => ({ PanelCapas: () => null }));
vi.mock("../_components/panel-propiedades", () => ({ PanelPropiedades: () => null }));
vi.mock("../_components/vista-previa", () => ({ VistaPrevia: () => null }));
vi.mock("../_components/dialogo-versiones", () => ({ DialogoVersiones: () => null }));

import DisenoPage from "../page";

const escena = datos.base as unknown as Escena;

describe("DisenoPage", () => {
  beforeEach(() => {
    useEditor.getState().vaciar();
    guardar.mockReset();
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

  it("un layout null no carga el store", () => {
    diseno = { id: 7, nombre: "X", aspecto: "4:5", estado: "borrador", editable: true, layout: null };
    render(<DisenoPage />);
    expect(useEditor.getState().escena).toBeNull();
    expect(screen.queryByTestId("lienzo")).toBeNull();
  });
});
