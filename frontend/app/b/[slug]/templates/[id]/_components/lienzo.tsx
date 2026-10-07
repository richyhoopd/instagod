"use client";

import { Maximize, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Moveable from "react-moveable";
import Selecto from "react-selecto";
import { Button } from "@/components/ui/button";
import { expandir } from "@/lib/edicion";
import { normalizarAngulo, ocultasEfectivas, type Escena, type Op } from "@/lib/escena";
import { alternar, encuadre, raicesSeleccionables, zoomEnPunto } from "@/lib/vista";
import { useEditor } from "@/stores/editor";
import { Escenario, fondoCss } from "./capa-vista";

type Props = { slug: string; colorMarca: string; ajustarAlCargar?: boolean };
type Gesto = { t?: number[]; w?: number; h?: number; rot?: number };
type Pan = { x: number; y: number };

const PAN_INICIAL: Pan = { x: 32, y: 32 };
const selector = (id: string) => `#marco .capa[data-id="${id}"]`;

// Moveable escribe directo en el DOM. Al soltar se regresa el nodo a lo que
// dice el store; el commit siguiente pinta la posición nueva.
function restaurar(escena: Escena, el: HTMLElement | SVGElement) {
  const c = escena.capas.find((x) => x.id === el.getAttribute("data-id"));
  if (!c) return;
  el.style.left = `${c.x}px`;
  el.style.top = `${c.y}px`;
  el.style.width = `${c.w}px`;
  el.style.height = `${c.h}px`;
  el.style.transform = `rotate(${c.rot}deg)`;
}

export function Lienzo({ slug, colorMarca, ajustarAlCargar = true }: Props) {
  const escena = useEditor((s) => s.escena);
  const seleccion = useEditor((s) => s.seleccion);
  const zoom = useEditor((s) => s.zoom);
  const editandoTexto = useEditor((s) => s.editandoTexto);

  const [marco, setMarco] = useState<HTMLDivElement | null>(null);
  const [pan, setPan] = useState<Pan>(PAN_INICIAL);
  const panRef = useRef<Pan>(PAN_INICIAL);
  const moveableRef = useRef<Moveable>(null);
  const gesto = useRef<Gesto | null>(null);

  const fijarPan = useCallback((p: Pan) => {
    panRef.current = p;
    setPan(p);
  }, []);

  const ajustar = useCallback(() => {
    const st = useEditor.getState();
    if (!marco || !st.escena) return;
    const r = marco.getBoundingClientRect();
    const v = encuadre({ w: r.width, h: r.height }, st.escena.lienzo);
    st.setZoom(v.zoom);
    fijarPan({ x: v.x, y: v.y });
  }, [marco, fijarPan]);

  // Ajusta al montar, al cambiar de formato y al cambiar el tamaño del marco.
  // El setState ocurre en el callback del observer, no en el cuerpo del efecto.
  const claveLienzo = escena ? `${escena.lienzo.w}x${escena.lienzo.h}` : null;
  useEffect(() => {
    if (!ajustarAlCargar || !marco || !claveLienzo) return;
    const ro = new ResizeObserver(() => ajustar());
    ro.observe(marco);
    return () => ro.disconnect();
  }, [ajustarAlCargar, marco, claveLienzo, ajustar]);

  // Rueda: con ctrl/cmd (o pellizco del trackpad) hace zoom en el cursor; sin, desplaza.
  useEffect(() => {
    if (!marco) return;
    const rueda = (ev: WheelEvent) => {
      ev.preventDefault();
      const st = useEditor.getState();
      if (ev.ctrlKey || ev.metaKey) {
        const r = marco.getBoundingClientRect();
        const v = zoomEnPunto(
          { zoom: st.zoom, ...panRef.current },
          st.zoom * Math.exp(-ev.deltaY / 300),
          ev.clientX - r.left,
          ev.clientY - r.top,
        );
        st.setZoom(v.zoom);
        fijarPan({ x: v.x, y: v.y });
      } else {
        fijarPan({ x: panRef.current.x - ev.deltaX, y: panRef.current.y - ev.deltaY });
      }
    };
    marco.addEventListener("wheel", rueda, { passive: false });
    return () => marco.removeEventListener("wheel", rueda);
  }, [marco, fijarPan]);

  const objetivos = useMemo(() => {
    if (!escena || editandoTexto) return [];
    const ocultas = ocultasEfectivas(escena);
    const m = new Map(escena.capas.map((c) => [c.id, c]));
    return expandir(escena, seleccion).filter((id) => !ocultas.has(id) && !m.get(id)?.bloqueada);
  }, [escena, seleccion, editandoTexto]);
  const unaHoja = objetivos.length === 1 && seleccion.length === 1 && seleccion[0] === objetivos[0];

  // La caja de Moveable se recalcula cuando cambia lo que hay debajo.
  useEffect(() => {
    moveableRef.current?.updateRect();
  }, [escena, zoom, pan]);

  const terminar = (targets: (HTMLElement | SVGElement)[]): Gesto | null => {
    const g = gesto.current;
    gesto.current = null;
    const e = useEditor.getState().escena;
    if (e) targets.forEach((el) => restaurar(e, el));
    return g;
  };

  const confirmarMovimiento = (g: Gesto | null) => {
    if (g?.t) useEditor.getState().mover(Math.round(g.t[0]), Math.round(g.t[1]));
  };

  if (!escena) return null;
  const { w: W, h: H } = escena.lienzo;

  return (
    <div className="relative h-full w-full">
      <div
        id="marco"
        ref={setMarco}
        className="relative h-full w-full overflow-hidden bg-muted"
        onDoubleClick={(ev) => {
          const el = (ev.target as Element).closest("#marco .capa");
          const id = el?.getAttribute("data-id");
          const c = escena.capas.find((x) => x.id === id);
          if (c?.tipo === "text" && !c.bloqueada) useEditor.getState().editarTexto(c.id);
        }}
      >
        <div
          data-testid="escenario"
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: W,
            height: H,
            overflow: "hidden",
            background: fondoCss(escena.lienzo.fondo, escena.tokens, colorMarca, slug),
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "0 0",
          }}
        >
          <Escenario escena={escena} slug={slug} colorMarca={colorMarca} editandoTexto={editandoTexto} />
        </div>

        <Moveable
          ref={moveableRef}
          target={objetivos.map(selector)}
          draggable
          resizable={unaHoja}
          rotatable={unaHoja}
          keepRatio={false}
          snappable={escena.guias?.iman ?? true}
          snapThreshold={6}
          elementGuidelines={escena.capas.filter((c) => !objetivos.includes(c.id)).map((c) => selector(c.id))}
          onDragStart={() => {
            gesto.current = null;
          }}
          onDrag={(e) => {
            e.target.style.transform = e.transform;
            gesto.current = { t: e.beforeTranslate };
          }}
          onDragEnd={(e) => confirmarMovimiento(terminar([e.target]))}
          onDragGroupStart={() => {
            gesto.current = null;
          }}
          onDragGroup={(e) => {
            e.events.forEach((ev) => {
              ev.target.style.transform = ev.transform;
            });
            gesto.current = { t: e.events[0]?.beforeTranslate };
          }}
          onDragGroupEnd={(e) => confirmarMovimiento(terminar(e.targets))}
          onResizeStart={() => {
            gesto.current = null;
          }}
          onResize={(e) => {
            e.target.style.width = `${e.width}px`;
            e.target.style.height = `${e.height}px`;
            e.target.style.transform = e.drag.transform;
            gesto.current = { t: e.drag.beforeTranslate, w: e.width, h: e.height };
          }}
          onResizeEnd={(e) => {
            const g = terminar([e.target]);
            const st = useEditor.getState();
            const c = st.escena?.capas.find((x) => x.id === e.target.getAttribute("data-id"));
            if (!g || g.w === undefined || g.h === undefined || !c) return;
            const t = g.t ?? [0, 0];
            const ops: Op[] = [
              { op: "set", capa: c.id, ruta: "x", valor: Math.round(c.x + t[0]) },
              { op: "set", capa: c.id, ruta: "y", valor: Math.round(c.y + t[1]) },
              { op: "set", capa: c.id, ruta: "w", valor: Math.max(1, Math.round(g.w)) },
              { op: "set", capa: c.id, ruta: "h", valor: Math.max(1, Math.round(g.h)) },
            ];
            st.aplicar(ops, "Redimensionar");
          }}
          onRotateStart={() => {
            gesto.current = null;
          }}
          onRotate={(e) => {
            e.target.style.transform = e.drag.transform;
            // ⚠️ En 0.56 `rotation` es el ángulo total del objetivo, no el delta.
            gesto.current = { rot: e.rotation };
          }}
          onRotateEnd={(e) => {
            const g = terminar([e.target]);
            const id = e.target.getAttribute("data-id");
            if (g?.rot === undefined || !id) return;
            useEditor
              .getState()
              .aplicar([{ op: "set", capa: id, ruta: "rot", valor: normalizarAngulo(Math.round(g.rot)) }], "Rotar");
          }}
        />
      </div>

      {marco && (
        <Selecto
          dragContainer={marco}
          selectableTargets={["#marco .capa"]}
          hitRate={0}
          selectByClick
          selectFromInside={false}
          onDragStart={(e) => {
            const t = e.inputEvent.target as Element;
            const st = useEditor.getState();
            if (!st.escena) return e.stop();
            if (t.closest("[data-editor-texto], [data-editor-barra]")) return e.stop();
            if (moveableRef.current?.isMoveableElement(t)) return e.stop();
            const id = t.closest("#marco .capa")?.getAttribute("data-id");
            const yaElegida = !!id && expandir(st.escena, st.seleccion).includes(id);
            if (yaElegida && !(e.inputEvent as MouseEvent).shiftKey) e.stop();
          }}
          onSelectEnd={(e) => {
            const st = useEditor.getState();
            if (!st.escena) return;
            const ids = e.selected.map((el) => el.getAttribute("data-id")!).filter(Boolean);
            const nuevos = raicesSeleccionables(st.escena, ids);
            const shift = (e.inputEvent as MouseEvent).shiftKey;
            st.seleccionar(shift ? alternar(st.seleccion, nuevos) : nuevos);
            if (e.isDragStart && !shift && nuevos.length > 0) {
              e.inputEvent.preventDefault();
              moveableRef.current?.waitToChangeTarget().then(() => moveableRef.current?.dragStart(e.inputEvent));
            }
          }}
        />
      )}

      <div className="absolute bottom-3 left-3 flex items-center gap-1 rounded-md border bg-background p-1 shadow-sm">
        <Button variant="ghost" size="icon-sm" aria-label="Alejar" onClick={() => useEditor.getState().setZoom(zoom / 1.25)}>
          <ZoomOut />
        </Button>
        <span className="w-12 text-center text-xs tabular-nums">{Math.round(zoom * 100)}%</span>
        <Button variant="ghost" size="icon-sm" aria-label="Acercar" onClick={() => useEditor.getState().setZoom(zoom * 1.25)}>
          <ZoomIn />
        </Button>
        <Button variant="ghost" size="icon-sm" aria-label="Ajustar" onClick={ajustar}>
          <Maximize />
        </Button>
      </div>
    </div>
  );
}
