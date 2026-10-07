import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PanelLateral } from "../panel-lateral";

const pestanas = [
  { id: "capas", etiqueta: "Capas", contenido: <p>contenido capas</p> },
  { id: "assets", etiqueta: "Assets", contenido: <p>contenido assets</p> },
];

describe("PanelLateral", () => {
  it("abre en la primera pestaña", () => {
    render(<PanelLateral pestanas={pestanas} />);
    expect(screen.queryByText("contenido capas")).not.toBeNull();
    expect(screen.queryByText("contenido assets")).toBeNull();
  });

  it("cambia de pestaña", () => {
    render(<PanelLateral pestanas={pestanas} />);
    // Radix Tabs activa en mousedown con el botón principal.
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Assets" }), { button: 0 });
    expect(screen.queryByText("contenido assets")).not.toBeNull();
  });
});
