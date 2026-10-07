import type { Aspecto } from "@/hooks/use-disenos";

// Para `aspect-ratio` en CSS.
export const RELACION_DE_ASPECTO: Record<Aspecto, string> = {
  "4:5": "4/5",
  "1:1": "1/1",
  "9:16": "9/16",
};

export const ETIQUETA_DE_ASPECTO: Record<Aspecto, string> = {
  "4:5": "Cuadrada alta",
  "1:1": "Cuadrada",
  "9:16": "Vertical",
};
