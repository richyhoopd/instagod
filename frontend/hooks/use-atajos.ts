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

export function useAtajos() {
  useEffect(() => {
    const alTeclear = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      const s = useEditor.getState();
      if (ignorar(e, s)) return;
      const accion = accionDe(e);
      if (!accion) return;
      e.preventDefault();
      accion(s);
    };
    window.addEventListener("keydown", alTeclear);
    return () => window.removeEventListener("keydown", alTeclear);
  }, []);
}
