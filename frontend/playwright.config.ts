import { defineConfig, devices } from "@playwright/test";

// El frontend de prueba corre en 3100 para no chocar con un `pnpm dev` en 3000.
// API_URL apunta al backend de e2e (Task 15). Hasta entonces, las páginas
// de dev no llaman a la API.
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 60_000,
  use: { baseURL: "http://127.0.0.1:3100", trace: "retain-on-failure" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: [
    {
      command: "pnpm exec next dev --port 3100 --hostname 127.0.0.1",
      url: "http://127.0.0.1:3100/login",
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: { API_URL: "http://127.0.0.1:8102" },
    },
  ],
});
