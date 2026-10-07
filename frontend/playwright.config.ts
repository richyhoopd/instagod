import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

// El frontend de prueba corre en 3101 y NUNCA reutiliza un servidor ya vivo:
// un `next dev` en 3000/3101 puede tener otro API_URL (rewrites fijados al
// arrancar) y las pruebas pegarían a una API que no es la sembrada.
// API_URL apunta al backend de e2e (Task 15), en 8102 con su propia base en
// e2e/.datos/.
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 60_000,
  use: { baseURL: "http://127.0.0.1:3101", trace: "retain-on-failure" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: [
    {
      // Siembra una base desechable y levanta la API sobre ella. Nunca se
      // reutiliza un servidor: la base se recrea en cada corrida.
      command:
        "/Users/ricardo/Work/personal/instagod/.venv/bin/python frontend/e2e/sembrar.py && exec /Users/ricardo/Work/personal/instagod/.venv/bin/uvicorn api.app:app --host 127.0.0.1 --port 8102",
      cwd: "..",
      url: "http://127.0.0.1:8102/health",
      reuseExistingServer: false,
      timeout: 60_000,
      env: { DB_PATH: path.resolve(__dirname, "e2e/.datos/e2e.db"), ENV: "dev" },
    },
    {
      command: "pnpm exec next dev --port 3101 --hostname 127.0.0.1",
      url: "http://127.0.0.1:3101/login",
      reuseExistingServer: false,
      timeout: 180_000,
      env: { API_URL: "http://127.0.0.1:8102", NEXT_DIST_DIR: ".next-e2e" },
    },
  ],
});
