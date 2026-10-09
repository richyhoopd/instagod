"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/lib/api";
import { OpInvalida, type Escena, type Formato, type Op } from "@/lib/escena";
import { useJob } from "@/hooks/use-job";
import { resultadoDeJob } from "@/hooks/use-disenos";

export type MensajeHistorial = {
  version: number;
  mensaje: string;
  respuesta: string | null;
  modo: "crear" | "editar";
  kind: string | null;
  creado_en: string | null;
};

export type ResultadoChat =
  | { tipo: "escena"; escena: Escena; respuesta: string; version: number }
  | { tipo: "ops"; ops: Op[]; respuesta: string; version: number };

export function interpretarResultado(r: unknown): ResultadoChat | null {
  if (!r || typeof r !== "object") return null;
  const o = r as Record<string, unknown>;
  const respuesta = typeof o.respuesta === "string" ? o.respuesta : "";
  const version = typeof o.version === "number" ? o.version : 0;
  if (o.escena && typeof o.escena === "object") {
    return { tipo: "escena", escena: o.escena as Escena, respuesta, version };
  }
  if (Array.isArray(o.ops)) return { tipo: "ops", ops: o.ops as Op[], respuesta, version };
  return null;
}

/** Lleva el resultado al store. Si la escena cambió mientras corría el job y las ops ya no
 *  aplican, `aplicar` lanza `OpInvalida` sin registrar nada (plan 2): se devuelve el error
 *  para el chat en vez de tumbar el editor. */
export function aplicarResultado(
  r: ResultadoChat,
  store: { cargar: (e: Escena) => void; aplicar: (ops: Op[], etiqueta?: string) => void },
): string | null {
  try {
    if (r.tipo === "escena") store.cargar(r.escena);
    else store.aplicar(r.ops, `IA: ${r.respuesta.slice(0, 40)}`);
    return null;
  } catch (e) {
    if (e instanceof OpInvalida) {
      return "El diseño cambió mientras la IA trabajaba y su cambio ya no aplica. Pídelo de nuevo.";
    }
    throw e;
  }
}

export function useChatDiseno(slug: string, tid: number, alResultado: (r: ResultadoChat) => void) {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<number | null>(null);
  const [errorEnvio, setErrorEnvio] = useState<string | null>(null);
  const procesado = useRef<number | null>(null);
  const job = useJob(slug, jobId);

  const historial = useQuery<MensajeHistorial[]>({
    queryKey: ["chat", slug, tid],
    queryFn: () => get<MensajeHistorial[]>(`/brands/${slug}/templates/${tid}/chat`),
    enabled: !!slug,
  });

  const j = jobId !== null ? job.data : undefined;
  const terminado = !!j && (j.estado === "ok" || j.estado === "error" || j.estado === "cancelado");
  const resultado = j?.estado === "ok" ? interpretarResultado(resultadoDeJob<unknown>(j)) : null;

  // El resultado se entrega una sola vez por job; el estado se deriva en el render.
  useEffect(() => {
    if (!j || jobId === null || procesado.current === jobId) return;
    if (j.estado === "ok") {
      procesado.current = jobId;
      if (resultado) alResultado(resultado);
      void qc.invalidateQueries({ queryKey: ["chat", slug, tid] });
    } else if (j.estado === "error" || j.estado === "cancelado") {
      procesado.current = jobId;
    }
  }, [j, jobId, resultado, alResultado, qc, slug, tid]);

  let error = errorEnvio;
  if (!error && j && (j.estado === "error" || j.estado === "cancelado")) {
    error = "No se pudo completar. Intenta de nuevo o reformula.";
  } else if (!error && j?.estado === "ok" && !resultado) {
    error = "El job terminó sin resultado.";
  }

  const enviar = useCallback(
    async (mensaje: string, modo: "crear" | "editar", escena: Escena | null, formato?: Formato) => {
      setErrorEnvio(null);
      try {
        const r = await post<{ job_id: number }>(`/brands/${slug}/templates/${tid}/chat`, {
          mensaje,
          modo,
          escena: modo === "editar" ? escena : null,
          formato: formato ?? null,
        });
        setJobId(r.job_id);
      } catch {
        setErrorEnvio("No se pudo enviar el mensaje. Intenta de nuevo.");
      }
    },
    [slug, tid],
  );

  return {
    historial: historial.data ?? [],
    enviar,
    ocupado: jobId !== null && !terminado,
    progreso: j,
    error,
  };
}
