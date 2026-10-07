import { expect, test, type Page } from "@playwright/test";
import { cookieFalsa } from "./sesion";

type CapaEstado = { id: string; x: number; y: number; w: number; h: number; rot: number; texto?: string };
type Estado = { sel: string[]; pasado: number; editando: string | null; capas: CapaEstado[] };

async function estado(page: Page): Promise<Estado> {
  return JSON.parse(await page.getByTestId("estado").innerText());
}
const capa = async (page: Page, id: string) => (await estado(page)).capas.find((c) => c.id === id)!;

async function arrastrar(page: Page, x: number, y: number, dx: number, dy: number) {
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx / 2, y + dy / 2, { steps: 5 });
  await page.mouse.move(x + dx, y + dy, { steps: 5 });
  await page.mouse.up();
}

test.beforeEach(async ({ context, page }) => {
  await cookieFalsa(context);
  const errores: string[] = [];
  page.on("pageerror", (e) => errores.push(e.message));
  await page.goto("/dev/editor");
  await expect(page.locator('#marco .capa[data-id="titulo"]')).toBeVisible();
});

test("arrastrar es un paso y deshacer regresa", async ({ page }) => {
  const titulo = page.locator('#marco .capa[data-id="titulo"]');
  await titulo.click();
  await expect.poll(async () => (await estado(page)).sel).toEqual(["titulo"]);
  const antes = (await titulo.boundingBox())!;
  await arrastrar(page, antes.x + antes.width / 2, antes.y + antes.height / 2, 100, 0);

  // Zoom 0.5: 100 px de pantalla son 200 px del lienzo.
  await expect.poll(async () => (await capa(page, "titulo")).x).toBeGreaterThan(270);
  const t = await capa(page, "titulo");
  expect(t.x).toBeLessThan(290);
  expect((await estado(page)).pasado).toBe(1);

  // Sin restaurar el DOM, la caja quedaría 200 px a la derecha y no 100.
  const despues = (await titulo.boundingBox())!;
  expect(despues.x - antes.x).toBeGreaterThan(95);
  expect(despues.x - antes.x).toBeLessThan(105);

  await page.getByRole("button", { name: "Deshacer" }).click();
  await expect.poll(async () => (await capa(page, "titulo")).x).toBe(80);
});

test("el lazo selecciona la raíz del grupo", async ({ page }) => {
  const marco = (await page.locator("#marco").boundingBox())!;
  // Pantalla y 600–720 son lienzo y 1136–1376: toca caja y logo, no el título.
  await arrastrar(page, marco.x + 5, marco.y + 600, 695, 120);
  await expect.poll(async () => (await estado(page)).sel).toEqual(["marca"]);
});

test("arrastrar un hijo mueve el grupo completo en un paso", async ({ page }) => {
  const caja = page.locator('#marco .capa[data-id="caja"]');
  const b = (await caja.boundingBox())!;
  // El centro de caja (x 540) no cae sobre logo (x 900–1020).
  await page.mouse.click(b.x + b.width / 2, b.y + b.height / 2);
  await expect.poll(async () => (await estado(page)).sel).toEqual(["marca"]);
  await arrastrar(page, b.x + b.width / 2, b.y + b.height / 2, 0, -100);

  await expect.poll(async () => (await capa(page, "caja")).y).toBeLessThan(1010);
  expect((await capa(page, "caja")).y).toBeGreaterThan(990);
  const e = await estado(page);
  const logo = e.capas.find((c) => c.id === "logo")!;
  const marca = e.capas.find((c) => c.id === "marca")!;
  expect(logo.y).toBeGreaterThan(1020);
  expect(logo.y).toBeLessThan(1040);
  expect(marca.y).toBe((await capa(page, "caja")).y);
  expect(e.pasado).toBe(1);
});

test("redimensionar una capa desde la esquina", async ({ page }) => {
  await page.locator('#marco .capa[data-id="titulo"]').click();
  const manija = page.locator(".moveable-control.moveable-se");
  await expect(manija).toBeVisible();
  const m = (await manija.boundingBox())!;
  await arrastrar(page, m.x + m.width / 2, m.y + m.height / 2, 50, 50);

  await expect.poll(async () => (await capa(page, "titulo")).w).toBeGreaterThan(1010);
  const t = await capa(page, "titulo");
  expect(t.w).toBeLessThan(1030);
  expect(t.h).toBeGreaterThan(390);
  expect(t.h).toBeLessThan(410);
  expect((await estado(page)).pasado).toBe(1);
});
