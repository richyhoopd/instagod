"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

type Guardar = (escena: Escena, mensaje?: string) => Promise<unknown>;

// Guarda la escena 2 s después de la última edición. Los guardados van en
// fila: nunca hay dos PATCH en vuelo, y el que termina marca como guardada
// la revisión que mandó, no la actual.
export function useAutoguardado({
  activo,
  guardar,
  retraso = 2000,
}: {
  activo: boolean;
  guardar: Guardar;
  retraso?: number;
}) {
  const sucio = useEditor((s) => s.sucio);
  const revision = useEditor((s) => s.revision);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // La mutación cambia de identidad en cada render; el temporizador no debe
  // reiniciarse por eso.
  const guardarRef = useRef(guardar);
  useEffect(() => {
    guardarRef.current = guardar;
  });
  const cola = useRef<Promise<void>>(Promise.resolve());

  const guardarAhora = useCallback((mensaje?: string): Promise<void> => {
    const correr = async () => {
      const { escena, sucio, revision } = useEditor.getState();
      if (!escena || (!sucio && !mensaje)) return;
      setGuardando(true);
      try {
        await guardarRef.current(escena, mensaje);
        useEditor.getState().marcarGuardado(revision);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e : new Error(String(e)));
        // Un autoguardado que falla se queda en `error`; el que pidió la
        // persona con mensaje necesita saber que falló.
        if (mensaje) throw e;
      } finally {
        setGuardando(false);
      }
    };
    const p = cola.current.then(correr);
    cola.current = p.catch(() => {});
    return p;
  }, []);

  useEffect(() => {
    if (!activo || !sucio) return;
    const t = setTimeout(() => void guardarAhora(), retraso);
    return () => clearTimeout(t);
  }, [activo, sucio, revision, retraso, guardarAhora]);

  useEffect(() => {
    if (!sucio) return;
    const avisar = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, [sucio]);

  return { guardando, error, guardarAhora };
}
