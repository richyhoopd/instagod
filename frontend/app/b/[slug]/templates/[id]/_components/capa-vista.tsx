"use client";

import type { CSSProperties } from "react";
import { ImageIcon } from "lucide-react";
import {
  ocultasEfectivas,
  ordenadas,
  resolverColor,
  urlDeAsset,
  type Capa,
  type CapaTexto,
  type Escena,
  type Fondo,
  type Tokens,
} from "@/lib/escena";
import { trozos } from "@/lib/spans";

const VERTICAL: Record<string, CSSProperties["justifyContent"]> = {
  top: "flex-start",
  center: "center",
  bottom: "flex-end",
};

export function radioDeMascara(mascara: string): string | undefined {
  if (mascara === "circle") return "50%";
  const m = /^rounded:(\d+)$/.exec(mascara);
  return m ? `${m[1]}px` : undefined;
}

// Mismo criterio que _fondo_css del plan 1: el gradiente va tal cual y la
// imagen cubre el lienzo.
export function fondoCss(fondo: Fondo, tokens: Tokens, colorMarca: string, slug: string): string {
  if (fondo.tipo === "gradiente") return fondo.valor;
  if (fondo.tipo === "imagen") return `url('${urlDeAsset(slug, fondo.valor)}') center/cover no-repeat`;
  return resolverColor(fondo.valor, tokens, colorMarca);
}

// Las fuentes de la marca se sirven desde el backend; se declaran solo las
// que usa la escena.
export function EstilosFuentes({ slug, familias }: { slug: string; familias: string[] }) {
  if (familias.length === 0) return null;
  const css = familias
    .map(
      (f) =>
        `@font-face{font-family:'${f.replace(/'/g, "")}';src:url('/api/brands/${slug}/files/fonts/${encodeURIComponent(f)}');font-display:swap;}`,
    )
    .join("\n");
  return <style>{css}</style>;
}

type Props = { capa: Capa; tokens: Tokens; slug: string; colorMarca: string; editando?: boolean };

export function CapaVista({ capa, tokens, slug, colorMarca, editando = false }: Props) {
  if (capa.tipo === "group") return null;
  const color = (v: string) => resolverColor(v, tokens, colorMarca);
  const caja: CSSProperties = {
    position: "absolute",
    left: capa.x,
    top: capa.y,
    width: capa.w,
    height: capa.h,
    transform: `rotate(${capa.rot}deg)`,
    opacity: capa.opacity,
    zIndex: capa.z,
  };

  if (capa.tipo === "text") {
    const e = capa.estilo;
    return (
      <div
        data-id={capa.id}
        className="capa"
        style={{
          ...caja,
          display: "flex",
          flexDirection: "column",
          justifyContent: VERTICAL[e.verticalAlign ?? "top"],
          overflow: "hidden",
          // Mientras se edita, el textarea (Task 8) ocupa su lugar.
          visibility: editando ? "hidden" : undefined,
        }}
      >
        <div
          style={{
            fontFamily: familiaCss(e.fontFamily),
            fontWeight: e.fontWeight,
            fontSize: e.fontSize,
            lineHeight: e.lineHeight,
            letterSpacing: e.letterSpacing,
            color: color(e.color),
            textAlign: e.textAlign,
            textTransform: e.textTransform,
            // Paridad con escena.py: el texto fijo respeta saltos (pre-line,
            // pre si nowrap); el dato del post no. whiteSpace va antes que
            // textWrap porque el shorthand reinicia text-wrap-mode.
            ...cortesDeTexto(capa),
            overflowWrap: "break-word",
          }}
        >
          {trozos(capa.texto, e.spans).map((t, i) => (
            <span key={i} style={t.color ? { color: color(t.color) } : undefined}>
              {t.texto}
            </span>
          ))}
        </div>
      </div>
    );
  }

  if (capa.tipo === "shape") {
    const e = capa.estilo;
    const borde = e.borderWidth ?? 0;
    return (
      <div data-id={capa.id} className="capa" style={caja}>
        <div
          style={{
            width: "100%",
            height: "100%",
            boxSizing: "border-box",
            backgroundColor: color(e.fill),
            borderRadius: capa.forma === "ellipse" ? "50%" : (e.radius ?? 0),
            border: borde > 0 ? `${borde}px solid ${color(e.borderColor ?? "#000000")}` : undefined,
            filter: e.filter,
            mixBlendMode: e.mixBlendMode as CSSProperties["mixBlendMode"],
          }}
        />
      </div>
    );
  }

  if (capa.tipo === "svg") {
    return (
      <div data-id={capa.id} className="capa" style={caja}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={urlDeAsset(slug, capa.src)}
          alt=""
          draggable={false}
          style={{
            width: "100%",
            height: "100%",
            objectFit: capa.ajuste,
            filter: capa.estilo.filter,
            mixBlendMode: capa.estilo.mixBlendMode as CSSProperties["mixBlendMode"],
            pointerEvents: "none",
          }}
        />
      </div>
    );
  }

  // image y video
  const medio: CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: capa.ajuste,
    objectPosition: capa.estilo.objectPosition,
    filter: capa.estilo.filter,
    mixBlendMode: capa.estilo.mixBlendMode as CSSProperties["mixBlendMode"],
    borderRadius: radioDeMascara(capa.mascara),
    pointerEvents: "none",
  };
  if (!capa.src) {
    return (
      <div data-id={capa.id} className="capa" style={caja}>
        <div
          className="flex flex-col items-center justify-center gap-2 bg-muted text-muted-foreground"
          style={{ ...medio, fontSize: Math.max(18, Math.min(capa.w, capa.h) / 12) }}
        >
          <ImageIcon style={{ width: "20%", height: "20%" }} />
          <span>Campo: {capa.campo ?? "imagen"}</span>
        </div>
      </div>
    );
  }
  if (capa.tipo === "video") {
    return (
      <div data-id={capa.id} className="capa" style={caja}>
        <video
          src={urlDeAsset(slug, capa.src)}
          poster={capa.poster ? urlDeAsset(slug, capa.poster) : undefined}
          muted
          playsInline
          style={medio}
        />
      </div>
    );
  }
  return (
    <div data-id={capa.id} className="capa" style={caja}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={urlDeAsset(slug, capa.src)} alt="" draggable={false} style={medio} />
    </div>
  );
}

type PropsEscenario = { escena: Escena; slug: string; colorMarca: string; editandoTexto?: string | null };

// Las capas en orden de pintado. El fondo lo pone quien contiene al escenario.
export function Escenario({ escena, slug, colorMarca, editandoTexto = null }: PropsEscenario) {
  const ocultas = ocultasEfectivas(escena);
  const visibles = ordenadas(escena).filter((c) => c.tipo !== "group" && !ocultas.has(c.id));
  const familias = [...new Set(visibles.flatMap((c) => (c.tipo === "text" ? [c.estilo.fontFamily] : [])))];
  return (
    <>
      <EstilosFuentes slug={slug} familias={familias} />
      {visibles.map((c) => (
        <CapaVista
          key={c.id}
          capa={c}
          tokens={escena.tokens}
          slug={slug}
          colorMarca={colorMarca}
          editando={c.id === editandoTexto}
        />
      ))}
    </>
  );
}

/** white-space y text-wrap como escena.py; lo comparte el textarea de edición. */
export function cortesDeTexto(capa: CapaTexto): CSSProperties {
  const wrap = capa.estilo.textWrap;
  return {
    whiteSpace: capa.campo ? (wrap === "nowrap" ? "nowrap" : "normal") : wrap === "nowrap" ? "pre" : "pre-line",
    textWrap: wrap === "balance" || wrap === "pretty" ? wrap : undefined,
  };
}

export const familiaCss = (familia: string) => `'${familia}', sans-serif`;
