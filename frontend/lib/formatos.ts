// Formatos editoriales del motor de slideshows (config.SLIDESHOW_FORMATOS,
// src/marcas.py::_formatos_default). La API no expone un catálogo aparte de
// formatos: BrandDetail.formatos ya trae el JSON con el subconjunto que la
// marca tiene habilitado (null/vacío → default del motor, "listicle"
// primero por ser el default editorial histórico).
export const FORMATO_LABELS: Record<string, string> = {
  listicle: "Listicle",
  todo_lo_que_sabemos: "Todo lo que sabemos",
  perfil: "Perfil",
  libre: "Libre",
};

const DEFAULT_FORMATOS = ["listicle", "libre", "perfil", "todo_lo_que_sabemos"];

export function formatosDeMarca(formatosJson: string | null | undefined): string[] {
  if (!formatosJson) return DEFAULT_FORMATOS;
  try {
    const parsed: unknown = JSON.parse(formatosJson);
    if (Array.isArray(parsed) && parsed.length > 0 && parsed.every((v) => typeof v === "string")) {
      return parsed;
    }
  } catch {
    // JSON malformado: mismo fallback que usa el backend (src/marcas.py).
  }
  return DEFAULT_FORMATOS;
}

export function formatoLabel(formato: string): string {
  return FORMATO_LABELS[formato] ?? formato;
}
