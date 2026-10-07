import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { cookieFalsa } from "./sesion";

type Sembrado = { token: string; slug: string; id: number };
const sembrado = (): Sembrado =>
  JSON.parse(readFileSync(path.join(__dirname, ".datos", "sembrado.json"), "utf8")) as Sembrado;

test("editar, autoguardar, recargar y activar", async ({ page, context }) => {
  const { token, slug, id } = sembrado();
  await cookieFalsa(context, token);

  const patches: number[] = [];
  page.on("response", (r) => {
    if (r.request().method() === "PATCH" && r.url().includes(`/api/brands/${slug}/templates/${id}`)) {
      patches.push(r.status());
    }
  });

  await page.goto(`/b/${slug}/templates/${id}`);
  const estado = page.getByTestId("estado-guardado");
  await expect(estado).toHaveText("Guardado");

  // Arrastrar el título 60 px a la derecha.
  const titulo = page.locator('#marco .capa[data-id="e2e_titulo"]');
  await titulo.click();
  const x0 = Number(await page.getByRole("spinbutton", { name: "X" }).inputValue());
  const caja = (await titulo.boundingBox())!;
  const cx = caja.x + caja.width / 2;
  const cy = caja.y + caja.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + 30, cy, { steps: 5 });
  await page.mouse.move(cx + 60, cy, { steps: 5 });
  await page.mouse.up();
  const x1 = Number(await page.getByRole("spinbutton", { name: "X" }).inputValue());
  expect(x1).toBeGreaterThan(x0);

  // Cambiar el texto. Escape confirma (Task 8).
  await titulo.dblclick();
  const ta = page.locator("[data-editor-texto]");
  await ta.fill("Hola desde e2e");
  await ta.press("Escape");
  await expect(estado).toHaveText("Cambios sin guardar");
  await expect(estado).toHaveText("Guardado", { timeout: 15_000 });
  expect(patches.length).toBeGreaterThan(0);
  expect(patches.every((s) => s === 200)).toBe(true);

  // Lo guardado sobrevive a la recarga.
  await page.reload();
  await expect(estado).toHaveText("Guardado");
  await expect(titulo).toContainText("Hola desde e2e");
  await titulo.click();
  const x2 = Number(await page.getByRole("spinbutton", { name: "X" }).inputValue());
  expect(Math.abs(x2 - x1)).toBeLessThanOrEqual(2);

  // Activar y verlo en la lista.
  await page.getByRole("button", { name: "Activar" }).click();
  await expect(page.getByTestId("estado-diseno")).toHaveText("Publicado");
  await expect(page.getByRole("button", { name: "Activar" })).toHaveCount(0);

  await page.goto(`/b/${slug}/templates`);
  await expect(page.getByAltText("Vista previa del diseño E2E")).toBeVisible();
  await expect(page.getByText("Publicado", { exact: true })).toBeVisible();
});
