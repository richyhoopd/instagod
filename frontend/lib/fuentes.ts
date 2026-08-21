// Fuentes de imagen del motor (src/image_sources.py). La API no expone
// GET /brands/{slug}/sources en este build (plan de Fase 3 sin llegar):
// BrandDetail.fuentes_imagen ya trae el JSON con el orden configurado para
// la marca (null/vacío → default del motor, ["pexels"]).
const FUENTE_LABELS: Record<string, string> = {
  pexels: "Pexels",
  pinterest: "Pinterest",
  unsplash: "Unsplash",
  banco: "Banco de fotos",
  covers: "Covers",
  carpeta: "Carpeta local",
  ig_accounts: "Cuentas de Instagram",
  rss: "RSS",
  newsapi: "NewsAPI",
  manual: "Manual",
};

const DEFAULT_FUENTES = ["pexels"];

export function fuenteLabel(nombre: string): string {
  return FUENTE_LABELS[nombre] ?? nombre;
}

export function fuentesDeMarca(fuentesJson: string | null | undefined): string[] {
  if (!fuentesJson) return DEFAULT_FUENTES;
  try {
    const parsed: unknown = JSON.parse(fuentesJson);
    if (Array.isArray(parsed) && parsed.length > 0 && parsed.every((v) => typeof v === "string")) {
      return parsed;
    }
  } catch {
    // JSON malformado: mismo fallback que usa el backend.
  }
  return DEFAULT_FUENTES;
}
