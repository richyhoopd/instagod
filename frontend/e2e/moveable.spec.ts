import { expect, test, type Page } from "@playwright/test";
import { cookieFalsa } from "./sesion";

type Estado = { sel: string[]; cajas: { id: string; x: number; y: number }[]; ultimo: number[] | null };

async function estado(page: Page): Promise<Estado> {
  return JSON.parse(await page.getByTestId("estado").innerText());
}

test.beforeEach(async ({ context }) => {
  await cookieFalsa(context);
});

test("moveable arrastra dentro de un escenario con scale(0.5)", async ({ page }) => {
  const errores: string[] = [];
  page.on("pageerror", (e) => errores.push(e.message));
  await page.goto("/dev/moveable");

  const b = page.locator('[data-id="b"]');
  await b.click();
  await expect.poll(async () => (await estado(page)).sel).toEqual(["b"]);

  const caja = (await b.boundingBox())!;
  const cx = caja.x + caja.width / 2;
  const cy = caja.y + caja.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + 50, cy, { steps: 5 });
  await page.mouse.move(cx + 100, cy, { steps: 5 });
  await page.mouse.up();

  // 100 px de pantalla a escala 0.5 son 200 px del escenario: b pasa de x=400 a ~600.
  await expect.poll(async () => (await estado(page)).cajas.find((c) => c.id === "b")!.x).toBeGreaterThan(590);
  const x = (await estado(page)).cajas.find((c) => c.id === "b")!.x;
  expect(x).toBeLessThan(610);
  expect(errores).toEqual([]);
});

test("selecto selecciona con lazo", async ({ page }) => {
  const errores: string[] = [];
  page.on("pageerror", (e) => errores.push(e.message));
  await page.goto("/dev/moveable");

  const marco = (await page.locator("#marco").boundingBox())!;
  // a está en (20,20)-(120,120) y c en (20,200)-(120,300) de pantalla; b empieza en x=200.
  await page.mouse.move(marco.x + 5, marco.y + 5);
  await page.mouse.down();
  await page.mouse.move(marco.x + 80, marco.y + 150, { steps: 5 });
  await page.mouse.move(marco.x + 150, marco.y + 310, { steps: 5 });
  await page.mouse.up();

  await expect.poll(async () => [...(await estado(page)).sel].sort()).toEqual(["a", "c"]);
  expect(errores).toEqual([]);
});
