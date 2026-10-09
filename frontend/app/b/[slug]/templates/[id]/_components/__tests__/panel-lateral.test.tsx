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

  it("una pestaña montada sigue en el DOM, oculta, al cambiar de pestaña", () => {
    render(
      <PanelLateral
        pestanas={[
          { id: "capas", etiqueta: "Capas", contenido: <p>contenido capas</p> },
          { id: "chat", etiqueta: "Chat", montada: true, contenido: <p>contenido chat</p> },
        ]}
      />,
    );
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Chat" }), { button: 0 });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Capas" }), { button: 0 });
    const chat = screen.getByText("contenido chat");
    expect(chat.closest("[data-state]")?.getAttribute("data-state")).toBe("inactive");
    expect(screen.queryByText("contenido capas")).not.toBeNull();
  });
});
