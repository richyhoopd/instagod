import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { VersionDiseno } from "@/hooks/use-disenos";
import { ListaVersiones } from "../dialogo-versiones";

const versiones: VersionDiseno[] = [
  { version: 4, mensaje: null, creado_en: "2026-10-06T12:04:00" },
  { version: 3, mensaje: "Portada lista", creado_en: "2026-10-06T12:03:00" },
  { version: 2, mensaje: null, creado_en: "2026-10-06T12:02:00" },
  { version: 1, mensaje: "Primera", creado_en: "2026-10-06T12:01:00" },
];
const restaurar = (n: number) => screen.queryByRole("button", { name: `Restaurar versión ${n}` }) as HTMLButtonElement | null;

describe("ListaVersiones", () => {
  it("esconde los autoguardados hasta pedirlos", () => {
    render(<ListaVersiones versiones={versiones} versionActual={4} ocupado={false} onRestaurar={vi.fn()} />);
    expect(restaurar(3)).not.toBeNull();
    expect(restaurar(2)).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Ver autoguardados" }));
    expect(restaurar(2)).not.toBeNull();
  });

  it("restaura otra versión y no la actual", () => {
    const onRestaurar = vi.fn();
    render(<ListaVersiones versiones={versiones} versionActual={3} ocupado={false} onRestaurar={onRestaurar} />);
    expect(restaurar(3)!.disabled).toBe(true);
    fireEvent.click(restaurar(1)!);
    expect(onRestaurar).toHaveBeenCalledWith(1);
  });

  it("no restaura mientras se guarda", () => {
    render(<ListaVersiones versiones={versiones} versionActual={4} ocupado onRestaurar={vi.fn()} />);
    expect(restaurar(1)!.disabled).toBe(true);
  });
});
