// Formatos editoriales del motor de slideshows (config.SLIDESHOW_FORMATOS,
// src/marcas.py::_formatos_default). La API no expone un catálogo aparte de
// formatos: BrandDetail.formatos ya trae el JSON con el subconjunto que la
// marca tiene habilitado (null/vacío → default del motor, "listicle"
// primero por ser el default editorial histórico).
export const FORMATO_LABELS: Record<string, string> = {
  listicle: "Lista",
  todo_lo_que_sabemos: "Todo lo que sabemos",
  perfil: "Perfil",
  libre: "Libre",
};

// Una línea por formato para que quien no conoce los términos editoriales
// pueda elegir sin adivinar.
export const FORMATO_DESCRIPCIONES: Record<string, string> = {
  listicle: "Un punto por slide: “5 foros que...”, “7 señales de que...”",
  todo_lo_que_sabemos: "Junta todo lo que se sabe de un tema o evento en un resumen.",
  perfil: "Presenta a una persona, banda o lugar: quién es y por qué importa.",
  libre: "La IA estructura el tema como mejor fluya, sin molde fijo.",
};

export function formatoDescripcion(formato: string): string {
  return FORMATO_DESCRIPCIONES[formato] ?? "";
}

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
