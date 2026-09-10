"use client";

import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { ImageIcon } from "lucide-react";
import type { Capa } from "@/lib/layout";

export type Asa = "nw" | "ne" | "sw" | "se";

const ASAS: Asa[] = ["nw", "ne", "sw", "se"];

const VERTICAL: Record<string, CSSProperties["alignItems"]> = {
  arriba: "flex-start",
  centro: "center",
  abajo: "flex-end",
};

const HORIZONTAL: Record<string, CSSProperties["justifyContent"]> = {
  izq: "flex-start",
  centro: "center",
  der: "flex-end",
};

const TEXTO_ALINEADO: Record<string, CSSProperties["textAlign"]> = {
  izq: "left",
  centro: "center",
  der: "right",
};

/**
 * Un gesto de puntero que sobrevive a que el cursor se salga del elemento.
 * `setPointerCapture` es lo que lo hace posible: sin eso el arrastre se corta
 * en cuanto el puntero pisa otro elemento y se siente roto.
 *
 * El delta que se reporta es SIEMPRE el acumulado desde el inicio del gesto y
 * ya viene dividido entre la escala, o sea en píxeles reales del lienzo. Así
 * un `pointermove` perdido no descuadra nada: el padre recalcula desde la
 * posición de partida en vez de ir sumando incrementos.
 */
function iniciarGesto(
  e: ReactPointerEvent,
  escala: number,
  alMover: (dx: number, dy: number) => void,
  alSoltar: () => void
) {
  e.stopPropagation();
  const el = e.currentTarget as HTMLElement;
  el.setPointerCapture(e.pointerId);
  const inicio = { x: e.clientX, y: e.clientY };
  const mover = (ev: PointerEvent) =>
    alMover((ev.clientX - inicio.x) / escala, (ev.clientY - inicio.y) / escala);
  const soltar = () => {
    window.removeEventListener("pointermove", mover);
    window.removeEventListener("pointerup", soltar);
    window.removeEventListener("pointercancel", soltar);
    alSoltar();
  };
  window.addEventListener("pointermove", mover);
  window.addEventListener("pointerup", soltar);
  window.addEventListener("pointercancel", soltar);
}

export function CapaVista({
  capa,
  escala,
  seleccionada,
  colorMarca,
  stickers,
  onSeleccionar,
  onArrastrar,
  onRedimensionar,
  onSoltar,
}: {
  capa: Capa;
  escala: number;
  seleccionada: boolean;
  colorMarca: string;
  stickers: { nombre: string; url: string }[];
  onSeleccionar: () => void;
  onArrastrar: (dx: number, dy: number) => void;
  onRedimensionar: (asa: Asa, dx: number, dy: number) => void;
  onSoltar: () => void;
}) {
  // El color "marca" es un alias que resuelve el color de cada marca; el
  // backend hace lo mismo al renderizar.
  const color = (v: string | undefined) => (v === "marca" ? colorMarca : (v ?? "#111111"));

  // Todo lo que tiene que medir igual en pantalla sin importar el acercamiento
  // se divide entre la escala, porque vive dentro del contenedor escalado.
  const px = (n: number) => n / escala;

  const marco: CSSProperties = {
    position: "absolute",
    left: capa.x,
    top: capa.y,
    width: capa.w,
    height: capa.h,
    zIndex: capa.z,
    opacity: capa.opacidad,
    transform: `rotate(${capa.rot}deg)`,
    touchAction: "none",
    cursor: "move",
    outline: seleccionada ? `${px(2)}px solid #2563eb` : undefined,
    outlineOffset: 0,
  };

  return (
    <div
      style={marco}
      onPointerDown={(e) => {
        onSeleccionar();
        iniciarGesto(e, escala, onArrastrar, onSoltar);
      }}
    >
      <Contenido capa={capa} color={color} stickers={stickers} />

      {seleccionada &&
        ASAS.map((asa) => (
          <span
            key={asa}
            onPointerDown={(e) =>
              iniciarGesto(e, escala, (dx, dy) => onRedimensionar(asa, dx, dy), onSoltar)
            }
            style={{
              position: "absolute",
              width: px(12),
              height: px(12),
              top: asa[0] === "n" ? px(-6) : undefined,
              bottom: asa[0] === "s" ? px(-6) : undefined,
              left: asa[1] === "w" ? px(-6) : undefined,
              right: asa[1] === "e" ? px(-6) : undefined,
              background: "#2563eb",
              border: `${px(2)}px solid #ffffff`,
              borderRadius: px(3),
              cursor: `${asa}-resize`,
              touchAction: "none",
            }}
          />
        ))}
    </div>
  );
}

/** El dibujo de cada tipo de elemento. Es vista previa de estructura, no de contenido. */
function Contenido({
  capa,
  color,
  stickers,
}: {
  capa: Capa;
  color: (v: string | undefined) => string;
  stickers: { nombre: string; url: string }[];
}) {
  if (capa.tipo === "caja") {
    return (
      <div
        style={{
          width: "100%",
          height: "100%",
          background: color(capa.color),
          borderRadius: capa.radio ?? 0,
        }}
      />
    );
  }

  if (capa.tipo === "imagen") {
    const sticker = capa.archivo
      ? stickers.find((s) => s.nombre === capa.archivo)
      : undefined;
    if (sticker) {
      return (
        // eslint-disable-next-line @next/next/no-img-element -- archivo servido por la API vía rewrite
        <img
          src={`/api${sticker.url}`}
          alt=""
          draggable={false}
          style={{
            width: "100%",
            height: "100%",
            objectFit: capa.ajuste ?? "cover",
            borderRadius: capa.radio ?? 0,
            pointerEvents: "none",
          }}
        />
      );
    }
    // Sin archivo la imagen sale de un dato del diseño: aquí solo se marca el
    // hueco, porque el contenido real llega al generar el post.
    return (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 12,
          border: "4px dashed #9ca3af",
          borderRadius: capa.radio ?? 0,
          color: "#6b7280",
          background: "rgba(148,163,184,0.15)",
        }}
      >
        <ImageIcon style={{ width: 64, height: 64 }} strokeWidth={1.5} />
        <span style={{ fontSize: 32, fontWeight: 500 }}>Foto</span>
      </div>
    );
  }

  // Texto. Atado a un dato se dibuja el nombre del dato en gris: lo que se está
  // acomodando es el hueco, no la frase que va a caer ahí.
  const esDato = !!capa.campo;
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: VERTICAL[capa.vertical ?? "centro"] ?? "center",
        justifyContent: HORIZONTAL[capa.alinear ?? "centro"] ?? "center",
        overflow: "hidden",
      }}
    >
      <span
        style={{
          width: "100%",
          fontFamily: capa.fuente ? JSON.stringify(capa.fuente) : undefined,
          fontSize: capa.tam ?? 48,
          fontWeight: capa.peso ?? 400,
          color: esDato ? "#9ca3af" : color(capa.color),
          textAlign: TEXTO_ALINEADO[capa.alinear ?? "centro"] ?? "center",
          lineHeight: capa.interlinea ?? 1.2,
          textTransform: capa.mayusculas ? "uppercase" : undefined,
          whiteSpace: "pre-wrap",
          overflowWrap: "break-word",
        }}
      >
        {esDato ? `«${capa.campo}»` : (capa.texto ?? "")}
      </span>
    </div>
  );
}
