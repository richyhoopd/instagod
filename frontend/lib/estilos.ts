// Presets de estilo del compilador de slideshows (config.SLIDESHOW_ESTILOS,
// src/marcas.py::estilos_de). La API todavía no expone un endpoint de
// presets (GET /brands/{slug}/presets del plan de Fase 3 no llegó a este
// build): los globales del motor se listan a mano aquí y se combinan con
// los propios de la marca (BrandDetail.estilos_json), que pisan a los
// globales igual que hace el backend.
export interface EstiloPreset {
  texto?: string;
  fondo?: string;
  background_opacity?: number;
  propio?: boolean;
}

const GLOBALES: Record<string, EstiloPreset> = {
  tiktok_bold: { texto: "blanco", fondo: "negro" },
  editorial: { texto: "negro", fondo: "crema" },
};

const ESTILO_LABELS: Record<string, string> = {
  tiktok_bold: "TikTok Bold",
  editorial: "Editorial",
};

// Subconjunto de config.SLIDESHOW_PALETA usado para el mini-preview de cada
// estilo (swatch de texto/fondo); nombres fuera de esta lista caen a gris.
const PALETA: Record<string, string> = {
  blanco: "#ffffff",
  negro: "#111111",
  verde: "#1b5e3f",
  crema: "#f5efe0",
  rojo: "#c0392b",
  amarillo: "#f1c40f",
  cobalto: "#2F52D9",
  navy: "#1A2142",
  oro: "#EAC366",
  olivo: "#223124",
  hueso: "#f9fbf7",
  laton: "#eac783",
};

export function colorSwatch(nombre: string | undefined): string {
  if (!nombre) return "#9ca3af";
  return PALETA[nombre] ?? "#9ca3af";
}

export function estiloLabel(nombre: string): string {
  return ESTILO_LABELS[nombre] ?? nombre;
}

export function estilosDeMarca(
  estilosJson: string | null | undefined
): Record<string, EstiloPreset> {
  let propios: Record<string, EstiloPreset> = {};
  if (estilosJson) {
    try {
      const parsed: unknown = JSON.parse(estilosJson);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        propios = parsed as Record<string, EstiloPreset>;
      }
    } catch {
      // JSON malformado: se ignora, igual que el backend.
    }
  }
  const combinado: Record<string, EstiloPreset> = { ...GLOBALES };
  for (const [nombre, estilo] of Object.entries(propios)) {
    combinado[nombre] = { ...estilo, propio: true };
  }
  return combinado;
}
