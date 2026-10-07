"use client";

import { useEffect } from "react";
import { esCampoDeTexto } from "@/lib/edicion";
import { useEditor, type EstadoEditor } from "@/stores/editor";

type Accion = (s: EstadoEditor) => void;

const FLECHAS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

// Traduce una tecla a una acción del store. ⌘ en Mac y Ctrl en lo demás
// hacen lo mismo. Los corchetes se leen por `code` porque en teclados en
// español `key` no es "[".
export function accionDe(e: KeyboardEvent): Accion | null {
  if (e.metaKey || e.ctrlKey) {
    if (e.altKey) return null;
    if (e.code === "BracketRight") return (s) => s.ordenarZ(e.shiftKey ? "frente" : "subir");
    if (e.code === "BracketLeft") return (s) => s.ordenarZ(e.shiftKey ? "fondo" : "bajar");
    switch (e.key.toLowerCase()) {
      case "z":
        return e.shiftKey ? (s) => s.rehacer() : (s) => s.deshacer();
      case "y":
        return (s) => s.rehacer();
      case "c":
        return (s) => s.copiar();
      case "v":
        return (s) => s.pegar();
      case "d":
        return (s) => s.duplicar();
      case "g":
        return e.shiftKey ? (s) => s.desagrupar() : (s) => s.agrupar();
      default:
        return null;
    }
  }
  if (e.altKey) return null;
  if (e.key === "Delete" || e.key === "Backspace") return (s) => s.borrar();
  if (e.key === "Escape") return (s) => s.seleccionar([]);
  const flecha = FLECHAS[e.key];
  if (flecha) {
    const paso = e.shiftKey ? 10 : 1;
    return (s) => s.mover(flecha[0] * paso, flecha[1] * paso);
  }
  return null;
}

function ignorar(e: KeyboardEvent, s: EstadoEditor): boolean {
  if (!s.escena || s.editandoTexto) return true;
  if (esCampoDeTexto(e.target)) return true;
  return e.target instanceof Element && e.target.closest('[role="dialog"],[role="alertdialog"]') !== null;
}

// Cuántas veces se repite una tecla mantenida sin sentido: ⌘D, ⌘V, ⌘G y ⌘Z.
const SIN_REPETIR = new Set(["z", "y", "v", "d", "g"]);

function huella(s: EstadoEditor): [unknown, unknown, string] {
  return [s.escena, s.portapapeles, s.seleccion.join("\0")];
}

// ¿La primera pulsación habría hecho algo? Sin eso no se bloquea el nativo.
function habriaActuado(tecla: string, s: EstadoEditor): boolean {
  if (tecla === "z") return s.pasado.length > 0 || s.futuro.length > 0;
  if (tecla === "y") return s.futuro.length > 0;
  if (tecla === "v") return s.portapapeles.length > 0;
  return s.seleccion.length > 0;
}

export function useAtajos(activo = true) {
  useEffect(() => {
    if (!activo) return;
    const alTeclear = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.isComposing || e.keyCode === 229) return;
      const s = useEditor.getState();
      if (ignorar(e, s)) return;
      const accion = accionDe(e);
      if (!accion) return;
      if (e.repeat && (e.metaKey || e.ctrlKey) && SIN_REPETIR.has(e.key.toLowerCase())) {
        // La acción no se repite, pero el navegador tampoco debe recibir el
        // atajo (⌘D abre "agregar marcador"). Solo si la primera pulsación
        // habría hecho algo: sin selección ⌘D no actúa y no se bloquea.
        if (habriaActuado(e.key.toLowerCase(), s)) e.preventDefault();
        return;
      }
      const antes = huella(s);
      accion(s);
      // Solo se bloquea el comportamiento nativo si la acción hizo algo: sin
      // selección, las flechas siguen haciendo scroll y ⌘C copia texto.
      const despues = huella(useEditor.getState());
      if (antes.some((v, i) => v !== despues[i])) e.preventDefault();
    };
    window.addEventListener("keydown", alTeclear);
    return () => window.removeEventListener("keydown", alTeclear);
  }, [activo]);
}
