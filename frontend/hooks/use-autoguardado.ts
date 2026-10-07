"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

type Estado = ReturnType<typeof useEditor.getState>;
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
  // Mientras una restauración está en vuelo no se dispara ningún autoguardado:
  // su PATCH podría llegar al servidor después del revert y pisarlo.
  const [pausado, setPausado] = useState(false);
  const pausadoRef = useRef(false);

  // La mutación cambia de identidad en cada render; el temporizador no debe
  // reiniciarse por eso.
  const guardarRef = useRef(guardar);
  useEffect(() => {
    guardarRef.current = guardar;
  });
  const cola = useRef<Promise<void>>(Promise.resolve());
  // Todo lo que toca el servidor (guardados y reverts) corre en esta fila.
  const encolar = useCallback(<T,>(tarea: () => Promise<T>): Promise<T> => {
    const p = cola.current.then(tarea);
    cola.current = p.then(
      () => {},
      () => {},
    );
    return p;
  }, []);

  const activoRef = useRef(activo);
  useEffect(() => {
    activoRef.current = activo;
  });

  // `instantanea` fija la escena y la revisión al llamar (el flush de
  // desmontaje, que corre antes de que la página vacíe el store).
  // Resuelve true si guardó o no había nada que guardar; false si un
  // autoguardado falló (con mensaje, en cambio, rechaza).
  const guardarAhora = useCallback((mensaje?: string, instantanea?: Estado): Promise<boolean> => {
    // Con instantánea (flush de desmontaje) todo se fija ahora: cuando la fila
    // llegue a correr, la ref puede haber cambiado.
    const guardarFijo = instantanea ? guardarRef.current : null;
    const activoFijo = instantanea ? activoRef.current : null;
    const correr = async (): Promise<boolean> => {
      if (!(activoFijo ?? activoRef.current)) {
        if (mensaje) throw new Error("El autoguardado está inactivo: no se puede guardar este diseño.");
        return true;
      }
      if (pausadoRef.current && !mensaje && !instantanea) return true;
      const { escena, sucio, revision, idCarga } = instantanea ?? useEditor.getState();
      if (!escena) {
        if (mensaje) throw new Error("No hay escena cargada que guardar.");
        return true;
      }
      if (!sucio && !mensaje) return true;
      setGuardando(true);
      try {
        await (guardarFijo ?? guardarRef.current)(escena, mensaje);
        // Si mientras tanto se cargó o vació otra escena, este guardado ya no
        // habla del estado actual.
        if (useEditor.getState().idCarga === idCarga) useEditor.getState().marcarGuardado(revision);
        setError(null);
        return true;
      } catch (e) {
        setError(e instanceof Error ? e : new Error(String(e)));
        // Un autoguardado que falla se queda en `error`; el que pidió la
        // persona con mensaje necesita saber que falló.
        if (mensaje) throw e;
        return false;
      } finally {
        setGuardando(false);
      }
    };
    return encolar(correr);
  }, [encolar]);

  // Restaurar una versión: vuelca lo pendiente (y espera lo que va en vuelo),
  // pausa el autoguardado mientras corre `accion` y lo reanuda al terminar.
  const restaurar = useCallback(
    async <T,>(accion: () => Promise<T>): Promise<T> => {
      await guardarAhora();
      // En la fila: un flush de desmontaje no corre en paralelo con el revert.
      return encolar(async () => {
        pausadoRef.current = true;
        setPausado(true);
        try {
          return await accion();
        } finally {
          pausadoRef.current = false;
          setPausado(false);
        }
      });
    },
    [guardarAhora, encolar],
  );

  useEffect(() => {
    if (!activo || !sucio || pausado) return;
    const t = setTimeout(() => void guardarAhora(), retraso);
    return () => clearTimeout(t);
  }, [activo, sucio, pausado, revision, retraso, guardarAhora]);

  // Navegación SPA o cambio de diseño (la página remonta por id): lo que quedó
  // sucio se manda ahora.
  useEffect(
    () => () => {
      const s = useEditor.getState();
      if (activoRef.current && s.sucio && s.escena) void guardarAhora(undefined, s);
    },
    [guardarAhora],
  );

  useEffect(() => {
    if (!activo || !sucio) return;
    const avisar = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, [activo, sucio]);

  return { guardando, error, guardarAhora, restaurar };
}
