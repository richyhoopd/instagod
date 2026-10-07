"use client";

import { useEffect, useRef, useState } from "react";
import { MAX_TEXTO, resolverColor, type CapaTexto, type Op, type Span, type Tokens } from "@/lib/escena";
import { ajustarSpans, pintarSpan, utf16ACodePoint } from "@/lib/spans";
import { useEditor } from "@/stores/editor";

type Props = { capa: CapaTexto; tokens: Tokens; colorMarca: string; zoom: number };
type Opcion = { valor: string; nombre: string; css: string };

const mismos = (a: Span[], b: Span[]) => JSON.stringify(a) === JSON.stringify(b);

export function EditorTexto({ capa, tokens, colorMarca, zoom }: Props) {
  const [texto, setTexto] = useState(capa.texto);
  const [spans, setSpans] = useState<Span[]>(capa.estilo.spans ?? []);
  const ref = useRef<HTMLTextAreaElement>(null);
  const terminado = useRef(false);

  useEffect(() => {
    ref.current?.focus();
  }, []);

  const confirmar = () => {
    if (terminado.current) return;
    terminado.current = true;
    const ops: Op[] = [];
    if (texto !== capa.texto) ops.push({ op: "set", capa: capa.id, ruta: "texto", valor: texto });
    if (!mismos(spans, capa.estilo.spans ?? [])) ops.push({ op: "set", capa: capa.id, ruta: "estilo.spans", valor: spans });
    const st = useEditor.getState();
    if (ops.length) st.aplicar(ops, "Editar texto");
    st.editarTexto(null);
  };

  const opciones: Opcion[] = Object.keys(tokens.colores).map((k) => ({
    valor: `token:${k}`,
    nombre: k,
    css: resolverColor(`token:${k}`, tokens, colorMarca),
  }));
  if (!("marca" in tokens.colores)) opciones.push({ valor: "token:marca", nombre: "marca", css: colorMarca });

  // La selección del textarea es UTF-16; los tramos van en code points.
  const pintar = (color: string | null) => {
    const ta = ref.current;
    if (!ta || ta.selectionStart === ta.selectionEnd) return;
    const desde = utf16ACodePoint(texto, ta.selectionStart);
    const hasta = utf16ACodePoint(texto, ta.selectionEnd);
    setSpans((s) => pintarSpan(s, desde, hasta, color, Array.from(texto).length));
  };

  const e = capa.estilo;
  return (
    <>
      <textarea
        ref={ref}
        data-editor-texto
        aria-label={`Texto de ${capa.nombre}`}
        value={texto}
        maxLength={MAX_TEXTO}
        spellCheck={false}
        onChange={(ev) => {
          const nuevo = ev.target.value;
          const cursor = utf16ACodePoint(nuevo, ev.target.selectionStart);
          setSpans((s) => ajustarSpans(texto, nuevo, s, cursor));
          setTexto(nuevo);
        }}
        onBlur={confirmar}
        onKeyDown={(ev) => {
          ev.stopPropagation();
          if (ev.key === "Escape") {
            ev.preventDefault();
            confirmar();
          }
        }}
        style={{
          position: "absolute",
          left: capa.x,
          top: capa.y,
          width: capa.w,
          height: capa.h,
          transform: `rotate(${capa.rot}deg)`,
          zIndex: 10_000,
          margin: 0,
          padding: 0,
          border: "none",
          resize: "none",
          overflow: "hidden",
          background: "transparent",
          outline: `${2 / zoom}px solid #3b82f6`,
          fontFamily: e.fontFamily,
          fontWeight: e.fontWeight,
          fontSize: e.fontSize,
          lineHeight: e.lineHeight,
          letterSpacing: e.letterSpacing,
          textAlign: e.textAlign,
          textTransform: e.textTransform,
          color: resolverColor(e.color, tokens, colorMarca),
        }}
      />
      <div
        style={{
          position: "absolute",
          left: capa.x,
          top: capa.y,
          width: 0,
          height: 0,
          zIndex: 10_001,
          transform: `scale(${1 / zoom})`,
          transformOrigin: "0 0",
        }}
      >
        <div
          data-editor-barra
          className="absolute bottom-2 left-0 flex items-center gap-1 whitespace-nowrap rounded-md border bg-background p-1 shadow-md"
        >
          {opciones.map((o) => (
            <button
              key={o.nombre}
              type="button"
              aria-label={`Color ${o.nombre}`}
              title={o.nombre}
              className="size-6 rounded-sm border"
              style={{ background: o.css }}
              onMouseDown={(ev) => ev.preventDefault()}
              onClick={() => pintar(o.valor)}
            />
          ))}
          <button
            type="button"
            className="h-6 rounded-sm px-2 text-xs hover:bg-muted"
            onMouseDown={(ev) => ev.preventDefault()}
            onClick={() => pintar(null)}
          >
            Quitar
          </button>
        </div>
      </div>
    </>
  );
}
