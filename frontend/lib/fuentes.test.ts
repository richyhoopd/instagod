import { describe, expect, it } from "vitest";
import { fuenteLabel, fuentesDeMarca } from "@/lib/fuentes";

describe("fuenteLabel", () => {
  it("ig_seguidos tiene etiqueta legible, no el id crudo", () => {
    expect(fuenteLabel("ig_seguidos")).toBe("Instagram (seguidos)");
  });
  it("proveedor desconocido cae al nombre", () => {
    expect(fuenteLabel("zzz")).toBe("zzz");
  });
});

describe("fuentesDeMarca", () => {
  it("sin config usa el default", () => {
    expect(fuentesDeMarca(null)).toEqual(["pexels"]);
  });
});
