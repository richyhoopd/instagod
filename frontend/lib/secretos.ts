// Traducción de claves internas de credenciales (src/secrets_store.CLAVES) a
// lenguaje de producto. La UI nunca muestra el nombre de la variable como
// texto principal; la clave técnica queda como referencia secundaria.

export type GrupoConexion = "instagram" | "telegram" | "ia" | "imagenes" | "noticias" | "sheet";

export const GRUPO_LABELS: Record<GrupoConexion, string> = {
  instagram: "Instagram",
  telegram: "Bot de Telegram",
  ia: "Textos con IA",
  imagenes: "Bancos de imágenes",
  noticias: "Fuentes de noticias",
  sheet: "Hoja de cálculo (legacy)",
};

export const SECRETO_INFO: Record<string, { label: string; ayuda: string; grupo: GrupoConexion }> = {
  IG_USER_ID: {
    label: "Cuenta de Instagram",
    ayuda: "Identificador de la cuenta de Instagram donde se publica.",
    grupo: "instagram",
  },
  IG_ACCESS_TOKEN: {
    label: "Acceso a Instagram",
    ayuda: "Permiso para publicar en la cuenta. Lo genera quien administra la app de Meta.",
    grupo: "instagram",
  },
  TELEGRAM_BOT_TOKEN: {
    label: "Bot de Telegram",
    ayuda: "Conecta el bot que avisa y deja aprobar desde Telegram.",
    grupo: "telegram",
  },
  TELEGRAM_CHAT_ID: {
    label: "Chat de Telegram",
    ayuda: "El chat o grupo donde el bot manda las publicaciones para revisar.",
    grupo: "telegram",
  },
  LLM_PROVIDER: {
    label: "Proveedor de IA",
    ayuda: "Servicio de IA que redacta los textos (por ejemplo deepseek).",
    grupo: "ia",
  },
  LLM_API_KEY: {
    label: "Llave de la IA",
    ayuda: "Llave del servicio de IA que redacta los textos de esta marca.",
    grupo: "ia",
  },
  LLM_MODEL: {
    label: "Modelo de IA",
    ayuda: "Modelo concreto a usar. Si no se define, se usa el general.",
    grupo: "ia",
  },
  PEXELS_API_KEY: {
    label: "Fotos de Pexels",
    ayuda: "Permite buscar fotos de stock en Pexels para los carruseles.",
    grupo: "imagenes",
  },
  UNSPLASH_ACCESS_KEY: {
    label: "Fotos de Unsplash",
    ayuda: "Permite buscar fotos de stock en Unsplash para los carruseles.",
    grupo: "imagenes",
  },
  NEWSAPI_KEY: {
    label: "Noticias (NewsAPI)",
    ayuda: "Trae noticias para sugerir temas de contenido.",
    grupo: "noticias",
  },
  SHEET_ID: {
    label: "Hoja de cálculo (legacy)",
    ayuda: "Espejo opcional en Google Sheets. Solo para marcas del flujo viejo.",
    grupo: "sheet",
  },
};

export function secretoLabel(clave: string): string {
  return SECRETO_INFO[clave]?.label ?? clave;
}

/** Colapsa una lista de claves faltantes en grupos humanos únicos, en orden estable. */
export function gruposFaltantes(claves: string[]): string[] {
  const grupos: GrupoConexion[] = [];
  for (const clave of claves) {
    const grupo = SECRETO_INFO[clave]?.grupo;
    if (grupo && !grupos.includes(grupo)) grupos.push(grupo);
  }
  return grupos.map((g) => GRUPO_LABELS[g]);
}
