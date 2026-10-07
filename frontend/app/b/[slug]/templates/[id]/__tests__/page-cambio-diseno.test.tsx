import { act, render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

let idRuta = "7";
const api = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), post: vi.fn() }));

vi.mock("next/navigation", () => ({ useParams: () => ({ slug: "marca", id: idRuta }) }));
vi.mock("@/hooks/use-brands", () => ({ useBrand: () => ({ data: { color_marca: "#112233" } }) }));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));
vi.mock("../_components/lienzo", () => ({ Lienzo: () => <div data-testid="lienzo" /> }));
vi.mock("../_components/panel-capas", () => ({ PanelCapas: () => null }));
vi.mock("../_components/panel-propiedades", () => ({
  PanelPropiedades: () => null,
  camposDeContrato: () => ({ texto: [], imagen: [] }),
}));
vi.mock("../_components/vista-previa", () => ({ VistaPrevia: () => null }));
vi.mock("../_components/dialogo-versiones", () => ({ DialogoVersiones: () => null }));

import DisenoPage from "../page";

const escena = datos.base as unknown as Escena;
const diseno = (id: number) => ({
  id,
  nombre: `D${id}`,
  aspecto: "4:5",
  estado: "borrador",
  editable: true,
  version_actual: 1,
  layout: structuredClone(escena),
});

function montar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = () => (
    <QueryClientProvider client={qc}>
      <DisenoPage />
    </QueryClientProvider>
  );
  return { ...render(ui()), ui };
}

describe("DisenoPage con el cliente real de TanStack Query", () => {
  beforeEach(() => {
    useEditor.getState().vaciar();
    Object.values(api).forEach((m) => m.mockReset());
    api.get.mockImplementation(async (url: string) => {
      const m = /templates\/(\d+)$/.exec(url);
      return m ? diseno(Number(m[1])) : [];
    });
    api.patch.mockResolvedValue(diseno(7));
    idRuta = "7";
  });

  it("el flush de A al navegar a B pega en el endpoint de A, nunca en el de B", async () => {
    const { rerender, ui } = montar();
    await waitFor(() => expect(useEditor.getState().escena).not.toBeNull());
    act(() => useEditor.getState().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 90 }]));
    idRuta = "8";
    rerender(ui());
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    const urls = api.patch.mock.calls.map((c) => c[0]);
    expect(urls).toEqual(["/brands/marca/templates/7"]);
  });
});
