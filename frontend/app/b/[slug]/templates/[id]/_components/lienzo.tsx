"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { dentro, imantar, LIENZO, type Capa, type Layout } from "@/lib/layout";
import { CapaVista, type Asa } from "./capa-vista";

// Qué bordes mueve cada asa. El asa arrastra siempre su propia esquina y deja
// quieta la opuesta.
const REDIM: Record<Asa, (c: Capa, dx: number, dy: number) => Partial<Capa>> = {
  se: (c, dx, dy) => ({ w: c.w + dx, h: c.h + dy }),
  sw: (c, dx, dy) => ({ x: c.x + dx, w: c.w - dx, h: c.h + dy }),
  ne: (c, dx, dy) => ({ y: c.y + dy, w: c.w + dx, h: c.h - dy }),
  nw: (c, dx, dy) => ({ x: c.x + dx, y: c.y + dy, w: c.w - dx, h: c.h - dy }),
};

const MINIMO = 8;

export function Lienzo({
  layout,
  aspecto,
  seleccion,
  slug,
  colorMarca,
  fuentes,
  stickers,
  onSeleccionar,
  onCambiar,
  onBorrar,
  rejilla,
}: {
  layout: Layout;
  aspecto: string;
  seleccion: string | null;
  slug: string;
  colorMarca: string;
  fuentes: { familia: string; propia: boolean }[];
  stickers: { nombre: string; url: string }[];
  onSeleccionar: (id: string | null) => void;
  onCambiar: (capa: Capa) => void;
  onBorrar: (id: string) => void;
  rejilla: boolean;
}) {
  const { ancho, alto } = LIENZO[aspecto] ?? LIENZO["4:5"];

  // El lienzo real mide 1080 px de ancho y en pantalla cabe en bastante menos.
  // Todo se dibuja en coordenadas reales y se encoge con un `scale`, así lo que
  // se guarda no depende del monitor de quien lo acomodó.
  const ref = useRef<HTMLDivElement>(null);
  const [escala, setEscala] = useState(0.4);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) =>
      // Un ancestro oculto reporta ancho 0 y una escala 0 vuelve infinitos
      // los deltas y las asas. El piso mantiene el lienzo utilizable.
      setEscala(Math.max(0.05, e.contentRect.width / ancho))
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, [ancho]);

  // Posición del elemento al empezar el gesto. El arrastre reporta el delta
  // acumulado, así que hay que recordar de dónde salió.
  const partida = useRef<Capa | null>(null);

  // Con Alt se ignora el imán y el movimiento es fino. Es la convención de
  // todos los editores; se lee de la ventana porque el gesto ya está en curso
  // cuando la tecla se aprieta.
  const alt = useRef(false);
  useEffect(() => {
    const marcar = (e: KeyboardEvent) => {
      alt.current = e.altKey;
    };
    // Al salir de la ventana con Alt apretado no llega el `keyup` y el imán
    // se quedaría apagado en silencio.
    const soltar = () => {
      alt.current = false;
    };
    window.addEventListener("keydown", marcar);
    window.addEventListener("keyup", marcar);
    window.addEventListener("blur", soltar);
    return () => {
      window.removeEventListener("keydown", marcar);
      window.removeEventListener("keyup", marcar);
      window.removeEventListener("blur", soltar);
    };
  }, []);

  const paso = {
    x: ancho / Math.max(1, layout.guias.cols),
    y: alto / Math.max(1, layout.guias.filas),
  };

  // Las tipografías propias de la marca solo se ven bien si el navegador las
  // baja; el endpoint las sirve por familia y se autentica con la cookie.
  const css = useMemo(
    () =>
      fuentes
        .map(
          (f) =>
            `@font-face{font-family:${JSON.stringify(f.familia)};` +
            `src:url('/api/brands/${slug}/files/fonts/${encodeURIComponent(f.familia)}');` +
            `font-display:block;}`
        )
        .join("\n"),
    [fuentes, slug]
  );

  const capaSel = layout.capas.find((c) => c.id === seleccion) ?? null;

  function arrastrar(capa: Capa, dx: number, dy: number) {
    const base = (partida.current ??= capa);
    const libre = alt.current;
    onCambiar(
      dentro(
        {
          ...base,
          x: libre ? Math.round(base.x + dx) : imantar(base.x + dx, paso.x, layout.guias.iman),
          y: libre ? Math.round(base.y + dy) : imantar(base.y + dy, paso.y, layout.guias.iman),
        },
        ancho,
        alto
      )
    );
  }

  function redimensionar(capa: Capa, asa: Asa, dx: number, dy: number) {
    const base = (partida.current ??= capa);
    // Si el tirón pasa de largo el borde opuesto, acotar `w` y `h` después no
    // basta: `x`/`y` ya se movieron y el elemento salta más allá del borde que
    // debía quedarse quieto. Se acota el delta antes de repartirlo.
    const mueveIzq = asa === "sw" || asa === "nw";
    const mueveArr = asa === "ne" || asa === "nw";
    const ddx = mueveIzq ? Math.min(dx, base.w - MINIMO) : Math.max(dx, MINIMO - base.w);
    const ddy = mueveArr ? Math.min(dy, base.h - MINIMO) : Math.max(dy, MINIMO - base.h);
    const cambio = REDIM[asa](base, ddx, ddy);
    onCambiar(
      dentro(
        {
          ...base,
          ...cambio,
          w: Math.max(MINIMO, cambio.w ?? base.w),
          h: Math.max(MINIMO, cambio.h ?? base.h),
        },
        ancho,
        alto
      )
    );
  }

  function teclado(e: React.KeyboardEvent) {
    if (!capaSel) return;
    if (e.key === "Escape") {
      onSeleccionar(null);
      return;
    }
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      onBorrar(capaSel.id);
      return;
    }
    const salto = e.shiftKey ? 10 : 1;
    const mueve: Record<string, [number, number]> = {
      ArrowLeft: [-salto, 0],
      ArrowRight: [salto, 0],
      ArrowUp: [0, -salto],
      ArrowDown: [0, salto],
    };
    const d = mueve[e.key];
    if (!d) return;
    e.preventDefault();
    onCambiar(dentro({ ...capaSel, x: capaSel.x + d[0], y: capaSel.y + d[1] }, ancho, alto));
  }

  return (
    <div
      ref={ref}
      tabIndex={0}
      onKeyDown={teclado}
      onPointerDown={() => onSeleccionar(null)}
      style={{ height: alto * escala }}
      className="relative w-full overflow-hidden rounded-lg border outline-none"
    >
      <style>{css}</style>
      <div
        style={{
          width: ancho,
          height: alto,
          transform: `scale(${escala})`,
          transformOrigin: "top left",
          // Sin esto, arrastrar un texto pinta la selección azul del navegador
          // encima del editor y dispara el arrastre nativo de texto.
          userSelect: "none",
          background: layout.lienzo.fondo === "marca" ? colorMarca : layout.lienzo.fondo,
          position: "relative",
        }}
      >
        {rejilla && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              pointerEvents: "none",
              // La línea se engorda al dividirla entre la escala: dibujada en
              // coordenadas reales, 1 px se encogería hasta desaparecer.
              backgroundImage:
                `linear-gradient(to right, rgba(15,23,42,0.16) ${1 / escala}px, transparent ${1 / escala}px),` +
                `linear-gradient(to bottom, rgba(15,23,42,0.16) ${1 / escala}px, transparent ${1 / escala}px)`,
              backgroundSize: `${paso.x}px ${paso.y}px`,
            }}
          />
        )}

        {layout.capas.map((capa) => (
          <CapaVista
            key={capa.id}
            capa={capa}
            escala={escala}
            seleccionada={capa.id === seleccion}
            colorMarca={colorMarca}
            stickers={stickers}
            onSeleccionar={() => onSeleccionar(capa.id)}
            onArrastrar={(dx, dy) => arrastrar(capa, dx, dy)}
            onRedimensionar={(asa, dx, dy) => redimensionar(capa, asa, dx, dy)}
            onSoltar={() => {
              partida.current = null;
            }}
          />
        ))}
      </div>
    </div>
  );
}
