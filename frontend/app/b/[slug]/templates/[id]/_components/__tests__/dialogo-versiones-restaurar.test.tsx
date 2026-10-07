import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Diseno } from "@/hooks/use-disenos";

const revertido = { id: 7, layout: { v: 2 } } as unknown as Diseno;
const mutateAsync = vi.fn();

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/hooks/use-disenos", () => ({
  useVersiones: () => ({
    isLoading: false,
    isError: false,
    data: [
      { version: 2, mensaje: "Actual", creado_en: "2026-10-06T12:02:00" },
      { version: 1, mensaje: "Primera", creado_en: "2026-10-06T12:01:00" },
    ],
  }),
  useRevertir: () => ({ mutateAsync, isPending: false }),
}));

import { DialogoVersiones } from "../dialogo-versiones";

describe("DialogoVersiones", () => {
  it("restaurar llama a onRestaurado con el Diseno devuelto, dentro de proteger", async () => {
    mutateAsync.mockResolvedValue(revertido);
    const onRestaurado = vi.fn();
    const proteger = vi.fn((accion: () => Promise<Diseno>) => accion());
    render(
      <DialogoVersiones
        slug="marca"
        id={7}
        versionActual={2}
        ocupado={false}
        onRestaurado={onRestaurado}
        proteger={proteger}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /versiones/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Restaurar versión 1" }));
    await waitFor(() => expect(onRestaurado).toHaveBeenCalledWith(revertido));
    expect(proteger).toHaveBeenCalledTimes(1);
    expect(mutateAsync).toHaveBeenCalledWith(1);
  });
});
