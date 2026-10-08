import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { cookieFalsa } from "./sesion";

type Sembrado = { token: string; slug: string; id: number };
const sembrado = (): Sembrado =>
  JSON.parse(readFileSync(path.join(__dirname, ".datos", "sembrado.json"), "utf8")) as Sembrado;

// Dentro del max-w-6xl y junto al menú de la marca, la columna del lienzo
// quedaba en ~310 px y el 4:5 se veía como una tira alta y angosta.
test("el lienzo usa el ancho de la ventana y conserva el 4:5", async ({ page, context }) => {
  const { token, slug, id } = sembrado();
  await cookieFalsa(context, token);

  await page.goto(`/b/${slug}/templates/${id}`);
  await expect(page.getByTestId("estado-guardado")).toHaveText("Guardado");

  const vista = page.viewportSize()!;
  const marco = (await page.locator("#marco").boundingBox())!;
  expect(marco.width).toBeGreaterThan(vista.width * 0.5);

  const escenario = page.getByTestId("escenario");
  await expect
    .poll(async () => (await escenario.boundingBox())!.height)
    .toBeGreaterThan(marco.height * 0.8);
  const caja = (await escenario.boundingBox())!;
  expect(caja.width / caja.height).toBeCloseTo(0.8, 2);
});
