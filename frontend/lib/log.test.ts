import { describe, expect, it } from "vitest";
import { ultimaLinea } from "@/lib/log";

describe("ultimaLinea", () => {
  it("devuelve la última línea con contenido aunque el log termine en salto", () => {
    expect(ultimaLinea("a\nHTTP 429\n")).toBe("HTTP 429");
    expect(ultimaLinea("a\nHTTP 429\n\n  \n")).toBe("HTTP 429");
  });
  it("tolera log vacío o nulo", () => {
    expect(ultimaLinea(null)).toBe("");
    expect(ultimaLinea(undefined)).toBe("");
    expect(ultimaLinea("\n")).toBe("");
  });
  it("una sola línea", () => {
    expect(ultimaLinea("solo")).toBe("solo");
  });
});
