"use client";

import { useCallback, useState } from "react";
import { useEditor } from "@/stores/editor";
import { aplicarResultado, useChatDiseno, type ResultadoChat } from "@/hooks/use-chat-diseno";

export function PanelChat({ slug, tid }: { slug: string; tid: number }) {
  const escena = useEditor((s) => s.escena);
  const cargar = useEditor((s) => s.cargar);
  const aplicar = useEditor((s) => s.aplicar);
  const [texto, setTexto] = useState("");
  const [modo, setModo] = useState<"crear" | "editar">(escena?.capas?.length ? "editar" : "crear");
  const [ultima, setUltima] = useState<string | null>(null);
  const [errorAplicar, setErrorAplicar] = useState<string | null>(null);

  const alResultado = useCallback(
    (r: ResultadoChat) => {
      const err = aplicarResultado(r, { cargar, aplicar });
      setErrorAplicar(err);
      if (err) return;
      setUltima(r.respuesta);
      setModo("editar");
    },
    [cargar, aplicar],
  );

  const { historial, enviar, ocupado, progreso, error } = useChatDiseno(slug, tid, alResultado);

  const mandar = async () => {
    const m = texto.trim();
    if (!m || ocupado) return;
    if (modo === "crear" && escena?.capas?.length &&
        !window.confirm("Crear desde cero reemplaza el diseño y no se puede deshacer. ¿Seguir?")) {
      return;
    }
    await enviar(m, modo, escena ?? null);
    setTexto("");
  };

  return (
    <div className="flex h-full flex-col gap-3 p-3 text-sm">
      <div className="flex gap-1 rounded-md bg-muted p-1">
        {(["crear", "editar"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setModo(m)}
            className={`flex-1 rounded px-2 py-1 ${modo === m ? "bg-background shadow-sm" : ""}`}
          >
            {m === "crear" ? "Crear desde cero" : "Editar este"}
          </button>
        ))}
      </div>

      <ol className="flex-1 space-y-3 overflow-y-auto">
        {historial.map((h) => (
          <li key={h.version} className="space-y-1">
            <p className="rounded-md bg-muted px-2 py-1">{h.mensaje}</p>
            {h.respuesta && <p className="px-2 text-muted-foreground">{h.respuesta}</p>}
          </li>
        ))}
        {ocupado && (
          <li className="px-2 text-muted-foreground">
            Pensando… {progreso?.progreso ? `${progreso.progreso}%` : ""}
          </li>
        )}
        {ultima && !ocupado && historial.length === 0 && (
          <li className="px-2 text-muted-foreground">{ultima}</li>
        )}
      </ol>

      {(error ?? errorAplicar) && <p className="text-destructive">{error ?? errorAplicar}</p>}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void mandar();
        }}
        className="flex flex-col gap-2"
      >
        <textarea
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void mandar();
          }}
          rows={3}
          maxLength={2000}
          placeholder={modo === "crear" ? "Post de 3 señales de que tu regla no es normal" : "El título más grande y en amarillo"}
          className="w-full resize-none rounded-md border bg-background p-2"
          disabled={ocupado}
        />
        <button
          type="submit"
          disabled={ocupado || !texto.trim()}
          className="rounded-md bg-primary px-3 py-2 text-primary-foreground disabled:opacity-50"
        >
          {ocupado ? "Trabajando…" : "Enviar"}
        </button>
      </form>
    </div>
  );
}
