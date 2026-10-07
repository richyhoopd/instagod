import { describe, expect, it } from "vitest";
import { ETIQUETA_DE_ASPECTO, RELACION_DE_ASPECTO } from "../aspecto";
import { ASPECTO_DE_FORMATO } from "../escena";

describe("aspecto", () => {
  it("cubre los tres formatos del lienzo", () => {
    const aspectos = Object.values(ASPECTO_DE_FORMATO).sort();
    expect(Object.keys(RELACION_DE_ASPECTO).sort()).toEqual(aspectos);
    expect(Object.keys(ETIQUETA_DE_ASPECTO).sort()).toEqual(aspectos);
  });

  it("la relación es la del aspecto con diagonal", () => {
    expect(RELACION_DE_ASPECTO["9:16"]).toBe("9/16");
    expect(ETIQUETA_DE_ASPECTO["1:1"]).toBe("Cuadrada");
  });

  it("nombra cada formato igual que el selector de formato del panel", () => {
    // El encabezado del editor usa esta tabla: un 1:1 no es «Cuadrada alta».
    expect(ETIQUETA_DE_ASPECTO).toEqual({
      "4:5": "Cuadrada alta",
      "1:1": "Cuadrada",
      "9:16": "Vertical",
    });
  });
});
