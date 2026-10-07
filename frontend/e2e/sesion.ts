import type { BrowserContext } from "@playwright/test";

// proxy.ts solo revisa que exista la cookie; las páginas /dev no llaman a la API.
export async function cookieFalsa(context: BrowserContext, valor = "e2e") {
  await context.addCookies([{ name: "instagod_session", value: valor, url: "http://127.0.0.1:3100" }]);
}
